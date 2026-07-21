# Implementation Plan: X Hype Finder MVP

**Branch**: `001-x-hype-finder-mvp` | **Date**: 2026-07-21 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-x-hype-finder-mvp/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

X Hype Finder monitors a user's tracked X topics/tickers on a schedule (or on demand), runs a
fully deterministic Fetch → Filter → Detect → Cluster pipeline (rule + statistics + local
embeddings only, per Constitution Principle I), then hands filtered/clustered themes to an
Anthropic Claude API stage for plain-language, confidence-scored Summarize and Draft Post output,
ranks the results into a digest, and emails a completion notification. The Summarize/Draft Post
model is staged: Claude Sonnet 5 during the 3-week manual-posting validation period (this is the
window the core concept itself is being judged, so quality matters most here), reassessed at the
week-3 mode switch — kept on Sonnet into the autonomous phase if the $5 API credit is holding up,
downgraded to Haiku if budget is tight, since by then the pipeline itself is already validated and
a downgrade only affects phrasing. Posting is manual-hold-only for the first 3 weeks, then
switchable to confidence-gated autonomous posting via the official X API — gated by a bio-label
check, jittered timing, a 5-posts/24h cap, and a kill switch. Runs as a single long-lived Python
process on the user's own machine against a local SQLite store, isolated per user.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: `tweepy` (official X API v2 posting + bio-label read), TwitterAPI.io
client (third-party X data reads, plain HTTP), `anthropic` SDK for Summarize/Draft Post only —
`claude-sonnet-5` during the weeks 1-3 validation period, reassessed at the week-3 mode switch
(kept on Sonnet if the $5 credit allows, downgraded to `claude-haiku-4-5-20251001` if not; see
research.md §3), local Ollama (`nomic-embed-text` for clustering + Filter Tier 2 embeddings),
`numpy`/`scikit-learn`-class stats for baseline/spike math and Filter Tier 1 rule scoring,
`APScheduler` (in-process scheduling), `sqlalchemy` (SQLite access), Resend HTTP API
(digest-completion email)

**Storage**: SQLite (single file; see data-model.md) — aggregated `TopicBaselineSnapshot` rows
persist indefinitely per topic, raw `SourcePost` rows are pruned after their drill-down/baseline
window per FR-020

**Testing**: `pytest` — unit tests per deterministic stage (Filter, Detect, Cluster), contract
tests per external integration (TwitterAPI.io, X posting, Claude API, Ollama, Resend), integration
tests per user story acceptance scenario

**Target Platform**: a single long-running process on the user's own machine (macOS/Linux), no
hosted/cloud deployment in MVP scope

**Project Type**: single project — CLI-driven background agent (no web/GUI dashboard; Product
Brief §13 explicitly excludes one from MVP)

**Performance Goals**: on-demand single-topic run completes in <5 minutes (FR-009/SC-004); a full
scheduled multi-topic run (≤5 topics/user) completes well within that same order of magnitude,
non-blocking across topics (one topic's failure never blocks another's — FR-002)

**Constraints**: fixed one-time $50 total budget, tracked cumulatively (Constitution VI); Fetch/
Filter/Detect/Cluster MUST remain fully deterministic, no LLM/agent judgment at any tier
(Constitution I, II — see research.md §3/§5 for how the PRD's "deeper LLM check" language was
reconciled with this); credentials env-var only, never committed (Constitution V, FR-021); raw X
data used only for run duration, not retained beyond baseline needs (FR-020); ≤5 autonomous posts
per rolling 24h per user + kill switch (FR-022); jittered posting timing, never fixed cadence
(FR-014); autonomous mode blocked without a live "automated" bio label (FR-013); manual-only
posting for the first 3 weeks regardless of confidence (FR-010)

**Scale/Scope**: 2 users (MVP-fixed per spec Assumptions), ~5 tracked topics/user, ~200 posts/
topic/run, daily default cadence (~30 scheduled runs/month) plus on-demand runs

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Status |
|---|---|---|
| I. Deterministic, Testable Data Pipeline | Fetch/Filter/Detect/Cluster use only rules, stats, and local embeddings (`nomic-embed-text`); each stage has a defined input/output contract (`contracts/pipeline-stages.md`). Resolved a real conflict: the source PRD described Filter's "deeper judgment check" as an LLM call — redesigned as a deterministic embedding-based coordinated-content check instead (research.md §5), confirmed with the user. | **PASS** |
| II. Filter-Before-Detect Ordering | Pipeline order is Fetch → Filter → Detect → Cluster; Detect's input is explicitly post-Filter `kept` counts only (`contracts/pipeline-stages.md`). | **PASS** |
| III. Staged Posting Autonomy | `PostingMode` defaults to `manual`; autonomous requires the explicit `posting mode set autonomous` toggle, blocked until the 3-week validation period ends (data-model.md). | **PASS** |
| IV. Platform-Safe Autonomous Posting | Bio-label live-check gates the mode switch (FR-013); jittered timing enforced procedurally at publish time (FR-014). | **PASS** |
| V. Credential Hygiene | All provider credentials (TwitterAPI.io, X OAuth, Anthropic, Resend) are env-var only (research.md, contracts/external-integrations.md). | **PASS** |
| VI. Cost Discipline | Paid usage confined to TwitterAPI.io reads (~$4.50/mo at MVP scale) and Claude for Summarize/Draft only — Sonnet during weeks 1-3 (~$2-9/mo, tracked against the $5 credit) with an explicit reassess-and-possibly-downgrade-to-Haiku checkpoint at the week-3 mode switch rather than an open-ended commitment; embeddings and Filter run on $0 local Ollama; X posting cost is negligible and capped by FR-022 (research.md §3, §4, §6, §7). | **PASS** |
| VII. Measurable Definition of Done | Every FR ties to a stated SC or acceptance scenario in spec.md; quickstart.md gives a runnable validation script per user story. | **PASS** |

No unresolved violations — Complexity Tracking table below is empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-x-hype-finder-mvp/
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
├── models/          # User, Topic, TopicBaselineSnapshot, Digest, DigestTopicResult,
│                     # SourcePost, Theme, DraftPost, PostingMode (data-model.md)
├── pipeline/         # deterministic stages — one module per stage boundary
│   ├── fetch.py       # TwitterAPI.io client + per-topic error handling
│   ├── filter.py       # Tier 1 rule scoring + Tier 2 embedding coordinated-content check
│   ├── detect.py       # baseline comparison, 7-day observation gate
│   ├── cluster.py       # nomic-embed-text similarity grouping
│   └── rank.py         # descending-significance ordering
├── agent/            # LLM-powered stages (Claude Haiku 4.5 only)
│   ├── summarize.py
│   └── draft_post.py
├── posting/          # PostingMode state machine, bio-label check, jitter, 24h cap,
│                       # kill switch, tweepy publish client
├── notify/           # Resend email client (FR-023)
├── scheduler/         # APScheduler wiring for scheduled + on-demand runs
├── cli/              # topic, digest, posting, drafts commands (contracts/cli-commands.md)
└── db/               # sqlalchemy models/session, SQLite migrations

tests/
├── contract/         # TwitterAPI.io, X posting API, Claude API, Ollama, Resend
├── integration/       # one test per user-story acceptance scenario (spec.md)
└── unit/             # filter rules, spike math, clustering, ranking
```

**Structure Decision**: Single project (Option 1) — a CLI-driven background agent with no
frontend/dashboard, matching Project Type above and the MVP's explicit out-of-scope web UI. The
`pipeline/` vs `agent/` split mirrors the PRD's own architecture split (deterministic vs
LLM-judgment layers) and directly enforces Constitution Principles I and II at the module
boundary.

## Constitution Check (Post-Design Re-check)

*Re-evaluated after Phase 1 design (data-model.md, contracts/, quickstart.md).*

All seven principles remain satisfied by the design as detailed in data-model.md and contracts/:
the Filter/Detect/Cluster boundary stays LLM-free even in `Theme`/`SourcePost` schema fields;
`PostingMode` encodes every Principle III/IV safeguard as explicit, testable state rather than
incidental logic; credentials appear nowhere in the data model itself, only as env-var-sourced
client config (contracts/external-integrations.md). No new violations were introduced during
design. **Status: PASS.**

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No violations — this table is intentionally empty.
