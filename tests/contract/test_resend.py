"""Contract test for the Resend notification client (tasks.md T031,
contracts/external-integrations.md § Notifications, FR-023).

Verifies request shape (auth header, recipient/subject/body), the
completed/partial/failed subject variants (extended per /speckit-analyze
finding E2), and that a failed send is logged and returns False rather than
raising — all against a mocked `requests.Session`, never a live network call.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
import requests

from src.models.digest import Digest, DigestRunType, DigestStatus
from src.models.user import User
from src.notify.email import RESEND_API_URL, send_digest_completion_notification

API_KEY = "test-resend-key"


def _digest(status: DigestStatus) -> Digest:
    return Digest(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        run_type=DigestRunType.SCHEDULED,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        status=status,
        notification_sent_at=None,
    )


def _user() -> User:
    return User(id=uuid.uuid4(), email="pilot@example.com", x_account_handle="pilot")


def _response(status_code=200, text_body=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.text = text_body
    return resp


def test_request_shape_includes_auth_header_recipient_and_subject():
    session = MagicMock()
    session.post.return_value = _response(200)
    digest = _digest(DigestStatus.COMPLETED)
    user = _user()

    send_digest_completion_notification(digest, user, api_key=API_KEY, session=session)

    session.post.assert_called_once()
    args, kwargs = session.post.call_args
    assert args[0] == RESEND_API_URL
    assert kwargs["headers"] == {"Authorization": f"Bearer {API_KEY}"}
    assert kwargs["json"]["to"] == [user.email]
    assert "ready" in kwargs["json"]["subject"]
    assert str(digest.id) in kwargs["json"]["text"]


@pytest.mark.parametrize(
    ("status", "expected_fragment"),
    [
        (DigestStatus.COMPLETED, "ready"),
        (DigestStatus.PARTIAL, "some topics had issues"),
        (DigestStatus.FAILED, "failed"),
    ],
)
def test_subject_reflects_digest_status(status, expected_fragment):
    session = MagicMock()
    session.post.return_value = _response(200)
    digest = _digest(status)

    send_digest_completion_notification(digest, _user(), api_key=API_KEY, session=session)

    subject = session.post.call_args.kwargs["json"]["subject"]
    assert expected_fragment in subject


def test_successful_send_returns_true_and_sets_notification_sent_at():
    session = MagicMock()
    session.post.return_value = _response(200)
    digest = _digest(DigestStatus.COMPLETED)

    result = send_digest_completion_notification(digest, _user(), api_key=API_KEY, session=session)

    assert result is True
    assert digest.notification_sent_at is not None


def test_non_2xx_response_is_logged_and_returns_false_without_raising():
    session = MagicMock()
    session.post.return_value = _response(500, "internal error")
    digest = _digest(DigestStatus.COMPLETED)

    result = send_digest_completion_notification(digest, _user(), api_key=API_KEY, session=session)

    assert result is False
    assert digest.notification_sent_at is None


def test_network_failure_is_logged_and_returns_false_without_raising():
    session = MagicMock()
    session.post.side_effect = requests.ConnectionError("boom")
    digest = _digest(DigestStatus.COMPLETED)

    result = send_digest_completion_notification(digest, _user(), api_key=API_KEY, session=session)

    assert result is False
    assert digest.notification_sent_at is None


def test_failed_status_body_mentions_retry_via_digest_run():
    session = MagicMock()
    session.post.return_value = _response(200)
    digest = _digest(DigestStatus.FAILED)

    send_digest_completion_notification(digest, _user(), api_key=API_KEY, session=session)

    body = session.post.call_args.kwargs["json"]["text"]
    assert "digest run" in body
