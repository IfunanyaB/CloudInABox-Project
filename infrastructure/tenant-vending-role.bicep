targetScope = 'subscription'

@description('System-assigned identity of the isolated queue worker.')
param workerPrincipalId string

@description('Stable worker resource name used for deterministic role assignment IDs.')
param workerName string

resource vendingOperatorRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = {
  name: guid(subscription().id, 'CloudInABoxTenantVending')
  properties: {
    roleName: 'Cloud-in-a-Box Tenant Vending Operator'
    description: 'Read-only access to the platform subscription context. Tenant deployments run with the worker as owner of each separately vended subscription; shared-hub peering permissions are scoped to the hub resource group.'
    type: 'CustomRole'
    permissions: [{
      actions: ['Microsoft.Resources/subscriptions/read']
      notActions: []
    }]
    assignableScopes: [subscription().id]
  }
}

resource vendingWorkerRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(subscription().id, workerName, 'CloudInABoxTenantVendingAssignment')
  properties: {
    roleDefinitionId: vendingOperatorRole.id
    principalId: workerPrincipalId
    principalType: 'ServicePrincipal'
  }
}
