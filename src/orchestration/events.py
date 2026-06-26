"""Event bus for sandbox events + SSE streaming."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncIterator

logger = logging.getLogger(__name__)


@dataclass
class Event:
    sandbox_id: str
    event_type: str
    data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps({
            "sandbox_id": self.sandbox_id,
            "event_type": self.event_type,
            "data": self.data,
            "timestamp": self.timestamp,
        })


class EventBus:
    """In-memory event bus with SSE subscriber support."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._global_subscribers: list[asyncio.Queue] = []

    async def publish(self, event: Event) -> None:
        """Publish an event to all subscribers."""
        # Send to sandbox-specific subscribers
        for queue in self._subscribers.get(event.sandbox_id, []):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

        # Send to global subscribers
        for queue in self._global_subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def subscribe(self, sandbox_id: str | None = None) -> AsyncIterator[Event]:
        """Subscribe to events. If sandbox_id is None, subscribe to all."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)

        if sandbox_id:
            self._subscribers.setdefault(sandbox_id, []).append(queue)
        else:
            self._global_subscribers.append(queue)

        return self._listen(queue)

    async def _listen(self, queue: asyncio.Queue) -> AsyncIterator[Event]:
        """Listen for events on a queue."""
        try:
            while True:
                event = await queue.get()
                yield event
        except asyncio.CancelledError:
            pass
        finally:
            # Clean up
            for sid, queues in self._subscribers.items():
                if queue in queues:
                    queues.remove(queue)
            if queue in self._global_subscribers:
                self._global_subscribers.remove(queue)
