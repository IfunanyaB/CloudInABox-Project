# Cloud-in-a-Box implementation and deployment record

**Record date:** 20 October 2026  
**Repository:** [IfunanyaB/FinalYearProject](https://github.com/IfunanyaB/FinalYearProject)  
**Hosted portal:** [cloudinabox-portal](https://cloudinabox-portal.bluehill-55c79b52.uksouth.azurecontainerapps.io)

## Project implementation

Cloud-in-a-Box is implemented as an Azure self-service vending portal. Customer requests are submitted without customer accounts. The administrator portal supports tenant request review, Azure resource verification, tenant access administration, tenant lifecycle operations, reporting, and deprovisioning.

New tenants are isolated using four resource groups in the active platform subscription: `network`, `app`, `data`, and `monitoring`. The tenant foundation provisions the network and monitoring baseline, applies tenant-scoped governance and budget alerts, and uses resource groups to keep tenant resources distinct. This is a shared-subscription/resource-group vending model; it does not create one Azure subscription per tenant.

The principal components are:

- `index.html`: customer and administrator portal.
- `automation/api.py`: FastAPI portal API and administration endpoints.
- `automation/worker.py` and `automation/jobs.py`: asynchronous tenant lifecycle processing.
- `automation/tenant_vending.py` and `automation/arm_client.py`: Azure resource provisioning, verification, FinOps queries, and deprovisioning.
- `infrastructure/`: Bicep modules for tenant groups, networking, monitoring, governance, FinOps, shared platform resources, and hosting.
- `sample-app/`: a small sample SaaS workload used to demonstrate an app deployed into a tenant's app resource group.
- `.github/workflows/deploy-sample-saas.yml`: GitHub Actions workflow that builds the sample image and deploys it using Azure OIDC.

The project does not currently deploy customer-specific databases or storage accounts into the `data` resource group. The sample app is a demonstrator; the portal does not yet connect a customer's source repository or deploy that customer's own website.

## Hosted sample workload deployment

The sample workload was deployed to the existing validation tenant:

| Item | Verified value |
| --- | --- |
| Tenant ID | `cib-rg-validation-02-20261020` |
| Platform subscription | `64d98e32-d07b-4134-9081-d8050020ac3b` |
| Region | `uksouth` (UK South) |
| App resource group | `rg-cib-rg-validation-02-20261020-app` |
| Container Apps environment | `cae-cib-rg-validation-02-20261020` |
| Sample Container App | `saas-etya3lzysgomm` |
| Public application URL | [Open sample app](https://saas-etya3lzysgomm.ambitiouscoast-413c60bb.uksouth.azurecontainerapps.io) |
| Health endpoint | [Open `/health`](https://saas-etya3lzysgomm.ambitiouscoast-413c60bb.uksouth.azurecontainerapps.io/health) |
| GitHub Actions run | [Successful deployment run](https://github.com/IfunanyaB/FinalYearProject/actions/runs/39420677444) |
| Container Apps revision | `saas-etya3lzysgomm--gcl3pcx` |

Azure reported the deployment and latest revision as `Succeeded`. Five HTTPS requests to `/health` returned `status: healthy` and the expected tenant ID, region, and subscription ID. The sample serves `/` and `/health` and writes HTTP request lines to its container console logs.

The sample app and environment are real Azure resources in the tenant's `app` resource group. The current tenant resource inventory is:

- `network`: `vnet-cib-rg-validation-02-20261020` and `rt-vnet-cib-rg-validation-02-20261020`.
- `app`: `cae-cib-rg-validation-02-20261020` and `saas-etya3lzysgomm`.
- `data`: no resources currently deployed.
- `monitoring`: `law-cib-rg-validation-02-20261020`.

## Deployment fixes and Azure workflow access

The GitHub Actions deployment initially exposed three setup issues, which were resolved:

1. GHCR rejected the mixed-case GitHub owner in the image path. The workflow now lowercases the owner before tagging and publishing the image.
2. The generated Container App name exceeded Azure's 32-character limit. `sample-app/app.bicep` now derives a short, stable name from the tenant app resource group ID.
3. The workflow's scoped Log Analytics role lacked `Microsoft.OperationalInsights/workspaces/listKeys/action`. That action was added to the tenant workspace custom role so Bicep could configure log forwarding.

The workflow uses GitHub OIDC instead of an Azure client secret. An Azure app registration and federated credentials were created for this repository's main branch. Its principal has Contributor on this tenant's app resource group, Network Contributor on this tenant's network resource group, and a custom Log Analytics configuration role on this tenant's monitoring resource group. These Azure identity and role assignments were configured in Azure; they are not stored as credentials in Git. The workflow and Bicep code are stored in Git.

## Portal visibility and telemetry status

The portal can discover the new Azure resources when an administrator opens the tenant and selects **Verify actual Azure resources**. The app group should then list the Container Apps environment and sample app.

The workflow completed successfully but reported that portal callback settings are missing. As a result, the portal does not automatically record the sample app URL or GitHub Actions run link in the tenant record. The links above work independently. To enable automatic status updates, configure a shared callback secret on the portal worker and as the GitHub Actions `GITHUB_CALLBACK_SECRET`, retaining the signed callback mechanism. Do not use the administrator key for this callback.

Container Apps is configured to send console logs to the tenant Log Analytics workspace. Five health requests were issued. A query of the workspace shortly afterward returned no console-log rows yet, so telemetry ingestion has not been confirmed in the workspace at the time of this record. Allow for Azure ingestion delay and refresh tenant Azure data before concluding that logs are absent. No cost data or workload utilization figures are claimed here; those must come from Azure after data is available.

## Git status and cleanup

The deployment-related code fixes are pushed in:

- `3413d21 Fix sample workload image tag casing`
- `e9bf258 Use valid tenant sample app resource name`

The recent portal and reporting changes are also present in the pushed history, including `93615e9`, `379df3a`, and `8b14c1d`. A repository-wide text/file scan of this project root found no CrewAI or Tavily references or files. This confirms those unused integrations are not present in the current project root; the historical side project is separate from this portal repository.

This document and the smoke-test guide describe the current deployment and its observed limits. Azure secrets and administrator keys are intentionally omitted.
