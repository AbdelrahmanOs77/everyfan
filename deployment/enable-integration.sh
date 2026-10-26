#!/usr/bin/env bash
# Switch the RUNNING Container App to the integrated pipeline (analytics + agents + MCP + tracing)
# without a full redeploy. Safe to re-run.
#
#   cp deployment/integration.env.example deployment/integration.env   # fill in FOUNDRY_API_KEY etc.
#   ./deployment/enable-integration.sh [--resource-group rg-everyfan-hackathon] [--app everyfan-api]
#        [--file deployment/integration.env] [--cosmos-account NAME --cosmos-rg RG] [--no-insights] [--no-smoke]
#
# What it does:
#   1. App Insights on the existing Log Analytics workspace (agent traces) unless --no-insights
#   2. Container Apps secrets: FOUNDRY_API_KEY, MCP_API_KEY, COSMOS_KEY, App Insights connection string
#   3. Environment: PIPELINE_PLUGINS, AGENT_*, FOUNDRY_*, MCP_SERVER_URL, MCP_ALLOWED_HOSTS, COSMOS_*
#   4. Optional: Cosmos DB data-plane role for the app's managed identity (same subscription only)
#   5. Waits for the new revision and runs the smoke test (agents, feed, recap, Break it, MCP)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RG="rg-everyfan-hackathon"; APP="everyfan-api"; FILE="$ROOT/deployment/integration.env"
COSMOS_ACCOUNT=""; COSMOS_RG=""; INSIGHTS=1; SMOKE=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --resource-group) RG="$2"; shift 2 ;;
    --app) APP="$2"; shift 2 ;;
    --file) FILE="$2"; shift 2 ;;
    --cosmos-account) COSMOS_ACCOUNT="$2"; shift 2 ;;
    --cosmos-rg) COSMOS_RG="$2"; shift 2 ;;
    --no-insights) INSIGHTS=0; shift ;;
    --no-smoke) SMOKE=0; shift ;;
    *) echo "unknown option $1"; exit 2 ;;
  esac
done
[[ -f "$FILE" ]] || { echo "Missing $FILE: cp deployment/integration.env.example deployment/integration.env"; exit 2; }
step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
cfg() { python3 "$ROOT/deployment/integration_env.py" "$FILE" "$@"; }

step "Azure login and the running app"
az account show -o none 2>/dev/null || az login -o none
az config set extension.use_dynamic_install=yes_without_prompt -o none 2>/dev/null || true
FQDN="$(az containerapp show -n "$APP" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)"
LOCATION="$(az containerapp show -n "$APP" -g "$RG" --query location -o tsv)"
URL="https://$FQDN"
echo "App: $URL ($LOCATION)"
if [[ "$(cfg get AGENT_MODE)" == "foundry" && -z "$(cfg get FOUNDRY_API_KEY)" ]]; then
  echo "WARNING: AGENT_MODE=foundry without FOUNDRY_API_KEY: the app will try Entra ID, which only works if its"
  echo "         managed identity has 'Azure AI User' on the Foundry resource (same tenant). Overlays fall back"
  echo "         to checked templates if it cannot authenticate."
fi

SECRETS=(); while IFS= read -r line; do [[ -n "$line" ]] && SECRETS+=("$line"); done < <(cfg secrets)
ENVS=(); while IFS= read -r line; do [[ -n "$line" ]] && ENVS+=("$line"); done < <(cfg env)
ENVS+=("MCP_SERVER_URL=http://127.0.0.1:8000/mcp/" "MCP_ALLOWED_HOSTS=localhost,localhost:*,127.0.0.1,127.0.0.1:*,$FQDN")

if [[ "$INSIGHTS" == 1 ]]; then
  step "Application Insights for agent traces"
  WS="$(az monitor log-analytics workspace list -g "$RG" --query "[0].id" -o tsv)"
  NAME="${APP%-api}-insights"
  if ! az monitor app-insights component show --app "$NAME" -g "$RG" -o none 2>/dev/null; then
    az monitor app-insights component create --app "$NAME" -g "$RG" -l "$LOCATION" --kind web --workspace "$WS" -o none
  fi
  CONN="$(az monitor app-insights component show --app "$NAME" -g "$RG" --query connectionString -o tsv)"
  SECRETS+=("appinsights-connection=$CONN")
  ENVS+=("APPLICATIONINSIGHTS_CONNECTION_STRING=secretref:appinsights-connection")
  echo "Traces: Portal > $NAME > Transaction search (filter on everyfan.workflow)"
fi

step "Secrets (${#SECRETS[@]}): $(printf '%s ' "${SECRETS[@]%%=*}")"
az containerapp secret set -n "$APP" -g "$RG" --secrets "${SECRETS[@]}" -o none

step "Environment (new revision)"
printf '  %s\n' "${ENVS[@]%%=*}"
az containerapp update -n "$APP" -g "$RG" --set-env-vars "${ENVS[@]}" -o none

if [[ -n "$COSMOS_ACCOUNT" ]]; then
  step "Cosmos DB data role for the app identity"
  PRINCIPAL="$(az identity list -g "$RG" --query "[?contains(name,'api-identity')].principalId | [0]" -o tsv)"
  az cosmosdb sql role assignment create -g "${COSMOS_RG:-$RG}" -a "$COSMOS_ACCOUNT" --scope "/" \
    --role-definition-id 00000000-0000-0000-0000-000000000002 --principal-id "$PRINCIPAL" -o none \
    && echo "granted to $PRINCIPAL" || echo "role assignment failed (different subscription? use COSMOS_KEY instead)"
fi

step "Waiting for the new revision"
for _ in $(seq 1 40); do
  if curl -fs "$URL/api/health" | python3 -c "import json,sys; h=json.load(sys.stdin); sys.exit(0 if h.get('agents',{}).get('mode') else 1)" 2>/dev/null; then break; fi
  sleep 6
done
curl -fs "$URL/api/health" | python3 -c "import json,sys; h=json.load(sys.stdin); print('plugins', h['pipeline']['plugins']); print('agents', h.get('agents')); print('mcp', h.get('mcp'))"

if [[ "$SMOKE" == 1 ]]; then
  step "Smoke test"
  ARGS=(--url "$URL" --mcp-key "$(cfg get MCP_API_KEY)")
  [[ -f "$ROOT/deployment/.admin-token" ]] && ARGS+=(--live --admin-token "$(cat "$ROOT/deployment/.admin-token")")
  (cd "$ROOT" && python3 -m backend.cli smoke "${ARGS[@]}")
fi
