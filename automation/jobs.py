"""Queue tenant lifecycle work durably in Azure; keep local mode convenient."""

from __future__ import annotations

import json
import os
from uuid import uuid4


def enqueue_job(action: str, tenant_id: str, background_tasks, local_runner) -> None:
    namespace = os.getenv("SERVICE_BUS_NAMESPACE", "").strip()
    if not namespace:
        if os.getenv("APP_ENV", "development").lower() == "production":
            raise RuntimeError("SERVICE_BUS_NAMESPACE must be configured in production.")
        background_tasks.add_task(local_runner, tenant_id)
        return

    from azure.identity import DefaultAzureCredential
    from azure.servicebus import ServiceBusClient, ServiceBusMessage

    queue_name = os.getenv("SERVICE_BUS_QUEUE", "tenant-provisioning")
    body = json.dumps({"action": action, "tenant_id": tenant_id})
    with ServiceBusClient(namespace, credential=DefaultAzureCredential()) as client:
        with client.get_queue_sender(queue_name) as sender:
            sender.send_messages(ServiceBusMessage(body, message_id=f"{action}:{tenant_id}:{uuid4()}"))
