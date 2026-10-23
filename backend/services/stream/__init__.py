"""Pick the transport from STREAM_TRANSPORT=local|eventhubs (default local)."""

from __future__ import annotations

import os

from .base import Envelope, Publisher, Subscriber
from .local import LocalBus, default_bus


def transport_name(name: str | None = None) -> str:
    return (name or os.getenv("STREAM_TRANSPORT", "local")).lower()


def make_publisher(name: str | None = None, bus: LocalBus | None = None) -> Publisher:
    if transport_name(name) == "eventhubs":
        from .eventhubs import EventHubsPublisher

        return EventHubsPublisher()
    return (bus or default_bus()).publisher()


def make_subscriber(name: str | None = None, bus: LocalBus | None = None, from_start: bool = False) -> Subscriber:
    if transport_name(name) == "eventhubs":
        from .eventhubs import EventHubsSubscriber

        return EventHubsSubscriber(from_start=from_start)
    return (bus or default_bus()).subscribe()


__all__ = ["Envelope", "Publisher", "Subscriber", "LocalBus", "default_bus", "make_publisher", "make_subscriber"]
