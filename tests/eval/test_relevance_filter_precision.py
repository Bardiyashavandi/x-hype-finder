"""Precision eval for the Relevance Filter (tasks.md T009, spec.md §6,
contracts/pipeline-stages.md § Relevance Filter acceptance, research.md §3).

A small hand-labeled fixture set of known real "can't find a sublet"-style
complaints mixed with noise (some catchable by the exclude-terms list, some
not — the residual noise `filter_relevance`'s deterministic substring match
can't catch on its own, same caveat `src/pipeline/filter.py`'s
`TIER2_COMPOSITE_SCORE` docstring carries about needing a bigger labeled
sample before fine-tuning further). This is a sanity check before demoing
(spec.md §6's own framing), not a statistically powered claim — the fixture's
`n` is reported alongside the result.

Precision = (relevant posts kept) / (total posts kept) — mirrors Filter's own
`tests/unit/test_filter_tier1.py`-style eval approach, adjusted for this
mode's ≥80% acceptance bar (contracts/pipeline-stages.md § Relevance Filter).
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.pipeline.fetch import AuthorMetadata, RawPost
from src.pipeline.relevance_filter import RelevanceOutcome, filter_relevance

PRECISION_TARGET = 0.80

NOW = datetime(2026, 8, 12, tzinfo=UTC)

EXCLUDE_TERMS = ["sublet.com", "dm me", "check my bio"]

# (post text, is_relevant) — a real complaint/request about the sublet
# problem space vs. noise that happens to contain "sublet" in a different
# sense, or is promotional spam.
_FIXTURE: list[tuple[str, bool]] = [
    # --- Real complaints/requests (relevant) ---
    ("Can't find a sublet for the summer, everyone wants a full year lease", True),
    ("Been searching for 3 weeks for a sublet near campus, nothing available", True),
    ("No easy way to sublet my apartment while I'm abroad for 6 months", True),
    ("Sublet is a nightmare in this city, landlords don't even reply", True),
    ("I need a 4-month sublet and every listing wants a 12-month minimum", True),
    ("Moved for an internship and finding a short sublet has been impossible", True),
    ("Why is there no good app for finding a sublet, I've tried everything", True),
    ("Sublet hunting is exhausting, scams everywhere and nothing legit", True),
    ("Trying to sublet my room for the semester, no one wants short-term", True),
    ("Just gave up looking for a sublet, going with an overpriced Airbnb instead", True),
    ("Anyone know a good way to find a sublet that isn't full of scammers", True),
    ("The sublet market here is broken, everything is gone within an hour", True),
    # --- Noise the exclude-terms list catches (excluded, so not counted as a false positive) ---
    ("Check out sublet.com for all your subletting needs!!", False),
    ("DM me for a great sublet deal, hurry before it's gone", False),
    ("Sublet available, check my bio for details", False),
    # --- Residual noise the deterministic substring filter can't catch (kept, but irrelevant) ---
    ("Just signed a sublet lease for my cat's new luxury condo", False),
    ("Sublet Boulevard is my favorite street to walk down in this city", False),
    ("My favorite band Sublet just dropped a new album, it's incredible", False),
]


def _post(index: int, text: str) -> RawPost:
    return RawPost(
        x_post_id=str(index),
        author_handle=f"fixture_user_{index}",
        text=text,
        posted_at=NOW,
        author_metadata=AuthorMetadata(
            account_age_days=500, followers_count=200, following_count=100, post_frequency=1.0
        ),
    )


def test_relevance_filter_precision_meets_target_on_hand_labeled_fixture():
    posts = [_post(i, text) for i, (text, _is_relevant) in enumerate(_FIXTURE)]
    labels = {str(i): is_relevant for i, (_text, is_relevant) in enumerate(_FIXTURE)}

    results = filter_relevance(posts, EXCLUDE_TERMS)
    kept = [r for r in results if r.relevance_outcome == RelevanceOutcome.KEPT]

    assert kept, "fixture must produce at least one kept post to compute precision"
    relevant_kept = sum(1 for r in kept if labels[r.post.x_post_id])
    precision = relevant_kept / len(kept)

    n = len(_FIXTURE)
    print(
        f"\nRelevance Filter precision: {precision:.2%} (relevant_kept={relevant_kept}, "
        f"kept={len(kept)}, n={n})"
    )

    failure_message = (
        f"precision {precision:.2%} (n={n}) fell below the {PRECISION_TARGET:.0%} target"
    )
    assert precision >= PRECISION_TARGET, failure_message
