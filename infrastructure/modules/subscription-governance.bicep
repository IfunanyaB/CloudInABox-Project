targetScope = 'subscription'

@description('Unique tenant identifier required on tenant resources.')
param tenantId string

@description('Environment tag required on tenant resources.')
param environment string

resource tenantIdTagPolicy 'Microsoft.Authorization/policyAssignments@2024-04-01' = {
  name: 'cib-required-tenant-id'
  properties: {
    displayName: 'Cloud-in-a-Box: Required TenantId Tag'
    description: 'Requires the assigned tenant identifier on resources.'
    policyDefinitionId: '/providers/Microsoft.Authorization/policyDefinitions/1e30110a-5ceb-460c-a204-c1c3969c6d62'
    notScopes: [subscriptionResourceId('Microsoft.Consumption/budgets', 'budget-${tenantId}')]
    parameters: { tagName: { value: 'TenantId' }, tagValue: { value: tenantId } }
  }
}

resource environmentTagPolicy 'Microsoft.Authorization/policyAssignments@2024-04-01' = {
  name: 'cib-required-environment'
  properties: {
    displayName: 'Cloud-in-a-Box: Required Environment Tag'
    description: 'Requires the assigned environment tag on resources.'
    policyDefinitionId: '/providers/Microsoft.Authorization/policyDefinitions/1e30110a-5ceb-460c-a204-c1c3969c6d62'
    notScopes: [subscriptionResourceId('Microsoft.Consumption/budgets', 'budget-${tenantId}')]
    parameters: { tagName: { value: 'Environment' }, tagValue: { value: environment } }
  }
}

resource noPublicIpDefinition 'Microsoft.Authorization/policyDefinitions@2023-04-01' = {
  name: 'cib-deny-public-ip-resources'
  properties: {
    policyType: 'Custom'
    mode: 'All'
    displayName: 'Cloud-in-a-Box: Deny Public IP Resources'
    description: 'Blocks creation of standalone Azure Public IP resources in tenant subscriptions.'
    metadata: { category: 'Cloud-in-a-Box Security', version: '1.0.0' }
    policyRule: {
      if: { field: 'type', equals: 'Microsoft.Network/publicIPAddresses' }
      then: { effect: 'Deny' }
    }
  }
}

resource noPublicIpAssignment 'Microsoft.Authorization/policyAssignments@2024-04-01' = {
  name: 'cib-deny-public-ip'
  properties: {
    displayName: 'Cloud-in-a-Box: Deny Public IP Resources'
    description: 'Tenant workloads must use approved ingress and egress paths.'
    policyDefinitionId: noPublicIpDefinition.id
  }
}

output policyAssignmentIds array = [
  tenantIdTagPolicy.id
  environmentTagPolicy.id
  noPublicIpAssignment.id
]
