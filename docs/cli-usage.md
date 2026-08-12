# CLI Usage

**Feature**: 001-x-hype-finder-mvp (tasks.md T068, contracts/cli-commands.md)

A web dashboard also exists now (specs/003-web-dashboard) — see the README's
[Web Dashboard](../README.md#web-dashboard) section for what it is and how to run it. Every
dashboard action is a thin wrapper over these same CLI commands' underlying functions, never a
reimplementation, so this document remains the authoritative reference for the full command
surface, every flag, and every error case; the dashboard's own API is documented in
[`specs/003-web-dashboard/plan.md`](../specs/003-web-dashboard/plan.md) rather than duplicated
here. There are five command groups: `topic`, `digest`, `posting`, `drafts`, `scheduler`. Each is
invoked as a Python module:

```sh
python -m src.cli.topic <command> [args]
python -m src.cli.digest <command> [args]
python -m src.cli.posting <command> [args]
python -m src.cli.drafts <command> [args]
python -m src.cli.scheduler <command> [args]
```

The dashboard itself is started the same way — `python -m src.cli.web run [--host] [--port]`
— but see the README section linked above rather than this document for its setup. Dashboard
accounts (real per-user login, User Story 5 / FR-015) are created the same way too —
`python -m src.cli.user create <email> [--handle <x_account_handle>]` (src/cli/user.py), which
prompts for a password (hidden input, never a CLI argument) and stores its bcrypt hash — there is
no public signup, this is the only way an account is ever provisioned.

A separate, non-scheduled, non-persisted `idea-validate` mode also exists
(002-idea-validation-mode) — see [`idea-validate`](#idea-validate-002-idea-validation-mode)
below.

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

- Without `--full`: shows each Theme's 3-5 curated example posts (the default view), and
  hides any Theme scoring below `confidence_score` 20 (`CONFIDENCE_DISPLAY_THRESHOLD` in
  `src/cli/digest.py`) as noise below the Summarize prompt's calibrated signal floor — the
  prompt reserves 0-5 for "not a genuine trend" and only starts describing a real "moderate
  spike" at 30+, so 20 clears the observed noise floor without hiding anything the model
  calibrated as a real trend.
- With `--full`: un-hides those low-confidence Themes too, *and* shows every underlying
  `SourcePost` for that topic — both the ones clustered into a Theme and the ones Filter
  excluded — each annotated with its `filter_outcome` (FR-016). The author metadata Filter
  Tier 1 scored the post against (followers/following counts, account age, post frequency)
  and its engagement counts (likes, retweets, replies, quotes, views — when the active Fetch
  provider exposes them) are stored on the same row but not yet rendered here — query
  `SourcePost` directly if you need them.
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

---

## `eval`

Human-in-the-loop evaluation for every judgment-making pipeline stage —
Filter, Detect, Cluster, Summarize, Draft Post, Digest — backed by one shared
`EvaluationLabel` table rather than a separate table per stage. Like every
other command here, both sampling and reporting are scoped to the current
user (FR-015): labeling as one user never counts against, or shows up in,
another user's report.

### `eval label <stage> [--count N] [--id <uuid>]`

Samples up to `N` (default 5) real, unlabeled items for `stage` — items you
haven't already labeled for that stage yourself — and prompts interactively
for a label per item, showing the same context a human reviewer needs:

| stage       | samples from        | shows                                             | label       |
|-------------|----------------------|----------------------------------------------------|-------------|
| `filter`    | `SourcePost`         | post text, author, Filter's decision                | correct/incorrect |
| `detect`    | `Theme`               | is_spike, spike_ratio, example posts                | correct/incorrect |
| `cluster`   | `Theme`               | member posts (was the grouping sensible?)           | correct/incorrect |
| `summarize` | `Theme`               | summary, rationale, confidence_score                | 1-5 |
| `draft`     | `DraftPost`           | draft_text + parent theme's summary/rationale       | 1-5 |
| `digest`    | `Digest`              | run type/status + per-topic outcomes and themes     | 1-5 (SC-011 KPI) |

At each prompt: `y`/`n` (binary stages) or `1`-`5` (rated stages), plus
`s` to skip the current item (leaves it unlabeled) or `q` to end the
session early. Each label is committed immediately, so ending the session
early (including via Ctrl+D/EOF) never loses labels already recorded.

Pass `--id <uuid>` to label one specific item directly instead of random
sampling — still scoped to the current user, and still rejected if that
item is already labeled by them. `--count` is ignored when `--id` is given.

```sh
python -m src.cli.eval label filter
python -m src.cli.eval label digest --count 10
python -m src.cli.eval label filter --id 3fa85f64-5717-4562-b3fc-2c963f66afa6
```

### `eval report [--stage <stage>]`

Prints accuracy % (binary stages) or average rating (rated stages) across
every label *you've* recorded so far, one line per stage. `--stage` narrows
to a single stage. A stage with no labels yet prints `no labels yet` rather
than being omitted.

```sh
python -m src.cli.eval report
python -m src.cli.eval report --stage digest   # SC-011 KPI
```

---

## `scheduler`

Unlike the other command groups, `scheduler` doesn't act on one user's data and
return — it starts a **long-lived process** that runs scheduled jobs for every user
in the background, and keeps running until stopped.

### `scheduler run [--cadence-hours N] [--retention-sweep-cadence-hours N]`

Constructs `Config`, starts the in-process APScheduler (`src/scheduler/jobs.py`),
and blocks until interrupted (Ctrl+C), at which point it shuts the scheduler down
gracefully rather than killing jobs mid-run. Registers two independent interval
jobs:

- **`scheduled_digest_run`** — every `--cadence-hours` hours (default 24). Runs a
  scheduled Digest (`run_type = scheduled`) for every user's active topics, via the
  same `run_digest` orchestrator entry point `digest run` uses. One user's failure
  is logged and never blocks another user's run (FR-002's per-topic isolation, one
  level up).
- **`source_post_retention_sweep`** — every `--retention-sweep-cadence-hours` hours
  (default 24). Deletes every `SourcePost` row older than the 30-day retention
  window, across all topics and users (FR-020) — a standalone sweep that catches
  rows a run's own inline prune could miss (e.g. a run that crashed before reaching
  its prune step).

```sh
python -m src.cli.scheduler run
python -m src.cli.scheduler run --cadence-hours 12 --retention-sweep-cadence-hours 24
```

Both jobs fire on a fixed interval from whenever the process starts (not a fixed
wall-clock time like a cron entry) — run this as a persistent process (e.g. under
your process manager of choice) rather than a one-shot command.

---

## `idea-validate` (002-idea-validation-mode)

A separate, one-off mode from every command group above — it doesn't track a brand or
existing topic. Give it a short list of problem-describing phrases instead (e.g. "people
struggling to find sublets in a new city") and it searches X for real complaints/requests
around that problem, then reports back whether there's genuine signal. Unlike every other
command here, `idea-validate run` does **not** resolve a current user and opens **no
database session at all** — both the Fetch-provider API key and `ANTHROPIC_API_KEY` are
app-level credentials already (`src/config.py`), and this mode persists nothing: no
`Digest`/`Theme`/`SourcePost`/`DraftPost`/`PostingMode` row is ever written, and there's no
posting step (spec.md §3, §5.2 of `specs/002-idea-validation-mode/spec.md`). Output is
stdout plus an optional local file — a one-time strategic input, not a scheduled digest.

Fetch is resolved through the same `FETCH_PROVIDER` abstraction every other command uses
(`src/pipeline/fetch_provider.py`'s `get_fetch_provider_for_query`, the query-string-accepting
sibling of the `get_fetch_provider()` the digest pipeline calls) — this mode defaults to
TwitterAPIs.com and respects `FETCH_PROVIDER=twitterapi_io` to switch providers, exactly like
`topic`/`digest` mode; it does not hardcode either provider.

### `idea-validate run --phrase <p> [--phrase <p> ...] [--exclude-term <t> ...] [--since <ISO8601>] [--until <ISO8601>] [--out <path>]`

Runs Query Construction → Fetch → Relevance Filter → Bot/Noise Filter (reused unchanged
from `topic`/`digest` mode) → Signal Strength → Cluster (reused unchanged) → Validate
Summarize → Validation Readout, once, and prints the resulting readout to stdout.

- `--phrase` is **required**, repeatable (1-8 problem-describing phrases) — rejected with a
  clear message before any network call if none is given.
- `--exclude-term` is optional, repeatable — filtered both at query-construction time (an X
  advanced-search `-"term"` clause) and again post-fetch against actual post text (a
  cost-reduction pass, not the sole relevance guarantee — broad problem phrases are noisier
  than a fixed brand name).
- `--since`/`--until` default to Fetch's existing lookback window if omitted.
- `--out <path>` also writes the rendered readout to a local file — a plain file you own,
  not tracked or read by any other command.

The readout always prints something complete. On the signal-present path it leads with a
**`Verdict:`** block — a 3-5 sentence executive-summary paragraph (Validate Synthesize,
`src/agent/validate_synthesize.py`) synthesizing every theme found into one strategic read:
is this a real, validated problem; is the signal concentrated or fragmented; do any themes
show existing competitors/solutions already targeting it; and an honest pursue/pass
recommendation — grounded strictly in the themes actually generated, never invented beyond
them. This prints *above* Signal Strength and Themes, so a strategist reads the conclusion
first and only drills into supporting detail if they want it (spec.md §5.3, §7). Below that:
signal strength (`total_relevant_count`/`distinct_author_count`/recency buckets, no
baseline-relative `is_spike`/`spike_ratio`, since a new problem space has no history to
compare against) plus 2-4 recurring themes (`summary`, `representative_ask`,
`recurrence_signal`, 3-5 example posts) — or an explicit `No meaningful signal found.` when
nothing relevant survives, with no Verdict block at all in that case (the no-signal message
already is the top-line verdict, and Validate Synthesize is never even called in that
scenario) — never a blank/empty output either way. A Fetch failure is reported as an explicit
fetch-error state rather than a stack trace; a single theme's Validate Summarize failure
drops just that theme (with a logged note) rather than blanking the whole readout; a Validate
Synthesize failure similarly omits just the Verdict block (`Verdict: unavailable
(executive-summary synthesis failed — see themes below).`) rather than the whole readout.

```sh
python -m src.cli.idea_validate run \
  --phrase "can't find sublet" \
  --phrase "no easy way to sublet" \
  --phrase "sublet is a nightmare" \
  --exclude-term "sublet.com"
```

Sample readout (truncated):

```
== Idea Validation Readout ==
generated_at: 2026-08-12T14:02:11.123456+00:00
phrases: can't find sublet, no easy way to sublet, sublet is a nightmare
exclude_terms: sublet.com

Verdict:
  There is real, recurring frustration around finding short-term sublets when moving to a
  new city, concentrated in a single strong theme with three distinct authors rather than
  scattered across many isolated posts. None of the found posts describe an existing
  competitor or product already solving this. Given the concentrated signal and clear,
  repeated ask, this is worth pursuing further.

Signal strength:
  total_relevant_count: 3
  distinct_author_count: 3
  posts_last_24h: 1
  posts_last_7d: 3
  most_recent_post_at: 2026-08-12T09:15:00+00:00
  oldest_post_at: 2026-08-10T18:40:00+00:00

Themes (1):

[1] recurrence_signal=recurring  cluster_post_count=3  distinct_author_count=3
    summary: People struggle to find short-term sublets when moving to a new city.
    representative_ask: I just need a place for a few months, not a full year lease.
    examples:
      - Can't find a sublet anywhere in this city, it's impossible
      - Sublet is a nightmare here, nobody wants short-term
      - No easy way to sublet an apartment for just a summer
```
