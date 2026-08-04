"""Contract test for the TwitterAPIs.com Fetch client
(src/pipeline/fetch_twitterapis_com.py, contracts/pipeline-stages.md § Fetch,
contracts/external-integrations.md § X Data Read Provider).

Verifies request shape (bearer auth header, query/pagination params), response
parsing into `RawPost` with full author metadata, retry-then-error behavior on
persistent failure, and the no-proactive-pacing behavior that distinguishes
this provider from TwitterAPI.io (tests/contract/test_twitterapi_io.py) — all
against a mocked `requests.Session`, never a live network call. Field names
and the full-author-metadata-on-search-response shape are taken from a live
test call made and inspected manually on 2026-07-31 (docs.twitterapis.com's
own examples were trimmed and did not show these fields).
"""

import time
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
import requests

from src.pipeline import fetch_twitterapis_com as fetch_module
from src.pipeline.fetch import FetchErrorKind
from src.pipeline.fetch_twitterapis_com import fetch_topic_posts

API_KEY = "test-key"


@pytest.fixture(autouse=True)
def _fast_retry_sleep(monkeypatch):
    """Skip real sleeping between retries. `retry_with_backoff` resolves
    `time.sleep` fresh on every call (src/utils/retry.py), so patching it
    globally here is sufficient even though `_fetch_page` was decorated once
    at module-import time."""
    monkeypatch.setattr(time, "sleep", lambda seconds: None)


def _author(
    *,
    username="naval",
    followers_count=3753032,
    following_count=0,
    tweet_count=27117,
    created_at="Thu Feb 01 23:05:04 +0000 2007",
) -> dict:
    return {
        "id": "745273",
        "username": username,
        "name": "Naval",
        "followers_count": followers_count,
        "following_count": following_count,
        "tweet_count": tweet_count,
        "created_at": created_at,
    }


def _tweet(
    tweet_id: str,
    text: str,
    *,
    created_at="Mon Jul 27 15:26:44 +0000 2026",
    author: dict | None = None,
    reply_count=3,
    retweet_count=7,
    favorite_count=42,
    quote_count=2,
    bookmark_count=5,
    view_count=1000,
) -> dict:
    return {
        "id": tweet_id,
        "text": text,
        "created_at": created_at,
        "author": author or _author(),
        "reply_count": reply_count,
        "retweet_count": retweet_count,
        "favorite_count": favorite_count,
        "quote_count": quote_count,
        "bookmark_count": bookmark_count,  # not persisted — no SourcePost column yet
        "view_count": view_count,
    }


def _response(status_code=200, json_body=None, text_body=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.json.return_value = json_body or {}
    resp.text = text_body
    return resp


def test_request_shape_includes_bearer_auth_header_and_query_params():
    session = MagicMock()
    session.get.return_value = _response(200, {"tweets": [], "has_more": False, "next_cursor": ""})

    since = datetime(2026, 7, 1, tzinfo=UTC)
    until = datetime(2026, 7, 22, tzinfo=UTC)
    fetch_topic_posts("AAPL", ["cnbc"], api_key=API_KEY, since=since, until=until, session=session)

    session.get.assert_called_once()
    args, kwargs = session.get.call_args
    assert args[0] == f"{fetch_module.BASE_URL}{fetch_module.SEARCH_PATH}"
    assert kwargs["headers"] == {"Authorization": f"Bearer {API_KEY}"}
    assert kwargs["params"]["product"] == "Latest"
    assert kwargs["params"]["cursor"] == ""
    query = kwargs["params"]["query"]
    assert '"AAPL"' in query
    assert "from:cnbc" in query
    assert f"since_time:{int(since.timestamp())}" in query
    assert f"until_time:{int(until.timestamp())}" in query


def test_successful_response_parses_into_raw_posts_with_full_author_metadata():
    session = MagicMock()
    session.get.return_value = _response(
        200,
        {
            "tweets": [_tweet("123", "Hello world")],
            "has_more": False,
            "next_cursor": "",
        },
    )

    result = fetch_topic_posts("AAPL", [], api_key=API_KEY, session=session)

    assert result.ok
    assert len(result.posts) == 1
    post = result.posts[0]
    assert post.x_post_id == "123"
    assert post.author_handle == "naval"
    assert post.text == "Hello world"
    assert post.author_metadata.followers_count == 3753032
    assert post.author_metadata.following_count == 0
    assert post.author_metadata.account_age_days > 0
    assert post.author_metadata.post_frequency > 0


def test_successful_response_parses_into_raw_posts_with_engagement_metrics():
    session = MagicMock()
    session.get.return_value = _response(
        200,
        {
            "tweets": [
                _tweet(
                    "123",
                    "Hello world",
                    reply_count=3,
                    retweet_count=7,
                    favorite_count=42,
                    quote_count=2,
                    bookmark_count=5,
                    view_count=1000,
                )
            ],
            "has_more": False,
            "next_cursor": "",
        },
    )

    result = fetch_topic_posts("AAPL", [], api_key=API_KEY, session=session)

    assert result.ok
    engagement = result.posts[0].engagement_metrics
    # X's classic "favorite_count" naming is the like count.
    assert engagement.like_count == 42
    assert engagement.retweet_count == 7
    assert engagement.reply_count == 3
    assert engagement.quote_count == 2
    assert engagement.view_count == 1000


def test_pagination_follows_cursor_until_has_more_is_false():
    session = MagicMock()
    session.get.side_effect = [
        _response(
            200,
            {
                "tweets": [_tweet("1", "first")],
                "has_more": True,
                "next_cursor": "page-2",
            },
        ),
        _response(
            200,
            {
                "tweets": [_tweet("2", "second")],
                "has_more": False,
                "next_cursor": "",
            },
        ),
    ]

    result = fetch_topic_posts("AAPL", [], api_key=API_KEY, session=session)

    assert result.ok
    assert [p.x_post_id for p in result.posts] == ["1", "2"]
    assert session.get.call_count == 2
    second_call_params = session.get.call_args_list[1].kwargs["params"]
    assert second_call_params["cursor"] == "page-2"


def test_no_proactive_delay_between_page_requests(monkeypatch):
    """Unlike fetch.py's TwitterAPI.io client (paced to its 0.2 QPS free
    tier), this provider has no fixed QPS cap, so successive pages should
    fire back-to-back with no proactive `time.sleep` between them."""
    sleep_calls = []
    monkeypatch.setattr(time, "sleep", lambda seconds: sleep_calls.append(seconds))
    session = MagicMock()
    session.get.side_effect = [
        _response(200, {"tweets": [_tweet("1", "first")], "has_more": True, "next_cursor": "p2"}),
        _response(200, {"tweets": [_tweet("2", "second")], "has_more": False, "next_cursor": ""}),
    ]

    result = fetch_topic_posts("AAPL", [], api_key=API_KEY, session=session)

    assert result.ok
    assert sleep_calls == []


def test_max_posts_caps_results_and_stops_paging():
    session = MagicMock()
    session.get.return_value = _response(
        200,
        {
            "tweets": [_tweet(str(i), f"post {i}") for i in range(20)],
            "has_more": True,
            "next_cursor": "next",
        },
    )

    result = fetch_topic_posts("AAPL", [], api_key=API_KEY, max_posts=5, session=session)

    assert result.ok
    assert len(result.posts) == 5


def test_persistent_error_returns_fetch_error_instead_of_raising():
    session = MagicMock()
    session.get.side_effect = requests.ConnectionError("boom")

    result = fetch_topic_posts("AAPL", [], api_key=API_KEY, session=session)

    assert not result.ok
    assert result.posts is None
    assert result.error.kind == FetchErrorKind.ERROR
    # Retried up to max_attempts (3) before giving up.
    assert session.get.call_count == 3


def test_persistent_rate_limit_is_reported_as_rate_limited_kind():
    session = MagicMock()
    session.get.return_value = _response(429, {}, "rate limited")

    result = fetch_topic_posts("AAPL", [], api_key=API_KEY, session=session)

    assert not result.ok
    assert result.error.kind == FetchErrorKind.RATE_LIMITED
    assert session.get.call_count == 3


def test_transient_error_then_success_does_not_surface_as_error():
    session = MagicMock()
    session.get.side_effect = [
        requests.ConnectionError("transient"),
        _response(200, {"tweets": [], "has_more": False, "next_cursor": ""}),
    ]

    result = fetch_topic_posts("AAPL", [], api_key=API_KEY, session=session)

    assert result.ok
    assert result.posts == []
    assert session.get.call_count == 2


def test_successful_fetch_records_cost(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        fetch_module, "record_twitterapis_com_read", lambda count: recorded.append(count)
    )
    session = MagicMock()
    session.get.return_value = _response(
        200,
        {
            "tweets": [_tweet("1", "a"), _tweet("2", "b")],
            "has_more": False,
            "next_cursor": "",
        },
    )

    result = fetch_topic_posts("AAPL", [], api_key=API_KEY, session=session)

    assert result.ok
    assert recorded == [2]


@pytest.mark.parametrize("status_code", [400, 500])
def test_non_2xx_error_body_message_is_captured_in_detail(status_code):
    session = MagicMock()
    session.get.return_value = _response(
        status_code, {"error": "bad_request", "message": "something went wrong"}
    )

    result = fetch_topic_posts("AAPL", [], api_key=API_KEY, session=session)

    assert not result.ok
    assert "something went wrong" in result.error.detail
