targetScope = 'resourceGroup'

param location string = 'uksouth'
param codeStorageName string

var tags = {
  Project: 'CloudInABox'
  TenantId: 'platform'
  Environment: 'dev'
  CostCentre: 'cloudinabox-platform'
  ManagedBy: 'bicep'
}
var envName = 'cae-cib-${take(uniqueString(subscription().id), 8)}'

resource codeStorage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: codeStorageName
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: true
    publicNetworkAccess: 'Enabled'
  }
}
resource fileService 'Microsoft.Storage/storageAccounts/fileServices@2023-05-01' existing = {
  parent: codeStorage
  name: 'default'
}
resource codeShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = {
  parent: fileService
  name: 'portal-code'
  properties: { shareQuota: 5, enabledProtocols: 'SMB' }
}
resource env 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: envName
}
resource envStorage 'Microsoft.App/managedEnvironments/storages@2024-08-02-preview' = {
  parent: env
  name: 'cloudinabox-source'
  properties: {
    azureFile: {
      accountName: codeStorage.name
      accountKey: codeStorage.listKeys().keys[0].value
      shareName: codeShare.name
      accessMode: 'ReadOnly'
    }
  }
}
