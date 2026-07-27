"""Unit tests for scheduler job wiring (tasks.md T047/T070, FR-009, FR-020).

Confirms the standalone SourcePost retention sweep (T070) is registered as
its own independent periodic job — a separate id and cadence from the digest
run job — rather than folded into the digest cadence, since it isn't tied to
any one run completing (/speckit-analyze finding D1).
"""

from __future__ import annotations

from src.config import Config
from src.scheduler import jobs as jobs_module
from src.scheduler.jobs import (
    DEFAULT_CADENCE_HOURS,
    DEFAULT_RETENTION_SWEEP_CADENCE_HOURS,
    run_source_post_retention_sweep,
    start_scheduler,
)


def _config() -> Config:
    return Config(
        twitterapi_io_key="test-twitterapi-key",
        anthropic_api_key="test-anthropic-key",
        resend_api_key="test-resend-key",
        claude_model="claude-sonnet-5",
    )


def test_start_scheduler_registers_both_the_digest_and_retention_sweep_jobs():
    scheduler = start_scheduler(_config(), cadence_hours=1, retention_sweep_cadence_hours=2)
    try:
        job_ids = {job.id for job in scheduler.get_jobs()}
        assert job_ids == {"scheduled_digest_run", "source_post_retention_sweep"}

        digest_job = scheduler.get_job("scheduled_digest_run")
        sweep_job = scheduler.get_job("source_post_retention_sweep")
        assert digest_job.trigger.interval.total_seconds() == 1 * 3600
        assert sweep_job.trigger.interval.total_seconds() == 2 * 3600
    finally:
        scheduler.shutdown(wait=False)


def test_start_scheduler_defaults_to_a_daily_cadence_for_both_jobs():
    scheduler = start_scheduler(_config())
    try:
        assert DEFAULT_CADENCE_HOURS == 24
        assert DEFAULT_RETENTION_SWEEP_CADENCE_HOURS == 24
        for job in scheduler.get_jobs():
            assert job.trigger.interval.total_seconds() == 24 * 3600
    finally:
        scheduler.shutdown(wait=False)


def test_retention_sweep_job_body_calls_prune_and_commits(monkeypatch):
    committed = {"n": 0}
    calls = []

    class _FakeSession:
        def commit(self):
            committed["n"] += 1

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    def fake_get_session():
        return _FakeSession()

    def fake_prune(session):
        calls.append(session)
        return 7

    monkeypatch.setattr(jobs_module, "get_session", fake_get_session)
    monkeypatch.setattr(jobs_module, "prune_stale_source_posts", fake_prune)

    run_source_post_retention_sweep()

    assert len(calls) == 1
    assert committed["n"] == 1
