"""Week-3 reassess-and-possibly-downgrade checkpoint (tasks.md T059,
research.md §3, plan.md Constitution Check VI, /speckit-analyze finding E1).

At `validation_period_ends_at` — the same week-3 moment src/posting/mode.py
gates the autonomous mode switch on — decide whether Summarize/Draft Post
(src/agent/summarize.py, src/agent/draft_post.py) should stay on
`claude-sonnet-5` or downgrade to `claude-haiku-4-5-20251001` for the
autonomous phase, based on cumulative Claude-only spend against the $5
Anthropic credit (a narrower figure than the $50 total budget the cost
tracker also tracks — see `get_cumulative_spend_by_source`).

The model name is env-var config (`XHF_CLAUDE_MODEL`, src/config.py), never
DB-stored — Constitution V treats all provider config as env-var only, and a
long-lived process shouldn't rewrite its own environment at runtime. So this
checkpoint is advisory: it recommends a model, and the CLI (T063's `posting
mode set autonomous`) surfaces that recommendation to the operator at the
exact moment it matters, for them to apply via `.env` before the next run.
"""

from __future__ import annotations

from src.config import DEFAULT_CLAUDE_MODEL
from src.utils.cost_tracker import get_cumulative_spend_by_source

# research.md §3: the user's $5 Anthropic credit is the reassessment
# benchmark for Summarize/Draft Post spend specifically, not the $50 total
# project budget (which also covers TwitterAPI.io reads).
ANTHROPIC_CREDIT_USD = 5.00

FALLBACK_MODEL = "claude-haiku-4-5-20251001"


def recommend_model_for_autonomous_phase(*, cumulative_claude_spend: float | None = None) -> str:
    """Recommend which Claude model to run Summarize/Draft Post under for the
    autonomous phase: stay on `claude-sonnet-5` if the $5 credit is holding
    up, otherwise downgrade to `claude-haiku-4-5-20251001` (research.md §3).

    `cumulative_claude_spend` is injectable for tests; defaults to the real
    cost-tracker ledger's Claude-only total.
    """
    spend = (
        cumulative_claude_spend
        if cumulative_claude_spend is not None
        else get_cumulative_spend_by_source("claude")
    )
    if spend >= ANTHROPIC_CREDIT_USD:
        return FALLBACK_MODEL
    return DEFAULT_CLAUDE_MODEL
