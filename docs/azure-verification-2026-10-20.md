# Azure verification record — 20 October 2026

Verification record for the active platform subscription and hosted portal. Azure changes made during this session are listed explicitly below. Values describe the state observed during this session and can change later.

## Portal availability

- Hosted portal loaded successfully in the in-app browser.
- The page displayed **Portal API connected**.
- The public request page and its form loaded. The form showed Development and UK South as the available choices, consistent with the displayed subscription constraints.
- The portal was used to submit the approved connectivity-test tenant request, and browser screenshots were captured at the form and submission stages in the Codex session. They were displayed during the session but could not be saved as repository image files with the available capture methods.

## Subscription and network

- Active subscription state: `Enabled`.
- Hub VNet: `rg-cib-hub/vnet-cib-hub`, `10.255.0.0/16`.
- Validation tenant spoke: `rg-cib-rg-validation-02-20261020-network/vnet-cib-rg-validation-02-20261020`, `10.34.0.0/16`.
- Both directions of the validation spoke-to-hub peering reported `Connected` and `Succeeded`; virtual-network access and forwarded traffic were enabled. A hub-side peering to a VNet in another subscription also reported `Connected`.
- The validation spoke's app subnet is associated with its route table, but that route table has no user-defined routes. The data and management subnets have no route-table or NSG association in the observed response.
- The hub VNet has reserved `AzureFirewallSubnet` and `GatewaySubnet`, but the hub resource group contains only the hub VNet. No Azure Firewall or virtual network gateway resource was found in the subscription inventory.
- Nine other inspected legacy tenant VNets returned no peering entries. Thus, peering is not uniformly provisioned across all historical VNets.
- A new tenant, `connectivity-test-2026-10-20`, was submitted through the public portal with a synthetic test contact (`isolation-test@example.org`), Development tier, UK South, and a €50 monthly alert. The request completed successfully in the active shared subscription. Four resource groups were created: `rg-connectivity-test-2026-10-20-network`, `-app`, `-data`, and `-monitoring`. Its VNet is `10.35.0.0/16`, with app/data/management subnets `10.35.1.0/24`, `10.35.2.0/24`, and `10.35.3.0/24`. The tenant is intentionally being retained for the project demonstration.
- The new tenant's hub peering and the validation tenant's hub peering both report Connected. No direct peering between those two spokes was found. The hub has no Firewall or VPN Gateway, and the validation spoke route table has no user-defined routes. This topology is consistent with non-transitive VNet peering, but it does not prove zero packet-level cross-tenant reachability.
- A live private TCP test was attempted as approved. Azure rejected `Standard_B1s` in UK South as unavailable to this subscription. The approved alternative `Standard_D2as_v5` was also initially blocked because the subscription's `standardDASv5Family` quota was 0. `Microsoft.Compute` had not been registered, which left the Azure Portal quota blade empty. After registering the provider, the approved quota request was submitted using Azure CLI and recorded as request `2267bd02-cc07-4b87-a2f9-0cb0f2cc84d6`; Azure reports it `Succeeded` with a limit of 2 vCPUs in UK South. The user chose to keep the 2-vCPU limit and revise the test. One private D2as v5 probe VM was created in the validation spoke's management subnet (`10.34.3.4`) with no public IP. Its effective routes had `10.34.0.0/16` as `VnetLocal`, `10.255.0.0/16` as `VNetPeering`, and an aggregate `10.0.0.0/8` route with next hop `None`; Network Watcher `show-next-hop` to `10.35.3.4` returned `nextHopType: None` and `routeTableId: System Route`. This is route-level evidence that the validation spoke had no next hop to the new tenant's private address. It is not a reciprocal live packet test between two active endpoints. Azure denied installation of the Network Watcher VM agent extension because the required CostCentre, Environment, and TenantId tag policies prevented the extension from carrying the mandated tags. No tag-policy exemption was added. The probe VM is retained in the existing validation app resource group and its power state was verified as `VM deallocated`; it has no public IP. A deallocated VM does not incur VM compute charges, but its OS disk continues to incur storage charges. Azure's UK South quota usage currently reads 2 of 2 vCPUs even though this VM is deallocated, leaving no quota for a second D2as v5 probe. A fresh two-endpoint packet test therefore cannot run within the approved 2-vCPU limit while this retained VM exists. The user chose to keep the 2-vCPU limit and deallocate, rather than delete, test VMs.

## Governance

Subscription-scope assignments observed:

- Allowed Locations: `Deny`, configured for `uksouth`; current evaluated resources were compliant.
- Required CostCentre tag: `Deny`; one evaluated resource was noncompliant.
- Required Environment tag: `Deny`, configured for `Environment=dev`; one evaluated resource was noncompliant.

Both tag-policy findings identified the Azure-managed Network Watcher resource at `/subscriptions/.../resourceGroups/NetworkWatcherRG/providers/Microsoft.Network/networkWatchers/NetworkWatcher_uksouth`. This is a platform-managed resource and is not part of a tenant workload. It makes the subscription-wide compliance view nonzero and should be handled as an explicit policy scope/exclusion decision rather than presented as a clean result.

- The repository contained a subscription-governance Bicep definition for denying public IPs, but the policy definition and assignment were absent in Azure. With the user's approval, I created definition `cib-deny-public-ip-resources` and subscription assignment `cib-deny-public-ip` at `/subscriptions/64d98e32-d07b-4134-9081-d8050020ac3b`.
- Negative test: a disposable UK South resource group was created, then a tagged Standard Public IP create request was attempted. Azure rejected it with `RequestDisallowedByPolicy`, identifying the Cloud-in-a-Box public-IP deny assignment. The first attempt omitted the subscription's required CostCentre tag and was blocked by that unrelated tag policy too; the retry included `CostCentre`, `Environment=dev`, and `TenantId` and was blocked specifically by the public-IP policy. The empty test resource group was deleted afterward. Existing platform Public IPs remain untouched; the policy prevents future matching create/update requests but does not delete existing IPs.
- This demonstrates a subscription-scope deny for identities unable to modify policy or create exemptions. It does not establish literal non-bypassability against subscription owners or policy administrators. The built-in Azure Security Center initiative includes audit-oriented checks; an audit result is not proof that resource creation is blocked.
- Important interaction discovered: the sample Container Apps deployment creates an Azure-managed Container Apps environment in a `ME_*` managed resource group. Azure Container Apps attempted to create its platform load-balancer Public IP (`capp-svc-lb-ip`), and the new subscription-scope deny blocked that operation. The user approved a time-limited exception only for the managed resource group belonging to `connectivity-test-2026-10-20`, expiring 20 November 2026. The failed Azure-managed resource group was deleted; Azure's control-plane record for the Container Apps environment remained `ScheduledForDelete`. To support retry in the same approved managed group, the subscription deny assignment temporarily has a single `notScopes` entry matching exactly `ME_cae-connectivity-test-2026-10-20_rg-connectivity-test-2026-10-20-app_uksouth`. This is an exclusion for that future managed group, not a broader subscription exclusion. The environment was still `ScheduledForDelete` at 14:25 UTC; a second delete request was issued and no replacement deployment has succeeded. Restore the deny assignment with no `notScopes` after the environment is recreated, then use a time-limited exemption scoped to the actual managed group and verify both scopes.

## Cost query

- The `az costmanagement` command group was not installed in the current Azure CLI, so the query was run through the ARM REST endpoint.
- The first query returned HTTP `429 Too Many Requests`; one later retry succeeded but returned no rows for the validation tenant's four resource groups in the current month.
- No current cost value is recorded. An empty response means Azure returned no matching cost rows at query time; it is not proof that the tenant had zero accrued or eventual charges.
- After provisioning `connectivity-test-2026-10-20`, an ActualCost MonthToDate query filtered to its four resource groups returned the `Cost`, `UsageDate`, and `Currency` columns but no rows. Actual-cost P&L and a usage-over-time chart therefore cannot be populated from this query yet. The alert budget is not a substitute for measured cost. Cost data can lag; re-query after Azure posts billable usage.

## Sample workload

- Existing tenant ID: `cib-rg-validation-02-20261020` in the shared platform subscription.
- App resource group: `rg-cib-rg-validation-02-20261020-app`.
- Container App: `saas-etya3lzysgomm`; Azure reported its resource creation time as `2026-10-20T12:17:46Z`.
- Image: `ghcr.io/ifunanyab/cloudinabox-sample-saas:e9bf258f8e954fa85863c2caf684fb9cfae1b11d`.
- The live `/health` response returned `status: healthy`, tenant ID `cib-rg-validation-02-20261020`, region `uksouth`, and the active platform subscription ID. This is a successful end-to-end workload check in a tenant-specific app group, but it is not a new subscription vending test.
- The browser screenshot of the live health response was captured in the Codex session. The local display capture restriction described above also prevented saving that screenshot into the repository.
- A new sample-app deployment was attempted in the retained `connectivity-test-2026-10-20` tenant. GitHub Actions successfully built/published the image and authenticated to Azure, but its service principal lacked `Microsoft.Resources/deployments/validate/action` on the new tenant app resource group. No role assignment was broadened for that identity. Retrying with the existing Owner identity reached Azure deployment, but failed because the subscription-scope Public IP deny blocked Container Apps' platform-created `capp-svc-lb-ip`. Azure created the managed resource group `ME_cae-connectivity-test-2026-10-20_rg-connectivity-test-2026-10-20-app_uksouth` and associated it with managed environment `cae-connectivity-test-2026-10-20`; the deployment operation is Failed with `RequestDisallowedByPolicy`. Therefore the new tenant currently has no deployed sample app or health URL. No VM resources were created either.

## Outstanding evidence

1. The revised one-way route check is complete: Network Watcher found no next hop from the validation spoke probe toward the retained tenant's private address. The probe VM remains deallocated in the validation tenant and still incurs disk storage charges; its 2-vCPU size currently consumes the full approved family quota. A reciprocal packet-level isolation check was not completed.
2. Decide whether a hub Firewall is needed for central inspection. A VPN Gateway is only necessary if the demonstrated scenario includes a remote/on-premises network. Neither was deployed in this session.
3. Retry Cost Management after throttling clears or configure a scheduled actual-cost export; keep budget alerts and actual cost reporting distinct.
4. Azure has accepted deletion of the failed ACA environment but still reports it `ScheduledForDelete` (last checked 2026-10-20 14:27 UTC; the managed-resource-group field has since become null). A repeated delete request was issued. Wait for its control-plane record to clear, then retry the sample workload deployment using only the approved managed-group exception. If successful, confirm `/health`, tenant identity, resource inventory, and deprovisioning behavior before marking that evidence complete.
5. Conduct the usability study with real participants after appropriate supervisor/ethics review. The task sheet, consent draft, blank data templates, and analysis plan are provided separately; they contain no participant results.
