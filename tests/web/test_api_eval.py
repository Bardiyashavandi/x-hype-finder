"""Tests for `src/web/routers/eval.py` — wraps `_compute_report`
(src/cli/eval.py, specs/003-web-dashboard/plan.md §1).
"""

from __future__ import annotations

import uuid

from src.models.evaluation_label import CORRECT, INCORRECT, EvalStage, EvaluationLabel


def _label(user, stage: EvalStage, value: str) -> EvaluationLabel:
    return EvaluationLabel(
        stage=stage, target_id=uuid.uuid4(), label_type=value, labeled_by_user_id=user.id
    )


def test_eval_report_is_all_none_with_no_labels_yet(authed_client, seed_user):
    response = authed_client.get("/api/eval")
    assert response.status_code == 200
    report = response.json()["report"]
    assert set(report.keys()) == {s.value for s in EvalStage}
    assert all(v is None for v in report.values())


def test_eval_report_computes_binary_accuracy(authed_client, db_session, seed_user):
    db_session.add_all(
        [
            _label(seed_user, EvalStage.FILTER, CORRECT),
            _label(seed_user, EvalStage.FILTER, CORRECT),
            _label(seed_user, EvalStage.FILTER, INCORRECT),
        ]
    )
    db_session.commit()

    response = authed_client.get("/api/eval")
    filter_report = response.json()["report"]["filter"]
    assert filter_report == {"kind": "binary", "correct": 2, "total": 3, "avg": None, "n": None}


def test_eval_report_computes_average_rating(authed_client, db_session, seed_user):
    db_session.add_all(
        [
            _label(seed_user, EvalStage.DIGEST, "4"),
            _label(seed_user, EvalStage.DIGEST, "5"),
        ]
    )
    db_session.commit()

    response = authed_client.get("/api/eval")
    digest_report = response.json()["report"]["digest"]
    assert digest_report["kind"] == "rating"
    assert digest_report["avg"] == 4.5
    assert digest_report["n"] == 2


def test_eval_report_can_be_scoped_to_a_single_stage(authed_client, db_session, seed_user):
    db_session.add(_label(seed_user, EvalStage.FILTER, CORRECT))
    db_session.commit()

    response = authed_client.get("/api/eval", params={"stage": "filter"})
    report = response.json()["report"]
    assert set(report.keys()) == {"filter"}


def test_eval_report_rejects_an_unknown_stage(authed_client, seed_user):
    response = authed_client.get("/api/eval", params={"stage": "not_a_real_stage"})
    assert response.status_code == 400


def test_eval_endpoint_requires_auth(client):
    assert client.get("/api/eval").status_code == 401
