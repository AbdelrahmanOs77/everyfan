// EveryFan backend infrastructure (Owner A).
// Deploys into ONE resource group, in a region your Azure for Students subscription allows:
//   Log Analytics (capped) -> Container Apps environment
//   User-assigned managed identity
//   Event Hubs namespace (Basic) + hub "match-events"
//   Role assignments: identity = Data Sender + Data Receiver; optional developer = Data Owner
//   Container App (0.5 vCPU / 1 GiB, always 1 replica so WebSockets never cold-start)
//   Optional monthly budget with e-mail alerts
// Other owners' settings (Foundry, Cosmos DB, App Insights) are passed through `extraEnv`.

targetScope = 'resourceGroup'

@description('Region. Must be one of the "Allowed locations" of your subscription policy.')
param location string = resourceGroup().location

@description('Short lowercase prefix for every resource name.')
@minLength(3)
@maxLength(12)
param prefix string = 'everyfan'

@description('Container image, e.g. ghcr.io/<owner>/<repo>-backend:latest (package must be public).')
param image string

@description('Comma-separated frontend origins allowed by CORS (your Static Web App URL).')
param frontendOrigin string = 'http://localhost:5173'

@description('Admin token for the API (X-Admin-Token). Keep it secret.')
@secure()
param adminToken string

@description('Object ID of a developer who may use Event Hubs from a laptop with `az login` (optional).')
param developerPrincipalId string = ''

@description('Broadcast delay in real seconds between ingest and what viewers see.')
param broadcastDelaySeconds string = '6'

@description('Daily model-token cap for live mode (0 disables live AI; the cached demo always works).')
param dailyTokenCap string = '200000'

@description('Comma-separated pipeline plugins (module:function).')
param pipelinePlugins string = 'backend.api.template_plugin:register'

@description('Extra environment variables for other owners, e.g. [{ name: \'FOUNDRY_PROJECT_ENDPOINT\', value: \'...\' }].')
param extraEnv array = []

@description('Create a monthly budget with e-mail alerts at 50% / 80% / 100% (forecast).')
param deployBudget bool = true

@description('Monthly budget amount in the billing currency.')
param budgetAmount int = 40

@description('E-mail for budget alerts.')
param alertEmail string = ''

@description('First day of the current month (budgets must start on the 1st).')
param budgetStartDate string = utcNow('yyyy-MM-01')

var suffix = uniqueString(resourceGroup().id)
var ehNamespaceName = '${prefix}-eh-${suffix}'
var hubName = 'match-events'
var roles = {
  eventHubsDataOwner: 'f526a384-b230-433a-b45c-95f59c4a2dec'
  eventHubsDataReceiver: 'a638d3c7-ab3a-418d-83e6-5f17a39d4fde'
  eventHubsDataSender: '2b629674-e913-4c01-ae53-ef4638d8f975'
}

// ---------------------------------------------------------------- observability

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${prefix}-logs-${suffix}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: json('0.1') } // hard cap on log ingestion cost
  }
}

// ---------------------------------------------------------------- identity

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${prefix}-api-identity'
  location: location
}

// ---------------------------------------------------------------- Event Hubs

resource eventHubs 'Microsoft.EventHub/namespaces@2024-01-01' = {
  name: ehNamespaceName
  location: location
  sku: { name: 'Basic', tier: 'Basic', capacity: 1 }
  properties: {
    minimumTlsVersion: '1.2'
    disableLocalAuth: false // keeps the connection-string option for a first laptop test
  }
}

resource hub 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = {
  parent: eventHubs
  name: hubName
  properties: {
    partitionCount: 2
    messageRetentionInDays: 1
  }
}

resource apiSends 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(eventHubs.id, identity.id, roles.eventHubsDataSender)
  scope: eventHubs
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.eventHubsDataSender)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource apiReceives 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(eventHubs.id, identity.id, roles.eventHubsDataReceiver)
  scope: eventHubs
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.eventHubsDataReceiver)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource developerOwns 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(developerPrincipalId)) {
  name: guid(eventHubs.id, developerPrincipalId, roles.eventHubsDataOwner)
  scope: eventHubs
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.eventHubsDataOwner)
    principalId: developerPrincipalId
    principalType: 'User'
  }
}

// ---------------------------------------------------------------- Container Apps

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${prefix}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

var baseEnv = [
  { name: 'STREAM_TRANSPORT', value: 'eventhubs' }
  { name: 'EVENT_HUB_NAMESPACE', value: '${ehNamespaceName}.servicebus.windows.net' }
  { name: 'EVENT_HUB_NAME', value: hubName }
  { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
  { name: 'FRONTEND_ORIGIN', value: frontendOrigin }
  { name: 'BROADCAST_DELAY_S', value: broadcastDelaySeconds }
  { name: 'LIVE_MODE_DAILY_TOKEN_CAP', value: dailyTokenCap }
  { name: 'PIPELINE_PLUGINS', value: pipelinePlugins }
  { name: 'ADMIN_TOKEN', secretRef: 'admin-token' }
  { name: 'APP_VERSION', value: last(split(image, ':')) }
]

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${prefix}-api'
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto' // HTTP/1.1 upgrade -> WebSockets work
        allowInsecure: false
        traffic: [ { latestRevision: true, weight: 100 } ]
      }
      secrets: [ { name: 'admin-token', value: adminToken } ]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: image
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: concat(baseEnv, extraEnv)
          probes: [
            {
              type: 'Startup'
              httpGet: { path: '/api/health', port: 8000 }
              periodSeconds: 3
              failureThreshold: 30
            }
            {
              type: 'Liveness'
              httpGet: { path: '/api/health', port: 8000 }
              periodSeconds: 30
              failureThreshold: 3
            }
            {
              type: 'Readiness'
              httpGet: { path: '/api/health', port: 8000 }
              periodSeconds: 10
              failureThreshold: 3
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1 // never scale to zero: live WebSockets and the replay live in memory
        maxReplicas: 1 // one replica by design (in-memory broadcast state)
      }
    }
  }
  dependsOn: [ apiSends, apiReceives ]
}

// ---------------------------------------------------------------- budget

resource budget 'Microsoft.Consumption/budgets@2023-11-01' = if (deployBudget && !empty(alertEmail)) {
  name: '${prefix}-monthly-budget'
  properties: {
    category: 'Cost'
    amount: budgetAmount
    timeGrain: 'Monthly'
    timePeriod: { startDate: budgetStartDate }
    notifications: {
      actual50: { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 50, thresholdType: 'Actual', contactEmails: [ alertEmail ] }
      actual80: { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 80, thresholdType: 'Actual', contactEmails: [ alertEmail ] }
      forecast100: { enabled: true, operator: 'GreaterThanOrEqualTo', threshold: 100, thresholdType: 'Forecasted', contactEmails: [ alertEmail ] }
    }
  }
}

// ---------------------------------------------------------------- outputs

output apiUrl string = 'https://${api.properties.configuration.ingress.fqdn}'
output eventHubNamespace string = '${ehNamespaceName}.servicebus.windows.net'
output eventHubName string = hubName
output identityClientId string = identity.properties.clientId
output containerAppName string = api.name
output logAnalyticsWorkspace string = logs.name
