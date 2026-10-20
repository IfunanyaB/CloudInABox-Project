// Apply the shared Azure Landing Zones governance baseline to the existing
// tenant management group. This deliberately does not create or move groups.
targetScope = 'managementGroup'

@description('Existing management group that receives all vended tenant subscriptions.')
param managementGroupName string = 'Tenant'

@description('Azure regions permitted for tenant subscriptions.')
param allowedLocations array = [
  'uksouth'
]

module alzTenantFoundation 'br/public:avm/ptn/alz/empty:0.3.5' = {
  name: 'cib-alz-tenant-foundation'
  params: {
    managementGroupName: managementGroupName
    createOrUpdateManagementGroup: false
    enableTelemetry: false
    managementGroupPolicyAssignments: [
      {
        name: 'cib-allowed-locations'
        displayName: 'Cloud-in-a-Box: Allowed Locations'
        description: 'Denies tenant resources outside the approved landing-zone regions.'
        policyDefinitionId: '/providers/Microsoft.Authorization/policyDefinitions/e56962a6-4747-49cd-b67b-bf8b01975c4c'
        parameters: {
          listOfAllowedLocations: {
            value: allowedLocations
          }
        }
      }
    ]
  }
}
