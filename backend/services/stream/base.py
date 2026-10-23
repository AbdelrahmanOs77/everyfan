"""Transport-agnostic streaming interface.

Everything downstream (consumer, analytics, API) only depends on these two
protocols, so the same code runs on the in-process LocalBus and on Azure Event Hubs.
"""

from __future__ import annotations

from typing import AsyncIterator, Protocol, Sequence, runtime_checkable

from shared.schemas import EventEnvelope, MetadataEnvelope, TrackingEnvelope, ControlEnvelope

Envelope = MetadataEnvelope | EventEnvelope | TrackingEnvelope | ControlEnvelope


@runtime_checkable
class Publisher(Protocol):
    async def send(self, envelopes: Sequence[Envelope]) -> None: ...

    async def close(self) -> None: ...


@runtime_checkable
class Subscriber(Protocol):
    def __aiter__(self) -> AsyncIterator[Envelope]: ...

    async def close(self) -> None: ...
