# Quickstart: Validating Idea Validation Mode

**Feature**: 002-idea-validation-mode

This is a validation guide, not an implementation guide — it proves the feature works end-to-end
against spec.md §7's success criteria. See `data-model.md` for entity detail and `contracts/` for
command/stage shapes.

## Prerequisites

- Same environment as the base project (`TWITTERAPI_IO_KEY` or `TWITTERAPIS_COM_KEY` per
  `FETCH_PROVIDER`, `ANTHROPIC_API_KEY`, an embedding provider — see
  `specs/001-x-hype-finder-mvp/quickstart.md` Prerequisites for the full list). No new
  environment variables are introduced by this feature (research.md §6, plan.md Technical
  Context § Constraints).
- **No DB migration or seeded data required** — `idea-validate run` doesn't touch the database
  (contracts/cli-commands.md).

## Scenario 1 — Synthetic problem-space example (spec.md Rollout step 5)

Uses the spec's own running example (spec.md §2, §5.2): "people struggling to find sublets in a
new city."

1. Run:
   ```
   idea-validate run \
     --phrase "can't find sublet" \
     --phrase "no easy way to sublet" \
     --phrase "sublet is a nightmare" \
     --exclude-term "sublet.com"
   ```
2. **Expect** (spec.md §7, first bullet): a small set of real, relevant posts and 2-4 recurring
   themes is printed — not a wall of noise. Verify by eye that no printed example post is
   obviously off-topic (e.g. unrelated real-estate spam, or a post that only contains the excluded
   term `sublet.com` with no genuine complaint attached).
3. **Expect**: the printed readout includes signal strength (`total_relevant_count`,
   `distinct_author_count`, recency buckets — data-model.md § SignalStrength), not just a raw post
   dump (spec.md §7, second bullet).
4. Re-run with phrases for a genuinely obscure/unused problem statement (e.g. a nonsense phrase no
   one would post) → **expect** the readout states "no meaningful signal found" explicitly
   (contracts/pipeline-stages.md § Validation Readout's zero-signal acceptance rule) rather than
   crashing, hanging, or printing nothing.

## Scenario 2 — Relevance filter precision (spec.md §6)

1. Assemble a small hand-labeled fixture set: known real complaints/requests for a chosen problem
   space, mixed with unrelated noise that happens to match the same phrases in a different sense
   (the labeled-data equivalent of Filter's own bot/spam test set, per
   `specs/001-x-hype-finder-mvp/quickstart.md` Scenario 1 step 7).
2. Run the fixture set through `filter_relevance` (`src/pipeline/relevance_filter.py`) directly
   (unit-level, no network call needed — `tests/eval/test_relevance_filter_precision.py`).
3. **Expect**: precision (relevant posts kept ÷ total posts kept) meets the ≥80% target
   (contracts/pipeline-stages.md § Relevance Filter's acceptance bar). Report the fixture set's
   `n` alongside the result — this is a sanity check before demoing, not a statistically powered
   claim (spec.md §6's own framing: "enough to sanity-check this before demoing").

## Scenario 3 — No brand-mode/scheduled-pipeline side effects (spec.md §3 non-goals)

1. Before running `idea-validate run`, note the current row counts for `digests`, `themes`,
   `source_posts`, and `draft_posts` in the local DB.
2. Run `idea-validate run --phrase "<anything>"` to completion.
3. **Expect**: all four row counts are unchanged (contracts/cli-commands.md's "MUST NOT write to
   any application-owned table"). Confirms this mode is additive-only and never touches the
   brand-tracking/posting pipeline, per the spec's explicit non-goal.

## Scenario 4 — Fetch/Summarize failure isolation

1. Simulate a Fetch rate-limit or generic error (same technique
   `specs/001-x-hype-finder-mvp/quickstart.md`-style contract tests use for `fetch_topic_posts`,
   applied to `fetch_posts_for_query`).
2. **Expect**: the readout states the fetch error explicitly rather than crashing or printing an
   empty result (contracts/cli-commands.md § Errors).
3. Simulate a single Validate Summarize failure for one theme among several clustered candidates.
4. **Expect**: that one theme is omitted from the readout (with a logged note), but every other
   theme still prints — mirroring `orchestrator.py`'s existing per-theme Summarize failure
   handling.
