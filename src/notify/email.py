"""Resend digest-completion notification (tasks.md T046, FR-023,
contracts/external-integrations.md § Notifications).

Sent when a Digest's `status` transitions to `completed`, `partial`, **or
`failed`** — extended beyond the original completed/partial pair per
/speckit-analyze finding E2: FR-018 requires a scheduled run's failure to be
visible to the user before the next expected run, and since there is no
dashboard in MVP scope, this notification is the only channel. A failed send
is logged, never raised — the digest is already persisted regardless of
notification delivery (FR-023).
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

import requests

from src.models.digest import Digest, DigestStatus
from src.models.user import User

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"

# Falls back to this placeholder sender if RESEND_FROM_EMAIL isn't set; real
# sends require a domain verified with Resend (research.md §10).
DEFAULT_FROM_EMAIL = "X Hype Finder <digest@x-hype-finder.app>"

_STATUS_SUBJECT = {
    DigestStatus.COMPLETED: "Your X Hype Finder digest is ready",
    DigestStatus.PARTIAL: "Your X Hype Finder digest is ready (some topics had issues)",
    DigestStatus.FAILED: "Your X Hype Finder digest run failed",
}


def _from_email() -> str:
    return os.environ.get("RESEND_FROM_EMAIL") or DEFAULT_FROM_EMAIL


def _build_body(digest: Digest) -> str:
    if digest.status == DigestStatus.FAILED:
        return (
            f"Digest {digest.id} failed to complete — every tracked topic hit a "
            "fetch or processing error this run. Check the logs for per-topic "
            "detail, then try `digest run` again once resolved."
        )
    # FR-023: during the manual-only period, also point the user at any
    # drafts awaiting manual publishing (`drafts list --status held_manual`)
    # so drafted content doesn't go unreviewed — this note is unconditional
    # (cheap to print, harmless if there happen to be none this run) rather
    # than querying DraftPost here, keeping the notification path simple and
    # non-blocking regardless of posting state.
    ready_note = (
        f" Run `digest show {digest.id}` to review the results, and "
        "`drafts list --status held_manual` for any drafts awaiting manual publishing."
    )
    partial_note = (
        " One or more topics hit an error this run; other topics completed "
        "normally — check the logs for per-topic detail."
        if digest.status == DigestStatus.PARTIAL
        else ""
    )
    return (
        f"Digest {digest.id} finished with status '{digest.status.value}'."
        f"{partial_note}{ready_note}"
    )


def send_digest_completion_notification(
    digest: Digest,
    user: User,
    *,
    api_key: str,
    session: requests.Session | None = None,
) -> bool:
    """POST the digest-completion email via Resend.

    Never raises — a failed send is logged and this returns `False` rather
    than blocking or failing the digest run itself. Returns `True` on a
    successful (2xx) send, and sets `digest.notification_sent_at` on the
    passed-in object (the caller is responsible for persisting it).
    """
    effective_session = session if session is not None else requests.Session()
    payload = {
        "from": _from_email(),
        "to": [user.email],
        "subject": _STATUS_SUBJECT[digest.status],
        "text": _build_body(digest),
    }

    try:
        response = effective_session.post(
            RESEND_API_URL,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
    except requests.RequestException as exc:
        logger.error("Resend notification failed for digest %s: %s", digest.id, exc)
        return False

    if not response.ok:
        logger.error(
            "Resend notification failed (%s) for digest %s: %s",
            response.status_code,
            digest.id,
            response.text,
        )
        return False

    digest.notification_sent_at = datetime.now(UTC)
    return True
