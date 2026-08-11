# Data Model: Idea Validation Mode

**Feature**: 002-idea-validation-mode

Per research.md §1, this feature adds **no new SQLAlchemy models or database tables**. Every
entity below is a plain in-memory `dataclass`, living only for the duration of one CLI run — none
of them are persisted. This section documents their shape as the equivalent of a data model
because they're the real contract between this feature's stages, even though nothing here reaches
the database.

```
IdeaValidationQuery ─▶ Fetch ─▶ RawPost[] ─▶ Relevance Filter ─▶ Bot/Noise Filter ─▶
    RelevantPost[] ─▶ Signal Strength ─▶ Cluster ─▶ Validate Summarize ─▶ ValidationReadout
```

---

## IdeaValidationQuery

The CLI input, parsed once at the start of a run.

| Field | Type | Notes |
|---|---|---|
| `phrases` | `list[str]` | 1-8 problem-describing phrases (e.g. `"can't find sublet"`). At least one required — `idea-validate run` rejects an empty list with a clear error, mirroring `topic add`'s empty-name rejection (`src/cli/topic.py`). |
| `exclude_terms` | `list[str]` | 0-N terms/phrases to exclude, both at query-construction time and at Relevance Filter time (research.md §3). Empty list is valid — exclusion is optional. |
| `since` / `until` | `datetime` | Fetch window; defaults mirror `fetch_topic_posts`'s `DEFAULT_LOOKBACK` (`src/pipeline/fetch.py`) unless overridden. |

**Validation rules**: `phrases` non-empty after stripping whitespace from each entry (same
`.strip()` pattern as `Topic.name` in `src/cli/topic.py`); duplicate phrases/exclude-terms are
de-duplicated case-insensitively before query construction, to avoid an inflated/broken OR clause.

---

## RawPost

**Reused as-is** from `src/pipeline/fetch.py` — no change. Idea Validation mode calls the same
`fetch_posts_for_query` primitive (research.md §4) that produces this type today.

---

## RelevantPost

The Relevance Filter's output wrapper (`src/pipeline/relevance_filter.py`), one per `RawPost`.

| Field | Type | Notes |
|---|---|---|
| `post` | `RawPost` | The original fetched post — never mutated. |
| `relevance_outcome` | `RelevanceOutcome` (enum: `KEPT` \| `EXCLUDED_TERM_MATCH`) | Mirrors `FilterOutcome`'s "no post is dropped from the record" principle (`src/models/source_post.py`'s docstring) — every post gets a recorded decision, even though nothing here is persisted to a table. |
| `matched_term` | `str \| None` | Which `exclude_terms` entry triggered exclusion, if any — for debuggability in the readout's optional verbose mode. |

**State transition**: `RawPost` → (Relevance Filter) → `RelevantPost` → (Bot/Noise Filter, reusing
`src/pipeline/filter.py`'s existing `FilteredPost` type unchanged, operating only on
`relevance_outcome == KEPT` posts) → the set that flows into Signal Strength + Cluster.

---

## SignalStrength

The Detect-stage equivalent (`src/pipeline/signal_strength.py`) — absolute volume/recency instead
of a baseline-relative spike ratio, per spec.md §5.2's "Detect" row and research.md's framing.

| Field | Type | Notes |
|---|---|---|
| `total_relevant_count` | `int` | Count of posts that survived both Relevance Filter and Bot/Noise Filter. |
| `distinct_author_count` | `int` | Same "account diversity" concept `orchestrator.py` already computes per-cluster (`len({post.author_handle for post in candidate.posts})`), computed here across the whole result set. |
| `most_recent_post_at` / `oldest_post_at` | `datetime \| None` | `None` only when `total_relevant_count == 0`. |
| `posts_last_24h` / `posts_last_7d` | `int` | Recency buckets — substitutes for "is this spiking now" when there's no historical baseline to compare against (spec.md §5.2). |

**No `is_spike`/`spike_ratio` field exists here** — this is a deliberate, documented absence
(research.md §5), not an oversight: those concepts only make sense with the historical baseline
this mode explicitly doesn't have.

---

## ValidationTheme

One cluster's output after `summarize_validation_theme` (`src/agent/validate_summarize.py`) —
the Idea Validation analogue of `Theme` (`src/models/theme.py`), but never persisted and carrying
different fields.

| Field | Type | Notes |
|---|---|---|
| `summary` | `str` | Plain-language statement of the recurring want/frustration (not "why this is trending" — research.md §5). |
| `representative_ask` | `str` | The concrete thing people are asking for/complaining about, distinct from `summary` (a one-line "in their own words" framing) — grounds the readout in real language a strategist can quote back to a client. |
| `recurrence_signal` | `str` (enum-like: `"isolated"` \| `"emerging"` \| `"recurring"`) | Grounded in `cluster_post_count` + `distinct_author_count` (same deterministic-grounding principle `summarize.py`'s `confidence_score` uses, research.md §5) — not a free-floating LLM judgment. |
| `cluster_post_count` | `int` | Same meaning as `Theme.cluster_post_count`. |
| `example_post_texts` | `list[str]` | 3-5 curated examples, same `_MIN_EXAMPLE_POSTS`/`_MAX_EXAMPLE_POSTS` convention as `orchestrator.py`. |

---

## ValidationReadout

The final output object `report/validation_readout.py` assembles and the CLI prints/writes — the
Idea Validation analogue of `Digest`, but a plain dataclass, not a DB row.

| Field | Type | Notes |
|---|---|---|
| `query` | `IdeaValidationQuery` | Echoed back so the readout is self-describing (what was searched, what was excluded). |
| `signal_strength` | `SignalStrength` | |
| `themes` | `list[ValidationTheme]` | Ordered by `cluster_post_count` descending (ties broken by `distinct_author_count`, then original order) — same stable-sort spirit as `rank_themes` (`src/pipeline/rank.py`), but simpler since there's no cross-topic ranking need (only one ad-hoc query per run). |
| `generated_at` | `datetime` | Run timestamp, for the printed/written readout's header. |

**Acceptance framing** (spec.md §7): a `ValidationReadout` with `signal_strength.total_relevant_count
== 0` or `themes == []` still prints a complete, explicit readout ("no meaningful signal found") —
mirroring `DigestTopicOutcome`'s principle that a topic/query never silently vanishes
(`src/models/digest_topic_result.py`'s docstring) — rather than an empty/blank output.
