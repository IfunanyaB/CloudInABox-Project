targetScope = 'resourceGroup'

@description('All platform resources are constrained to the subscription-approved region.')
param location string = 'uksouth'

@description('Globally unique PostgreSQL server name.')
param postgresServerName string

@description('Globally unique Service Bus namespace name.')
param serviceBusNamespaceName string

@description('Globally unique Key Vault name.')
param keyVaultName string

@description('Password for the PostgreSQL administrator.')
@secure()
param databasePassword string

@description('One-time administrator portal key; also stored in Key Vault.')
@secure()
param adminKey string

@description('Current operator object ID; grants read access to the generated admin secret only.')
param operatorObjectId string

var platformTags = {
  Project: 'CloudInABox'
  TenantId: 'platform'
  Environment: 'dev'
  CostCentre: 'cloudinabox-platform'
  ManagedBy: 'bicep'
}
var suffix = uniqueString(subscription().id)
var lawName = 'law-cib-${take(suffix, 8)}'
var databaseName = 'cloudinabox'
var databaseLogin = 'cibadmin'
var queueName = 'tenant-provisioning'
var adminKeySecretName = 'portal-admin-key'
var vnetName = 'vnet-cib-platform'
var privateDnsZoneName = 'cib-private.postgres.database.azure.com'

resource platformVnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
}

resource databasePrivateDns 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: privateDnsZoneName
  location: 'global'
  tags: platformTags
}

resource databaseDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: databasePrivateDns
  name: 'link-cib-platform'
  location: 'global'
  tags: platformTags
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: platformVnet.id }
  }
}

resource workspace 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: lawName
  location: location
  tags: platformTags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2023-06-01-preview' = {
  name: postgresServerName
  location: location
  tags: platformTags
  sku: {
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    version: '16'
    administratorLogin: databaseLogin
    administratorLoginPassword: databasePassword
    storage: {
      storageSizeGB: 32
      autoGrow: 'Enabled'
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    network: {
      publicNetworkAccess: 'Disabled'
      delegatedSubnetResourceId: resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, 'snet-postgres')
      privateDnsZoneArmResourceId: databasePrivateDns.id
    }
    authConfig: {
      passwordAuth: 'Enabled'
      activeDirectoryAuth: 'Disabled'
    }
  }
  dependsOn: [platformVnet, databaseDnsLink]
}

resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2023-06-01-preview' = {
  parent: postgres
  name: databaseName
  tags: platformTags
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource serviceBus 'Microsoft.ServiceBus/namespaces@2022-10-01-preview' = {
  name: serviceBusNamespaceName
  location: location
  tags: platformTags
  sku: {
    name: 'Standard'
    tier: 'Standard'
    capacity: 0
  }
  properties: {
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
  }
}

resource queue 'Microsoft.ServiceBus/namespaces/queues@2022-10-01-preview' = {
  parent: serviceBus
  name: queueName
  tags: platformTags
  properties: {
    lockDuration: 'PT5M'
    maxDeliveryCount: 10
    deadLetteringOnMessageExpiration: true
    defaultMessageTimeToLive: 'P14D'
  }
}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  tags: platformTags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'
  }
}

resource adminKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: adminKeySecretName
  tags: platformTags
  properties: {
    value: adminKey
    attributes: { enabled: true }
  }
}

output postgresHost string = '${postgres.name}.postgres.database.azure.com'
output serviceBusNamespace string = serviceBus.name
output keyVaultName string = vault.name
output portalAdminKeySecret string = adminKeySecret.name

resource operatorSecretReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(adminKeySecret.id, operatorObjectId, 'portal-admin-key-reader')
  scope: adminKeySecret
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
    principalId: operatorObjectId
    principalType: 'User'
  }
}
