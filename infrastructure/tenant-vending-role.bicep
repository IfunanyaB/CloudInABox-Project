targetScope = 'subscription'

@description('System-assigned identity of the tenant provisioning queue worker.')
param workerPrincipalId string

@description('Stable worker resource name used for deterministic role assignment IDs.')
param workerName string

resource vendingOperatorRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = {
  name: guid(subscription().id, 'CloudInABoxTenantVending')
  properties: {
    roleName: 'Cloud-in-a-Box Tenant Vending Operator'
    description: 'Allows the worker to deploy and remove tenant resource groups, VNets, route tables, workspaces, scoped policies, and tenant budgets, and read tenant inventory, metrics, costs, and workspace logs. It does not grant Azure role-assignment permissions.'
    type: 'CustomRole'
    permissions: [{
      actions: [
        'Microsoft.Resources/subscriptions/read'
        'Microsoft.Resources/subscriptions/locations/read'
        'Microsoft.Resources/subscriptions/providers/read'
        'Microsoft.Resources/subscriptions/resourceGroups/resources/read'
        'Microsoft.Resources/deployments/*'
        'Microsoft.Resources/subscriptions/resourceGroups/read'
        'Microsoft.Resources/subscriptions/resourceGroups/write'
        'Microsoft.Resources/subscriptions/resourceGroups/delete'
        'Microsoft.Network/virtualNetworks/read'
        'Microsoft.Network/virtualNetworks/write'
        'Microsoft.Network/virtualNetworks/delete'
        'Microsoft.Network/virtualNetworks/virtualNetworkPeerings/read'
        'Microsoft.Network/virtualNetworks/virtualNetworkPeerings/write'
        'Microsoft.Network/virtualNetworks/virtualNetworkPeerings/delete'
        'Microsoft.Network/routeTables/read'
        'Microsoft.Network/routeTables/write'
        'Microsoft.Network/routeTables/delete'
        'Microsoft.Network/routeTables/join/action'
        'Microsoft.OperationalInsights/workspaces/read'
        'Microsoft.OperationalInsights/workspaces/query/*/read'
        'Microsoft.OperationalInsights/workspaces/query/read'
        'Microsoft.OperationalInsights/workspaces/write'
        'Microsoft.OperationalInsights/workspaces/delete'
        'Microsoft.Authorization/policyAssignments/read'
        'Microsoft.Authorization/policyAssignments/write'
        'Microsoft.Authorization/policyAssignments/delete'
        'Microsoft.Consumption/budgets/read'
        'Microsoft.Consumption/budgets/write'
        'Microsoft.Consumption/budgets/delete'
        'Microsoft.CostManagement/query/read'
        'Microsoft.CostManagement/query/action'
        'Microsoft.Insights/metrics/read'
        'Microsoft.Insights/metricDefinitions/read'
      ]
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
