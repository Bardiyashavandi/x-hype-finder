"""Generic in-memory background-job registry, shared by the digest-run and
idea-validate-run endpoints (specs/003-web-dashboard/plan.md §1 "Background
jobs (digest run + idea-validate run)").

Both underlying operations take minutes — too long to block an HTTP request
— so each is started via FastAPI's `BackgroundTasks` (Starlette runs a sync
callable in a threadpool automatically, so `run_digest`'s blocking
`time.sleep`-based rate pacing and sync Claude/httpx calls work as-is, no
`asyncio` rewrite needed) and polled via `GET .../jobs/{job_id}`.

Deliberately **not** a persisted job queue (no Celery/RQ): an in-process
dict, single `uvicorn` worker only (`--workers 1` — a second worker process
wouldn't share this dict). Job state is lost on server restart, which is
acceptable for a multi-minute-but-bounded operation the user is actively
watching in the UI — this matches the project's existing single-operator,
self-hosted scale rather than over-engineering for horizontal scale it
doesn't need.
"""

from __future__ import annotations

import enum
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

T = TypeVar("T")


class JobStatus(enum.StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Job:
    id: uuid.UUID
    kind: str
    status: JobStatus = JobStatus.RUNNING
    result: Any = None
    error: str | None = None


class JobRegistry:
    """A plain `job_id -> Job` dict guarded by a lock — needed because
    `BackgroundTasks` runs each job's worker function on its own threadpool
    thread, concurrently with `GET .../jobs/{job_id}` polls from the request
    thread(s)."""

    def __init__(self) -> None:
        self._jobs: dict[uuid.UUID, Job] = {}
        self._lock = threading.Lock()

    def create(self, kind: str) -> Job:
        job = Job(id=uuid.uuid4(), kind=kind)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: uuid.UUID) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def run(self, job: Job, fn: Callable[..., T], *args: Any, **kwargs: Any) -> None:
        """Run `fn(*args, **kwargs)` and record its outcome on `job` — the
        actual callable handed to FastAPI's `BackgroundTasks.add_task`.

        A raised exception is recorded as the job's `error` rather than
        propagated — `BackgroundTasks` has no caller left to propagate to by
        the time this runs, and an unrecorded failure would leave the job
        stuck at `running` forever from the poller's point of view. Tests
        call this directly (bypassing real `BackgroundTasks` scheduling) for
        deterministic, non-flaky polling assertions (plan.md §5).
        """
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - must never leave a job stuck at "running"
            with self._lock:
                job.status = JobStatus.FAILED
                job.error = str(exc)
            return
        with self._lock:
            job.status = JobStatus.COMPLETED
            job.result = result


# One shared, process-wide registry — see module docstring for why this is
# deliberately a singleton rather than per-request state.
registry = JobRegistry()
