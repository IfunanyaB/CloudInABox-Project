"""Provision isolated tenant resource groups in the shared Azure subscription."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import subprocess
import tempfile
from urllib.parse import quote
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

load_dotenv()
PROJECT_ROOT = Path(__file__).resolve().parent.parent
INFRASTRUCTURE_DIR = PROJECT_ROOT / "infrastructure"
ALLOWED_ENVIRONMENTS = {"dev"}
ALLOWED_LOCATIONS = {"uksouth"}
MAX_REQUEST_BUDGET_EUR = int(os.getenv("MAX_REQUEST_BUDGET_EUR", "1000") or "1000")

PORTAL_ENVIRONMENT_OPTIONS = [
    {"value": "dev", "label": "Development", "enabled": True},
    {"value": "test", "label": "Test", "enabled": False,
     "reason": "The active subscription policy currently requires Environment=dev."},
    {"value": "prod", "label": "Production", "enabled": False,
     "reason": "The active subscription policy currently requires Environment=dev."},
]
PORTAL_LOCATION_OPTIONS = [
    {"value": "uksouth", "label": "UK South", "enabled": True},
    {"value": "westeurope", "label": "West Europe", "enabled": False,
     "reason": "The active subscription currently allows UK South only."},
    {"value": "northeurope", "label": "North Europe", "enabled": False,
     "reason": "The active subscription currently allows UK South only."},
]


def run_az(arguments: list[str], timeout: int = 1800) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["az", *arguments], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise RuntimeError("Azure CLI (az) is not installed or not on PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Azure CLI command timed out after {timeout} seconds.") from exc


def az_json(arguments: list[str], description: str) -> Any:
    result = run_az(arguments)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"{description} failed.")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Azure CLI returned invalid JSON while {description}.") from exc


def validate_tenant(tenant: dict[str, Any]) -> None:
    for key in ("tenant_id", "environment", "owner", "location", "monthly_budget"):
        if tenant.get(key) is None or str(tenant[key]).strip() == "":
            raise ValueError(f"Missing required tenant field: {key}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,38}[a-z0-9]", str(tenant["tenant_id"])):
        raise ValueError("tenant_id must be 3–40 lowercase letters, digits, or hyphens.")
    if tenant["environment"] not in ALLOWED_ENVIRONMENTS:
        raise ValueError("This subscription currently permits the Development environment only.")
    if not re.fullmatch(r"[a-z0-9]+", str(tenant["location"])):
        raise ValueError("location must be an Azure region name using lowercase letters and digits.")
    if tenant["location"] not in ALLOWED_LOCATIONS:
        raise ValueError("This subscription currently permits the UK South region only.")
    if not re.fullmatch(r"[A-Za-z0-9._@+-]{1,120}", str(tenant["owner"])):
        raise ValueError("owner contains unsupported characters.")
    try:
        amount = int(tenant["monthly_budget"])
    except (TypeError, ValueError) as exc:
        raise ValueError("monthly_budget must be a positive whole number.") from exc
    if amount <= 0:
        raise ValueError("monthly_budget must be a positive whole number.")
    if amount > MAX_REQUEST_BUDGET_EUR:
        raise ValueError(f"monthly_budget cannot exceed the configured €{MAX_REQUEST_BUDGET_EUR} request limit.")


def active_subscription_id() -> str:
    configured = os.getenv("AZURE_SUBSCRIPTION_ID", "").strip()
    if os.getenv("APP_ENV", "development").lower() == "production":
        if not configured:
            raise RuntimeError("AZURE_SUBSCRIPTION_ID is required in the hosted environment.")
        from automation.arm_client import AzureArmClient
        if AzureArmClient(configured).subscription_state() != "Enabled":
            raise RuntimeError("The configured Azure subscription is not enabled.")
        return configured
    context = az_json(["account", "show", "--query", "{id:id,state:state}", "-o", "json"], "reading Azure context")
    selected = context.get("id", "")
    if context.get("state") != "Enabled":
        raise RuntimeError("The selected Azure subscription is not enabled.")
    if configured and configured != selected:
        account = az_json(["account", "list", "--query", f"[?id=='{configured}'].{{id:id,state:state}} | [0]", "-o", "json"], "checking configured subscription")
        if not account or account.get("state") != "Enabled":
            raise RuntimeError("AZURE_SUBSCRIPTION_ID must refer to an enabled subscription available to this account.")
        selected = configured
    return selected


def platform_subscription_id() -> str:
    """Return the configured shared subscription, using the Azure CLI context locally."""
    configured = os.getenv("AZURE_SUBSCRIPTION_ID", "").strip()
    if configured:
        return configured
    if os.getenv("APP_ENV", "development").lower() != "production":
        try:
            return active_subscription_id()
        except (RuntimeError, OSError, ValueError):
            return ""
    return ""


def tenant_subscription_id(
    tenant: dict[str, Any],
    platform_subscription_id: str,
    *,
    on_subscription_id: Callable[[str], None] | None = None,
) -> str:
    """Use a recorded subscription for existing tenants, else the shared platform subscription."""
    existing = str(tenant.get("subscription_id") or "").strip()
    if existing:
        return existing
    if on_subscription_id:
        on_subscription_id(platform_subscription_id)
    return platform_subscription_id


def hub_configuration(platform_subscription_id: str) -> dict[str, str | bool]:
    hub_subscription_id = os.getenv("HUB_SUBSCRIPTION_ID", platform_subscription_id).strip()
    hub_resource_group = os.getenv("HUB_RESOURCE_GROUP", "rg-cib-hub").strip()
    hub_vnet_name = os.getenv("HUB_VNET_NAME", "").strip()
    hub_vnet_id = (f"/subscriptions/{hub_subscription_id}/resourceGroups/{hub_resource_group}"
                   f"/providers/Microsoft.Network/virtualNetworks/{hub_vnet_name}") if hub_vnet_name else ""
    return {
        "subscription_id": hub_subscription_id,
        "resource_group": hub_resource_group,
        "vnet_name": hub_vnet_name,
        "vnet_id": hub_vnet_id,
        "firewall_private_ip": os.getenv("HUB_FIREWALL_PRIVATE_IP", "").strip(),
        "vpn_gateway_enabled": os.getenv("HUB_VPN_GATEWAY_ENABLED", "false").lower() == "true",
    }


def validate_bicep() -> None:
    files = [
        INFRASTRUCTURE_DIR / "main.bicep",
        INFRASTRUCTURE_DIR / "hub-network-deploy.bicep",
        INFRASTRUCTURE_DIR / "hub-network.bicep",
        INFRASTRUCTURE_DIR / "tenant-management-group-access.bicep",
        INFRASTRUCTURE_DIR / "platform-apps.bicep",
        PROJECT_ROOT / "sample-app" / "main.bicep",
        PROJECT_ROOT / "sample-app" / "app.bicep",
        *sorted((INFRASTRUCTURE_DIR / "modules").glob("*.bicep")),
    ]
    for file in files:
        result = run_az(["bicep", "build", "--file", str(file), "--stdout"])
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"Bicep build failed: {file.name}")
    for file in sorted(PARAMETERS_DIR.glob("*.bicepparam")):
        with tempfile.NamedTemporaryFile(suffix=".json") as output:
            result = run_az(["bicep", "build-params", "--file", str(file), "--outfile", output.name])
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"Parameter validation failed: {file.name}")


def allocate_address_space(tenant_id: str, subscription_id: str) -> ipaddress.IPv4Network:
    if os.getenv("APP_ENV", "development").lower() == "production":
        from automation.arm_client import AzureArmClient
        vnets = AzureArmClient(subscription_id).list_vnets()
        vnets = [{"name": item.get("name"), **item.get("properties", {})} for item in vnets]
    else:
        vnets = az_json(["network", "vnet", "list", "--subscription", subscription_id, "-o", "json"], "checking tenant VNet ranges")
    used: list[tuple[ipaddress.IPv4Network, bool]] = []
    own = None
    for vnet in vnets:
        prefixes = (vnet.get("addressSpace") or {}).get("addressPrefixes", [])
        for prefix in prefixes:
            network = ipaddress.ip_network(prefix, strict=True)
            is_own = vnet.get("name") == f"vnet-{tenant_id}"
            used.append((network, is_own))
            if is_own:
                own = network
    if own:
        if own.prefixlen != 16:
            raise RuntimeError(f"Existing VNet vnet-{tenant_id} uses {own}; expected a /16 for this template.")
        if sum(1 for v in vnets if v.get("name") == f"vnet-{tenant_id}") != 1:
            raise RuntimeError(f"Found multiple VNets named vnet-{tenant_id}.")
        if sum(1 for _, is_own in used if is_own) != 1:
            raise RuntimeError(f"Existing VNet vnet-{tenant_id} has an unexpected number of address ranges.")
        if any(own.overlaps(other) for other, is_own in used if not is_own):
            raise RuntimeError(f"Existing VNet address range {own} overlaps another VNet in the subscription.")
        return own
    for second_octet in range(30, 255):
        candidate = ipaddress.ip_network(f"10.{second_octet}.0.0/16")
        if not any(candidate.overlaps(other) for other, _ in used):
            return candidate
    raise RuntimeError("No non-overlapping /16 range is available in 10.0.0.0/8.")


def write_deployment_parameters(values: dict[str, Any], address: ipaddress.IPv4Network) -> Path:
    subnets = list(address.subnets(new_prefix=24))
    values.update({
        "tenantVnetAddressPrefix": str(address),
        "appSubnetPrefix": str(subnets[1]),
        "dataSubnetPrefix": str(subnets[2]),
        "managementSubnetPrefix": str(subnets[3]),
    })
    payload = {"$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
               "contentVersion": "1.0.0.0",
               "parameters": {key: {"value": value} for key, value in values.items()}}
    handle = tempfile.NamedTemporaryFile(mode="w", suffix=".parameters.json", delete=False)
    with handle:
        json.dump(payload, handle, indent=2)
    return Path(handle.name)


def vend_tenant(
    tenant: dict[str, Any], *, dry_run: bool = True,
    on_phase: Callable[[str], None] | None = None,
    on_subscription_id: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Provision one tenant's isolated resource groups in the active subscription."""
    validate_tenant(tenant)
    platform_subscription_id = active_subscription_id()
    hub = hub_configuration(platform_subscription_id)
    if not hub["vnet_id"]:
        raise RuntimeError("Tenant environment provisioning requires HUB_VNET_NAME and a provisioned shared hub VNet.")
    values = {
        "tenantId": tenant["tenant_id"], "environment": tenant["environment"],
        "owner": tenant["owner"], "location": tenant["location"],
        "monthlyBudgetAmount": int(tenant["monthly_budget"]),
        "budgetContactEmail": os.getenv("BUDGET_CONTACT_EMAIL") or tenant["owner"],
        "budgetStartDate": date.today().replace(day=1).isoformat() + "T00:00:00Z",
        "hubVnetId": hub["vnet_id"],
        "hubSubscriptionId": hub["subscription_id"],
        "hubResourceGroupName": hub["resource_group"],
        "hubVnetName": hub["vnet_name"],
        "hubFirewallPrivateIp": hub["firewall_private_ip"],
        "hubVpnGatewayEnabled": hub["vpn_gateway_enabled"],
    }
    subscription_id = tenant_subscription_id(
        tenant, platform_subscription_id,
        on_subscription_id=on_subscription_id if not dry_run else None,
    )
    address = ipaddress.ip_network(tenant.get("address_space") or allocate_address_space(tenant["tenant_id"], subscription_id), strict=True)
    details = {
        "tenant_id": tenant["tenant_id"],
        "tenant_name": tenant.get("tenant_name", tenant["tenant_id"]),
        "environment": tenant["environment"],
        "owner": tenant["owner"],
        "location": tenant["location"],
        "monthly_budget": int(tenant["monthly_budget"]),
        "subscription_id": subscription_id,
        "address_space": str(address),
        "deployment_name": f"cloudinabox-{tenant['tenant_id']}",
        "hub_vnet_id": hub["vnet_id"],
    }
    if os.getenv("APP_ENV", "development").lower() == "production":
        from automation.arm_client import AzureArmClient
        template_path = INFRASTRUCTURE_DIR / "main.json"
        if not template_path.is_file():
            return {**details, "status": "failed", "phase": "template", "error": "Compiled ARM template is missing from the hosted package."}
        template = json.loads(template_path.read_text(encoding="utf-8"))
        parameters = {
            "tenantId": tenant["tenant_id"], "environment": tenant["environment"],
            "owner": tenant["owner"], "location": tenant["location"],
            "monthlyBudgetAmount": int(tenant["monthly_budget"]),
            "budgetContactEmail": os.getenv("BUDGET_CONTACT_EMAIL") or tenant["owner"],
            "budgetStartDate": date.today().replace(day=1).isoformat() + "T00:00:00Z",
            "tenantVnetAddressPrefix": str(address),
            "appSubnetPrefix": str(list(address.subnets(new_prefix=24))[1]),
            "dataSubnetPrefix": str(list(address.subnets(new_prefix=24))[2]),
            "managementSubnetPrefix": str(list(address.subnets(new_prefix=24))[3]),
            "hubVnetId": hub["vnet_id"],
            "hubSubscriptionId": hub["subscription_id"],
            "hubResourceGroupName": hub["resource_group"],
            "hubVnetName": hub["vnet_name"],
            "hubFirewallPrivateIp": hub["firewall_private_ip"],
            "hubVpnGatewayEnabled": hub["vpn_gateway_enabled"],
        }
        parameter_values = {key: {"value": value} for key, value in parameters.items()}
        arm = AzureArmClient(subscription_id)
        phase = "what-if"
        try:
            if on_phase:
                on_phase(phase)
            what_if = arm.subscription_what_if(details["deployment_name"], tenant["location"], template, parameter_values)
            if str(what_if.get("status", "Succeeded")).lower() not in {"succeeded", "success"}:
                raise RuntimeError(str(what_if.get("error") or "Azure what-if did not succeed."))
            if dry_run:
                return {**details, "status": "validated", "phase": "what-if"}
            phase = "deployment"
            if on_phase:
                on_phase(phase)
            arm.create_subscription_deployment(details["deployment_name"], tenant["location"], template, parameter_values)
            return {**details, "status": "success", "phase": "complete"}
        except Exception as exc:
            return {**details, "status": "failed", "phase": phase, "error": str(exc)}

    parameter_file = write_deployment_parameters(values, address)
    try:
        template = INFRASTRUCTURE_DIR / "main.bicep"
        if on_phase:
            on_phase("what-if")
        command = ["deployment", "sub", "what-if", "--name",
                   f"cloudinabox-{tenant['tenant_id']}", "--location", tenant["location"],
                   "--subscription", subscription_id, "--template-file", str(template),
                   "--parameters", str(parameter_file)]
        result = run_az(command)
        if result.returncode:
            return {**details, "status": "failed", "phase": "what-if",
                    "error": result.stderr.strip() or result.stdout.strip()}
        if dry_run:
            return {**details, "status": "validated", "phase": "what-if"}
        if on_phase:
            on_phase("deployment")
        command[2] = "create"
        result = run_az(command + ["-o", "json"])
        if result.returncode:
            return {**details, "status": "failed", "phase": "deployment",
                    "error": result.stderr.strip() or result.stdout.strip()}
        return {**details, "status": "success", "phase": "complete"}
    finally:
        parameter_file.unlink(missing_ok=True)


def deprovision_tenant(
    tenant_id: str,
    *,
    expected_subscription_id: str,
    on_phase: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Delete only the resource groups and budget owned by one recorded tenant."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,38}[a-z0-9]", tenant_id):
        raise ValueError("Invalid tenant ID; refusing to construct Azure resource names.")

    subscription_id = str(expected_subscription_id or "")
    if not subscription_id:
        raise RuntimeError("No Azure subscription ID is recorded for this tenant; no resources were deleted.")

    platform_subscription_id = active_subscription_id()

    if os.getenv("APP_ENV", "development").lower() == "production":
        from automation.arm_client import AzureArmClient
        arm = AzureArmClient(subscription_id)
        hub = hub_configuration(platform_subscription_id)
        group_names = {f"rg-{tenant_id}-{suffix}" for suffix in ("network", "app", "data", "monitoring")}
        owned_groups = []
        for group in arm.list_resource_groups():
            if group.get("name") not in group_names:
                continue
            tags = group.get("tags") or {}
            if tags.get("TenantId") != tenant_id or tags.get("Project") != "CloudInABox":
                raise RuntimeError(f"Resource group {group['name']} does not have the expected tenant ownership tags; no resources were deleted.")
            owned_groups.append(group["name"])
        if hub["vnet_id"]:
            AzureArmClient(str(hub["subscription_id"])).delete_virtual_network_peering(str(hub["vnet_id"]), f"to-{tenant_id}")
        budget_name = f"budget-{tenant_id}"
        has_budget = any(item.get("name") == budget_name for item in arm.list_budgets())
        removed_groups = []
        for group_name in owned_groups:
            if on_phase:
                on_phase(f"deleting-{group_name}")
            arm.delete_resource_group(group_name)
            removed_groups.append(group_name)
        if has_budget:
            if on_phase:
                on_phase("deleting-budget")
            arm.delete_budget(budget_name)
        return {"tenant_id": tenant_id, "subscription_id": subscription_id,
                "removed_resource_groups": removed_groups, "removed_budget": has_budget}

    group_names = [f"rg-{tenant_id}-{suffix}" for suffix in ("network", "app", "data", "monitoring")]
    groups = az_json(["group", "list", "--subscription", subscription_id, "-o", "json"], "listing tenant resource groups")
    owned_groups = []
    for group in groups:
        if group.get("name") not in group_names:
            continue
        tags = group.get("tags") or {}
        if tags.get("TenantId") != tenant_id or tags.get("Project") != "CloudInABox":
            raise RuntimeError(f"Resource group {group['name']} does not have the expected tenant ownership tags; no resources were deleted.")
        owned_groups.append(group["name"])

    budgets = az_json(["consumption", "budget", "list", "--subscription", subscription_id, "-o", "json"], "listing subscription budgets")
    budget_name = f"budget-{tenant_id}"
    has_budget = any(item.get("name") == budget_name for item in budgets)

    from automation.arm_client import AzureArmClient
    hub = hub_configuration(platform_subscription_id)
    if hub["vnet_id"]:
        AzureArmClient(str(hub["subscription_id"])).delete_virtual_network_peering(str(hub["vnet_id"]), f"to-{tenant_id}")

    removed_groups = []
    for group_name in owned_groups:
        if on_phase:
            on_phase(f"deleting-{group_name}")
        result = run_az(["group", "delete", "--name", group_name, "--subscription", subscription_id, "--yes"])
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"Could not delete resource group {group_name}.")
        removed_groups.append(group_name)

    if has_budget:
        if on_phase:
            on_phase("deleting-budget")
        result = run_az(["consumption", "budget", "delete", "--budget-name", budget_name, "--subscription", subscription_id, "--output", "none"])
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"Could not delete budget {budget_name}.")

    return {"tenant_id": tenant_id, "subscription_id": subscription_id,
            "removed_resource_groups": removed_groups, "removed_budget": has_budget}


def verify_tenant_resources(tenant: dict[str, Any]) -> dict[str, Any]:
    """Read the deployed baseline directly from Azure and return a verifiable report."""
    tenant_id = str(tenant.get("tenant_id", ""))
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,38}[a-z0-9]", tenant_id):
        raise ValueError("Invalid tenant ID; refusing to construct Azure resource IDs.")
    subscription_id = str(tenant.get("subscription_id") or "")
    if not subscription_id:
        raise RuntimeError("The tenant has no recorded Azure subscription ID.")

    from automation.arm_client import AzureArmClient
    arm = AzureArmClient(subscription_id)
    api_versions = {
        "group": "2021-04-01",
        "network": "2024-05-01",
        "workspace": "2023-09-01",
        "policy": "2025-03-01",
        "budget": "2023-05-01",
    }
    checks: list[dict[str, Any]] = []

    def get(resource_id: str, version_key: str) -> dict[str, Any] | None:
        try:
            _, body, _ = arm.request("GET", f"{resource_id}?api-version={api_versions[version_key]}")
            return body
        except RuntimeError as exc:
            if "failed (404)" in str(exc):
                return None
            raise

    groups = [f"rg-{tenant_id}-{suffix}" for suffix in ("network", "app", "data", "monitoring")]

    def add_check(name: str, resource_id: str, expected: str, actual: Any, ok: bool, evidence: dict | None = None) -> None:
        checks.append({"name": name, "resource_id": resource_id, "expected": expected,
                       "actual": actual, "passed": bool(ok), "evidence": evidence or {}})

    for group_name in groups:
        path = f"/subscriptions/{subscription_id}/resourceGroups/{group_name}"
        group = get(path, "group")
        tags = (group or {}).get("tags") or {}
        valid = bool(group and tags.get("TenantId") == tenant_id and tags.get("Project") == "CloudInABox")
        add_check(f"Resource group {group_name}", path, "exists with matching tenant ownership tags",
                  "missing" if not group else {"TenantId": tags.get("TenantId"), "Project": tags.get("Project")}, valid,
                  {"location": (group or {}).get("location")})
        if subscription_id == platform_subscription_id():
            for policy_name in ("policy-allowed-locations", "policy-required-tenant-id",
                                "policy-required-environment"):
                assignment_id = f"{path}/providers/Microsoft.Authorization/policyAssignments/{policy_name}"
                assignment = get(assignment_id, "policy")
                add_check(f"{group_name}: {policy_name}", assignment_id,
                          "tenant-scoped policy assignment exists", "present" if assignment else "missing",
                          bool(assignment), {"displayName": ((assignment or {}).get("properties") or {}).get("displayName")})

    vnet_id = f"/subscriptions/{subscription_id}/resourceGroups/rg-{tenant_id}-network/providers/Microsoft.Network/virtualNetworks/vnet-{tenant_id}"
    vnet = get(vnet_id, "network")
    subnet_names = sorted(item.get("name") for item in ((vnet or {}).get("properties") or {}).get("subnets", []))
    expected_subnets = ["snet-app", "snet-data", "snet-management"]
    add_check("Tenant virtual network", vnet_id, "exists with all three tenant subnets",
              "missing" if not vnet else {"addressPrefixes": ((vnet.get("properties") or {}).get("addressSpace") or {}).get("addressPrefixes", []), "subnets": subnet_names},
              bool(vnet and all(name in subnet_names for name in expected_subnets)))

    workspace_id = f"/subscriptions/{subscription_id}/resourceGroups/rg-{tenant_id}-monitoring/providers/Microsoft.OperationalInsights/workspaces/law-{tenant_id}"
    workspace = get(workspace_id, "workspace")
    retention = ((workspace or {}).get("properties") or {}).get("retentionInDays")
    add_check("Log Analytics workspace", workspace_id, "exists with 30-day retention",
              "missing" if not workspace else {"retentionInDays": retention, "sku": ((workspace.get("properties") or {}).get("sku") or {}).get("name")},
              bool(workspace and retention == 30))

    if subscription_id != platform_subscription_id():
        for policy_name in ("cib-required-tenant-id", "cib-required-environment", "cib-deny-public-ip"):
            resource_id = f"/subscriptions/{subscription_id}/providers/Microsoft.Authorization/policyAssignments/{policy_name}"
            policy = get(resource_id, "policy")
            add_check(f"Subscription policy {policy_name}", resource_id, "legacy tenant subscription assignment exists",
                      "present" if policy else "missing", bool(policy),
                      {"displayName": ((policy or {}).get("properties") or {}).get("displayName")})

    budget_id = f"/subscriptions/{subscription_id}/providers/Microsoft.Consumption/budgets/budget-{tenant_id}"
    budget = get(budget_id, "budget")
    budget_properties = (budget or {}).get("properties") or {}
    dimensions = ((budget_properties.get("filter") or {}).get("dimensions") or {})
    expected_groups = groups
    budget_groups = dimensions.get("values", []) if isinstance(dimensions, dict) else []
    budget_is_tenant_scoped = (
        dimensions.get("name") == "ResourceGroupName"
        and dimensions.get("operator") == "In"
        and set(budget_groups) == set(expected_groups)
    )
    expected_budget_scope = subscription_id == platform_subscription_id()
    budget_scope_valid = budget_is_tenant_scoped if expected_budget_scope else not dimensions
    add_check("Tenant monthly budget", budget_id,
              "monthly budget filtered to this tenant's four resource groups" if expected_budget_scope else "legacy budget scoped to the dedicated tenant subscription",
              "missing" if not budget else {"amount": budget_properties.get("amount"), "timeGrain": budget_properties.get("timeGrain"), "filter": budget_properties.get("filter")},
              bool(budget and budget_properties.get("timeGrain") == "Monthly" and budget_scope_valid))

    # Include a live inventory and real Cost Management/Log Analytics responses
    # alongside the baseline verification. Keep each data source independently
    # fallible so missing permissions never hide the ARM resource inventory.
    resource_groups = []
    tenant_group_objects = [item for item in arm.list_resource_groups()
                            if item.get("tags", {}).get("TenantId") == tenant_id
                            or item.get("name") in groups]
    for group_object in tenant_group_objects:
        group_name = group_object.get("name")
        if not group_name:
            continue
        group_path = f"/subscriptions/{subscription_id}/resourceGroups/{group_name}"
        resources = []
        try:
            path = f"{group_path}/resources?api-version=2021-04-01"
            while path:
                _, page, _ = arm.request("GET", path)
                for resource in page.get("value", []):
                    properties = resource.get("properties") or {}
                    resource_item = {
                        "name": resource.get("name"), "type": resource.get("type"),
                        "location": resource.get("location"), "id": resource.get("id"),
                        "provisioning_state": properties.get("provisioningState") or resource.get("provisioningState"),
                        "sku": resource.get("sku"), "metrics": [], "metrics_state": "unavailable",
                    }
                    try:
                        definitions_path = f"{resource['id']}/providers/Microsoft.Insights/metricDefinitions?api-version=2018-01-01"
                        _, definitions, _ = arm.request("GET", definitions_path, timeout=30)
                        definition_items = definitions.get("value", [])
                        metric_names = [item.get("name", {}).get("value") for item in definition_items[:3]]
                        metric_names = [name for name in metric_names if name]
                        if metric_names:
                            end_time = datetime.now(timezone.utc).replace(microsecond=0)
                            start_time = end_time - timedelta(hours=24)
                            # Azure Monitor's timespan parser expects UTC Z values;
                            # Python's +00:00 offset form is rejected by ARM.
                            timespan = (f"{start_time.strftime('%Y-%m-%dT%H:%M:%SZ')}/"
                                        f"{end_time.strftime('%Y-%m-%dT%H:%M:%SZ')}")
                            metric_namespace = next(
                                (item.get("namespace") for item in definition_items if item.get("namespace")),
                                None,
                            )
                            metric_path = (f"{resource['id']}/providers/Microsoft.Insights/metrics"
                                           f"?api-version=2018-01-01&metricnames={quote(','.join(metric_names))}"
                                           f"&timespan={quote(timespan)}&interval=PT1H&aggregation=Average")
                            if metric_namespace:
                                metric_path += f"&metricnamespace={quote(metric_namespace)}"
                            _, metric_result, _ = arm.request("GET", metric_path, timeout=30)
                            for metric in metric_result.get("value", []):
                                points = [point for series in metric.get("timeseries", []) for point in series.get("data", [])]
                                recent = next((point for point in reversed(points) if point.get("average") is not None), None)
                                if recent:
                                    resource_item["metrics"].append({
                                        "name": metric.get("name", {}).get("localizedValue") or metric.get("name", {}).get("value"),
                                        "unit": metric.get("unit"), "timestamp": recent.get("timeStamp"),
                                        "average": recent.get("average"),
                                    })
                            resource_item["metrics_state"] = "available" if resource_item["metrics"] else "no_data"
                        else:
                            resource_item["metrics_state"] = "not_supported"
                    except Exception as metrics_exc:
                        error_text = str(metrics_exc)
                        if "not a supported platform metric namespace" in error_text.lower():
                            resource_item["metrics_state"] = "not_supported"
                        else:
                            resource_item["metrics_state"] = "unavailable"
                            resource_item["metrics_error"] = error_text
                    resources.append(resource_item)
                path = page.get("nextLink")
            inventory_state = "available"
            inventory_error = None
        except Exception as exc:
            inventory_state, inventory_error = "unavailable", str(exc)
        resource_groups.append({"name": group_name, "resource_id": group_path,
                                "resources": resources, "state": inventory_state,
                                "error": inventory_error})

    cost = {"state": "unavailable", "currency": None, "month_to_date": None, "daily": [], "by_resource_group": [], "error": None}
    try:
        cost_path = f"/subscriptions/{subscription_id}/providers/Microsoft.CostManagement/query?api-version=2023-03-01"
        cost_body = {
            "type": "Usage", "timeframe": "MonthToDate",
            "dataset": {"granularity": "Daily",
                "aggregation": {"totalCost": {"name": "PreTaxCost", "function": "Sum"}},
                "grouping": [{"type": "Dimension", "name": "ResourceGroup"}],
                "filter": {"dimensions": {"name": "ResourceGroup", "operator": "In", "values": groups}}},
        }
        _, result, _ = arm.request("POST", cost_path, cost_body, timeout=120)
        columns = [column.get("name") for column in result.get("properties", {}).get("columns", [])]
        rows = result.get("properties", {}).get("rows", [])
        cost_rows = [dict(zip(columns, row)) for row in rows]
        amount_key = next((key for key in columns if key and key.lower() in {"pretaxcost", "totalcost"}), None)
        currency_key = next((key for key in columns if key and key.lower() == "currency"), None)
        date_key = next((key for key in columns if key and key.lower() == "usagedate"), None)
        group_key = next((key for key in columns if key and key.lower() in {"resourcegroup", "resourcegroupname"}), None)
        by_day, by_group = {}, {}
        total = 0.0
        for row in cost_rows:
            amount = float(row.get(amount_key) or 0) if amount_key else 0.0
            total += amount
            if date_key:
                day = str(row.get(date_key))
                if day.isdigit() and len(day) == 8:
                    day = f"{day[:4]}-{day[4:6]}-{day[6:8]}"
                by_day[day] = by_day.get(day, 0.0) + amount
            if group_key:
                group = str(row.get(group_key) or "Unknown")
                by_group[group] = by_group.get(group, 0.0) + amount
        cost = {"state": "available" if cost_rows else "no_data", "currency": next((str(row.get(currency_key)) for row in cost_rows if row.get(currency_key)), None),
                "month_to_date": total if cost_rows else None, "daily": [{"date": key, "amount": value} for key, value in sorted(by_day.items())],
                "by_resource_group": [{"name": key, "amount": value} for key, value in sorted(by_group.items())], "error": None}
    except Exception as exc:
        cost["error"] = str(exc)

    logs = {"state": "unavailable", "tables": [], "error": None}
    workspace_customer_id = ((workspace or {}).get("properties") or {}).get("customerId")
    if workspace_customer_id:
        try:
            token = arm.credential.get_token("https://api.loganalytics.io/.default").token
            from urllib.request import Request, urlopen
            query_url = f"https://api.loganalytics.azure.com/v1/workspaces/{workspace_customer_id}/query"
            # Activity logs appear only when diagnostic settings route them to
            # this workspace. Container Apps logs are emitted to the custom
            # tables below when the optional tenant workload is deployed.
            query_data = json.dumps({"query": (
                "union isfuzzy=true withsource=SourceTable "
                "ContainerAppConsoleLogs_CL, ContainerAppSystemLogs_CL, AzureActivity "
                "| where TimeGenerated > ago(24h) "
                "| summarize Events=count() by SourceTable "
                "| order by Events desc | take 20"
            )}).encode()
            req = Request(query_url, data=query_data, method="POST", headers={
                "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
            with urlopen(req, timeout=45) as response:
                logs_response = json.loads(response.read() or b"{}")
            logs = {"state": "available", "tables": logs_response.get("tables", []), "error": None}
        except Exception as exc:
            logs["error"] = str(exc)
    else:
        logs["error"] = "The tenant Log Analytics workspace could not be read."

    passed = sum(1 for check in checks if check["passed"])
    return {"verified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "subscription_id": subscription_id, "tenant_id": tenant_id,
            "passed": passed, "total": len(checks), "all_passed": passed == len(checks),
            "checks": checks, "resource_groups": resource_groups, "cost": cost, "logs": logs,
            "telemetry_note": "Platform metrics are resource-specific; this deployment currently provisions networking and monitoring foundations rather than compute workloads."}


def main() -> int:
    parser = argparse.ArgumentParser(description="Vend an isolated Azure subscription and landing zone.")
    parser.add_argument("--tenant-id", default="tenant-b")
    parser.add_argument("--environment", choices=sorted(ALLOWED_ENVIRONMENTS), default="dev")
    parser.add_argument("--owner", default="platform-team")
    parser.add_argument("--location", default=os.getenv("AZURE_LOCATION", "uksouth"))
    parser.add_argument("--monthly-budget", type=int, default=50)
    parser.add_argument("--deploy", action="store_true", help="Run Azure what-if and deploy the tenant resources.")
    args = parser.parse_args()
    try:
        validate_bicep()
        subscription_id = active_subscription_id()
        tenant = {"tenant_id": args.tenant_id, "environment": args.environment, "owner": args.owner,
                  "location": args.location, "monthly_budget": args.monthly_budget}
        results = [vend_tenant(tenant, dry_run=not args.deploy)]
    except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2))
        return 1
    print(json.dumps({"subscription_id": subscription_id, "results": results}, indent=2))
    return 0 if all(item["status"] in ({"success"} if args.deploy else {"validated"}) for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
