"""Durable Azure Service Bus worker for tenant provisioning and cleanup."""

from __future__ import annotations

import json
import os
import subprocess
import time

from azure.identity import DefaultAzureCredential
from azure.servicebus import ServiceBusClient

from automation.api import (
    get_record,
    initialize_database,
    run_deprovisioning,
    run_provisioning,
)


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
    elif action == "deprovision" and record["status"] == "deprovisioning":
        run_deprovisioning(tenant_id)
    elif action not in {"provision", "deprovision"}:
        raise ValueError("Unknown tenant lifecycle job action.")


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
