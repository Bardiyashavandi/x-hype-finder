# Phase 1 Data Model: X Hype Finder MVP

**Feature**: 001-x-hype-finder-mvp | **Date**: 2026-07-21

Storage: SQLite, one file per deployment, all tables scoped by `user_id` for isolation
(FR-015). Source: spec's Key Entities section, expanded with fields/relationships/validation
derived from the functional requirements and research decisions.

---

## User

Represents one of the two MVP users (FR-015, User Story 5).

| Field | Type | Notes |
|---|---|---|
| `id` | UUID/PK | |
| `email` | string, unique | notification target (FR-023) |
| `x_account_handle` | string | the account this user posts as |
| `created_at` | timestamp | |

**Isolation rule**: every other table below carries a `user_id` foreign key; all queries MUST
filter by the authenticated user's `id`. No table is shared across users.

---

## Topic

A tracked keyword/ticker belonging to one user (FR-001).

| Field | Type | Notes |
|---|---|---|
| `id` | UUID/PK | |
| `user_id` | FK → User | |
| `name` | string | keyword or ticker |
| `x_handles` | string[] | optional associated handles |
| `status` | enum: `active`, `removed` | removal is a soft delete so history/baseline can persist if re-added |
| `first_tracked_at` | timestamp | anchors the 7-day observation window (FR-005) |
| `created_at`, `updated_at` | timestamp | |

**Validation**:
- `name` required, non-empty, unique per `user_id` among `active` topics.
- `observation_period_active` (derived, not stored) = `now() - first_tracked_at < 7 days`. When
  true, Detect MUST NOT flag a spike regardless of activity (FR-005).

**Relationships**: one Topic → many `TopicBaselineSnapshot`, many `SourcePost`, many `Digest`
entries (via Theme).

---

## TopicBaselineSnapshot

The system-maintained historical activity baseline referenced in FR-004/FR-020. Stored as
aggregated counts, not raw posts, so raw source data doesn't have to be retained long-term.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID/PK | |
| `topic_id` | FK → Topic | |
| `window_date` | date | one row per day of filtered-activity count |
| `filtered_post_count` | integer | count of posts that survived Filter that day |
| `created_at` | timestamp | |

**Validation**: exactly one row per `(topic_id, window_date)`. Baseline for a run = rolling
mean of `filtered_post_count` over the trailing N days, excluding the current run's own window.
Per research §5/FR-004: current filtered activity ≥ `baseline mean + k * effective standard
deviation` (k = 2.5) ⇒ spike, where the effective standard deviation is the larger of the
trailing window's own stdev and a Poisson noise floor (`sqrt(baseline mean)`) — a fixed ratio
like a flat 3x is miscalibrated across volume regimes, since count-data variance scales with
its mean, so scaling the threshold to each topic's own variance replaces one fixed ratio that
was simultaneously too loose for low-volume topics and too tight for high-volume ones.

**Retention**: this table (aggregates only) is the durable historical record; it is what FR-020
means by "what is needed to maintain each topic's ongoing historical baseline." Raw `SourcePost`
rows are pruned after a run completes and its baseline snapshot is written (see SourcePost
retention note below).

---

## Digest

A ranked collection of Themes produced by one run — scheduled or on-demand (FR-009).

| Field | Type | Notes |
|---|---|---|
| `id` | UUID/PK | |
| `user_id` | FK → User | |
| `run_type` | enum: `scheduled`, `on_demand` | |
| `started_at`, `completed_at` | timestamp | completion drives the FR-023 notification |
| `status` | enum: `completed`, `partial`, `failed` | `partial` when a topic-level fetch/processing error occurred but other topics succeeded (edge case: rate limits mid-run) |
| `notification_sent_at` | timestamp, nullable | |

**Relationships**: one Digest → many `DigestTopicResult` (one per tracked topic covered by the
run, including topics with "no significant activity" or "all filtered as noise" per FR-017 — a
topic is never silently omitted).

---

## DigestTopicResult

Per-topic outcome within one Digest run — the entity that lets a topic appear in a digest even
when it has nothing to show (edge cases in spec.md).

| Field | Type | Notes |
|---|---|---|
| `id` | UUID/PK | |
| `digest_id` | FK → Digest | |
| `topic_id` | FK → Topic | |
| `outcome` | enum: `themes_present`, `no_significant_activity`, `all_filtered_as_noise`, `fetch_error`, `incomplete_rate_limited` | drives which explicit message is rendered (FR-017) |
| `error_detail` | string, nullable | populated for `fetch_error` (FR-002) |

**Relationships**: one `DigestTopicResult` → many `Theme` (only when `outcome = themes_present`).

---

## SourcePost

A single retrieved post for a topic, carrying its filter outcome and cluster assignment
(spec's Key Entities).

| Field | Type | Notes |
|---|---|---|
| `id` | UUID/PK | |
| `topic_id` | FK → Topic | |
| `digest_topic_result_id` | FK → DigestTopicResult | which run this observation belongs to |
| `x_post_id` | string | source platform's post id |
| `author_handle` | string | |
| `text` | string | |
| `posted_at` | timestamp | |
| `filter_outcome` | enum: `kept`, `excluded_rule`, `excluded_deeper_check` | which Filter tier excluded it, if any (research §5) |
| `theme_id` | FK → Theme, nullable | set only when `filter_outcome = kept` and clustering has run |

**Retention (FR-020)**: rows in this table are retained only long enough to serve drill-down
for the digest they belong to and to compute the day's `TopicBaselineSnapshot` count; a
scheduled prune job deletes `SourcePost` rows older than the drill-down retention window (e.g.
30 days) once their contribution to `TopicBaselineSnapshot` is durably recorded. The aggregate
baseline outlives the raw posts; the raw posts do not need to survive indefinitely.

---

## Theme

A cluster of related, filtered posts for a topic within one run (spec's Key Entities).

| Field | Type | Notes |
|---|---|---|
| `id` | UUID/PK | |
| `digest_topic_result_id` | FK → DigestTopicResult | |
| `summary` | string | plain-language, from Summarize stage (FR-007) |
| `rationale` | string | why it's trending (FR-007) |
| `confidence_score` | integer 0-100 | grounded per research §12 |
| `is_spike` | boolean | false during a topic's 7-day observation period regardless of activity (FR-005) |
| `spike_ratio` | decimal, nullable | current filtered activity ÷ baseline (FR-004) |
| `cluster_post_count` | integer | total posts in this theme (denominator for "3 of 41") |
| `rank` | integer | descending significance order within the Digest (FR-008) |

**Relationships**: one Theme → many `SourcePost` (all clustered members); a curated subset (3-5,
FR-008) are flagged as `is_example` on the SourcePost↔Theme association for default digest
display, with the rest available via drill-down (User Story 3).

**Validation**: `cluster_post_count` MUST equal the count of associated `SourcePost` rows;
example posts shown by default MUST be between 3 and 5 inclusive and MUST be a subset of the
full cluster.

---

## DraftPost

A system-generated post derived from a high-signal Theme, pending manual or autonomous handling
(spec's Key Entities, User Story 4).

| Field | Type | Notes |
|---|---|---|
| `id` | UUID/PK | |
| `theme_id` | FK → Theme | |
| `user_id` | FK → User | |
| `draft_text` | string | from Draft Post stage |
| `confidence_score` | integer 0-100 | copied from Theme at draft time |
| `status` | enum: `held_manual`, `published_manual`, `held_below_threshold`, `published_auto`, `publish_failed` | see state machine below |
| `created_at` | timestamp | |
| `published_at` | timestamp, nullable | |
| `publish_error` | string, nullable | populated on `publish_failed` (FR-019) |

**State machine** (FR-010, FR-012, FR-019, edge cases):

```
                 ┌─ (posting_mode = manual, any confidence) ──► held_manual ──(user publishes by hand)──► published_manual
created ─────────┤
                 └─ (posting_mode = autonomous) ─┬─ confidence ≥ threshold ──► publish attempt ─┬─ success ─► published_auto
                                                  │                                              └─ failure ─► publish_failed (surfaced, never silently dropped)
                                                  └─ confidence < threshold ──► held_below_threshold (manual review, never auto-discarded)
```

**Validation**: a draft's `status` MUST be assigned exactly once at creation based on the
`PostingMode` in effect **at that moment** — never retroactively changed by a later mode switch
(edge case: "switched from manual to autonomous mode mid-cycle... applies from the next run
onward").

---

## PostingMode

Per-user state governing draft handling (spec's Key Entities, FR-011, FR-013, FR-022).

| Field | Type | Notes |
|---|---|---|
| `id` | UUID/PK | |
| `user_id` | FK → User, unique | one row per user |
| `mode` | enum: `manual`, `autonomous` | |
| `confidence_threshold` | integer 0-100 | tunable parameter (spec Assumptions) |
| `validation_period_ends_at` | timestamp | 3 weeks from first run; `mode` cannot become `autonomous` before this regardless of toggle state |
| `kill_switch_engaged` | boolean | when true, forces manual-hold behavior immediately regardless of `mode` (FR-022) |
| `last_post_published_at` | timestamp, nullable | used to compute rolling-24h cap and jitter |
| `updated_at` | timestamp | |

**Validation** (gates enforced at the moment `mode` is set to `autonomous`, FR-013):
- MUST be blocked unless a live check of the associated X account bio contains a visible
  "automated" label at that instant.
- MUST be blocked before `validation_period_ends_at`.
- Publishing autonomously MUST be blocked once 5 posts have been published by this user within
  the trailing 24 hours (FR-022), independent of `mode`/`kill_switch_engaged`.
- Autonomous publish timing MUST vary between posts (jitter) — enforced procedurally at publish
  time (research §7/§9), not a static field, but the varying gaps MUST be observable from
  `published_at` across consecutive `DraftPost` rows (SC-008).

---

## Entity Relationship Summary

```
User 1──* Topic 1──* TopicBaselineSnapshot
User 1──* Digest 1──* DigestTopicResult *──1 Topic
DigestTopicResult 1──* SourcePost
DigestTopicResult 1──* Theme 1──* SourcePost (clustered subset, incl. examples)
Theme 1──* DraftPost *──1 User
User 1──1 PostingMode
```
