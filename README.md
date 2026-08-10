# X Hype Finder

[![Tests](https://github.com/Bardiyashavandi/x-hype-finder/actions/workflows/tests.yml/badge.svg)](https://github.com/Bardiyashavandi/x-hype-finder/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

Tell it what to watch — a topic, a ticker, a niche — and it does the timeline-watching for you:
spotting real spikes in interest on X, filtering out bots and manufactured hype, and delivering a
short, ranked, evidence-backed digest of what's actually gaining traction and why.

## Table of Contents

- [About The Project](#about-the-project)
- [Architecture](#architecture)
- [Algorithms](#algorithms)
- [Built With](#built-with)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
- [Usage](#usage)
- [Cost Model](#cost-model)
- [Development Process](#development-process)
- [Roadmap](#roadmap)
- [License](#license)

## About The Project

Catching emerging hype on X today means constantly watching timelines by hand — which doesn't
scale past a topic or two, and bot/engagement-farming noise makes it hard to trust what looks like
real interest. Enterprise social-listening tools (Brandwatch, Sprinklr, Sprout Social) already
solve this well — real-time capture, sentiment analysis, AI-generated trend narratives — which is a
strong signal the underlying problem is real. But they're built for a different buyer: brand, PR,
and growth teams, priced in the hundreds-to-thousands-per-month range, centered on "what are people
saying about my brand." There's no lightweight, topic-agnostic version built for a curious
individual who just wants to track a topic, ticker, or niche they care about.

X Hype Finder is that version: any topic as a first-class subject, reasoned about with an LLM
rather than a fixed metrics dashboard, on a personal-project budget (see [Cost
Model](#cost-model)). What comes back isn't a wall of raw posts or a dashboard full of numbers —
it's a short, ranked summary: what's trending, why, and how confident the system is that it's real
signal rather than manufactured hype, with the original source posts always one click away.

Full pitch, market analysis, competitive gap, and target users:
[`docs/Product_Brief_X_Hype_Finder.md`](docs/Product_Brief_X_Hype_Finder.md). Detailed
requirements, architecture, and cost model: [`docs/PRD_X_Hype_Finder.md`](docs/PRD_X_Hype_Finder.md).

## Architecture

The system is a strict two-layer split: a **deterministic data pipeline** (rules, statistics, and
embeddings — local via Ollama or hosted via Voyage AI, see [Getting Started](#getting-started) — no
LLM, fully reproducible and unit-testable) hands off to a small **AI agent layer** (Claude) only for
the two stages that genuinely require language judgment — writing the summary and drafting the
post. Everything downstream of a draft is gated by an explicit posting state machine, never a
silent auto-publish.

```mermaid
graph TD
    Topics(["Tracked Topics"]) --> Fetch

    subgraph Pipeline["Data Pipeline — deterministic, no AI"]
        direction TB
        Fetch["Fetch<br/>TwitterAPIs.com reads"] --> Filter["Filter<br/>Tier 1 rules + Tier 2<br/>embedding coordination check"]
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

Stage by stage:

- **Fetch** (`src/pipeline/fetch*.py`) — pulls raw posts for each tracked topic from a pluggable
  third-party X data provider (see [Built With](#built-with)), never the official X read API (100x
  the cost at this volume). Provider-agnostic: every backend returns the same `RawPost`/author-metadata
  shape, selected via `FETCH_PROVIDER` (`src/pipeline/fetch_provider.py`) — same pattern as the
  embedding provider below.
- **Filter** (`src/pipeline/filter.py`) — two tiers, both rule-based. Tier 1 scores each post's
  author metadata (account age, follower/following ratio, posting frequency) against fixed
  thresholds; Tier 2 embeds post text to catch coordinated/duplicate-content bot campaigns a single
  post's metadata wouldn't reveal. No LLM judgment calls what counts as spam.
- **Detect** (`src/pipeline/detect.py`) — compares a topic's current filtered post volume against
  its *own* trailing baseline, never another topic's. Rather than flagging a spike at a fixed
  multiple of the baseline mean (e.g. "3x everything"), which is miscalibrated across volume
  regimes — count data's variance scales with its mean, so a flat ratio is too loose for a
  low-volume topic (ordinary noise clears it trivially) and too tight for a high-volume one (a real
  trend may never reach it) — a spike is current activity clearing the baseline mean by **`K_SIGMA`
  (2.5) effective standard deviations**, a threshold that adapts to each topic's own volume and
  variance instead of one fixed ratio for every topic. Every newly tracked topic also serves a
  **7-day observation period** during which `is_spike` is unconditionally `False`, regardless of
  activity — there's no baseline yet to compare against honestly.
- **Cluster** (`src/pipeline/cluster.py`) — groups filtered posts into themes by embedding
  near-duplicate/related content together, so the digest reads as a handful of coherent stories
  instead of a flat list of individual posts.
- **Rank** (`src/pipeline/rank.py`) — orders every theme across every topic in the run by
  significance, descending, so the digest surfaces the highest-signal items first.
- **Summarize / Draft Post** (`src/agent/`) — the only two stages that call an LLM (Claude), and
  only *after* the deterministic pipeline has already decided what's significant: the model
  explains and drafts, it never decides what counts as a spike or filters noise itself.
- **Posting gate** (`src/posting/`) — every draft is held for manual publishing during a 3-week
  validation period, regardless of confidence. After that, an explicit, reversible toggle enables
  confidence-gated autonomous posting, safeguarded by a live "automated" bio-label check, jittered
  timing, a 5-posts/24h cap, and a kill switch.

## Algorithms

The three stages that actually decide what's noise, what's a spike, and what's one story rather
than ten are all deterministic — no LLM judgment anywhere in this section (Constitution Principle
I). This is the logic behind them, not just the boxes in the diagram above.

### Filter — Bot/Noise Detection (`src/pipeline/filter.py`)

**Problem:** a raw fetch for any active topic includes bot amplification, engagement farming, and
spam alongside genuine posts. Deciding "bot or not" per post needs to be cheap (it runs on every
fetched post, every run) but still catch coordinated behavior a single post's metadata can't reveal
on its own — so it's split into two tiers, with the expensive tier gated behind the cheap one.

**Tier 1 — rule-based composite score, 0-100** (`score_tier1`). Each post starts at 0 and accumulates
points from independent, additive signals:

| Signal | Condition | Points |
|---|---|---|
| New account | `account_age_days < 30` | +20 |
| Suspicious follow ratio | `followers < 50` **and** `following > max(followers, 1) × 10` | +20 |
| High posting velocity | `post_frequency > 50`/day | +20 |
| Duplicate text | ≥50% of other posts in the same batch are ≥0.9 similar (`SequenceMatcher` ratio, link-stripped/lowercased) | +25 |
| Link-heavy | URL characters ≥50% of post length | +10 |
| Spam pattern | regex match on `dm me`, `guaranteed profit(s)`, `\d{2,}x gains?`, `free airdrop`, follow-back bait, wallet-solicitation/giveaway-bait (wallet + drop/comment/send + airdrop/giveaway/winner), or a bare/labeled contract address (`0x` hex, `solana:` URI, `CA:` label, or the phrase "contract address") | +25 |
| Cashtag stuffing | ≥6 distinct `$TICKER` cashtags in one post | +20 |

The composite score is capped at 100 and bucketed:

```
score >= 70   → clear_exclude
score <= 20   → clear_keep
otherwise     → ambiguous          (escalated to Tier 2)
```

**Tier 2 — embedding-based coordinated-content check** (`apply_tier2`), run *only* over Tier 1's
`ambiguous` posts — clear-keep and clear-exclude posts never pay for an embedding call at all. This
catches what Tier 1's per-post metadata structurally can't: near-duplicate content posted by
*distinct* accounts in a tight time window, a signature of coordinated amplification a single
post's own metadata looks perfectly clean under. Concretely: for each ambiguous post, embed it and
every other post in the batch, and flag it `excluded_deeper_check` if ≥2 *distinct* authors posted
content ≥0.92 cosine-similar within a 2-hour window. If no coordination signature is found, it falls
back to a stricter composite threshold (≥50, versus Tier 1's own 70) rather than defaulting to keep —
an ambiguous post that fails both checks is still excluded, not given the benefit of the doubt.

No post is ever silently dropped — every post gets a `filter_outcome` (`kept` /
`excluded_rule` / `excluded_deeper_check`) persisted on `SourcePost`, so a filtered-out post is
still auditable via `digest show --full`, not erased from the record. The author metadata Tier 1
scored it against (`followers_count`, `following_count`, `account_age_days`, `post_frequency`) is
persisted on the same row alongside the outcome, for both kept and excluded posts — nullable, since
rows written before these columns existed have nothing to backfill. Post-level engagement counts
(`like_count`, `retweet_count`, `reply_count`, `quote_count`, `view_count`) are persisted the same
way when the active Fetch provider exposes them — currently only `fetch_twitterapis_com.py`; the
original `fetch.py` (TwitterAPI.io) client's response doesn't expose engagement counts, so those
columns stay `null` for posts fetched through it.

**Why two tiers instead of one ML classifier or a single embedding pass over everything:** a
trained classifier needs labeled bot/not-bot data this project doesn't have and can't audit as
easily as an explicit rule list; running embeddings over *every* post regardless of how obviously
clean or spammy it is would multiply embedding-provider cost and latency for zero marginal signal
on the cases Tier 1 already resolves confidently. Gating Tier 2 behind Tier 1's `ambiguous` bucket
means the expensive check only runs where a cheap rule genuinely can't decide.

### Detect — Spike Detection (`src/pipeline/detect.py`)

**Problem:** decide whether a topic's current filtered post volume is a genuine spike in interest —
compared strictly to *that topic's own* trailing baseline, never another topic's — without either
drowning in false positives on quiet topics or missing real trends on already-busy ones.

The naive approach — flag a spike at a fixed multiple of the baseline mean (e.g. "current ≥ 3×
baseline") — is miscalibrated across volume regimes, because count data's variance scales with its
mean (a Poisson-like property): a flat ratio is far too loose for a low-volume topic, where ordinary
day-to-day noise clears it trivially, and far too tight for a high-volume topic, where a real
emerging trend may never reach it. This is the same reasoning behind established
seasonal/statistical anomaly-detection approaches (e.g. Twitter's own Seasonal-Hybrid ESD work),
which likewise reject a fixed threshold in favor of bounds that adapt to a series' own variance
rather than one constant applied uniformly.

`detect_spike` instead flags a spike when current activity clears the baseline mean by
**`K_SIGMA` (2.5) effective standard deviations**:

```
is_spike = current_count >= baseline_mean + K_SIGMA * sigma_eff

sigma_eff = max(
    baseline_stdev,          # the trailing window's own population stdev
    sqrt(baseline_mean),     # Poisson noise floor — variance scales with the mean
    MIN_SIGMA_FLOOR,         # 1.0 — guards near-zero-variance baselines (e.g. flat at 0-1/day)
)
```

`baseline_mean`/`baseline_stdev` are computed over a trailing 7-day window of `TopicBaselineSnapshot`
rows, excluding the current day itself. Every newly tracked topic also serves a **7-day observation
period** (`Topic.observation_period_active`) during which `is_spike` is unconditionally `False`
regardless of activity — there's no honest baseline yet to compare against. `spike_ratio`
(`current ÷ baseline_mean`) is still computed and reported downstream as a magnitude signal even
when it isn't what decides `is_spike`.

**Worked example** (both cases from `tests/unit/test_detect.py`, same `K_SIGMA=2.5`):

- **Low-volume topic**, baseline mean = 1 post/day, current = 3 (a flat 3× move). Under a fixed
  3× rule this registers as a spike (3 ÷ 1 = 3.0 ≥ 3.0) — but at this volume, 3 posts in a day is
  unremarkable noise. `sigma_eff = max(0, √1, 1.0) = 1.0`, so the threshold is `1 + 2.5×1 = 3.5`;
  current = 3 falls short → **not a spike**.
- **High-volume topic**, baseline mean = 1000 posts/day, current = 1100 (a modest 1.1× move). Under
  the same fixed 3× rule this would need 3000 posts to register at all — but a sustained 10% lift on
  1000/day is a real signal. `sigma_eff = max(0, √1000, 1.0) ≈ 31.6`, so the threshold is
  `1000 + 2.5×31.6 ≈ 1079`; current = 1100 clears it → **is a spike**.

Same `K_SIGMA`, same formula, correct call in both directions — because the bound itself scales
with the topic's own baseline variance instead of being fixed.

### Cluster — Thematic Grouping (`src/pipeline/cluster.py`)

**Problem:** turn a flat list of Filter-kept posts into a handful of coherent stories — a digest
of 40 individual posts is unreadable, but a digest of 3-5 *themes* isn't, provided the grouping
itself is honest about what's actually related.

`cluster_posts` embeds every kept post's text and runs scikit-learn's `AgglomerativeClustering`
over the embeddings with **cosine distance** and **average linkage**, using a **distance threshold**
rather than a fixed cluster count:

```
distance_threshold = 1.0 - CLUSTER_SIMILARITY_THRESHOLD   # 1.0 - 0.75 = 0.25
AgglomerativeClustering(n_clusters=None, distance_threshold=0.25, metric="cosine", linkage="average")
```

Posts land in the same cluster only once their pairwise cosine similarity clears **0.75**; nothing
else determines how many clusters come out — `n_clusters=None` explicitly lets the data decide,
rather than forcing a pre-chosen number of themes (as k-means would require) onto whatever content
actually showed up. A post with no sufficiently similar peers becomes a **singleton cluster of
one** rather than being dropped or force-merged into an unrelated group — Cluster never excludes a
post, only Filter does.

**Real example:** a live run against the broad, handle-less topic "AI agents" (`docs/PRD_X_Hype_Finder.md`,
2026-07-31) fetched 40 posts and produced **37 themes** — almost entirely singletons. That's the
correct outcome, not a clustering failure: a keyword that broad pulls in posts that mention "AI
agents" while discussing genuinely unrelated specifics, so they simply aren't 0.75-similar to each
other, and the threshold correctly declines to force them into shared stories they don't belong to.
A narrower, handle-anchored topic sees proportionally larger clusters, since its posts are more
likely to actually be repeating or reacting to the same specific thing.

## Built With

- **[Python](https://www.python.org/) 3.11+** — the entire application, CLI included (no web/GUI
  dashboard in this MVP).
- **[Claude](https://www.anthropic.com/claude) (`claude-sonnet-5`)** — Summarize and Draft Post,
  the two stages that need language judgment.
- **[Ollama](https://ollama.com) (`nomic-embed-text`, default) / [Voyage AI](https://www.voyageai.com)
  (`voyage-4-lite`, opt-in)** — embeddings for Filter Tier 2's coordinated-content check and
  Cluster, pluggable via `EMBEDDING_PROVIDER`.
- **[TwitterAPIs.com](https://www.twitterapis.com) (default) / [TwitterAPI.io](https://twitterapi.io)
  (alternative)** — third-party X data read providers, pluggable via `FETCH_PROVIDER`; both far
  cheaper at this read volume than the official X read API.
- **[tweepy](https://www.tweepy.org/)** — the official X API v2, used only for posting (each user's
  own account) and the live "automated" bio-label check.
- **[SQLAlchemy](https://www.sqlalchemy.org/) + [Alembic](https://alembic.sqlalchemy.org/)** — ORM
  and schema migrations, SQLite by default.
- **[APScheduler](https://apscheduler.readthedocs.io/)** — the long-lived scheduler process
  (scheduled digest runs, `SourcePost` retention sweep).
- **[Resend](https://resend.com/)** — digest-completion email notifications.
- **[uv](https://docs.astral.sh/uv/)** — dependency management and the dev/CI toolchain.
- **[pytest](https://docs.pytest.org/) / [ruff](https://docs.astral.sh/ruff/) /
  [black](https://black.readthedocs.io/)** — tests, linting, formatting; enforced on every push and
  PR via [GitHub Actions](.github/workflows/tests.yml).

## Getting Started

### Prerequisites

- **Python 3.11+** and [`uv`](https://docs.astral.sh/uv/) (or `pip`).
- An embedding provider (see [Built With](#built-with)) — pick one:
  - **Ollama (default, free)** — install [Ollama](https://ollama.com), running locally, with the
    embedding model pulled:
    ```sh
    ollama pull nomic-embed-text
    ```
  - **Voyage AI** — no local install; just a `VOYAGE_API_KEY` (see Installation below).
- API keys/credentials for whichever Fetch provider, the Claude API, Resend, and each user's own X
  OAuth app — all set via `.env` (next section).

### Installation

1. Install dependencies:
   ```sh
   uv sync
   ```
2. Copy `.env.example` to `.env` and fill in real values — **every** variable it lists is
   documented inline there (what it's for, which are required vs. provider-conditional). At a
   glance:

   | Variable(s) | Purpose |
   |---|---|
   | `FETCH_PROVIDER`, `TWITTERAPIS_COM_KEY` / `TWITTERAPI_IO_KEY` | X data reads (default: TwitterAPIs.com) |
   | `EMBEDDING_PROVIDER`, `VOYAGE_API_KEY` | Embeddings (default: local Ollama, no key needed) |
   | `ANTHROPIC_API_KEY` | Summarize / Draft Post (Claude) |
   | `RESEND_API_KEY`, `RESEND_FROM_EMAIL` | Digest-completion email notifications |
   | `X_API_KEY__<HANDLE>` etc. (per user) | Each user's own X OAuth posting credentials, namespaced by their `x_account_handle` |

   `.env` is gitignored — never commit real credentials (Constitution V, FR-021).
3. Apply database migrations:
   ```sh
   uv run alembic upgrade head
   ```

This project was built with [GitHub's spec-kit](https://github.com/github/spec-kit) — see
[Development Process](#development-process) below for the toolchain used to go from idea to shipped
feature.

## Usage

The CLI is the entire user-facing interface (no web dashboard in MVP scope). Full command
reference, every flag, and every error case: [`docs/cli-usage.md`](docs/cli-usage.md).

```sh
# Track topics
python -m src.cli.topic add "$AAPL" --handles aapl_news
python -m src.cli.topic list
python -m src.cli.topic remove "$AAPL"

# Run and read digests
python -m src.cli.digest run                        # all active topics
python -m src.cli.digest run --topic "$AAPL"         # single topic, on demand
python -m src.cli.digest show <digest-id> --full     # low-confidence themes + full source evidence, not just examples

# Posting mode
python -m src.cli.posting mode show
python -m src.cli.posting mode set autonomous        # gated: validation period + live bio-label check
python -m src.cli.posting kill-switch on

# Manually-held drafts (the default during the 3-week validation period)
python -m src.cli.drafts list --status held_manual
python -m src.cli.drafts mark-published <draft-id>

# Human-in-the-loop evaluation (Filter/Detect/Cluster/Summarize/Draft Post/Digest)
python -m src.cli.eval label digest --count 10
python -m src.cli.eval report --stage digest         # SC-011 KPI

# Scheduler (long-lived process — runs scheduled digests + retention sweep for every user)
python -m src.cli.scheduler run
```

`digest run` above is on-demand and one-shot. To get the automatic, scheduled digest cadence plus
the periodic retention sweep running in the background, start the scheduler as its own long-lived
process — see [`docs/cli-usage.md#scheduler`](docs/cli-usage.md#scheduler) for cadence flags.

By default, `digest show` hides any Theme scoring below `confidence_score` 20 as noise below the
Summarize prompt's calibrated signal floor; `--full` un-hides those low-confidence themes in
addition to showing every filtered-out `SourcePost`, not just Filter-kept ones — see
[`docs/cli-usage.md`](docs/cli-usage.md#digest) for the exact threshold and rationale.

Example output — `topic list`:

```
AI agents	first_tracked_at=2026-07-22T10:25:02.671979	in_observation_period=no
SOL	first_tracked_at=2026-07-31T09:43:48.673752	in_observation_period=yes
```

Example output — `posting mode show`:

```
mode:                      manual
confidence_threshold:      70
validation_period_ends_at: 2026-08-16T12:57:44.219157
kill_switch_engaged:       False
last_post_published_at:    -
```

## Cost Model

Budget is a fixed **one-time $50 total** (not a monthly allowance), so the design pushes every
stage that doesn't need language judgment onto free, local infrastructure:

| Component | Approach | Cost |
|---|---|---|
| Embeddings (clustering + Filter Tier 2) | Local Ollama (`nomic-embed-text`, default) or hosted Voyage AI (`voyage-4-lite`, opt-in via `EMBEDDING_PROVIDER=voyage`) | $0 (ollama) / usage-based (voyage) |
| Filter Tier 1, Detect, Cluster, Rank | Deterministic rules/statistics, in-process | $0 |
| X data reads | TwitterAPIs.com (default, ~$0.04/1K reads) or TwitterAPI.io (~$0.15/1K reads), pluggable via `FETCH_PROVIDER` | ~$1-4.50/mo at MVP scale |
| Summarize + Draft Post | Claude (`claude-sonnet-5`, reassessed for `claude-haiku-4-5` after the week-3 checkpoint) | ~$2-9/mo, tracked against a $5 credit |
| X posting | Official X API v2, capped at 5 posts/24h | ~$2.25/mo worst case |
| Notifications | Resend free tier | $0 |

**Observed from live runs (2026-07-31):** the table above is the planning estimate. Two real
end-to-end `digest run`s against live services give two real data points so far:

| Run | Topics | Posts fetched | Themes produced | Cost |
|---|---|---|---|---|
| Single-topic | 1 ("AI agents") | 40 | 37 | ~$0.41 |
| Multi-topic | 2 ("AI agents" + "SOL") | 80 | 63 | ~$0.65 |

Cost tracks with topic count and theme volume, not a fixed per-run number — almost all of it is
Claude Summarize/Draft Post calls (one pair of calls per theme, occasionally more on a
length-correction retry), with Fetch itself contributing a few tenths of a cent. Real spend, not a
projection, but not yet enough samples to replace the per-component estimate above — kept here as
data points to weigh it against.

A running cost ledger (`src/utils/cost_tracker.py`) tracks cumulative spend against the $50 total,
with an explicit reassess-and-possibly-downgrade checkpoint at the week-3 posting-mode switch
rather than an open-ended commitment to the pricier model. Full reasoning:
[`specs/001-x-hype-finder-mvp/research.md`](specs/001-x-hype-finder-mvp/research.md).

## Development Process

This repo was built with [GitHub's spec-kit](https://github.com/github/spec-kit): a project
**constitution** (non-negotiable engineering principles — e.g. the pipeline/agent determinism split
in [Architecture](#architecture)) governs a per-feature **spec** (user stories, requirements,
acceptance criteria), which becomes a **plan** (architecture, tech stack, research decisions) and a
**tasks** breakdown (dependency-ordered, testable units of work) — implemented task-by-task against
that trail, rather than freeform prompting against a vague idea.

Everything is checked in and readable:
[`specs/001-x-hype-finder-mvp/`](specs/001-x-hype-finder-mvp/) has the full spec, plan, research
notes, data model, API/CLI contracts, and the complete task breakdown (all 72 tasks, done) behind
this implementation. Every push and pull request also runs the full test suite plus lint/format
checks automatically — [`.github/workflows/tests.yml`](.github/workflows/tests.yml).

## Roadmap

**Built — validated MVP, all 5 user stories implemented, 294 passing tests:**

| User Story | Scope | PR |
|---|---|---|
| US1 | End-to-end hype digest pipeline (Fetch→Filter→Detect→Cluster→Summarize→Rank) | [#1](https://github.com/Bardiyashavandi/x-hype-finder/pull/1) |
| US2 + US3 | On-demand triggering, full source drill-down | [#2](https://github.com/Bardiyashavandi/x-hype-finder/pull/2) |
| US4 | Manual-first, then confidence-gated autonomous posting | [#3](https://github.com/Bardiyashavandi/x-hype-finder/pull/3) |
| US5 | Multi-user isolation (data, credentials, process identity) | [#4](https://github.com/Bardiyashavandi/x-hype-finder/pull/4) |
| Polish | CLI docs, retention job, security review, coverage gaps | [#5](https://github.com/Bardiyashavandi/x-hype-finder/pull/5) |
| — | Pluggable embedding providers (Ollama default, Voyage AI alternative) | [#9](https://github.com/Bardiyashavandi/x-hype-finder/pull/9) |
| — | Pluggable Fetch providers (TwitterAPIs.com default, TwitterAPI.io alternative) | [#11](https://github.com/Bardiyashavandi/x-hype-finder/pull/11) |
| — | CI (GitHub Actions), real cost-model validation data | [#12](https://github.com/Bardiyashavandi/x-hype-finder/pull/12) |

**Open:**

- **Real second-user validation.** Currently one pilot user in the 3-week manual-only validation
  period (through 2026-08-16); the Product Brief's target of two real, engaged users hasn't
  happened yet.
- **Formal bot-filtering / detection accuracy measurement.** Signal Recall (≥75% target) and
  Flagged-Signal Precision (≥70% target against a ≥50-post hand-labeled set) are both defined as
  success metrics but not yet measured against real, labeled data — currently validated only via
  unit/contract tests against synthetic fixtures.
- **Filter Tier 1 threshold tuning (deferred from PR [#21](https://github.com/Bardiyashavandi/x-hype-finder/pull/21)).**
  That PR added the contract-address, cashtag-stuffing, and click-link-regex detectors above but
  deliberately left `CLEAR_KEEP_SCORE`, `CLEAR_EXCLUDE_SCORE`, `TIER2_COMPOSITE_SCORE`, and
  `LINK_RATIO_THRESHOLD` untouched: a lone, non-coordinated spam-pattern hit scores 25, lands in
  `ambiguous`, and only actually gets excluded via Tier 2 if it's part of a coordinated swarm or
  the composite reaches 50 — so a solo spam post can still fall through as kept. Tuning those
  thresholds needs a larger labeled sample than the FILTER-stage eval set currently has (n=10,
  target ≥50 per SC-002) to validate against before it ships.
- **Autonomous posting switch-on**, once the manual validation period actually confirms digests and
  drafts are trustworthy in practice — currently every draft is `held_manual` regardless of
  confidence.
- **Phase 4 (Product Brief §16):** a lightweight dashboard as an alternative to the digest format,
  and revisiting market demand with users beyond the initial pilot.

## License

Distributed under the MIT License. See [`LICENSE`](LICENSE) for the full text.
