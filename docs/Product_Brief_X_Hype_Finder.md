# Product Brief: X Hype Finder

**Document owner:** Bardiya (with Sep, mentor)
**Status:** Draft v5
**Date:** July 10, 2026
**Related document:** PRD — X Hype Finder

---

## 1. Executive Summary

Every day, something worth knowing about starts trending on X — a new AI tool, a crypto ticker, a niche topic about to go big — and almost nobody catches it early enough to matter. Spotting it means constantly watching timelines by hand, which doesn't scale past a topic or two. The tools that already do this well are built for big brands, priced for marketing departments, and only care about mentions of their own company — not about helping a curious person track any topic they care about.

X Hype Finder fixes that. Tell it what to watch — a topic, a ticker, a niche — and it does the timeline-watching for you: spotting real spikes in interest, filtering out bots and fake hype, and sending you a short, ranked summary of what's actually gaining traction and why. It's built to prove itself with two real users first, designed to grow to many more, and affordable in a way the big enterprise tools never were.

## 2. Vision

A hype-detection tool, accessible to any curious individual — not just enterprise marketing teams — that surfaces what's actually gaining real traction on X for any topic worth watching, before it's obvious to everyone else.

## 3. Problem Statement

Catching emerging hype on X today requires constant manual monitoring, which doesn't scale across multiple topics. Real signals are frequently missed entirely, or noticed only once a trend is already mainstream — at which point the early-mover advantage is gone. Bot activity and low-effort engagement farming compound the problem, making it hard to trust what looks like genuine interest. This is a real, persistent, widely-felt problem — it's the entire reason a multi-billion-dollar social listening industry exists — but that industry has largely solved it for brands, not for individuals.

## 4. Market & Competitive Analysis

Social listening and X-monitoring is an established, well-funded category. Vendors like Brandwatch, Sprinklr, Talkwalker, and Sprout Social sell real-time capture, sentiment analysis, and AI-generated trend narratives — the same underlying capabilities this project aims to build. That's a strong signal the core problem is real and valuable to solve.

But the existing market is built for a different buyer. These tools target brand, PR, and growth teams, typically priced in the range of several hundred to several thousand dollars per month, centered on "what are people saying about my brand or my competitors." On the lighter end, tools like Hypefury and Twilert serve individuals, but around growing your own personal account — not discovering hype in topics you're simply curious about.

**The gap:** there is no lightweight, individually-accessible tool for topic-agnostic hype discovery — one that treats any topic as a first-class subject, reasons about it with an LLM rather than a fixed dashboard, and costs a personal-project budget rather than a marketing-department line item.

**Why now:** recent shifts in X's own platform economics — a pay-per-use, credit-based pricing model and a new hosted developer server — lower the cost and integration burden for exactly this kind of small-scale, individually-built tool, turning what would have been a costly build a year ago into something achievable on a modest budget today.

## 5. Opportunity

Build the tool the existing market doesn't serve: personal-scale, topic-agnostic hype discovery, powered by an LLM reasoning over real conversation rather than a fixed metrics dashboard — validated first with two real, engaged users, and designed from day one to extend to more.

## 6. Target Users

**Primary (MVP):** Anyone who wants to stay ahead of what's gaining traction on X — around AI/tech, crypto, or general viral topics — without a brand-monitoring budget or a marketing dashboard. The first version is used directly by its two builders, serving as an early, hands-on test of the concept.

**Future:** The same persona, at scale — independent researchers, content creators, and tech-curious individuals more broadly, once the tool has proven itself with its first users.

## 7. User Persona

**The Independent Trend-Watcher** — someone who's genuinely curious about what's emerging online (in AI/tech, crypto, or wherever their interests lie) and wants to stay ahead of it. They don't have hours to spend scrolling X every day, and they don't need — or want to pay for — an enterprise tool built for big brands. What they want is simple: a quick, trustworthy read on what's actually worth paying attention to right now.

## 8. User Pain Points

| # | Pain Point | Description | Severity | Affected User | Frequency |
|---|---|---|---|---|---|
| 1 | Manual monitoring doesn't scale | Watching X by hand can't keep up with more than a topic or two at once | High | All users | Daily |
| 2 | Bots and fake hype | Coordinated bot activity and low-effort posts make it hard to tell real interest from manufactured noise | High | All users | Frequent |
| 3 | Missed early signals | By the time a trend is obvious through casual observation, the early-mover advantage is already gone | Medium | Trend-watchers, researchers, content creators | Weekly |
| 4 | No affordable option | Existing tools are priced and built for brand teams, not individuals with a personal interest | Medium | Individuals without a marketing budget | Ongoing |

## 9. Value Proposition

X Hype Finder gives you back the time you'd spend scrolling X — without the price tag of an enterprise tool. Tell it what to watch — a topic, a ticker, a niche you're curious about — and it takes over the tedious part: constantly checking in, filtering out the noise, and deciding what's actually worth your attention.

What comes back isn't a wall of raw posts or a dashboard full of numbers to interpret yourself. It's a short, ranked summary: what's trending, why it's trending, and how confident the system is that this is real signal and not manufactured hype. If you want to dig deeper into any item, the original source posts are always one click away — so you're never just trusting a black box.

The table below breaks down exactly how this compares to your two current options: doing it yourself, or paying for a tool built for someone else's problem.

| What matters | Doing it yourself | Enterprise tools | X Hype Finder |
|---|---|---|---|
| **Cost** | Free, but costs your time | Marketing-department budget | Personal-project budget |
| **What you can track** | Anything, if you have the time | Only your own brand/competitors | Any topic, ticker, or niche |
| **Filtering out fakes/bots** | Manual guesswork | Built-in, but for brand mentions | Built-in, for any topic |
| **Effort required** | High — constant attention | Low, but takes training to use | Low — read a digest and go |
| **Why should I trust this result?** | Your own judgment call | A metrics dashboard | A plain-language reason + confidence score |

## 10. Product Goals

1. **Prove it's genuinely useful, fast.** Within the trial period, both real users should find that most digests are worth reading — meaning the tool catches things they'd have otherwise missed, without wasting their time on false alarms.
2. **Prove the idea is worth building further.** Use real usage from the trial to answer one honest question: does this actually save time and surface things a person would miss on their own? If yes, that's the basis for expanding beyond two users later — not a guess, but a tested result.
3. **Build it properly, not just quickly.** Even at this small scale, the system should be built with sound design, a way to check whether it's actually working, and careful handling of credentials and data — the kind of standard expected in a professional engineering setting.

## 11. Success Metrics (KPIs)

| Metric | Definition | Baseline | Target | Data Source | Type |
|---|---|---|---|---|---|
| **Digest Usefulness Rate** | % of digests either user rates "worth reading" | 0% (no digests exist yet) | ≥ 80% over a 3-week trial | User feedback logged after each digest | Primary |
| **Signal Recall** | % of hype events a manual scroll would have caught that the digest also caught | Not yet measured | ≥ 75% across at least 10 spot-comparisons | Manual comparison log (Bardiya + Sep) | Primary |
| **Flagged-Signal Precision** | % of items flagged as genuine signal that hold up as real on manual review | Not yet measured | ≥ 70% against a hand-labeled set of ≥ 50 posts | Manual review against labeled test set | Primary |
| **Time Saved vs. Manual Scrolling** | Estimated minutes/week saved per user, self-reported | 0 (manual baseline) | ≥ 30 min/week per user | Weekly self-report from both users | Supporting |
| **Digest Delivery Reliability** | % of scheduled runs that complete and deliver a digest without failure | Not yet measured | ≥ 95% of scheduled runs | System run logs | Guardrail |
| **Total Spend to Date** | Cumulative actual spend across all components since project start | $0 | Stay within $50 total budget | Provider billing dashboards | Guardrail |

## 12. Core Features (MVP)

| # | Feature | What It Does | Why It Matters | Effort Size |
|---|---|---|---|---|
| 1 | Configurable Topic Tracking | Add or remove any topic, ticker, or niche at any time | Keeps monitoring current with what you actually care about, without needing a rebuild | S |
| 2 | Spike Detection | Recognizes when a topic's activity is genuinely unusual, not just normal day-to-day noise | Separates real emerging hype from ordinary chatter | M |
| 3 | Noise/Bot Filtering | Excludes low-quality and bot-driven content before it reaches the digest | Ensures what you read reflects real interest, not manufactured hype | M |
| 4 | Thematic Clustering | Groups related conversation into coherent themes instead of a flat list of posts | Makes the digest skimmable instead of repetitive | M |
| 5 | Explained, Scored Summaries | Each theme comes with a plain-language summary, a reason it's trending, and a confidence score | Builds trust — you know why something is flagged, not just that it is | S |
| 6 | Ranked Digest Delivery | Delivers a skimmable, evidence-backed digest, on a schedule or on demand | Gets you the highest-signal items first, in whatever format fits your day | S |

*S = a few hours to a day of build effort. M = a day or two, involving real design decisions.*

## 13. Out of Scope (for MVP)

- Web dashboard or graphical UI.
- Public signup or broader external user onboarding.

## 14. Business Risks

1. **API cost/access risk:** X API rate limits or usage costs could constrain monitoring breadth as usage grows.
2. **Filtering reliability risk:** bot/noise filtering may produce false positives or negatives, undermining digest trust.
3. **Detection noise risk:** spike detection may flag normal variance as hype, especially for newly tracked topics.
4. **Market risk:** the opportunity described above is inferred from competitor pricing and positioning; broader demand beyond the initial two users is still unproven.
5. **Platform risk:** autonomous posting carries real reputational and platform-policy exposure. This is managed two ways: first, a 3-week manual-publishing validation period before autonomous posting is ever switched on; second, once switched on, a confidence threshold that only lets high-certainty content post automatically, holding anything less certain for manual review. **The decision to build toward fully autonomous posting at all — even with this staged rollout — is a real scope choice that should be explicitly confirmed with Sep, rather than assumed as a default.**
6. **Cost risk:** the available budget is a one-time **$50 total**, not a recurring monthly allowance. At the estimated $13–16/month baseline, that covers roughly 3 months of runway — actual usage patterns could shrink this further. Early build and testing can run at close to $0 using free trial credits and locally-run models; the $13–16/month estimate applies once those free allowances are used up, and stretching them matters more precisely because the budget doesn't renew. Once the $50 is exhausted, continued operation requires either additional budget or a shift toward cheaper, more local-model-heavy operation.
7. **Automated-account policy risk:** X's platform norms expect automated accounts to be clearly disclosed as such, and a perfectly fixed posting cadence is a known trigger for reduced visibility or account suspension. Both are addressed before autonomous mode is ever switched on: the account bio must carry a visible "automated" label, and posting uses jittered/varied timing rather than a fixed schedule.

## 15. Assumptions

- Sufficient read access to X data is available within budget, using a cost-effective data provider — to be confirmed early in the build.
- The pricing gap identified in the competitive analysis reflects genuine unmet demand, not just an underserved-because-unprofitable niche.
- Shipping toward fully autonomous, confidence-gated posting — with a 3-week manual validation period first — is an acceptable risk tradeoff. **This assumption needs explicit sign-off from Sep before the switch to autonomous mode is made, not just a decision made in this document.**

## 16. Roadmap

| Phase | Scope |
|---|---|
| Phase 1 (Weeks 1–3) | Validate the core hype-detection loop with two real users; every post is published manually by Bardiya while the full autonomous posting logic runs alongside, unused, for comparison. |
| Phase 2 (After Week 3) | Switch on confidence-gated autonomous posting, once the manual trial has confirmed the digests and drafts are trustworthy. |
| Phase 3 | Tune the posting confidence threshold based on real outcomes; extend the architecture to support more users. |
| Phase 4 | Build a lightweight dashboard as an alternative to the current digest format; formalize an evaluation process for detection and filtering accuracy; revisit market demand with users beyond the initial two. |

*(Detailed technical architecture and implementation design are intentionally kept out of this brief — see the companion PRD.)*
