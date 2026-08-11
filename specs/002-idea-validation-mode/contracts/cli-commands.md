# CLI Command Contracts

**Feature**: 002-idea-validation-mode

This is the only user-facing surface for Idea Validation mode — no web/GUI dashboard, matching
the existing project's CLI-only scope (`specs/001-x-hype-finder-mvp/contracts/cli-commands.md`).
Unlike every other `cli/*.py` command, `idea-validate run` does **not** call
`resolve_current_user` and does not open a DB session — both the Fetch-provider API key and the
`ANTHROPIC_API_KEY` are app-level credentials already (`src/config.py`), not per-user ones, and
this mode persists nothing (research.md §1), so there is no per-user data to scope this command
to.

---

## `idea-validate run --phrase <p> [--phrase <p> ...] [--exclude-term <t> ...] [--since <ISO8601>] [--until <ISO8601>] [--out <path>]`

- **Effect**: runs the full Query Construction → Fetch → Relevance Filter → Bot/Noise Filter →
  Signal Strength → Cluster → Validate Summarize → Validation Readout pipeline
  (contracts/pipeline-stages.md) for the given phrases, once, and prints the resulting readout to
  stdout.
- **Required**: at least one `--phrase` (repeatable flag, matching `--handles`-style repetition
  conventions elsewhere in the CLI where a list is needed — see `topic add --handles`'s
  comma-separated pattern in `src/cli/topic.py` for precedent, though `--phrase` here is
  repeat-the-flag rather than comma-split, since phrases themselves may contain commas).
- **Optional**: `--exclude-term` (repeatable, 0 or more); `--since`/`--until` (defaults mirror
  Fetch's existing `DEFAULT_LOOKBACK`); `--out <path>` writes the same rendered readout to a local
  file in addition to stdout (the file is plain output the user owns — not tracked/read by any
  other command).
- **Contract**: MUST NOT write to any application-owned table (`Digest`, `Theme`, `SourcePost`,
  `DraftPost`, `PostingMode`) — this command has no DB session at all in the default path.
  Completes as a single synchronous run; no scheduling, no `--topic` semantics (there is no
  `Topic` involved).
- **Output**: the rendered `ValidationReadout` (contracts/pipeline-stages.md § Validation
  Readout) — signal strength summary, 2-4 recurring themes each with `summary`,
  `representative_ask`, `recurrence_signal`, and 3-5 example post texts. When
  `signal_strength.total_relevant_count == 0`, prints an explicit "no meaningful signal found"
  readout instead of an empty output (spec.md §7).
- **Errors**:
  - No `--phrase` given → reject with a clear message before any network call, no partial output
    (mirrors `topic add`'s empty-name rejection).
  - Fetch failure (rate-limited or generic) → reported clearly in the readout as an explicit
    fetch-error state (mirroring `DigestTopicOutcome.FETCH_ERROR`'s "never silently vanish"
    principle), not a stack trace, not a silently empty readout.
  - A Validate Summarize failure for one theme → that theme is dropped from the readout with a
    logged note; the run still completes and prints every other theme (mirrors
    `orchestrator.py`'s per-theme Summarize failure handling) — one bad LLM call never blanks the
    whole readout.

**Non-goal reminder**: no `posting`, `digest`, `topic`, or `eval` command's behavior changes as a
result of this command existing (spec.md §3 non-goals) — `idea-validate` is additive-only.
