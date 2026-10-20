"""Durable Azure Service Bus worker for tenant provisioning and cleanup."""

from __future__ import annotations

import json
import os
import subprocess
import time
import json as json_module
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from azure.identity import DefaultAzureCredential
from azure.servicebus import ServiceBusClient

from automation.api import (
    append_history,
    get_record,
    initialize_database,
    run_deprovisioning,
    run_provisioning,
    run_verification_job,
    store_record,
    utc_now,
)
from automation.jobs import enqueue_job


def ensure_azure_login() -> None:
    if os.getenv("APP_ENV", "development").lower() == "production":
        credential = DefaultAzureCredential()
        try:
            credential.get_token("https://management.azure.com/.default")
        finally:
            credential.close()
        return
    command = ["az", "login", "--identity", "--output", "none"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Azure CLI managed-identity login failed.")
    subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID", "").strip()
    if subscription_id:
        result = subprocess.run(
            ["az", "account", "set", "--subscription", subscription_id],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "Could not select the configured Azure subscription.")


def handle_job(payload: dict) -> None:
    tenant_id = payload.get("tenant_id")
    action = payload.get("action")
    record = get_record(tenant_id) if isinstance(tenant_id, str) else None
    if not record:
        return
    if action == "provision" and record["status"] == "provisioning":
        run_provisioning(record)
        provisioned = get_record(tenant_id)
        if provisioned and provisioned.get("status") == "success" and os.getenv("SERVICE_BUS_NAMESPACE", "").strip():
            store_record({**provisioned, "verification_state": "queued", "verification_report": None})
            append_history(tenant_id, "success", "verification", "Azure environment snapshot queued after provisioning.")
            try:
                enqueue_job("verify", tenant_id, None, run_verification_job)
            except Exception as exc:
                failed = get_record(tenant_id) or provisioned
                store_record({**failed, "verification_state": "failed", "verification_report": {
                    "verified_at": utc_now(), "tenant_id": tenant_id, "subscription_id": failed.get("subscription_id"),
                    "all_passed": False, "checks": [], "error": f"Could not queue the initial Azure environment snapshot: {exc}",
                }})
                append_history(tenant_id, "success", "verification", f"Initial Azure environment snapshot could not be queued: {exc}")
        if provisioned and provisioned.get("status") == "success":
            trigger_sample_workload(provisioned)
    elif action == "deprovision" and record["status"] == "deprovisioning":
        run_deprovisioning(tenant_id)
    elif action == "verify" and record.get("verification_state") in {"queued", "verifying"}:
        run_verification_job(tenant_id)
    elif action not in {"provision", "deprovision", "verify"}:
        raise ValueError("Unknown tenant lifecycle job action.")


def trigger_sample_workload(tenant: dict) -> None:
    """Send the completed tenant subscription to the repository's OIDC workflow."""
    token = os.getenv("GITHUB_ACTIONS_TOKEN", "").strip()
    repository = os.getenv("GITHUB_REPOSITORY", "").strip()
    if not token or not repository or "/" not in repository:
        store_record({**tenant, "sample_workload_state": "not_configured"})
        append_history(
            tenant["tenant_id"], "success", "sample-workload",
            "Sample workload pipeline was not triggered; configure GITHUB_ACTIONS_TOKEN and GITHUB_REPOSITORY.",
        )
        return
    owner, name = repository.split("/", 1)
    if not owner or not name or any(part in {".", ".."} for part in (owner, name)):
        store_record({**tenant, "sample_workload_state": "not_configured"})
        append_history(tenant["tenant_id"], "success", "sample-workload", "Sample workload pipeline was not triggered; GITHUB_REPOSITORY is invalid.")
        return
    endpoint = f"https://api.github.com/repos/{quote(owner, safe='')}/{quote(name, safe='')}/dispatches"
    payload = {
        "event_type": "cloudinabox-tenant-provisioned",
        "client_payload": {
            "tenant_id": tenant["tenant_id"],
            "subscription_id": tenant["subscription_id"],
            "address_space": tenant.get("address_space"),
        },
    }
    request = Request(endpoint, data=json_module.dumps(payload).encode("utf-8"), method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
        "User-Agent": "Cloud-in-a-Box-tenant-vending",
    })
    try:
        with urlopen(request, timeout=20) as response:
            if response.status not in {200, 201, 204}:
                raise RuntimeError(f"GitHub returned HTTP {response.status}.")
        store_record({**tenant, "sample_workload_state": "queued"})
        append_history(tenant["tenant_id"], "success", "sample-workload", "GitHub Actions accepted the sample SaaS deployment event.")
    except (HTTPError, URLError, TimeoutError, RuntimeError) as exc:
        store_record({**tenant, "sample_workload_state": "failed"})
        append_history(tenant["tenant_id"], "success", "sample-workload", f"GitHub Actions did not accept the sample workload event: {exc}")


def main() -> None:
    namespace = os.getenv("SERVICE_BUS_NAMESPACE", "").strip()
    queue_name = os.getenv("SERVICE_BUS_QUEUE", "tenant-provisioning")
    if not namespace:
        raise RuntimeError("SERVICE_BUS_NAMESPACE is required for the hosted worker.")

    initialize_database()
    ensure_azure_login()
    credential = DefaultAzureCredential()
    try:
        with ServiceBusClient(namespace, credential=credential) as client:
            with client.get_queue_receiver(queue_name, max_wait_time=10) as receiver:
                while True:
                    messages = receiver.receive_messages(max_message_count=1, max_wait_time=10)
                    if not messages:
                        continue
                    for message in messages:
                        try:
                            payload = json.loads(b"".join(message.body).decode("utf-8"))
                            handle_job(payload)
                            receiver.complete_message(message)
                        except Exception:
                            receiver.abandon_message(message)
                            time.sleep(2)
    finally:
        credential.close()


if __name__ == "__main__":
    main()
