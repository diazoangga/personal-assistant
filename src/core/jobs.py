"""Job queue and state management."""

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator, Callable, Coroutine

from .commands import Command
from .events import Event


class JobState(str, Enum):
    """Job lifecycle states."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job:
    """Represents an async job."""

    job_id: str
    command: Command
    state: JobState = JobState.PENDING
    result: Any | None = None
    error: str | None = None
    created_at: float = field(default_factory=lambda: asyncio.get_event_loop().time())
    updated_at: float = field(default_factory=lambda: asyncio.get_event_loop().time())


class JobQueue:
    """Async job queue with state tracking."""

    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def spawn(
        self, job: Job, handler: Coroutine[Any, Any, Any]
    ) -> None:
        """Spawn a new job and start executing its handler."""
        async with self._lock:
            self._jobs[job.job_id] = job
            job.state = JobState.RUNNING

            # Create task for the handler
            task = asyncio.create_task(self._run_handler(job, handler))
            self._tasks[job.job_id] = task

    async def _run_handler(
        self, job: Job, handler: Coroutine[Any, Any, Any]
    ) -> None:
        """Run the handler and update job state."""
        try:
            result = await handler
            job.state = JobState.COMPLETED
            job.result = result
        except asyncio.CancelledError:
            job.state = JobState.CANCELLED
            raise
        except Exception as e:
            job.state = JobState.FAILED
            job.error = str(e)
        finally:
            job.updated_at = asyncio.get_event_loop().time()
            # Clean up task reference
            if job.job_id in self._tasks:
                del self._tasks[job.job_id]

    async def cancel(self, job_id: str) -> bool:
        """Cancel a running job. Returns True if cancelled."""
        async with self._lock:
            if job_id not in self._tasks:
                return False

            task = self._tasks[job_id]
            if not task.done():
                task.cancel()
                return True
            return False

    def get(self, job_id: str) -> Job | None:
        """Get a job by ID."""
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[Job]:
        """List all jobs."""
        return list(self._jobs.values())
