<#
.SYNOPSIS
  Roll the running Container App to a new image (published by the "image" GitHub workflow), then smoke test.
.EXAMPLE
  ./deployment/update-image.ps1 -Image ghcr.io/<owner>/<repo>-backend:3f2a9c1e5b7d
#>
param(
    [Parameter(Mandatory = $true)] [string] $Image,
    [string] $ResourceGroup = "rg-everyfan-hackathon",
    [string] $App = "everyfan-api"
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
az containerapp update -n $App -g $ResourceGroup --image $Image --set-env-vars "APP_VERSION=$($Image.Split(':')[-1])" -o none
if ($LASTEXITCODE -ne 0) { Write-Host "Update failed" -ForegroundColor Red; exit 1 }
$Url = "https://" + (az containerapp show -n $App -g $ResourceGroup --query properties.configuration.ingress.fqdn -o tsv)
Write-Host "Rolled to $Image. Waiting for the new revision..."
Start-Sleep 25
$Token = Get-Content "$Root/deployment/.admin-token" -ErrorAction SilentlyContinue
if ($Token) { python -m backend.cli smoke --url $Url --live --admin-token $Token } else { python -m backend.cli smoke --url $Url }
