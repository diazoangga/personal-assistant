"""In-process job/event hub for the local web API.

Unlike the engine's EventBus (which drops events published before a subscriber
attaches), the hub *buffers* every event for a job from the moment the job is
created. A job is registered synchronously in the POST handler before any work
starts, so an SSE/WebSocket client that connects slightly later still replays the
full event history and then follows live updates. This eliminates the
submit-then-subscribe race.

The hub also owns the command runners that turn an HTTP request into a streamed
job, driving the engine's public coroutines and emitting the event envelope from
events.py.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from . import events

logger = logging.getLogger(__name__)


@dataclass
class JobRecord:
    """Buffered event log for a single job."""

    job_id: str
    kind: str
    events: list[dict[str, Any]] = field(default_factory=list)
    done: bool = False
    cond: asyncio.Condition = field(default_factory=asyncio.Condition)


class EventHub:
    """Registry of in-flight/finished jobs and their buffered events."""

    def __init__(self, max_jobs: int = 256):
        self._jobs: dict[str, JobRecord] = {}
        self._order: list[str] = []
        self._max_jobs = max_jobs

    def create(self, kind: str, job_id: Optional[str] = None) -> JobRecord:
        """Register a new job. Call this *before* starting work."""
        job_id = job_id or uuid.uuid4().hex[:8]
        rec = JobRecord(job_id=job_id, kind=kind)
        self._jobs[job_id] = rec
        self._order.append(job_id)
        self._evict()
        return rec

    def get(self, job_id: str) -> Optional[JobRecord]:
        return self._jobs.get(job_id)

    def _evict(self) -> None:
        """Drop the oldest *finished* jobs once over capacity."""
        while len(self._order) > self._max_jobs:
            oldest = self._order[0]
            rec = self._jobs.get(oldest)
            if rec is None or rec.done:
                self._order.pop(0)
                self._jobs.pop(oldest, None)
            else:
                break

    async def emit(self, job_id: str, event: dict[str, Any]) -> None:
        rec = self._jobs.get(job_id)
        if rec is None:
            return
        async with rec.cond:
            rec.events.append(event)
            rec.cond.notify_all()

    async def finish(self, job_id: str) -> None:
        rec = self._jobs.get(job_id)
        if rec is None:
            return
        async with rec.cond:
            rec.done = True
            rec.cond.notify_all()

    async def stream(self, job_id: str) -> AsyncIterator[dict[str, Any]]:
        """Yield buffered then live events until the job finishes.

        Safe to call at any time after `create()` — replays history first.
        """
        rec = self._jobs.get(job_id)
        if rec is None:
            return
        idx = 0
        while True:
            async with rec.cond:
                while idx >= len(rec.events) and not rec.done:
                    await rec.cond.wait()
                pending = rec.events[idx:]
                idx = len(rec.events)
                done = rec.done
            for ev in pending:
                yield ev
            if done and not pending:
                return


# --------------------------------------------------------------------------- #
# Command runners
# --------------------------------------------------------------------------- #
#
# Each runner registers nothing (the caller already created the JobRecord) and
# drives one engine coroutine to completion, emitting started -> message ->
# result (or error). Because the job was created before the runner starts, no
# event can be missed by a late subscriber.


async def run_text_job(
    hub: EventHub,
    job_id: str,
    kind: str,
    coro: Awaitable[str],
    *,
    result_extra: Optional[Callable[[], Awaitable[dict[str, Any]]]] = None,
) -> None:
    """Run a coroutine that returns answer text; stream it as one message + result.

    `result_extra`, if given, is awaited after success to enrich the result
    payload (e.g. research run counts).
    """
    await hub.emit(job_id, events.started(job_id, kind))
    try:
        text = await coro
        await hub.emit(job_id, events.message(job_id, text))
        data: dict[str, Any] = {"answer": text}
        if result_extra is not None:
            try:
                data.update(await result_extra())
            except Exception as exc:  # enrichment is best-effort
                logger.warning("result enrichment failed for job %s: %s", job_id, exc)
        await hub.emit(job_id, events.result(job_id, True, data))
    except Exception as exc:
        logger.exception("job %s (%s) failed", job_id, kind)
        await hub.emit(job_id, events.error(job_id, str(exc)))
        await hub.emit(job_id, events.result(job_id, False, {"error": str(exc)}))
    finally:
        await hub.finish(job_id)
