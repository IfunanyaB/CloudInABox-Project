targetScope = 'subscription'

@description('Dedicated hosting resource group, separate from tenant resource groups.')
param platformResourceGroupName string = 'rg-cloudinabox-platform'

@description('The subscription policy currently permits UK South and the Development tag only.')
param location string = 'uksouth'

@description('Globally unique PostgreSQL server name.')
param postgresServerName string

@description('Globally unique Service Bus namespace name.')
param serviceBusNamespaceName string

@description('Globally unique Key Vault name.')
param keyVaultName string

@description('PostgreSQL administrator password.')
@secure()
param databasePassword string

@description('Random portal administrator key stored in Key Vault and the API container secret.')
@secure()
param adminKey string

@description('Current operator object ID, granted read access to the single portal administrator secret.')
param operatorObjectId string

var platformTags = {
  Project: 'CloudInABox'
  TenantId: 'platform'
  Environment: 'dev'
  CostCentre: 'cloudinabox-platform'
  ManagedBy: 'bicep'
}

resource platformRg 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: platformResourceGroupName
  location: location
  tags: platformTags
}

module platform './platform-resources.bicep' = {
  name: 'cloudinabox-platform-resources'
  scope: platformRg
  params: {
    location: location
    postgresServerName: postgresServerName
    serviceBusNamespaceName: serviceBusNamespaceName
    keyVaultName: keyVaultName
    databasePassword: databasePassword
    adminKey: adminKey
    operatorObjectId: operatorObjectId
  }
}

output platformResourceGroup string = platformRg.name
output postgresHost string = platform.outputs.postgresHost
output serviceBusNamespace string = platform.outputs.serviceBusNamespace
output keyVaultName string = platform.outputs.keyVaultName
output portalAdminKeySecret string = platform.outputs.portalAdminKeySecret
