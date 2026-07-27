"""Contract test for the X posting API via `tweepy` (tasks.md T054,
contracts/external-integrations.md § X Posting, FR-013, FR-019).

Verifies bio-label read request shape (src/posting/bio_check.py), the
publish call shape and failure surfacing (src/posting/publish.py) — all
against a mocked `tweepy.Client`, never a live network call. Actual posting
to a live X account is out of scope for this MVP milestone; this test only
proves the client-integration logic is correct and safe to flip on later.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import tweepy

from src.config import XCredentials
from src.models.draft_post import DraftPostStatus
from src.models.posting_mode import PostingMode, PostingModeValue
from src.posting.bio_check import build_x_client, check_bio_has_automated_label
from src.posting.publish import decide_and_publish

USER_ID = uuid.uuid4()
NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


def _x_credentials() -> XCredentials:
    return XCredentials(
        api_key="test-x-api-key",
        api_secret="test-x-api-secret",
        access_token="test-x-access-token",
        access_token_secret="test-x-access-token-secret",
    )


def _posting_mode(**overrides) -> PostingMode:
    defaults = dict(
        user_id=USER_ID,
        mode=PostingModeValue.AUTONOMOUS,
        confidence_threshold=70,
        validation_period_ends_at=NOW,
        kill_switch_engaged=False,
        last_post_published_at=None,
    )
    defaults.update(overrides)
    return PostingMode(**defaults)


def _get_me_response(description: str | None):
    data = None if description is None else SimpleNamespace(description=description)
    return SimpleNamespace(data=data)


# --- build_x_client ----------------------------------------------------


def test_build_x_client_constructs_tweepy_client_from_env_sourced_config(monkeypatch):
    captured = {}

    class _FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(tweepy, "Client", _FakeClient)

    build_x_client(_x_credentials())

    assert captured == {
        "consumer_key": "test-x-api-key",
        "consumer_secret": "test-x-api-secret",
        "access_token": "test-x-access-token",
        "access_token_secret": "test-x-access-token-secret",
    }


# --- check_bio_has_automated_label (FR-013) -----------------------------


def test_bio_check_request_shape_reads_description_field():
    client = MagicMock()
    client.get_me.return_value = _get_me_response("🤖 Automated account")

    check_bio_has_automated_label(client)

    client.get_me.assert_called_once_with(user_fields=["description"])


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("🤖 Automated account tracking hype", True),
        ("This is an AUTOMATED bot", True),
        ("Just a regular human account", False),
        ("", False),
        (None, False),
    ],
)
def test_bio_check_detects_automated_label_case_insensitively(description, expected):
    client = MagicMock()
    client.get_me.return_value = _get_me_response(description)

    assert check_bio_has_automated_label(client) is expected


def test_bio_check_is_never_cached_reflects_the_live_call_every_time():
    """FR-013: checked at the instant of the switch, not a stale cached read."""
    client = MagicMock()
    client.get_me.side_effect = [
        _get_me_response("Automated account"),
        _get_me_response("no label here"),
    ]

    assert check_bio_has_automated_label(client) is True
    assert check_bio_has_automated_label(client) is False
    assert client.get_me.call_count == 2


# --- publish call shape + failure surfacing (FR-012, FR-019) -----------


def test_publish_call_shape_posts_the_draft_text_via_create_tweet(db_session):
    client = MagicMock()
    posting_mode = _posting_mode()

    outcome = decide_and_publish(
        db_session,
        posting_mode,
        confidence_score=90,
        draft_text="AAPL is seeing unusual bullish chatter today.",
        x_client=client,
        now=NOW,
    )

    client.create_tweet.assert_called_once_with(
        text="AAPL is seeing unusual bullish chatter today."
    )
    assert outcome.status == DraftPostStatus.PUBLISHED_AUTO
    assert outcome.published_at == NOW
    assert outcome.publish_error is None
    assert posting_mode.last_post_published_at == NOW


def test_publish_failure_is_surfaced_never_silently_dropped(db_session):
    """FR-019: a publish call that fails after clearing every gate must
    surface as publish_failed with the error populated, not raise or vanish."""
    client = MagicMock()
    client.create_tweet.side_effect = tweepy.TweepyException("403 duplicate content")
    posting_mode = _posting_mode()

    outcome = decide_and_publish(
        db_session,
        posting_mode,
        confidence_score=90,
        draft_text="A draft that X rejects.",
        x_client=client,
        now=NOW,
    )

    assert outcome.status == DraftPostStatus.PUBLISH_FAILED
    assert outcome.published_at is None
    assert outcome.publish_error is not None
    assert posting_mode.last_post_published_at is None  # never advanced on failure


def test_publish_never_attempted_when_manual_mode_holds_the_draft(db_session):
    client = MagicMock()
    posting_mode = _posting_mode(mode=PostingModeValue.MANUAL)

    outcome = decide_and_publish(
        db_session,
        posting_mode,
        confidence_score=95,
        draft_text="Should never be posted.",
        x_client=client,
        now=NOW,
    )

    client.create_tweet.assert_not_called()
    assert outcome.status == DraftPostStatus.HELD_MANUAL
