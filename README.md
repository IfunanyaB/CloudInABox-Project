# Cloud-in-a-Box

Cloud-in-a-Box is a self-service Azure subscription-vending portal for SaaS startup environments. The customer portal accepts requests without customer accounts and returns a private request token. An administrator can inspect tenant requests, assign tenant Entra groups, verify Azure resources, and deprovision tenant resources.

New tenants are designed to receive a dedicated Azure subscription under the `Tenant` management group, subscription-scoped governance and budget, a tenant spoke VNet, and peering to a separately deployed shared hub. This differs from the project's earlier single-subscription/resource-group design. Existing tenants are legacy records and are not migrated automatically.

## Components

- `index.html`: customer and administrator portal UI.
- `automation/api.py`: FastAPI request, status, admin, evidence-export, and GitHub callback endpoints.
- `automation/worker.py`: asynchronous tenant lifecycle jobs from Azure Service Bus.
- `automation/tenant_vending.py`: dedicated subscription alias creation/resumption, Bicep deployments, verification, and resource-group deprovisioning.
- `automation/arm_client.py`: managed-identity Azure Resource Manager client.
- `infrastructure/main.bicep`: subscription-scoped tenant landing zone, governance, RBAC, budget, network, monitoring, and optional hub peering.
- `infrastructure/hub-network-deploy.bicep`: shared hub VNet and optional Azure Firewall/VPN Gateway. Firewall and VPN are opt-in because they have ongoing charges.
- `sample-app/`: small containerized SaaS demonstration workload.
- `.github/workflows/deploy-sample-saas.yml`: GitHub Actions OIDC workflow to deploy the sample app into a newly vended tenant subscription.

## Local portal

Requirements: Python 3.11+, Azure CLI with Bicep, and an Azure identity with deployment permissions.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-portal.txt
.venv/bin/uvicorn automation.api:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>; opening `index.html` as a `file://` URL will not start the API. Local mode is loopback-only. The database is stored under ignored `project_outputs/` by default.

## Azure requirements before tenant requests can succeed

The hosted portal and worker require all values documented in [`.env.example`](.env.example), including:

- `TENANT_BILLING_SCOPE`: full Microsoft Customer Agreement invoice-section ID that permits subscription creation.
- `TENANT_MANAGEMENT_GROUP_ID=Tenant`: the existing tenant management group nested beneath `CloudInABox`.
- `HUB_SUBSCRIPTION_ID`, `HUB_RESOURCE_GROUP`, and `HUB_VNET_NAME`: a shared hub must be deployed before tenant vending.
- `PLATFORM_GROUP_OBJECT_ID`: Entra security group to receive Reader on each tenant subscription.
- `AZURE_TENANT_ID`: Microsoft Entra directory ID for the tenant subscriptions.
- `WORKER_PRINCIPAL_OBJECT_ID`: Container Apps worker identity; used as subscription owner during vending.
- GitHub OIDC identity/repository settings and callback secret if the sample SaaS deployment is enabled.

The portal worker needs subscription-creation rights at the configured MCA invoice section, permissions to place subscriptions under the target management group, and the narrowly scoped platform/hub roles described in [the hosted setup guide](docs/hosted-portal-setup.md). The subscription-creation permission on the human Azure login does not automatically grant it to the hosted worker identity. Configure and review the access assignments before accepting live requests.

Provision the shared hub first with `infrastructure/hub-network-deploy.bicep`, then deploy/update the hosted portal infrastructure with the matching parameters. Do not turn on `deployFirewall` or `deployVpnGateway` without reviewing their recurring costs and network design. The current account's existing `vnet-cib-platform` is used by Container Apps/PostgreSQL and is not the shared tenant hub.

New tenant requests intentionally do not fall back to the legacy shared subscription. Legacy records with a shared-subscription ID cannot be retried as dedicated subscriptions because doing so could target or misrepresent existing resources.

## Tenant lifecycle and deprovisioning

Tenant provisioning creates or resumes an idempotently named Azure subscription alias, deploys the landing zone, and records the subscription ID. Deprovisioning removes the tenant-owned resource groups, budget, and hub peering after confirmation and ownership-tag checks. **It does not cancel the Azure subscription.** That subscription remains enabled and may continue to incur charges; canceling it is a separate, irreversible administrative operation and is not automated by this project. Existing tenant resources are not migrated or deleted automatically.

## Proposal alignment and evaluation

See [`docs/proposal-alignment.md`](docs/proposal-alignment.md) for implemented capabilities and deployment prerequisites, and [`docs/usability-study-protocol.md`](docs/usability-study-protocol.md) for a task-based evaluation protocol. The admin endpoint `/admin/evaluation/evidence.csv` exports observed portal/Azure records; it deliberately leaves unmeasured manual baselines and isolation findings blank. Do not report experimental results until the study is approved and run.

## Important cost note

The €1,000 request maximum configures the highest monthly Azure **budget alert** a customer may request. It is not a hard spending cap: Azure budgets notify and report; they do not block deployments, shut down resources, or prevent charges. Actual spend can exceed an alert. Firewall, VPN Gateway, Container Apps, database, storage, and tenant resources may each add charges.
