@description('Name of the tenant virtual network.')
param vnetName string

@description('Address range for the tenant spoke virtual network.')
param vnetAddressPrefix string

@description('Address range for the application subnet.')
param appSubnetPrefix string

@description('Address range for the data subnet.')
param dataSubnetPrefix string

@description('Address range for the management subnet.')
param managementSubnetPrefix string

@description('Azure region where the virtual network will be deployed.')
param location string

@description('Tags applied to the tenant network resources.')
param tags object

resource tenantVnet 'Microsoft.Network/virtualNetworks@2025-07-01' = {
  name: vnetName
  location: location
  tags: tags

  properties: {
    addressSpace: {
      addressPrefixes: [
        vnetAddressPrefix
      ]
    }

    subnets: [
      {
        name: 'snet-app'
        properties: {
          addressPrefix: appSubnetPrefix
        }
      }
      {
        name: 'snet-data'
        properties: {
          addressPrefix: dataSubnetPrefix
        }
      }
      {
        name: 'snet-management'
        properties: {
          addressPrefix: managementSubnetPrefix
        }
      }
    ]
  }
}

output vnetName string = tenantVnet.name
output vnetId string = tenantVnet.id
