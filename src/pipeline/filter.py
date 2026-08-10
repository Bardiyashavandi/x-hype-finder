"""Filter Tier 1 + Tier 2 (tasks.md T035, T037; contracts/pipeline-stages.md § Filter;
research.md §5).

Fully deterministic, two-tier bot/noise filter — no LLM/agent judgment at
either tier (Constitution Principle I):

- Tier 1 (cheap rule-based): per-post heuristics over account age, follower/
  following ratio, posting velocity, duplicate-text ratio, link ratio,
  cashtag-stuffing count, and known spam patterns (including bare/labeled
  contract-address posting), bucketed into clear-keep / clear-exclude /
  ambiguous.
- Tier 2 (escalated only for Tier 1's ambiguous posts): an embedding-based
  coordinated-content check (near-duplicate content from distinct authors in
  a tight time window) combined with a stricter composite threshold over the
  Tier 1 score.

No post is dropped from the record — every post gets a `filter_outcome`
(FR-016), reusing `SourcePost.FilterOutcome` since that's the persisted enum
the orchestrator (a later phase) will write this decision into.
"""

from __future__ import annotations

import enum
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from difflib import SequenceMatcher

import numpy as np

from src.models.source_post import FilterOutcome
from src.pipeline.embedding_provider import get_embedding_provider
from src.pipeline.fetch import RawPost

# --- Tier 1 thresholds (research.md §5) ---
NEW_ACCOUNT_AGE_DAYS = 30
SUSPICIOUS_FOLLOWER_FLOOR = 50
SUSPICIOUS_FOLLOW_RATIO = 10
HIGH_VELOCITY_POSTS_PER_DAY = 50
DUPLICATE_TEXT_SIMILARITY = 0.9
DUPLICATE_RATIO_THRESHOLD = 0.5
LINK_RATIO_THRESHOLD = 0.5
# Real eval-labeled data (2026-08-05 digest review) showed 0 distinct cashtags
# on 375/480 fetched posts and the one legitimate multi-ticker post (genuine
# technical analysis) topped out at 5; ticker-stuffing spam (fake-signal-group
# shills) started at 6 and ran as high as 20 — 6 draws the line without
# touching the observed legitimate case.
CASHTAG_STUFFING_THRESHOLD = 6

CLEAR_EXCLUDE_SCORE = 70.0
CLEAR_KEEP_SCORE = 20.0

_SCORE_NEW_ACCOUNT = 20.0
_SCORE_SUSPICIOUS_FOLLOW_RATIO = 20.0
_SCORE_HIGH_VELOCITY = 20.0
_SCORE_DUPLICATE_TEXT = 25.0
_SCORE_LINK_HEAVY = 10.0
_SCORE_SPAM_PATTERN = 25.0
_SCORE_CASHTAG_STUFFING = 20.0

_URL_PATTERN = re.compile(r"https?://\S+")
_CASHTAG_PATTERN = re.compile(r"\$[A-Za-z]{2,10}\b")
_SPAM_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for pattern in (
        r"\bdm me\b",
        # Was `\bclick (the )?link\b` — missed real spam phrased "click *on
        # the* link" (eval-labeled beallcrypto example) because only a single
        # optional "the " was allowed between the two words. Widened to allow
        # up to 15 chars of filler ("on the", "this", "that below", ...).
        r"\bclick\b.{0,15}\blink\b",
        r"\bcheck (out )?my bio\b",
        r"\bguaranteed profit(s)?\b",
        r"\b\d{2,}x gains?\b",
        r"\bfree airdrop\b",
        r"\bfollow (me )?(and )?(i('ll)? )?follow back\b",
        # Wallet-solicitation/giveaway-bait: real eval labels showed Tier 1
        # consistently missing posts asking people to drop/comment/send their
        # wallet address for a fake airdrop/giveaway/prize. No single exact
        # phrase covers this — it's a co-occurrence of three separate cues
        # (wallet + a solicit verb + a giveaway word), hence the lookaheads
        # rather than one linear pattern like the phrases above.
        r"(?=.*\bwallet\b)(?=.*\b(?:drop|comment|send)\b)"
        r"(?=.*\b(?:airdrop|giveaway|winner(?:s)?)\b)",
        # Bare/labeled contract-address posting: real eval labels showed
        # Tier 1 missing "gem caller"/pump.fun-migration bot templates that
        # paste a raw token address inline (0x hex, a `solana:` URI, a `CA:`
        # label, or the literal phrase "contract address") — e.g. real
        # examples CSRcoinOfficial ("Official Contract Address (CA): Fsu...
        # pump"), GemChaserSOL ("CA:\n0x020bfC65..."), thetillydog
        # ("solana:5Jvxc2c6...pump"). Legitimate hype/community accounts talk
        # about tokens by name/ticker, not by pasting mint addresses, so this
        # is a near-zero-false-positive cue in this domain.
        r"\b0x[a-fA-F0-9]{38,40}\b"
        r"|\bsolana:[1-9A-HJ-NP-Za-km-z]{32,44}\b"
        r"|\bCA\s*:\s*[1-9A-HJ-NP-Za-km-z]{32,44}\b"
        r"|\bcontract address\b",
    )
)

# --- Tier 2 thresholds (research.md §5) ---
COORDINATED_SIMILARITY_THRESHOLD = 0.92
COORDINATED_TIME_WINDOW = timedelta(hours=2)
COORDINATED_MIN_DISTINCT_AUTHORS = 2
# Known, intentionally-deferred gap (PR #21): CLEAR_KEEP_SCORE, CLEAR_EXCLUDE_SCORE,
# TIER2_COMPOSITE_SCORE, and LINK_RATIO_THRESHOLD are untouched since that PR's detector
# additions above. A lone, non-coordinated spam-pattern hit scores 25 -> lands in `ambiguous`,
# and only actually gets excluded via Tier 2 if it's part of a coordinated swarm or the
# composite reaches 50 -- so a solo spam post can still fall through as `kept`. Tuning these
# thresholds needs a bigger labeled sample than the FILTER-stage eval set currently has (n=10,
# target >=50 per SC-002) to validate against before it ships. See README Roadmap "Open".
TIER2_COMPOSITE_SCORE = 50.0  # stricter than Tier 1's clear-exclude threshold


class Tier1Decision(enum.StrEnum):
    CLEAR_KEEP = "clear_keep"
    CLEAR_EXCLUDE = "clear_exclude"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class Tier1Result:
    score: float
    decision: Tier1Decision
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class FilteredPost:
    post: RawPost
    filter_outcome: FilterOutcome
    tier1_score: float
    tier1_decision: Tier1Decision


def _normalize(text: str) -> str:
    without_links = _URL_PATTERN.sub("", text)
    return " ".join(without_links.lower().split())


def _duplicate_ratio(index: int, normalized_texts: list[str]) -> float:
    if len(normalized_texts) <= 1:
        return 0.0
    target = normalized_texts[index]
    if not target:
        return 0.0
    matches = sum(
        1
        for i, other in enumerate(normalized_texts)
        if i != index and SequenceMatcher(None, target, other).ratio() >= DUPLICATE_TEXT_SIMILARITY
    )
    return matches / (len(normalized_texts) - 1)


def _link_ratio(text: str) -> float:
    if not text:
        return 0.0
    url_chars = sum(len(match.group(0)) for match in _URL_PATTERN.finditer(text))
    return url_chars / len(text)


def _matches_spam_pattern(text: str) -> bool:
    return any(pattern.search(text) for pattern in _SPAM_PATTERNS)


def _distinct_cashtag_count(text: str) -> int:
    return len({match.upper() for match in _CASHTAG_PATTERN.findall(text)})


def score_tier1(posts: list[RawPost]) -> dict[str, Tier1Result]:
    """Score every post 0-100 on cheap rule-based bot/noise signals.

    Batch-level (duplicate-text ratio) and per-post (account/velocity/link/
    spam) signals are combined into one composite score per research.md §5.
    """
    normalized_texts = [_normalize(post.text) for post in posts]
    results: dict[str, Tier1Result] = {}

    for i, post in enumerate(posts):
        meta = post.author_metadata
        reasons: list[str] = []
        score = 0.0

        if meta.account_age_days < NEW_ACCOUNT_AGE_DAYS:
            score += _SCORE_NEW_ACCOUNT
            reasons.append("new_account")

        if (
            meta.followers_count < SUSPICIOUS_FOLLOWER_FLOOR
            and meta.following_count > max(meta.followers_count, 1) * SUSPICIOUS_FOLLOW_RATIO
        ):
            score += _SCORE_SUSPICIOUS_FOLLOW_RATIO
            reasons.append("suspicious_follow_ratio")

        if meta.post_frequency > HIGH_VELOCITY_POSTS_PER_DAY:
            score += _SCORE_HIGH_VELOCITY
            reasons.append("high_velocity")

        if _duplicate_ratio(i, normalized_texts) >= DUPLICATE_RATIO_THRESHOLD:
            score += _SCORE_DUPLICATE_TEXT
            reasons.append("duplicate_text")

        if _link_ratio(post.text) >= LINK_RATIO_THRESHOLD:
            score += _SCORE_LINK_HEAVY
            reasons.append("link_heavy")

        if _matches_spam_pattern(post.text):
            score += _SCORE_SPAM_PATTERN
            reasons.append("spam_pattern")

        if _distinct_cashtag_count(post.text) >= CASHTAG_STUFFING_THRESHOLD:
            score += _SCORE_CASHTAG_STUFFING
            reasons.append("cashtag_stuffing")

        score = min(score, 100.0)
        if score >= CLEAR_EXCLUDE_SCORE:
            decision = Tier1Decision.CLEAR_EXCLUDE
        elif score <= CLEAR_KEEP_SCORE:
            decision = Tier1Decision.CLEAR_KEEP
        else:
            decision = Tier1Decision.AMBIGUOUS

        results[post.x_post_id] = Tier1Result(
            score=score, decision=decision, reasons=tuple(reasons)
        )

    return results


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    vec_a, vec_b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    denom = np.linalg.norm(vec_a) * np.linalg.norm(vec_b)
    if denom == 0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / denom)


def _is_coordinated(
    post: RawPost,
    embedding: list[float],
    all_posts: list[RawPost],
    all_embeddings: dict[str, list[float]],
) -> bool:
    """Flag near-duplicate content posted by distinct accounts in a tight
    time window — a signature of coordinated/bot amplification a single-post
    rule check misses (research.md §5)."""
    distinct_authors: set[str] = set()
    for other in all_posts:
        if other.x_post_id == post.x_post_id or other.author_handle == post.author_handle:
            continue
        if (
            abs((other.posted_at - post.posted_at).total_seconds())
            > COORDINATED_TIME_WINDOW.total_seconds()
        ):
            continue
        other_embedding = all_embeddings.get(other.x_post_id)
        if other_embedding is None:
            continue
        if _cosine_similarity(embedding, other_embedding) >= COORDINATED_SIMILARITY_THRESHOLD:
            distinct_authors.add(other.author_handle)
        if len(distinct_authors) >= COORDINATED_MIN_DISTINCT_AUTHORS:
            return True
    return False


def apply_tier2(
    ambiguous_posts: list[RawPost],
    all_posts: list[RawPost],
    tier1_results: dict[str, Tier1Result],
    *,
    embed_fn: Callable[[list[str]], list[list[float]]],
) -> dict[str, FilterOutcome]:
    """Escalate Tier 1's ambiguous posts to the embedding-based coordinated-
    content check, falling back to a stricter composite threshold over the
    Tier 1 score when no coordination signature is found."""
    if not ambiguous_posts:
        return {}

    vectors = embed_fn([post.text for post in all_posts])
    all_embeddings = {
        post.x_post_id: vector for post, vector in zip(all_posts, vectors, strict=True)
    }

    outcomes: dict[str, FilterOutcome] = {}
    for post in ambiguous_posts:
        embedding = all_embeddings[post.x_post_id]
        if _is_coordinated(post, embedding, all_posts, all_embeddings):
            outcomes[post.x_post_id] = FilterOutcome.EXCLUDED_DEEPER_CHECK
            continue
        if tier1_results[post.x_post_id].score >= TIER2_COMPOSITE_SCORE:
            outcomes[post.x_post_id] = FilterOutcome.EXCLUDED_DEEPER_CHECK
        else:
            outcomes[post.x_post_id] = FilterOutcome.KEPT

    return outcomes


def filter_posts(
    posts: list[RawPost],
    *,
    embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
) -> list[FilteredPost]:
    """Run the full two-tier Filter stage over one topic's fetched posts.

    Tier 2 (and its embedding provider call) only runs when Tier 1 leaves at
    least one post ambiguous — clear-keep/clear-exclude posts never pay for
    an embedding call, or for resolving which embedding provider to use.
    """
    tier1_results = score_tier1(posts)
    ambiguous = [
        post for post in posts if tier1_results[post.x_post_id].decision == Tier1Decision.AMBIGUOUS
    ]
    if ambiguous:
        resolved_embed_fn = embed_fn if embed_fn is not None else get_embedding_provider()
        tier2_outcomes = apply_tier2(ambiguous, posts, tier1_results, embed_fn=resolved_embed_fn)
    else:
        tier2_outcomes = {}

    filtered: list[FilteredPost] = []
    for post in posts:
        tier1 = tier1_results[post.x_post_id]
        if tier1.decision == Tier1Decision.CLEAR_KEEP:
            outcome = FilterOutcome.KEPT
        elif tier1.decision == Tier1Decision.CLEAR_EXCLUDE:
            outcome = FilterOutcome.EXCLUDED_RULE
        else:
            outcome = tier2_outcomes[post.x_post_id]
        filtered.append(
            FilteredPost(
                post=post,
                filter_outcome=outcome,
                tier1_score=tier1.score,
                tier1_decision=tier1.decision,
            )
        )
    return filtered
