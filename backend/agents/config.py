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
    # Cross-tenant deployments (the API's managed identity lives in another Azure account than
    # Foundry) authenticate with the Foundry resource key instead of Entra ID. Never logged.
    foundry_api_key: str = field(default="", repr=False)
    foundry_openai_endpoint: str = ""
    producer_timeout_s: float = 0.5
    analyst_timeout_s: float = 2.5
    writer_timeout_s: float = 2.0
    verifier_timeout_s: float = 1.0
    total_timeout_s: float = 5.5
    analyst_model_role: str = "strong"
    verifier_model_role: str = "strong"
    # How the Analyst reaches the evidence tools: in-process calls, or the real MCP transport.
    tools_transport: str = "inprocess"
    mcp_server_url: str = "http://127.0.0.1:8000/mcp/"
    club_persona: bool = True  # Favorite Club overlays, one per club (AGENT_CLUB_PERSONA=0 turns them off)
    ask_per_minute: int = 6
    ask_max_question: int = 300
    ask_max_history: int = 4
    ask_max_tools: int = 3
    coach_interval_s: int = 30
    coach_hold_s: int = 180
    coach_window_s: int = 60
    coach_cooldown_s: int = 300
    coach_baseline_s: int = 600
    coach_line_change_m: float = 8
    coach_area_change_pct: float = 25
    coach_counter_min: int = 2
    advanced_debounce_s: float = 0.75

    @classmethod
    def from_env(cls) -> "AgentConfig":
        mode = os.getenv("AGENT_MODE", "off").lower()
        if mode not in {"off", "stub", "foundry"}:
            raise ValueError("AGENT_MODE must be off, stub, or foundry")
        tools = os.getenv("AGENT_TOOLS", "inprocess").strip().lower()
        if tools not in {"inprocess", "mcp"}:
            raise ValueError("AGENT_TOOLS must be inprocess or mcp")
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
                   mcp_api_key=os.getenv("MCP_API_KEY", ""),
                   foundry_api_key=os.getenv("FOUNDRY_API_KEY", "").strip(),
                   foundry_openai_endpoint=os.getenv("FOUNDRY_OPENAI_ENDPOINT", "").strip(),
                   tools_transport=tools,
                   mcp_server_url=os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp/").strip(),
                   club_persona=os.getenv("AGENT_CLUB_PERSONA", "1").strip().lower() not in {"0", "false", "no", "off"},
                   **deadlines, **roles)
