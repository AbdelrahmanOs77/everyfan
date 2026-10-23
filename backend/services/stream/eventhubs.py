"""Azure Event Hubs transport (async).

Authentication, in order of preference:
  1. Microsoft Entra ID (passwordless): set EVENT_HUB_NAMESPACE=<ns>.servicebus.windows.net.
     Locally this uses your `az login`; in Container Apps it uses the managed identity.
     Your identity needs "Azure Event Hubs Data Sender" / "Data Receiver" roles.
  2. Connection string: set EVENT_HUB_CONNECTION_STR (handy for a first test; never commit it).

Every message is partitioned by match_id, so events of one match stay in order.
Basic tier notes: one consumer group ($Default), 256 KB max message, 1-day retention.
We do not use checkpointing: consumers start at "@latest" and de-duplicate by event_id.
"""

from __future__ import annotations

import asyncio
import os
from typing import AsyncIterator, Sequence

from shared.schemas import dump_envelope, parse_envelope

from .base import Envelope

_CLOSED = object()


def _config() -> dict:
    return {
        "conn_str": os.getenv("EVENT_HUB_CONNECTION_STR"),
        "namespace": os.getenv("EVENT_HUB_NAMESPACE"),
        "hub": os.getenv("EVENT_HUB_NAME", "match-events"),
        "consumer_group": os.getenv("EVENT_HUB_CONSUMER_GROUP", "$Default"),
    }


def _credential():
    from azure.identity.aio import DefaultAzureCredential

    client_id = os.getenv("AZURE_CLIENT_ID")  # user-assigned managed identity, if used
    return DefaultAzureCredential(managed_identity_client_id=client_id) if client_id else DefaultAzureCredential()


class EventHubsPublisher:
    def __init__(self) -> None:
        from azure.eventhub.aio import EventHubProducerClient

        cfg = _config()
        self._credential = None
        if cfg["conn_str"]:
            self.client = EventHubProducerClient.from_connection_string(cfg["conn_str"], eventhub_name=cfg["hub"])
        elif cfg["namespace"]:
            self._credential = _credential()
            self.client = EventHubProducerClient(
                fully_qualified_namespace=cfg["namespace"], eventhub_name=cfg["hub"], credential=self._credential
            )
        else:
            raise RuntimeError("Set EVENT_HUB_NAMESPACE (recommended) or EVENT_HUB_CONNECTION_STR")
        self.sent = 0

    async def probe(self) -> dict:
        """Fails fast on bad auth, missing roles or a wrong namespace/hub name."""
        props = await self.client.get_eventhub_properties()
        return {"eventhub": props["eventhub_name"], "partitions": len(props["partition_ids"])}

    async def send(self, envelopes: Sequence[Envelope]) -> None:
        from azure.eventhub import EventData

        by_match: dict[str, list[Envelope]] = {}
        for env in envelopes:
            by_match.setdefault(env.match_id, []).append(env)
        for match_id, envs in by_match.items():
            batch = await self.client.create_batch(partition_key=match_id)
            for env in envs:
                data = EventData(dump_envelope(env))
                data.properties = {"kind": env.kind, "match_id": match_id, "run_id": env.run_id}
                try:
                    batch.add(data)
                except ValueError:  # batch full -> send and start a new one
                    await self.client.send_batch(batch)
                    batch = await self.client.create_batch(partition_key=match_id)
                    batch.add(data)
            if len(batch):
                await self.client.send_batch(batch)
            self.sent += len(envs)

    async def close(self) -> None:
        await self.client.close()
        if self._credential:
            await self._credential.close()


class EventHubsSubscriber:
    """Receives from all partitions; yields parsed envelopes in arrival order."""

    def __init__(self, from_start: bool = False) -> None:
        from azure.eventhub.aio import EventHubConsumerClient

        cfg = _config()
        self._credential = None
        if cfg["conn_str"]:
            self.client = EventHubConsumerClient.from_connection_string(
                cfg["conn_str"], consumer_group=cfg["consumer_group"], eventhub_name=cfg["hub"]
            )
        elif cfg["namespace"]:
            self._credential = _credential()
            self.client = EventHubConsumerClient(
                fully_qualified_namespace=cfg["namespace"], eventhub_name=cfg["hub"],
                consumer_group=cfg["consumer_group"], credential=self._credential,
            )
        else:
            raise RuntimeError("Set EVENT_HUB_NAMESPACE (recommended) or EVENT_HUB_CONNECTION_STR")
        self.starting_position = "-1" if from_start else "@latest"
        self.q: asyncio.Queue = asyncio.Queue()
        self.parse_errors = 0
        self._task: asyncio.Task | None = None

    async def probe(self) -> dict:
        """Fails fast on bad auth, missing roles or a wrong namespace/hub name."""
        props = await self.client.get_eventhub_properties()
        return {"eventhub": props["eventhub_name"], "partitions": len(props["partition_ids"])}

    async def _on_event(self, _partition_context, event) -> None:
        if event is None:
            return
        try:
            self.q.put_nowait(parse_envelope(event.body_as_str(encoding="UTF-8")))
        except Exception:  # malformed message: count it, never crash the consumer
            self.parse_errors += 1

    async def _receive(self) -> None:
        try:
            await self.client.receive(on_event=self._on_event, starting_position=self.starting_position)
        finally:
            self.q.put_nowait(_CLOSED)

    async def __aiter__(self) -> AsyncIterator[Envelope]:
        if self._task is None:
            self._task = asyncio.create_task(self._receive())
        while True:
            item = await self.q.get()
            if item is _CLOSED:
                return
            yield item

    async def close(self) -> None:
        await self.client.close()
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)
        if self._credential:
            await self._credential.close()
