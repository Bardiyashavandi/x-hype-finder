# Quickstart: Validating X Hype Finder MVP

**Feature**: 001-x-hype-finder-mvp

This is a validation guide, not an implementation guide — it proves the feature works
end-to-end against the acceptance scenarios in spec.md. See `data-model.md` for entity detail
and `contracts/` for command/stage/integration shapes.

## Prerequisites

- Python 3.11+, and an embedding provider for Cluster/Filter Tier 2
  (`src/pipeline/embedding_provider.py`): either [Ollama](https://ollama.com) running locally with
  `nomic-embed-text` pulled (`ollama pull nomic-embed-text`) — the default — or
  `EMBEDDING_PROVIDER=voyage` with `VOYAGE_API_KEY` set for the hosted Voyage AI (`voyage-4-lite`)
  alternative.
- Environment variables set (never committed — Constitution V, FR-021):
  `TWITTERAPI_IO_KEY`, `ANTHROPIC_API_KEY`, `RESEND_API_KEY`, the embedding provider vars above,
  and per-user X posting OAuth credentials.
- Local SQLite DB initialized (migrations applied).

## Scenario 1 — Ranked, evidence-backed digest (User Story 1, P1)

1. Add a topic with 7+ days of seeded baseline history and inject known-spiking activity
   (filtered activity ≥ `baseline mean + k * effective standard deviation`, per FR-004):
   `topic add "<topic>"` then seed `TopicBaselineSnapshot` rows for the trailing week.
2. Add a second, non-spiking control topic with normal seeded activity.
3. Run `digest run`.
4. **Expect**: the spiking topic's `Digest` entry has a summary, rationale, confidence score,
   and 3-5 example posts (FR-007, FR-008); the control topic does **not** appear as a
   false-positive spike (SC-003).
5. Repeat with a topic inside its first 7 days (`first_tracked_at` < 7 days ago) at any activity
   level → **expect** raw activity shown, `is_spike = false` (FR-005).
6. Seed 50+ filtered posts with near-duplicate content for one topic → **expect** they collapse
   into a single Theme after `digest run` (FR-006).
7. Run Filter against a hand-labeled set of 50 known bot/spam posts mixed with genuine posts →
   **expect** ≥90% of the labeled bot/spam posts excluded before Detect runs (SC-002).

## Scenario 2 — On-demand trigger (User Story 2, P2)

1. With topics already configured, run `digest run --topic <topic>` and time it.
2. **Expect**: completes in under 5 minutes (SC-004) and produces output identical in format/
   quality to a scheduled run.

## Scenario 3 — Drill into source evidence (User Story 3, P2)

1. From a Digest entry showing 3 of N example posts, run `digest show <digest-id> --topic
   <topic> --full`.
2. **Expect**: all N underlying posts and each one's `filter_outcome` are visible (FR-016).
3. Run a topic where every post was filtered as noise → **expect** the digest states this
   explicitly (`all_filtered_as_noise`), never an empty/missing entry (FR-017).

## Scenario 4 — Manual-first, then confidence-gated autonomous posting (User Story 4, P3)

1. Within the first 3 weeks (`now() < validation_period_ends_at`), generate drafts across a
   range of confidence scores via `digest run` → **expect** every `DraftPost.status =
   held_manual`, none published automatically (FR-010, SC-005). Confirm with `drafts list`.
2. Attempt `posting mode set autonomous` before the 3 weeks elapse or before the account bio
   carries an "automated" label → **expect** the switch is rejected (FR-013).
3. After the validation period and with the bio label present, run `posting mode set
   autonomous` → **expect** success.
4. Run `digest run` again → **expect** drafts at/above `confidence_threshold` move to
   `published_auto`; drafts below move to `held_below_threshold`, never silently discarded
   (FR-012, SC-006).
5. Publish several autonomous posts over time → **expect** the gaps between `published_at`
   timestamps vary (jitter), never a fixed interval (FR-014, SC-008).
6. Force a publish call to fail after a draft clears the threshold → **expect** `status =
   publish_failed` with `publish_error` populated and surfaced, not silently dropped (FR-019).
7. Confirm drafts already `held_manual` before the mode switch are never retroactively
   auto-published (edge case: mid-cycle switch applies from the next run onward only).
8. Trigger `posting kill-switch on` mid-operation → **expect** all autonomous publishing halts
   immediately regardless of already-computed confidence scores (FR-022, SC-009); confirm no
   more than 5 autonomous posts occurred in any rolling 24h window prior to this.

## Scenario 5 — Independent multi-user operation (User Story 5, P3)

1. Configure two users with overlapping topic names (e.g., both track "$TICKER").
2. Run a digest for User A → **expect** only User A's topics/history are used.
3. Attempt to access User B's credentials or data from User A's session/process → **expect**
   zero access (FR-015, SC-010).

## Edge cases to confirm while running the above

- A topic returns near-zero posts in a run window → digest states "no significant activity"
  explicitly.
- A fetch error on one topic during a multi-topic run → logged clearly, other topics still
  complete (FR-002).
- Rate limits hit mid-run → partial results preserved, affected topics marked
  `incomplete_rate_limited` rather than dropped.
- Digest-completion notification (FR-023) arrives at `User.email` via Resend within minutes of
  each run completing (SC-013).
