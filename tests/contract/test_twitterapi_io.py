"""Contract test for the TwitterAPI.io Fetch client (tasks.md T028,
contracts/external-integrations.md § X Data Read Provider).

Verifies request shape (auth header, query/pagination params), response
parsing into `RawPost`, and retry-then-error behavior on persistent failure —
all against a mocked `requests.Session`, never a live network call.
"""

import time
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
import requests

from src.pipeline import fetch as fetch_module
from src.pipeline.fetch import FetchErrorKind, fetch_topic_posts

API_KEY = "test-key"


@pytest.fixture(autouse=True)
def _fast_retry_sleep(monkeypatch):
    """Skip real sleeping between retries. fetch.py's backoff now waits
    ~5s/~10s to respect TwitterAPI.io's free-tier rate limit (0.2 QPS) — real
    enough for production, far too slow for a test that exercises retry
    exhaustion. `retry_with_backoff` resolves `time.sleep` fresh on every
    call (src/utils/retry.py), so patching it globally here is sufficient
    even though `_fetch_page` was decorated once at module-import time."""
    monkeypatch.setattr(time, "sleep", lambda seconds: None)


def _tweet(
    tweet_id: str,
    text: str,
    *,
    author="alice",
    followers=1000,
    following=200,
    statuses=500,
    account_created="Mon Jan 01 00:00:00 +0000 2024",
    created_at="Tue Dec 10 07:00:30 +0000 2024",
) -> dict:
    return {
        "id": tweet_id,
        "text": text,
        "createdAt": created_at,
        "author": {
            "userName": author,
            "followers": followers,
            "following": following,
            "createdAt": account_created,
            "statusesCount": statuses,
        },
    }


def _response(status_code=200, json_body=None, text_body=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.json.return_value = json_body or {}
    resp.text = text_body
    return resp


def test_request_shape_includes_auth_header_and_query_params():
    session = MagicMock()
    session.get.return_value = _response(
        200, {"tweets": [], "has_next_page": False, "next_cursor": ""}
    )

    since = datetime(2026, 7, 1, tzinfo=UTC)
    until = datetime(2026, 7, 22, tzinfo=UTC)
    fetch_topic_posts("AAPL", ["cnbc"], api_key=API_KEY, since=since, until=until, session=session)

    session.get.assert_called_once()
    args, kwargs = session.get.call_args
    assert args[0] == f"{fetch_module.BASE_URL}{fetch_module.SEARCH_PATH}"
    assert kwargs["headers"] == {"X-API-Key": API_KEY}
    assert kwargs["params"]["queryType"] == "Latest"
    assert kwargs["params"]["cursor"] == ""
    query = kwargs["params"]["query"]
    assert '"AAPL"' in query
    assert "from:cnbc" in query
    assert f"since_time:{int(since.timestamp())}" in query
    assert f"until_time:{int(until.timestamp())}" in query


def test_successful_response_parses_into_raw_posts_with_author_metadata():
    session = MagicMock()
    session.get.return_value = _response(
        200,
        {
            "tweets": [_tweet("123", "Hello world")],
            "has_next_page": False,
            "next_cursor": "",
        },
    )

    result = fetch_topic_posts("AAPL", [], api_key=API_KEY, session=session)

    assert result.ok
    assert len(result.posts) == 1
    post = result.posts[0]
    assert post.x_post_id == "123"
    assert post.author_handle == "alice"
    assert post.text == "Hello world"
    assert post.author_metadata.followers_count == 1000
    assert post.author_metadata.following_count == 200
    assert post.author_metadata.account_age_days > 0
    assert post.author_metadata.post_frequency > 0


def test_pagination_follows_cursor_until_last_page():
    session = MagicMock()
    session.get.side_effect = [
        _response(
            200,
            {
                "tweets": [_tweet("1", "first")],
                "has_next_page": True,
                "next_cursor": "page-2",
            },
        ),
        _response(
            200,
            {
                "tweets": [_tweet("2", "second")],
                "has_next_page": False,
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


def test_max_posts_caps_results_and_stops_paging():
    session = MagicMock()
    session.get.return_value = _response(
        200,
        {
            "tweets": [_tweet(str(i), f"post {i}") for i in range(20)],
            "has_next_page": True,
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
    # Retried up to max_attempts (3) before giving up, per T020's retry-with-backoff.
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
        _response(200, {"tweets": [], "has_next_page": False, "next_cursor": ""}),
    ]

    result = fetch_topic_posts("AAPL", [], api_key=API_KEY, session=session)

    assert result.ok
    assert result.posts == []
    assert session.get.call_count == 2


def test_successful_fetch_records_cost(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        fetch_module, "record_twitterapi_io_read", lambda count: recorded.append(count)
    )
    session = MagicMock()
    session.get.return_value = _response(
        200,
        {
            "tweets": [_tweet("1", "a"), _tweet("2", "b")],
            "has_next_page": False,
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
        status_code, {"error": status_code, "message": "something went wrong"}
    )

    result = fetch_topic_posts("AAPL", [], api_key=API_KEY, session=session)

    assert not result.ok
    assert "something went wrong" in result.error.detail
