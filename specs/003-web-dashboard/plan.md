# Implementation Plan: Web Dashboard

**Branch**: `003-web-dashboard` (proposed) | **Date**: 2026-08-12

**Status**: Planned, not yet implemented — captured from a conversational design session
(not generated via `/speckit-plan`) so the design survives to whenever this gets built.

**Input**: "Build a professional, full-featured web UI for X Hype Finder — a real dashboard,
not just a read-only viewer" — a new FastAPI backend + React/Tailwind/Vite frontend exposing
topics, digests, drafts, Idea Validation Mode, and the eval report, with single-shared-password
auth, real confirmation modals before any destructive/posting action, and full test coverage.

## Summary

A new `src/web/` FastAPI backend and a new `web/` Vite + React + TypeScript + Tailwind
single-page frontend, together forming a genuine dashboard (not a read-only viewer) over the
existing brand-tracking pipeline, Idea Validation Mode, and the eval system. The backend is a
thin translation layer over the *existing* business-logic functions
(`add_topic`/`remove_topic`/`list_topics`, `run_digest`, `list_drafts`/`mark_published`,
`_compute_report`, and Idea Validation's pipeline) — no pipeline logic is reimplemented for the
API. Long-running operations (digest run, Idea Validation run — both take minutes) are exposed
as background jobs with a poll-for-status endpoint, matching the async, non-blocking nature of
the underlying pipeline. Authentication is a single shared password via env var, backed by
Starlette's built-in signed-cookie session middleware — appropriate for this project's
single-operator, self-hosted scale, not a multi-tenant login system.

---

## 0. Decisions made during planning (flagged, then resolved as follows)

Two points in the original request needed a decision before the design could be locked in; both
were flagged during planning and resolved as documented here — this is the design this plan
commits to, not an open question.

### A. "The manual-override publish flow we built earlier"

The real X-posting override (`DraftPostStatus.PUBLISHED_MANUAL_OVERRIDE`, an actual
`create_tweet()` call) was explicitly designed with **no reachable code path** —
`draft_post.py`'s docstring states: *"there is deliberately no CLI command that reaches this
status; every occurrence is a one-off, hand-confirmed action, never a routine automated path"* —
added after a real incident where a manual override was misrecorded. What was actually built and
tested is `mark_published()` in `src/cli/drafts.py`: it records that the user *already* posted a
`held_manual` draft themselves; it never calls the X API.

**Resolution**: `POST /api/drafts/{id}/publish` wraps `mark_published()`, not the override path.
The UI's confirmation modal replaces the CLI's `y/n` prompt (`_confirm_already_posted`), same
semantics: "mark this as published — you're asserting you already posted it yourself." Live,
one-click X posting from the dashboard is explicitly **out of scope** for this plan; it would be
a materially different, higher-risk endpoint requiring its own explicit design/approval.

### B. `GET /api/idea-validate`

Idea Validation Mode is deliberately stateless — no DB writes at all, by design (see
`specs/002-idea-validation-mode/research.md` §1). A `GET` returning "run history" is therefore
architecturally impossible without reversing that design decision.

**Resolution**: `GET /api/idea-validate` returns static config info for the run form (e.g. the
default lookback window) — not history. `POST /api/idea-validate` (same path) starts a run as a
background job, polled via `GET /api/idea-validate/jobs/{job_id}`.

---

## 1. Backend: `src/web/`

```
src/web/
├── __init__.py
├── app.py              # FastAPI app factory: middleware, routers, static-file mount
├── deps.py              # get_db, get_current_user, require_auth dependencies
├── auth.py               # password check (secrets.compare_digest) + session helpers
├── jobs.py                # generic in-memory job registry (shared by digest-run + idea-validate-run)
├── schemas.py               # Pydantic request/response models
└── routers/
    ├── auth.py
    ├── topics.py
    ├── digests.py
    ├── drafts.py
    ├── eval.py
    └── idea_validate.py
```

**Core principle**: every router is a thin translation layer over the *existing* business-logic
functions — `add_topic`/`remove_topic`/`list_topics` (`cli/topic.py`), `run_digest`
(`pipeline/orchestrator.py`), `list_drafts`/`mark_published` (`cli/drafts.py`), `_compute_report`
(`cli/eval.py`), and the Idea Validation pipeline. No pipeline logic gets rewritten for the API.

One small, necessary refactor: `run_idea_validation()` currently returns a pre-rendered
**string** (for the CLI). A dashboard needs structured JSON (verdict text, signal-strength
numbers, themes array) to build real cards — not a text blob dropped into a `<pre>`. Split it:

```python
def run_idea_validation_structured(query, *, anthropic_api_key, claude_model) -> ValidationReadout:
    ...  # exactly today's body, minus the final render call
def run_idea_validation(query, **kwargs) -> str:
    return render_validation_readout(run_idea_validation_structured(query, **kwargs))
```

CLI behavior is byte-for-byte unchanged; the API calls the structured version directly. Same
non-issue for digests — `GET /api/digests/{id}` queries `Digest`/`DigestTopicResult`/`Theme`/
`SourcePost` directly via the already-standalone `_digest_for_user`/`_active_topics` helpers and
`scoped_select`, building Pydantic models from the ORM rows (importing
`CONFIDENCE_DISPLAY_THRESHOLD` from `cli/digest.py` rather than re-deriving it, so the
confidence-hiding rule can't drift between CLI and API).

### Auth

Single shared password via `XHF_WEB_PASSWORD` env var, plus `XHF_WEB_SESSION_SECRET` for
signing — using Starlette's built-in `SessionMiddleware` (ships with FastAPI's underlying
framework, backed by `itsdangerous`, HttpOnly signed cookie, no hand-rolled crypto):

- `POST /api/auth/login` `{password}` → `secrets.compare_digest` against `XHF_WEB_PASSWORD`;
  sets `request.session["authenticated"] = True` on success, `401` on failure.
- `POST /api/auth/logout` → clears session.
- `GET /api/auth/me` → `{authenticated: bool}`, for the frontend's boot check.
- `require_auth` dependency on every other router — `401` if session isn't authenticated.

**Which "current user"?** The web server resolves the acting user via the *same*
`resolve_current_user()` every CLI command already uses (single-user auto-resolve, or
`XHF_USER_EMAIL` if ambiguous) — called fresh per request, not cached. This is a single-operator
dashboard behind one shared password, not multi-tenant login, so reusing the existing
identity-resolution rule is the correct fit rather than inventing a second concept.

### Background jobs (digest run + idea-validate run)

Both take minutes — can't block an HTTP request. `src/web/jobs.py`: a tiny in-memory registry
(`job_id → {kind, status: running|completed|failed, result_id, error}`), driven by FastAPI's
`BackgroundTasks` (Starlette runs a sync callable in a threadpool automatically, so `run_digest`'s
blocking `time.sleep`-based rate pacing and sync Claude/httpx calls work as-is, no `asyncio`
rewrite needed).

- `POST /api/digests/run` `{topic_name?: str}` → `202 {job_id}`.
- `GET /api/digests/jobs/{job_id}` → `{status, digest_id?, error?}` — frontend polls this.
- `POST /api/idea-validate` `{phrases, exclude_terms?, since?, until?}` → `202 {job_id}`.
- `GET /api/idea-validate/jobs/{job_id}` → `{status, readout?, error?}`.

Deliberately **not** a persisted job queue (no Celery/RQ) — in-process dict, single `uvicorn`
worker only (must be documented explicitly in the README setup section: `--workers 1`, since a
second worker process wouldn't share this dict). This matches the project's existing scale
(single-operator, self-hosted tool) rather than over-engineering for horizontal scale it doesn't
need. Job state is lost on server restart — acceptable for a multi-minute-but-bounded operation
the user is actively watching in the UI.

### Full endpoint table

| Method | Path | Reuses | Notes |
|---|---|---|---|
| POST | `/api/auth/login` | new | `{password}` → session cookie |
| POST | `/api/auth/logout` | new | clears session |
| GET | `/api/auth/me` | new | boot-check |
| GET | `/api/topics` | `list_topics` | |
| POST | `/api/topics` | `add_topic` | `{name, handles?}` |
| DELETE | `/api/topics/{id}` | `remove_topic` | |
| GET | `/api/digests` | direct query | list, newest first |
| GET | `/api/digests/{id}?full=false` | `_digest_for_user` + direct query | mirrors `digest show`/`--full` |
| POST | `/api/digests/run` | `run_digest` (background) | `{topic_name?}` → `202 {job_id}` |
| GET | `/api/digests/jobs/{job_id}` | `jobs.py` | poll |
| GET | `/api/drafts?status=` | `list_drafts` | |
| POST | `/api/drafts/{id}/publish` | `mark_published` | `{confirmed: true}` **required literal** — mirrors the CLI's explicit `--yes`, no implicit "button click = confirm" |
| GET | `/api/eval` | `_compute_report` | |
| GET | `/api/idea-validate` | new | static defaults, not history (stateless mode — see §0.B) |
| POST | `/api/idea-validate` | `run_idea_validation_structured` (background) | `202 {job_id}` |
| GET | `/api/idea-validate/jobs/{job_id}` | `jobs.py` | poll |

---

## 2. Frontend: `web/` (Vite + React + TypeScript + Tailwind)

TypeScript by default for a "professional, full-featured" dashboard (better DX/type-safety
against the Pydantic schemas) — plain JS remains an option if less tooling is preferred later.

```
web/
├── package.json, vite.config.ts, tailwind.config.js, tsconfig.json, index.html
└── src/
    ├── main.tsx, App.tsx                 # router + auth guard
    ├── api/client.ts                       # typed fetch wrapper, credentials: 'include'
    ├── hooks/useAuth.ts, useJobPolling.ts
    ├── layout/Sidebar.tsx, Header.tsx, DashboardLayout.tsx
    ├── pages/
    │   ├── LoginPage.tsx
    │   ├── TopicsPage.tsx
    │   ├── DigestsPage.tsx, DigestDetailPage.tsx
    │   ├── DraftsPage.tsx
    │   ├── IdeaValidationPage.tsx
    │   └── EvalPage.tsx
    └── components/
        ├── ui/  Button, Card, Modal, ConfirmDialog, Badge, Spinner, Toast
        ├── topics/  TopicCard, AddTopicModal
        ├── digests/  ThemeCard, RunDigestButton (job progress), FullToggle
        ├── drafts/  DraftCard, PublishConfirmModal
        └── idea-validate/  VerdictCard, SignalStrengthCard, ThemeCard, RunForm
```

- **Routing**: `react-router-dom` — `/login`, `/topics`, `/digests`, `/digests/:id`, `/drafts`,
  `/idea-validation`, `/eval`.
- **Server state**: `@tanstack/react-query` — fetch/cache everywhere, and `refetchInterval` is a
  natural fit for job polling (digest-run, idea-validate-run). No Redux/Zustand needed at this
  scope.
- **Destructive/posting actions**: one shared `ConfirmDialog` component, reused for topic
  removal and draft publish — a real modal, explicit "type to confirm" or a two-button dialog
  (not a single "Confirm?" button one misclick away), matching the CLI's
  `_confirm_already_posted` gate philosophy.
- **Production serving**: `npm run build` → `web/dist/`; FastAPI mounts it via `StaticFiles` so
  one `uvicorn src.web.app:app` process serves both API and SPA — one deployable unit. A thin
  `src/cli/web.py` (`web run [--host] [--port]`) for consistency with every other long-lived-
  process entry point in this project (matches `scheduler run`'s pattern).
- **Dev mode**: `uvicorn --reload` on `:8000` + `npm run dev` (Vite, `:5173`) proxying `/api` to
  `:8000`.

## 3. Visual design direction

Dark-mode-first, reusing this project's *own* established color language from the README's
Mermaid diagrams rather than inventing a new palette — genuine brand consistency between docs and
UI:

- **Background**: near-black slate (`#0b0f17`/`#0f172a` range), card surfaces one step lighter
  with a subtle 1px border, no heavy drop-shadows.
- **Primary accent (deterministic-pipeline actions — topics, digests, filters)**: the same blue
  as the diagrams' `pipelineNode` (`#2563eb` family).
- **Secondary accent (AI-derived content — Verdict, Summarize, Draft Post)**: the same pink as
  the diagrams' `agentNode` (`#db2777` family) — e.g. the Verdict card on the Idea Validation page
  gets a pink-accented border, visually saying "this came from the LLM stage" the same way the
  architecture diagram does.
- **Status semantics**: green = published/kept/success, amber = held/pending (matches the
  diagrams' gate-node amber), red = failed/error.
- **Type**: Inter or system-ui stack, generous spacing, card-based grid layouts, status badges
  everywhere (draft status, digest-topic outcome, theme confidence band).
- Light mode: not in scope for v1 given "dark-mode-first" — a toggle can be added later if wanted.

## 4. Dependencies

- **Backend** (`pyproject.toml`): `fastapi`, `uvicorn[standard]`, `itsdangerous` (session
  signing); dev: `httpx` (required by FastAPI's `TestClient`).
- **Frontend** (`web/package.json`): `react`, `react-dom`, `react-router-dom`,
  `@tanstack/react-query`, `vite`, `typescript`, `tailwindcss`, `postcss`, `autoprefixer`.

## 5. Testing

`tests/web/` — `TestClient` (FastAPI/Starlette), DB dependency overridden to the existing
in-memory `db_session` fixture, Fetch/Claude mocked the same way `test_on_demand_digest.py`/
`test_idea_validation_flow.py` already do. One file per router: `test_api_auth.py`,
`test_api_topics.py`, `test_api_digests.py`, `test_api_drafts.py`, `test_api_eval.py`,
`test_api_idea_validate.py`. Background-job tests invoke the worker function directly (bypassing
real `BackgroundTasks` scheduling) for deterministic, non-flaky polling assertions.

**CI**: add a `web` job to `.github/workflows/tests.yml` — `npm ci && npm run build`
(+ `tsc --noEmit`) in `web/`, alongside the existing Python job, so a broken frontend build fails
CI same as a broken Python one.

## 6. Docs

- New `## Web Dashboard` README section (added to the Table of Contents): what it is, setup
  (`XHF_WEB_PASSWORD`/`XHF_WEB_SESSION_SECRET`, `npm install && npm run build`,
  `python -m src.cli.web run`), a screenshot placeholder
  (`docs/media/web-dashboard-placeholder.png` — noted as pending a real run, not fabricated).
- Update `docs/cli-usage.md`'s intro line, which currently states *"No web/GUI dashboard exists
  in this MVP (Product Brief §13) — the CLI is the entire user-facing interface"* — this becomes
  false the moment this ships.
- `.env.example` gets the two new web env vars.

---

## Suggested build order (for review-ability, not necessarily separate PRs)

1. Backend: `src/web/` (auth → topics/drafts/eval routers, simplest reuse first →
   digests/idea-validate with the job registry) + full test suite.
2. Frontend scaffold: Vite/Tailwind/routing/auth guard, empty pages.
3. Page-by-page implementation wired to the real API.
4. Docs + CI.

This is a large addition — realistically ~25-30 new backend files/tests and a full SPA.

## Complexity Tracking

No violations of this project's Constitution to record — this plan is additive-only (new
`src/web/` and `web/` trees), does not modify pipeline logic, and introduces no new credential
type beyond the two new web-specific env vars documented in §6.
