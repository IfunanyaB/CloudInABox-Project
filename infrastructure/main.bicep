// Cloud-in-a-Box main tenant template

targetScope = 'subscription'

// Tenant configuration
@description('Unique identifier for the tenant.')
param tenantId string

@description('Environment being deployed.')
param environment string = 'dev'

@description('Azure region for the tenant resources.')
param location string = 'uksouth'

@description('Person or team responsible for the tenant.')
param owner string = 'platform-team'

@description('Monthly budget amount for the tenant.')
param monthlyBudgetAmount int = 50

@description('Email address for the budget notifications.')
param budgetContactEmail string

@description('Start date for the tenant monthly budget.')
param budgetStartDate string

@description('Address range allocated to this tenant spoke VNet.')
param tenantVnetAddressPrefix string = '10.10.0.0/16'

@description('Address range for the application subnet.')
param appSubnetPrefix string = '10.10.1.0/24'

@description('Address range for the data subnet.')
param dataSubnetPrefix string = '10.10.2.0/24'

@description('Address range for the management subnet.')
param managementSubnetPrefix string = '10.10.3.0/24'

@description('Resource ID for the shared, separately provisioned Cloud-in-a-Box hub VNet.')
param hubVnetId string = ''

@description('Subscription hosting the shared hub network.')
param hubSubscriptionId string = subscription().subscriptionId

@description('Resource group containing the shared hub VNet.')
param hubResourceGroupName string = 'rg-cib-hub'

@description('Name of the shared hub VNet.')
param hubVnetName string = 'vnet-cib-hub'

@description('Private IP address of the shared Azure Firewall; empty disables forced egress routing.')
param hubFirewallPrivateIp string = ''

@description('Whether the shared hub has a VPN gateway for transit.')
param hubVpnGatewayEnabled bool = false

// Common tags for tenant resources
var commonTags = {
  Project: 'CloudInABox'
  TenantId: tenantId
  Environment: environment
  Owner: owner
  CostCentre: tenantId
  ManagedBy: 'bicep'
  DataClassification: 'Internal'
  Region: location
}

// Resource group for tenant networking
resource networkResourceGroup 'Microsoft.Resources/resourceGroups@2025-04-01' = {
  name: 'rg-${tenantId}-network'
  location: location
  tags: commonTags
}

// Deploy the tenant networking
module tenantNetworking './modules/networking.bicep' = {
  name: 'tenant-networking-${tenantId}'
  scope: networkResourceGroup

  params: {
    vnetName: 'vnet-${tenantId}'
    vnetAddressPrefix: tenantVnetAddressPrefix
    appSubnetPrefix: appSubnetPrefix
    dataSubnetPrefix: dataSubnetPrefix
    managementSubnetPrefix: managementSubnetPrefix
    hubVnetId: hubVnetId
    firewallPrivateIp: hubFirewallPrivateIp
    hubVpnGatewayEnabled: hubVpnGatewayEnabled
    location: location
    tags: commonTags
  }
}

// Create the tenant resource groups
module tenantResources './modules/tenant.bicep' = {
  name: 'tenant-resources-${tenantId}'

  params: {
    tenantId: tenantId
    location: location
    tags: commonTags
  }
}
// Deploy tenant monitoring
module tenantMonitoring './modules/monitoring.bicep' = {
  name: 'tenant-monitoring-${tenantId}'
  scope: resourceGroup('rg-${tenantId}-monitoring')

  params: {
    workspaceName: 'law-${tenantId}'
    location: location
    retentionInDays: 30
    tags: commonTags
  }

  dependsOn: [
    tenantResources
  ]
}

// In the shared-subscription model, tenant controls are scoped to the tenant's
// resource groups so one tenant's tags/policies cannot affect another tenant.
module networkGovernance './modules/governance.bicep' = {
  name: 'tenant-network-governance-${tenantId}'
  scope: networkResourceGroup
  params: { tenantId: tenantId, environment: environment }
}

module appGovernance './modules/governance.bicep' = {
  name: 'tenant-app-governance-${tenantId}'
  scope: resourceGroup('rg-${tenantId}-app')
  params: { tenantId: tenantId, environment: environment }
  dependsOn: [tenantResources]
}

module dataGovernance './modules/governance.bicep' = {
  name: 'tenant-data-governance-${tenantId}'
  scope: resourceGroup('rg-${tenantId}-data')
  params: { tenantId: tenantId, environment: environment }
  dependsOn: [tenantResources]
}

module monitoringGovernance './modules/governance.bicep' = {
  name: 'tenant-monitoring-governance-${tenantId}'
  scope: resourceGroup('rg-${tenantId}-monitoring')
  params: { tenantId: tenantId, environment: environment }
  dependsOn: [tenantResources]
}



// Deployment outputs
output tenantIdOutput string = tenantId
output networkResourceGroupName string = networkResourceGroup.name
output tenantVnetId string = tenantNetworking.outputs.vnetId


// Configure tenant budget and FinOps controls
module tenantFinOps './modules/finops.bicep' = {
  name: 'tenant-finops-${tenantId}'

  params: {
    tenantId: tenantId
    monthlyBudgetAmount: monthlyBudgetAmount
    budgetContactEmail: budgetContactEmail
    budgetStartDate: budgetStartDate
    resourceGroupNames: [
      'rg-${tenantId}-network'
      'rg-${tenantId}-app'
      'rg-${tenantId}-data'
      'rg-${tenantId}-monitoring'
    ]
  }
}

module hubSidePeering './modules/hub-peering.bicep' = if (!empty(hubVnetId)) {
  name: 'tenant-hub-peering-${tenantId}'
  scope: resourceGroup(hubSubscriptionId, hubResourceGroupName)
  params: {
    hubVnetName: hubVnetName
    spokeVnetId: tenantNetworking.outputs.vnetId
    tenantId: tenantId
    vpnGatewayEnabled: hubVpnGatewayEnabled
  }
}
