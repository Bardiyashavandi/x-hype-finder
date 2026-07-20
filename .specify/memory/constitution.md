<!--
Sync Impact Report
Version change: [TEMPLATE] → 1.0.0 (initial ratification)
Modified principles: none (first fill of template placeholders)
Added sections:
  - Core Principles I–VII (Deterministic Data Pipeline, Filter-Before-Detect Ordering,
    Staged Posting Autonomy, Platform-Safe Autonomous Posting, Credential Hygiene,
    Cost Discipline, Measurable Definition of Done)
  - Security & Privacy Constraints
  - Development Workflow & Quality Gates
  - Governance
Removed sections: none
Templates requiring updates:
  - .specify/templates/plan-template.md — ✅ no change needed (Constitution Check gate
    already resolves dynamically against this file at plan time)
  - .specify/templates/spec-template.md — ✅ no change needed (generic template already
    accommodates measurable, testable requirements per Principle VII)
  - .specify/templates/tasks-template.md — ✅ no change needed (generic template; no new
    mandatory task category introduced by these principles)
  - README.md — ✅ reviewed, stub file, nothing to sync
Follow-up TODOs: none
-->

# X Hype Finder Constitution

## Core Principles

### I. Deterministic, Testable Data Pipeline
Fetch, Filter, Detect, and Cluster MUST remain fully deterministic — driven only by
rules, statistics, and embeddings, never by LLM or agent judgment. Each stage MUST
take a defined input and produce a reproducible, independently testable output.
**Rationale**: keeps the core system fast, cheap, and verifiable, and prevents model
drift or prompt changes from silently altering what counts as a "spike" or "clean" post.

### II. Filter-Before-Detect Ordering
Bot/noise filtering MUST run before spike detection, never after. Spike Detection MUST
only ever see already-filtered content. **Rationale**: a burst of coordinated bot
activity must never be able to trigger a false "trending" flag before the bots are
removed from consideration.

### III. Staged Posting Autonomy
Posting MUST default to fully manual for the first 3 weeks of operation, regardless of
confidence score — zero posts go out without a human action during this window. After
the validation period, the system MAY switch to confidence-gated autonomous posting,
but only through a single, explicit mode toggle, never as an incidental side effect of
an unrelated change. **Rationale**: builds real, evidence-based trust in the system
before it acts unsupervised, and keeps the manual→autonomous transition an intentional,
auditable decision.

### IV. Platform-Safe Autonomous Posting
Autonomous posting MUST NOT be enabled until the X account's bio carries a visible
"automated" label, verified against the live bio text at the time the mode switch is
flipped. Once autonomous, posts MUST use jittered/varied timing between publishes —
a perfectly fixed cadence is explicitly disallowed. **Rationale**: disclosure and
non-robotic timing are baseline expectations for automated accounts on X; skipping
either is a known trigger for reduced visibility or account suspension.

### V. Credential Hygiene
Credentials MUST live only in environment variables and MUST NEVER be committed to
version control. Any credential that is exposed MUST be rotated immediately.
**Rationale**: this project handles live, personally-owned X API access — a leaked
credential is an irreversible, immediate-impact failure, not a recoverable bug.

### VI. Cost Discipline
The total available budget is a one-time **$50**, not a recurring monthly allowance.
Free trial credits and locally-run models MUST be used for as long as possible before
any paid API or LLM usage begins, and actual spend MUST be tracked cumulatively against
the $50 total rather than assumed to renew. **Rationale**: because the budget is fixed
rather than renewing, premature or untracked paid usage directly and permanently
shortens the project's runway.

### VII. Measurable Definition of Done
No feature is considered done without an explicit, measurable acceptance criterion that
is verified before it is treated as complete. Vague criteria ("should work", "looks
right") are not acceptable substitutes for a stated, checkable condition.
**Rationale**: with only two real users and a short validation window, ambiguous
"done" criteria are how scope and quality silently drift.

## Security & Privacy Constraints

Credentials are handled per Principle V (environment variables only, immediate
rotation on exposure). Beyond that: X data MUST be used only for the duration of
analysis and MUST NOT be stored permanently beyond what's needed to maintain each
topic's historical baseline. No private individual MUST be singled out beyond what is
already public in their own posts. Each user's topics, credentials, and history MUST
be stored with strict isolation — one user MUST have zero visibility into another
user's data.

## Development Workflow & Quality Gates

Every feature MUST carry the measurable acceptance criterion required by Principle
VII before it is merged or treated as shippable. Reliability MUST follow the pattern
already established for the pipeline: a failure on one tracked topic MUST NOT block
digest generation for other topics, transient errors MUST retry with backoff, and
scheduled job failures MUST be visible to the user before the next expected run.
Posting failures MUST be surfaced clearly — a draft that cleared the confidence
threshold but failed to publish MUST NEVER be silently dropped.

## Governance

This constitution supersedes all other project practices and prior undocumented
conventions. Any amendment MUST update this file directly, include a Sync Impact
Report as an HTML comment at the top of the file, and propagate necessary changes to
dependent templates (plan, spec, tasks) in the same change.

**Versioning policy** (semantic versioning applied to this document):
- **MAJOR**: backward-incompatible principle removals or redefinitions.
- **MINOR**: a new principle or materially expanded section is added.
- **PATCH**: wording clarifications or non-semantic fixes.

**Compliance review**: the Constitution Check gate in the plan workflow MUST be
evaluated against the current version of this file before Phase 0 research and
re-checked after Phase 1 design. Any deviation MUST be justified in that plan's
Complexity Tracking table or the deviation MUST be resolved before proceeding.

**Version**: 1.0.0 | **Ratified**: 2026-07-20 | **Last Amended**: 2026-07-20
