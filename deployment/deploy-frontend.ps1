param(
    [Parameter(Mandatory = $true)][string]$Subscription,
    [ValidateSet('centralus','eastus2','westus2','westeurope','eastasia')]
    [string]$Location = 'westeurope',
    [string]$ResourceGroup = 'everyfan-frontend-rg',
    [string]$Name = 'everyfan-viewer'
)
$ErrorActionPreference = 'Stop'
$templatePath = Join-Path $PSScriptRoot 'azure/frontend.bicep'

# Check the named subscription; never change the operator's default subscription.
$policies = az policy assignment list --subscription $Subscription -o json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect target subscription policy.' }
foreach ($policy in $policies) {
    $allowed = $policy.parameters.listOfAllowedLocations.value
    if ($allowed -and $Location -notin $allowed) {
        throw "Region $Location is blocked by subscription policy $($policy.name). Choose a subscription that permits a Static Web Apps region."
    }
}
az group create --subscription $Subscription --name $ResourceGroup --location $Location --output none
if ($LASTEXITCODE -ne 0) { throw 'Resource group creation failed.' }
az deployment group create --subscription $Subscription --resource-group $ResourceGroup `
    --name everyfan-frontend --template-file $templatePath `
    --parameters "location=$Location" "name=$Name" --output none
if ($LASTEXITCODE -ne 0) { throw 'Frontend infrastructure deployment failed.' }
$hostname = az staticwebapp show --subscription $Subscription --resource-group $ResourceGroup `
    --name $Name --query defaultHostname -o tsv
if ($LASTEXITCODE -ne 0 -or -not $hostname) { throw 'Could not read frontend hostname.' }
Write-Output "Frontend origin: https://$hostname"
Write-Output 'Next: store the Azure deployment token in GitHub Actions secret AZURE_STATIC_WEB_APPS_API_TOKEN; add this origin to backend FRONTEND_ORIGIN; set repository variable FRONTEND_DEPLOY_ENABLED=true. The ci workflow deploys after both backend and frontend gates pass on main.'
