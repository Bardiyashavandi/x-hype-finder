"""`posting mode show/set` and `posting kill-switch on|off` CLI commands
(tasks.md T063, contracts/cli-commands.md; FR-011, FR-013, FR-022).

`mode set autonomous` also surfaces T059's week-3 model-reassessment
recommendation (Sonnet vs Haiku for the autonomous phase) at the exact
moment it becomes actionable — the model itself stays env-var config
(src/config.py), so this only prints guidance for the operator to apply via
`.env`, never rewrites it (Constitution V).
"""

from __future__ import annotations

import argparse
import sys

from src.cli._common import NoCurrentUserError, resolve_current_user
from src.config import load_config, load_x_credentials_for_user
from src.db.scoped import scoped_select
from src.db.session import get_session
from src.logging_config import configure_logging
from src.models.posting_mode import PostingMode
from src.posting.bio_check import build_x_client
from src.posting.mode import (
    PostingModeError,
    set_kill_switch,
    switch_to_autonomous,
    switch_to_manual,
)
from src.posting.model_checkpoint import recommend_model_for_autonomous_phase


def _posting_mode_for_user(session, user_id) -> PostingMode | None:
    return session.execute(scoped_select(PostingMode, user_id)).scalar_one_or_none()


def _print_mode(posting_mode: PostingMode) -> None:
    last_post = (
        posting_mode.last_post_published_at.isoformat()
        if posting_mode.last_post_published_at
        else "-"
    )
    print(f"mode:                      {posting_mode.mode.value}")
    print(f"confidence_threshold:      {posting_mode.confidence_threshold}")
    print(f"validation_period_ends_at: {posting_mode.validation_period_ends_at.isoformat()}")
    print(f"kill_switch_engaged:       {posting_mode.kill_switch_engaged}")
    print(f"last_post_published_at:    {last_post}")


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="posting")
    subparsers = parser.add_subparsers(dest="command", required=True)

    mode_parser = subparsers.add_parser("mode")
    mode_subparsers = mode_parser.add_subparsers(dest="mode_command", required=True)
    mode_subparsers.add_parser("show")
    set_parser = mode_subparsers.add_parser("set")
    set_parser.add_argument("value", choices=["autonomous", "manual"])

    kill_switch_parser = subparsers.add_parser("kill-switch")
    kill_switch_parser.add_argument("value", choices=["on", "off"])

    args = parser.parse_args(argv)

    with get_session() as session:
        try:
            user = resolve_current_user(session)
        except NoCurrentUserError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        posting_mode = _posting_mode_for_user(session, user.id)
        if posting_mode is None:
            print(
                "No posting mode configured yet — run `digest run` at least once first "
                "(the validation period is anchored to your first digest run).",
                file=sys.stderr,
            )
            return 1

        if args.command == "mode" and args.mode_command == "show":
            _print_mode(posting_mode)
            return 0

        if args.command == "mode" and args.mode_command == "set" and args.value == "manual":
            switch_to_manual(posting_mode)
            session.commit()
            print("Posting mode set to manual.")
            return 0

        if args.command == "mode" and args.mode_command == "set" and args.value == "autonomous":
            config = load_config()
            x_client = build_x_client(load_x_credentials_for_user(user))
            try:
                switch_to_autonomous(posting_mode, x_client=x_client)
            except PostingModeError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                return 1
            session.commit()
            print("Posting mode set to autonomous.")

            recommended_model = recommend_model_for_autonomous_phase()
            if recommended_model != config.claude_model:
                print(
                    f"NOTE: cumulative Claude spend suggests setting XHF_CLAUDE_MODEL="
                    f"{recommended_model!r} in .env for the autonomous phase "
                    f"(currently {config.claude_model!r})."
                )
            return 0

        if args.command == "kill-switch":
            engaged = args.value == "on"
            set_kill_switch(posting_mode, engaged=engaged)
            session.commit()
            print(f"Kill switch {'engaged' if engaged else 'disengaged'}.")
            return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
