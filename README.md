# Cloud-in-a-Box

Cloud-in-a-Box is a web portal for requesting and managing Azure environments. A customer can submit a request without an account and use its private reference and token to check progress. An administrator can review requests, inspect Azure resources, and deprovision tenant environments.

## How tenant provisioning works

New tenants are created in the platform's active Azure subscription. Each tenant gets four resource groups (`network`, `app`, `data`, and `monitoring`), a VNet, scoped policies, monitoring, and a budget alert filtered to its resource groups. This is resource-group isolation in one shared subscription; the portal does not create a separate subscription for each tenant.

The budget is an alert threshold. It does not stop deployments or prevent charges. New requests use the region and environment allowed by the current Azure policies.

## Main files

- `index.html` — customer and administrator portal.
- `automation/api.py` — FastAPI endpoints for requests and administration.
- `automation/worker.py` and `automation/jobs.py` — background provisioning jobs.
- `automation/tenant_vending.py` and `automation/arm_client.py` — Azure provisioning, verification, cost queries, and deprovisioning.
- `infrastructure/` — Bicep templates for tenant resources, governance, monitoring, budgets, and portal hosting.
- `sample-app/` — sample SaaS application and its deployment templates.
- `.github/workflows/deploy-sample-saas.yml` — GitHub Actions workflow for deploying the sample app.

## Run locally

You need Python 3.11 or later, Azure CLI with Bicep, and an Azure identity with the required deployment permissions.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-portal.txt
.venv/bin/uvicorn automation.api:app --host 127.0.0.1 --port 8000
```

Then open <http://127.0.0.1:8000>. Opening `index.html` directly as a file will not start the API. Local database files are stored in the ignored `project_outputs/` directory by default.

## Azure configuration

Use [`.env.example`](.env.example) as the list of settings for the hosted portal and worker. At minimum, configure the active platform subscription and Entra tenant. Hub peering also needs the hub subscription, resource group, and VNet settings. The sample-app workflow needs its GitHub OIDC identity and callback settings.

The worker needs the custom role in `infrastructure/tenant-vending-role.bicep` at the platform subscription. It also needs Network Contributor on the hub resource group when hub peering is enabled. The worker does not assign customer roles; a subscription Owner must grant customer groups access to the tenant resource groups.

Deploy the hub before enabling tenant peering. Azure Firewall and VPN Gateway are optional and are disabled by default because they add ongoing costs. The portal hosting VNet is separate from the tenant hub.

## Deprovisioning

Deprovisioning removes the tenant's resource groups, budget, and matching hub peering after the confirmation and ownership checks. It does not remove shared platform resources or resources owned by another tenant. Existing tenants in other subscriptions are not migrated automatically.

## Project records

- [`docs/project-implementation-and-deployment-record.md`](docs/project-implementation-and-deployment-record.md) describes the deployed portal, sample workload, and known limits.
- [`docs/proposal-alignment.md`](docs/proposal-alignment.md) compares the implementation with the project proposal.
- [`docs/tenant-workload-smoke-test.md`](docs/tenant-workload-smoke-test.md) describes the sample workload checks.
- [`docs/hosted-portal-setup.md`](docs/hosted-portal-setup.md) covers portal hosting.
