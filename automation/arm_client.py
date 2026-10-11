"""Small Azure Resource Manager REST client for managed-identity deployments."""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


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
            detail = error.get("message") or error.get("code") or str(data)
            raise RuntimeError(f"Azure Resource Manager {method} failed ({exc.code}): {detail}") from exc
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

    def list_vnets(self) -> list[dict[str, Any]]:
        path = f"/subscriptions/{self.subscription_id}/providers/Microsoft.Network/virtualNetworks?api-version=2024-05-01"
        _, result, _ = self.request("GET", path)
        return result.get("value", [])

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

