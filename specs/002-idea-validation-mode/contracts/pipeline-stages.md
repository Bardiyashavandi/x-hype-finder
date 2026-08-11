# Pipeline Stage Contracts

**Feature**: 002-idea-validation-mode

Per Constitution Principle I, every deterministic stage below MUST take a defined input and
produce a reproducible, independently testable output, with no LLM/agent judgment. Validate
Summarize is the sole LLM-powered stage. Every stage boundary is a real function boundary —
unit/contract-testable in isolation, matching Principle VII.

```
IdeaValidationQuery ─▶ Fetch ─▶ Relevance Filter ─▶ Bot/Noise Filter ─▶ Signal Strength ─▶
    Cluster ─▶ Validate Summarize ─▶ Validation Readout
    └─────────────────────────── deterministic ───────────────────────────┘   └── LLM ──┘   └ deterministic ┘
```

No stage here performs autonomous posting or reads/writes `PostingMode`/`DraftPost` — see
research.md §6.

---

## Query Construction

- **Input**: `IdeaValidationQuery.phrases` (1-8 strings) + `IdeaValidationQuery.exclude_terms`
  (0-N strings) + a `[since, until)` window.
- **Output**: one X advanced-search query string, OR-ing every phrase (quoted exact-phrase, same
  quoting convention as `build_search_query` in `src/pipeline/query_builder.py`) and appending a
  `-"term"` clause per exclude term where the term is a clean phrase (research.md §3 — this is a
  cost-reduction pass, not the sole relevance guarantee).
- **Function**: `build_idea_validation_query(phrases, exclude_terms, since, until) ->
  str` in `src/pipeline/idea_query_builder.py`.
- **Acceptance**: given `phrases=["can't find sublet", "no easy way to sublet"]`, the query
  contains both phrases OR'd together, each independently quoted; given a non-empty
  `exclude_terms`, each appears as a negated clause in the output string.

## Fetch

- **Input**: the query string from Query Construction (not a `Topic`).
- **Output**: `list[RawPost]` (unchanged type from `src/pipeline/fetch.py`) or a `FetchError` —
  identical error semantics to the existing Fetch stage (rate-limit vs. generic error
  classification, retry-with-backoff before giving up).
- **Function**: `fetch_posts_for_query(query, *, api_key, max_posts, session) -> FetchResult`,
  extracted from the existing `fetch_topic_posts` per research.md §4. `fetch_topic_posts` itself
  is unchanged from the caller's perspective — this is an internal refactor.
- **Acceptance**: identical pagination/rate-limit-pacing behavior to the existing Fetch stage,
  verified by the existing `tests/contract/test_twitterapi_io.py` continuing to pass unmodified
  against the refactored internals.

## Relevance Filter

- **Input**: `list[RawPost]` (Fetch output) + `IdeaValidationQuery.exclude_terms`.
- **Output**: `list[RelevantPost]` (data-model.md), each tagged
  `relevance_outcome ∈ {kept, excluded_term_match}`. No post is dropped from the record — mirrors
  `FilterOutcome`'s "every post gets an outcome" principle even though nothing here is persisted.
- **Rule** (fully deterministic, no LLM): case-insensitive substring match of each exclude term
  against the post's normalized text (reusing the `_normalize` link-stripping/lowercasing/
  whitespace-collapsing helper pattern from `src/pipeline/filter.py`); first match wins and is
  recorded as `matched_term`.
- **Function**: `filter_relevance(posts, exclude_terms) -> list[RelevantPost]` in
  `src/pipeline/relevance_filter.py`.
- **Acceptance** (spec.md §6): on the hand-labeled real-complaint-vs-noise fixture set
  (`tests/eval/test_relevance_filter_precision.py`), precision (relevant posts kept ÷ posts kept)
  meets a stated minimum threshold — set at ≥80%, the same order of magnitude as Filter's own
  ≥90% FR-003/SC-002 bot-exclusion target, adjusted down slightly since relevance-vs-noise
  judgment on broad problem phrases is inherently noisier than a fixed brand name (spec.md §5.1).
  Document the fixture set's n alongside the reported number, same caveat `filter.py`'s
  `TIER2_COMPOSITE_SCORE` docstring already carries about needing a bigger labeled sample before
  fine-tuning further.

## Bot/Noise Filter

- **Input**: `list[RawPost]` restricted to `relevance_outcome == kept` posts from Relevance
  Filter.
- **Output**: `list[FilteredPost]` — **unchanged type and logic** from `src/pipeline/filter.py`'s
  existing `filter_posts` (Tier 1 rule scoring + Tier 2 embedding coordinated-content check). No
  new code; this stage is reused, not reimplemented (spec.md §5.2 "Filter (bot/noise): No
  change.").
- **Acceptance**: identical to the existing Filter stage's own contract
  (`specs/001-x-hype-finder-mvp/contracts/pipeline-stages.md` § Filter) — no new acceptance bar,
  since no new code is introduced here.

## Signal Strength

- **Input**: posts that survive both Relevance Filter and Bot/Noise Filter (`kept` on both).
- **Output**: one `SignalStrength` (data-model.md) — `total_relevant_count`,
  `distinct_author_count`, `most_recent_post_at`/`oldest_post_at`, `posts_last_24h`/`posts_last_7d`.
- **Function**: `compute_signal_strength(posts, *, now) -> SignalStrength` in
  `src/pipeline/signal_strength.py`.
- **Rules** (fully deterministic — this mode's Detect-equivalent, spec.md §5.2): no baseline
  comparison, no `is_spike` boolean, no 7-day observation gate (there is no history to observe
  against) — see research.md §5 for why those fields don't exist here.
- **Acceptance**: given zero surviving posts, returns `total_relevant_count=0` and
  `most_recent_post_at=None`/`oldest_post_at=None` rather than raising — mirroring
  `DigestTopicOutcome.NO_SIGNIFICANT_ACTIVITY`'s "state the explicit no-activity outcome, never an
  empty/missing entry" principle.

## Cluster

- **Input**: posts that survived Signal Strength's input set (same set, Cluster doesn't need
  Signal Strength's output, only runs after it in this pipeline's ordering for stage-numbering
  clarity — the two could run in parallel, mirroring the existing Detect/Cluster relationship
  noted in `specs/001-x-hype-finder-mvp/contracts/pipeline-stages.md` § Cluster).
- **Output**: `list[ThemeCandidate]` — **unchanged type and logic** from
  `src/pipeline/cluster.py`'s existing `cluster_posts` (embedding-similarity grouping,
  `CLUSTER_SIMILARITY_THRESHOLD = 0.75`). No new code (spec.md §5.2 "Cluster: No change.").

## Validate Summarize

- **Input**: one `ThemeCandidate`'s post texts + this mode's deterministic context signals
  (`cluster_post_count`, `distinct_author_count` for that cluster, and the problem phrases being
  validated against, for prompt grounding).
- **Output**: one `ValidationTheme` (data-model.md) — `summary`, `representative_ask`,
  `recurrence_signal`.
- **Function**: `summarize_validation_theme(data, *, api_key, model) -> ValidationSummarizeResult`
  in `src/agent/validate_summarize.py`, mirroring `summarize_theme`'s structured-tool-call pattern
  (grammar-constrained Claude tool schema, `retry_with_backoff`, `record_claude_usage`).
- **Prompt framing** (research.md §5): "summarize what people want/are frustrated by," not "why is
  this trending." `recurrence_signal` is grounded in `cluster_post_count`/`distinct_author_count`
  the same way `summarize.py`'s `confidence_score` is grounded in `spike_ratio` — never invented
  from post text alone.
- **Failure mode**: same as `summarize_theme` — a persistent Claude failure or malformed tool
  response raises a `ValidateSummarizeError`; the caller (`idea_validate.py`) excludes that one
  theme from the readout with a logged note rather than failing the whole run, mirroring
  `orchestrator.py`'s `_summarize_candidates` failure handling.

## Validation Readout

- **Input**: `IdeaValidationQuery` (echoed) + `SignalStrength` + `list[ValidationTheme]`.
- **Output**: one `ValidationReadout` (data-model.md), rendered to stdout and optionally written
  to `--out <path>` as plain text/Markdown.
- **Function**: `build_validation_readout(query, signal_strength, themes, *, now) ->
  ValidationReadout` plus a `render_validation_readout(readout) -> str` formatter, both in
  `src/report/validation_readout.py`.
- **Ordering rule**: `themes` sorted by `cluster_post_count` descending, ties broken by
  `distinct_author_count` then original input order (data-model.md).
- **Acceptance** (spec.md §7): zero-signal case (`signal_strength.total_relevant_count == 0` or
  `themes == []`) still renders a complete readout stating "no meaningful signal found" — never a
  blank/empty output.
