// Shared hub resources deployed inside the dedicated hub resource group.
targetScope = 'resourceGroup'

@description('Approved Azure deployment region.')
param location string = resourceGroup().location

@description('The hub range is outside the current legacy tenant range and new 10.30/16–10.254/16 spoke pool.')
param hubAddressPrefix string = '10.255.0.0/16'

@description('Enable the Azure Firewall. The service has hourly and traffic charges.')
param deployFirewall bool = false

@description('Enable the VPN Gateway. It has hourly and connection-related charges.')
param deployVpnGateway bool = false

@description('Existing platform Log Analytics workspace resource ID for hub diagnostics.')
param logAnalyticsWorkspaceId string = ''

@description('System-assigned identity of the portal provisioning worker, granted Network Contributor on the hub resource group.')
param tenantVendingPrincipalId string = ''

var tags = {
  Project: 'CloudInABox'
  TenantId: 'platform'
  Environment: 'dev'
  CostCentre: 'cloudinabox-platform'
  ManagedBy: 'bicep'
}

resource hubVnet 'Microsoft.Network/virtualNetworks@2025-07-01' = {
  name: 'vnet-cib-hub'
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: [hubAddressPrefix] }
    subnets: [
      { name: 'AzureFirewallSubnet', properties: { addressPrefix: cidrSubnet(hubAddressPrefix, 26, 0) } }
      { name: 'GatewaySubnet', properties: { addressPrefix: cidrSubnet(hubAddressPrefix, 27, 32) } }
      { name: 'snet-shared-services', properties: { addressPrefix: cidrSubnet(hubAddressPrefix, 24, 2) } }
    ]
  }
}

resource firewallPublicIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = if (deployFirewall) {
  name: 'pip-cib-hub-firewall'
  location: location
  tags: tags
  sku: { name: 'Standard' }
  properties: { publicIPAllocationMethod: 'Static' }
}

resource firewallPolicy 'Microsoft.Network/firewallPolicies@2023-09-01' = if (deployFirewall) {
  name: 'afwp-cib-hub'
  location: location
  tags: tags
  properties: {
    sku: { tier: 'Basic' }
    threatIntelMode: 'Alert'
  }
}

resource firewallRules 'Microsoft.Network/firewallPolicies/ruleCollectionGroups@2023-09-01' = if (deployFirewall) {
  parent: firewallPolicy
  name: 'tenant-egress'
  properties: {
    priority: 100
    ruleCollections: [
      {
        ruleCollectionType: 'FirewallPolicyFilterRuleCollection'
        name: 'tenant-egress-allow'
        priority: 100
        action: { type: 'Allow' }
        rules: [
          {
            ruleType: 'NetworkRule'
            name: 'tenant-dns'
            ipProtocols: ['UDP', 'TCP']
            sourceAddresses: ['10.0.0.0/8']
            destinationAddresses: ['*']
            destinationPorts: ['53']
          }
          {
            ruleType: 'NetworkRule'
            name: 'tenant-https'
            ipProtocols: ['TCP']
            sourceAddresses: ['10.0.0.0/8']
            destinationAddresses: ['*']
            destinationPorts: ['443']
          }
        ]
      }
    ]
  }
}

resource azureFirewall 'Microsoft.Network/azureFirewalls@2024-05-01' = if (deployFirewall) {
  name: 'afw-cib-hub'
  location: location
  tags: tags
  properties: {
    sku: { name: 'AZFW_VNet', tier: 'Basic' }
    firewallPolicy: { id: firewallPolicy!.id }
    ipConfigurations: [
      {
        name: 'configuration'
        properties: {
          subnet: { id: '${hubVnet.id}/subnets/AzureFirewallSubnet' }
          publicIPAddress: { id: firewallPublicIp!.id }
        }
      }
    ]
  }
  dependsOn: [firewallRules]
}

resource vpnPublicIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = if (deployVpnGateway) {
  name: 'pip-cib-hub-vpn'
  location: location
  tags: tags
  sku: { name: 'Standard' }
  properties: { publicIPAllocationMethod: 'Static' }
}

resource vpnGateway 'Microsoft.Network/virtualNetworkGateways@2024-05-01' = if (deployVpnGateway) {
  name: 'vpngw-cib-hub'
  location: location
  tags: tags
  properties: {
    gatewayType: 'Vpn'
    vpnType: 'RouteBased'
    enableBgp: false
    activeActive: false
    sku: { name: 'VpnGw1', tier: 'VpnGw1' }
    ipConfigurations: [
      {
        name: 'gateway-ip'
        properties: {
          privateIPAllocationMethod: 'Dynamic'
          subnet: { id: '${hubVnet.id}/subnets/GatewaySubnet' }
          publicIPAddress: { id: vpnPublicIp!.id }
        }
      }
    ]
  }
}

resource workerHubNetworkAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(tenantVendingPrincipalId)) {
  name: guid(resourceGroup().id, tenantVendingPrincipalId, 'NetworkContributor')
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4d97b98b-1d4f-4787-a291-c67834d212e7')
    principalId: tenantVendingPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource hubDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (deployFirewall && !empty(logAnalyticsWorkspaceId)) {
  scope: azureFirewall!
  name: 'send-to-cib-platform-workspace'
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [
      { category: 'AzureFirewallApplicationRule', enabled: true }
      { category: 'AzureFirewallNetworkRule', enabled: true }
      { category: 'AzureFirewallDnsProxy', enabled: true }
    ]
    metrics: [{ category: 'AllMetrics', enabled: true }]
  }
}

output hubVirtualNetworkId string = hubVnet.id
output hubResourceGroupName string = resourceGroup().name
output firewallPrivateIp string = deployFirewall ? azureFirewall!.properties.ipConfigurations[0].properties.privateIPAddress : ''
output firewallId string = deployFirewall ? azureFirewall!.id : ''
output vpnGatewayId string = deployVpnGateway ? vpnGateway!.id : ''
