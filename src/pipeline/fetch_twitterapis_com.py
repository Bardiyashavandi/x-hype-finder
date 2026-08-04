"""TwitterAPIs.com Fetch client — the default Fetch provider
(src/pipeline/fetch_provider.py), ahead of the original TwitterAPI.io client
(src/pipeline/fetch.py).

Selected via `FETCH_PROVIDER=twitterapis_com` (src/pipeline/fetch_provider.py).
Mirrors fetch.py's shape (`fetch_topic_posts` returning the same `FetchResult`/
`RawPost`/`FetchError` types, never raising out to the caller) and shares its
advanced-search query construction via `src/pipeline/query_builder.py`
(confirmed identical `since_time:`/`until_time:` epoch operators via
docs.twitterapis.com/blogs/twitter-advanced-search-operators), but differs
where the providers genuinely differ:

- Auth is `Authorization: Bearer <key>`, not TwitterAPI.io's `X-API-Key`.
- The response embeds full author metadata (followers_count, following_count,
  tweet_count, created_at) directly on each tweet's `author`, confirmed via a
  live test call (2026-07-31) after docs.twitterapis.com's own examples
  turned out to be trimmed/incomplete on this point.
- Pagination cursor field is `next_cursor` + a `has_more` boolean (vs.
  TwitterAPI.io's `has_next_page`).
- No fixed QPS cap (pay-per-call pricing; docs.twitterapis.com's rate-limits
  guide describes 429s only as occasional burst protection, not a steady-state
  budget), so unlike fetch.py's INTER_PAGE_DELAY_SECONDS=5.0 tuned to
  TwitterAPI.io's 0.2 QPS free tier, this client does no proactive
  between-page pacing at all — only retry-with-backoff reacting to an actual
  429.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import requests

from src.pipeline.fetch import AuthorMetadata, FetchError, FetchErrorKind, FetchResult, RawPost
from src.pipeline.query_builder import build_search_query
from src.utils.cost_tracker import record_twitterapis_com_read
from src.utils.retry import retry_with_backoff

BASE_URL = "https://api.twitterapis.com/twitter"
SEARCH_PATH = "/tweet/advanced_search"

DEFAULT_LOOKBACK = timedelta(days=1)

# Same ~200 posts/topic/run target as fetch.py's plan.md Scale/Scope — no
# QPS-driven reason to lower it the way fetch.py's MAX_POSTS_PER_RUN was
# temporarily lowered for TwitterAPI.io's free tier.
MAX_POSTS_PER_RUN = 200

# No proactive inter-page delay: docs.twitterapis.com states there is no
# platform-level QPS cap (pay-per-call), so pacing every page the way fetch.py
# does for TwitterAPI.io's 0.2 QPS would just add latency for no reason.
# _fetch_page's retry-with-backoff still reacts to an actual 429 if one shows
# up on a burst.
INTER_PAGE_DELAY_SECONDS = 0.0

_TWITTER_DATE_FORMAT = "%a %b %d %H:%M:%S %z %Y"  # e.g. "Mon Jul 27 15:26:44 +0000 2026"


class FetchAPIError(Exception):
    """Raised internally on a non-2xx TwitterAPIs.com response.

    Retried by `_fetch_page`'s retry-with-backoff wrapper; if it still
    persists, `fetch_topic_posts` converts it to a `FetchResult.error`
    instead of letting it propagate (FR-002), matching fetch.py.
    """

    def __init__(self, message: str, *, rate_limited: bool = False) -> None:
        super().__init__(message)
        self.rate_limited = rate_limited


def _parse_twitter_date(value: str) -> datetime:
    return datetime.strptime(value, _TWITTER_DATE_FORMAT)


def _parse_tweet(raw: dict) -> RawPost:
    author = raw["author"]
    posted_at = _parse_twitter_date(raw["created_at"])
    account_created_at = _parse_twitter_date(author["created_at"])
    account_age_days = max((datetime.now(UTC) - account_created_at).total_seconds() / 86400, 0.0)
    tweet_count = author.get("tweet_count", 0)
    post_frequency = tweet_count / account_age_days if account_age_days > 0 else float(tweet_count)
    return RawPost(
        x_post_id=str(raw["id"]),
        author_handle=author["username"],
        text=raw["text"],
        posted_at=posted_at,
        author_metadata=AuthorMetadata(
            account_age_days=account_age_days,
            followers_count=author.get("followers_count", 0),
            following_count=author.get("following_count", 0),
            post_frequency=post_frequency,
        ),
    )


@retry_with_backoff(
    max_attempts=3,
    base_delay_seconds=1.0,
    exceptions=(requests.RequestException, FetchAPIError),
)
def _fetch_page(api_key: str, query: str, cursor: str, *, session: requests.Session) -> dict:
    response = session.get(
        f"{BASE_URL}{SEARCH_PATH}",
        params={"query": query, "product": "Latest", "cursor": cursor},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    if response.status_code == 429:
        raise FetchAPIError("TwitterAPIs.com rate limit exceeded", rate_limited=True)
    if not response.ok:
        try:
            body = response.json()
            message = body.get("message", response.text)
        except ValueError:
            message = response.text
        raise FetchAPIError(f"TwitterAPIs.com error {response.status_code}: {message}")
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

    Never raises on a persistent TwitterAPIs.com failure — returns a
    `FetchResult` carrying a `FetchError` instead, so one topic's fetch
    failure never halts Fetch for other topics in the same run (FR-002),
    matching fetch.py.
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
            if not is_first_page and INTER_PAGE_DELAY_SECONDS:
                time.sleep(INTER_PAGE_DELAY_SECONDS)
            is_first_page = False

            page = _fetch_page(api_key, query, cursor, session=session)
            tweets = page.get("tweets", [])
            posts.extend(_parse_tweet(tweet) for tweet in tweets)
            if not page.get("has_more") or not tweets:
                break
            cursor = page.get("next_cursor", "")
    except FetchAPIError as exc:
        kind = FetchErrorKind.RATE_LIMITED if exc.rate_limited else FetchErrorKind.ERROR
        return FetchResult(posts=None, error=FetchError(kind=kind, detail=str(exc)))
    except requests.RequestException as exc:
        return FetchResult(posts=None, error=FetchError(kind=FetchErrorKind.ERROR, detail=str(exc)))

    posts = posts[:max_posts]
    record_twitterapis_com_read(len(posts))
    return FetchResult(posts=posts, error=None)
