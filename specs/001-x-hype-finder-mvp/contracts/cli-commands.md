# CLI Command Contracts

**Feature**: 001-x-hype-finder-mvp

No web/GUI dashboard exists in MVP scope (Product Brief §13). The CLI is the entire user-facing
interface. Every command operates only on the authenticated user's own data (FR-015) — the
process is invoked per-user, scoped by that user's local credentials/config.

---

## `topic add <name> [--handles h1,h2,...]`

- **Effect**: creates a `Topic` (status `active`, `first_tracked_at = now()`).
- **Contract**: MUST be visible to the very next run (scheduled or on-demand) with no code
  change or redeploy (FR-001, SC-001).
- **Errors**: duplicate active topic name for this user → reject with a clear message, no
  partial write.

## `topic remove <name>`

- **Effect**: sets matching `Topic.status = removed`. Historical baseline rows are retained
  (not deleted) in case the topic is re-added later.
- **Contract**: removed topics MUST NOT appear in the next run's Digest.

## `topic list`

- **Effect**: prints all `active` topics for this user with `first_tracked_at` and whether each
  is still inside its 7-day observation period.

## `digest run [--topic <name>]`

- **Effect**: triggers an on-demand pipeline run (`run_type = on_demand`) for all active topics,
  or a single named topic.
- **Contract**: completes in under 5 minutes for a single topic (FR-009, SC-004); output format
  and quality bar MUST match a scheduled run (User Story 2, Acceptance Scenario 2).
- **Output**: prints the digest to stdout AND persists it identically to a scheduled run (same
  `Digest`/`DigestTopicResult`/`Theme` writes, same notification trigger).

## `digest show <digest-id> [--topic <name>] [--full]`

- **Effect**: renders a stored Digest. Without `--full`, shows the 3-5 example posts per Theme
  (default). With `--full`, shows every underlying `SourcePost` for that Theme/topic plus the
  filtering trail (`filter_outcome` per post) — User Story 3, FR-016.
- **Contract**: MUST work even when a topic's outcome is `no_significant_activity` or
  `all_filtered_as_noise` — rendering that explicit state, never an empty/missing entry (FR-017).

## `posting mode show`

- **Effect**: prints the current `PostingMode` row for this user (`mode`,
  `confidence_threshold`, `validation_period_ends_at`, `kill_switch_engaged`).

## `posting mode set autonomous`

- **Effect**: attempts to flip `PostingMode.mode` to `autonomous`.
- **Contract** (FR-011, FR-013): MUST be rejected (no state change) if any of:
  - `now() < validation_period_ends_at` (still inside the 3-week manual window), or
  - a live check of the X account bio does not currently contain a visible "automated" label.
  On success, applies from the next run onward only — never retroactively changes the `status`
  of `DraftPost` rows already created under manual mode (edge case in spec.md).

## `posting mode set manual`

- **Effect**: flips `PostingMode.mode` back to `manual`. Always allowed (fail-safe direction).

## `posting kill-switch on|off`

- **Effect**: sets `PostingMode.kill_switch_engaged`.
- **Contract** (FR-022): when `on`, ALL autonomous publishing halts immediately regardless of
  `mode` or any already-computed confidence scores; drafts fall back to `held_below_threshold`-
  style manual hold, never silently discarded.

## `drafts list [--status <status>]`

- **Effect**: lists `DraftPost` rows for this user, optionally filtered by status — this is how
  the user finds what's `held_manual` and needs to be published by hand during the 3-week
  window, or reviews anything `held_below_threshold` / `publish_failed` after the switch
  (FR-019).

## `drafts mark-published <draft-id>`

- **Effect**: records that the user manually published a `held_manual` draft themselves on X;
  sets `status = published_manual`, `published_at = now()`.
