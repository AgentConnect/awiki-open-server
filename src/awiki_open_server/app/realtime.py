from __future__ import annotations

import asyncio
from dataclasses import dataclass
from threading import Lock
from typing import Any


@dataclass(frozen=True)
class _Subscription:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[dict[str, Any]]


class RealtimeHub:
    def __init__(self) -> None:
        self._lock = Lock()
        self._subscriptions: dict[str, list[_Subscription]] = {}

    def subscribe(self, did: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        subscription = _Subscription(loop=asyncio.get_running_loop(), queue=queue)
        with self._lock:
            self._subscriptions.setdefault(did, []).append(subscription)
        return queue

    def unsubscribe(self, did: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            subscriptions = self._subscriptions.get(did, [])
            remaining = [item for item in subscriptions if item.queue is not queue]
            if remaining:
                self._subscriptions[did] = remaining
            else:
                self._subscriptions.pop(did, None)

    def publish(self, did: str, notification: dict[str, Any]) -> None:
        with self._lock:
            subscriptions = list(self._subscriptions.get(did, []))
        for subscription in subscriptions:
            subscription.loop.call_soon_threadsafe(self._put_nowait, subscription.queue, notification)

    @staticmethod
    def _put_nowait(queue: asyncio.Queue[dict[str, Any]], notification: dict[str, Any]) -> None:
        try:
            queue.put_nowait(notification)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            queue.put_nowait(notification)
