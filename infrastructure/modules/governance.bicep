// Cloud-in-a-Box tenant governance policies

targetScope = 'resourceGroup'

@description('Azure regions allowed for resources in this tenant resource group.')
param allowedLocations array = [
  'uksouth'
]

@description('Tenant identifier required on resources in this resource group.')
param tenantId string

@description('Environment assigned to the tenant.')
param environment string

// Policy 1: Restrict resources to approved Azure locations

resource allowedLocationsPolicy 'Microsoft.Authorization/policyAssignments@2025-03-01' = {
  name: 'policy-allowed-locations'

  properties: {
    displayName: 'Cloud-in-a-Box: Allowed Locations'
    description: 'Restricts tenant resources to approved Azure regions.'
    policyDefinitionId: '/providers/Microsoft.Authorization/policyDefinitions/e56962a6-4747-49cd-b67b-bf8b01975c4c'

    parameters: {
      listOfAllowedLocations: {
        value: allowedLocations
      }
    }
  }
}

// Policy 2: Require this tenant's identifier tag on resources

resource costCentreTagPolicy 'Microsoft.Authorization/policyAssignments@2025-03-01' = {
  name: 'policy-required-tenant-id'

  properties: {
    displayName: 'Cloud-in-a-Box - Required TenantId Tag'
    description: 'Requires resources in this resource group to carry this tenant identifier.'
    policyDefinitionId: '/providers/Microsoft.Authorization/policyDefinitions/1e30110a-5ceb-460c-a204-c1c3969c6d62'

    parameters: {
      tagName: { value: 'TenantId' }
      tagValue: { value: tenantId }
    }
  }
}

// Policy 3: Require Environment tag on resources

resource environmentTagPolicy 'Microsoft.Authorization/policyAssignments@2025-03-01' = {
  name: 'policy-required-environment'

  properties: {
    displayName: 'Cloud-in-a-Box - Required Environment Tag'
    description: 'Requires tenant resources to have an Environment tag.'
    policyDefinitionId: '/providers/Microsoft.Authorization/policyDefinitions/1e30110a-5ceb-460c-a204-c1c3969c6d62'

    parameters: {
      tagName: {
        value: 'Environment'
      }

      tagValue: {
        value: environment
      }
    }
  }
}


output allowedLocationPolicyAssignmentId string = allowedLocationsPolicy.id

output tenantIdPolicyAssignmentId string = costCentreTagPolicy.id

output environmentPolicyAssignmentId string = environmentTagPolicy.id
