targetScope = 'resourceGroup'

@description('Name of the existing Cloud-in-a-Box hub VNet.')
param hubVnetName string

@description('Tenant VNet resource ID.')
param spokeVnetId string

@description('Unique tenant ID used to name the hub-side peering.')
param tenantId string

@description('Whether the shared hub provides VPN gateway transit.')
param vpnGatewayEnabled bool = false

resource hubVnet 'Microsoft.Network/virtualNetworks@2025-07-01' existing = {
  name: hubVnetName
}

resource hubToSpokePeering 'Microsoft.Network/virtualNetworks/virtualNetworkPeerings@2025-07-01' = {
  parent: hubVnet
  name: 'to-${tenantId}'
  properties: {
    remoteVirtualNetwork: { id: spokeVnetId }
    allowVirtualNetworkAccess: true
    allowForwardedTraffic: true
    allowGatewayTransit: vpnGatewayEnabled
    useRemoteGateways: false
  }
}

output peeringId string = hubToSpokePeering.id
