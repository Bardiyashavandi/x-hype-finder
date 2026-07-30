# Feature Specification: X Hype Finder MVP

**Feature Branch**: `001-x-hype-finder-mvp`

**Created**: 2026-07-20

**Status**: Draft

**Input**: User description: "Build X Hype Finder based on docs/PRD_X_Hype_Finder_.md and docs/Product_Brief_X_Hype_Finder.md — read both files fully and use them as the source of truth for the specification. This is an agent that monitors X for configured topics, detects genuine activity spikes against each topic's own baseline, filters bot/noise content before spike detection runs, clusters related content into themes, generates confidence-scored summaries, and delivers a ranked digest — with posting handled manually for the first 3 weeks before switching to confidence-gated autonomous posting."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Get a Ranked, Evidence-Backed Hype Digest (Priority: P1)

As a tracked-topic owner, I want the system to automatically fetch, filter, detect spikes,
cluster, summarize, and rank activity for each of my tracked topics into a single digest, so
I can see what's genuinely gaining traction on X without manually scrolling timelines.

**Why this priority**: This is the entire reason the product exists — every other capability
exists to support, verify, or extend this core loop.

**Independent Test**: Configure at least one tracked topic with a known historical baseline
and inject a known activity spike alongside a non-spiking control topic; run the pipeline
once; confirm the digest surfaces the spiking topic — ranked, with summary, rationale,
confidence score, and example posts — while the control topic does not falsely appear.

**Acceptance Scenarios**:

1. **Given** a topic with 7+ days of baseline history and current filtered activity at or
   above its own `baseline mean + k * effective standard deviation` threshold (FR-004),
   **When** a digest run executes, **Then** that topic appears in the digest with a
   plain-language summary, a rationale, a confidence score, and 3–5 example posts.
2. **Given** a topic with normal, non-spiking activity, **When** a digest run executes,
   **Then** that topic does not appear as a false-positive spike.
3. **Given** a topic within its first 7 days of being tracked, **When** a digest run
   executes, **Then** that topic shows raw activity with no spike flag.
4. **Given** 50+ filtered posts on one topic containing near-duplicate content, **When**
   clustering runs, **Then** near-duplicate posts are grouped into a single theme rather than
   shown as separate entries.
5. **Given** a mix of known bot/spam posts and genuine posts for a topic, **When** filtering
   runs, **Then** at least 90% of the known bot/spam posts are excluded before spike
   detection evaluates that topic's activity.

---

### User Story 2 - Trigger a Digest On Demand (Priority: P2)

As a user, I want to trigger a digest run immediately for my tracked topics, so I can check
on something right now instead of waiting for the next scheduled run.

**Why this priority**: Extends the core value with immediacy, but the scheduled digest
already delivers the primary value on its own.

**Independent Test**: With topics already configured, manually trigger a run and confirm
results return within the defined time budget and match scheduled-run quality.

**Acceptance Scenarios**:

1. **Given** a configured topic, **When** the user manually triggers a run, **Then** the
   digest for that topic completes in under 5 minutes.
2. **Given** a manual run has completed, **When** the user reviews the result, **Then** it
   follows the same format and quality bar as a scheduled run.

---

### User Story 3 - Drill Into Source Evidence (Priority: P2)

As a user, I want to view the full source data behind any digest entry, so I can
independently verify a signal I'm unsure about rather than just trusting the summary.

**Why this priority**: Builds the verifiability a user needs to trust the system before it's
ever allowed to act autonomously — a prerequisite for User Story 4.

**Independent Test**: From a delivered digest entry, request full source data and confirm
every underlying filtered/clustered post is available, not just the shown examples.

**Acceptance Scenarios**:

1. **Given** a digest entry showing 3 of 41 example posts, **When** the user requests full
   detail, **Then** all 41 underlying posts and the filtering trail are available.
2. **Given** a topic where every post was filtered out as noise, **When** the user views
   that topic's entry, **Then** the digest states this explicitly rather than showing an
   empty or missing entry.

---

### User Story 4 - Manual-First, Then Confidence-Gated Autonomous Posting (Priority: P3)

As a user, I want every drafted post published manually during an initial validation period,
and then — only once I've explicitly validated the system and satisfied platform-safety
requirements — switch to autonomous posting for high-confidence drafts, so I can build real
trust in the system before it acts on its own on a live account.

**Why this priority**: This is the highest-risk capability, since it acts on a live, publicly
visible account. It is deliberately staged last, behind the trust built by User Stories 1–3.

**Independent Test**: During the first 3 weeks, generate drafts across a range of confidence
scores and confirm none post automatically; then flip the mode toggle (with the platform-
safety prerequisites met) and confirm threshold-based auto-posting, labeling, and timing
safeguards all take effect.

**Acceptance Scenarios**:

1. **Given** the system is within its first 3 weeks of operation, **When** a draft is
   generated at any confidence level, **Then** it is held for manual publishing and never
   posted automatically.
2. **Given** the 3-week validation period has ended and the posting mode has been switched to
   autonomous, **When** a draft's confidence is at or above the threshold, **Then** it is
   published automatically; **when** it is below the threshold, **then** it is held for
   manual review — never silently discarded either way.
3. **Given** autonomous mode is about to be switched on, **When** the account's bio does not
   yet carry a visible "automated" label, **Then** the switch is blocked and autonomous
   posting does not begin.
4. **Given** autonomous mode is active, **When** multiple posts are published over time,
   **Then** the time between posts varies (jitter) rather than following a fixed interval.
5. **Given** a draft cleared the confidence threshold, **When** the actual publish attempt
   fails, **Then** the failure is surfaced clearly and the draft is not silently discarded.
6. **Given** the system is switched from manual to autonomous mode mid-cycle, **When** the
   switch takes effect, **Then** it applies from the next run onward, with no retroactive
   autonomous posting of drafts that were already held under manual mode.

---

### User Story 5 - Independent Multi-User Operation (Priority: P3)

As a secondary user, I want my tracked topics and credentials kept fully separate from the
primary user's, so we can each use the tool independently without seeing each other's data.

**Why this priority**: Required for the two-person validation trial itself, but not required
for a single user to get value from User Stories 1–4.

**Independent Test**: Configure two distinct users with overlapping topic names and confirm
each only ever sees their own data, credentials, and history.

**Acceptance Scenarios**:

1. **Given** two configured users, **When** either user runs a digest, **Then** only that
   user's own tracked topics and history are used.
2. **Given** one user's credentials, **When** the other user's session or process runs,
   **Then** it has no access to those credentials or that user's data.

---

### Edge Cases

- What happens when a tracked topic returns near-zero posts in a given run window? The
  digest must state "no significant activity" explicitly, not error or silently omit the
  topic.
- What happens when rate limits are hit mid-run? Partial results must be preserved where
  possible, and affected topics must be marked incomplete rather than silently dropped.
- What happens when a fetch error occurs for one topic during a multi-topic run? The error
  is logged clearly for that topic while processing continues uninterrupted for the others.
- What happens when a user attempts to access another user's data? The request must be
  blocked by data isolation.
- What happens when a draft's confidence falls below the posting threshold after the
  autonomous switch? It is held for manual review — never auto-posted and never silently
  discarded.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST allow a user to add, remove, or list tracked topics (a keyword or
  ticker plus optional associated X handles) at any time, with changes reflected starting
  from the very next run, requiring no code change or redeploy.
- **FR-002**: System MUST retrieve recent posts for every tracked topic within a defined time
  window on each run, and MUST log a clear fetch error for any topic that fails without
  halting processing for the other topics in that run.
- **FR-003**: System MUST filter out low-quality, bot-like, or coordinated content for each
  topic before that topic's activity is evaluated for a spike, using rule-based checks first
  and escalating ambiguous cases to a deeper judgment check.
- **FR-004**: System MUST compare each topic's filtered current activity to that topic's own
  filtered historical baseline and flag the topic as spiking when activity reaches at least
  `baseline mean + k * effective standard deviation` (k = 2.5), where the effective standard
  deviation is the larger of the topic's own trailing-window stdev and a Poisson noise floor
  (`sqrt(baseline mean)`). A single fixed ratio (e.g. a flat 3x) is miscalibrated across
  volume regimes — count-data variance scales with its mean, so a flat ratio is too loose
  for low-volume topics (ordinary noise clears it) and too tight for high-volume ones (a
  real trend may never reach it); scaling the threshold to each topic's own variance fixes
  both failure modes at once.
- **FR-005**: System MUST NOT flag a newly tracked topic as spiking during its first 7 days
  of tracked history, regardless of activity level.
- **FR-006**: System MUST group filtered, related posts on a topic into thematic clusters
  rather than presenting them as a flat list.
- **FR-007**: System MUST generate, for every theme included in a digest, a plain-language
  summary, a rationale explaining why it's trending, and a confidence score.
- **FR-008**: System MUST rank digest themes in descending order of significance and include
  3–5 example posts per theme, with full underlying source data available on request but not
  shown by default.
- **FR-009**: System MUST support both an automatic, scheduled run and an on-demand, manually
  triggered run for generating a digest.
- **FR-010**: System MUST hold every drafted post for manual publishing during the first 3
  weeks of operation, regardless of confidence score, with zero posts published without
  manual action in that window.
- **FR-011**: After the 3-week validation period, System MUST support switching to autonomous
  posting through a single, explicit mode toggle, without requiring the posting logic itself
  to be rebuilt.
- **FR-012**: Once autonomous mode is active, System MUST publish drafts automatically when
  their confidence is at or above the configured threshold, and MUST hold lower-confidence
  drafts for manual review — never silently discarding a draft in either phase.
- **FR-013**: System MUST NOT allow autonomous posting to be enabled unless the associated X
  account's bio carries a visible "automated" label at the moment the mode is switched.
- **FR-014**: Once autonomous mode is active, System MUST space published posts using
  jittered/varied timing and MUST NOT publish on a perfectly fixed cadence.
- **FR-015**: System MUST store each user's tracked topics, credentials, and run history in
  isolation from every other user, such that no user can view or access another user's data.
- **FR-016**: System MUST allow a user to drill into the full source data (every filtered and
  clustered post, not just the shown examples) behind any digest entry.
- **FR-017**: System MUST state explicitly, within the digest, when a tracked topic has no
  significant activity or when all of its posts were filtered out as noise, rather than
  omitting the entry silently or raising an error.
- **FR-018**: System MUST retry transient fetch or processing errors automatically with
  backoff, and MUST make any scheduled run failure visible to the user before the next
  expected run.
- **FR-019**: System MUST surface any posting failure clearly and MUST NOT silently drop a
  draft that cleared the confidence threshold but failed to publish.
- **FR-020**: System MUST use retrieved X data only for the duration of a given run's
  analysis and MUST NOT retain raw source posts beyond what is needed to maintain each
  topic's ongoing historical baseline.
- **FR-021**: System MUST store all credentials only via environment-level configuration and
  MUST NOT allow credentials to be committed to version control.
- **FR-022**: System MUST enforce a cap of no more than 5 autonomous posts published within
  any rolling 24-hour window per user, and MUST provide a manual kill switch that
  immediately halts all autonomous posting (reverting to manual-hold behavior) when
  activated, regardless of confidence scores already computed.
- **FR-023**: System MUST send a lightweight notification (e.g., email) to the user when
  each digest run completes, so the user is alerted a digest — and, during the manual-only
  period, any drafts awaiting manual publishing — is ready for review.

### Key Entities *(include if feature involves data)*

- **Topic**: A tracked keyword, ticker, or niche belonging to one user, with optional
  associated X handles, its own historical activity baseline, and observation-period status.
- **Source Post**: A single piece of content retrieved from X for a topic, carrying its
  filter outcome (kept/excluded) and, if kept, its cluster assignment.
- **Theme**: A cluster of related, filtered posts for a topic, carrying a summary, a
  rationale, a confidence score, and a small set of example posts.
- **Digest**: A ranked collection of themes produced by one run (scheduled or on-demand) for
  a user's tracked topics.
- **Draft Post**: A system-generated post derived from a high-signal theme, pending either
  manual publishing or autonomous evaluation against the confidence threshold.
- **User**: An individual with their own topics, credentials, run history, and posting-mode
  state, fully isolated from other users.
- **Posting Mode**: The current state governing how drafts are handled — manual-only, or
  confidence-gated autonomous — switched via a single toggle and subject to the platform-
  safety prerequisites (bio label, jittered timing, posting cap, kill switch).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can add a topic and see it reflected in a digest within the very next
  run, with no code change involved.
- **SC-002**: At least 90% of a labeled test set of 50 known bot/spam posts are correctly
  excluded before spike detection runs.
- **SC-003**: Across 10 or more topics with known-normal activity, zero are flagged as a
  false-positive spike.
- **SC-004**: An on-demand run for a single topic completes in under 5 minutes.
- **SC-005**: During the first 3 weeks of operation, zero posts are published without manual
  action, including high-confidence drafts.
- **SC-006**: After the switch to autonomous mode, drafts at or above the confidence
  threshold post automatically and lower-confidence drafts are held for review, with none
  silently discarded in either phase.
- **SC-007**: Autonomous posting is never active while the account bio lacks a visible
  "automated" label.
- **SC-008**: Post timing under autonomous mode shows measurable variation between
  consecutive posts and never follows a fixed interval.
- **SC-009**: Autonomous posting volume never exceeds 5 posts in any rolling 24-hour window,
  and activating the kill switch halts all autonomous posting from that point on.
- **SC-010**: Two distinct users maintain fully separate topic lists, credentials, and
  history, with zero visibility into each other's data.
- **SC-011**: At least 80% of digests are rated "worth reading" by users over a 3-week trial.
  This is measured out-of-band via informal check-ins with the two pilot users, not an
  in-product rating feature — consistent with the MVP's no-dashboard scope (Product Brief §13,
  Assumptions below). *(Clarified per /speckit-analyze finding A1.)*
- **SC-012**: Total spend across the validation period stays within the one-time $50 total
  budget.
- **SC-013**: A user is notified within minutes of every digest run completing, without
  needing to manually check whether a new digest is ready.

## Assumptions

- In addition to being available for direct retrieval and drill-down, the system sends a
  lightweight notification (e.g., email) when each digest completes, so a completed run
  doesn't go unnoticed. This matters most during the 3-week manual-posting period, when
  drafted content depends on the user actually seeing that a digest is ready to review.
- Default scheduled cadence is daily unless a user configures a different interval; exact
  cadence is user-configurable, not fixed.
- The precise numeric confidence threshold for autonomous posting, and how it is calibrated,
  is a parameter tuned during implementation rather than fixed at the specification level.
- The MVP serves exactly two known users (the builder and their mentor); broader public
  signup and onboarding are out of scope.
- The variance-aware spike threshold (`baseline mean + k * effective standard deviation`,
  k = 2.5) and 7-day new-topic observation period are treated as fixed MVP behavior, per the
  source product requirements. The threshold's `k` value is a starting point pending
  calibration against real topic history, per FR-004.
- The autonomous-posting cap (5 posts/24h) and kill-switch mechanism satisfy the
  "governance guardrails" need without further specification; exact cap tuning may be
  revisited post-MVP based on real usage.
