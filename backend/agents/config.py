"""Agent settings. Importing this module never connects to a model or Azure."""

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentConfig:
    mode: str = "off"
    foundry_project_endpoint: str = ""
    model_fast: str = ""
    model_strong: str = ""
    mcp_api_key: str = field(default="", repr=False)
    producer_timeout_s: float = 0.5
    analyst_timeout_s: float = 2.5
    writer_timeout_s: float = 2.0
    verifier_timeout_s: float = 1.0
    total_timeout_s: float = 5.5
    analyst_model_role: str = "strong"
    verifier_model_role: str = "strong"

    @classmethod
    def from_env(cls) -> "AgentConfig":
        mode = os.getenv("AGENT_MODE", "off").lower()
        if mode not in {"off", "stub", "foundry"}:
            raise ValueError("AGENT_MODE must be off, stub, or foundry")
        deadlines = {}
        roles = {}
        for stage in ("analyst", "verifier"):
            key = f"AGENT_{stage.upper()}_MODEL_ROLE"
            role = os.getenv(key, "strong").lower()
            if role not in {"fast", "strong"}:
                raise ValueError(f"{key} must be fast or strong")
            roles[f"{stage}_model_role"] = role
        for stage in ("producer", "analyst", "writer", "verifier", "total"):
            key = f"{stage}_timeout_s"
            value = float(os.getenv(f"AGENT_{key.upper()}", str(getattr(cls, key))))
            if not 0 < value < float("inf"):
                raise ValueError(f"AGENT_{key.upper()} must be finite and positive")
            deadlines[key] = value
        return cls(mode=mode, foundry_project_endpoint=os.getenv("FOUNDRY_PROJECT_ENDPOINT", ""),
                   model_fast=os.getenv("FOUNDRY_MODEL_FAST", ""),
                   model_strong=os.getenv("FOUNDRY_MODEL_STRONG", ""),
                   mcp_api_key=os.getenv("MCP_API_KEY", ""), **deadlines, **roles)
