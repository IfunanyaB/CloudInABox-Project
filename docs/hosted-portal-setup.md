# Hosted Cloud-in-a-Box portal

The public customer page runs in Azure Container Apps in the same subscription as tenant vending. Customers do not create accounts. A request gets a private reference/token pair; the token is required to view that request's status. Administrator actions require a separate random key.

## The €1,000 setting

`MAX_REQUEST_BUDGET_EUR=1000` rejects requests whose *monthly Azure budget alert* is above €1,000. It does **not** impose a spending limit. Azure Cost Management budgets are monitoring and notification tools: provisioning and resource usage continue after the threshold is crossed, and actual costs can exceed the amount before alerts arrive. Cost data generally arrives 8–24 hours after usage, budgets are evaluated daily, and alert email is sent after evaluation. The subscription billing profile currency is EUR, matching the portal. Azure has no general subscription setting that guarantees a hard €1,000 stop across arbitrary resources. A true hard stop needs a separately designed automation policy that monitors actual cost and disables/deletes resources; that can interrupt services and still cannot guarantee there will be no overshoot. Configure Azure budget notifications and review costs regularly. See [Microsoft's budget behavior and evaluation timing](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets).

The submitted amount is used to create a per-tenant Azure budget, filtered to the tenant's resource groups. It is a forecast/alert threshold, not a quota or authorization boundary.

## Deployed hosting components

- Public HTTPS ingress through Azure Container Apps (`cloudinabox-portal`).
- A separate non-public Container App worker (`cloudinabox-worker`) reads lifecycle jobs from Service Bus.
- PostgreSQL Flexible Server on a private VNet address, storing request records and history.
- Service Bus Standard queue for durable provisioning/deprovisioning jobs.
- Key Vault for the administrator key; the API receives it as a Container Apps secret.
- Log Analytics, Azure Files source share, and managed identities.
- A dedicated `rg-cloudinabox-platform` resource group; tenant resources remain in their own isolated resource groups.

The source package is staged in an authenticated Azure Files SMB share and mounted read-only by the containers. The storage service currently has public network access enabled and protects the share with its account key; use a private endpoint/network restriction before production hardening. The runtime installs project requirements during startup. No ACR image build is used because this subscription blocks ACR Tasks; the unused empty registry created during that attempt was removed. App Service B1 deployment is unavailable under the subscription's current quota. The requested App Service name is not the portal URL; the live Container Apps URL is:

<https://cloudinabox-portal.bluehill-55c79b52.uksouth.azurecontainerapps.io>

## Access and safeguards

- The API accepts at most two public requests per contact email per rolling 24 hours. The address is not verified, so this is not a robust anti-abuse boundary. Add a rate-limiting/WAF edge before broad public promotion.
- Each customer request receives a high-entropy token once. The portal stores it in that browser's session storage; the customer should save the reference/token pair for later tracking.
- The administrator key is random and stored in Key Vault. Retrieve it only when needed with Azure CLI, and do not put it in source control or share it publicly:

  ```sh
  az keyvault secret show --vault-name cibkvwcrzymyb --name portal-admin-key --query value -o tsv
  ```

- The worker uses a managed identity and a custom subscription role for tenant vending. That identity can create/delete tenant resource groups and apply the project's listed networking, monitoring, policy, deployment, and budget actions. Treat the worker as a privileged platform component.
- The worker also processes admin-triggered, read-only verification jobs. It checks tenant resource groups, the VNet/subnets, Log Analytics workspace, policy assignments, and budget through Azure Resource Manager, then stores a per-resource report in the portal database. Verification requires the worker code to be deployed alongside the API and worker; it does not run in the public request handler.
- The platform database and queue hold costs while the subscription remains enabled. The portal's €1,000 request ceiling does not limit hosting costs or tenant spend.

## Selected request constraints

The current subscription policy permits UK South and requires the `Environment=dev` tag. The portal disables unsupported tiers/regions instead of allowing requests known to fail. Additional services remain unavailable until their Bicep resources and request validation are implemented.

## Operations

Use Azure Container Apps revisions and Log Analytics to inspect startup, API, and worker failures. Check that both apps have a ready replica, the portal `/health` endpoint is healthy, the worker can receive the Service Bus queue, and a small authorized test request reaches a final status. Tenant deprovisioning remains an explicit administrator action requiring confirmation; the worker deletes only resources whose names and ownership tags match the request record.
