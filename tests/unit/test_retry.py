"""Unit tests for the retry-with-backoff decorator (tasks.md T069, T020, FR-018).

`sleep` is always injected in these tests so nothing here actually waits —
real timing behavior (delay growth, jitter) is asserted against the recorded
call arguments instead.
"""

from __future__ import annotations

import logging

import pytest

from src.utils.retry import retry_with_backoff


class _FlakyError(RuntimeError):
    pass


class _OtherError(RuntimeError):
    pass


def test_succeeds_on_first_attempt_without_sleeping():
    sleeps: list[float] = []
    calls = {"n": 0}

    @retry_with_backoff(max_attempts=3, sleep=sleeps.append)
    def fn():
        calls["n"] += 1
        return "ok"

    assert fn() == "ok"
    assert calls["n"] == 1
    assert sleeps == []


def test_succeeds_after_transient_failures_within_max_attempts():
    sleeps: list[float] = []
    calls = {"n": 0}

    @retry_with_backoff(
        max_attempts=3, base_delay_seconds=1.0, jitter_seconds=0, sleep=sleeps.append
    )
    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _FlakyError("transient")
        return "ok"

    assert fn() == "ok"
    assert calls["n"] == 3
    assert len(sleeps) == 2  # slept between attempt 1->2 and 2->3, not after success


def test_raises_last_exception_after_exhausting_all_attempts():
    sleeps: list[float] = []
    calls = {"n": 0}

    @retry_with_backoff(max_attempts=3, jitter_seconds=0, sleep=sleeps.append)
    def fn():
        calls["n"] += 1
        raise _FlakyError(f"failure {calls['n']}")

    with pytest.raises(_FlakyError, match="failure 3"):
        fn()

    assert calls["n"] == 3
    assert len(sleeps) == 2  # never sleeps after the final, non-retried failure


def test_never_retries_an_exception_outside_the_configured_set():
    calls = {"n": 0}

    @retry_with_backoff(max_attempts=3, exceptions=(_FlakyError,), sleep=lambda _: None)
    def fn():
        calls["n"] += 1
        raise _OtherError("not retryable")

    with pytest.raises(_OtherError):
        fn()

    assert calls["n"] == 1  # propagated immediately, no retry attempted


def test_delay_grows_by_the_configured_backoff_factor():
    sleeps: list[float] = []
    calls = {"n": 0}

    @retry_with_backoff(
        max_attempts=4,
        base_delay_seconds=1.0,
        backoff_factor=2.0,
        jitter_seconds=0,
        sleep=sleeps.append,
    )
    def fn():
        calls["n"] += 1
        raise _FlakyError("always fails")

    with pytest.raises(_FlakyError):
        fn()

    # attempt indices 0, 1, 2 (3 retries before the 4th and final failure):
    # delay = base_delay_seconds * backoff_factor ** attempt
    assert sleeps == [1.0, 2.0, 4.0]


def test_jitter_adds_a_small_bounded_extra_delay():
    sleeps: list[float] = []
    calls = {"n": 0}

    @retry_with_backoff(
        max_attempts=2,
        base_delay_seconds=1.0,
        backoff_factor=2.0,
        jitter_seconds=0.25,
        sleep=sleeps.append,
    )
    def fn():
        calls["n"] += 1
        raise _FlakyError("always fails")

    with pytest.raises(_FlakyError):
        fn()

    assert len(sleeps) == 1
    assert 1.0 <= sleeps[0] <= 1.25


def test_max_attempts_below_one_is_rejected():
    with pytest.raises(ValueError, match="max_attempts"):
        retry_with_backoff(max_attempts=0)


def test_default_sleep_uses_real_time_sleep_when_none_injected(monkeypatch):
    """Without an injected `sleep`, the decorator falls back to `time.sleep` —
    verify that fallback wiring rather than assuming it (T020's real-world path)."""
    import src.utils.retry as retry_module

    recorded: list[float] = []
    monkeypatch.setattr(retry_module.time, "sleep", recorded.append)

    calls = {"n": 0}

    @retry_with_backoff(max_attempts=2, jitter_seconds=0)
    def fn():
        calls["n"] += 1
        if calls["n"] < 2:
            raise _FlakyError("transient")
        return "ok"

    assert fn() == "ok"
    assert len(recorded) == 1


def test_gives_up_and_logs_an_error_after_the_final_attempt(caplog):
    @retry_with_backoff(max_attempts=2, jitter_seconds=0, sleep=lambda _: None)
    def fn():
        raise _FlakyError("boom")

    with caplog.at_level(logging.ERROR, logger="src.utils.retry"):
        with pytest.raises(_FlakyError):
            fn()

    assert "failed after 2 attempt(s), giving up" in caplog.text


def test_logs_a_warning_before_each_retry(caplog):
    calls = {"n": 0}

    @retry_with_backoff(max_attempts=2, jitter_seconds=0, sleep=lambda _: None)
    def fn():
        calls["n"] += 1
        if calls["n"] < 2:
            raise _FlakyError("transient")
        return "ok"

    with caplog.at_level(logging.WARNING, logger="src.utils.retry"):
        fn()

    assert "retrying in" in caplog.text
