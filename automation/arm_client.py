"""Small Azure Resource Manager REST client for managed-identity deployments."""

from __future__ import annotations

import json
import time
import uuid
from urllib.parse import quote
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class AzureArmError(RuntimeError):
    """ARM request failure with structured status for safe retry decisions."""

    def __init__(self, method: str, status_code: int, code: str, message: str, retry_after: float | None = None):
        self.method = method
        self.status_code = status_code
        self.code = code
        self.retry_after = retry_after
        super().__init__(f"Azure Resource Manager {method} failed ({status_code} {code}): {message}")


def _error_message(error: dict[str, Any], fallback: str) -> tuple[str, str]:
    """Unwrap ARM's occasionally JSON-encoded nested error messages."""
    code = str(error.get("code") or "AzureError")
    message = str(error.get("message") or fallback)
    for _ in range(3):
        # Some Azure subscription responses append their serialized error object
        # to the human-readable message. Keep the actionable sentence only.
        embedded_error = message.find('{"error":')
        if embedded_error > 0:
            message = message[:embedded_error].rstrip(" .")
        try:
            nested = json.loads(message)
        except (TypeError, json.JSONDecodeError):
            break
        if not isinstance(nested, dict):
            break
        nested_error = nested.get("error") if isinstance(nested.get("error"), dict) else nested
        code = str(nested_error.get("code") or code)
        next_message = nested_error.get("message")
        if not next_message or str(next_message) == message:
            break
        message = str(next_message)
    return code, message


class AzureArmClient:
    def __init__(self, subscription_id: str, credential=None):
        if credential is None:
            from azure.identity import DefaultAzureCredential
            credential = DefaultAzureCredential()
        self.subscription_id = subscription_id
        self.credential = credential
        self.base = "https://management.azure.com"

    def request(self, method: str, path: str, body: dict | None = None, timeout: int = 60) -> tuple[int, dict, dict]:
        url = path if path.startswith("https://") else f"{self.base}{path}"
        if urlparse(url).hostname != "management.azure.com":
            raise RuntimeError("Azure returned an unexpected management endpoint.")
        token = self.credential.get_token("https://management.azure.com/.default").token
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(url, data=payload, method=method, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        try:
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
                data = json.loads(raw) if raw else {}
                return response.status, data, dict(response.headers.items())
        except HTTPError as exc:
            raw = exc.read()
            try:
                data = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                data = {"error": {"message": raw.decode("utf-8", "replace")[:2000]}}
            error = data.get("error") or {}
            code, detail = _error_message(error, str(data))
            retry_after = None
            try:
                retry_after = float(exc.headers.get("Retry-After", ""))
            except (TypeError, ValueError):
                pass
            raise AzureArmError(method, exc.code, code, detail, retry_after) from exc
        except URLError as exc:
            raise RuntimeError(f"Could not reach Azure Resource Manager: {exc.reason}") from exc

    def wait_operation(self, status: int, data: dict, headers: dict, timeout: int = 1800) -> dict:
        async_url = next((value for key, value in headers.items() if key.lower() == "azure-asyncoperation"), None)
        location_url = next((value for key, value in headers.items() if key.lower() == "location"), None)
        poll_url = async_url or location_url
        if status not in {201, 202} and not poll_url:
            return data
        if not poll_url:
            return data
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(5)
            _, result, _ = self.request("GET", poll_url)
            state = str(result.get("status") or result.get("properties", {}).get("provisioningState") or "").lower()
            if state in {"succeeded", "success"}:
                return result
            if state in {"failed", "canceled", "cancelled"}:
                detail = result.get("error") or result.get("properties", {}).get("error") or result
                raise RuntimeError(f"Azure operation ended with {state}: {detail}")
        raise RuntimeError(f"Azure operation did not complete within {timeout} seconds.")

    def subscription_state(self) -> str:
        path = f"/subscriptions/{self.subscription_id}?api-version=2022-12-01"
        _, result, _ = self.request("GET", path)
        return result.get("state", "")

    def get_subscription_alias(self, alias_name: str) -> dict[str, Any] | None:
        path = f"/providers/Microsoft.Subscription/aliases/{quote(alias_name, safe='')}?api-version=2021-10-01"
        try:
            _, result, _ = self.request("GET", path)
            return result
        except RuntimeError as exc:
            if isinstance(exc, AzureArmError) and exc.status_code == 404:
                return None
            raise

    def create_subscription_alias(
        self,
        alias_name: str,
        *,
        billing_scope: str,
        display_name: str,
        management_group_id: str,
        tenant_id: str,
        subscription_owner_id: str,
        timeout: int = 1800,
    ) -> dict[str, Any]:
        """Create or resume an idempotently named subscription alias."""
        path = f"/providers/Microsoft.Subscription/aliases/{quote(alias_name, safe='')}?api-version=2021-10-01"
        existing = self.get_subscription_alias(alias_name)
        properties = (existing or {}).get("properties") or {}
        state = str(properties.get("provisioningState") or properties.get("state") or "").lower()
        subscription_id = str(properties.get("subscriptionId") or "").strip()
        # A failed alias with no subscription is the durable result of a previous
        # failed attempt. Re-submit the same idempotent alias on user retry rather
        # than polling the same failure forever. Never recreate an alias that has
        # already produced a subscription ID.
        should_submit = existing is None or (state in {"failed", "canceled", "cancelled"} and not subscription_id)
        if should_submit:
            body = {
                "properties": {
                    "displayName": display_name,
                    "billingScope": billing_scope,
                    "workload": "Production",
                    "additionalProperties": {
                        "subscriptionTenantId": tenant_id,
                        "subscriptionOwnerId": subscription_owner_id,
                        "managementGroupId": management_group_id,
                        "tags": {"Project": "CloudInABox", "ManagedBy": "CloudInABox"},
                    },
                },
            }
            deadline = time.monotonic() + timeout
            for attempt in range(4):
                try:
                    status, result, headers = self.request("PUT", path, body, timeout=300)
                    self.wait_operation(status, result, headers, timeout=max(1, int(deadline - time.monotonic())))
                    break
                except AzureArmError as exc:
                    if (exc.method == "PUT" and exc.status_code == 429
                            and "subscription is not created" in str(exc).lower()):
                        raise RuntimeError(
                            "Azure billing did not create this subscription and returned a subscription-creation "
                            "cooldown response. This is a billing-side limit, not a tenant deployment error. "
                            "Wait before retrying; repeated retries cannot bypass Azure's allowance."
                        ) from exc
                    if exc.method != "PUT" or exc.status_code != 429 or attempt == 3:
                        raise
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise
                    delay = exc.retry_after if exc.retry_after is not None else min(5 * (2 ** attempt), 60)
                    time.sleep(min(max(delay, 1), remaining))

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.get_subscription_alias(alias_name)
            properties = (result or {}).get("properties") or {}
            state = str(properties.get("provisioningState") or properties.get("state") or "").lower()
            if properties.get("subscriptionId") and state in {"succeeded", "success", ""}:
                return result
            if state in {"failed", "canceled", "cancelled"}:
                raise RuntimeError(f"Azure subscription vending failed: {properties.get('error') or properties}")
            time.sleep(5)
        raise RuntimeError(f"Azure subscription alias {alias_name} did not finish within {timeout} seconds.")

    def list_vnets(self) -> list[dict[str, Any]]:
        path = f"/subscriptions/{self.subscription_id}/providers/Microsoft.Network/virtualNetworks?api-version=2024-05-01"
        _, result, _ = self.request("GET", path)
        return result.get("value", [])

    def list_resource_inventory(self, resource_group: str | None = None) -> list[dict[str, Any]]:
        scope = (f"/subscriptions/{self.subscription_id}/resourceGroups/{quote(resource_group, safe='')}"
                 if resource_group else f"/subscriptions/{self.subscription_id}")
        path = f"{scope}/resources?api-version=2021-04-01"
        output = []
        while path:
            _, result, _ = self.request("GET", path)
            output.extend(result.get("value", []))
            path = result.get("nextLink")
        return output

    def peer_virtual_network(
        self,
        vnet_resource_id: str,
        peering_name: str,
        remote_vnet_id: str,
        *,
        allow_gateway_transit: bool = False,
        use_remote_gateways: bool = False,
    ) -> dict[str, Any]:
        path = (f"{vnet_resource_id}/virtualNetworkPeerings/{quote(peering_name, safe='')}"
                "?api-version=2025-01-01")
        body = {"properties": {
            "remoteVirtualNetwork": {"id": remote_vnet_id},
            "allowVirtualNetworkAccess": True,
            "allowForwardedTraffic": True,
            "allowGatewayTransit": allow_gateway_transit,
            "useRemoteGateways": use_remote_gateways,
        }}
        status, result, headers = self.request("PUT", path, body, timeout=300)
        return self.wait_operation(status, result, headers)

    def delete_virtual_network_peering(self, vnet_resource_id: str, peering_name: str) -> None:
        path = (f"{vnet_resource_id}/virtualNetworkPeerings/{quote(peering_name, safe='')}"
                "?api-version=2025-01-01")
        try:
            status, result, headers = self.request("DELETE", path, timeout=300)
            if status != 204:
                self.wait_operation(status, result, headers)
        except RuntimeError as exc:
            if "failed (404)" not in str(exc):
                raise

    def assign_subscription_role(self, principal_id: str, role_definition_id: str) -> dict[str, Any]:
        assignment_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{self.subscription_id}:{principal_id}:{role_definition_id}"))
        path = (f"/subscriptions/{self.subscription_id}/providers/Microsoft.Authorization/roleAssignments/"
                f"{assignment_id}?api-version=2022-04-01")
        body = {"properties": {
            "roleDefinitionId": f"/subscriptions/{self.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/{role_definition_id}",
            "principalId": principal_id,
            "principalType": "Group",
        }}
        _, result, _ = self.request("PUT", path, body)
        return result

    def subscription_what_if(self, deployment_name: str, location: str, template: dict, parameters: dict) -> dict:
        path = (f"/subscriptions/{self.subscription_id}/providers/Microsoft.Resources/deployments/"
                f"{deployment_name}/whatIf?api-version=2022-09-01")
        payload = {
            "location": location,
            "properties": {
                "mode": "Incremental",
                "template": template,
                "parameters": parameters,
                "whatIfSettings": {"resultFormat": "FullResourcePayloads"},
            },
        }
        status, data, headers = self.request("POST", path, payload, timeout=300)
        return self.wait_operation(status, data, headers, timeout=1800)

    def create_subscription_deployment(self, deployment_name: str, location: str, template: dict, parameters: dict) -> dict:
        path = (f"/subscriptions/{self.subscription_id}/providers/Microsoft.Resources/deployments/"
                f"{deployment_name}?api-version=2022-09-01")
        payload = {
            "location": location,
            "properties": {"mode": "Incremental", "template": template, "parameters": parameters},
        }
        status, data, headers = self.request("PUT", path, payload, timeout=300)
        if status in {201, 202}:
            result = self.wait_operation(status, data, headers)
            if result.get("properties", {}).get("provisioningState", "Succeeded") != "Succeeded":
                state_path = f"/subscriptions/{self.subscription_id}/providers/Microsoft.Resources/deployments/{deployment_name}?api-version=2022-09-01"
                _, result, _ = self.request("GET", state_path)
                state = result.get("properties", {}).get("provisioningState")
                if state != "Succeeded":
                    raise RuntimeError(f"Azure deployment ended in state {state or 'unknown'}.")
            return result
        return data

    def list_resource_groups(self) -> list[dict[str, Any]]:
        path = f"/subscriptions/{self.subscription_id}/resourcegroups?api-version=2021-04-01"
        output = []
        while path:
            _, result, _ = self.request("GET", path)
            output.extend(result.get("value", []))
            path = result.get("nextLink")
        return output

    def delete_resource_group(self, name: str) -> None:
        path = f"/subscriptions/{self.subscription_id}/resourceGroups/{name}?api-version=2021-04-01"
        status, data, headers = self.request("DELETE", path, timeout=300)
        if status != 204:
            self.wait_operation(status, data, headers, timeout=3600)

    def list_budgets(self) -> list[dict[str, Any]]:
        path = f"/subscriptions/{self.subscription_id}/providers/Microsoft.Consumption/budgets?api-version=2023-05-01"
        _, result, _ = self.request("GET", path)
        return result.get("value", [])

    def delete_budget(self, name: str) -> None:
        path = (f"/subscriptions/{self.subscription_id}/providers/Microsoft.Consumption/budgets/"
                f"{name}?api-version=2023-05-01")
        self.request("DELETE", path)

