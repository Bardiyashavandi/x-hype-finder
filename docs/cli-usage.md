# CLI Usage

**Feature**: 001-x-hype-finder-mvp (tasks.md T068, contracts/cli-commands.md)

No web/GUI dashboard exists in this MVP (Product Brief §13) — the CLI is the entire
user-facing interface. There are four command groups: `topic`, `digest`, `posting`,
`drafts`. Each is invoked as a Python module:

```sh
python -m src.cli.topic <command> [args]
python -m src.cli.digest <command> [args]
python -m src.cli.posting <command> [args]
python -m src.cli.drafts <command> [args]
```

## Setup

1. Copy `.env.example` to `.env` and fill in real values — never commit `.env` (it's
   already gitignored; see Constitution V, FR-021).
2. `TWITTERAPI_IO_KEY`, `ANTHROPIC_API_KEY`, and `RESEND_API_KEY` are shared service
   credentials the app itself uses (`src/config.py`).
3. X OAuth posting credentials are **per user**, namespaced by that user's
   `x_account_handle` — see `.env.example` for the exact `X_API_KEY__<HANDLE>` etc.
   naming convention (FR-015, FR-021).
4. Apply Alembic migrations before first use so the schema exists.

## Which user is this process running as?

Every command operates only on one user's own data (FR-015) — the CLI process is
invoked per-user. Which `User` row that is gets resolved automatically
(`src/cli/_common.py`):

- If exactly one `User` row exists in the database, that user is used — no extra
  configuration needed for local single-user development.
- If more than one `User` row exists, set `XHF_USER_EMAIL` to the email of the user
  this process should run as. The CLI never guesses between multiple users — with
  more than one user configured and no `XHF_USER_EMAIL` set, every command fails
  with a clear error rather than risk operating on the wrong person's data.

```sh
export XHF_USER_EMAIL=you@example.com
python -m src.cli.topic list
```

---

## `topic`

### `topic add <name> [--handles h1,h2,...]`

Creates a `Topic` (status `active`, `first_tracked_at = now()`). Visible to the very
next run — scheduled or on-demand — with no code change or redeploy (FR-001, SC-001).
Re-adding a previously-removed topic of the same name reactivates the original row
(preserving its baseline/history) rather than inserting a duplicate.

```sh
python -m src.cli.topic add "$AAPL" --handles aapl_news,applenews
```

Rejected with a clear message (no partial write) if this user already has an
*active* topic with that name.

### `topic remove <name>`

Soft-deletes: sets `status = removed`. Historical baseline rows are retained (not
deleted), in case the topic is re-added later. Removed topics never appear in the
next run's Digest.

```sh
python -m src.cli.topic remove "$AAPL"
```

### `topic list`

Prints every `active` topic for this user, with `first_tracked_at` and whether it's
still inside its 7-day observation period (during which Detect never flags a spike —
FR-005).

```sh
python -m src.cli.topic list
```

---

## `digest`

### `digest run [--topic <name>]`

Triggers an on-demand pipeline run (`run_type = on_demand`) for every active topic,
or a single named one via `--topic`. Completes in under 5 minutes for a single topic
(FR-009, SC-004); output format and quality match a scheduled run exactly (same
orchestrator entry point — User Story 2, Acceptance Scenario 2).

```sh
python -m src.cli.digest run
python -m src.cli.digest run --topic "$AAPL"
```

Errors clearly (exit code 1, no `Digest` written) if `--topic` doesn't match an
active topic for this user.

### `digest show <digest-id> [--topic <name>] [--full]`

Renders a stored Digest, grouped by topic.

- Without `--full`: shows each Theme's 3-5 curated example posts (the default view).
- With `--full`: shows every underlying `SourcePost` for that topic — both the ones
  clustered into a Theme and the ones Filter excluded — each annotated with its
  `filter_outcome` (FR-016).
- `--topic <name>` scopes the output to a single topic within the digest, erroring
  clearly if the name doesn't match anything in that digest.
- Always renders the topic's outcome explicitly — `no_significant_activity`,
  `all_filtered_as_noise`, `fetch_error`, `incomplete_rate_limited` — never an
  empty or missing entry (FR-017).

```sh
python -m src.cli.digest show <digest-id>
python -m src.cli.digest show <digest-id> --topic "$AAPL" --full
```

---

## `posting`

### `posting mode show`

Prints the current `PostingMode` row for this user: `mode`,
`confidence_threshold`, `validation_period_ends_at`, `kill_switch_engaged`,
`last_post_published_at`.

```sh
python -m src.cli.posting mode show
```

### `posting mode set autonomous`

Attempts to flip `PostingMode.mode` to `autonomous`. Rejected (no state change) if
either of these holds (FR-011, FR-013):

- still inside the 3-week manual-only validation window
  (`now() < validation_period_ends_at`), or
- a **live** check of the X account bio does not currently show a visible
  "automated" label.

On success, applies from the next run onward only — never retroactively changes
the `status` of `DraftPost` rows already created under manual mode.

```sh
python -m src.cli.posting mode set autonomous
```

### `posting mode set manual`

Flips `PostingMode.mode` back to `manual`. Always allowed (the fail-safe
direction).

```sh
python -m src.cli.posting mode set manual
```

### `posting kill-switch on|off`

Sets `PostingMode.kill_switch_engaged`. When `on`, all autonomous publishing halts
immediately regardless of `mode` or any already-computed confidence scores; drafts
fall back to a held-for-manual-review status rather than being silently discarded
(FR-022).

```sh
python -m src.cli.posting kill-switch on
python -m src.cli.posting kill-switch off
```

---

## `drafts`

### `drafts list [--status <status>]`

Lists `DraftPost` rows for this user, optionally filtered by status. This is how a
user finds what's `held_manual` and needs to be published by hand during the
3-week window, or reviews anything `held_below_threshold` / `publish_failed` after
the autonomous switch (FR-019).

```sh
python -m src.cli.drafts list
python -m src.cli.drafts list --status held_manual
```

Valid `--status` values: `held_manual`, `held_below_threshold`, `published_auto`,
`published_manual`, `publish_failed`.

### `drafts mark-published <draft-id>`

Records that the user manually published a `held_manual` draft themselves on X:
sets `status = published_manual`, `published_at = now()`. Only valid for drafts
currently `held_manual` — rejected with a clear message otherwise.

```sh
python -m src.cli.drafts mark-published <draft-id>
```
