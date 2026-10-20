// Deploy at the Tenant management group after the portal worker identity exists.
targetScope = 'managementGroup'

@description('System-assigned principal ID of the Cloud-in-a-Box queue worker.')
param workerPrincipalId string

resource subscriptionPlacementRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = {
  name: guid(managementGroup().id, 'CloudInABoxSubscriptionPlacement')
  properties: {
    roleName: 'Cloud-in-a-Box Tenant Subscription Placement'
    description: 'Allows the portal worker to associate newly created subscriptions with this tenant landing-zone management group.'
    type: 'CustomRole'
    permissions: [{
      actions: [
        'Microsoft.Management/managementGroups/read'
        // Subscription alias placement requires write access on the target
        // management group in addition to subscriptions/write.
        'Microsoft.Management/managementGroups/write'
        'Microsoft.Management/managementGroups/subscriptions/read'
        'Microsoft.Management/managementGroups/subscriptions/write'
      ]
      notActions: []
    }]
    assignableScopes: [managementGroup().id]
  }
}

resource subscriptionPlacementAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(managementGroup().id, workerPrincipalId, 'CloudInABoxTenantSubscriptionPlacement')
  properties: {
    roleDefinitionId: subscriptionPlacementRole.id
    principalId: workerPrincipalId
    principalType: 'ServicePrincipal'
  }
}
