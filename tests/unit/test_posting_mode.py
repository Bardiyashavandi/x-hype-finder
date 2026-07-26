"""Unit tests for PostingMode state-machine gating (tasks.md T053,
data-model.md § PostingMode, FR-010, FR-011, FR-013, FR-022).

Covers src/posting/mode.py (validation-period gate, bio-label gate,
kill-switch-forces-manual, threshold routing) and src/posting/rate_limit.py
(rolling 24h/5-post cap, jittered publish gate) together, since both compose
into "PostingMode state-machine gating" behavior as described in tasks.md —
plus src/posting/model_checkpoint.py's week-3 model-reassessment
recommendation (T059). All against an in-memory SQLite session
(tests/conftest.py's `db_session`) or pure function calls — no network.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from src.models.draft_post import DraftPost, DraftPostStatus
from src.models.posting_mode import PostingMode, PostingModeValue
from src.models.user import User
from src.posting.mode import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    VALIDATION_PERIOD,
    DraftRouting,
    PostingModeError,
    effective_mode,
    get_or_create_posting_mode,
    is_autonomous_switch_allowed,
    route_new_draft,
    set_kill_switch,
    switch_to_autonomous,
    switch_to_manual,
)
from src.posting.model_checkpoint import (
    ANTHROPIC_CREDIT_USD,
    FALLBACK_MODEL,
    recommend_model_for_autonomous_phase,
)
from src.posting.rate_limit import (
    JITTER_MAX_INTERVAL,
    JITTER_MIN_INTERVAL,
    RATE_CAP_POSTS_PER_ROLLING_WINDOW,
    can_publish_now,
    compute_next_allowed_publish_time,
    count_autonomous_posts_in_rolling_window,
    has_rate_cap_headroom,
)

NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


class _FixedRandom:
    """A deterministic rand-like object for jitter tests."""

    def __init__(self, value: float):
        self._value = value

    def uniform(self, a: float, b: float) -> float:
        return self._value


def _seed_user(session) -> User:
    user = User(email="pilot@example.com", x_account_handle="pilot")
    session.add(user)
    session.flush()
    return user


def _posting_mode(
    user: User,
    *,
    mode: PostingModeValue = PostingModeValue.MANUAL,
    confidence_threshold: int = DEFAULT_CONFIDENCE_THRESHOLD,
    validation_period_ends_at: datetime = NOW - timedelta(days=1),
    kill_switch_engaged: bool = False,
    last_post_published_at: datetime | None = None,
) -> PostingMode:
    return PostingMode(
        user_id=user.id,
        mode=mode,
        confidence_threshold=confidence_threshold,
        validation_period_ends_at=validation_period_ends_at,
        kill_switch_engaged=kill_switch_engaged,
        last_post_published_at=last_post_published_at,
    )


def _draft_post(user: User, *, status: DraftPostStatus, published_at: datetime | None) -> DraftPost:
    return DraftPost(
        theme_id=uuid.uuid4(),
        user_id=user.id,
        draft_text="A draft.",
        confidence_score=90,
        status=status,
        published_at=published_at,
    )


# --- get_or_create_posting_mode -------------------------------------------


def test_get_or_create_posting_mode_creates_manual_row_anchored_to_now(db_session):
    user = _seed_user(db_session)

    posting_mode = get_or_create_posting_mode(db_session, user, now=NOW)

    assert posting_mode.mode == PostingModeValue.MANUAL
    assert posting_mode.confidence_threshold == DEFAULT_CONFIDENCE_THRESHOLD
    assert posting_mode.validation_period_ends_at == NOW + VALIDATION_PERIOD
    assert posting_mode.kill_switch_engaged is False


def test_get_or_create_posting_mode_returns_existing_row_on_second_call(db_session):
    user = _seed_user(db_session)

    first = get_or_create_posting_mode(db_session, user, now=NOW)
    first.mode = PostingModeValue.AUTONOMOUS  # mutate to prove the second call doesn't reset it
    db_session.flush()

    second = get_or_create_posting_mode(db_session, user, now=NOW + timedelta(days=1))

    assert second.id == first.id
    assert second.mode == PostingModeValue.AUTONOMOUS
    assert second.validation_period_ends_at == NOW + VALIDATION_PERIOD  # unchanged


# --- effective_mode / kill switch ------------------------------------------


def test_effective_mode_is_kill_switch_free_reads_stored_mode(db_session):
    user = _seed_user(db_session)
    manual = _posting_mode(user, mode=PostingModeValue.MANUAL)
    autonomous = _posting_mode(user, mode=PostingModeValue.AUTONOMOUS)

    assert effective_mode(manual) == PostingModeValue.MANUAL
    assert effective_mode(autonomous) == PostingModeValue.AUTONOMOUS


def test_effective_mode_kill_switch_forces_manual_regardless_of_stored_mode(db_session):
    user = _seed_user(db_session)
    posting_mode = _posting_mode(user, mode=PostingModeValue.AUTONOMOUS, kill_switch_engaged=True)

    assert effective_mode(posting_mode) == PostingModeValue.MANUAL


def test_set_kill_switch_toggles_engaged_flag(db_session):
    user = _seed_user(db_session)
    posting_mode = _posting_mode(user)

    set_kill_switch(posting_mode, engaged=True, now=NOW)
    assert posting_mode.kill_switch_engaged is True

    set_kill_switch(posting_mode, engaged=False, now=NOW)
    assert posting_mode.kill_switch_engaged is False


# --- is_autonomous_switch_allowed / switch_to_autonomous / switch_to_manual


def test_autonomous_switch_blocked_within_validation_period_even_with_bio_label(db_session):
    user = _seed_user(db_session)
    posting_mode = _posting_mode(user, validation_period_ends_at=NOW + timedelta(days=1))

    allowed, reason = is_autonomous_switch_allowed(
        posting_mode, bio_has_automated_label=True, now=NOW
    )

    assert allowed is False
    assert "validation period" in reason


def test_autonomous_switch_blocked_without_bio_label_after_validation_period(db_session):
    user = _seed_user(db_session)
    posting_mode = _posting_mode(user, validation_period_ends_at=NOW - timedelta(days=1))

    allowed, reason = is_autonomous_switch_allowed(
        posting_mode, bio_has_automated_label=False, now=NOW
    )

    assert allowed is False
    assert "automated" in reason


def test_autonomous_switch_allowed_when_both_gates_clear(db_session):
    user = _seed_user(db_session)
    posting_mode = _posting_mode(user, validation_period_ends_at=NOW - timedelta(days=1))

    allowed, reason = is_autonomous_switch_allowed(
        posting_mode, bio_has_automated_label=True, now=NOW
    )

    assert allowed is True
    assert reason is None


def test_switch_to_autonomous_raises_and_leaves_mode_unchanged_when_blocked(
    db_session, monkeypatch
):
    user = _seed_user(db_session)
    posting_mode = _posting_mode(user, validation_period_ends_at=NOW + timedelta(days=1))
    monkeypatch.setattr("src.posting.mode.check_bio_has_automated_label", lambda x_client: True)

    with pytest.raises(PostingModeError):
        switch_to_autonomous(posting_mode, x_client=object(), now=NOW)

    assert posting_mode.mode == PostingModeValue.MANUAL


def test_switch_to_autonomous_succeeds_when_gates_clear(db_session, monkeypatch):
    user = _seed_user(db_session)
    posting_mode = _posting_mode(user, validation_period_ends_at=NOW - timedelta(days=1))
    monkeypatch.setattr("src.posting.mode.check_bio_has_automated_label", lambda x_client: True)

    switch_to_autonomous(posting_mode, x_client=object(), now=NOW)

    assert posting_mode.mode == PostingModeValue.AUTONOMOUS


def test_switch_to_autonomous_live_checks_the_bio_every_call_never_cached(db_session, monkeypatch):
    """FR-013: checked at the instant of the switch — a bio that had the
    label a moment ago but doesn't right now must still block."""
    user = _seed_user(db_session)
    posting_mode = _posting_mode(user, validation_period_ends_at=NOW - timedelta(days=1))
    monkeypatch.setattr("src.posting.mode.check_bio_has_automated_label", lambda x_client: False)

    with pytest.raises(PostingModeError, match="automated"):
        switch_to_autonomous(posting_mode, x_client=object(), now=NOW)


def test_switch_to_manual_always_succeeds_even_from_autonomous(db_session):
    user = _seed_user(db_session)
    posting_mode = _posting_mode(user, mode=PostingModeValue.AUTONOMOUS, kill_switch_engaged=True)

    switch_to_manual(posting_mode, now=NOW)

    assert posting_mode.mode == PostingModeValue.MANUAL


# --- route_new_draft (threshold routing) -----------------------------------


def test_route_new_draft_manual_mode_holds_regardless_of_confidence(db_session):
    user = _seed_user(db_session)
    posting_mode = _posting_mode(user, mode=PostingModeValue.MANUAL, confidence_threshold=70)

    assert route_new_draft(posting_mode, 100, now=NOW) == DraftRouting.HOLD_MANUAL
    assert route_new_draft(posting_mode, 0, now=NOW) == DraftRouting.HOLD_MANUAL


def test_route_new_draft_kill_switch_holds_manual_even_in_autonomous_mode(db_session):
    user = _seed_user(db_session)
    posting_mode = _posting_mode(
        user, mode=PostingModeValue.AUTONOMOUS, confidence_threshold=70, kill_switch_engaged=True
    )

    assert route_new_draft(posting_mode, 95, now=NOW) == DraftRouting.HOLD_MANUAL


def test_route_new_draft_autonomous_below_threshold_holds_for_review(db_session):
    user = _seed_user(db_session)
    posting_mode = _posting_mode(user, mode=PostingModeValue.AUTONOMOUS, confidence_threshold=70)

    assert route_new_draft(posting_mode, 69, now=NOW) == DraftRouting.HOLD_BELOW_THRESHOLD


def test_route_new_draft_autonomous_at_or_above_threshold_is_eligible(db_session):
    user = _seed_user(db_session)
    posting_mode = _posting_mode(user, mode=PostingModeValue.AUTONOMOUS, confidence_threshold=70)

    assert (
        route_new_draft(posting_mode, 70, now=NOW) == DraftRouting.ELIGIBLE_FOR_AUTONOMOUS_PUBLISH
    )
    assert (
        route_new_draft(posting_mode, 100, now=NOW) == DraftRouting.ELIGIBLE_FOR_AUTONOMOUS_PUBLISH
    )


# --- rate_limit: rolling 24h/5-post cap -------------------------------------


def test_count_autonomous_posts_only_counts_published_auto_in_window(db_session):
    user = _seed_user(db_session)
    db_session.add_all(
        [
            _draft_post(
                user, status=DraftPostStatus.PUBLISHED_AUTO, published_at=NOW - timedelta(hours=1)
            ),
            _draft_post(
                user, status=DraftPostStatus.PUBLISHED_AUTO, published_at=NOW - timedelta(hours=23)
            ),
            # Outside the 24h window:
            _draft_post(
                user, status=DraftPostStatus.PUBLISHED_AUTO, published_at=NOW - timedelta(hours=25)
            ),
            # Not actually published yet — must not count:
            _draft_post(user, status=DraftPostStatus.HELD_BELOW_THRESHOLD, published_at=None),
            _draft_post(user, status=DraftPostStatus.HELD_MANUAL, published_at=None),
        ]
    )
    db_session.flush()

    assert count_autonomous_posts_in_rolling_window(db_session, user.id, now=NOW) == 2


def test_has_rate_cap_headroom_false_once_five_published_in_window(db_session):
    user = _seed_user(db_session)
    db_session.add_all(
        [
            _draft_post(
                user, status=DraftPostStatus.PUBLISHED_AUTO, published_at=NOW - timedelta(hours=h)
            )
            for h in range(RATE_CAP_POSTS_PER_ROLLING_WINDOW)
        ]
    )
    db_session.flush()

    assert has_rate_cap_headroom(db_session, user.id, now=NOW) is False


def test_has_rate_cap_headroom_true_below_the_cap(db_session):
    user = _seed_user(db_session)
    db_session.add_all(
        [
            _draft_post(
                user, status=DraftPostStatus.PUBLISHED_AUTO, published_at=NOW - timedelta(hours=1)
            )
            for _ in range(RATE_CAP_POSTS_PER_ROLLING_WINDOW - 1)
        ]
    )
    db_session.flush()

    assert has_rate_cap_headroom(db_session, user.id, now=NOW) is True


# --- rate_limit: jittered publish gate --------------------------------------


def test_next_allowed_publish_time_is_now_when_no_prior_post():
    assert compute_next_allowed_publish_time(None, now=NOW) == NOW


def test_next_allowed_publish_time_adds_jitter_within_configured_bounds():
    last_published = NOW - timedelta(hours=1)

    next_allowed = compute_next_allowed_publish_time(
        last_published, now=NOW, rand=_FixedRandom(JITTER_MIN_INTERVAL.total_seconds())
    )
    assert next_allowed == last_published + JITTER_MIN_INTERVAL

    next_allowed = compute_next_allowed_publish_time(
        last_published, now=NOW, rand=_FixedRandom(JITTER_MAX_INTERVAL.total_seconds())
    )
    assert next_allowed == last_published + JITTER_MAX_INTERVAL


def test_jitter_never_a_fixed_interval_across_many_draws():
    """FR-014: spacing must vary, never a fixed cadence — sample real
    `random` (not a fixed stub) and confirm we don't get the same gap twice
    in a row across a reasonably large sample."""
    last_published = NOW - timedelta(hours=1)
    gaps = {
        compute_next_allowed_publish_time(last_published, now=NOW) - last_published
        for _ in range(20)
    }
    assert len(gaps) > 1


def test_can_publish_now_blocked_by_rate_cap_even_if_jitter_gate_would_pass(db_session):
    user = _seed_user(db_session)
    posting_mode = _posting_mode(user, last_post_published_at=NOW - timedelta(hours=10))
    db_session.add_all(
        [
            _draft_post(
                user, status=DraftPostStatus.PUBLISHED_AUTO, published_at=NOW - timedelta(hours=h)
            )
            for h in range(RATE_CAP_POSTS_PER_ROLLING_WINDOW)
        ]
    )
    db_session.flush()

    allowed, reason = can_publish_now(
        db_session, posting_mode, user.id, now=NOW, rand=_FixedRandom(0)
    )

    assert allowed is False
    assert "cap" in reason


def test_can_publish_now_blocked_by_jitter_gate_when_cap_has_headroom(db_session):
    user = _seed_user(db_session)
    posting_mode = _posting_mode(user, last_post_published_at=NOW - timedelta(minutes=1))

    allowed, reason = can_publish_now(
        db_session,
        posting_mode,
        user.id,
        now=NOW,
        rand=_FixedRandom(JITTER_MAX_INTERVAL.total_seconds()),
    )

    assert allowed is False
    assert "jitter" in reason


def test_can_publish_now_true_when_both_gates_clear(db_session):
    user = _seed_user(db_session)
    posting_mode = _posting_mode(user, last_post_published_at=None)

    allowed, reason = can_publish_now(db_session, posting_mode, user.id, now=NOW)

    assert allowed is True
    assert reason is None


# --- model_checkpoint (T059) -------------------------------------------------


def test_recommend_model_stays_on_sonnet_when_credit_is_holding_up():
    model = recommend_model_for_autonomous_phase(
        cumulative_claude_spend=ANTHROPIC_CREDIT_USD - 0.01
    )
    assert model == "claude-sonnet-5"


def test_recommend_model_downgrades_to_haiku_once_credit_is_exhausted():
    model = recommend_model_for_autonomous_phase(cumulative_claude_spend=ANTHROPIC_CREDIT_USD)
    assert model == FALLBACK_MODEL
