// Tenant resource groups

targetScope = 'subscription'

@description('Unique identifier for the tenant.')
param tenantId string

@description('Azure region for the tenant resources.')
param location string 

@description('Tags applied to all tenant resource groups.')
param tags object

//Tenant application resource group
resource appResourceGroup 'Microsoft.Resources/resourceGroups@2025-04-01' = {
  name: 'rg-${tenantId}-app'
  location: location
  tags: tags
}
// Tenant data resource group
resource dataResourceGroup 'Microsoft.Resources/resourceGroups@2025-04-01' = {
  name: 'rg-${tenantId}-data'
  location: location
  tags: tags
}

// Tenant monitoring resource group
resource monitoringResourceGroup 'Microsoft.Resources/resourceGroups@2025-04-01' = {
  name: 'rg-${tenantId}-monitoring'
  location: location
  tags: tags
}

// Resource group outputs
output appResourceGroupName string = appResourceGroup.name
output dataResourceGroupName string = dataResourceGroup.name
output monitoringResourceGroupName string = monitoringResourceGroup.name
