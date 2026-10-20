# Cloud-in-a-Box

Cloud-in-a-Box is a self-service Azure environment-vending portal for SaaS startup environments. Customers can submit requests without creating an account and receive a private request token. Administrators can review requests, verify Azure resources, assign tenant access, and deprovision tenant environments.

## Tenant isolation model

New tenants share the active platform subscription. Each tenant receives four uniquely named and tagged resource groups (`network`, `app`, `data`, and `monitoring`), a dedicated VNet/address range, resource-group-scoped governance, and a monthly Azure budget filtered to only those groups. This avoids MCA subscription-creation cooldowns and keeps tenant policies, costs, and cleanup scoped to the tenant's groups. Existing tenant records pointing to another subscription continue to use that recorded subscription; existing Azure resources are not migrated automatically.

The hosted worker intentionally has no Azure role-assignment permissions. A subscription Owner must grant any customer Entra group access directly to the tenant's four resource groups. The optional sample app's GitHub Actions principal also requires a manual Contributor grant on only `rg-{tenant}-app`.

## Components

- `index.html`: customer and administrator portal UI.
- `automation/api.py`: FastAPI request, status, admin, evidence-export, and GitHub callback endpoints.
- `automation/worker.py`: asynchronous tenant lifecycle jobs from Azure Service Bus.
- `automation/tenant_vending.py`: tenant resource-group provisioning, Bicep deployment, Azure verification, tenant-filtered costs/budgets, and deprovisioning.
- `automation/arm_client.py`: managed-identity Azure Resource Manager client.
- `infrastructure/main.bicep`: subscription deployment that creates tenant resource groups and applies tenant-scoped governance, budget, network, monitoring, and optional hub peering.
- `infrastructure/tenant-vending-role.bicep`: custom role for the hosted worker's resource, policy, budget, and cleanup operations; it excludes role-assignment permissions.
- `infrastructure/hub-network-deploy.bicep`: shared hub VNet and optional Azure Firewall/VPN Gateway. Firewall and VPN are opt-in because they have ongoing charges.
- `sample-app/`: small containerized SaaS demonstration workload.
- `.github/workflows/deploy-sample-saas.yml`: GitHub Actions OIDC workflow deploying to one tenant app resource group.

## Local portal

Requirements: Python 3.11+, Azure CLI with Bicep, and an Azure identity with deployment permissions.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-portal.txt
.venv/bin/uvicorn automation.api:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>; opening `index.html` as a `file://` URL will not start the API. Local mode is loopback-only. The database is stored under ignored `project_outputs/` by default.

## Azure setup

Configure the hosted portal and worker using [`.env.example`](.env.example), including:

- `AZURE_SUBSCRIPTION_ID`: the enabled platform subscription used for new tenant requests.
- `AZURE_TENANT_ID`: Microsoft Entra directory ID for the hosted Azure identity.
- `HUB_SUBSCRIPTION_ID`, `HUB_RESOURCE_GROUP`, and `HUB_VNET_NAME`: the separately deployed shared hub that tenant spokes peer with.
- GitHub OIDC identity/repository settings and callback secret if the sample workload is enabled.

The worker needs the custom tenant-vending role in `infrastructure/tenant-vending-role.bicep` at the platform subscription and Network Contributor on the hub resource group. Review its actions before applying it. MCA billing-scope subscription-creation and management-group subscription-placement permissions are not needed. Deploy the hub first with `infrastructure/hub-network-deploy.bicep`; do not enable `deployFirewall` or `deployVpnGateway` without reviewing recurring costs and network design. The platform VNet used by Container Apps/PostgreSQL is not the tenant hub.

## Tenant lifecycle and deprovisioning

Each tenant request creates four resource groups and tenant-specific resources in the active subscription. Its Azure budget and Cost Management query filter to those groups. Deprovisioning removes only the tenant-owned groups, budget, and matching hub peering after confirmation and ownership-tag checks; it does not delete shared platform resources or another tenant. Existing tenants in separate subscriptions are not migrated or deleted automatically.

See [`docs/proposal-alignment.md`](docs/proposal-alignment.md) for implementation status and [`docs/usability-study-protocol.md`](docs/usability-study-protocol.md) for the evaluation protocol. `/admin/evaluation/evidence.csv` exports observed request and Azure verification measurements; it leaves unmeasured study findings blank.

## Budget note

The €1,000 request maximum is an Azure budget alert, not a spending cap. Azure budgets notify and report; they do not block deployments, shut down resources, or prevent charges. Actual spend can exceed an alert.
