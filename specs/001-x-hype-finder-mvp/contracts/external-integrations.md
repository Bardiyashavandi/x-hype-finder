# External Integration Contracts

**Feature**: 001-x-hype-finder-mvp

The shape of data exchanged with each third-party dependency selected in research.md. All
credentials for these integrations are environment-variable only (Constitution V, FR-021).

---

## X Data Read Provider — TwitterAPI.io

- **Auth**: API key via env var (e.g. `TWITTERAPI_IO_KEY`), never committed (FR-021).
- **Request shape**: query by keyword/ticker + optional handles, bounded by a time window.
- **Response shape consumed**: `{x_post_id, author_handle, text, posted_at, author_metadata:
  {account_age, followers_count, following_count, post_frequency}}` — the `author_metadata`
  fields feed Filter Tier 1 rule scoring directly.
- **Failure handling**: non-2xx or timeout → retried with backoff (FR-018); persistent failure →
  per-topic fetch error, does not halt the run for other topics (FR-002).

## X Posting — Official X API v2 (via `tweepy`)

- **Auth**: OAuth 1.0a or 2.0 user-context credentials via env vars, per user (FR-015, FR-021).
- **Used for**: (a) reading the live account bio text to verify the "automated" label
  immediately before an autonomous-mode switch (FR-013); (b) publishing a post, only when
  `mode = autonomous`, confidence clears threshold, kill switch is off, and the rolling 24h cap
  has headroom (FR-022).
- **Failure handling**: a publish call that fails after clearing all gates → `DraftPost.status =
  publish_failed` with `publish_error` populated, surfaced to the user, never silently dropped
  (FR-019).

## LLM — Anthropic Claude API (`claude-sonnet-5` for weeks 1-3, reassessed at the week-3 switch)

- **Auth**: `ANTHROPIC_API_KEY` env var.
- **Used for**: Summarize and Draft Post stages only (research §3). Model is a runtime-configured
  parameter, not hardcoded — `claude-sonnet-5` during the validation period; at the week-3 mode
  switch, kept on Sonnet if cumulative spend against the $5 credit allows, otherwise switched to
  `claude-haiku-4-5-20251001` for the autonomous phase.
- **Request shape**: structured/tool-call request constraining output to the Summarize schema
  (`summary`, `rationale`, `confidence_score`) or a `draft_text` string for Draft Post.
- **Failure handling**: processing errors retry with backoff; if persistent, the affected
  Theme/topic is excluded with a note in the digest rather than failing the whole run (PRD §14
  error-handling table, Constitution Development Workflow section).

## Embeddings — pluggable provider (`src/pipeline/embedding_provider.py`)

Selected via `EMBEDDING_PROVIDER` (default `ollama`); Cluster and Filter Tier 2 both depend only
on the `texts -> vectors` abstraction, never on a specific provider's client directly.

- **`ollama` (default) — local Ollama (`nomic-embed-text`)**
  - **Auth**: none (localhost-only, `http://localhost:11434/api/embed`).
  - **Failure handling**: if the local Ollama server is unreachable, this is a local-environment
    fault, not a per-topic data fault — the run fails fast with a clear local-setup error rather
    than silently degrading clustering/filtering quality.
- **`voyage` — hosted Voyage AI (`voyage-4-lite`)**
  - **Auth**: `VOYAGE_API_KEY` env var, required only when this provider is selected.
  - **Failure handling**: same fail-fast principle as `ollama` — an unreachable API, bad key, or
    malformed response raises immediately rather than degrading clustering/filtering quality.

- **Used for** (both providers): Cluster stage similarity grouping, and Filter Tier 2's
  coordinated-content check (research §4, §5).

## Notifications — Resend

- **Auth**: `RESEND_API_KEY` env var.
- **Used for**: FR-023's digest-completion notification, sent to `User.email` when a Digest's
  `status` transitions to `completed` or `partial`.
- **Request shape**: recipient (`User.email`), subject, a short body linking/pointing to the
  digest (and, during the manual-only period, a reminder that drafts are awaiting manual
  publishing).
- **Failure handling**: a failed send is logged; it MUST NOT block or fail the digest run itself
  — the digest is already persisted regardless of notification delivery.
