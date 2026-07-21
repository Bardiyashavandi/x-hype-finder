# Pipeline Stage Contracts

**Feature**: 001-x-hype-finder-mvp

Per Constitution Principle I, Fetch/Filter/Detect/Cluster MUST each take a defined input and
produce a reproducible, independently testable output, with no LLM/agent judgment. Summarize
and Draft Post are the two LLM-powered stages. Every stage boundary below is a real function
boundary — each is unit/contract-testable in isolation, matching Principle VII's measurable
definition of done.

```
Topics ─▶ Fetch ─▶ Filter ─▶ Detect ─▶ Cluster ─▶ Summarize ─▶ Rank ─▶ Draft Post ─▶ (hold | publish)
          └──────────── deterministic ────────────┘   └──── LLM ────┘
```

---

## Fetch

- **Input**: one `Topic` (name + optional handles) + a time window (default: since last
  successful run for this topic, or a configured lookback for a brand-new topic).
- **Output**: list of raw posts `{x_post_id, author_handle, text, posted_at, author_metadata}`
  from the TwitterAPI.io provider (research §6), OR a per-topic error record (FR-002) that does
  NOT halt Fetch for other topics in the same run.
- **Retry**: transient errors retry with backoff (FR-018) before being recorded as a fetch
  error; partial multi-topic results are preserved (edge case: rate limits mid-run) —
  `DigestTopicResult.outcome = incomplete_rate_limited` for affected topics.

## Filter

- **Input**: raw posts for one topic (Fetch output).
- **Output**: each post tagged `filter_outcome ∈ {kept, excluded_rule, excluded_deeper_check}`.
  No post is dropped from the record — exclusions are recorded, not deleted, so the filtering
  trail is drillable (FR-016).
- **Tiering** (research §5, fully deterministic, no LLM at either tier):
  - Tier 1: per-post rule scoring (account age, follower/following ratio, posting velocity,
    duplicate-text ratio, link ratio, known spam patterns) → clear-keep, clear-exclude, or
    ambiguous.
  - Tier 2 (ambiguous only): embedding-based coordinated-content check + stricter composite
    threshold over the Tier 1 features.
- **Acceptance**: ≥90% of a labeled 50-post bot/spam test set excluded (FR-003, SC-002).

## Detect

- **Input**: this run's `kept` post count for a topic + that topic's `TopicBaselineSnapshot`
  history.
- **Output**: `{is_spike: bool, spike_ratio: decimal}`.
- **Rules** (FR-004, FR-005, deterministic): `is_spike = false` unconditionally while
  `Topic.observation_period_active` (first 7 days); otherwise `is_spike = (current_filtered_count
  / trailing_baseline_mean) ≥ 3.0`.

## Cluster

- **Input**: `kept` posts for a topic (post-Detect; Detect only needs the count, so Cluster can
  run in parallel with/after Detect).
- **Output**: groups of posts (`Theme` candidates) by embedding similarity (`nomic-embed-text`,
  research §4) — near-duplicate/related posts collapsed into one group rather than shown flat.
- **Acceptance**: given 50+ filtered posts with near-duplicates, near-duplicates land in the same
  group (FR-006, User Story 1 Acceptance Scenario 4).

## Summarize (LLM stage — Claude Sonnet 5 during weeks 1-3, reassessed at the week-3 switch per research §3)

- **Input**: one cluster's post texts + deterministic context signals (`spike_ratio`,
  `cluster_post_count`, filter-survival rate, account-diversity count of the cluster).
- **Output** (structured/tool-call schema, not free text): `{summary: string, rationale:
  string, confidence_score: integer 0-100}` (FR-007).
- **Grounding rule** (research §12): `confidence_score` MUST be derived using the passed-in
  deterministic signals as context, not invented from raw text alone.

## Rank

- **Input**: all Themes produced for a user's run across all their topics.
- **Output**: Themes ordered descending by significance (spike_ratio × confidence, or
  equivalent), each annotated with `rank` (FR-008).

## Draft Post (LLM stage — Claude Sonnet 5 during weeks 1-3, reassessed at the week-3 switch per research §3)

- **Input**: a high-signal Theme (summary + rationale + example posts).
- **Output**: `draft_text` for a `DraftPost`, `status` assigned per the `PostingMode` state
  machine in effect at creation time (data-model.md).

## Post (manual hand-off or autonomous publish)

- **Input**: a `DraftPost` with `status = held_manual` (no-op, awaiting user action) or a
  confidence-cleared draft under `mode = autonomous`.
- **Output** (autonomous only): publish attempt via `tweepy` against the official X API →
  `published_auto` or `publish_failed` (FR-019, never silently dropped). Gated by the
  `PostingMode` validations in data-model.md (bio-label check, validation-period check,
  24h/5-post cap, kill switch, jittered timing).
