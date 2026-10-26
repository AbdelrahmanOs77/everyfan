<#
.SYNOPSIS
  Record the cached demo matches with REAL Foundry agents (the only step that spends model tokens).
  Judges then watch agent-written, verified overlays and recaps with zero model cost.

.EXAMPLE
  ./deployment/build-demo-agents.ps1                    # all 4 matches
  ./deployment/build-demo-agents.ps1 -Scenario derby_balanced

  Needs FOUNDRY_* settings: `az login` with access to Owner C's Foundry project, or FOUNDRY_API_KEY,
  in .env or deployment/integration.env. Writes into a scratch folder first; copy to demo/ after review.
#>
param([string] $Scenario = "", [string] $Out = "", [switch] $Relaxed)
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not $Out) { $Out = Join-Path $Root ".venv/demo-agents" }
$Integration = Join-Path $Root "deployment/integration.env"
if (Test-Path $Integration) {
    Get-Content $Integration | Where-Object { $_ -match '^(FOUNDRY_|AGENT_ANALYST|AGENT_VERIFIER)[A-Z_]*=.+' } | ForEach-Object {
        $k, $v = $_ -split "=", 2; Set-Item -Path "Env:$k" -Value $v.Trim()
    }
}
$env:AGENT_MODE = "foundry"
$env:PIPELINE_PLUGINS = "backend.analytics.plugin:register,backend.agents.plugin:register"
$env:AGENT_TOOLS = "inprocess"
# Default: the real live deadlines (5.5 s per moment), so every recorded overlay - and its latency readout -
# is exactly what live mode would have aired. One moment at a time, paced under the deployment's
# tokens-per-minute quota (everyfan-fast is 30k TPM). -Relaxed: generous deadlines, more agent overlays.
if (-not $env:AGENT_BUILD_CONCURRENCY) { $env:AGENT_BUILD_CONCURRENCY = "1" }
if (-not $env:AGENT_BUILD_TPM) { $env:AGENT_BUILD_TPM = "24000" }
if ($Relaxed) {
    $env:AGENT_PRODUCER_TIMEOUT_S = "30"; $env:AGENT_ANALYST_TIMEOUT_S = "30"; $env:AGENT_WRITER_TIMEOUT_S = "30"
    $env:AGENT_VERIFIER_TIMEOUT_S = "30"; $env:AGENT_TOTAL_TIMEOUT_S = "120"
}
$env:LIVE_MODE_DAILY_TOKEN_CAP = if ($env:BUILD_TOKEN_CAP) { $env:BUILD_TOKEN_CAP } else { "3000000" }
$Target = if ($Scenario) { @("--scenario", $Scenario) } else { @("--all") }
python -m backend.cli build-demo @Target --out $Out
Write-Host ""
Write-Host "Recorded into $Out. Review it (overlay_sources: agent/approved vs template/fallback; have a native"
Write-Host "speaker spot-check the Arabic), then:"
Write-Host "  copy $Out\*.bundle.json demo\ ; python -m pytest -q tests/test_api.py tests/test_integration.py"
Write-Host "  git add demo/*.bundle.json   # then push; the image workflow ships it"
