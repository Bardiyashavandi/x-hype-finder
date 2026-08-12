"""`GET/POST /api/topics`, `DELETE /api/topics/{id}` — thin wrappers over
`list_topics`/`add_topic`/`remove_topic` (src/cli/topic.py,
specs/003-web-dashboard/plan.md §1).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.cli.topic import TopicCommandError, add_topic, list_topics, remove_topic
from src.db.scoped import scoped_select
from src.models.topic import Topic, TopicStatus
from src.models.user import User
from src.web.deps import get_current_user, get_db
from src.web.schemas import TopicCreateRequest, TopicResponse

router = APIRouter()


def _to_response(topic: Topic) -> TopicResponse:
    return TopicResponse(
        id=topic.id,
        name=topic.name,
        x_handles=topic.x_handles,
        status=topic.status.value,
        first_tracked_at=topic.first_tracked_at,
        in_observation_period=topic.observation_period_active,
    )


@router.get("", response_model=list[TopicResponse])
def get_topics(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[TopicResponse]:
    return [_to_response(t) for t in list_topics(db, user.id)]


@router.post("", response_model=TopicResponse, status_code=201)
def create_topic(
    payload: TopicCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TopicResponse:
    try:
        topic = add_topic(db, user.id, payload.name, payload.handles)
    except TopicCommandError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_response(topic)


@router.delete("/{topic_id}", response_model=TopicResponse)
def delete_topic(
    topic_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TopicResponse:
    # remove_topic (src/cli/topic.py) is name-keyed, not id-keyed (mirroring
    # the CLI's own `topic remove <name>`) — look the row up by id first so
    # the API can offer the id-keyed REST shape the frontend needs.
    topic = db.execute(
        scoped_select(Topic, user.id).where(
            Topic.id == topic_id, Topic.status == TopicStatus.ACTIVE
        )
    ).scalar_one_or_none()
    if topic is None:
        raise HTTPException(status_code=404, detail=f"No active topic with id {topic_id}.")
    try:
        removed = remove_topic(db, user.id, topic.name)
    except TopicCommandError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _to_response(removed)
