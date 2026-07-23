---

description: "Task list for X Hype Finder MVP implementation"
---

# Tasks: X Hype Finder MVP

**Input**: Design documents from `/specs/001-x-hype-finder-mvp/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (pipeline-stages.md, cli-commands.md, external-integrations.md), quickstart.md

**Tests**: Included — plan.md's Testing section and Project Structure explicitly define `tests/contract/`, `tests/integration/`, `tests/unit/` directories, and Constitution Principle VII requires a measurable, verified acceptance criterion per stage before it is "done."

**Organization**: Tasks are grouped by user story (spec.md priorities P1-P3) to enable independent implementation and testing of each story.

> **Revision note**: This revision incorporates the remediation from `/speckit-analyze` (7 findings: C1, E1, I2, E2, U1, A1, D1). Task IDs below were renumbered to make room for 3 new tasks (T022, T032, T059); see inline notes at each changed task.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1-US5)
- File paths are exact, per plan.md's Project Structure

## Path Conventions

Single project (per plan.md Structure Decision): `src/` and `tests/` at repository root —
`src/models/`, `src/pipeline/`, `src/agent/`, `src/posting/`, `src/notify/`, `src/scheduler/`,
`src/cli/`, `src/db/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [X] T001 Create project directory structure per plan.md: `src/{models,pipeline,agent,posting,notify,scheduler,cli,db}/`, `tests/{contract,integration,unit}/`, each with `__init__.py`
- [X] T002 Initialize Python 3.11+ project with `pyproject.toml` pinning `tweepy`, `anthropic`, `requests`, `numpy`, `scikit-learn`, `apscheduler`, `sqlalchemy`, `alembic`, `python-dotenv`, `pytest` (per plan.md Technical Context)
- [X] T003 [P] Configure `ruff`/`black` linting and formatting in `pyproject.toml`
- [X] T004 [P] Create `.env.example` documenting required env vars (`TWITTERAPI_IO_KEY`, `ANTHROPIC_API_KEY`, `RESEND_API_KEY`, X OAuth 1.0a/2.0 credentials) with no real values, and confirm `.env` is in `.gitignore` (FR-021, Constitution V)
- [X] T005 [P] Configure `pytest` in `pyproject.toml`/`conftest.py` with a test-scoped SQLite DB fixture in `tests/conftest.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared data model, DB access, config, and cross-cutting infrastructure every user story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T006 Implement SQLAlchemy engine/session management in `src/db/session.py`
- [X] T007 Scaffold Alembic migrations in `src/db/migrations/` (env.py, script template) wired to the engine from T006
- [X] T008 [P] Create `User` model in `src/models/user.py` (id, email, x_account_handle, created_at — data-model.md)
- [X] T009 [P] Create `Topic` model in `src/models/topic.py` (id, user_id, name, x_handles, status, first_tracked_at — data-model.md)
- [X] T010 [P] Create `TopicBaselineSnapshot` model in `src/models/topic_baseline_snapshot.py` (id, topic_id, window_date, filtered_post_count — data-model.md)
- [X] T011 [P] Create `Digest` model in `src/models/digest.py` (id, user_id, run_type, started_at, completed_at, status, notification_sent_at — data-model.md)
- [X] T012 [P] Create `DigestTopicResult` model in `src/models/digest_topic_result.py` (id, digest_id, topic_id, outcome, error_detail — data-model.md)
- [X] T013 [P] Create `SourcePost` model in `src/models/source_post.py` (id, topic_id, digest_topic_result_id, x_post_id, author_handle, text, posted_at, filter_outcome, theme_id, **is_example: bool**, — data-model.md; `is_example` flags the curated 3-5 posts shown by default per Theme, distinct from the full drill-down set — FR-008, FR-016; *added per /speckit-analyze finding I2*)
- [X] T014 [P] Create `Theme` model in `src/models/theme.py` (id, digest_topic_result_id, summary, rationale, confidence_score, is_spike, spike_ratio, cluster_post_count, rank — data-model.md)
- [X] T015 [P] Create `DraftPost` model in `src/models/draft_post.py` (id, theme_id, user_id, draft_text, confidence_score, status, created_at, published_at, publish_error — data-model.md)
- [X] T016 [P] Create `PostingMode` model in `src/models/posting_mode.py` (id, user_id unique, mode, confidence_threshold, validation_period_ends_at, kill_switch_engaged, last_post_published_at, updated_at — data-model.md)
- [X] T017 Generate initial Alembic migration covering all models from T008-T016 (depends on T008-T016)
- [X] T018 Implement a per-user-scoped query helper/base repository in `src/db/scoped.py` that enforces `user_id` filtering on every query (FR-015, Constitution Security & Privacy Constraints)
- [X] T019 [P] Implement structured logging configuration in `src/logging_config.py` (clear, per-topic error visibility per FR-002/FR-018)
- [X] T020 [P] Implement a retry-with-backoff decorator in `src/utils/retry.py` for transient fetch/processing errors (FR-018)
- [X] T021 [P] Implement env-var-only config loader in `src/config.py` that fails fast with a clear error if a required credential is missing, never accepting a hardcoded fallback (FR-021, Constitution V); also exposes the currently-selected Claude model name (`claude-sonnet-5` default) as a runtime-configurable setting consumed by T040/T056, per research.md §3/contracts/external-integrations.md
- [X] T022 [P] **NEW (finding C1)** Implement cumulative cost tracking in `src/utils/cost_tracker.py` that logs TwitterAPI.io read costs and Claude API token spend (input/output tokens × current pricing) against the fixed one-time $50 total budget, exposing a running-total query used by T059's week-3 reassessment checkpoint (Constitution VI, SC-012)

**Checkpoint**: Foundation ready — user story implementation can now begin

---

## Phase 3: User Story 1 - Get a Ranked, Evidence-Backed Hype Digest (Priority: P1) 🎯 MVP

**Goal**: Fetch → Filter → Detect → Cluster → Summarize → Rank a full run for a user's tracked topics into one persisted, notified Digest.

**Independent Test**: Configure a topic with 7+ days of seeded baseline plus an injected spike and a non-spiking control topic; run the pipeline once; confirm the digest surfaces the spiking topic (summary, rationale, confidence, 3-5 examples) and the control topic does not falsely appear (spec.md Independent Test, quickstart.md Scenario 1).

### Tests for User Story 1 ⚠️

- [X] T023 [P] [US1] Unit test Filter Tier 1 rule scoring (account age, follower ratio, velocity, duplicate-text ratio, link ratio, spam patterns) in `tests/unit/test_filter_tier1.py`
- [X] T024 [P] [US1] Unit test Filter Tier 2 embedding coordinated-content escalation in `tests/unit/test_filter_tier2.py`
- [X] T025 [P] [US1] Unit test Detect baseline/spike math and 7-day observation gate in `tests/unit/test_detect.py`
- [X] T026 [P] [US1] Unit test Cluster near-duplicate similarity grouping in `tests/unit/test_cluster.py`
- [X] T027 [P] [US1] Unit test Rank descending-significance ordering in `tests/unit/test_rank.py`
- [X] T028 [P] [US1] Contract test TwitterAPI.io Fetch client (request shape, retry-then-error behavior) in `tests/contract/test_twitterapi_io.py`
- [X] T029 [P] [US1] Contract test Ollama embeddings client (`nomic-embed-text` via localhost:11434) in `tests/contract/test_ollama_embeddings.py`
- [X] T030 [P] [US1] Contract test Claude Summarize stage structured output (`summary`, `rationale`, `confidence_score`) in `tests/contract/test_claude_summarize.py`
- [X] T031 [P] [US1] Contract test Resend notification client in `tests/contract/test_resend.py`
- [X] T032 [P] [US1] **NEW (finding U1)** Construct and curate a labeled fixture set of 50 known bot/spam posts mixed with genuine posts in `tests/fixtures/labeled_bot_spam_posts.json`, used by T033's ≥90%-exclusion assertion (SC-002; quickstart.md Scenario 1 step 7)
- [X] T033 [US1] Integration test for User Story 1 acceptance scenarios (spike surfaced, control not false-positive, 7-day gate, near-duplicate clustering, ≥90% bot exclusion using the T032 fixture) in `tests/integration/test_digest_pipeline.py` (depends on T032)

### Implementation for User Story 1

- [X] T034 [US1] Implement TwitterAPI.io Fetch client in `src/pipeline/fetch.py` — per-topic error record on persistent failure, never halting other topics (FR-002), using retry from T020; reports read costs to the cost tracker from T022
- [X] T035 [US1] Implement Filter Tier 1 rule scoring in `src/pipeline/filter.py` (clear-keep / clear-exclude / ambiguous per research.md §5)
- [X] T036 [US1] Implement Ollama embeddings client wrapper in `src/pipeline/embeddings.py` (fails fast with a clear local-setup error if Ollama is unreachable, per contracts/external-integrations.md)
- [X] T037 [US1] Implement Filter Tier 2 embedding-based coordinated-content check in `src/pipeline/filter.py`, escalated only for Tier 1 ambiguous posts (depends on T035, T036)
- [X] T038 [US1] Implement Detect baseline comparison and 7-day observation gate in `src/pipeline/detect.py` (`is_spike`, `spike_ratio` — FR-004, FR-005)
- [X] T039 [US1] Implement Cluster similarity grouping into Theme candidates in `src/pipeline/cluster.py` (depends on T036)
- [X] T040 [US1] Implement Claude Summarize client in `src/agent/summarize.py` — structured tool-call output grounded on spike_ratio/cluster_post_count/filter-survival-rate/account-diversity context (FR-007, research.md §3/§12); **model name is read from `src/config.py` (T021), never hardcoded — defaults to `claude-sonnet-5`, may switch to `claude-haiku-4-5-20251001` after T059's week-3 reassessment (finding E1)**; reports token spend to the cost tracker from T022
- [X] T041 [US1] Implement Rank ordering across a run's Themes in `src/pipeline/rank.py` (FR-008)
- [X] T042 [US1] Implement `TopicBaselineSnapshot` daily write plus **inline, per-run** `SourcePost` retention prune in `src/pipeline/baseline.py` (FR-020) — this task covers pruning executed immediately after each run writes its baseline snapshot; T070 (Polish) separately covers a standalone periodic sweep for rows this per-run prune could miss (e.g. from a run that failed before completing) — *distinction clarified per /speckit-analyze finding D1*
- [X] T043 [US1] Implement the digest run orchestrator in `src/pipeline/orchestrator.py` wiring Fetch→Filter→Detect→Cluster→Summarize→Rank into `Digest`/`DigestTopicResult`/`Theme`/`SourcePost` writes, handling `no_significant_activity`/`all_filtered_as_noise`/`fetch_error`/`incomplete_rate_limited` outcomes explicitly per topic (FR-017; depends on T034-T042)
- [X] T044 [US1] Implement `topic add/remove/list` CLI commands in `src/cli/topic.py` (contracts/cli-commands.md; FR-001, SC-001)
- [X] T045 [US1] Implement `digest run` CLI command invoking the orchestrator in `src/cli/digest.py` (depends on T043)
- [X] T046 [US1] Implement Resend digest-completion notification in `src/notify/email.py`, sent when `Digest.status` transitions to `completed`, `partial`, **or `failed`** (extended per /speckit-analyze finding E2 — FR-018 requires a scheduled run's failure to be visible to the user before the next expected run; there is no dashboard, so this notification is the only channel), logged-not-blocking on send failure (FR-023)
- [X] T047 [US1] Wire the default daily (user-configurable) `APScheduler` cadence job invoking the same orchestrator in `src/scheduler/jobs.py` (FR-009 scheduled path; depends on T043)

**Checkpoint**: User Story 1 is fully functional and independently testable

---

## Phase 4: User Story 2 - Trigger a Digest On Demand (Priority: P2)

**Goal**: Let a user manually trigger an immediate run for one topic, matching scheduled-run quality and completing under 5 minutes.

**Independent Test**: With topics already configured, manually trigger a run and confirm results return within the time budget and match scheduled-run quality (spec.md Independent Test; quickstart.md Scenario 2).

### Tests for User Story 2 ⚠️

- [X] T048 [P] [US2] Integration test that an on-demand single-topic run completes in under 5 minutes and matches scheduled-run output format/quality in `tests/integration/test_on_demand_digest.py`

### Implementation for User Story 2

- [X] T049 [US2] Add `--topic <name>` single-topic scoping to the `digest run` CLI command in `src/cli/digest.py` (depends on T045)
- [X] T050 [US2] Add run-duration instrumentation/logging to the orchestrator to verify the <5 minute budget in `src/pipeline/orchestrator.py` (FR-009, SC-004)

**Checkpoint**: User Stories 1 AND 2 both work independently

---

## Phase 5: User Story 3 - Drill Into Source Evidence (Priority: P2)

**Goal**: Let a user retrieve every underlying filtered/clustered post behind a digest entry, not just the shown examples, and see an explicit state when a topic had nothing to show.

**Independent Test**: From a delivered digest entry, request full source data and confirm every underlying post and the filtering trail are available (spec.md Independent Test; quickstart.md Scenario 3).

### Tests for User Story 3 ⚠️

- [X] T051 [P] [US3] Integration test full source drill-down (all N posts + `filter_outcome` trail) and the explicit `all_filtered_as_noise` state in `tests/integration/test_drilldown.py`

### Implementation for User Story 3

- [X] T052 [US3] Implement `digest show <digest-id> [--topic <name>] [--full]` CLI command in `src/cli/digest.py` — default view shows the 3-5 `is_example`-flagged posts per Theme (T013); `--full` shows every `SourcePost` plus `filter_outcome`, for both Theme-clustered and Filter-excluded posts; renders `no_significant_activity`/`all_filtered_as_noise`/`fetch_error`/`incomplete_rate_limited` explicitly rather than an empty entry (FR-016, FR-017). `--topic <name>` scopes rendering to a single topic, erroring clearly if the name doesn't match anything in the digest.

**Checkpoint**: User Stories 1-3 all work independently

---

## Phase 6: User Story 4 - Manual-First, Then Confidence-Gated Autonomous Posting (Priority: P3)

**Goal**: Hold every draft for manual publishing during the first 3 weeks; after validation, support an explicit, gated switch to confidence-based autonomous posting with bio-label, jitter, cap, and kill-switch safeguards.

**Independent Test**: During the first 3 weeks, generate drafts across confidence levels and confirm none post automatically; then flip the mode toggle (with prerequisites met) and confirm threshold-based auto-posting, labeling, and timing safeguards take effect (spec.md Independent Test; quickstart.md Scenario 4).

### Tests for User Story 4 ⚠️

- [ ] T053 [P] [US4] Unit test `PostingMode` state-machine gating (validation-period check, bio-label check, threshold routing, kill switch, rolling 24h/5-post cap) in `tests/unit/test_posting_mode.py`
- [ ] T054 [P] [US4] Contract test X posting API via `tweepy` (bio-label read, publish call, failure surfacing) in `tests/contract/test_x_posting.py`
- [ ] T055 [US4] Integration test User Story 4 acceptance scenarios (manual-only hold, gated autonomous switch, threshold routing never silently discarding, jittered timing, publish-failure surfacing, no retroactive auto-publish after a mid-cycle switch) in `tests/integration/test_posting_autonomy.py`

### Implementation for User Story 4

- [ ] T056 [US4] Implement the Draft Post Claude client in `src/agent/draft_post.py` — `draft_text` generated from a high-signal Theme (contracts/pipeline-stages.md); **model name is read from `src/config.py` (T021), never hardcoded — defaults to `claude-sonnet-5`, may switch to `claude-haiku-4-5-20251001` after T059's week-3 reassessment (finding E1)**; reports token spend to the cost tracker from T022
- [ ] T057 [US4] Wire `DraftPost` creation into the orchestrator, with `status` assigned exactly once per the `PostingMode` in effect at creation time — never changed retroactively by a later mode switch — in `src/pipeline/orchestrator.py` (depends on T043, T056)
- [ ] T058 [US4] Implement the `PostingMode` state machine (manual/autonomous transitions, `validation_period_ends_at` gate, `kill_switch_engaged`) in `src/posting/mode.py` (FR-010, FR-011)
- [ ] T059 [US4] **NEW (finding E1)** Implement the week-3 reassess-and-possibly-downgrade checkpoint in `src/posting/model_checkpoint.py`: at `validation_period_ends_at` (the same week-3 moment T058 gates the mode switch on), read cumulative spend from T022's cost tracker against the $5 Anthropic credit; if spend is holding up, keep the config value from T021 at `claude-sonnet-5` for T040/T056; if budget is tight, switch it to `claude-haiku-4-5-20251001` (research.md §3; depends on T022, T040, T056, T058)
- [ ] T060 [US4] Implement the live X account bio "automated"-label check via `tweepy` in `src/posting/bio_check.py`, checked at the instant the mode switches to autonomous (FR-013)
- [ ] T061 [US4] Implement jittered publish timing plus rolling-24h/5-post cap enforcement in `src/posting/rate_limit.py` (FR-014, FR-022)
- [ ] T062 [US4] Implement the autonomous publish client in `src/posting/publish.py` — `published_auto` on success, `publish_failed` with `publish_error` surfaced (never silently dropped) on failure (FR-012, FR-019; depends on T058, T060, T061)
- [ ] T063 [US4] Implement `posting mode show`, `posting mode set autonomous`, `posting mode set manual`, and `posting kill-switch on|off` CLI commands in `src/cli/posting.py` (contracts/cli-commands.md; depends on T058, T060)
- [ ] T064 [US4] Implement `drafts list [--status <status>]` and `drafts mark-published <draft-id>` CLI commands in `src/cli/drafts.py` (contracts/cli-commands.md)

**Checkpoint**: User Stories 1-4 all work independently

---

## Phase 7: User Story 5 - Independent Multi-User Operation (Priority: P3)

**Goal**: Guarantee each user's topics, credentials, and history are fully isolated from the other's.

**Independent Test**: Configure two users with overlapping topic names and confirm each only ever sees their own data, credentials, and history (spec.md Independent Test; quickstart.md Scenario 5).

### Tests for User Story 5 ⚠️

- [ ] T065 [P] [US5] Integration test two-user isolation with overlapping topic names — cross-user data/credential access is blocked in `tests/integration/test_multi_user_isolation.py`

### Implementation for User Story 5

- [ ] T066 [US5] Audit and enforce `user_id` scoping across every repository/query call path built in prior phases in `src/db/scoped.py` and its callers (FR-015; depends on T018)
- [ ] T067 [US5] Implement per-user credential loading (no cross-user credential access, per-user X OAuth/env-var namespacing) in `src/config.py` (FR-015, FR-021)

**Checkpoint**: All user stories independently functional

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that span multiple user stories

- [ ] T068 [P] Document CLI usage for every command from contracts/cli-commands.md in `docs/cli-usage.md`
- [ ] T069 [P] Unit test the retry-with-backoff utility in `tests/unit/test_retry.py`
- [ ] T070 [P] Implement a **separate, standalone periodic** `SourcePost` retention prune job (30-day drill-down window per FR-020) in `src/pipeline/baseline.py` — sweeps any rows older than the window that T042's inline per-run prune didn't already remove (e.g. from a run that failed before completing its prune step) — *distinction clarified per /speckit-analyze finding D1*
- [ ] T071 Security review pass: confirm no credentials are committed anywhere in the repo and `.env` stays gitignored (Constitution V, FR-021)
- [ ] T072 Run the full quickstart.md validation across all 5 scenarios end-to-end

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories (shared schema, DB session, config, logging, retry, cost tracking)
- **User Stories (Phase 3-7)**: All depend on Foundational completion
  - US1 (P1) has no dependency on other stories
  - US2 (P2) depends on US1's `digest run` CLI command and orchestrator (T043, T045) existing to extend
  - US3 (P2) depends on US1's orchestrator/models (T043) to have data to drill into, but is otherwise independent of US2
  - US4 (P3) depends on US1's orchestrator (T043) to hang `DraftPost` creation off of, and on Foundational's cost tracker (T022) for the week-3 reassessment (T059)
  - US5 (P3) depends on Foundational's `src/db/scoped.py` (T018) to audit/tighten
- **Polish (Phase 8)**: Depends on all desired user stories being complete

### Within Each User Story

- Tests are written before implementation and should fail first
- Models (Foundational) before pipeline stages
- Pipeline stages before orchestrator wiring
- Orchestrator before CLI commands that invoke it
- Story implementation complete before moving to the next priority

### Parallel Opportunities

- All Setup tasks marked [P] (T003-T005) can run in parallel after T001-T002
- All Foundational model tasks marked [P] (T008-T016) can run in parallel after T006-T007
- All Foundational cross-cutting tasks marked [P] (T019-T022) can run in parallel, including the new cost-tracker task (T022)
- Once Foundational completes, US1, and independently the test-writing sub-tasks of US2-US5, can be staffed in parallel — but US2/US3/US4 implementation tasks depend on US1's orchestrator (T043) landing first
- All [P] test tasks within a story can run in parallel with each other
- US5's isolation audit (T066) can run in parallel with US4's posting implementation once Foundational is done, since they touch different files

---

## Parallel Example: User Story 1

```bash
# Launch all US1 tests together:
Task: "Unit test Filter Tier 1 rule scoring in tests/unit/test_filter_tier1.py"
Task: "Unit test Filter Tier 2 embedding coordinated-content escalation in tests/unit/test_filter_tier2.py"
Task: "Unit test Detect baseline/spike math in tests/unit/test_detect.py"
Task: "Unit test Cluster near-duplicate similarity grouping in tests/unit/test_cluster.py"
Task: "Unit test Rank descending-significance ordering in tests/unit/test_rank.py"
Task: "Contract test TwitterAPI.io Fetch client in tests/contract/test_twitterapi_io.py"
Task: "Contract test Ollama embeddings client in tests/contract/test_ollama_embeddings.py"
Task: "Contract test Claude Summarize stage in tests/contract/test_claude_summarize.py"
Task: "Contract test Resend notification client in tests/contract/test_resend.py"
Task: "Construct/curate labeled 50-post bot/spam fixture set in tests/fixtures/labeled_bot_spam_posts.json"

# Launch independent US1 pipeline-stage implementations together (after their contract/unit tests exist):
Task: "Implement TwitterAPI.io Fetch client in src/pipeline/fetch.py"
Task: "Implement Filter Tier 1 rule scoring in src/pipeline/filter.py"
Task: "Implement Ollama embeddings client wrapper in src/pipeline/embeddings.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: run quickstart.md Scenario 1 independently
5. This alone delivers the entire core loop (Product Brief's reason the product exists)

### Incremental Delivery

1. Setup + Foundational → foundation ready
2. US1 → validate via quickstart.md Scenario 1 → this is the MVP
3. US2 → validate via quickstart.md Scenario 2 (on-demand timing/parity)
4. US3 → validate via quickstart.md Scenario 3 (drill-down)
5. US4 → validate via quickstart.md Scenario 4 (posting autonomy) — highest risk, deliberately last
6. US5 → validate via quickstart.md Scenario 5 (multi-user isolation)
7. Polish → full quickstart.md pass across all 5 scenarios

### Parallel Team Strategy

With multiple developers, after Foundational completes:
- Developer A: US1 (critical path — others build on its orchestrator)
- Developer B: starts US2/US3 test-writing and CLI scaffolding, integrates once US1's orchestrator (T043) lands
- Developer C: starts US4's Claude draft-post client and posting-safeguard modules (T056, T058, T060-T062), which have no US1-orchestrator dependency until the DraftPost wiring step (T057)

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Every FR/SC/contract reference above ties back to spec.md, data-model.md, or contracts/ — no invented scope
- Verify tests fail before implementing
- Commit after each task or logical group
- Stop at any checkpoint to validate a story independently
- US4 (autonomous posting) is intentionally last among the P3s in build order despite being listed before US5 in spec.md numbering, because it is the highest-risk capability (spec.md's own stated rationale) — teams may still build US5 in parallel since it has no dependency on US4
- SC-011 ("≥80% of digests rated worth reading") is intentionally **not** represented by a task here — per spec.md's Assumptions, it is measured out-of-band via informal check-ins with the two pilot users, not an in-product rating feature, consistent with the MVP's no-dashboard scope (clarified per /speckit-analyze finding A1)
