targetScope = 'resourceGroup'

@description('A Static Web Apps region permitted by the target subscription policy.')
@allowed(['centralus', 'eastus2', 'westus2', 'westeurope', 'eastasia'])
param location string = 'westeurope'

@description('Name of the public EveryFan viewer; no backend resources are modified.')
param name string = 'everyfan-viewer'

resource viewer 'Microsoft.Web/staticSites@2022-09-01' = {
  name: name
  location: location
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  properties: {
    provider: 'Other'
  }
  tags: {
    project: 'EveryFan'
    owner: 'D'
  }
}

output hostname string = viewer.properties.defaultHostname
output resourceId string = viewer.id
