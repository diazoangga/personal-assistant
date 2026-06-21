"""In-process event bus for job progress streaming."""

import asyncio
from collections import defaultdict
from typing import AsyncIterator

from .events import Event


class EventBus:
    """
    Async pub/sub event bus keyed by job_id.

    Allows multiple subscribers to stream events from a job.
    """

    def __init__(self):
        # job_id -> list of queues (one per subscriber)
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def subscribe(self, job_id: str) -> AsyncIterator[Event]:
        """
        Subscribe to events for a job.

        Yields events as they are published.
        """
        queue: asyncio.Queue = asyncio.Queue()

        async with self._lock:
            self._subscribers[job_id].append(queue)

        try:
            while True:
                event = await queue.get()
                if event is None:  # Sentinel for end of stream
                    break
                yield event
        finally:
            async with self._lock:
                if queue in self._subscribers[job_id]:
                    self._subscribers[job_id].remove(queue)

    async def publish(self, event: Event) -> None:
        """Publish an event to all subscribers of the job."""
        async with self._lock:
            queues = self._subscribers.get(event.job_id, [])

        # Send to all subscribers concurrently
        async def put(queue: asyncio.Queue):
            try:
                await queue.put(event)
            except asyncio.CancelledError:
                pass

        await asyncio.gather(*[put(q) for q in queues], return_exceptions=True)

    async def close(self, job_id: str) -> None:
        """Close the event stream for a job (send sentinel)."""
        async with self._lock:
            queues = self._subscribers.pop(job_id, [])

        # Send sentinel to all subscribers
        async def put_sentinel(queue: asyncio.Queue):
            try:
                await queue.put(None)
            except asyncio.CancelledError:
                pass

        await asyncio.gather(*[put_sentinel(q) for q in queues], return_exceptions=True)
