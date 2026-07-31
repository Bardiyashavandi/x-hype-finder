# X Hype Finder

Tell it what to watch — a topic, a ticker, a niche — and it does the timeline-watching for you:
spotting real spikes in interest on X, filtering out bots and manufactured hype, and delivering a
short, ranked, evidence-backed digest of what's actually gaining traction and why.

## Why

Catching emerging hype on X today means constantly watching timelines by hand — which doesn't
scale past a topic or two, and bot/engagement-farming noise makes it hard to trust what looks like
real interest. Enterprise social-listening tools (Brandwatch, Sprinklr, Sprout Social) solve this
well, but only for brand mentions, at a marketing-department price. There's no lightweight,
topic-agnostic version built for a curious individual.

X Hype Finder is that version: any topic as a first-class subject, reasoned about with an LLM
rather than a fixed metrics dashboard, on a personal-project budget. Full pitch, market analysis,
and target users: [`docs/Product_Brief_X_Hype_Finder.md`](docs/Product_Brief_X_Hype_Finder.md).

## Architecture

The system is a strict two-layer split: a **deterministic data pipeline** (rules, statistics, and
embeddings — local via Ollama or hosted via Voyage AI, see Setup — no LLM, fully reproducible and
unit-testable) hands off to a small **AI agent
layer** (Claude) only for the two stages that genuinely require language judgment — writing the
summary and drafting the post. Everything downstream of a draft is gated by an explicit posting
state machine, never a silent auto-publish.

```mermaid
graph TD
    Topics(["Tracked Topics"]) --> Fetch

    subgraph Pipeline["Data Pipeline — deterministic, no AI"]
        direction TB
        Fetch["Fetch<br/>TwitterAPI.io reads"] --> Filter["Filter<br/>Tier 1 rules + Tier 2<br/>embedding coordination check"]
        Filter --> Detect["Detect<br/>baseline vs. spike,<br/>7-day observation gate"]
        Detect --> Cluster["Cluster<br/>embedding-based<br/>near-duplicate grouping"]
    end

    Cluster --> Rank["Rank<br/>descending significance"]

    subgraph AgentLayer["Agent Layer — AI-powered (Claude)"]
        direction TB
        Summarize["Summarize<br/>summary + rationale +<br/>confidence score"]
        DraftPost["Draft Post<br/>candidate post text"]
        Summarize --> DraftPost
    end

    Rank --> Summarize

    DraftPost --> Digest["Digest<br/>ranked, evidence-backed"]
    Digest --> Notify["Notify<br/>Resend email"]

    DraftPost --> Gate{"Posting Mode"}
    Gate -- "Manual (weeks 1-3, always)" --> Manual["Held for manual review<br/>user publishes by hand"]
    Gate -- "Autonomous (gated)" --> Threshold{"confidence ≥ threshold?"}
    Threshold -- "yes" --> AutoPost["Published automatically<br/>jittered timing, 5-post/24h cap,<br/>kill switch"]
    Threshold -- "no" --> Manual

    classDef pipelineNode fill:#dbeafe,stroke:#2563eb,color:#1e3a8a,stroke-width:1px
    classDef agentNode fill:#fce7f3,stroke:#db2777,color:#831843,stroke-width:1px
    classDef gateNode fill:#fef3c7,stroke:#d97706,color:#78350f,stroke-width:1px
    class Fetch,Filter,Detect,Cluster pipelineNode
    class Summarize,DraftPost agentNode
    class Gate,Threshold gateNode

    style Pipeline fill:#eff6ff,stroke:#2563eb,stroke-width:2px
    style AgentLayer fill:#fdf2f8,stroke:#db2777,stroke-width:2px
```

- **Data pipeline** (`src/pipeline/`) — Fetch → Filter → Detect → Cluster. Rule-based scoring,
  statistical baseline/spike comparison, and embeddings (local by default, see Setup) only. No LLM
  at any tier, by design (see Cost Model below and the project constitution) — reproducible and
  independently unit-tested.
- **Agent layer** (`src/agent/`) — Summarize → Draft Post. The only two stages that call an LLM
  (Claude), and only after the pipeline has already decided *what's* significant — the model
  explains and drafts, it never decides what counts as a spike.
- **Posting gate** (`src/posting/`) — every draft is held for manual publishing during a 3-week
  validation period, regardless of confidence. After that, an explicit, reversible toggle enables
  confidence-gated autonomous posting, safeguarded by a live "automated" bio-label check, jittered
  timing, a 5-posts/24h cap, and a kill switch.

## Setup

1. **Python 3.11+** and [`uv`](https://docs.astral.sh/uv/) (or `pip`).
2. Install dependencies:
   ```sh
   uv sync
   ```
3. An embedding provider for Cluster and Filter Tier 2 (`src/pipeline/embedding_provider.py`) —
   pick one, selected via the `EMBEDDING_PROVIDER` env var:
   - **`ollama` (default, free)** — [Ollama](https://ollama.com), running locally, with the
     embedding model pulled:
     ```sh
     ollama pull nomic-embed-text
     ```
   - **`voyage`** — no local install needed; set `EMBEDDING_PROVIDER=voyage` and
     `VOYAGE_API_KEY` in `.env` (get a key at [voyageai.com](https://www.voyageai.com)). Uses
     `voyage-4-lite`.
4. Copy `.env.example` to `.env` and fill in real values — see that file for the exact variables
   needed (`TWITTERAPI_IO_KEY`, `ANTHROPIC_API_KEY`, `RESEND_API_KEY`, the embedding provider vars
   from step 3, and per-user X OAuth credentials namespaced by each user's `x_account_handle`).
   `.env` is gitignored; never commit it.
5. Apply database migrations:
   ```sh
   uv run alembic upgrade head
   ```

This project was built with [GitHub's spec-kit](https://github.com/github/spec-kit) — see
**Spec-Driven Development** below for the toolchain used to go from idea to shipped feature.

## Usage

The CLI is the entire user-facing interface (no web dashboard in MVP scope). Full command
reference: [`docs/cli-usage.md`](docs/cli-usage.md).

```sh
# Track topics
python -m src.cli.topic add "$AAPL" --handles aapl_news
python -m src.cli.topic list
python -m src.cli.topic remove "$AAPL"

# Run and read digests
python -m src.cli.digest run                        # all active topics
python -m src.cli.digest run --topic "$AAPL"         # single topic, on demand
python -m src.cli.digest show <digest-id> --full     # full source evidence, not just examples

# Posting mode
python -m src.cli.posting mode show
python -m src.cli.posting mode set autonomous        # gated: validation period + live bio-label check
python -m src.cli.posting kill-switch on

# Manually-held drafts (the default during the 3-week validation period)
python -m src.cli.drafts list --status held_manual
python -m src.cli.drafts mark-published <draft-id>

# Scheduler (long-lived process — runs scheduled digests + retention sweep for every user)
python -m src.cli.scheduler run
```

### Running the scheduler

`digest run` above is on-demand and one-shot. To get the automatic, scheduled digest
cadence (FR-009) plus the periodic `SourcePost` retention sweep (FR-020) running in the
background, start the scheduler as its own long-lived process:

```sh
python -m src.cli.scheduler run
```

This blocks the process and runs two jobs on independent interval timers (default: every
24h) until you stop it with Ctrl+C, which shuts the scheduler down gracefully:

- **Scheduled digest run** — a `run_type = scheduled` Digest for every user's active
  topics, via the same orchestrator path `digest run` uses.
- **SourcePost retention sweep** — deletes `SourcePost` rows older than the 30-day
  retention window, across all users/topics.

See [`docs/cli-usage.md`](docs/cli-usage.md#scheduler) for cadence flags and more detail.

## Current Status

**Validated MVP — all 5 user stories implemented, 200 passing tests.**

| User Story | Scope | PR |
|---|---|---|
| US1 | End-to-end hype digest pipeline (Fetch→Filter→Detect→Cluster→Summarize→Rank) | [#1](https://github.com/Bardiyashavandi/x-hype-finder/pull/1) |
| US2 + US3 | On-demand triggering, full source drill-down | [#2](https://github.com/Bardiyashavandi/x-hype-finder/pull/2) |
| US4 | Manual-first, then confidence-gated autonomous posting | [#3](https://github.com/Bardiyashavandi/x-hype-finder/pull/3) |
| US5 | Multi-user isolation (data, credentials, process identity) | [#4](https://github.com/Bardiyashavandi/x-hype-finder/pull/4) |
| Polish | CLI docs, retention job, security review, coverage gaps | [#5](https://github.com/Bardiyashavandi/x-hype-finder/pull/5) |

Currently in the manual-only validation period with two pilot users before autonomous posting is
switched on for real.

## Spec-Driven Development

This repo was built with [GitHub's spec-kit](https://github.com/github/spec-kit): a project
**constitution** (non-negotiable engineering principles — e.g. the pipeline/agent determinism
split above) governs a per-feature **spec** (user stories, requirements, acceptance criteria),
which becomes a **plan** (architecture, tech stack, research decisions) and a **tasks** breakdown
(dependency-ordered, testable units of work), which is then implemented task-by-task against that
trail — rather than freeform prompting against a vague idea.

Everything is checked in and readable: [`specs/001-x-hype-finder-mvp/`](specs/001-x-hype-finder-mvp/)
has the full spec, plan, research notes, data model, API/CLI contracts, and the complete task
breakdown (all 72 tasks, done) behind this implementation.

## Cost Model

Budget is a fixed **one-time $50 total** (not a monthly allowance), so the design pushes every
stage that doesn't need language judgment onto free, local infrastructure:

| Component | Approach | Cost |
|---|---|---|
| Embeddings (clustering + Filter Tier 2) | Local Ollama (`nomic-embed-text`, default) or hosted Voyage AI (`voyage-4-lite`, opt-in via `EMBEDDING_PROVIDER=voyage`) | $0 (ollama) / usage-based (voyage) |
| Filter Tier 1, Detect, Cluster, Rank | Deterministic rules/statistics, in-process | $0 |
| X data reads | TwitterAPI.io (~$0.15/1K reads) | ~$4.50/mo at MVP scale |
| Summarize + Draft Post | Claude (`claude-sonnet-5`, reassessed for `claude-haiku-4-5` after the week-3 checkpoint) | ~$2-9/mo, tracked against a $5 credit |
| X posting | Official X API v2, capped at 5 posts/24h | ~$2.25/mo worst case |
| Notifications | Resend free tier | $0 |

A running cost ledger (`src/utils/cost_tracker.py`) tracks cumulative spend against the $50 total,
with an explicit reassess-and-possibly-downgrade checkpoint at the week-3 posting-mode switch
rather than an open-ended commitment to the pricier model. Full reasoning:
[`specs/001-x-hype-finder-mvp/research.md`](specs/001-x-hype-finder-mvp/research.md).
