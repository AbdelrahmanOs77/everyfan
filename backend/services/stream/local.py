"""In-process message bus with the same contract as Event Hubs.

Messages are serialised to JSON and parsed again on the way out, exactly like the
real transport, so contract errors show up locally too. Every subscriber receives
every message (fan-out), in publish order.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Sequence

from shared.schemas import dump_envelope, parse_envelope

from .base import Envelope

_CLOSED = object()


class LocalBus:
    def __init__(self) -> None:
        self._queues: list[asyncio.Queue] = []

    def subscribe(self) -> "LocalSubscriber":
        q: asyncio.Queue = asyncio.Queue()
        self._queues.append(q)
        return LocalSubscriber(self, q)

    def publisher(self) -> "LocalPublisher":
        return LocalPublisher(self)

    def _unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._queues:
            self._queues.remove(q)
            q.put_nowait(_CLOSED)

    def _publish(self, body: str) -> None:
        for q in self._queues:
            q.put_nowait(body)


_default_bus: LocalBus | None = None


def default_bus() -> LocalBus:
    global _default_bus
    if _default_bus is None:
        _default_bus = LocalBus()
    return _default_bus


class LocalPublisher:
    def __init__(self, bus: LocalBus) -> None:
        self.bus = bus
        self.sent = 0

    async def send(self, envelopes: Sequence[Envelope]) -> None:
        for env in envelopes:
            self.bus._publish(dump_envelope(env))
            self.sent += 1
        await asyncio.sleep(0)  # let subscribers run

    async def probe(self) -> dict:
        return {"local": True}

    async def close(self) -> None:
        return None


class LocalSubscriber:
    def __init__(self, bus: LocalBus, q: asyncio.Queue) -> None:
        self.bus, self.q = bus, q

    async def __aiter__(self) -> AsyncIterator[Envelope]:
        while True:
            body = await self.q.get()
            if body is _CLOSED:
                return
            yield parse_envelope(body)

    async def close(self) -> None:
        self.bus._unsubscribe(self.q)
