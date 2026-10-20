// Resources for the sample SaaS application, scoped to rg-{tenant}-app.
targetScope = 'resourceGroup'

@description('Tenant identifier used for resource names and tags.')
param tenantId string
@description('Tenant approved Azure region.')
param location string
@description('Public GHCR image produced by the repository workflow.')
param image string

var tags = {
  Project: 'CloudInABox'
  TenantId: tenantId
  Environment: 'dev'
  CostCentre: tenantId
  ManagedBy: 'github-actions'
}
// Container Apps names are limited to 32 characters; resource group IDs give
// each tenant deployment a stable, collision-resistant suffix.
var sampleAppName = 'saas-${uniqueString(resourceGroup().id)}'

resource tenantVnet 'Microsoft.Network/virtualNetworks@2025-07-01' existing = {
  scope: resourceGroup(subscription().subscriptionId, 'rg-${tenantId}-network')
  name: 'vnet-${tenantId}'
}

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  scope: resourceGroup(subscription().subscriptionId, 'rg-${tenantId}-monitoring')
  name: 'law-${tenantId}'
}

resource containerEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-${tenantId}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: workspace.properties.customerId
        sharedKey: workspace.listKeys().primarySharedKey
      }
    }
    vnetConfiguration: {
      infrastructureSubnetId: '${tenantVnet.id}/subnets/snet-app'
      internal: false
    }
  }
}

resource sampleApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: sampleAppName
  location: location
  tags: tags
  properties: {
    managedEnvironmentId: containerEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: true, targetPort: 8000, transport: 'http', allowInsecure: false }
    }
    template: {
      containers: [{
        name: 'sample-saas'
        image: image
        resources: { cpu: json('0.25'), memory: '0.5Gi' }
        env: [
          { name: 'TENANT_ID', value: tenantId }
          { name: 'TENANT_REGION', value: location }
          { name: 'TENANT_SUBSCRIPTION_ID', value: subscription().subscriptionId }
        ]
      }]
      scale: {
        minReplicas: 0
        maxReplicas: 2
        rules: [{ name: 'http-scale', http: { metadata: { concurrentRequests: '20' } } }]
      }
    }
  }
}

output applicationUrl string = 'https://${sampleApp.properties.configuration.ingress.fqdn}'
output applicationResourceId string = sampleApp.id
