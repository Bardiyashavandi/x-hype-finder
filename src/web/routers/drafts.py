"""`GET /api/drafts?status=`, `POST /api/drafts/{id}/publish` — thin wrappers
over `list_drafts`/`mark_published` (src/cli/drafts.py,
specs/003-web-dashboard/plan.md §0.A, §1).

`publish_draft` wraps `mark_published()`, never the real X-posting override
path — see plan.md §0.A: live, one-click X posting from the dashboard is
explicitly out of scope. This only records that the caller already posted a
`held_manual` draft themselves, same semantics as the CLI's
`_confirm_already_posted` gate, now enforced by the request body's required
`{"confirmed": true}` literal instead of an interactive prompt.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.cli.drafts import DraftsCommandError, list_drafts, mark_published
from src.models.draft_post import DraftPost, DraftPostStatus
from src.models.user import User
from src.web.deps import get_current_user, get_db
from src.web.schemas import DraftPublishRequest, DraftResponse

router = APIRouter()


def _to_response(draft: DraftPost) -> DraftResponse:
    return DraftResponse(
        id=draft.id,
        theme_id=draft.theme_id,
        draft_text=draft.draft_text,
        confidence_score=draft.confidence_score,
        status=draft.status.value,
        created_at=draft.created_at,
        published_at=draft.published_at,
        publish_error=draft.publish_error,
        tweet_id=draft.tweet_id,
        tweet_url=draft.tweet_url,
    )


@router.get("", response_model=list[DraftResponse])
def get_drafts(
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DraftResponse]:
    parsed_status: DraftPostStatus | None = None
    if status is not None:
        try:
            parsed_status = DraftPostStatus(status)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"Unknown draft status {status!r}."
            ) from exc
    return [_to_response(d) for d in list_drafts(db, user.id, status=parsed_status)]


@router.post("/{draft_id}/publish", response_model=DraftResponse)
def publish_draft(
    draft_id: uuid.UUID,
    _payload: DraftPublishRequest,  # presence of the validated {"confirmed": true} body is the gate
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DraftResponse:
    try:
        draft = mark_published(db, user.id, draft_id)
    except DraftsCommandError as exc:
        status_code = 404 if "No draft found" in str(exc) else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return _to_response(draft)
