#!/usr/bin/env bash
# Roll the running Container App to a new image, then smoke test.
#   ./deployment/update-image.sh ghcr.io/<owner>/<repo>-backend:3f2a9c1e5b7d [resource-group] [app]
set -euo pipefail
IMAGE="${1:?usage: $0 <image> [resource-group] [app]}"; RG="${2:-rg-everyfan-hackathon}"; APP="${3:-everyfan-api}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
az containerapp update -n "$APP" -g "$RG" --image "$IMAGE" --set-env-vars "APP_VERSION=${IMAGE##*:}" -o none
URL="https://$(az containerapp show -n "$APP" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)"
echo "Rolled to $IMAGE. Waiting for the new revision..."; sleep 25
if [[ -f "$ROOT/deployment/.admin-token" ]]; then
  python3 -m backend.cli smoke --url "$URL" --live --admin-token "$(cat "$ROOT/deployment/.admin-token")"
else
  python3 -m backend.cli smoke --url "$URL"
fi
