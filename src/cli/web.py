"""`web run [--host] [--port]` CLI command (specs/003-web-dashboard/plan.md
§2 "Production serving").

Starts the web dashboard's single `uvicorn` process — the same `src.web.app`
FastAPI app that serves `/api/*` also serves the compiled SPA (`web/dist`,
`npm run build`) once it exists, so this one process/one command is the
entire deployable unit. Mirrors `src/cli/scheduler.py`'s `run` subcommand:
a thin argparse wrapper around a long-lived, blocking process.

Deliberately always `--workers 1` (not exposed as a flag): `src/web/jobs.py`'s
background-job registry is an in-process dict — a second worker process
wouldn't share it, so job polling would silently see the wrong worker's jobs
depending on which one handled a given request.
"""

from __future__ import annotations

import argparse

import uvicorn
from dotenv import load_dotenv

from src.logging_config import configure_logging

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def run_web(*, host: str, port: int) -> int:
    # Same "load .env into os.environ, then read from there" convention as
    # src/config.py's load_config — XHF_WEB_SESSION_SECRET is read by
    # src.web.app.create_app() the same way.
    load_dotenv()

    print(f"Web dashboard running on http://{host}:{port} — Ctrl+C to stop.")
    uvicorn.run("src.web.app:create_app", factory=True, host=host, port=port, workers=1)
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="web")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--host", default=DEFAULT_HOST)
    run_parser.add_argument("--port", type=int, default=DEFAULT_PORT)

    args = parser.parse_args(argv)

    if args.command == "run":
        return run_web(host=args.host, port=args.port)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
