"""Minimal workload used to demonstrate a tenant's provisioned SaaS environment."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in {"/", "/health"}:
            self.send_error(404)
            return
        payload = {
            "service": "Cloud-in-a-Box sample SaaS workload",
            "status": "healthy",
            "tenant_id": os.getenv("TENANT_ID", "not-configured"),
            "region": os.getenv("TENANT_REGION", "not-configured"),
            "subscription_id": os.getenv("TENANT_SUBSCRIPTION_ID", "not-configured"),
        }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"{self.client_address[0]} - {fmt % args}")


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", int(os.getenv("PORT", "8000"))), Handler).serve_forever()
