// Grants the API's managed identity "Cosmos DB Built-in Data Contributor" on Owner B's account.
// Data-plane roles are Cosmos-specific (not Azure RBAC), so they need this sqlRoleAssignments resource.
targetScope = 'resourceGroup'

@description('Existing Cosmos DB for NoSQL account name.')
param accountName string

@description('Principal (object) ID of the API managed identity.')
param principalId string

var dataContributor = '00000000-0000-0000-0000-000000000002'

resource account 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' existing = {
  name: accountName
}

resource dataRole 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: account
  name: guid(account.id, principalId, dataContributor)
  properties: {
    roleDefinitionId: '${account.id}/sqlRoleDefinitions/${dataContributor}'
    principalId: principalId
    scope: account.id
  }
}
