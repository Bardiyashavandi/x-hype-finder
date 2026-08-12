"""FastAPI backend for the Web Dashboard (specs/003-web-dashboard/plan.md).

Every router here is a thin translation layer over the *existing*
business-logic functions in `src/cli/*.py` and `src/pipeline/orchestrator.py`
— no pipeline logic is reimplemented for the API (plan.md §1 "Core
principle").
"""

from __future__ import annotations
