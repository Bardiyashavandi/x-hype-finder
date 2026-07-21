# Product Requirements Document: X Hype Finder

**Document owner:** Bardiya (with Sep, mentor)
**Status:** Draft v5
**Date:** July 10, 2026
**Related document:** Product Brief — X Hype Finder (problem, market, personas, goals, risks)

---

## 1. Overview

X Hype Finder is an agent that monitors X for configured topics/tickers, detects meaningful activity spikes relative to each topic's own baseline, filters bot and low-quality noise, groups related content into themes, and produces a ranked, evidence-backed digest. It runs on a schedule with an on-demand option. Posting is manual for an initial 3-week validation period, then switches to automatic for high-confidence drafts, with lower-confidence drafts still held for manual review. This document defines what the product must do and why; deeper implementation detail (specific algorithms, libraries, prompts) lives in a companion Technical Approach document.

## 2. Objectives

1. Deliver a working, reliable agent that produces digests its two initial users genuinely find useful.
2. Validate — with real usage — whether the market gap identified in the Product Brief is real and worth building further.
3. Keep the system extensible toward more users and more autonomous operation without requiring a rebuild.

## 3. Stakeholders

| Role | Name | Interest |
|---|---|---|
| Builder / Primary user | Bardiya | Builds and uses the agent; primary decision-maker on scope |
| Mentor / Secondary user | Sep | Internship oversight; second real user of the tool |

## 4. User Stories

- As a user, I want to add or remove tracked topics at any time, so my monitoring stays current with what I care about.
- As a user, I want a scheduled digest of emerging hype on my tracked topics, so I don't have to manually scroll X.
- As a user, I want to trigger a digest on demand, so I can check a topic immediately.
- As a user, I want each digest entry to explain why something is trending and how confident the system is, so I can quickly judge whether it deserves my attention.
- As a user, I want a few representative example posts per theme rather than a full data dump, so the digest stays skimmable while remaining verifiable.
- As a user, I want to drill into full source data for a specific entry, so I can independently verify a signal I'm unsure about.
- As a user, I want to manually publish content during an initial trial period and have the system switch to automatic posting once I've validated it's trustworthy, so I can build confidence in the system before it acts on its own.
- As a secondary user, I want my topic list and credentials kept separate from the primary user's, so we can use the tool independently.

## 5. Architecture Approach

The system is split into two layers, based on which parts genuinely need AI judgment and which don't:

- **Data pipeline (deterministic):** Fetch → Filter → Detect → Cluster. Each stage takes an input and produces one predictable output using rules, statistics, and embeddings — no AI decision-making involved. This keeps the core system fast, cheap, and easy to test.
- **Agent layer (AI-powered):** Summarize and Draft Post. These two stages genuinely require language understanding and judgment — explaining *why* something is trending in plain language, and drafting a post that reads naturally.

Filtering runs **before** spike detection, not after — this matters because a burst of bot activity should never be able to trigger a false "trending" flag before the bots are removed from consideration.

The entire pipeline runs fully autonomously, with no human step, from the moment a topic is tracked through to a drafted post — every stage is built and ready from day one, including the confidence-gated autonomous posting logic. However, posting itself is switched on in two phases:

- **Weeks 1–3 (validation period):** every draft, regardless of confidence score, is held and published manually by Bardiya. This is a deliberate trial window to confirm the digest and drafts are actually trustworthy before anything posts on its own.
- **After week 3, once validated:** the system switches to fully autonomous, confidence-gated posting — drafts at or above the threshold post automatically, and lower-confidence drafts are held for review, exactly as designed from the start.

The switch between these two modes is a single configuration toggle, not a rebuild — the autonomous logic is fully built and tested during the manual phase, just not yet acting on its own.

```
Topics → Fetch → Filter → Detect → Cluster → Summarize → Rank → Digest → Post
         └──────── data pipeline ────────┘   └── agent layer ──┘        │
                                                          Weeks 1–3: always manual publish
                                                          After week 3: auto if ≥ threshold,
                                                                        held for review if not
```

## 6. Features

| # | Feature | Priority | What It Does | Acceptance Criteria |
|---|---|---|---|---|
| 1 | Topic Configuration | P0 | Add, remove, or list tracked topics and optional X handles; persists between runs | A topic added now appears in the very next run, with no code change or redeploy |
| 2 | Data Fetching | P0 | Retrieve recent posts for each tracked topic within a defined time window | Each run returns posts for every tracked topic, or logs a clear fetch error without halting other topics |
| 3 | Bot/Noise Filtering | P0 | Remove low-quality, bot-like, or coordinated content using cheap rule-based checks first, then a deeper LLM check on ambiguous cases; runs before Spike Detection | ≥ 90% of a labeled test set of 50 known bot/spam posts are correctly excluded |
| 4 | Spike Detection | P0 | Compare filtered current activity to a topic's own filtered historical baseline; new topics get a 7-day observation period with no spike flag | A topic with 7+ days of history and activity ≥ 3x its baseline is flagged; a topic in its observation period never triggers a flag |
| 5 | Thematic Clustering | P0 | Group filtered, related posts into themes instead of a flat list | Given 50+ filtered posts on one topic, near-duplicate posts are grouped into the same theme, not shown separately |
| 6 | Explained, Scored Summaries | P0 | Generate a plain-language summary, a rationale, and a confidence score per theme | Every theme in a digest includes all three fields, in a structured format |
| 7 | Ranked Digest Delivery | P0 | Rank themes by strength and deliver a digest with summary, rationale, confidence score, and 3–5 example posts per entry | Digest entries appear in descending order of significance; full source data is available on request, not shown by default |
| 8 | Scheduling & On-Demand Trigger | P0 | Run automatically on a schedule, or immediately on manual request | A scheduled run fires without manual action; a manual trigger completes within minutes |
| 9 | Posting (Manual-First, Autonomous-Ready) | P0 | Build the full confidence-gated auto-posting logic, but gate it behind a mode switch: during weeks 1–3, every draft is held for manual publishing regardless of confidence; after week 3, the system switches to autonomous — posting automatically above the threshold, holding for review below it. Before autonomous posting is ever enabled, the X account's bio must carry a visible "automated" label. Once autonomous, posts go out on a jittered/varied schedule rather than a perfectly fixed cadence, since a robotic fixed cadence is a known suspension trigger | During weeks 1–3, zero posts go out without manual action, even high-confidence ones; after the switch, drafts at or above the threshold post automatically and none are silently discarded either way. Autonomous posting is never enabled while the account bio lacks a visible "automated" label — verified by checking the live bio text before the mode switch is allowed to flip. Post timing under autonomous mode is measurably jittered (varying intervals between posts), never a fixed cadence — verified by inspecting the timestamp gaps across a sample of autonomous posts |
| 10 | Multi-User-Ready Data Model | P0 | Store each user's topics, credentials, and history separately | Two users can each configure and use the tool with zero visibility into each other's data |

## 7. Non-Functional Requirements

| Requirement | Target |
|---|---|
| **Performance** | An on-demand run for a single topic completes in under 5 minutes |
| **Reliability** | A failure on one topic never blocks digest generation for other topics; transient errors retry automatically |
| **Security** | Credentials stored only in environment variables, never in version control; rotated immediately if exposed |
| **Privacy** | X data is used only for the duration of analysis, not stored permanently; no private individual is singled out beyond what's already public in their own posts |

## 8. Cost

Estimated monthly spend across all components, assuming 5 tracked topics, 200 posts/topic/run, daily cadence (30 runs/month):

| Component | Approach | Estimated Cost |
|---|---|---|
| Data reads (fetching posts) | Third-party data provider (not the official X API, which would cost 100x more at this volume) | ~$1–2/month |
| Posting (confidence-gated) | Official X API — required to post under the user's own account | <$1/month |
| LLM (filtering judgment, summarization, rationale) | Current-generation LLM pricing | ~$10–12/month |
| Embeddings (clustering) | Current-generation embedding pricing | <$1/month |
| **Estimated total** | | **~$13–16/month baseline** |

A working budget of **$50 total** — a one-time allowance, not a recurring monthly amount — is set to cover the build-and-validate phase, with some buffer for prompt overhead, retries, and usage growth. At the ~$13–16/month estimated baseline, $50 total covers roughly **3 months of runway**. That's a real constraint worth flagging: once it's exhausted, either more budget needs to be approved or the approach has to shift toward cheaper operation (more local-model usage, less paid LLM/API spend) to keep running.

**Getting started at effectively $0:** the first stretch of development and testing can run at close to zero cost. Most third-party data providers offer one-time free trial credits (roughly 2,000–6,000 reads), enough to cover build-and-test before any real spend is needed. LLM filtering, summarization, and embeddings can run on a local open-source model on Bardiya's own machine at zero marginal cost, at some quality trade-off versus a hosted frontier model. The $13–16/month estimate above applies once free trial credits are exhausted and/or hosted models are used instead of local ones for better output quality. Because the $50 is a fixed total rather than a renewing monthly amount, stretching these free trial credits and local-model usage as long as possible matters even more — every free/local day directly extends the project's runway before additional budget or a cheaper operating mode becomes necessary.

## 9. AI Agent Responsibilities

The agent is responsible for: fetching data per tracked topic; detecting meaningful spikes against topic-specific baselines; filtering bot/low-quality content; clustering related content thematically; generating structured, confidence-scored summaries; ranking and formatting the digest; and generating postable drafts. During the initial 3-week validation period, the agent holds every draft for manual publishing rather than posting on its own. After validation, the agent submits posts automatically when confidence clears the set threshold, and continues holding lower-confidence drafts for manual review. The agent is explicitly **not** responsible, at MVP, for a broader public signup/account system.

## 10. Inputs & Outputs

**Inputs:** tracked topic configuration (keyword + optional X handles, per user); a system-maintained historical activity baseline per topic; X API/data-provider credentials (per user).

**Outputs:** scheduled and on-demand digests (ranked theme entries with summary, rationale, confidence score, example posts); drill-down source data on request; posts submitted automatically for high-confidence drafts, held for manual review otherwise.

## 11. External Integrations

- X (Twitter) — official API for posting; a third-party data provider for reading/monitoring, chosen for cost reasons (see §8).
- An LLM provider — for filtering judgment, summarization, and rationale generation.
- An embedding provider — for semantic clustering.
- A scheduler — for automated runs.

## 12. Digest Format (Illustrative)

```
X HYPE FINDER — Daily Digest — July 10, 2026

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#1  Topic: AI Agents        Confidence: 87%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"Claude Agent SDK" mentions up 6.2x vs. 14-day baseline

Why it's trending: A wave of independent devs are sharing
working demos after a framework update dropped overnight.
High reply/quote ratio from accounts with real posting
history, not bot-pattern amplification.

Example posts (3 of 41 in this cluster):
  → @user1: "just rebuilt my agent in an hour with..."
  → @user2: "ok this changes how I'll ship agents..."
  → @user3: "anyone else seeing 40% fewer tool-call errors..."

[ See all 41 posts + full filtering trail → ]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#2  Topic: $TICKER          Confidence: 54%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Mentions up 1.8x vs. 14-day baseline — a mild, ambiguous rise

Why it's trending: Volume is elevated but not sharply so, and
the increase overlaps with a scheduled earnings call, making it
hard to tell whether this is organic interest or a routine event.

Example posts (3 of 22 in this cluster):
  → @trader1: "earnings call in an hour, watching this one"
  → @trader2: "small volume tick up, nothing unusual yet"
  → @trader3: "anyone else seeing chatter on $TICKER today?"

[ See all 22 posts + full filtering trail → ]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#3  Topic: Robotics         Confidence: —
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
No significant activity detected in this window.
```

## 13. Edge Cases

| Case | Expected Behavior |
|---|---|
| A newly added topic is in its 7-day observation period | Digest shows raw activity, no spike flag |
| A tracked topic returns near-zero posts in a window | Digest states "no significant activity," not an error or silent omission |
| Rate limits are hit mid-run | Partial results are preserved where possible; affected topics marked incomplete |
| All posts for a topic are filtered as noise | Digest states this explicitly, rather than a silently empty entry |
| A user attempts to access another user's data | Blocked by data isolation (Feature 10) |
| A draft post's confidence falls below the posting threshold (post-switch) | Held for manual review; never auto-posted and never silently discarded |
| The system is switched from manual to autonomous mode mid-cycle | The switch takes effect from the next run onward; no retroactive posting of previously held drafts without explicit action |

## 14. Error Handling

| Error Type | Response |
|---|---|
| Fetch errors | Retry with backoff; log; continue with other topics |
| Processing errors (LLM/embedding calls) | Retry with backoff; if persistent, exclude the item with a note in the digest |
| Posting failures | Surface clearly; never silently drop a post that cleared the confidence threshold but failed to publish |
| Scheduled job failures | Visible to the user before the next expected run |

## 15. Acceptance Criteria (MVP, System-Level)

| # | Criterion | How It's Verified |
|---|---|---|
| 1 | A user can add a topic and see it reflected in a digest within one run | Manually add a topic, run the pipeline once, confirm it appears |
| 2 | A genuinely spiking topic's entry includes summary, rationale, confidence score, and 3–5 example posts, with drill-down available | Inspect a real spike event end-to-end |
| 3 | A topic with normal activity doesn't appear as a false-positive spike | Run against 10+ topics with known-normal activity; zero false flags |
| 4 | An on-demand run completes within 5 minutes for a single topic | Timed test run |
| 5 | During weeks 1–3, all drafts are held for manual publishing regardless of confidence; after the switch to autonomous mode, drafts at or above the threshold post automatically and lower-confidence ones are held for review — never silently dropped in either phase | Run test drafts during the manual phase and confirm none auto-post; repeat after switching modes and confirm threshold behavior works as designed |
| 6 | Two distinct users maintain separate topic lists and credentials with zero cross-contamination | Configure two test users, confirm each only sees their own data |

## 16. Success Metrics

See Product Brief §11.

## 17. Risks

See Product Brief §14.

## 18. Dependencies

- Sufficient read access via the chosen data provider, and posting access via the official X API.
- LLM and embedding provider availability within the approved budget.
- Existing secrets-management practice (environment variables, `.gitignore` discipline) carried forward from prior work.

## 19. Open Questions

- Exact spike-detection threshold tuning (deferred to Technical Approach).
- Exact bot-filtering heuristics and LLM filtering prompt design (deferred to Technical Approach).
- Embedding/clustering method and specific provider choice (deferred to Technical Approach).
- Notification mechanism for scheduled job failures.
- Exact confidence threshold for autonomous posting, and how it's calibrated (deferred to Technical Approach).
- Governance rules for autonomous posting — content restrictions, rate limits, and a kill switch in case of repeated bad posts.
- Cadence for building and refreshing the labeled evaluation set used in Feature 3's acceptance criterion.

## 20. Future Enhancements

See Product Brief §16 (Roadmap).
