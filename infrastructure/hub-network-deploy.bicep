// Creates the shared hub resource group and deploys its network resources.
targetScope = 'subscription'

@description('Resource group dedicated to shared hub networking.')
param resourceGroupName string = 'rg-cib-hub'
@description('Approved Azure deployment region.')
param location string = 'uksouth'
@description('Hub address range. Check for overlap with connected networks.')
param hubAddressPrefix string = '10.255.0.0/16'
@description('Enable Azure Firewall; this adds ongoing charges.')
param deployFirewall bool = false
@description('Enable VPN Gateway; this adds ongoing charges.')
param deployVpnGateway bool = false
@description('Platform Log Analytics workspace resource ID for firewall diagnostics.')
param logAnalyticsWorkspaceId string = ''
@description('Portal worker system-assigned identity to grant hub Network Contributor.')
param tenantVendingPrincipalId string = ''

var tags = {
  Project: 'CloudInABox'
  TenantId: 'platform'
  Environment: 'dev'
  CostCentre: 'cloudinabox-platform'
  ManagedBy: 'bicep'
}

resource hubRg 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

module hub './hub-network.bicep' = {
  name: 'cloudinabox-shared-hub'
  scope: hubRg
  params: {
    location: location
    hubAddressPrefix: hubAddressPrefix
    deployFirewall: deployFirewall
    deployVpnGateway: deployVpnGateway
    logAnalyticsWorkspaceId: logAnalyticsWorkspaceId
    tenantVendingPrincipalId: tenantVendingPrincipalId
  }
}

output hubVirtualNetworkId string = hub.outputs.hubVirtualNetworkId
output firewallPrivateIp string = hub.outputs.firewallPrivateIp
output firewallId string = hub.outputs.firewallId
output vpnGatewayId string = hub.outputs.vpnGatewayId
