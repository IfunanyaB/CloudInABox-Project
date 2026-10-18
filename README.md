# Cloud-in-a-Box

Tenant vending portal backed by Azure Bicep. Every tenant is provisioned into the active Azure subscription, with separate tenant resource groups, a dedicated VNet, scoped policy assignments, scoped RBAC, tenant tags, and a budget filtered to that tenant's resource groups. Tenant VNets are not peered to each other. The subscription policy requires a `CostCentre` tag while allowing its value to differ by tenant.

## Requirements

- Python 3.11 or later
- Dependencies from `requirements-portal.txt` installed in `.venv`
- Azure CLI with Bicep support
- An authenticated Azure CLI session with deployment permissions in one enabled subscription
- Optional `AZURE_SUBSCRIPTION_ID` to select an enabled subscription the current account can access; otherwise the Azure CLI selected subscription is used
- Optional `BUDGET_CONTACT_EMAIL` for budgets created through the portal

## Install the portal dependencies

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-portal.txt
```

Tenant parameter profiles are environment-specific and are intentionally not committed. Create a local Bicep parameter file based on the parameters declared in `infrastructure/main.bicep`; keep customer names and contact details out of source control.

## Validate and deploy configured tenants

Run a validation and what-if for all parameter profiles:

```sh
.venv/bin/python automation/tenant_vending.py --all-profiles
```

Deploy all configured profiles serially after their what-if succeeds:

```sh
.venv/bin/python automation/tenant_vending.py --all-profiles --deploy
```

To deploy one tenant through the CLI:

```sh
.venv/bin/python automation/tenant_vending.py --tenant-id example-tenant --owner team@example.com --monthly-budget 100 --deploy
```

The deployer finds a non-overlapping `/16` VNet range in `10.0.0.0/8` and reuses a tenant's existing VNet range on redeployment. Resource groups, governance policies, role assignments, and budget tracking are scoped per tenant. Cost budgets use a resource group filter at subscription scope.

## Run the local portal

```sh
.venv/bin/uvicorn automation.api:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. The portal requires the API server; do not open `index.html` directly as a file.

Portal tenant requests and status history are stored in `project_outputs/portal.sqlite3` (ignored by Git). The default request options match the active subscription policy: Development (`Environment=dev`) and UK South. Test/Production and other regions are disabled in the portal until the subscription policy and regional eligibility allow them. Requests run the existing Azure what-if and deployment workflow; submitting a request can create billable Azure resources.

Administrators can deprovision a completed tenant, or clean up a failed deployment that may have left partial resources, from its details page. The workflow requires confirmation and the exact tenant ID, matches the recorded subscription, checks tenant ownership tags, deletes only the four known tenant resource groups and `budget-{tenantId}`, and retains the portal record and operation history. An older record without a recorded subscription ID is intentionally not eligible for automatic deletion. Azure deployment history entries are retained by Azure.

In this project, a Bicep template is an infrastructure-as-code file that declares actual Azure resources and settings. The existing `infrastructure/main.bicep` template deploys the baseline resource groups, network, monitoring, governance, and budget. The Services page also lists example additional services, clearly marked as unavailable; they cannot be selected or provisioned. An extra service becomes selectable only after its Bicep module is implemented and connected to the main deployment, with an API allowlist and request validation, UI configuration fields, and what-if/deployment coverage. That work should also account for tenant isolation, required tags/policies, identity and network access, region/SKU availability, cost impact, and deprovision behavior.

Administrators can run **Verify actual Azure resources** for a successfully provisioned tenant. This queues a read-only check in the isolated worker and queries Azure Resource Manager for the tenant's four tagged resource groups, VNet and subnets, Log Analytics workspace and retention, policy assignments, and tenant budget. The persisted report shows the subscription, resource IDs, expected/observed values, and pass/fail for each check. Verification needs the worker's existing tenant-vending identity and its read permissions; it does not create or change resources. The portal uses `Cache-Control: no-store` for the app shell and disables HTTP caching for API reads so updated status is fetched without clearing the browser session that stores private request tokens.

The portal supports local loopback development and a hosted public request flow using Azure Container Apps, private PostgreSQL Flexible Server, Azure Service Bus, Azure Files, and a separate managed-identity worker. Customers do not need accounts: each request returns a private token for status/history lookup. Admin APIs require a separate administrator key stored in Key Vault. The public API rejects requested monthly budget alerts above €1,000; Azure budgets notify but do not cap or stop spending. The subscription billing profile currency has been verified as EUR. Hosted mode requires administrator authentication, a database, a queue, and a request budget ceiling. Follow [the public Azure hosting guide](docs/hosted-portal-setup.md). Additional compute/database/storage services and actual Azure cost ingestion are not implemented.

