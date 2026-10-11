// Tenant monitoring module

targetScope = 'resourceGroup'

@description('Name of the Log Analytics workspace.')
param workspaceName string

@description('Azure region for the monitoring workspace.')
param location string

@description('Number of days to retain monitoring data.')
param retentionInDays int = 30

@description('Tags applied to the monitoring workspace.')
param tags object

// Log Analytics workspace

resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2025-07-01' = {
  name: workspaceName
  location: location
  tags: tags

  properties: {
    retentionInDays: retentionInDays

    sku: {
      name: 'PerGB2018'
    }
  }
}

output workspaceName string = logAnalyticsWorkspace.name

output workspaceId string = logAnalyticsWorkspace.id
