"""Provision isolated tenant resource groups in the active Azure subscription."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import subprocess
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

load_dotenv()
PROJECT_ROOT = Path(__file__).resolve().parent.parent
INFRASTRUCTURE_DIR = PROJECT_ROOT / "infrastructure"
PARAMETERS_DIR = INFRASTRUCTURE_DIR / "parameters"
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


def validate_bicep() -> None:
    for file in [INFRASTRUCTURE_DIR / "main.bicep", *sorted((INFRASTRUCTURE_DIR / "modules").glob("*.bicep"))]:
        result = run_az(["bicep", "build", "--file", str(file), "--stdout"])
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"Bicep build failed: {file.name}")
    for file in sorted(PARAMETERS_DIR.glob("*.bicepparam")):
        with tempfile.NamedTemporaryFile(suffix=".json") as output:
            result = run_az(["bicep", "build-params", "--file", str(file), "--outfile", output.name])
            if result.returncode:
                raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"Parameter validation failed: {file.name}")


def profile_parameters(profile: Path) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(suffix=".json") as output:
        result = run_az(["bicep", "build-params", "--file", str(profile), "--outfile", output.name])
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"Could not read {profile.name}")
        parsed = json.loads(Path(output.name).read_text(encoding="utf-8"))
    values = {key: value["value"] for key, value in parsed["parameters"].items()}
    tenant = {
        "tenant_id": values["tenantId"], "environment": values["environment"],
        "owner": values["owner"], "location": values["location"],
        "monthly_budget": values["monthlyBudgetAmount"],
    }
    validate_tenant(tenant)
    return values


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
    for second_octet in range(10, 256):
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


def deploy_profile(profile: Path, subscription_id: str, *, dry_run: bool) -> dict[str, Any]:
    values = profile_parameters(profile)
    tenant_id = values["tenantId"]
    location = values["location"]
    address = allocate_address_space(tenant_id, subscription_id)
    param_file = write_deployment_parameters(values, address)
    deployment_name = f"cloudinabox-{tenant_id}"
    base = ["deployment", "sub", "what-if", "--name", deployment_name,
            "--location", location, "--subscription", subscription_id,
            "--template-file", str(INFRASTRUCTURE_DIR / "main.bicep"), "--parameters", str(param_file)]
    try:
        result = run_az(base)
        if result.returncode:
            return {"tenant_id": tenant_id, "status": "failed", "phase": "what-if",
                    "subscription_id": subscription_id, "address_space": str(address),
                    "error": result.stderr.strip() or result.stdout.strip()}
        if dry_run:
            return {"tenant_id": tenant_id, "status": "validated", "phase": "what-if",
                    "subscription_id": subscription_id, "address_space": str(address),
                    "deployment_name": deployment_name}
        create = [*base]
        create[2] = "create"
        result = run_az([*create, "-o", "json"])
        if result.returncode:
            return {"tenant_id": tenant_id, "status": "failed", "phase": "deployment",
                    "subscription_id": subscription_id, "address_space": str(address),
                    "error": result.stderr.strip() or result.stdout.strip()}
        return {"tenant_id": tenant_id, "status": "success", "phase": "deployment",
                "subscription_id": subscription_id,
                "address_space": str(address), "deployment_name": deployment_name}
    finally:
        param_file.unlink(missing_ok=True)


def vend_tenant(
    tenant: dict[str, Any], *, dry_run: bool = True,
    on_phase: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Deploy one portal request into the active subscription."""
    validate_tenant(tenant)
    values = {
        "tenantId": tenant["tenant_id"], "environment": tenant["environment"],
        "owner": tenant["owner"], "location": tenant["location"],
        "monthlyBudgetAmount": int(tenant["monthly_budget"]),
        "budgetContactEmail": os.getenv("BUDGET_CONTACT_EMAIL") or tenant["owner"],
        "budgetStartDate": date.today().replace(day=1).isoformat() + "T00:00:00Z",
    }
    subscription_id = active_subscription_id()
    address = allocate_address_space(tenant["tenant_id"], subscription_id)
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

    subscription_id = active_subscription_id()
    if not expected_subscription_id or subscription_id != expected_subscription_id:
        raise RuntimeError("The active Azure subscription does not match this tenant's recorded subscription; no resources were deleted.")

    if os.getenv("APP_ENV", "development").lower() == "production":
        from automation.arm_client import AzureArmClient
        arm = AzureArmClient(subscription_id)
        group_names = {f"rg-{tenant_id}-{suffix}" for suffix in ("network", "app", "data", "monitoring")}
        owned_groups = []
        for group in arm.list_resource_groups():
            if group.get("name") not in group_names:
                continue
            tags = group.get("tags") or {}
            if tags.get("TenantId") != tenant_id or tags.get("Project") != "CloudInABox":
                raise RuntimeError(f"Resource group {group['name']} does not have the expected tenant ownership tags; no resources were deleted.")
            owned_groups.append(group["name"])
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
    configured = active_subscription_id()
    if not subscription_id or configured != subscription_id:
        raise RuntimeError("The active Azure subscription does not match this tenant's recorded subscription.")

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

    policies = ["policy-allowed-locations", "policy-required-tenant-id", "policy-required-environment"]
    for group_name in groups:
        for policy_name in policies:
            resource_id = f"/subscriptions/{subscription_id}/resourceGroups/{group_name}/providers/Microsoft.Authorization/policyAssignments/{policy_name}"
            policy = get(resource_id, "policy")
            add_check(f"Policy {policy_name} on {group_name}", resource_id, "assignment exists",
                      "present" if policy else "missing", bool(policy),
                      {"displayName": ((policy or {}).get("properties") or {}).get("displayName")})

    budget_id = f"/subscriptions/{subscription_id}/providers/Microsoft.Consumption/budgets/budget-{tenant_id}"
    budget = get(budget_id, "budget")
    budget_properties = (budget or {}).get("properties") or {}
    dimensions = ((budget_properties.get("filter") or {}).get("dimensions") or {})
    budget_groups = set(dimensions.get("values") or [])
    add_check("Tenant monthly budget", budget_id, "budget exists and filters to the four tenant resource groups",
              "missing" if not budget else {"amount": budget_properties.get("amount"), "timeGrain": budget_properties.get("timeGrain"), "resourceGroups": sorted(budget_groups)},
              bool(budget and set(groups).issubset(budget_groups)))

    passed = sum(1 for check in checks if check["passed"])
    return {"verified_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "subscription_id": subscription_id, "tenant_id": tenant_id,
            "passed": passed, "total": len(checks), "all_passed": passed == len(checks),
            "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision isolated tenants in the active Azure subscription.")
    parser.add_argument("--tenant-id", default="tenant-b")
    parser.add_argument("--environment", choices=sorted(ALLOWED_ENVIRONMENTS), default="dev")
    parser.add_argument("--owner", default="platform-team")
    parser.add_argument("--location", default=os.getenv("AZURE_LOCATION", "uksouth"))
    parser.add_argument("--monthly-budget", type=int, default=50)
    parser.add_argument("--all-profiles", action="store_true", help="Process all configured tenant parameter profiles.")
    parser.add_argument("--deploy", action="store_true", help="Run Azure what-if and deploy the tenant resources.")
    args = parser.parse_args()
    try:
        validate_bicep()
        subscription_id = active_subscription_id()
        if args.all_profiles:
            profiles = sorted(PARAMETERS_DIR.glob("*.bicepparam"))
            results = [deploy_profile(profile, subscription_id, dry_run=not args.deploy) for profile in profiles]
        else:
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
