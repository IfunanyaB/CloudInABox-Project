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
@description('Microsoft Entra tenant directory ID used when vending tenant subscriptions.')
param tenantDirectoryId string
@description('MCA invoice section billing scope used to create tenant subscriptions.')
param tenantBillingScope string = ''
@description('ARM resource ID of the management group receiving new tenant subscriptions.')
param tenantManagementGroupId string = '/providers/Microsoft.Management/managementGroups/Tenant'
@description('Platform subscription that contains the shared hub network.')
param hubSubscriptionId string = ''
@description('Hub resource group name.')
param hubResourceGroupName string = 'rg-cib-hub'
@description('Hub VNet name; must exist before requests can be provisioned.')
param hubVnetName string = ''
@description('Private IP of the hub firewall; leave empty if the firewall is not deployed.')
param hubFirewallPrivateIp string = ''
@description('Set true only after a VPN gateway is deployed in the hub.')
param hubVpnGatewayEnabled bool = false
@description('Platform Entra security group object ID, assigned Reader in each tenant subscription.')
param platformGroupObjectId string = ''
@description('GitHub Actions service principal object ID, assigned Contributor in tenant subscriptions.')
param githubActionsPrincipalObjectId string = ''
@description('GitHub repository in owner/name form for sample workload dispatch.')
param githubRepository string = ''
@secure()
@description('Fine-grained GitHub token with repository Contents: write to send repository_dispatch events.')
param githubActionsToken string = ''
@secure()
@description('Random shared secret used only to authenticate GitHub Actions status callbacks to the portal API.')
param githubCallbackSecret string = ''
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
        { name: 'github-callback-secret', value: githubCallbackSecret }
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
          { name: 'AZURE_TENANT_ID', value: tenantDirectoryId }
          { name: 'TENANT_BILLING_SCOPE', value: tenantBillingScope }
          { name: 'TENANT_MANAGEMENT_GROUP_ID', value: tenantManagementGroupId }
          { name: 'WORKER_PRINCIPAL_OBJECT_ID', value: worker!.identity.principalId }
          { name: 'HUB_SUBSCRIPTION_ID', value: empty(hubSubscriptionId) ? subscriptionId : hubSubscriptionId }
          { name: 'HUB_RESOURCE_GROUP', value: hubResourceGroupName }
          { name: 'HUB_VNET_NAME', value: hubVnetName }
          { name: 'HUB_FIREWALL_PRIVATE_IP', value: hubFirewallPrivateIp }
          { name: 'HUB_VPN_GATEWAY_ENABLED', value: hubVpnGatewayEnabled ? 'true' : 'false' }
          { name: 'PLATFORM_GROUP_OBJECT_ID', value: platformGroupObjectId }
          { name: 'GITHUB_ACTIONS_PRINCIPAL_OBJECT_ID', value: githubActionsPrincipalObjectId }
          { name: 'GITHUB_CALLBACK_SECRET', secretRef: 'github-callback-secret' }
          { name: 'GITHUB_REPOSITORY', value: githubRepository }
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
      secrets: concat(
        [{ name: 'database-url', value: databaseUrl }],
        empty(githubActionsToken) ? [] : [{ name: 'github-actions-token', value: githubActionsToken }]
      )
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
        env: concat([
          { name: 'APP_ENV', value: 'production' }
          { name: 'DATABASE_URL', secretRef: 'database-url' }
          { name: 'SERVICE_BUS_NAMESPACE', value: 'https://${serviceBus.name}.servicebus.windows.net' }
          { name: 'SERVICE_BUS_QUEUE', value: queueName }
          { name: 'AZURE_SUBSCRIPTION_ID', value: subscriptionId }
          { name: 'AZURE_TENANT_ID', value: tenantDirectoryId }
          { name: 'TENANT_BILLING_SCOPE', value: tenantBillingScope }
          { name: 'TENANT_MANAGEMENT_GROUP_ID', value: tenantManagementGroupId }
          { name: 'HUB_SUBSCRIPTION_ID', value: empty(hubSubscriptionId) ? subscriptionId : hubSubscriptionId }
          { name: 'HUB_RESOURCE_GROUP', value: hubResourceGroupName }
          { name: 'HUB_VNET_NAME', value: hubVnetName }
          { name: 'HUB_FIREWALL_PRIVATE_IP', value: hubFirewallPrivateIp }
          { name: 'HUB_VPN_GATEWAY_ENABLED', value: hubVpnGatewayEnabled ? 'true' : 'false' }
          { name: 'PLATFORM_GROUP_OBJECT_ID', value: platformGroupObjectId }
          { name: 'GITHUB_ACTIONS_PRINCIPAL_OBJECT_ID', value: githubActionsPrincipalObjectId }
          { name: 'GITHUB_REPOSITORY', value: githubRepository }
          { name: 'MAX_REQUEST_BUDGET_EUR', value: '1000' }
        ], empty(githubActionsToken) ? [] : [{ name: 'GITHUB_ACTIONS_TOKEN', secretRef: 'github-actions-token' }])
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
