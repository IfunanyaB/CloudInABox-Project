# Hosted portal and tenant provisioning

The customer portal and queue worker run in the platform subscription. New tenants use that same subscription, with four isolated resource groups, a dedicated VNet/address range, tenant-scoped governance, and a budget filtered to their own groups. Existing tenant records that point to another subscription continue to use it; no Azure resources are migrated.

## Prerequisites

Configure the hosted settings in [`.env.example`](../.env.example). Never commit real secrets.

1. **Platform subscription.** `AZURE_SUBSCRIPTION_ID` must identify an enabled subscription. It hosts the portal and all new tenant resource groups.
2. **Worker identity.** Deploy/update the portal infrastructure with `infrastructure/platform-apps.bicep`. This assigns the custom tenant-vending role in `infrastructure/tenant-vending-role.bicep` to the worker. Review its resource, policy, budget, and cleanup actions. It intentionally has no role-assignment permissions. The worker also needs Network Contributor on the shared hub resource group.
3. **Hub.** Deploy `infrastructure/hub-network-deploy.bicep` once and configure `HUB_SUBSCRIPTION_ID`, `HUB_RESOURCE_GROUP`, and `HUB_VNET_NAME`. The existing platform VNet `vnet-cib-platform` is for Container Apps/PostgreSQL and is not the tenant hub. The hub uses `10.255.0.0/16`; tenant networks are allocated from `10.30.0.0/16` to `10.254.0.0/16` with overlap checks against visible VNets.
4. **Customer access.** A subscription Owner must grant a customer's Entra group Contributor directly on that tenant's four resource groups. The hosted worker cannot create Azure role assignments. The admin access action explains this limitation and makes no Azure RBAC change.
5. **Optional sample workload.** Follow [the tenant workload smoke-test guide](tenant-workload-smoke-test.md) to deploy the included sample web app into `rg-{tenant}-app`. Core tenant provisioning creates the isolated foundation only; it does not deploy the sample app or a database.
6. **Cost and monitoring.** The monthly budget and Cost Management query are filtered to the four tenant group names. Actual Azure cost data can be delayed, and a workspace may initially contain no telemetry. The budget is an alert, not a spending cap.

## Deployment behavior

A tenant request deploys the subscription-scope Bicep template into the active subscription. It creates `rg-{tenant}-network`, `rg-{tenant}-app`, `rg-{tenant}-data`, and `rg-{tenant}-monitoring`. Tenant policies are assigned to each group instead of the shared subscription, so one tenant's tags and region restrictions do not affect other tenant groups. Tenant VNets and peerings are separately named.

The worker needs permission to create/delete tenant resource groups, deploy the included Azure resources, assign tenant-scoped policies, create budgets, inspect tenant state and costs, and peer/unpeer from the hub. It cannot manage Azure role assignments. No MCA billing-scope or management-group subscription-placement permission is required for new tenant requests.

## Why tenant groups can be empty

Every new tenant gets four groups. The baseline puts the VNet and route table in `network`, the Log Analytics workspace in `monitoring`, and governance/budget configuration at their respective Azure scopes. `app` and `data` are intentionally empty at this stage: no application or database is part of the baseline template. The included optional sample workflow can add a Container Apps environment and sample web app to `app`; there is not yet a deployable database/storage module for `data`. Empty groups are therefore expected until an approved workload template is deployed.

## Deprovision behavior

After an admin confirms by entering the exact tenant ID, the worker checks the four expected groups and their `TenantId` and `Project=CloudInABox` ownership tags. It removes only the tenant's matching hub peering, budget, and tagged resource groups. It never deletes the shared subscription, hub, portal, database, queue, or another tenant's groups. Existing tenants in separate subscriptions continue to be targeted by their recorded subscription ID.

## Current hosted setup

- Portal: `https://cloudinabox-portal.bluehill-55c79b52.uksouth.azurecontainerapps.io`.
- The portal and worker run in the enabled platform subscription.
- `rg-cib-hub` contains the shared hub VNet; Firewall and VPN Gateway are disabled.
- `deployment/package-source.py` compiles `infrastructure/main.bicep` into the ARM JSON loaded by the worker.
- Review Container Apps revisions, portal `/health`, worker logs, Service Bus delivery/dead-letter counts, Azure deployment operations, and Key Vault/managed-identity access when diagnosing failures.
