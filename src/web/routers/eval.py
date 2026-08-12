"""`GET /api/eval` — thin wrapper over `_compute_report` (src/cli/eval.py,
specs/003-web-dashboard/plan.md §1).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.cli.eval import _compute_report
from src.models.evaluation_label import EvalStage
from src.models.user import User
from src.web.deps import get_current_user, get_db
from src.web.schemas import EvalReportResponse, EvalStageReport

router = APIRouter()


@router.get("", response_model=EvalReportResponse)
def get_eval_report(
    stage: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> EvalReportResponse:
    parsed_stage: EvalStage | None = None
    if stage is not None:
        try:
            parsed_stage = EvalStage(stage)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Unknown eval stage {stage!r}.") from exc

    raw = _compute_report(db, user.id, parsed_stage)
    report = {
        s.value: (EvalStageReport(**stats) if stats is not None else None)
        for s, stats in raw.items()
    }
    return EvalReportResponse(report=report)
