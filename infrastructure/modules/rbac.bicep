// Tenant and platform RBAC assignments scoped to one tenant resource group.

targetScope = 'resourceGroup'

@description('Object ID of the platform team Entra ID group.')
param platformGroupObjectId string

@description('Object ID of the tenant team Entra ID group.')
param tenantGroupObjectId string

@description('Object ID of the GitHub Actions service principal deployed with OIDC.')
param githubActionsPrincipalObjectId string = ''

// Reader access for the platform team
resource platformReaderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(platformGroupObjectId)) {
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
resource tenantContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(tenantGroupObjectId)) {
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

resource githubActionsContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(githubActionsPrincipalObjectId)) {
  name: guid(resourceGroup().id, githubActionsPrincipalObjectId, 'GitHubActionsContributor')
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b24988ac-6180-42a0-ab88-20f7382dd24c')
    principalId: githubActionsPrincipalObjectId
    principalType: 'ServicePrincipal'
  }
}
