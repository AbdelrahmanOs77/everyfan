#!/usr/bin/env bash
# One-command deployment of the EveryFan backend to Azure (macOS / Linux / WSL / Cloud Shell).
#
#   ./deployment/deploy.sh --location swedencentral --image ghcr.io/<owner>/<repo>-backend:latest \
#       --frontend-origin https://<your-static-web-app>.azurestaticapps.net --alert-email you@example.com
#
# --location must be one of your subscription's allowed regions
# (Portal > Policy > Assignments > "Allowed resource deployment regions" > Parameters).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RG="rg-everyfan-hackathon"; LOCATION=""; IMAGE=""; ORIGIN="http://localhost:5173"
EMAIL=""; BUDGET=40; ADMIN_TOKEN=""; EXTRA_ENV="[]"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --location) LOCATION="$2"; shift 2 ;;
    --image) IMAGE="$2"; shift 2 ;;
    --resource-group) RG="$2"; shift 2 ;;
    --frontend-origin) ORIGIN="$2"; shift 2 ;;
    --alert-email) EMAIL="$2"; shift 2 ;;
    --budget) BUDGET="$2"; shift 2 ;;
    --admin-token) ADMIN_TOKEN="$2"; shift 2 ;;
    --extra-env-json) EXTRA_ENV="$2"; shift 2 ;;
    *) echo "unknown option $1"; exit 2 ;;
  esac
done
[[ -z "$LOCATION" || -z "$IMAGE" ]] && { echo "usage: $0 --location <region> --image <image> [...]"; exit 2; }
step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }

step "Checking the Azure CLI and your login"
command -v az >/dev/null || { echo "Install the Azure CLI: https://aka.ms/azure-cli"; exit 1; }
az account show -o none 2>/dev/null || az login -o none
az account show --query "{subscription:name, user:user.name}" -o table
az bicep install >/dev/null 2>&1 || true

step "Registering resource providers (first run only, can take 1-2 minutes)"
for ns in Microsoft.App Microsoft.OperationalInsights Microsoft.Insights Microsoft.EventHub Microsoft.ManagedIdentity Microsoft.Consumption; do
  az provider register --namespace "$ns" --wait -o none
done

step "Resource group $RG in $LOCATION"
az group create -n "$RG" -l "$LOCATION" -o none || { echo "Is '$LOCATION' in your allowed regions?"; exit 1; }

[[ -z "$ADMIN_TOKEN" ]] && ADMIN_TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
DEV="$(az ad signed-in-user show --query id -o tsv 2>/dev/null || true)"

# Agents, Foundry, Cosmos and secrets come from deployment/integration.env when it exists
# (see deployment/integration.env.example). Without it the app runs analytics + checked templates.
INTEGRATION="${INTEGRATION_FILE:-$ROOT/deployment/integration.env}"
PARAMS="$(mktemp)"; trap 'rm -f "$PARAMS"' EXIT
deploy() {
  EF_IMAGE="$IMAGE" EF_ORIGIN="$ORIGIN" EF_ADMIN_TOKEN="$ADMIN_TOKEN" EF_DEV="$DEV" EF_EMAIL="$EMAIL" \
  EF_BUDGET="$BUDGET" EF_WITH_BUDGET="$1" EF_EXTRA_ENV="$EXTRA_ENV" \
    python3 "$ROOT/deployment/integration_env.py" "$INTEGRATION" paramfile "$PARAMS"
  az deployment group create -g "$RG" -n everyfan-backend -f "$ROOT/deployment/azure/main.bicep" \
    -p "@$PARAMS" --query properties.outputs -o json
}

step "Deploying Event Hubs, managed identity and Container Apps (3-6 minutes)"
if ! OUT="$(deploy true)"; then
  [[ -n "$EMAIL" ]] || exit 1
  echo "Deployment failed with the budget included; retrying without it (create the budget in the portal)."
  OUT="$(deploy false)"
fi
out() { python3 -c "import json,sys; print(json.load(sys.stdin)['$1']['value'])" <<<"$OUT"; }
URL="$(out apiUrl)"; NS="$(out eventHubNamespace)"; HUB="$(out eventHubName)"

printf '%s\n' "$ADMIN_TOKEN" > "$ROOT/deployment/.admin-token"
cat > "$ROOT/.env.azure" <<EOF
# Written by deploy.sh. No secrets: auth uses \`az login\` (you have the Event Hubs Data Owner role).
STREAM_TRANSPORT=eventhubs
EVENT_HUB_NAMESPACE=$NS
EVENT_HUB_NAME=$HUB
API_URL=$URL
EOF

step "Deployed"
echo "API:            $URL"
echo "API docs:       $URL/docs"
echo "Event Hubs:     $NS / $HUB"
echo "Admin token:    saved to deployment/.admin-token (never commit it)"
echo "Local settings: .env.azure (copy into .env to use Event Hubs from your laptop)"

step "Waiting for the app to become healthy"
for _ in $(seq 1 40); do curl -fs "$URL/api/health" >/dev/null && break; sleep 6; done
curl -fs "$URL/api/health" | python3 -c "import json,sys; h=json.load(sys.stdin); print('transport=',h['transport'],'fallback=',h['transport_fallback_reason'])" \
  || { echo "Not healthy yet: az containerapp logs show -n everyfan-api -g $RG --tail 100"; exit 1; }

step "Smoke test"
MCP_KEY="$(python3 "$ROOT/deployment/integration_env.py" "$INTEGRATION" get MCP_API_KEY)"
python3 -m backend.cli smoke --url "$URL" --origin "${ORIGIN%%,*}" --live --admin-token "$ADMIN_TOKEN" --mcp-key "$MCP_KEY"
