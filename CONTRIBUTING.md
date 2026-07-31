# Contributing

This is currently a **solo/internship project** — one contributor, no external contribution
process yet. This document exists to record the actual development process used so far, not to
onboard outside contributors. If that changes, this doc should change with it.

## Workflow: spec-driven development

Built with [GitHub's spec-kit](https://github.com/github/spec-kit). Foundational work goes
through:

**constitution → spec → plan → tasks → analyze → implement**

- **Constitution** ([`.specify/memory/constitution.md`](.specify/memory/constitution.md)) —
  non-negotiable engineering principles (e.g. the pipeline/agent determinism split, credential
  hygiene, cost discipline). Rarely changes.
- **Spec** — user stories, functional requirements, and acceptance criteria for one feature.
- **Plan** — architecture, tech stack, and research decisions, resolved against the constitution.
- **Tasks** — a dependency-ordered breakdown of the plan into independently testable units of work.
- **Analyze** — a cross-check of spec/plan/tasks for consistency and gaps before implementation
  starts.
- **Implement** — executes the task list, one task at a time, tests included per task.

**Reference example:** the full artifact trail for the original MVP —
[`specs/001-x-hype-finder-mvp/`](specs/001-x-hype-finder-mvp/) (`spec.md`, `plan.md`, `tasks.md`,
`research.md`, `data-model.md`, `contracts/`, `checklists/`). Every requirement in that spec traces
to a task, and every task traces to a test.

Not every change needs the full cycle. Smaller, well-scoped additions (a new pluggable provider, a
CI workflow, a docs update) have been implemented directly against the constitution's principles
without a separate spec/plan/tasks artifact set. Use judgment: a change touching core pipeline
behavior, the data model, or a user-facing contract deserves a spec; something additive and
self-contained doesn't.

## Branches

Numbered, kebab-case feature branches: `NNN-short-description` — e.g. `001-x-hype-finder-mvp`,
`005-variance-aware-detection`. The number increments per feature/change regardless of size (see
`git branch -a` for the full sequence). One branch per PR, merged into `main` with a real merge
commit — history is preserved, never squashed or rebased away.

## Before opening a PR

- **Full test suite must pass:** `uv run pytest`
- **Lint and format must be clean:** `uv run ruff check .`, `uv run ruff format --check .`, and
  `uv run black --check .`

All of the above run automatically on every push and PR via
[`.github/workflows/tests.yml`](.github/workflows/tests.yml). There's no branch-protection rule
enforcing it yet, but a red check blocks merge in practice.

## Code style

Enforced by `ruff` and `black`, configured in [`pyproject.toml`](pyproject.toml): 100-character
line length, Python 3.11 target. If either check fails locally, run `uv run ruff format .` and
re-check rather than hand-formatting to satisfy the tool.

## PR descriptions

Say what changed and **why**, not just what the diff shows. When a change was validated with a
real run against live services — not just the test suite — say so explicitly and include the
observed result, e.g. *"validated with a live `digest run`: 37 themes produced, no Fetch errors,
~$0.41 total cost"* — rather than just "tests pass." Passing tests confirm the code behaves as
written; a live validation note confirms it behaves as intended.
