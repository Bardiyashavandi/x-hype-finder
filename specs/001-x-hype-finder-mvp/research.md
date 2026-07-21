# Phase 0 Research: X Hype Finder MVP

**Feature**: 001-x-hype-finder-mvp | **Date**: 2026-07-21

This document resolves every open technical question left by the spec, the source PRD/Product
Brief, and the constitution's gates, before Phase 1 design begins.

---

## 1. Language & Runtime

- **Decision**: Python 3.11+.
- **Rationale**: Best-supported ecosystem for every stage of this pipeline in one language —
  local embeddings (`sentence-transformers` / Ollama), local LLM serving (Ollama), numeric
  baseline/spike math (`numpy`), a mature official-API client (`tweepy`), and a mature scheduler
  (`APScheduler`). Confirmed directly with the user over TypeScript/Node.
- **Alternatives considered**: TypeScript/Node — weaker local-model/embedding ecosystem, no
  offsetting benefit since no web dashboard exists in MVP scope (Product Brief §13, out of scope).

## 2. Deployment Target

- **Decision**: A single long-running Python process on the user's own machine, driving both the
  scheduled cadence and on-demand (CLI-triggered) runs against a local SQLite database.
- **Rationale**: Confirmed with the user. Zero hosting cost against the fixed $50 total budget
  (Constitution VI), and it's the only target that makes local Ollama models viable (Ollama isn't
  available on serverless/managed schedulers).
- **Alternatives considered**: Cloud VM (adds hosting cost, more ops surface for a 2-user MVP);
  serverless/managed cron (no server to babysit, but forces a hosted-only LLM/embedding path from
  day one, conflicting with the cost-discipline principle).

## 3. LLM Usage Split (Summarize / Draft Post vs. Filter)

- **Decision**: Anthropic Claude API is used **only** for the Summarize and Draft Post stages —
  the two stages the constitution and PRD agree require genuine language judgment. Everything else
  (Fetch, Filter, Detect, Cluster) remains fully deterministic with **no LLM involved at any
  tier**, including the Filter stage's "deeper judgment check." Model choice is staged:
  - **Weeks 1-3 (manual-posting validation period)**: `claude-sonnet-5`. This is the period the
    core concept itself is being judged — whether digests are genuinely "worth reading" (SC-011)
    and whether drafts read naturally enough to trust — so summary/rationale/draft quality is
    worth spending the better model on, even at higher token cost.
  - **At the week-3 mode switch (reassess, don't auto-continue)**: check actual cumulative spend
    against the $5 Anthropic credit at that point. If the credit is holding up, **keep Sonnet**
    through the autonomous phase too — that phase is higher-stakes (posts go out with no human
    check), so quality still matters as much or more. If budget is tight, **downgrade to
    `claude-haiku-4-5-20251001`** — by that point the underlying pipeline (Fetch/Filter/Detect/
    Cluster, and the confidence-gating logic itself) is already validated against real usage, so a
    model downgrade only affects phrasing quality, not correctness of what gets flagged or posted.
- **Rationale**: Confirmed with the user, who holds a $5 Anthropic credit and wants it spent where
  output quality (trustworthy rationale, calibrated confidence) matters most, and wants that
  spend/quality tradeoff reassessed rather than fixed for the project's duration. Sonnet 5 launch
  pricing is $2/M input, $10/M output tokens (through 2026-08-31; $3/M input, $15/M output
  standard after) — roughly 2-3x Haiku 4.5's $1/M input, $5/M output. At this feature's scale (a
  handful of themes/day across ~5 topics) that lands around $2-9/month in token spend depending on
  which pricing window the 3-week period falls in, which is tighter against the $5 credit than
  Haiku's ~$1-3/month but still workable for a 3-week window — hence the explicit spend check
  before deciding whether to carry Sonnet into the autonomous phase.
- **Constitution conflict resolved**: Principle I bans LLM/agent judgment in Filter/Detect/Cluster.
  The PRD's Feature 3 description ("a deeper LLM check on ambiguous cases") directly conflicted
  with this. Resolved with the user in favor of keeping the constitution as ratified: Filter's
  escalation tier is a **deterministic** second pass (see §5), not an LLM call, local or hosted, or
  any model tier.
- **Alternatives considered**: Haiku 4.5 for the validation period — rejected because this is
  exactly the window the concept is being judged on, and quality differences are most visible
  before the user has learned to trust (or distrust) the system's phrasing; Local Ollama model for
  Summarize/Draft — rejected because the user explicitly wants the $5 credit spent on this exact
  stage for quality reasons; hosted API for everything — rejected, would burn budget on stages
  that don't need language judgment and that the constitution requires stay deterministic; fixing
  one model for the whole project regardless of spend — rejected in favor of an explicit
  reassessment checkpoint, since the budget is a one-time $50 total, not renewing (Constitution
  VI).

## 4. Embeddings (Clustering)

- **Decision**: Local embedding model via Ollama, `nomic-embed-text` (768-dim, ~0.3GB, served at
  `POST /api/embed` on `localhost:11434`, no API key, $0 marginal cost).
- **Rationale**: Confirmed with the user ("everything else... on local Ollama models at $0
  marginal cost"). `nomic-embed-text` benchmarks above `text-embedding-ada-002` / `-3-small` on
  short- and long-context retrieval tasks, comfortably sufficient for near-duplicate/theme
  clustering of short-form posts. Embeddings are explicitly compatible with Principle I
  ("driven only by rules, statistics, and embeddings").
- **Alternatives considered**: `sentence-transformers` (all-MiniLM-L6-v2) run in-process — also
  viable and $0, but standardizing on Ollama for both embeddings and any future local-model need
  keeps one local-serving dependency instead of two.

## 5. Filter Stage: Deterministic "Deeper Judgment Check"

- **Decision**: A two-tier, fully deterministic filter, with no generative model at either tier:
  - **Tier 1 (cheap rule-based)**: fast per-post heuristics — account age, follower/following
    ratio, posting frequency/velocity, verbatim/near-verbatim duplicate-text ratio,
    link-to-text ratio, known spam-pattern matches.
  - **Tier 2 (deeper check, escalated only for posts Tier 1 marks ambiguous)**: embedding-based
    coordinated-content detection — using the same `nomic-embed-text` embeddings already computed
    for clustering, flag near-duplicate content posted by *distinct* accounts in a tight time
    window (a signature of coordinated/bot amplification that a single-post rule check misses),
    combined with a stricter composite threshold over the Tier 1 feature set.
- **Rationale**: Resolves the constitution-vs-PRD conflict (see §3) in favor of the ratified
  constitution: "escalating ambiguous cases to a deeper judgment check" (FR-003) is satisfied by a
  *statistically stricter* deterministic pass, not by handing the decision to an LLM. This also
  avoids needing a labeled training set before MVP can ship — the 50-post labeled set required by
  SC-002 is used to *evaluate* precision/recall of this deterministic pipeline, not to train a
  model.
- **Alternatives considered**: Trained lightweight classifier (logistic regression / gradient
  boosted trees) over the same features — left as a documented future upgrade path (still fully
  deterministic and constitution-compliant) once enough labeled data exists; not required for MVP
  since rule + embedding-coordination checks are sufficient to hit the 90% exclusion target.

## 6. X Data Reading (Fetch)

- **Decision**: TwitterAPI.io as the third-party read provider (~$0.15 per 1,000 tweets, flat,
  no monthly minimum, $1 trial credit on signup).
- **Rationale**: The official X API's pay-per-use reads ($0.005/read, i.e. $5/1,000) are ~30x more
  expensive than this MVP's budget supports at any real cadence — confirms the PRD's own
  reasoning for using a third-party provider. At this feature's scale (≤5 topics × 200 posts ×
  daily cadence ≈ 30,000 reads/month), TwitterAPI.io costs ≈ $4.50/month, which fits comfortably
  alongside the LLM spend inside the $50 one-time total, and its trial credit covers build/test
  before any real spend.
- **Alternatives considered**: GetXAPI (~$0.05/1K, cheapest found, but less established — kept as
  a fallback if TwitterAPI.io access/reliability proves insufficient during Phase 0 spike-testing);
  SocialData (~$0.20/1K, no meaningful advantage over TwitterAPI.io).

## 7. X Posting (Draft publishing / autonomous posting)

- **Decision**: Official X API v2 via `tweepy` (actively maintained, full v2 + OAuth 1.0a/2.0
  support), pay-per-use ($0.015/post created). Manual-phase drafts are **surfaced to the user**
  (in the digest and/or the completion notification) for the user to publish by hand directly on
  X — the system never calls the posting endpoint during the first 3 weeks. The full posting
  client and confidence-gate logic are still built and exercised via contract/integration tests
  during this period (per the Product Brief's "runs alongside, unused" framing), just never
  invoked to actually publish until the autonomous-mode toggle is flipped.
- **Rationale**: Must be the official API for posting under the user's own account — no
  third-party provider offers posting. Cost is negligible: FR-022's 5-posts/24h cap bounds worst
  case to ~150 posts/month × $0.015 ≈ $2.25/month.
- **Alternatives considered**: none viable — posting requires the account owner's own official
  API credentials by platform policy.

## 8. Storage

- **Decision**: SQLite (single file, accessed via `sqlalchemy` for schema/migrations convenience).
- **Rationale**: Zero cost, zero ops, trivially sufficient for 2 users, low write volume (daily
  digest runs), and satisfies FR-020 (no long-term raw-post retention beyond baseline needs) and
  FR-015 (per-user isolation) with simple foreign-key scoping by `user_id`.
- **Alternatives considered**: Postgres — unnecessary operational overhead for this scale.

## 9. Scheduling

- **Decision**: `APScheduler` running inside the same long-lived process, driving the daily (or
  user-configured interval) scheduled run; the same pipeline entry point is invoked directly by a
  CLI command for on-demand runs (FR-009).
- **Rationale**: In-process scheduling avoids a second moving part (no external cron/daemon setup
  needed beyond "keep this process running"), and guarantees scheduled and on-demand runs share
  identical code paths (User Story 2's requirement that manual-trigger quality match scheduled-run
  quality).
- **Alternatives considered**: OS-level cron invoking a one-shot script — viable, but splits
  configuration across the OS and the app; rejected for now as unnecessary complexity at this
  scale.

## 10. Notifications (FR-023)

- **Decision**: Resend (HTTP API), permanent free tier — 3,000 emails/month, 100/day cap, one
  domain.
- **Rationale**: Comfortably covers 2 users × 1 notification/day (≈60/month) with huge headroom
  for on-demand runs and retries, at $0. HTTP-only API is a non-issue since nothing here depends
  on SMTP.
- **Alternatives considered**: Mailgun free tier (100/day, one domain — thinner headroom, no
  material advantage); SendGrid (free tier discontinued for new signups in 2025).

## 11. Testing

- **Decision**: `pytest` for unit, contract, and integration tests.
- **Rationale**: Standard, and pairs directly with Principle I/VII's requirement that each
  deterministic pipeline stage be independently, reproducibly testable.

## 12. Confidence Score Calibration (Summarize stage)

- **Decision**: Confidence score is produced by Claude as a structured field alongside the
  summary/rationale (constrained to a 0-100 numeric output via structured output/tool-call
  schema), seeded by deterministic inputs already computed upstream (spike ratio vs. baseline,
  cluster size, filter-survival rate, account-diversity of the cluster) passed into the prompt as
  context — not invented by the model from raw text alone.
- **Rationale**: Keeps the *judgment* (is this genuinely trending, in plain language) with the
  LLM, per Principle I's intent, while grounding the *score* in the same deterministic signals the
  rest of the pipeline already produces, improving calibration and auditability. Exact threshold
  tuning for autonomous posting (FR-011/FR-012) remains a runtime-configurable parameter, per the
  spec's own Assumptions section — not fixed at design time.
- **Alternatives considered**: Pure LLM-invented confidence with no numeric grounding — rejected as
  harder to calibrate and to justify under Principle VII's measurable-done requirement.

---

All prior `NEEDS CLARIFICATION` markers are resolved above. No open unknowns remain for Phase 1.
