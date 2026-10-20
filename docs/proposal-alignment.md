# Proposal alignment and implementation status

This note maps the current artefact to the proposal objective. It distinguishes implemented source, Azure components deployed during setup, remaining end-to-end validation, and study evidence that has not yet been collected.

| Proposal objective | Current implementation | Remaining work / evidence |
| --- | --- | --- |
| Automated environment vending | FastAPI queues a request; the worker deploys a tenant's dedicated resource groups in the active platform subscription. | Provision two or more tenants in one session and confirm distinct groups, tags, and VNets. No subscription alias or billing-scope permission is required. |
| Hub-and-spoke isolation | The hub VNet and resource group are deployed; the worker has Network Contributor. Tenant spoke template, per-tenant CIDR allocation, and peering are implemented in source. Firewall/VPN are off. | Verify hub-to-spoke peering after the first new tenant is vended, review routes, and run cross-tenant reachability checks. The platform VNet is not the hub. |
| Tenant governance | UK South allowed-locations and TenantId/Environment tag policies are assigned to each tenant resource group. Public-IP denial is not currently applied to the shared-subscription tenant groups. | Apply the updated template and capture a successful provisioning/verification report; test a denied region/tag deployment. |
| FinOps / tenant P&L | Each tenant budget and Cost Management query are filtered to only the tenant's four resource groups. | Cost Management data can be delayed or absent. Verify data permissions and charge attribution after usage; a budget is not a spend cap. |
| Sample SaaS deployment | A minimal containerized app and GitHub Actions OIDC deployment workflow are included, with a signed callback to portal status. | Configure GitHub/Azure federated credentials, dispatch token, callback secret, and image pull access; execute a real pipeline. |
| Usability study | Admin CSV endpoint exports observed request durations, verification checks, and measured cost fields when available. | Recruit participants and run the proposal's task-based study only after institutional ethics/consent requirements are resolved. Record manual baseline and questionnaire responses; the code cannot provide these results. |
| ALZ-Bicep foundation | `infrastructure/alz-tenant-foundation.bicep` applies a shared location baseline at the existing `Tenant` management group. New tenant-specific policies remain resource-group scoped within the platform subscription. | The existing foundation is optional for the shared-subscription deployment; capture policy compliance for tenant resource groups. This is a tailored governance foundation, not a complete enterprise ALZ with dedicated identity, management, and connectivity subscriptions. |

## Current Azure baseline checked read-only

The initial inspection found the management-group hierarchy, enabled platform subscription, and MCA invoice section. The architecture now places new tenant workloads into per-tenant resource groups within the platform subscription so repeated requests do not depend on subscription creation. The UK South policy assignment, worker roles, and separate `vnet-cib-hub` (`10.255.0.0/16`) are deployed. Firewall and VPN Gateway remain disabled. The worker cannot assign Azure RBAC; customer access requires an Owner to grant roles at the tenant resource-group scopes. Existing records and Azure resources are not migrated automatically.

## Evaluation evidence

`GET /admin/evaluation/evidence.csv` exports stored request and verification measurements. Fields requiring external measurement, such as manual baseline time, survey score, or cross-tenant traffic findings, are intentionally left empty. Report the sample size, task script, participant consent process, data handling, and limitations alongside any future results. Do not infer study outcomes from the presence of the export endpoint.
