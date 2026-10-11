targetScope = 'resourceGroup'

@description('UK South is the subscription-approved location.')
param location string = 'uksouth'
param serviceBusNamespaceName string
param keyVaultName string
@secure()
param databaseUrl string
@secure()
param adminKey string
param subscriptionId string
param deployApps bool = false
@description('Unique suffix used to roll the app revision when secret values change.')
param revisionSuffix string = 'initial'

var tags = {
  Project: 'CloudInABox'
  TenantId: 'platform'
  Environment: 'dev'
  CostCentre: 'cloudinabox-platform'
  ManagedBy: 'bicep'
}
var suffix = uniqueString(subscription().id)
var envName = 'cae-cib-${take(suffix, 8)}'
var queueName = 'tenant-provisioning'

resource serviceBus 'Microsoft.ServiceBus/namespaces@2022-10-01-preview' existing = {
  name: serviceBusNamespaceName
}
resource queue 'Microsoft.ServiceBus/namespaces/queues@2022-10-01-preview' existing = {
  parent: serviceBus
  name: queueName
}
resource vault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}
resource env 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: envName
}
resource envStorage 'Microsoft.App/managedEnvironments/storages@2024-08-02-preview' existing = {
  parent: env
  name: 'cloudinabox-source'
}

resource portal 'Microsoft.App/containerApps@2024-03-01' = if (deployApps) {
  name: 'cloudinabox-portal'
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: { external: true, targetPort: 8000, transport: 'http', allowInsecure: false }
      secrets: [
        { name: 'database-url', value: databaseUrl }
        { name: 'admin-key', value: adminKey }
      ]
    }
    template: {
      revisionSuffix: revisionSuffix
      volumes: [{ name: 'portal-source', storageType: 'AzureFile', storageName: envStorage.name }]
      containers: [{
        name: 'portal'
        image: 'python:3.13-slim'
        command: ['/bin/sh', '-c']
        args: ['cd /mnt/portal && python -m pip install --no-cache-dir -r requirements.txt && exec python -m uvicorn automation.api:app --host 0.0.0.0 --port 8000']
        resources: { cpu: json('0.5'), memory: '1Gi' }
        volumeMounts: [{ volumeName: 'portal-source', mountPath: '/mnt/portal' }]
        env: [
          { name: 'APP_ENV', value: 'production' }
          { name: 'AUTH_MODE', value: 'admin_key' }
          { name: 'DATABASE_URL', secretRef: 'database-url' }
          { name: 'PORTAL_ADMIN_KEY', secretRef: 'admin-key' }
          { name: 'MAX_REQUEST_BUDGET_EUR', value: '1000' }
          { name: 'PUBLIC_REQUESTS_PER_EMAIL_PER_DAY', value: '2' }
          { name: 'SERVICE_BUS_NAMESPACE', value: 'https://${serviceBus.name}.servicebus.windows.net' }
          { name: 'SERVICE_BUS_QUEUE', value: queueName }
          { name: 'AZURE_SUBSCRIPTION_ID', value: subscriptionId }
        ]
      }]
      scale: { minReplicas: 1, maxReplicas: 2 }
    }
  }
  dependsOn: [queue]
}
resource worker 'Microsoft.App/containerApps@2024-03-01' = if (deployApps) {
  name: 'cloudinabox-worker'
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: [{ name: 'database-url', value: databaseUrl }]
    }
    template: {
      revisionSuffix: revisionSuffix
      volumes: [{ name: 'portal-source', storageType: 'AzureFile', storageName: envStorage.name }]
      containers: [{
        name: 'worker'
        image: 'python:3.13-slim'
        command: ['/bin/sh', '-c']
        args: ['cd /mnt/portal && python -m pip install --no-cache-dir -r requirements.txt && exec python -m automation.worker']
        resources: { cpu: json('0.5'), memory: '1Gi' }
        volumeMounts: [{ volumeName: 'portal-source', mountPath: '/mnt/portal' }]
        env: [
          { name: 'APP_ENV', value: 'production' }
          { name: 'DATABASE_URL', secretRef: 'database-url' }
          { name: 'SERVICE_BUS_NAMESPACE', value: 'https://${serviceBus.name}.servicebus.windows.net' }
          { name: 'SERVICE_BUS_QUEUE', value: queueName }
          { name: 'AZURE_SUBSCRIPTION_ID', value: subscriptionId }
          { name: 'MAX_REQUEST_BUDGET_EUR', value: '1000' }
        ]
      }]
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
  dependsOn: [queue]
}
resource busSend 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployApps) {
  name: guid(serviceBus.id, 'cloudinabox-portal', 'ServiceBusDataSender')
  scope: serviceBus
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39')
    principalId: portal!.identity.principalId
    principalType: 'ServicePrincipal'
  }
}
resource busReceive 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deployApps) {
  name: guid(serviceBus.id, 'cloudinabox-worker', 'ServiceBusDataReceiver')
  scope: serviceBus
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0')
    principalId: worker!.identity.principalId
    principalType: 'ServicePrincipal'
  }
}
module workerPermissions './tenant-vending-role.bicep' = if (deployApps) {
  name: 'cloudinabox-worker-tenant-vending-permissions'
  scope: subscription()
  params: { workerPrincipalId: worker!.identity.principalId, workerName: worker!.name }
}

output portalUrl string = deployApps ? 'https://${portal!.properties.configuration.ingress.fqdn}' : ''
output adminKeySecret string = '${vault.name}/portal-admin-key'
output workerIdentity string = deployApps ? worker!.identity.principalId : ''
