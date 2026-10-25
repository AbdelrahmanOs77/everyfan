"""Small model interface; deterministic offline implementation for CI."""

import json
import asyncio
import os
import importlib
from typing import Protocol
from urllib.parse import urlparse

from .config import AgentConfig
from .telemetry import current, record_usage


class ModelClient(Protocol):
    async def complete(self, system: str, user: str, json_schema: dict | None = None) -> tuple[str, int]: ...


class BudgetUnavailable(RuntimeError):
    pass


async def complete_with_budget(model: ModelClient, system: str, user: str, json_schema: dict | None = None,
                               *, budget, timeout_s: float | None = None) -> tuple[str, int]:
    # UTF-8 bytes are a conservative token estimate, plus bounded output/role overhead.
    estimate = len((system + user + json.dumps(json_schema or {})).encode("utf-8")) + 1200
    with current().span("model.complete", model=getattr(model, "name", "unknown")) as span:
        if budget is None or not await budget.try_reserve(estimate):
            span.set(reason_code="BUDGET")
            raise BudgetUnavailable("Token budget unavailable")
        actual, reported = estimate, 0
        try:
            call = model.complete(system, user, json_schema)
            text, usage = await asyncio.wait_for(call, timeout_s) if timeout_s is not None else await call
            if not isinstance(usage, int) or isinstance(usage, bool) or usage < 0:
                raise ValueError("Model did not report valid token usage")
            actual = reported = usage
            span.set(outcome="completed", usage_unknown=False)
            return text, usage
        finally:
            # On cancellation/transport failure the service may still have spent tokens.
            span.set(usage_unknown=actual != reported)
            record_usage(reported, actual)
            await budget.settle(estimate, actual)


class FoundryModel:
    """Lazy direct inference through Agent Framework's current Foundry client."""

    def __init__(self, endpoint: str, deployment: str, *, client=None, reasoning_effort: str | None = None):
        parsed = urlparse(endpoint)
        if (parsed.scheme != "https" or not (parsed.hostname or "").endswith(".services.ai.azure.com")
                or not parsed.path.startswith("/api/projects/") or not deployment):
            raise ValueError("A Foundry project endpoint and deployment name are required")
        self.endpoint, self.name = endpoint, deployment
        self.reasoning_effort = reasoning_effort
        self._client, self._credential = client, None
        self._init_lock = asyncio.Lock()

    async def _get_client(self):
        async with self._init_lock:
            if self._client is None:
                foundry = await asyncio.to_thread(importlib.import_module, "agent_framework.foundry")
                identity = await asyncio.to_thread(importlib.import_module, "azure.identity.aio")
                self._credential = identity.DefaultAzureCredential(exclude_interactive_browser_credential=True,
                                                                    managed_identity_client_id=os.getenv("AZURE_CLIENT_ID"))
                self._client = foundry.FoundryChatClient(project_endpoint=self.endpoint, model=self.name, credential=self._credential)
        return self._client

    async def complete(self, system: str, user: str, json_schema: dict | None = None) -> tuple[str, int]:
        framework = await asyncio.to_thread(importlib.import_module, "agent_framework")
        options = {"store": False, "max_tokens": 1024}
        if json_schema is not None:
            # Dynamic fact maps cannot use OpenAI's strict fixed-property schemas.
            # Request JSON and validate the supplied schema in each consuming stage.
            options["response_format"] = {"type": "json_object"}
            system += "\nReturn JSON matching this schema: " + json.dumps(json_schema, ensure_ascii=False)
        if self.reasoning_effort:
            options["reasoning"] = {"effort": self.reasoning_effort}
        client = await self._get_client()
        response = await client.get_response([framework.Message("system", [system]), framework.Message("user", [user])], options=options)
        usage = response.usage_details or {}
        total = usage.get("total_token_count")
        if not isinstance(total, int) or isinstance(total, bool) or total < 0:
            raise ValueError("Foundry response omitted token usage")
        return response.text, total

    async def prepare(self) -> None:
        """Initialize SDK and authentication at startup, without a paid model request."""
        await self._get_client()
        if self._credential is not None:
            await self._credential.get_token("https://ai.azure.com/.default")

    async def aclose(self) -> None:
        if self._credential is not None:
            try:
                if self._client is not None:
                    await self._client.client.close()
                    await self._client.project_client.close()
            finally:
                await self._credential.close()
                self._client, self._credential = None, None


def create_model(config: AgentConfig, role: str = "fast") -> ModelClient | None:
    if role not in {"fast", "strong"}:
        raise ValueError("Model role must be fast or strong")
    if config.mode == "off":
        return None
    if config.mode == "stub":
        return StubModel()
    if config.mode != "foundry":
        raise ValueError("Unknown agent mode")
    deployment = config.model_fast if role == "fast" else config.model_strong
    effort = "low" if role == "strong" else None
    return FoundryModel(config.foundry_project_endpoint, deployment, reasoning_effort=effort)


class StubModel:
    """Return caller-provided grounded fixtures, never invent text or contact a service.

    User payload: {"task": "writer", "template": {"headline": ..., "body": ..., "fields": ...}}
    or {"task": "analyst", "brief": <Contract D>}.
    Zero tokens means zero model usage, rather than a fabricated token count.
    """

    name = "stub"

    async def complete(self, system: str, user: str, json_schema: dict | None = None) -> tuple[str, int]:
        payload = json.loads(user)
        task = payload.get("task")
        if task == "writer":
            template = payload["template"]
            result = {key: template[key] for key in ("headline", "body", "fields")}
        elif task == "analyst":
            result = payload["brief"]
        else:
            raise ValueError(f"Unsupported stub task: {task!r}")
        return json.dumps(result, ensure_ascii=False), 0
