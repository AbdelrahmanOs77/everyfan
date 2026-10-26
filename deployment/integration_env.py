"""Reads deployment/integration.env for the deploy scripts. Prints nothing secret unless asked to.

    python deployment/integration_env.py FILE secrets   -> one "name=value" per line (Container Apps secrets)
    python deployment/integration_env.py FILE env       -> one "KEY=value" or "KEY=secretref:name" per line
    python deployment/integration_env.py FILE get KEY   -> a single plain value (empty if missing)
    python deployment/integration_env.py FILE bicep     -> JSON {"params": {...}, "extraEnv": [...], "secretEnv": {...}}
    python deployment/integration_env.py FILE paramfile OUT
        -> writes an ARM parameters file for main.bicep from FILE plus EF_* variables set by deploy.sh
"""

from __future__ import annotations

import json
import os
import secrets
import sys
from pathlib import Path

SECRET_SUFFIXES = ("_KEY", "_SECRET", "_CONNECTION_STRING", "_CONNECTION_STR", "_TOKEN")
# Settings main.bicep takes as parameters (everything else goes through extraEnv).
BICEP_PARAMS = {"PIPELINE_PLUGINS": "pipelinePlugins", "AGENT_MODE": "agentMode",
                "FOUNDRY_PROJECT_ENDPOINT": "foundryProjectEndpoint", "FOUNDRY_MODEL_FAST": "foundryModelFast",
                "FOUNDRY_MODEL_STRONG": "foundryModelStrong", "AGENT_ANALYST_MODEL_ROLE": "analystModelRole",
                "AGENT_VERIFIER_MODEL_ROLE": "verifierModelRole", "AGENT_TOOLS": "agentTools",
                "LIVE_MODE_DAILY_TOKEN_CAP": "dailyTokenCap", "BROADCAST_DELAY_S": "broadcastDelaySeconds"}
ROOT = Path(__file__).resolve().parents[1]
MCP_KEY_FILE = ROOT / "deployment" / ".mcp-api-key"


def secret_name(key: str) -> str:
    return key.lower().replace("_", "-")


def read(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip().strip('"').strip("'")
            if value:
                values[key.strip()] = value
    if "MCP_API_KEY" not in values:
        if not MCP_KEY_FILE.exists():
            MCP_KEY_FILE.write_text(secrets.token_urlsafe(32), encoding="utf-8")
        values["MCP_API_KEY"] = MCP_KEY_FILE.read_text(encoding="utf-8").strip()
    if "PIPELINE_PLUGINS" in values and "template_plugin" in values["PIPELINE_PLUGINS"] and "agents" in values["PIPELINE_PLUGINS"]:
        sys.exit("PIPELINE_PLUGINS loads both template_plugin and agents: goals would air twice")
    return values


def is_secret(key: str) -> bool:
    return key.endswith(SECRET_SUFFIXES)


def main(argv: list[str]) -> int:
    path, mode = Path(argv[1]), argv[2]
    values = read(path)
    if mode == "secrets":
        for k, v in values.items():
            if is_secret(k):
                print(f"{secret_name(k)}={v}")
    elif mode == "env":
        for k, v in values.items():
            print(f"{k}=secretref:{secret_name(k)}" if is_secret(k) else f"{k}={v}")
    elif mode == "get":
        print(values.get(argv[3], ""))
    elif mode == "paramfile":
        params = {BICEP_PARAMS[k]: v for k, v in values.items() if k in BICEP_PARAMS}
        params.update(image=os.environ["EF_IMAGE"], frontendOrigin=os.environ["EF_ORIGIN"],
                      adminToken=os.environ["EF_ADMIN_TOKEN"], developerPrincipalId=os.environ.get("EF_DEV", ""),
                      alertEmail=os.environ.get("EF_EMAIL", ""), budgetAmount=int(os.environ.get("EF_BUDGET", "40")),
                      deployBudget=os.environ.get("EF_WITH_BUDGET", "true") == "true",
                      extraEnv=json.loads(os.environ.get("EF_EXTRA_ENV") or "[]")
                      + [{"name": k, "value": v} for k, v in values.items() if k not in BICEP_PARAMS and not is_secret(k)],
                      secretEnv={k: v for k, v in values.items() if is_secret(k)})
        doc = {"$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
               "contentVersion": "1.0.0.0", "parameters": {k: {"value": v} for k, v in params.items()}}
        Path(argv[3]).write_text(json.dumps(doc), encoding="utf-8")
    elif mode == "bicep":
        params = {BICEP_PARAMS[k]: v for k, v in values.items() if k in BICEP_PARAMS}
        extra = [{"name": k, "value": v} for k, v in values.items() if k not in BICEP_PARAMS and not is_secret(k)]
        secret_env = {k: v for k, v in values.items() if is_secret(k)}
        print(json.dumps({"params": params, "extraEnv": extra, "secretEnv": secret_env}))
    else:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
