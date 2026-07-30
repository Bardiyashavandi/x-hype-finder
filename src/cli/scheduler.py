"""`scheduler run` CLI command (mirrors digest.py/topic.py's subcommand
pattern).

`src/scheduler/jobs.py`'s `start_scheduler` wires up an in-process
APScheduler but is never itself invoked anywhere in this codebase — nothing
runs it as a long-lived process without this command. `run` constructs
`Config`, starts the scheduler, and blocks (a plain sleep loop) so the
process stays alive for the scheduler's background thread to keep firing
jobs, until interrupted (Ctrl+C / SIGINT), at which point it shuts the
scheduler down gracefully rather than letting the process die mid-job.
"""

from __future__ import annotations

import argparse
import time

from src.config import load_config
from src.logging_config import configure_logging, get_logger
from src.scheduler.jobs import (
    DEFAULT_CADENCE_HOURS,
    DEFAULT_RETENTION_SWEEP_CADENCE_HOURS,
    start_scheduler,
)

log = get_logger(__name__)


def run_scheduler(*, cadence_hours: int, retention_sweep_cadence_hours: int) -> int:
    """Start the scheduler and block until interrupted, then shut it down
    gracefully. Returns a process exit code."""
    config = load_config()
    scheduler = start_scheduler(
        config,
        cadence_hours=cadence_hours,
        retention_sweep_cadence_hours=retention_sweep_cadence_hours,
    )
    log.info(
        "scheduler started: digest run every %dh, retention sweep every %dh",
        cadence_hours,
        retention_sweep_cadence_hours,
    )
    print(
        f"Scheduler running (digest run every {cadence_hours}h, "
        f"retention sweep every {retention_sweep_cadence_hours}h). Press Ctrl+C to stop."
    )

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down scheduler...")
        scheduler.shutdown()
        log.info("scheduler shut down")

    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="scheduler")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument(
        "--cadence-hours",
        type=int,
        default=DEFAULT_CADENCE_HOURS,
        help=f"digest run cadence in hours (default: {DEFAULT_CADENCE_HOURS})",
    )
    run_parser.add_argument(
        "--retention-sweep-cadence-hours",
        type=int,
        default=DEFAULT_RETENTION_SWEEP_CADENCE_HOURS,
        help=(
            "SourcePost retention sweep cadence in hours "
            f"(default: {DEFAULT_RETENTION_SWEEP_CADENCE_HOURS})"
        ),
    )

    args = parser.parse_args(argv)

    if args.command == "run":
        return run_scheduler(
            cadence_hours=args.cadence_hours,
            retention_sweep_cadence_hours=args.retention_sweep_cadence_hours,
        )

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
