"""TwitterAPI.io Fetch client (tasks.md T034, contracts/pipeline-stages.md § Fetch,
contracts/external-integrations.md § X Data Read Provider).

Per-topic error record on persistent failure — never raises out to the
caller, so one topic's fetch failure never halts Fetch for other topics in
the same run (FR-002). Reports read costs to the cost tracker (T022).
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import requests

from src.pipeline.query_builder import build_search_query
from src.utils.cost_tracker import record_twitterapi_io_read
from src.utils.retry import retry_with_backoff

BASE_URL = "https://api.twitterapi.io"
SEARCH_PATH = "/twitter/tweet/advanced_search"

DEFAULT_LOOKBACK = timedelta(days=1)

# TEMPORARY: lowered from plan.md Scale/Scope's ~200 posts/topic/run while the
# TwitterAPI.io account is on the free tier (0.2 QPS = max 1 request/5s) —
# fetching 200 posts a page at a time at that pace can take several minutes
# per topic. Bump this back up to ~200 once the account is on a paid tier
# with a real QPS budget.
MAX_POSTS_PER_RUN = 20

# Minimum spacing between successive page requests to the same topic's
# search, matching TwitterAPI.io's free-tier 0.2 QPS cap (max 1 request per
# 5 seconds). Applied proactively between *successful* page fetches in
# `fetch_topic_posts`'s pagination loop — without it, each page after the
# first fires immediately and gets 429'd, relying entirely on `_fetch_page`'s
# retry-after-failure backoff to recover instead of avoiding the 429 in the
# first place. Raise/lower alongside `_fetch_page`'s retry `base_delay_seconds`
# if the account's rate limit changes.
INTER_PAGE_DELAY_SECONDS = 5.0

_TWITTER_DATE_FORMAT = "%a %b %d %H:%M:%S %z %Y"  # e.g. "Tue Dec 10 07:00:30 +0000 2024"


class FetchErrorKind(enum.StrEnum):
    RATE_LIMITED = "rate_limited"
    ERROR = "error"


class FetchAPIError(Exception):
    """Raised internally on a non-2xx TwitterAPI.io response.

    Retried by `_fetch_page`'s retry-with-backoff wrapper; if it still
    persists, `fetch_topic_posts` converts it to a `FetchResult.error`
    instead of letting it propagate (FR-002).
    """

    def __init__(self, message: str, *, rate_limited: bool = False) -> None:
        super().__init__(message)
        self.rate_limited = rate_limited


@dataclass(frozen=True)
class AuthorMetadata:
    """Fields Filter Tier 1 scores directly (contracts/external-integrations.md)."""

    account_age_days: float
    followers_count: int
    following_count: int
    post_frequency: float  # approx posts/day, derived from statusesCount / account age


@dataclass(frozen=True)
class EngagementMetrics:
    """Post-level engagement counts, persisted on `SourcePost` for
    auditability alongside `filter_outcome` (same pattern as `AuthorMetadata`).

    All fields are optional: TwitterAPI.io's search response (this module)
    doesn't expose engagement counts, so `_parse_tweet` below always builds
    this with every field `None` rather than guessing at unverified field
    names. Only `fetch_twitterapis_com.py`'s response currently populates
    real values.
    """

    like_count: int | None
    retweet_count: int | None
    reply_count: int | None
    quote_count: int | None
    view_count: int | None


_NO_ENGAGEMENT_METRICS = EngagementMetrics(
    like_count=None, retweet_count=None, reply_count=None, quote_count=None, view_count=None
)


@dataclass(frozen=True)
class RawPost:
    x_post_id: str
    author_handle: str
    text: str
    posted_at: datetime
    author_metadata: AuthorMetadata
    engagement_metrics: EngagementMetrics = _NO_ENGAGEMENT_METRICS


@dataclass(frozen=True)
class FetchError:
    kind: FetchErrorKind
    detail: str


@dataclass(frozen=True)
class FetchResult:
    posts: list[RawPost] | None
    error: FetchError | None

    @property
    def ok(self) -> bool:
        return self.error is None


def _parse_twitter_date(value: str) -> datetime:
    return datetime.strptime(value, _TWITTER_DATE_FORMAT)


def _parse_tweet(raw: dict) -> RawPost:
    author = raw["author"]
    posted_at = _parse_twitter_date(raw["createdAt"])
    account_created_at = _parse_twitter_date(author["createdAt"])
    account_age_days = max((datetime.now(UTC) - account_created_at).total_seconds() / 86400, 0.0)
    statuses_count = author.get("statusesCount", 0)
    post_frequency = (
        statuses_count / account_age_days if account_age_days > 0 else float(statuses_count)
    )
    return RawPost(
        x_post_id=str(raw["id"]),
        author_handle=author["userName"],
        text=raw["text"],
        posted_at=posted_at,
        author_metadata=AuthorMetadata(
            account_age_days=account_age_days,
            followers_count=author.get("followers", 0),
            following_count=author.get("following", 0),
            post_frequency=post_frequency,
        ),
    )


# base_delay_seconds=5.0 is tuned for TwitterAPI.io's free-tier rate limit
# (0.2 QPS = max 1 request per 5 seconds) — retrying any faster just hits the
# same limit again immediately. With the default backoff_factor=2.0 this
# waits ~5s then ~10s between the 3 attempts. If the account is upgraded to a
# paid tier with a higher QPS cap, this can come back down.
@retry_with_backoff(
    max_attempts=3,
    base_delay_seconds=5.0,
    exceptions=(requests.RequestException, FetchAPIError),
)
def _fetch_page(api_key: str, query: str, cursor: str, *, session: requests.Session) -> dict:
    response = session.get(
        f"{BASE_URL}{SEARCH_PATH}",
        params={"query": query, "queryType": "Latest", "cursor": cursor},
        headers={"X-API-Key": api_key},
        timeout=30,
    )
    if response.status_code == 429:
        raise FetchAPIError("TwitterAPI.io rate limit exceeded", rate_limited=True)
    if not response.ok:
        try:
            body = response.json()
            message = body.get("message", response.text)
        except ValueError:
            message = response.text
        raise FetchAPIError(f"TwitterAPI.io error {response.status_code}: {message}")
    return response.json()


def fetch_topic_posts(
    topic_name: str,
    x_handles: list[str],
    *,
    api_key: str,
    since: datetime | None = None,
    until: datetime | None = None,
    max_posts: int = MAX_POSTS_PER_RUN,
    session: requests.Session | None = None,
) -> FetchResult:
    """Fetch raw posts for one topic within [since, until).

    Never raises on a persistent TwitterAPI.io failure — returns a
    `FetchResult` carrying a `FetchError` instead, so one topic's fetch
    failure never halts Fetch for other topics in the same run (FR-002).
    """
    until = until or datetime.now(UTC)
    since = since or (until - DEFAULT_LOOKBACK)
    session = session or requests.Session()
    query = build_search_query(topic_name, x_handles, since, until)

    posts: list[RawPost] = []
    cursor = ""
    is_first_page = True
    try:
        while len(posts) < max_posts:
            if not is_first_page:
                # Pace successive page requests to the free-tier 0.2 QPS cap
                # proactively, rather than firing immediately and relying on
                # _fetch_page's retry-after-failure backoff to recover from
                # the resulting 429.
                time.sleep(INTER_PAGE_DELAY_SECONDS)
            is_first_page = False

            page = _fetch_page(api_key, query, cursor, session=session)
            tweets = page.get("tweets", [])
            posts.extend(_parse_tweet(tweet) for tweet in tweets)
            if not page.get("has_next_page") or not tweets:
                break
            cursor = page.get("next_cursor", "")
    except FetchAPIError as exc:
        kind = FetchErrorKind.RATE_LIMITED if exc.rate_limited else FetchErrorKind.ERROR
        return FetchResult(posts=None, error=FetchError(kind=kind, detail=str(exc)))
    except requests.RequestException as exc:
        return FetchResult(posts=None, error=FetchError(kind=FetchErrorKind.ERROR, detail=str(exc)))

    posts = posts[:max_posts]
    record_twitterapi_io_read(len(posts))
    return FetchResult(posts=posts, error=None)
