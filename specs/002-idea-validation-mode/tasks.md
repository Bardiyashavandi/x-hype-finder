# Tasks: Idea Validation Mode

**Input**: Design documents from `/specs/002-idea-validation-mode/`

**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included — plan.md's Technical Context commits to unit/contract/integration/eval test
coverage for every new module, matching the existing project's test-per-stage convention.

**Organization**: spec.md defines a single end-to-end user story (§4) rather than several
prioritized ones, so all feature work lives under one User Story 1 (P1) phase — the whole feature
**is** the MVP scope.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 for every task in the User Story phase; Setup/Foundational/Polish carry no
  story label
- Every description includes its exact file path

## Path Conventions

Single project (per plan.md's Structure Decision) — `src/`, `tests/` at repository root, no new
CLI entry-point registration (this project's commands are invoked as `python -m src.cli.<module>`,
not via `[project.scripts]` — see `docs/cli-usage.md`).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: create the two new package directories this feature introduces before anything is
written into them.

- [ ] T001 [P] Create `src/report/__init__.py` (empty package init) for the new report package (plan.md Project Structure)
- [ ] T002 [P] Create `tests/eval/__init__.py` (empty package init) for the new eval-fixture test package (plan.md Project Structure)

**Checkpoint**: new package directories exist and are importable.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the two building blocks every later task in this feature is built on — a reusable
Fetch primitive that accepts a prebuilt query string, and the query-construction module that
builds one from a phrase list. No user-story work can start until both exist.

**⚠️ CRITICAL**: No User Story 1 work can begin until this phase is complete.

- [ ] T003 [P] Extract `fetch_posts_for_query(query: str, *, api_key, max_posts, session) -> FetchResult` primitive out of the existing pagination/retry/rate-limit-pacing loop in `src/pipeline/fetch.py`; refactor `fetch_topic_posts` to build its query via the existing `build_search_query` and then delegate to the new primitive, with its own public signature and behavior unchanged (research.md §4, contracts/pipeline-stages.md § Fetch)
- [ ] T004 [P] Implement the `IdeaValidationQuery` dataclass (`phrases`, `exclude_terms`, `since`, `until`) with non-empty/whitespace-stripped phrase validation and case-insensitive de-duplication of both `phrases` and `exclude_terms`, plus `build_idea_validation_query(phrases, exclude_terms, since, until) -> str` (OR of quoted phrases + negated `-"term"` clauses per exclude term) in `src/pipeline/idea_query_builder.py` (data-model.md § IdeaValidationQuery, contracts/pipeline-stages.md § Query Construction)

**Checkpoint**: `fetch_posts_for_query` can be driven by a prebuilt idea-validation query string;
`tests/contract/test_twitterapi_io.py` still passes unmodified against the refactored `fetch.py`
internals, confirming `fetch_topic_posts`'s existing callers are unaffected.

---

## Phase 3: User Story 1 - Validate a problem statement and get a strategic readout (Priority: P1) 🎯 MVP

**Goal**: a strategist runs `python -m src.cli.idea_validate run --phrase "..." [--exclude-term
"..."]` and gets back a validation readout — signal strength, 2-4 recurring themes, representative
example posts, or an explicit "no meaningful signal found" — with zero database writes and no
posting step (spec.md §4, §5.3, §7).

**Independent Test**: run quickstart.md Scenarios 1, 3, and 4 against the synthetic "sublet"
example — confirm the readout prints signal strength + themes (or the explicit no-signal state),
and that `digests`/`themes`/`source_posts`/`draft_posts` row counts are identical before and after
the run.

### Tests for User Story 1 ⚠️

> Write these first — they exercise modules from Phase 2/3 Implementation that don't exist yet
> and are expected to fail until those tasks land.

- [ ] T005 [P] [US1] Unit test `build_idea_validation_query`'s phrase OR-quoting, exclude-term negation, and empty-phrase-list rejection in `tests/unit/test_idea_query_builder.py` (contracts/pipeline-stages.md § Query Construction acceptance)
- [ ] T006 [P] [US1] Unit test `filter_relevance`'s `kept`/`excluded_term_match` tagging and `matched_term` recording, including the "no post is dropped from the record" invariant, in `tests/unit/test_relevance_filter.py` (contracts/pipeline-stages.md § Relevance Filter)
- [ ] T007 [P] [US1] Unit test `compute_signal_strength`'s zero-post case (`total_relevant_count=0`, `most_recent_post_at`/`oldest_post_at=None`) and its `posts_last_24h`/`posts_last_7d` recency-bucket counts in `tests/unit/test_signal_strength.py` (contracts/pipeline-stages.md § Signal Strength acceptance)
- [ ] T008 [P] [US1] Contract test `summarize_validation_theme`'s structured tool-call schema, retry-on-transient-`anthropic`-error behavior, and `record_claude_usage` cost-tracker call in `tests/contract/test_claude_validate_summarize.py` (contracts/pipeline-stages.md § Validate Summarize)
- [ ] T009 [P] [US1] Hand-labeled real-complaint-vs-noise fixture set (spec.md §6) + precision computation for `filter_relevance` against the ≥80% target, reporting fixture `n` alongside the result, in `tests/eval/test_relevance_filter_precision.py` (contracts/pipeline-stages.md § Relevance Filter acceptance)
- [ ] T010 [US1] End-to-end integration test running Query Construction → Fetch → Relevance Filter → Bot/Noise Filter → Signal Strength → Cluster → Validate Summarize → Validation Readout against a synthetic problem-space fixture (mocked Fetch + Claude responses): assert zero row-count change across `digests`/`themes`/`source_posts`/`draft_posts`, a non-empty readout for the signal-present case, and the explicit "no meaningful signal found" readout for a zero-signal case, in `tests/integration/test_idea_validation_flow.py` (quickstart.md Scenarios 1, 3, 4; spec.md §7)

### Implementation for User Story 1

- [ ] T011 [P] [US1] Implement the `RelevanceOutcome` enum (`KEPT`, `EXCLUDED_TERM_MATCH`) + `RelevantPost` dataclass + `filter_relevance(posts, exclude_terms) -> list[RelevantPost]` (case-insensitive substring match of each exclude term against normalized post text, reusing the `_normalize` link-stripping/lowercasing pattern from `src/pipeline/filter.py`; first match wins and is recorded as `matched_term`) in `src/pipeline/relevance_filter.py` (data-model.md § RelevantPost, contracts/pipeline-stages.md § Relevance Filter)
- [ ] T012 [P] [US1] Implement the `SignalStrength` dataclass + `compute_signal_strength(posts, *, now) -> SignalStrength` (`total_relevant_count`, `distinct_author_count`, `most_recent_post_at`, `oldest_post_at`, `posts_last_24h`, `posts_last_7d`) in `src/pipeline/signal_strength.py` (data-model.md § SignalStrength, contracts/pipeline-stages.md § Signal Strength)
- [ ] T013 [P] [US1] Implement the `ValidationTheme` dataclass + `ValidateSummarizeError` + `summarize_validation_theme(data, *, api_key, model, client=None) -> ValidationSummarizeResult`, mirroring `summarize.py`'s structured-tool-call pattern (grammar-constrained schema, `retry_with_backoff`, `record_claude_usage`, leaked-parameter recovery) but with the "what people want/are frustrated by" prompt and a `recurrence_signal` field grounded in `cluster_post_count`/`distinct_author_count` instead of a spike-ratio-grounded `confidence_score`, in `src/agent/validate_summarize.py` (data-model.md § ValidationTheme, contracts/pipeline-stages.md § Validate Summarize, research.md §5)
- [ ] T014 [US1] Implement the `ValidationReadout` dataclass + `build_validation_readout(query, signal_strength, themes, *, now) -> ValidationReadout` (themes ordered by `cluster_post_count` desc, ties broken by `distinct_author_count` then original order) + `render_validation_readout(readout) -> str` (explicit "no meaningful signal found" text when `total_relevant_count == 0` or `themes == []`, never a blank output) in `src/report/validation_readout.py` (data-model.md § ValidationReadout, contracts/pipeline-stages.md § Validation Readout) — depends on T012, T013 for the dataclasses it composes
- [ ] T015 [US1] Implement the `idea-validate run` CLI command in `src/cli/idea_validate.py`: argparse for `--phrase` (repeatable, ≥1 required, reject with a clear message before any network call if none given), `--exclude-term` (repeatable, optional), `--since`/`--until` (ISO 8601, default to Fetch's existing lookback), `--out <path>` (writes the rendered readout to a file in addition to stdout); wires `IdeaValidationQuery` → `build_idea_validation_query` (T004) → `fetch_posts_for_query` (T003) → `filter_relevance` (T011) → the existing unmodified `filter_posts` (bot/noise) → `compute_signal_strength` (T012) → the existing unmodified `cluster_posts` → `summarize_validation_theme` (T013) per cluster, dropping a theme with a logged note on `ValidateSummarizeError` rather than failing the run → `build_validation_readout`/`render_validation_readout` (T014) → print + optional file write; opens no database session and calls no per-user credential/`Topic` lookup (contracts/cli-commands.md § `idea-validate run`) — depends on T003, T004, T011, T012, T013, T014

**Checkpoint**: User Story 1 is fully functional and independently testable — `idea-validate run`
produces a complete validation readout end-to-end with no side effects on the existing
brand-tracking/posting pipeline.

---

## Phase 4: Polish & Cross-Cutting Concerns

**Purpose**: documentation and acceptance verification once User Story 1 is complete.

- [ ] T016 [P] Add an `idea-validate run` section to `docs/cli-usage.md` (flags, example invocation, sample readout output) matching the existing per-command documentation pattern used for `topic`/`digest`/`posting`/`drafts`/`eval`/`scheduler`
- [ ] T017 [P] Add an "Idea Validation Mode" mention to `README.md`'s Usage/How It Works sections, describing it as a separate, non-scheduled, non-persisted mode (linking to `docs/cli-usage.md` for the full command reference) — matching how other modes are documented there
- [ ] T018 Run quickstart.md Scenarios 1-4 end-to-end against the synthetic "sublet" example on a real (non-mocked) run and record the results against spec.md §7's success criteria (Constitution VII — measurable definition of done)
- [ ] T019 [P] Confirm `summarize_validation_theme` usage appears in the existing cost ledger (`src/utils/cost_tracker.py` / `.data/cost_ledger.jsonl`) after the T018 real run, verifying no untracked spend path was introduced (plan.md Constitution Check § VI)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies — can start immediately
- **Foundational (Phase 2)**: depends on Setup completion — BLOCKS User Story 1
- **User Story 1 (Phase 3)**: depends on Foundational phase completion
- **Polish (Phase 4)**: depends on User Story 1 completion

### Within User Story 1

- Tests (T005-T010) exercise code from Foundational (T003, T004) and from this phase's own
  Implementation tasks (T011-T015) — expected to fail until the corresponding implementation task
  lands, then pass.
- T011 (Relevance Filter), T012 (Signal Strength), T013 (Validate Summarize) are mutually
  independent — different files, no shared code dependency.
- T014 (Validation Readout) depends on T012 and T013 (composes their dataclasses).
- T015 (CLI wiring) depends on everything before it in this phase and on both Foundational tasks
  (T003, T004) — it is the integration point, done last.

### Parallel Opportunities

- T001 and T002 (Setup) in parallel.
- T003 and T004 (Foundational) in parallel — different files, no shared dependency.
- T005-T009 (US1 tests, excluding the integration test T010) in parallel — five different files.
- T011, T012, T013 (US1 implementation) in parallel — three independent modules.
- T016, T017, T019 (Polish) in parallel — different files/independent verifications.

---

## Parallel Example: User Story 1

```bash
# Launch the independent US1 unit/contract/eval tests together:
Task: "Unit test build_idea_validation_query in tests/unit/test_idea_query_builder.py"
Task: "Unit test filter_relevance in tests/unit/test_relevance_filter.py"
Task: "Unit test compute_signal_strength in tests/unit/test_signal_strength.py"
Task: "Contract test summarize_validation_theme in tests/contract/test_claude_validate_summarize.py"
Task: "Relevance-filter precision eval in tests/eval/test_relevance_filter_precision.py"

# Then launch the three independent US1 implementation modules together:
Task: "Implement filter_relevance in src/pipeline/relevance_filter.py"
Task: "Implement compute_signal_strength in src/pipeline/signal_strength.py"
Task: "Implement summarize_validation_theme in src/agent/validate_summarize.py"
```

---

## Implementation Strategy

### MVP First (and only) — User Story 1

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks everything else)
3. Complete Phase 3: User Story 1 (the entire feature)
4. **STOP and VALIDATE**: run quickstart.md Scenarios 1-4 independently
5. Complete Phase 4: Polish, then demo/ship

Since spec.md defines only one user story, there is no incremental multi-story delivery plan here
— Phase 3 completion **is** feature completion.

---

## Notes

- [P] tasks = different files, no dependency on an incomplete task
- [US1] label maps every Phase 3 task to the feature's single user story
- Verify T005-T010 fail before their corresponding implementation task lands, then pass after
- Commit after each task or logical group
- Stop at the Phase 3 checkpoint to validate the story independently before moving to Polish
- Avoid: same-file conflicts between "parallel" tasks, and skipping the Foundational phase's
  `fetch.py` refactor verification (existing contract tests must keep passing unmodified)
