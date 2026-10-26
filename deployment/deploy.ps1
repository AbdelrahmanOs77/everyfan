<#
.SYNOPSIS
  One-command deployment of the EveryFan backend to Azure (Event Hubs + Container Apps + managed identity).

.EXAMPLE
  ./deployment/deploy.ps1 -Location swedencentral -Image ghcr.io/<owner>/<repo>-backend:latest `
      -FrontendOrigin https://<your-static-web-app>.azurestaticapps.net -AlertEmail you@example.com

  -Location must be one of your subscription's allowed regions:
  Portal > Policy > Assignments > "Allowed resource deployment regions" > Parameters.
#>
param(
    [Parameter(Mandatory = $true)] [string] $Location,
    [Parameter(Mandatory = $true)] [string] $Image,
    [string] $ResourceGroup = "rg-everyfan-hackathon",
    [string] $FrontendOrigin = "http://localhost:5173",
    [string] $AlertEmail = "",
    [int] $BudgetAmount = 40,
    [string] $AdminToken = "",
    [string] $ExtraEnvJson = "[]"
)
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
function Step([string] $m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Fail([string] $m) { Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }
function Write-Utf8([string] $Path, [string] $Text) {
    # BOM-free UTF-8 (Windows PowerShell 5.1 adds a BOM that breaks JSON and .env parsers)
    [IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding $false))
}

Step "Checking the Azure CLI and your login"
if (-not (Get-Command az -ErrorAction SilentlyContinue)) { Fail "Install the Azure CLI: https://aka.ms/installazurecliwindows" }
az account show -o none 2>$null
if ($LASTEXITCODE -ne 0) { az login | Out-Null }
az account show --query "{subscription:name, user:user.name}" -o table
az bicep install 2>$null | Out-Null

Step "Registering resource providers (first run only, can take 1-2 minutes)"
foreach ($ns in "Microsoft.App", "Microsoft.OperationalInsights", "Microsoft.Insights", "Microsoft.EventHub", "Microsoft.ManagedIdentity", "Microsoft.Consumption") {
    az provider register --namespace $ns --wait -o none
}

Step "Resource group $ResourceGroup in $Location"
az group create -n $ResourceGroup -l $Location -o none
if ($LASTEXITCODE -ne 0) { Fail "Could not create the resource group. Is '$Location' in your allowed regions?" }

if (-not $AdminToken) { $AdminToken = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N") }
$Developer = az ad signed-in-user show --query id -o tsv 2>$null
if ($LASTEXITCODE -ne 0) { $Developer = "" }

$ParamFile = Join-Path ([IO.Path]::GetTempPath()) "everyfan-params.json"
$Extra = @()
if ($ExtraEnvJson -and $ExtraEnvJson.Trim() -ne "[]") { $Extra = @($ExtraEnvJson | ConvertFrom-Json) }
# Agents, Foundry, Cosmos and secrets come from deployment/integration.env when it exists
# (see deployment/integration.env.example). Without it the app runs analytics + checked templates.
$Integration = Join-Path $Root "deployment/integration.env"
$IntegrationParams = @{}; $SecretEnv = @{}
$cfg = python "$Root/deployment/integration_env.py" $Integration bicep | ConvertFrom-Json
foreach ($p in $cfg.params.PSObject.Properties) { $IntegrationParams[$p.Name] = $p.Value }
foreach ($p in $cfg.secretEnv.PSObject.Properties) { $SecretEnv[$p.Name] = $p.Value }
$Extra += @($cfg.extraEnv)
function Write-Params([bool] $WithBudget) {
    $doc = @{
        '$schema'      = "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#"
        contentVersion = "1.0.0.0"
        parameters     = @{
            image                = @{ value = $Image }
            frontendOrigin       = @{ value = $FrontendOrigin }
            adminToken           = @{ value = $AdminToken }
            developerPrincipalId = @{ value = "$Developer" }
            alertEmail           = @{ value = $AlertEmail }
            budgetAmount         = @{ value = $BudgetAmount }
            deployBudget         = @{ value = $WithBudget }
            extraEnv             = @{ value = $Extra }
            secretEnv            = @{ value = $SecretEnv }
        }
    }
    foreach ($k in $IntegrationParams.Keys) { $doc.parameters[$k] = @{ value = $IntegrationParams[$k] } }
    Write-Utf8 $ParamFile ($doc | ConvertTo-Json -Depth 8)
}

Step "Deploying Event Hubs, managed identity and Container Apps (3-6 minutes)"
Write-Params $true
$json = az deployment group create -g $ResourceGroup -n everyfan-backend -f "$Root/deployment/azure/main.bicep" `
    -p "@$ParamFile" --query properties.outputs -o json
if ($LASTEXITCODE -ne 0 -and $AlertEmail) {
    Write-Host "Deployment failed with the budget included; retrying without it (create the budget in the portal)." -ForegroundColor Yellow
    Write-Params $false
    $json = az deployment group create -g $ResourceGroup -n everyfan-backend -f "$Root/deployment/azure/main.bicep" `
        -p "@$ParamFile" --query properties.outputs -o json
}
Remove-Item $ParamFile -ErrorAction SilentlyContinue
if ($LASTEXITCODE -ne 0) { Fail "Deployment failed. See the error above and docs/DEPLOYMENT.md > Troubleshooting." }
$out = $json | ConvertFrom-Json
$Url = $out.apiUrl.value

Write-Utf8 "$Root/deployment/.admin-token" $AdminToken
$envText = @"
# Written by deploy.ps1. No secrets: auth uses ``az login`` (you have the Event Hubs Data Owner role).
STREAM_TRANSPORT=eventhubs
EVENT_HUB_NAMESPACE=$($out.eventHubNamespace.value)
EVENT_HUB_NAME=$($out.eventHubName.value)
API_URL=$Url
"@
Write-Utf8 "$Root/.env.azure" $envText

Step "Deployed"
Write-Host "API:            $Url"
Write-Host "API docs:       $Url/docs"
Write-Host "Event Hubs:     $($out.eventHubNamespace.value) / $($out.eventHubName.value)"
Write-Host "Admin token:    saved to deployment/.admin-token (never commit it)"
Write-Host "Local settings: .env.azure (copy into .env to use Event Hubs from your laptop)"

Step "Waiting for the app to become healthy"
$ok = $false
for ($i = 0; $i -lt 40; $i++) {
    try { $h = Invoke-RestMethod "$Url/api/health" -TimeoutSec 10; $ok = $true; break } catch { Start-Sleep 6 }
}
if (-not $ok) { Fail "No healthy response yet. Check: az containerapp logs show -n everyfan-api -g $ResourceGroup --tail 100" }
Write-Host "transport=$($h.transport) fallback=$($h.transport_fallback_reason)"
if ($h.transport_fallback_reason) {
    Write-Host "Event Hubs role assignments can take a few minutes to apply; the app re-checks every minute." -ForegroundColor Yellow
}

Step "Smoke test"
$McpKey = python "$Root/deployment/integration_env.py" $Integration get MCP_API_KEY
python -m backend.cli smoke --url $Url --origin ($FrontendOrigin.Split(",")[0]) --live --admin-token $AdminToken --mcp-key $McpKey
