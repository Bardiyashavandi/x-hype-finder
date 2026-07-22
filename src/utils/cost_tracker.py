"""Cumulative cost tracking against the one-time $50 budget (tasks.md T022,
Constitution VI, SC-012; added per /speckit-analyze finding C1).

Kept deliberately separate from the main SQLite schema (src/db/) — this is an
append-only ledger, not a domain entity from data-model.md, so it doesn't
need an ORM model or migration. Each cost event is appended as one JSON line;
the running total is the sum of the ledger on read. For this MVP's write
volume (roughly one entry per topic per run, ~30 runs/month) that's more than
fast enough and keeps the write path a simple, race-free append.

Used by T059 (a later phase) to decide, at the week-3 validation-period
checkpoint, whether to keep Summarize/Draft Post on claude-sonnet-5 or
downgrade to claude-haiku-4-5-20251001 (research.md §3).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

TOTAL_BUDGET_USD = 50.00

# research.md §6: TwitterAPI.io, ~$0.15 per 1,000 read posts, flat.
TWITTERAPI_IO_COST_PER_1K_READS = 0.15

# research.md §3: per-million-token pricing for the two models Summarize/Draft
# Post may run under (Sonnet during weeks 1-3, reassessed at the week-3 switch).
CLAUDE_PRICING_PER_MILLION_TOKENS = {
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
}


@dataclass(frozen=True)
class CostEntry:
    timestamp: float
    source: str  # "twitterapi_io" | "claude"
    amount_usd: float
    detail: dict


def _ledger_path() -> Path:
    return Path(os.environ.get("XHF_COST_LEDGER_PATH", ".data/cost_ledger.jsonl"))


def _append_entry(entry: CostEntry) -> None:
    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(asdict(entry)) + "\n")


def record_twitterapi_io_read(post_count: int) -> float:
    """Record the cost of one TwitterAPI.io fetch call and return that cost in USD."""
    amount = (post_count / 1000) * TWITTERAPI_IO_COST_PER_1K_READS
    _append_entry(CostEntry(time.time(), "twitterapi_io", amount, {"post_count": post_count}))
    return amount


def record_claude_usage(model: str, input_tokens: int, output_tokens: int) -> float:
    """Record the cost of one Claude API call (Summarize or Draft Post) and return it in USD."""
    pricing = CLAUDE_PRICING_PER_MILLION_TOKENS.get(model)
    if pricing is None:
        raise ValueError(
            f"Unknown Claude model for cost tracking: {model!r}. "
            f"Add its per-token pricing to CLAUDE_PRICING_PER_MILLION_TOKENS."
        )
    amount = (input_tokens / 1_000_000) * pricing["input"] + (output_tokens / 1_000_000) * pricing[
        "output"
    ]
    _append_entry(
        CostEntry(
            time.time(),
            "claude",
            amount,
            {"model": model, "input_tokens": input_tokens, "output_tokens": output_tokens},
        )
    )
    return amount


def get_cumulative_spend() -> float:
    """Sum every recorded cost entry to date, in USD."""
    path = _ledger_path()
    if not path.exists():
        return 0.0
    total = 0.0
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                total += json.loads(line)["amount_usd"]
    return total


def get_budget_remaining() -> float:
    """USD remaining out of the fixed one-time $50 total (Constitution VI)."""
    return TOTAL_BUDGET_USD - get_cumulative_spend()
