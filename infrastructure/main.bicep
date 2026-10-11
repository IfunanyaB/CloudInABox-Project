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

@description('Object ID of the platform team entra ID group.')
param platformGroupObjectId string = ''

@description('Object ID of the tenant team Entra ID group.')
param tenantGroupObjectId string = ''

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



// Apply tenant governance policies
module networkGovernance './modules/governance.bicep' = {
  name: 'tenant-governance-${tenantId}-network'
  scope: networkResourceGroup
  params: {
    allowedLocations: [
      location
    ]
    tenantId: tenantId
    environment: environment
  }
}

module appGovernance './modules/governance.bicep' = {
  name: 'tenant-governance-${tenantId}-app'
  scope: resourceGroup('rg-${tenantId}-app')
  params: {
    allowedLocations: [location]
    tenantId: tenantId
    environment: environment
  }
  dependsOn: [tenantResources]
}

module dataGovernance './modules/governance.bicep' = {
  name: 'tenant-governance-${tenantId}-data'
  scope: resourceGroup('rg-${tenantId}-data')
  params: {
    allowedLocations: [location]
    tenantId: tenantId
    environment: environment
  }
  dependsOn: [tenantResources]
}

module monitoringGovernance './modules/governance.bicep' = {
  name: 'tenant-governance-${tenantId}-monitoring'
  scope: resourceGroup('rg-${tenantId}-monitoring')
  params: {
    allowedLocations: [location]
    tenantId: tenantId
    environment: environment
  }
  dependsOn: [tenantResources]
}

// Deployment outputs
output tenantIdOutput string = tenantId
output networkResourceGroupName string = networkResourceGroup.name

// Apply tenant RBAC when group IDs are provided
module tenantRbacApp './modules/rbac.bicep' = if (!empty(platformGroupObjectId) && !empty(tenantGroupObjectId)) {
  name: 'tenant-rbac-${tenantId}-app'
  scope: resourceGroup('rg-${tenantId}-app')
  params: {
    platformGroupObjectId: platformGroupObjectId
    tenantGroupObjectId: tenantGroupObjectId
  }
  dependsOn: [tenantResources]
}

module tenantRbacData './modules/rbac.bicep' = if (!empty(platformGroupObjectId) && !empty(tenantGroupObjectId)) {
  name: 'tenant-rbac-${tenantId}-data'
  scope: resourceGroup('rg-${tenantId}-data')
  params: {
    platformGroupObjectId: platformGroupObjectId
    tenantGroupObjectId: tenantGroupObjectId
  }
  dependsOn: [tenantResources]
}

module tenantRbacMonitoring './modules/rbac.bicep' = if (!empty(platformGroupObjectId) && !empty(tenantGroupObjectId)) {
  name: 'tenant-rbac-${tenantId}-monitoring'
  scope: resourceGroup('rg-${tenantId}-monitoring')
  params: {
    platformGroupObjectId: platformGroupObjectId
    tenantGroupObjectId: tenantGroupObjectId
  }
  dependsOn: [tenantResources]
}

module tenantRbacNetwork './modules/rbac.bicep' = if (!empty(platformGroupObjectId) && !empty(tenantGroupObjectId)) {
  name: 'tenant-rbac-${tenantId}-network'
  scope: networkResourceGroup
  params: {
    platformGroupObjectId: platformGroupObjectId
    tenantGroupObjectId: tenantGroupObjectId
  }
  dependsOn: [tenantNetworking]
}

// Configure tenant budget and FinOps controls
module tenantFinOps './modules/finops.bicep' = {
  name: 'tenant-finops-${tenantId}'

  params: {
    tenantId: tenantId
    monthlyBudgetAmount: monthlyBudgetAmount
    budgetContactEmail: budgetContactEmail
    budgetStartDate: budgetStartDate
    resourceGroupNames: [
      networkResourceGroup.name
      'rg-${tenantId}-app'
      'rg-${tenantId}-data'
      'rg-${tenantId}-monitoring'
    ]
  }
}
