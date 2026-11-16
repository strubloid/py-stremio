"""Thread-safe progress fanout for active API-triggered jobs."""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator


class ProgressHub:
    def __init__(self) -> None:
        self._subscribers: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()

    def publish(self, event: dict) -> None:
        for loop, queue in tuple(self._subscribers):
            if loop.is_closed():
                self._subscribers.discard((loop, queue))
                continue
            loop.call_soon_threadsafe(self._put_latest, queue, event)

    async def subscribe(self) -> AsyncIterator[asyncio.Queue]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        subscriber = (loop, queue)
        self._subscribers.add(subscriber)
        try:
            yield queue
        finally:
            self._subscribers.discard(subscriber)

    @staticmethod
    def _put_latest(queue: asyncio.Queue, event: dict) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(event)


progress_hub = ProgressHub()
