# Hosted portal and subscription-vending setup

The hosted customer portal and worker run in the platform subscription. A tenant request is vended into a **separate subscription** under the existing `Tenant` management group, with its own policy, budget, spoke network, and resource groups. The platform subscription continues to host the portal, database, queue, and shared hub. Existing legacy tenants remain in the old shared subscription until deliberately migrated or removed.

## Prerequisites

Configure the variables in [`.env.example`](../.env.example) in the hosting deployment. Never commit real credentials or billing scope IDs.

1. **MCA billing scope.** Set `TENANT_BILLING_SCOPE` to the full invoice-section resource ID that allows subscription creation. Azure CLI access by a human does not grant this permission to the Container Apps worker. Assign the worker identity the appropriate Microsoft Customer Agreement subscription-creation role at this billing scope.
2. **Management group placement and ALZ baseline.** `TENANT_MANAGEMENT_GROUP_ID` must be the ID of the tenant landing-zone management group (`Tenant` in the inspected account). First deploy `infrastructure/alz-tenant-foundation.bicep` at that existing management-group scope. It uses Microsoft's pinned ALZ AVM empty pattern to apply the shared allowed-locations policy; it will not create, rename, or move management groups. Then deploy `infrastructure/tenant-management-group-access.bicep` at the same scope with the worker principal ID. Review the custom role actions and scope before assignment. The tenant-vending verification checks this inherited policy at the management-group scope.
3. **Worker identity.** Set `WORKER_PRINCIPAL_OBJECT_ID` to the queue worker's system-assigned identity. It is named owner in each new subscription so the workflow can deploy landing-zone resources and assign customer/CI roles. Ensure the alias API operation accepts and applies that owner assignment in your MCA context.
4. **Platform access.** `PLATFORM_GROUP_OBJECT_ID` is optional. Set it to the operator Entra group if that group should receive Reader in each tenant subscription. The worker receives the narrow platform subscription role from `tenant-vending-role.bicep`; hub Network Contributor is scoped to the hub resource group. A customer group can be assigned Contributor by an authenticated administrator in the tenant details view.
5. **Hub.** Deploy `infrastructure/hub-network-deploy.bicep` in the platform subscription and configure `HUB_SUBSCRIPTION_ID`, `HUB_RESOURCE_GROUP`, and `HUB_VNET_NAME`. The existing platform VNet is not the tenant hub. Address planning currently reserves `10.255.0.0/16` for the hub and allocates new tenant spokes from `10.30.0.0/16` through `10.254.0.0/16`; check these ranges against any external networks before deployment.
6. **Optional inspection services.** Firewall and VPN Gateway are disabled by default. Enable only after reviewing recurring service charges, firewall policy, ingress/egress requirements, and route behavior. A public ingress path for the sample app is distinct from creating standalone Public IP resources.
7. **Sample app (optional).** To enable it, configure the GitHub repository, repository-dispatch token, callback secret, and an Azure federated credential for the GitHub Actions principal. Grant that principal Contributor in each new tenant subscription (the template supports it). Make the GHCR image public or add a secure image-pull identity. When this integration is not configured, provisioning and the portal still work; sample-workload runs are reported as unconfigured.

To apply the ALZ baseline after reviewing the existing management-group target and required policy permissions, run from the repository root:

```sh
az deployment mg create \
  --name cib-alz-tenant-foundation \
  --management-group-id Tenant \
  --location uksouth \
  --template-file infrastructure/alz-tenant-foundation.bicep
```

This is a separate platform setup step; tenant requests do not deploy or alter management-group policy. The first compile requires access to Microsoft's public Bicep registry to restore the pinned AVM module.

## Current hosted setup status (2026-10-20)

- The public portal is `https://cloudinabox-portal.bluehill-55c79b52.uksouth.azurecontainerapps.io`.
- The dedicated `rg-cib-hub` resource group and `vnet-cib-hub` are deployed in UK South with address range `10.255.0.0/16`. Azure Firewall and VPN Gateway are disabled. The worker identity has Network Contributor on the hub resource group.
- The existing `Tenant` management group has the UK South allowed-locations assignment. The worker has the custom subscription-placement role at that scope and Azure subscription creator at the selected MCA invoice section.
- The worker's hosted settings include the tenant directory ID, billing scope, management group, and hub. The current project source was uploaded to the existing Azure Files share. The latest worker revision reports Healthy; the portal `/health` endpoint returned HTTP 200 and the new portal revision logs show application startup completed.
- No new tenant subscription was created during this setup. A real tenant request is the remaining end-to-end check and will create resources under the MCA billing scope. Budgets are alerts, not spending caps.

The ALZ AVM Bicep file is present for repeatable deployment. In this environment, Bicep could not restore the external module from Microsoft's public registry, so the same built-in allowed-locations assignment was applied directly to the management group with Azure CLI. The AVM module deployment itself remains to be validated where public Bicep modules can be restored.

The initial inspection found an enabled platform subscription and an MCA invoice section that permits subscription creation for the signed-in operator. The worker has since been assigned Azure subscription creator at that invoice section. The platform VNet `vnet-cib-platform` contains Container Apps and PostgreSQL delegated subnets and is not the hub; the separate hub VNet is documented above.

## Subscription placement and deployment order

1. Review the tenant management group; deploy the ALZ allowed-locations baseline and worker placement role at that management-group scope.
2. Deploy the shared hub once. Do not enable charged services until reviewed.
3. Update the hosted portal/worker configuration with billing scope, management group, hub, principal IDs, and GitHub settings.
4. Confirm the worker identity's billing permission, management-group placement permission, platform subscription read access, and hub resource-group network role.
5. Submit a low-cost authorized test request only after the previous steps are complete. The worker creates/resumes `cib-{tenant_id}` and then deploys the tenant subscription template. A repeated retry uses the same alias and recorded subscription ID.

A dry-run request without an existing tenant subscription only checks basic portal configuration; it does not create a subscription or perform a full Azure what-if. Avoid implying otherwise.

## Current deprovision behavior

The confirmed admin action removes only the four tenant resource groups (`network`, `app`, `data`, `monitoring`), the subscription budget, and the matching hub-side peering after verifying ownership tags. It **does not cancel the vended Azure subscription**. The subscription remains active and billable. Subscription cancellation is not implemented because it is a separate destructive billing action; cancel or disable it through an explicitly reviewed Azure operation after confirming the customer data-retention and cleanup requirements.

## Security and operational checks

- Public requests do not require customer accounts. The private request token is the customer's access credential; keep it safe.
- Admin APIs require the configured admin key; store it in Key Vault and never include its value in source control.
- Apply a rate-limiting/WAF control before broader public use; request-per-email throttling is not robust identity verification.
- The €1,000 maximum is an alert limit, not a spend cap. Azure budgets do not stop resources or charges.
- Inspect Container Apps revisions, portal `/health`, worker logs, Service Bus delivery/dead-letter counts, Azure deployment operations, and Key Vault/managed identity access when diagnosing failures.
- Review actual subscription assignment permissions and the effects of `subscriptionOwnerId` for MCA before processing real tenant requests.
