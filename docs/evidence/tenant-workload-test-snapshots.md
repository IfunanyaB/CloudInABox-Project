# Tenant workload test snapshots

**Captured:** 20 October 2026  
**Purpose:** Evidence of the sample workload deployment and checks performed against the validation tenant.  
**Note:** These are captured command/service-response snapshots, not fabricated portal screenshots. Values are reproduced from the Azure CLI, GitHub Actions, and live HTTPS responses.

## 1. Live workload health checks

**Endpoint:** [Sample app `/health`](https://saas-etya3lzysgomm.ambitiouscoast-413c60bb.uksouth.azurecontainerapps.io/health)  
**Result:** Three fresh public requests returned HTTP 200 and identified the expected tenant.

```text
GET /health request 1: {"service": "Cloud-in-a-Box sample SaaS workload", "status": "healthy", "tenant_id": "cib-rg-validation-02-20261020", "region": "uksouth", "subscription_id": "64d98e32-d07b-4134-9081-d8050020ac3b"} [HTTP 200]
GET /health request 2: {"service": "Cloud-in-a-Box sample SaaS workload", "status": "healthy", "tenant_id": "cib-rg-validation-02-20261020", "region": "uksouth", "subscription_id": "64d98e32-d07b-4134-9081-d8050020ac3b"} [HTTP 200]
GET /health request 3: {"service": "Cloud-in-a-Box sample SaaS workload", "status": "healthy", "tenant_id": "cib-rg-validation-02-20261020", "region": "uksouth", "subscription_id": "64d98e32-d07b-4134-9081-d8050020ac3b"} [HTTP 200]
```

The JSON response confirms the sample container is serving requests and receiving its tenant, region, and subscription settings.

## 2. Azure tenant resource inventory

The following inventory was queried from Azure Resource Manager for subscription `64d98e32-d07b-4134-9081-d8050020ac3b`.

```text
rg-cib-rg-validation-02-20261020-network
  rt-vnet-cib-rg-validation-02-20261020  Microsoft.Network/routeTables  uksouth
  vnet-cib-rg-validation-02-20261020    Microsoft.Network/virtualNetworks  uksouth

rg-cib-rg-validation-02-20261020-app
  cae-cib-rg-validation-02-20261020     Microsoft.App/managedEnvironments  uksouth
  saas-etya3lzysgomm                     Microsoft.App/containerApps  uksouth

rg-cib-rg-validation-02-20261020-data
  []

rg-cib-rg-validation-02-20261020-monitoring
  law-cib-rg-validation-02-20261020     Microsoft.OperationalInsights/workspaces  uksouth
```

This snapshot shows that the sample deployment populated the tenant's `app` group. The `data` group has no resources yet; database and storage provisioning are not implemented in the current template.

## 3. Azure deployment and app readiness

Azure Resource Manager deployment result:

```json
{
  "state": "Succeeded",
  "applicationResourceId": "/subscriptions/64d98e32-d07b-4134-9081-d8050020ac3b/resourceGroups/rg-cib-rg-validation-02-20261020-app/providers/Microsoft.App/containerApps/saas-etya3lzysgomm",
  "applicationUrl": "https://saas-etya3lzysgomm.ambitiouscoast-413c60bb.uksouth.azurecontainerapps.io"
}
```

Container App readiness:

```json
{
  "state": "Succeeded",
  "revision": "saas-etya3lzysgomm--gcl3pcx",
  "fqdn": "saas-etya3lzysgomm.ambitiouscoast-413c60bb.uksouth.azurecontainerapps.io"
}
```

## 4. GitHub Actions deployment

The [GitHub Actions run](https://github.com/IfunanyaB/FinalYearProject/actions/runs/39420677444) completed successfully.

```json
{
  "conclusion": "success",
  "status": "completed",
  "headSha": "e9bf258f8e954fa85863c2caf684fb9cfae1b11d",
  "url": "https://github.com/IfunanyaB/FinalYearProject/actions/runs/39420677444"
}
```

The workflow builds the sample image, signs into Azure through GitHub OIDC, and deploys `sample-app/app.bicep` to the tenant app resource group.

## 5. Monitoring observation and limits

The sample Container App is configured to forward console logs to the tenant Log Analytics workspace. A Log Analytics query shortly after the health requests returned no console-log rows. Therefore, this test confirms that the app responded to HTTP requests, but it does **not** claim that workload logs or CPU, memory, and network measurements were visible in Azure Monitor at capture time. Allow for ingestion delay and query the workspace again later.

The GitHub run also reported that the portal callback settings are missing. The deployment is successful, but the portal will not automatically save the app URL and run link on the tenant record. The public links in this evidence file work independently.

## 6. Repository state

The project repository was on `main`, synchronized with `origin/main`, with no pending changes when checked after the deployment report was pushed. The latest documentation commit at that check was:

```text
88bcfba Document sample workload deployment status
```

Deployment code fixes were pushed in `3413d21` (lowercase GHCR image tag) and `e9bf258` (valid Container App name length). Azure identity and scoped role assignments are live Azure configuration and are not stored as secrets in the repository.
