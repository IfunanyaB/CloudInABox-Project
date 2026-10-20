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

@description('Resource ID of the shared hub VNet. Leave empty only for legacy single-subscription deployments.')
param hubVnetId string = ''

@description('Private IP address of the shared Azure Firewall. When set, application subnet egress uses it.')
param firewallPrivateIp string = ''

@description('Whether the shared hub exposes a VPN gateway for spoke transit.')
param hubVpnGatewayEnabled bool = false

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
          routeTable: { id: tenantRouteTable.id }
          delegations: [{
            name: 'container-apps'
            properties: { serviceName: 'Microsoft.App/environments' }
          }]
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

resource tenantRouteTable 'Microsoft.Network/routeTables@2024-05-01' = {
  name: 'rt-${take(vnetName, 55)}'
  location: location
  tags: tags
  properties: {
    disableBgpRoutePropagation: false
    routes: empty(firewallPrivateIp) ? [] : [{
        name: 'default-through-hub-firewall'
        properties: {
          addressPrefix: '0.0.0.0/0'
          nextHopType: 'VirtualAppliance'
          nextHopIpAddress: firewallPrivateIp
        }
      }]
  }
}

resource spokeToHubPeering 'Microsoft.Network/virtualNetworks/virtualNetworkPeerings@2025-07-01' = if (!empty(hubVnetId)) {
  parent: tenantVnet
  name: 'to-cib-hub'
  properties: {
    remoteVirtualNetwork: { id: hubVnetId }
    allowVirtualNetworkAccess: true
    allowForwardedTraffic: true
    allowGatewayTransit: false
    useRemoteGateways: hubVpnGatewayEnabled
  }
}

output vnetName string = tenantVnet.name
output vnetId string = tenantVnet.id
output appSubnetId string = '${tenantVnet.id}/subnets/snet-app'
