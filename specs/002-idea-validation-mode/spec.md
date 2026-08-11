# Spec: Idea Validation Mode — Hype Finder

**Status:** Draft
**Author:** Claude (drafted per spec-driven workflow — Specify → Plan → Tasks → Implement)
**Feature owner:** Bardiya
**Target project:** X/Twitter Hype Finder (main capstone project)

---

## 1. Problem

Paradigm Space's actual business is helping startups figure out **what to build** — product strategy, MVP definition, startup consultation. Right now, when a client comes in with an idea, the agency has no easy way to check whether people are actually talking about that problem or asking for that kind of solution — they just take the idea on faith and start building.

Hype Finder already does the hard part of this — filtering noise, detecting real spikes in mentions, clustering into themes — but it's built to watch a topic/ticker *after* it's already a thing. There's no mode for checking "is this problem space real" *before* anything exists to track.

## 2. Goal

Add a mode where, instead of tracking a brand or existing topic, you give Hype Finder a **problem statement or idea** (e.g. "people struggling to find sublets in a new city") and it searches for real complaints, requests, and discussion around that problem — then reports back whether there's genuine signal.

## 3. Non-goals

- Not a market-sizing tool — this reports on discussion volume/sentiment, not TAM or revenue potential
- Not predictive — it reports what's being said now, not a forecast
- No changes to brand-tracking or client-report features — this is a separate mode, run independently

## 4. User story

> As a strategist at Paradigm Space, when a client pitches an idea, I want to check whether people are actually complaining about or asking for that kind of solution on X, so I can give the client an evidence-based read before we commit to building it.

## 5. Design

### 5.1 What's different from existing tracking modes

| Existing mode (topic/ticker/brand) | Idea Validation mode |
|---|---|
| Tracks a *named* thing that already exists | Tracks a *problem description*, no fixed name to search |
| Goal: detect spikes in existing conversation | Goal: detect whether relevant conversation exists at all, and how strong it is |
| Query = the entity itself | Query = a set of phrases describing the problem/pain point |

### 5.2 Pipeline changes, stage by stage

| Stage | Change needed |
|---|---|
| **Query construction** | Instead of one entity string, take a short list of problem-describing phrases (e.g. "can't find sublet," "no easy way to sublet," "sublet is a nightmare") and search for all of them. |
| **Filter (bot/noise)** | No change. |
| **Filter (relevance)** | Reuse the `exclude_terms` idea from brand mode — needed here too, since problem phrases are broader and noisier than a brand name. |
| **Detect (spike)** | Adjusted framing: instead of "is this spiking *now* vs. its own history," report absolute volume and recency, since a new problem space has no history to compare against. |
| **Cluster** | No change — still groups similar complaints/requests into themes. |
| **Summarize** | New prompt framing: "summarize what people want/are frustrated by," not "summarize why this is trending." |
| **Draft / Digest** | Reframed as a **validation readout** rather than a hype digest: how many relevant posts found, what the recurring asks/complaints are, example posts. |
| **Confidence gate (posting)** | Not applicable — this mode is for internal/client strategy use, not for autonomous posting. Output stays a one-off report, no posting step. |

### 5.3 Output

A short readout, not a running digest: signal strength (how much real discussion exists), the 2-4 recurring themes found, and a handful of representative example posts. This is a one-time strategic input, not something scheduled daily.

## 6. Eval / quality check

Reuse the Filter-stage eval approach (precision on relevant vs. irrelevant matches) since filtering noisy problem-phrase matches is the hardest part of this mode — same as it was the hardest part of brand mode. A small set of labeled test cases (known real complaints vs. unrelated noise) is enough to sanity-check this before demoing.

## 7. Success criteria

- Given a plain-language problem description, the tool returns a small set of real, relevant posts and 2-4 recurring themes — not a wall of noise.
- The output reads as a useful strategic input (e.g. "yes, there's real recurring frustration here" or "no meaningful signal found"), not just a raw post dump.

## 8. Open questions

1. Should this reuse the existing scheduled pipeline infrastructure, or is a simpler one-off script sufficient since it's not a recurring job?
2. Is there a real client idea (with consent) Paradigm Space could test this against, or should the first version use a synthetic example?

## 9. Rollout

1. Build query construction from a problem-phrase list instead of a single entity
2. Adapt Filter stage with exclude-terms support (shared groundwork with brand mode, if both get built)
3. Adjust Summarize prompt for "validation" framing
4. Build the one-off validation readout output (not a scheduled digest)
5. Test against a synthetic problem-space example
