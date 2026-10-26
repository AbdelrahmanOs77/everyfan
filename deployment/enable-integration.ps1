<#
.SYNOPSIS
  Switch the RUNNING Container App to the integrated pipeline (analytics + agents + MCP + tracing)
  without a full redeploy. Safe to re-run.

.EXAMPLE
  copy deployment\integration.env.example deployment\integration.env   # fill in FOUNDRY_API_KEY etc.
  ./deployment/enable-integration.ps1
  ./deployment/enable-integration.ps1 -CosmosAccount everyfan-cosmos-xx -CosmosResourceGroup rg-everyfan-analytics

  1. App Insights on the existing Log Analytics workspace (agent traces) unless -NoInsights
  2. Container Apps secrets: FOUNDRY_API_KEY, MCP_API_KEY, COSMOS_KEY, App Insights connection string
  3. Environment: PIPELINE_PLUGINS, AGENT_*, FOUNDRY_*, MCP_SERVER_URL, MCP_ALLOWED_HOSTS, COSMOS_*
  4. Optional: Cosmos DB data-plane role for the app's managed identity (same subscription only)
  5. Waits for the new revision and runs the smoke test (agents, feed, recap, Break it, MCP)
#>
param(
    [string] $ResourceGroup = "rg-everyfan-hackathon",
    [string] $App = "everyfan-api",
    [string] $File = "",
    [string] $CosmosAccount = "",
    [string] $CosmosResourceGroup = "",
    [switch] $NoInsights,
    [switch] $NoSmoke
)
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $File) { $File = Join-Path $Root "deployment/integration.env" }
function Step([string] $m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Fail([string] $m) { Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }
function Cfg { python "$Root/deployment/integration_env.py" $File @args }
if (-not (Test-Path $File)) { Fail "Missing $File : copy deployment\integration.env.example deployment\integration.env" }

Step "Azure login and the running app"
az account show -o none 2>$null
if ($LASTEXITCODE -ne 0) { az login | Out-Null }
az config set extension.use_dynamic_install=yes_without_prompt -o none 2>$null
$Fqdn = az containerapp show -n $App -g $ResourceGroup --query properties.configuration.ingress.fqdn -o tsv
if ($LASTEXITCODE -ne 0 -or -not $Fqdn) { Fail "Container App $App not found in $ResourceGroup" }
$Location = az containerapp show -n $App -g $ResourceGroup --query location -o tsv
$Url = "https://$Fqdn"
Write-Host "App: $Url ($Location)"
if ((Cfg get AGENT_MODE) -eq "foundry" -and -not (Cfg get FOUNDRY_API_KEY)) {
    Write-Host "WARNING: AGENT_MODE=foundry without FOUNDRY_API_KEY: the app will try Entra ID, which only works if its" -ForegroundColor Yellow
    Write-Host "         managed identity has 'Azure AI User' on the Foundry resource (same tenant)." -ForegroundColor Yellow
}

$Secrets = @(Cfg secrets | Where-Object { $_ })
$Envs = @(Cfg env | Where-Object { $_ })
$Envs += "MCP_SERVER_URL=http://127.0.0.1:8000/mcp/"
$Envs += "MCP_ALLOWED_HOSTS=localhost,localhost:*,127.0.0.1,127.0.0.1:*,$Fqdn"

if (-not $NoInsights) {
    Step "Application Insights for agent traces"
    $Ws = az monitor log-analytics workspace list -g $ResourceGroup --query "[0].id" -o tsv
    $Name = ($App -replace "-api$", "") + "-insights"
    az monitor app-insights component show --app $Name -g $ResourceGroup -o none 2>$null
    if ($LASTEXITCODE -ne 0) {
        az monitor app-insights component create --app $Name -g $ResourceGroup -l $Location --kind web --workspace $Ws -o none
    }
    $Conn = az monitor app-insights component show --app $Name -g $ResourceGroup --query connectionString -o tsv
    $Secrets += "appinsights-connection=$Conn"
    $Envs += "APPLICATIONINSIGHTS_CONNECTION_STRING=secretref:appinsights-connection"
    Write-Host "Traces: Portal > $Name > Transaction search (filter on everyfan.workflow)"
}

Step ("Secrets ({0}): {1}" -f $Secrets.Count, (($Secrets | ForEach-Object { ($_ -split "=", 2)[0] }) -join " "))
az containerapp secret set -n $App -g $ResourceGroup --secrets @Secrets -o none
if ($LASTEXITCODE -ne 0) { Fail "Could not set secrets" }

Step "Environment (new revision)"
$Envs | ForEach-Object { Write-Host ("  " + ($_ -split "=", 2)[0]) }
az containerapp update -n $App -g $ResourceGroup --set-env-vars @Envs -o none
if ($LASTEXITCODE -ne 0) { Fail "Could not update the app environment" }

if ($CosmosAccount) {
    Step "Cosmos DB data role for the app identity"
    $Principal = az identity list -g $ResourceGroup --query "[?contains(name,'api-identity')].principalId | [0]" -o tsv
    $CosmosRg = if ($CosmosResourceGroup) { $CosmosResourceGroup } else { $ResourceGroup }
    az cosmosdb sql role assignment create -g $CosmosRg -a $CosmosAccount --scope "/" `
        --role-definition-id 00000000-0000-0000-0000-000000000002 --principal-id $Principal -o none
    if ($LASTEXITCODE -eq 0) { Write-Host "granted to $Principal" }
    else { Write-Host "role assignment failed (different subscription? use COSMOS_KEY instead)" -ForegroundColor Yellow }
}

Step "Waiting for the new revision"
for ($i = 0; $i -lt 40; $i++) {
    try { $h = Invoke-RestMethod "$Url/api/health" -TimeoutSec 10; if ($h.agents.mode) { break } } catch { }
    Start-Sleep -Seconds 6
}
$h = Invoke-RestMethod "$Url/api/health"
Write-Host ("plugins " + ($h.pipeline.plugins -join ","))
Write-Host ("agents  " + ($h.agents | ConvertTo-Json -Compress -Depth 4))
Write-Host ("mcp     " + ($h.mcp | ConvertTo-Json -Compress))

if (-not $NoSmoke) {
    Step "Smoke test"
    $SmokeArgs = @("--url", $Url, "--mcp-key", (Cfg get MCP_API_KEY))
    $TokenFile = Join-Path $Root "deployment/.admin-token"
    if (Test-Path $TokenFile) { $SmokeArgs += @("--live", "--admin-token", (Get-Content $TokenFile -Raw).Trim()) }
    Push-Location $Root
    python -m backend.cli smoke @SmokeArgs
    Pop-Location
}
