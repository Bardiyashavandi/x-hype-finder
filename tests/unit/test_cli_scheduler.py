"""Unit test for `scheduler run`'s graceful-shutdown path (src/cli/scheduler.py).

`run_scheduler` blocks on a plain `time.sleep` loop so the process stays alive
for the scheduler's background thread; on Ctrl+C (KeyboardInterrupt) it must
shut the scheduler down cleanly rather than leaving it dangling when the
process exits. `time.sleep` is monkeypatched to raise `KeyboardInterrupt`
immediately, so the test doesn't actually block.
"""

from __future__ import annotations

import src.cli.scheduler as scheduler_module
from src.config import Config


def _config() -> Config:
    return Config(
        twitterapi_io_key="test-twitterapi-key",
        anthropic_api_key="test-anthropic-key",
        resend_api_key="test-resend-key",
        claude_model="claude-sonnet-5",
    )


class _FakeScheduler:
    def __init__(self) -> None:
        self.shutdown_calls = 0

    def shutdown(self) -> None:
        self.shutdown_calls += 1


def test_run_scheduler_shuts_down_gracefully_on_keyboard_interrupt(monkeypatch):
    fake_scheduler = _FakeScheduler()
    start_calls = []

    def fake_load_config():
        return _config()

    def fake_start_scheduler(config, *, cadence_hours, retention_sweep_cadence_hours):
        start_calls.append((config, cadence_hours, retention_sweep_cadence_hours))
        return fake_scheduler

    def fake_sleep(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(scheduler_module, "load_config", fake_load_config)
    monkeypatch.setattr(scheduler_module, "start_scheduler", fake_start_scheduler)
    monkeypatch.setattr(scheduler_module.time, "sleep", fake_sleep)

    exit_code = scheduler_module.run_scheduler(cadence_hours=1, retention_sweep_cadence_hours=2)

    assert exit_code == 0
    assert fake_scheduler.shutdown_calls == 1
    assert start_calls == [(_config(), 1, 2)]
