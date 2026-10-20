// Deploy the sample SaaS container into the tenant's app resource group.
targetScope = 'subscription'

@description('Tenant identifier used for resource names and tags.')
param tenantId string
@description('Tenant approved Azure region.')
param location string = 'uksouth'
@description('Public GHCR image produced by the repository workflow.')
param image string

resource appRg 'Microsoft.Resources/resourceGroups@2022-09-01' existing = {
  name: 'rg-${tenantId}-app'
}

module app './app.bicep' = {
  name: 'sample-saas-${tenantId}'
  scope: appRg
  params: {
    tenantId: tenantId
    location: location
    image: image
  }
}

output applicationUrl string = app.outputs.applicationUrl
output applicationResourceId string = app.outputs.applicationResourceId
