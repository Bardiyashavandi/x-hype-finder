# Implementation Plan: Idea Validation Mode

**Branch**: `002-idea-validation-mode` | **Date**: 2026-08-11 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-idea-validation-mode/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

A one-off, non-persisted CLI command (`idea-validate run`) that takes a short list of
problem-describing phrases (plus optional exclude terms) instead of a tracked `Topic`, runs a
reused Fetch → deterministic relevance/bot Filter → Cluster pipeline against X, computes absolute
signal strength (volume + recency, not a baseline-relative spike — there is no history for a new
problem space), and produces a **validation readout**: signal strength, 2-4 recurring themes (via
a new "what people want/are frustrated by" Summarize prompt variant), and representative example
posts. It is deliberately not wired into the scheduled digest/posting infrastructure — no
`Digest`/`Theme`/`DraftPost`/`PostingMode` rows are written, no confidence-gated posting step
exists, and nothing is persisted to the database beyond the single run's stdout/optional file
output. This keeps the blast radius on the existing brand-tracking pipeline at zero (non-goal:
"no changes to brand-tracking or client-report features") while reusing every deterministic stage
that already exists (Fetch's HTTP/pagination/retry mechanics, Filter Tier 1/Tier 2 bot scoring,
Cluster's embedding-similarity grouping).

## Technical Context

**Language/Version**: Python 3.11+ (matches the existing project; no new interpreter/runtime
requirement)

**Primary Dependencies**: reuses the existing Fetch provider abstraction
(`src/pipeline/fetch_provider.py`, TwitterAPI.io/TwitterAPIs.com — read-only, app-level API key,
not per-user), `src.pipeline.filter` (Tier 1/Tier 2 bot-noise scoring, unchanged), the existing
embedding provider (`src/pipeline/embedding_provider.py`) for Filter Tier 2 + Cluster,
`scikit-learn`/`numpy` for Cluster (unchanged), and `anthropic` SDK for one new Summarize-prompt
variant. No new third-party dependency is introduced.

**Storage**: **N/A — intentionally stateless.** No new SQLAlchemy models or tables. A run's raw
post text, relevance/filter decisions, and generated themes exist only in-process for the
duration of that run; the readout is printed to stdout and optionally written to a local file via
`--out <path>` (a plain file the user manages themselves, not an app-owned/DB-tracked artifact).
This is stricter than the existing `SourcePost` retention rule (FR-020's "pruned after
baseline/drill-down window") — there is no baseline to serve here at all (§5.2 of spec.md), so
there is nothing to retain past the run. See research.md §1 for why this beats reusing
`Digest`/`SourcePost`/`Theme`.

**Testing**: `pytest`, matching the existing suite's layout — unit tests for every new
deterministic function (query construction, relevance filter, signal strength), a contract test
for the new Summarize-prompt variant (mirrors `tests/contract/test_claude_summarize.py`), one
integration test running the full flow against a synthetic problem-space fixture (spec.md
Rollout step 5), and a small precision-eval test against a hand-labeled real-complaint-vs-noise
fixture set (spec.md §6, mirrors the Filter-stage eval approach).

**Target Platform**: same CLI process as every other command (`topic`, `digest`, `eval`,
`posting`) — the user's own machine (macOS/Linux), no hosted/cloud deployment.

**Project Type**: single project — extends the existing CLI-driven pipeline codebase; no new
service/process.

**Performance Goals**: no hard SLA (this isn't a scheduled/on-demand digest run subject to
FR-009/SC-004's <5-minute budget) — informally sized to finish in a similar order of magnitude to
a single-topic on-demand run, since it reuses the same Fetch pagination/rate-limit pacing.

**Constraints**: Fetch/relevance-filter/bot-filter/Cluster/signal-strength stay fully
deterministic (Constitution I) — only the new Summarize-prompt variant is LLM-powered, preserving
the same deterministic/LLM split the existing pipeline enforces; relevance filtering runs before
signal-strength computation, mirroring Filter-before-Detect ordering (Constitution II) even though
"Detect" here is renamed/reframed; **no posting occurs in this mode at all** — Constitution
III/IV (Staged Posting Autonomy, Platform-Safe Autonomous Posting) are inapplicable by design, not
satisfied-by-omission (this mode never constructs a `DraftPost` or touches `PostingMode`);
credentials stay env-var only with no new credential type (Constitution V); Claude/embedding
spend for this mode is tracked through the existing cost ledger (`src/utils/cost_tracker.py`,
Constitution VI) — no new cost path exists outside it; raw X post text is held only in memory for
the run's duration and never written to the database (Security & Privacy Constraints, stricter
than the existing per-topic retention rule since there is no baseline to serve).

**Scale/Scope**: one ad-hoc run at a time, 3-8 problem-describing phrases + an optional handful of
exclude terms, same per-run fetch cap the existing Fetch stage already applies
(`MAX_POSTS_PER_RUN`-style), yielding 2-4 themes with 3-5 example posts each (mirrors the existing
`_MIN_EXAMPLE_POSTS`/`_MAX_EXAMPLE_POSTS` convention in `src/pipeline/orchestrator.py`).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Status |
|---|---|---|
| I. Deterministic, Testable Data Pipeline | Query construction, relevance filtering (exclude terms), bot/noise Filter (reused unchanged), and signal-strength computation are all rule/stats-only; only the new Summarize-prompt variant calls an LLM, same split as the existing pipeline (research.md §2). | **PASS** |
| II. Filter-Before-Detect Ordering | Relevance + bot/noise filtering both run before signal-strength computation (this mode's Detect-equivalent) — signal strength only ever sees already-filtered posts (data-model.md, contracts/pipeline-stages.md). | **PASS** |
| III. Staged Posting Autonomy | Inapplicable by design: this mode never constructs a `DraftPost` or reads/writes `PostingMode` — there is no posting step to stage (spec.md §5.2 "Confidence gate (posting): Not applicable"). Documented here rather than silently omitted so a future reviewer doesn't mistake the absence for an oversight. | **N/A — documented** |
| IV. Platform-Safe Autonomous Posting | Same reasoning as III — no posting occurs in this mode. | **N/A — documented** |
| V. Credential Hygiene | No new credential type: reuses the existing app-level Fetch-provider key and `ANTHROPIC_API_KEY`, both already env-var-only (`src/config.py`). | **PASS** |
| VI. Cost Discipline | The new Summarize-prompt variant's Claude usage is recorded through the existing `record_claude_usage` cost-tracker call (same as `src/agent/summarize.py`) — no parallel/untracked spend path (research.md §2). | **PASS** |
| VII. Measurable Definition of Done | quickstart.md gives a runnable synthetic-example validation scenario with an explicit pass/fail acceptance check tied to spec.md §7's success criteria. | **PASS** |

No unresolved violations — Complexity Tracking table below is empty.

## Project Structure

### Documentation (this feature)

```text
specs/002-idea-validation-mode/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/
├── pipeline/
│   ├── idea_query_builder.py   # NEW: phrase-list + exclude-terms query construction,
│   │                            #      sibling to query_builder.py's single-entity builder
│   ├── relevance_filter.py     # NEW: deterministic exclude-terms relevance filter
│   ├── signal_strength.py      # NEW: absolute volume/recency computation (this mode's
│   │                            #      Detect-equivalent — no baseline comparison)
│   ├── fetch.py                # UNCHANGED — pagination/retry mechanics reused as-is;
│   │                            #   internals reshaped (research.md §3) so a prebuilt query
│   │                            #   string can be supplied instead of only topic_name/handles
│   ├── filter.py                # UNCHANGED — Tier 1/Tier 2 bot/noise scoring reused as-is
│   └── cluster.py               # UNCHANGED — embedding-similarity grouping reused as-is
├── agent/
│   └── validate_summarize.py   # NEW: "what people want/are frustrated by" Summarize-prompt
│                                 #      variant, sibling to agent/summarize.py
├── report/
│   └── validation_readout.py   # NEW: assembles signal strength + themes + examples into
│                                 #      the printable/writable validation readout
└── cli/
    └── idea_validate.py        # NEW: `idea-validate run` command — no DB session required
                                  #      (no per-user Topic/credential lookup; the Fetch key
                                  #      and Anthropic key are both app-level, not per-user)

tests/
├── unit/
│   ├── test_idea_query_builder.py
│   ├── test_relevance_filter.py
│   └── test_signal_strength.py
├── contract/
│   └── test_claude_validate_summarize.py
├── integration/
│   └── test_idea_validation_flow.py   # synthetic problem-space example, end-to-end
└── eval/
    └── test_relevance_filter_precision.py  # hand-labeled real-complaint-vs-noise fixture set
```

**Structure Decision**: Single project (Option 1), extending the existing repository — no new
service, package, or process boundary. New modules sit as siblings to the existing pipeline/agent
modules they parallel (`idea_query_builder.py` next to `query_builder.py`,
`validate_summarize.py` next to `summarize.py`), so the deterministic/LLM split enforced by
`pipeline/` vs `agent/` in the 001 plan continues to hold here. The new `report/` package is
introduced because this mode's output is a one-off formatted readout, not a `Digest` row — giving
it its own package (rather than overloading `cli/idea_validate.py` with formatting logic) keeps
the CLI entry point thin, matching every other `cli/*.py` module's role of argument
parsing + orchestration only.

## Constitution Check (Post-Design Re-check)

*Re-evaluated after Phase 1 design (data-model.md, contracts/, quickstart.md).*

All seven principles remain satisfied by the design as detailed in data-model.md and contracts/:
Query construction, relevance filtering, and signal-strength computation are plain dataclasses and
pure functions with no LLM/agent judgment (data-model.md); the one LLM call
(`validate_summarize`) is isolated the same way `summarize.py` already is, and its usage funnels
through the existing cost tracker (contracts/pipeline-stages.md § Validate Summarize). No
`DraftPost`/`PostingMode`/`Digest` entity is touched anywhere in the design — III/IV stay
documented as N/A rather than quietly satisfied. No new violations were introduced during design.
**Status: PASS.**

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No violations — this table is intentionally empty.
