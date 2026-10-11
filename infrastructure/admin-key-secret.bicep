targetScope = 'resourceGroup'

param keyVaultName string

@secure()
param adminKey string

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource portalAdminKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'portal-admin-key'
  properties: {
    value: adminKey
    attributes: { enabled: true }
  }
}
