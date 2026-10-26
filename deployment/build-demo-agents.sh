#!/usr/bin/env bash
# Record the cached demo matches with REAL Foundry agents (the only step that spends model tokens).
# Judges then watch agent-written, verified overlays and recaps with zero model cost.
#
#   ./deployment/build-demo-agents.sh                 # all 4 matches
#   ./deployment/build-demo-agents.sh derby_balanced  # just the demo match (cheapest)
#
# Needs FOUNDRY_* settings: either `az login` with access to Owner C's Foundry project, or FOUNDRY_API_KEY,
# in .env or deployment/integration.env. Writes into a scratch folder first; copy to demo/ after review.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT="${OUT:-$ROOT/.venv/demo-agents}"
if [[ -f deployment/integration.env ]]; then
  set -a; source <(grep -E '^(FOUNDRY_|AGENT_ANALYST|AGENT_VERIFIER|AGENT_TOOLS)' deployment/integration.env); set +a
fi
export AGENT_MODE=foundry PIPELINE_PLUGINS="backend.analytics.plugin:register,backend.agents.plugin:register"
export AGENT_TOOLS=inprocess                                  # offline build: no server to call over MCP
# Default: the real live deadlines (5.5 s per moment), so every recorded overlay - and its "generated in
# X of 5500 ms" readout - is exactly what live mode would have aired. One moment at a time, paced under the
# deployment's tokens-per-minute quota (everyfan-fast is 30k TPM) to avoid 429 fallbacks.
# RELAXED=1: generous deadlines instead (more agent overlays, readouts then show the relaxed budget).
export AGENT_BUILD_CONCURRENCY="${AGENT_BUILD_CONCURRENCY:-1}" AGENT_BUILD_TPM="${AGENT_BUILD_TPM:-24000}"
if [[ "${RELAXED:-0}" == 1 ]]; then
  export AGENT_PRODUCER_TIMEOUT_S=30 AGENT_ANALYST_TIMEOUT_S=30 AGENT_WRITER_TIMEOUT_S=30
  export AGENT_VERIFIER_TIMEOUT_S=30 AGENT_TOTAL_TIMEOUT_S=120
fi
export LIVE_MODE_DAILY_TOKEN_CAP="${BUILD_TOKEN_CAP:-3000000}"
if [[ $# -gt 0 ]]; then TARGET=(--scenario "$1"); else TARGET=(--all); fi
python -m backend.cli build-demo "${TARGET[@]}" --out "$OUT"
cat <<EOF

Recorded into $OUT. Review it (overlay_sources shows agent/approved vs template/fallback; ask a native
speaker to spot-check the Arabic), then:

  cp $OUT/*.bundle.json demo/ && python -m pytest -q tests/test_api.py tests/test_integration.py
  git add demo/*.bundle.json    # then push; the image workflow ships it

EOF
