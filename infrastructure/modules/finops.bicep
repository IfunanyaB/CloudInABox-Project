// Tenant FinOps and budget configuration

targetScope = 'subscription'

@description('Unique identifier for the tenant.')
param tenantId string

@description('Monthly budget amount for the tenant.')
param monthlyBudgetAmount int = 50

@description('Email address that receives budget notifications.')
param budgetContactEmail string

@description('Start date for the budget period.')
param budgetStartDate string

// Tenant monthly budget
resource tenantBudget 'Microsoft.Consumption/budgets@2023-05-01' = {
  name: 'budget-${tenantId}'

  properties: {
    amount: monthlyBudgetAmount
    category: 'Cost'
    timeGrain: 'Monthly'

    timePeriod: {
      startDate: budgetStartDate
    }

    notifications: empty(budgetContactEmail) ? {} : {
      Actual_80_Percent: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 80
        thresholdType: 'Actual'
        contactEmails: [
          budgetContactEmail
        ]
        contactRoles: []
        contactGroups: []
      }

      Actual_100_Percent: {
        enabled: true
        operator: 'GreaterThan'
        threshold: 100
        thresholdType: 'Actual'
        contactEmails: [
          budgetContactEmail
        ]
        contactRoles: []
        contactGroups: []
      }
    }
  }
}

output budgetName string = tenantBudget.name
output budgetAmount int = monthlyBudgetAmount
