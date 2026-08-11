# Phase 0 Research: Idea Validation Mode

**Feature**: 002-idea-validation-mode

Every "NEEDS CLARIFICATION" below traces back to spec.md §8's two open questions, plus one design
question the stage-by-stage table (spec.md §5.2) raises but doesn't fully resolve on its own
(where exclude-terms filtering actually runs).

---

## §1. One-off script vs. reusing the scheduled digest infrastructure (spec.md §8 Q1)

**Decision**: A one-off CLI command with **no new database tables** — no `Digest`,
`DigestTopicResult`, `Theme`, `SourcePost`, or `DraftPost` rows. Output is stdout plus an optional
`--out <path>` file, not a DB-tracked entity.

**Rationale**:
- spec.md §5.3 already calls the output "a short readout, not a running digest... a one-time
  strategic input, not something scheduled daily," and Rollout step 4 says explicitly "Build the
  one-off validation readout output (not a scheduled digest)." The open question in §8 reads as
  unresolved only because it's phrased as a question, but the rest of the spec already answers it.
- Reusing `Digest`/`Theme` would drag in `PostingMode`/`DraftPost` by construction — the
  orchestrator (`src/pipeline/orchestrator.py`) creates a `DraftPost` for *every* `Theme` it
  writes, unconditionally, as part of the same transaction. Idea Validation mode's non-goal is
  explicit: "no changes to brand-tracking or client-report features — this is a separate mode, run
  independently." Reusing the Digest schema means either (a) special-casing the orchestrator to
  skip draft creation for this run type — a behavior change to shared, tested code for a
  feature that's supposed to be additive-only — or (b) writing `Theme` rows that never get a
  `DraftPost`, which breaks an invariant every other part of the codebase (eval CLI, `digest
  show`) currently assumes holds.
- The Security & Privacy Constraint ("X data MUST be used only for the duration of analysis and
  MUST NOT be stored permanently beyond what's needed to maintain each topic's historical
  baseline") is satisfied *by construction* if nothing is persisted — there is no baseline to
  maintain in this mode at all (§5.2's own "Detect" row: "a new problem space has no history to
  compare against"), so persisting posts would exceed what's needed for a purpose that doesn't
  exist here.
- A stateless design is also the smaller, more testable unit (Constitution VII) — every stage
  becomes a pure function over in-memory data, no DB fixtures/migrations needed for tests.

**Alternatives considered**:
- *Full reuse of `Digest`/`Theme`/`SourcePost`*: rejected per above — couples an internal-strategy
  tool to the client-facing brand-tracking schema and its posting side effects.
- *A parallel but persisted schema (e.g. `IdeaValidationRun`/`IdeaValidationTheme` tables)*:
  rejected for v1 as premature — nothing in spec.md's success criteria (§7) or user story (§4)
  requires historical recall of past validation runs; the strategist reads the readout once, in
  the moment, to inform a client conversation. Revisit if usage shows people want to compare
  runs over time (would then also need retention-policy decisions this spec doesn't make).

---

## §2. Synthetic vs. real client idea for the first test (spec.md §8 Q2)

**Decision**: Synthetic problem-space example for the first version, per spec.md Rollout step 5
("Test against a synthetic problem-space example"). This plan's quickstart.md uses the spec's own
"sublet" example (§2, §5.2) as the canonical walkthrough.

**Rationale**: No client consent process exists yet, and building one is out of scope for this
plan (it's an agency/business-process question, not a pipeline design question). Using a synthetic
example unblocks implementation and testing now; swapping in a real, consented client idea later
requires zero code changes — it's just a different `--phrase`/`--exclude-term` input to the same
command.

**Alternatives considered**: Waiting on a real client idea before building anything — rejected,
since it blocks all implementation on an external, unscheduled dependency with no stated timeline.

---

## §3. Where exclude-terms relevance filtering runs

Spec.md's stage table (§5.2) lists "Filter (relevance)" as a distinct row from "Query
construction," implying exclude-terms filtering is a **post-fetch filter step**, not merely
folded into the X search query string as native `-term` exclusion operators.

**Decision**: A new deterministic relevance-filter step, `src/pipeline/relevance_filter.py`,
runs on fetched posts **after** Query construction/Fetch and **before** signal-strength
computation (this mode's Detect-equivalent) — mirroring Filter-before-Detect ordering
(Constitution II). It does not replace or fold into the bot/noise Filter Tier 1/Tier 2 logic
(`src/pipeline/filter.py`), which stays unchanged and runs first (bot/noise is a different
concern from topical relevance, and keeping them separate keeps each independently testable per
Constitution I/VII).

**Rationale**:
- X's advanced-search `-"term"` operator only excludes an *exact phrase*; it can't express
  case-insensitive substring/keyword exclusion the way a post-fetch check can, and it silently
  narrows what Fetch even sees — useful for cutting request volume, but not sufficient on its own
  when the goal (per spec.md's framing of the problem: "problem phrases are broader and noisier
  than a brand name") is precision-tuning against noise that's only obvious once you can see the
  post text.
- Both are used together for defense in depth: exclude terms *are* still folded into the query
  string where possible (cuts wasted Fetch calls on obviously-irrelevant posts, same spirit as the
  existing cashtag-vs-quoted-phrase logic in `query_builder.py`), and the same exclude-term list is
  re-checked post-fetch as a substring match against normalized post text (reusing the
  `_normalize` pattern already in `src/pipeline/filter.py`) to catch anything the query-level
  exclusion missed (e.g. a term appearing mid-word, or X's search returning a near-match).
- This keeps the design fully deterministic (Constitution I) — no LLM judgment call on
  "relevant or not."

**Acceptance target**: spec.md §6 calls for reusing the Filter-stage eval approach (precision on
relevant vs. irrelevant matches) — a small hand-labeled fixture set of known real complaints vs.
unrelated noise, computed the same way `tests/unit/test_filter_tier1.py`-style tests validate
Filter today (see contracts/pipeline-stages.md § Relevance Filter for the concrete input/output
contract, and tests/eval/test_relevance_filter_precision.py in Project Structure above).

---

## §4. Reshaping Fetch to accept a prebuilt query instead of a `Topic`

`fetch_topic_posts` (`src/pipeline/fetch.py`) currently builds its query internally from
`topic_name`/`x_handles` via `build_search_query`. Idea Validation mode needs the *same*
pagination/retry/rate-limit-pacing mechanics but a *different* query-construction function
(`idea_query_builder.py`'s phrase-list + exclude-terms builder, §3 above).

**Decision**: Extract a `fetch_posts_for_query(query: str, ...) -> FetchResult` primitive that
`fetch_topic_posts` delegates to internally (after building its own query string exactly as
today), and that `idea_validate.py` calls directly with its own prebuilt query string. No public
signature of `fetch_topic_posts` changes — this is an internal refactor, not a breaking change to
any existing caller (`src/pipeline/orchestrator.py`, `tests/contract/test_twitterapi_io.py`, etc.).

**Rationale**: spec.md's stage table doesn't even list "Fetch" as a stage that changes — only
"Query construction" does. That's the signal that the HTTP/pagination/retry mechanics (rate-limit
pacing, cursor handling, per-request error classification) must stay byte-for-byte the same; only
what string goes into the `query` request parameter differs. Extracting the shared primitive is
the smallest change that achieves that without duplicating ~80 lines of pagination/retry logic
into a second module.

**Alternatives considered**: Duplicating a standalone fetch loop inside `idea_validate.py` —
rejected: violates DRY for exactly the logic (rate-limit pacing, retry backoff) that's most
important to keep correct and consistent, and would silently drift from `fetch_topic_posts` over
time as one got bugfixed and the other didn't.

---

## §5. Summarize-prompt reframing

**Decision**: A new function, `summarize_validation_theme`, in a new sibling module
`src/agent/validate_summarize.py`, reusing `summarize.py`'s structured-tool-call pattern
(grammar-constrained Claude tool schema, retry-with-backoff, cost-tracker recording,
leaked-parameter recovery) but with a different tool schema and prompt: "summarize what people
want/are frustrated by" instead of "summarize why this is trending," dropping the
trend-strength-calibrated `confidence_score` (there is no spike_ratio to ground it in — §5.2's
Detect row explicitly removes that signal) in favor of a `recurrence_signal` field grounded in the
deterministic signals this mode *does* have: cluster post count, distinct-author count, and
recency spread (data-model.md § ValidationTheme, contracts/pipeline-stages.md § Validate
Summarize).

**Rationale**: Copy-pasting `summarize.py`'s prompt and just swapping a few sentences risks the
same confidence-score-calibration bugs that module's own docstring documents fighting (leaked
`<parameter>` artifacts, miscalibrated scores) — but grounding the new field in *this mode's own*
deterministic signals (not a nonexistent spike_ratio) is a real, mode-specific change, not a
copy-paste. A separate module — rather than branching `summarize.py` on a mode flag — keeps each
prompt independently readable and testable, matching the existing `pipeline/` vs `agent/` module
boundary's spirit of one clear responsibility per file.

**Alternatives considered**: Adding a `mode` parameter to the existing `summarize_theme` — rejected,
since it would force every future edit to `summarize.py`'s prompt/schema to reason about two
unrelated framings at once, raising the risk of a change meant for brand-mode trending language
accidentally leaking into validation-mode output (or vice versa).

---

## §6. No confidence-gated posting step

**Decision**: `idea_validate.py` never constructs a `DraftPost`, never reads/writes `PostingMode`,
and never calls `src/posting/publish.py`. Confirmed directly by spec.md §5.2's "Confidence gate
(posting): Not applicable — this mode is for internal/client strategy use, not for autonomous
posting."

**Rationale**: Already explicit in the spec; recorded here only to make the Constitution Check's
"N/A — documented" verdict for Principles III/IV traceable to a source line rather than an
assumption.
