# Testing a provisioned tenant with a real workload

## What the portal currently provisions

A successful request proves that the platform created the tenant's isolated resource groups, VNet/subnets, route table, Log Analytics workspace, governance policies, and budget alert in the shared Azure subscription. It does **not** create a customer's company website, database, customer Azure identity, or app deployment pipeline. The contact email on a request is recorded for the request; it is not automatically given Azure access.

The repository includes an optional sample SaaS app and GitHub Actions workflow. Running it deploys a small HTTPS Container App into that tenant's `rg-{tenant}-app` resource group. Its `/` and `/health` endpoints return health and tenant/region/subscription identity. This is a demonstrator workload, not a mechanism for customers to connect arbitrary source repositories from the portal.

## One-time setup for the sample workflow

1. In Azure, create or use a service principal backed by an app registration with a federated identity credential for this GitHub repository and the branch you will run from. Use issuer `https://token.actions.githubusercontent.com`, audience `api://AzureADTokenExchange`, and subject `repo:IfunanyaB/FinalYearProject:ref:refs/heads/main` (adjust the owner/repository/branch if they differ). No client secret is needed for GitHub OIDC.
2. Add GitHub Actions repository secrets `AZURE_CLIENT_ID` and `AZURE_TENANT_ID` for that app registration and directory.
3. Grant its service principal permissions only on this tenant's groups:
   - `Contributor` on `rg-{tenant}-app` so the workflow can deploy the Container Apps environment and app.
   - `Network Contributor` on `rg-{tenant}-network` so Container Apps can read and join the delegated `snet-app` subnet.
   - A small custom role on `rg-{tenant}-monitoring` with `Microsoft.OperationalInsights/workspaces/read` and `Microsoft.OperationalInsights/workspaces/sharedKeys/action`, which the Bicep deployment uses to configure Container Apps log forwarding. This scope is specific to the tenant workspace.
4. Run the workflow once from **Actions → Deploy sample SaaS workload → Run workflow**. GitHub may first require approval to publish the `cloudinabox-sample-saas` package. Make that GHCR package public so the new Container App can pull the image without a registry credential.
5. To have the portal automatically record the app URL and GitHub run link, add repository variable `PORTAL_API_URL` with the hosted portal's base URL and repository secret `GITHUB_CALLBACK_SECRET` matching the worker's configured callback secret. The signed callback never uses or exposes the administrator key. Without these callback settings, the workflow can still deploy the app, but the portal will not show its result.

The app subnet is dedicated to Container Apps. The deployed environment uses the default workload-profiles mode; Microsoft's current guidance permits a dedicated subnet as small as `/27` for that mode, so the project's `/24` app subnet has enough address space. See [Microsoft's Container Apps virtual network requirements](https://learn.microsoft.com/en-us/azure/container-apps/custom-virtual-networks).

## Run a tenant smoke test

1. Provision a tenant from the portal and wait for **Success**.
2. Sign into the admin portal and open that tenant's details. Copy its tenant ID and subscription ID.
3. In GitHub Actions, run **Deploy sample SaaS workload** and supply those two IDs. The subscription ID is the platform subscription containing the four tenant groups.
4. Wait for the workflow to finish. Open its `application_url` output, or the app link in tenant details if the callback is configured. `/health` should return JSON with `status: healthy` and the same tenant ID.
5. Re-run **Verify actual Azure resources**. The app group should now contain the Container Apps environment and app. The FinOps tenant report can be downloaded from the tenant's FinOps detail. Once Azure has ingested telemetry and billing rows have settled, its monitoring and cost sections can show those measured values. Fresh tenants may legitimately have no costs yet.

This validates the resource vending plus a real, reachable workload deployed inside the tenant's isolated app group. For an actual customer business website, the customer would currently have to adapt and deploy their own source through an independently configured pipeline into that group; the portal does not yet offer source-repository connection, app configuration, or database selection. A production self-service feature would need a GitHub App/OIDC consent flow, supported workload templates and settings, per-tenant deployment permissions, and status/log callbacks. The portal should not collect source-control personal access tokens or Azure passwords.

## Why monitoring can be empty

Creating a Log Analytics workspace does not create events by itself. Azure Activity events appear only when Activity Log diagnostic settings route them to the tenant workspace. Container Apps console/system events arrive after the sample workload is deployed and its environment is configured to send logs to that workspace. The portal queries those sources and reports what Azure returns; it does not synthesize telemetry. Cost Management data may also arrive after a delay.
