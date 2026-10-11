//Tenant RBAC Assignments

targetScope = 'resourceGroup'

@description('Object ID of the platform team Entra ID group')
param platformGroupObjectId string

@description('Object ID of the tenant team Entra ID group.')
param tenantGroupObjectId string

// Reader access for the platform team
resource platformReaderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, platformGroupObjectId, 'Reader')
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'acdd72a7-3385-48ef-bd42-f606fba81ae7'
    )
    principalId: platformGroupObjectId
    principalType: 'Group'
  }
}

// Contributor access for the tenant team
resource tenantContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, tenantGroupObjectId, 'Contributor')
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'b24988ac-6180-42a0-ab88-20f7382dd24c'
    )
    principalId: tenantGroupObjectId
    principalType: 'Group'
  }
}


output platformRoleAssignmentId string = platformReaderRole.id
output tenantRoleAssignmentId string = tenantContributorRole.id
