"""FastAPI endpoints for the local Cloud-in-a-Box portal."""

from __future__ import annotations

import os
import sqlite3
import csv
import io
import base64
import json
import hashlib
import secrets
import hmac
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from automation.tenant_vending import (
    PORTAL_ENVIRONMENT_OPTIONS,
    PORTAL_LOCATION_OPTIONS,
    deprovision_tenant,
    platform_subscription_id,
    vend_tenant,
    verify_tenant_resources,
)
from automation.jobs import enqueue_job

app = FastAPI(title="Cloud-in-a-Box Portal API")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("AZURE_PORTAL_DB_PATH", PROJECT_ROOT / "project_outputs" / "portal.sqlite3"))
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
AUTH_MODE = os.getenv("AUTH_MODE", "local").lower()
APP_ENV = os.getenv("APP_ENV", "development").lower()
MAX_REQUEST_BUDGET_EUR = int(os.getenv("MAX_REQUEST_BUDGET_EUR", "1000") or "1000")
PUBLIC_REQUESTS_PER_EMAIL_PER_DAY = int(os.getenv("PUBLIC_REQUESTS_PER_EMAIL_PER_DAY", "2") or "2")
PORTAL_ADMIN_KEY = os.getenv("PORTAL_ADMIN_KEY", "")


class TenantRequest(BaseModel):
    tenant_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$")
    tenant_name: str = Field(min_length=2, max_length=100)
    environment: Literal["dev"]
    location: Literal["uksouth"]
    monthly_budget: int = Field(gt=0)
    owner_email: str = Field(pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", max_length=254)


class DeprovisionConfirmation(BaseModel):
    confirm_tenant_id: str


class TenantAccessRequest(BaseModel):
    tenant_group_object_id: str = Field(pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class TenantPipelineUpdate(BaseModel):
    subscription_id: str = Field(min_length=36, max_length=36)
    state: Literal["succeeded", "failed"]
    application_url: str | None = Field(default=None, max_length=2048)
    workflow_run_url: str | None = Field(default=None, max_length=2048)


def require_principal(request: Request) -> dict:
    if AUTH_MODE == "local":
        if os.getenv("APP_ENV", "development").lower() == "production":
            raise HTTPException(status_code=503, detail="Production requires hosted authentication.")
        host = request.client.host if request.client else ""
        if host not in {"127.0.0.1", "::1", "testclient"}:
            raise HTTPException(status_code=403, detail="Local authentication mode is restricted to loopback access.")
        return {"subject": "local-development-admin", "email": "local@localhost", "roles": ["Portal.Admin"]}

    if AUTH_MODE == "admin_key":
        supplied = request.headers.get("x-portal-admin-key", "")
        if len(PORTAL_ADMIN_KEY) < 32 or not hmac.compare_digest(supplied, PORTAL_ADMIN_KEY):
            raise HTTPException(status_code=401, detail="Administrator key is missing or invalid.")
        return {"subject": "portal-admin-key", "email": None, "roles": ["Portal.Admin"]}

    if AUTH_MODE != "easyauth":
        raise HTTPException(status_code=503, detail="Portal authentication is not configured.")
    encoded = request.headers.get("x-ms-client-principal")
    if not encoded:
        raise HTTPException(status_code=401, detail="Sign in to access tenant data.", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = json.loads(base64.b64decode(encoded, validate=True))
        claims = {}
        for claim in payload.get("claims", []):
            key = claim.get("typ", "").rsplit("/", 1)[-1].lower()
            value = claim.get("val")
            if key in {"roles", "role"}:
                claims.setdefault("roles", []).append(value)
            else:
                claims[key] = value
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail="The sign-in session could not be verified.")
    subject = claims.get("oid") or claims.get("objectidentifier") or claims.get("sub") or claims.get("nameidentifier")
    if not subject:
        raise HTTPException(status_code=401, detail="The sign-in token has no user identifier.")
    roles = claims.get("roles", [])
    if isinstance(roles, str):
        roles = [roles]
    return {
        "subject": subject,
        "email": claims.get("email") or claims.get("emailaddress") or claims.get("preferred_username") or claims.get("upn"),
        "roles": roles,
    }


def require_admin(principal: dict = Depends(require_principal)) -> dict:
    if "Portal.Admin" not in principal["roles"]:
        raise HTTPException(status_code=403, detail="Administrator access is required.")
    return principal


def require_request_token(tenant: dict, request: Request) -> None:
    token = request.headers.get("x-request-token", "")
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest() if token else ""
    if not tenant.get("request_token_hash") or not hmac.compare_digest(token_hash, tenant["request_token_hash"]):
        raise HTTPException(status_code=404, detail="Request not found. Check the reference and access token.")


def public_record(tenant: dict) -> dict:
    record = {key: value for key, value in tenant.items() if key not in {"customer_subject", "request_token_hash"}}
    platform_subscription = platform_subscription_id()
    record["isolation_model"] = (
        "shared subscription; isolated tenant resource groups"
        if platform_subscription and tenant.get("subscription_id") == platform_subscription
        else "dedicated subscription" if tenant.get("subscription_id") else "not provisioned"
    )
    return record


def customer_request_view(tenant: dict) -> dict:
    allowed = ("tenant_id", "tenant_name", "status", "phase", "environment", "location",
               "monthly_budget", "created_at", "updated_at", "error_summary",
               "verification_state", "verification_report", "sample_workload_state",
               "sample_workload_url", "sample_workload_run_url")
    return {key: tenant.get(key) for key in allowed}


def customer_history_view(rows, tenant: dict) -> list[dict]:
    output = []
    for row in rows:
        event = dict(row)
        failed = event["status"] in {"failed", "deprovision_failed"}
        output.append({
            "status": event["status"],
            "phase": event["phase"],
            "created_at": event["created_at"],
            "message": f"Provisioning failed: {tenant.get('error_summary') or 'check the portal for the failure summary.'}" if failed else f"Request entered {event['phase']}.",
        })
    return output


def connect_db():
    if DATABASE_URL:
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")
    return connection


def db_execute(connection, statement: str, parameters=()):
    if DATABASE_URL:
        statement = statement.replace("?", "%s")
    return connection.execute(statement, parameters)


@contextmanager
def db_session():
    connection = connect_db()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    event_id = "BIGSERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    with db_session() as connection:
        db_execute(connection, """
            CREATE TABLE IF NOT EXISTS tenant_requests (
                tenant_id TEXT PRIMARY KEY,
                tenant_name TEXT,
                customer_subject TEXT,
                request_token_hash TEXT,
                status TEXT NOT NULL,
                phase TEXT,
                environment TEXT,
                owner TEXT,
                location TEXT,
                monthly_budget INTEGER,
                subscription_id TEXT,
                address_space TEXT,
                deployment_name TEXT,
                error TEXT,
                tenant_group_object_id TEXT,
                sample_workload_state TEXT,
                sample_workload_url TEXT,
                sample_workload_run_url TEXT,
                created_at TEXT,
                updated_at TEXT NOT NULL
            )
        """)
        if DATABASE_URL:
            columns = {row["column_name"] for row in db_execute(connection, "SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='tenant_requests'").fetchall()}
        else:
            columns = {row["name"] for row in db_execute(connection, "PRAGMA table_info(tenant_requests)").fetchall()}
        for column in (
            "customer_subject", "request_token_hash", "verification_state", "verification_report",
            "tenant_group_object_id", "sample_workload_state", "sample_workload_url", "sample_workload_run_url",
        ):
            if column not in columns:
                db_execute(connection, f"ALTER TABLE tenant_requests ADD COLUMN {column} TEXT")
        db_execute(connection, f"""
            CREATE TABLE IF NOT EXISTS tenant_request_events (
                id {event_id},
                tenant_id TEXT NOT NULL,
                status TEXT NOT NULL,
                phase TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (tenant_id) REFERENCES tenant_requests(tenant_id) ON DELETE CASCADE
            )
        """)
        db_execute(connection, """
            CREATE TABLE IF NOT EXISTS public_submission_limits (
                email_hash TEXT PRIMARY KEY,
                window_started_at TEXT NOT NULL,
                request_count INTEGER NOT NULL
            )
        """)
        db_execute(connection, """
            CREATE TABLE IF NOT EXISTS tenant_network_allocations (
                tenant_id TEXT PRIMARY KEY,
                address_space TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            )
        """)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def summarize_error(error: str | None) -> str | None:
    if not error:
        return None
    normalized = error.lower()
    if "locationineligible" in normalized or "not accepting new customers" in normalized:
        return "Azure declined the selected region for this subscription. The portal now offers UK South only."
    if "policy-allowed-locations" in normalized or "allowed locations" in normalized:
        return "The selected region was blocked by the subscription policy. Only UK South is currently allowed."
    if "policy-required-environment" in normalized or "environment tag" in normalized:
        return "The selected environment was blocked by the subscription policy. Only Development is currently allowed."
    lines = [line.strip() for line in error.splitlines() if line.strip() and not line.strip().startswith("WARNING:")]
    return lines[-1][:500] if lines else "Provisioning failed. Expand the error details for more information."


def row_to_record(row: sqlite3.Row) -> dict:
    record = dict(row)
    record["error_summary"] = summarize_error(record.get("error"))
    report = record.get("verification_report")
    if report:
        try:
            record["verification_report"] = json.loads(report)
        except (TypeError, json.JSONDecodeError):
            record["verification_report"] = None
    return record


def get_record(tenant_id: str) -> dict | None:
    with db_session() as connection:
        row = db_execute(connection,
            "SELECT * FROM tenant_requests WHERE tenant_id = ?", (tenant_id,)
        ).fetchone()
    return row_to_record(row) if row else None


def list_records() -> list[dict]:
    with db_session() as connection:
        rows = db_execute(connection,
            "SELECT * FROM tenant_requests ORDER BY COALESCE(created_at, updated_at) DESC, tenant_id"
        ).fetchall()
    return [row_to_record(row) for row in rows]


def store_record(record: dict) -> None:
    now = utc_now()
    record = {**record, "updated_at": now}
    if isinstance(record.get("verification_report"), (dict, list)):
        record["verification_report"] = json.dumps(record["verification_report"])
    columns = (
        "tenant_id", "tenant_name", "customer_subject", "request_token_hash", "status", "phase", "environment", "owner", "location",
        "monthly_budget", "subscription_id", "address_space", "deployment_name", "error",
        "verification_state", "verification_report",
        "tenant_group_object_id",
        "sample_workload_state", "sample_workload_url", "sample_workload_run_url",
        "created_at", "updated_at",
    )
    with db_session() as connection:
        db_execute(connection,
            f"INSERT INTO tenant_requests ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) "
            "ON CONFLICT(tenant_id) DO UPDATE SET "
            + ",".join(f"{column}=excluded.{column}" for column in columns if column not in {"tenant_id", "created_at"}),
            tuple(record.get(column) for column in columns),
        )


def reserve_tenant_network(tenant_id: str) -> str:
    """Reserve a stable, non-overlapping /16 from the project tenant address pool."""
    with db_session() as connection:
        existing = db_execute(connection,
            "SELECT address_space FROM tenant_network_allocations WHERE tenant_id = ?", (tenant_id,)
        ).fetchone()
        if existing:
            return existing["address_space"] if isinstance(existing, dict) else existing[0]
        used = {row["address_space"] if isinstance(row, dict) else row[0] for row in db_execute(
            connection, "SELECT address_space FROM tenant_network_allocations"
        ).fetchall()}
        used.update(row["address_space"] if isinstance(row, dict) else row[0] for row in db_execute(
            connection, "SELECT address_space FROM tenant_requests WHERE address_space IS NOT NULL"
        ).fetchall())
        # Existing project networks occupy 10.10/16 through 10.20/16. New spokes
        # use a dedicated 10.30/16–10.254/16 pool; the hub template defaults to 10.255/16.
        for second_octet in range(30, 255):
            candidate = f"10.{second_octet}.0.0/16"
            if candidate in used:
                continue
            row = db_execute(connection,
                "INSERT INTO tenant_network_allocations(tenant_id,address_space,created_at) VALUES(?,?,?) "
                "ON CONFLICT DO NOTHING RETURNING address_space",
                (tenant_id, candidate, utc_now()),
            ).fetchone()
            if row:
                return candidate
            used.add(candidate)
        raise HTTPException(status_code=503, detail="The tenant VNet address pool is exhausted.")


def set_phase(tenant_id: str, phase: str, status: str = "provisioning") -> None:
    with db_session() as connection:
        db_execute(connection,
            "UPDATE tenant_requests SET status = ?, phase = ?, updated_at = ? WHERE tenant_id = ?",
            (status, phase, utc_now(), tenant_id),
        )
        db_execute(connection,
            "INSERT INTO tenant_request_events(tenant_id,status,phase,message,created_at) VALUES(?,?,?,?,?)",
            (tenant_id, status, phase, f"Azure workflow entered {phase}.", utc_now()),
        )


def append_history(tenant_id: str, status: str, phase: str, message: str) -> None:
    with db_session() as connection:
        db_execute(connection,
            "INSERT INTO tenant_request_events(tenant_id,status,phase,message,created_at) VALUES(?,?,?,?,?)",
            (tenant_id, status, phase, message, utc_now()),
        )


def run_provisioning(tenant: dict) -> None:
    try:
        result = vend_tenant(
            tenant,
            dry_run=False,
            on_phase=lambda phase: set_phase(tenant["tenant_id"], phase),
            on_subscription_id=lambda subscription_id: store_record({
                **(get_record(tenant["tenant_id"]) or tenant), "subscription_id": subscription_id,
            }),
        )
        original = get_record(tenant["tenant_id"]) or tenant
        store_record({**original, **tenant, **result, "created_at": original.get("created_at")})
        summary = summarize_error(result.get("error")) or "Azure deployment succeeded."
        append_history(tenant["tenant_id"], result["status"], result.get("phase", "complete"), summary)
    except Exception as exc:  # Persist failures so the portal can explain and retry them.
        original = get_record(tenant["tenant_id"]) or tenant
        store_record({
            **original,
            **tenant,
            "status": "failed",
            "phase": "backend",
            "error": str(exc),
            "created_at": original.get("created_at"),
        })
        append_history(tenant["tenant_id"], "failed", "backend", str(exc))


def run_provisioning_job(tenant_id: str) -> None:
    tenant = get_record(tenant_id)
    if tenant and tenant["status"] == "provisioning":
        run_provisioning(tenant)


def run_deprovisioning(tenant_id: str) -> None:
    tenant = get_record(tenant_id)
    if not tenant:
        return
    try:
        result = deprovision_tenant(
            tenant_id,
            expected_subscription_id=tenant.get("subscription_id"),
            on_phase=lambda phase: set_phase(tenant_id, phase, status="deprovisioning"),
        )
        updated = get_record(tenant_id) or tenant
        store_record({**updated, **result, "status": "deprovisioned", "phase": "complete", "error": None})
        with db_session() as connection:
            db_execute(connection, "DELETE FROM tenant_network_allocations WHERE tenant_id = ?", (tenant_id,))
        append_history(tenant_id, "deprovisioned", "complete", "Tenant resource groups and tenant budget have been removed.")
    except Exception as exc:
        updated = get_record(tenant_id) or tenant
        store_record({**updated, "status": "deprovision_failed", "phase": "deprovisioning", "error": str(exc)})
        append_history(tenant_id, "deprovision_failed", "deprovisioning", str(exc))


def run_verification_job(tenant_id: str) -> None:
    tenant = get_record(tenant_id)
    if not tenant or tenant.get("verification_state") not in {"queued", "verifying"}:
        return
    store_record({**tenant, "verification_state": "verifying"})
    append_history(tenant_id, tenant["status"], "verification", "Checking the tenant's resources directly in Azure Resource Manager.")
    try:
        report = verify_tenant_resources(tenant)
        current = get_record(tenant_id) or tenant
        store_record({**current, "verification_state": "complete" if report["all_passed"] else "failed",
                      "verification_report": report})
        result = f"Azure resource verification: {report['passed']} of {report['total']} checks passed."
        append_history(tenant_id, current["status"], "verification", result)
    except Exception as exc:
        current = get_record(tenant_id) or tenant
        report = {"verified_at": utc_now(), "subscription_id": tenant.get("subscription_id"),
                  "tenant_id": tenant_id, "all_passed": False, "checks": [], "error": str(exc)}
        store_record({**current, "verification_state": "failed", "verification_report": report})
        append_history(tenant_id, current["status"], "verification", f"Azure resource verification failed: {exc}")


def dispatch_job(action: str, tenant_id: str, background_tasks: BackgroundTasks, local_runner) -> None:
    try:
        enqueue_job(action, tenant_id, background_tasks, local_runner)
    except Exception as exc:
        failed_status = "deprovision_failed" if action == "deprovision" else "failed"
        current = get_record(tenant_id) or {"tenant_id": tenant_id}
        store_record({**current, "status": failed_status, "phase": "queue", "error": str(exc)})
        append_history(tenant_id, failed_status, "queue", str(exc))
        raise HTTPException(status_code=503, detail=f"Could not queue {action}. No Azure resources were changed.") from exc


def schedule_request(tenant: dict, background_tasks: BackgroundTasks) -> dict:
    existing = get_record(tenant["tenant_id"])
    if existing:
        raise HTTPException(status_code=409, detail="A request already exists for this tenant ID. Use its private request reference to track it.")
    now = utc_now()
    address_space = reserve_tenant_network(tenant["tenant_id"])
    store_record({
        **tenant,
        "status": "provisioning",
        "phase": "queued",
        "subscription_id": None,
        "address_space": address_space,
        "deployment_name": f"cloudinabox-{tenant['tenant_id']}",
        "error": None,
        "created_at": existing.get("created_at") if existing else now,
    })
    append_history(tenant["tenant_id"], "provisioning", "queued", "Provisioning request accepted by the portal.")
    dispatch_job("provision", tenant["tenant_id"], background_tasks, run_provisioning_job)
    return get_record(tenant["tenant_id"])


def enforce_public_submission_limit(email: str) -> None:
    """Atomically limit repeat requests from the same contact address."""
    if not 1 <= PUBLIC_REQUESTS_PER_EMAIL_PER_DAY <= 20:
        raise HTTPException(status_code=503, detail="Public request limits are not configured safely.")
    now = datetime.now(timezone.utc)
    now_text = now.isoformat(timespec="seconds")
    cutoff_text = (now - timedelta(hours=24)).isoformat(timespec="seconds")
    rate_key = PORTAL_ADMIN_KEY or os.getenv("PUBLIC_REQUEST_RATE_LIMIT_SALT", "local-development-only")
    email_hash = hmac.new(rate_key.encode("utf-8"), email.strip().lower().encode("utf-8"), hashlib.sha256).hexdigest()
    with db_session() as connection:
        row = db_execute(connection, """
            INSERT INTO public_submission_limits(email_hash, window_started_at, request_count)
            VALUES(?, ?, 1)
            ON CONFLICT(email_hash) DO UPDATE SET
              request_count = CASE
                WHEN public_submission_limits.window_started_at <= ? THEN 1
                ELSE public_submission_limits.request_count + 1
              END,
              window_started_at = CASE
                WHEN public_submission_limits.window_started_at <= ? THEN ?
                ELSE public_submission_limits.window_started_at
              END
            RETURNING request_count
        """, (email_hash, now_text, cutoff_text, cutoff_text, now_text)).fetchone()
        count = row["request_count"] if isinstance(row, dict) else row[0]
    if count > PUBLIC_REQUESTS_PER_EMAIL_PER_DAY:
        raise HTTPException(status_code=429, detail="This contact email has reached the daily request limit. Try again later.", headers={"Retry-After": "86400"})


@app.on_event("startup")
def startup() -> None:
    if APP_ENV == "production":
        missing = [name for name, value in {
            "AUTH_MODE=admin_key": AUTH_MODE == "admin_key",
            "PORTAL_ADMIN_KEY (at least 32 characters)": len(PORTAL_ADMIN_KEY) >= 32,
            "DATABASE_URL": bool(DATABASE_URL),
            "SERVICE_BUS_NAMESPACE": bool(os.getenv("SERVICE_BUS_NAMESPACE", "").strip()),
            "TENANT_BILLING_SCOPE": bool(os.getenv("TENANT_BILLING_SCOPE", "").strip()),
            "TENANT_MANAGEMENT_GROUP_ID": bool(os.getenv("TENANT_MANAGEMENT_GROUP_ID", "").strip()),
            "HUB_VNET_NAME": bool(os.getenv("HUB_VNET_NAME", "").strip()),
            "MAX_REQUEST_BUDGET_EUR": MAX_REQUEST_BUDGET_EUR > 0,
            "PUBLIC_REQUESTS_PER_EMAIL_PER_DAY (1–20)": 1 <= PUBLIC_REQUESTS_PER_EMAIL_PER_DAY <= 20,
        }.items() if not value]
        if os.getenv("GITHUB_REPOSITORY", "").strip() and len(os.getenv("GITHUB_CALLBACK_SECRET", "")) < 32:
            missing.append("GITHUB_CALLBACK_SECRET (at least 32 characters when GitHub integration is enabled)")
        if missing:
            raise RuntimeError("Production startup is blocked; configure " + ", ".join(missing) + ".")
    initialize_database()


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(PROJECT_ROOT / "index.html", headers={
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    })


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/auth/status")
def auth_status(request: Request):
    try:
        principal = require_principal(request)
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
        return {
            "authenticated": False,
            "is_admin": False,
        }
    return {
        "authenticated": True,
        "is_admin": "Portal.Admin" in principal["roles"],
        "email": principal.get("email"),
    }


@app.get("/config")
def portal_config():
    return {
        "environments": PORTAL_ENVIRONMENT_OPTIONS,
        "locations": PORTAL_LOCATION_OPTIONS,
        "max_monthly_budget_eur": MAX_REQUEST_BUDGET_EUR or None,
        "limitations": [
            "The active Azure subscription currently allows UK South only.",
            "The active Azure subscription currently requires the Development environment tag.",
        ],
    }


@app.get("/catalog")
def service_catalog():
    return {
        "included": [
            {"id": "resource-groups", "name": "Tenant resource groups", "description": "Four isolated resource groups for network, app, data, and monitoring resources.", "details": "rg-{tenant}-network · rg-{tenant}-app · rg-{tenant}-data · rg-{tenant}-monitoring", "source": "infrastructure/modules/tenant.bicep"},
            {"id": "network", "name": "Isolated virtual network", "description": "Dedicated tenant VNet in UK South.", "details": "VNet vnet-{tenant}; subnets snet-app, snet-data, and snet-management. Address ranges are allocated to avoid overlap.", "source": "infrastructure/modules/networking.bicep"},
            {"id": "monitoring", "name": "Log Analytics workspace", "description": "Tenant-scoped Azure Monitor workspace.", "details": "Workspace law-{tenant} in the monitoring group, PerGB2018 pricing, 30-day retention.", "source": "infrastructure/modules/monitoring.bicep"},
            {"id": "governance", "name": "Governance policies", "description": "Policies assigned to each of the four tenant resource groups.", "details": "Restricts location to UK South and requires matching TenantId and Environment=dev tags.", "source": "infrastructure/modules/governance.bicep"},
            {"id": "budget", "name": "Monthly budget alerts", "description": "Cost alert filtered to this tenant's four resource groups.", "details": "Monthly threshold with alerts at 80% and 100%. Alerts notify; they do not stop spending.", "source": "infrastructure/modules/finops.bicep"},
        ],
        "additional": [
            {"id": "app-service", "name": "Azure App Service", "description": "Managed web application hosting.", "details": "App Service plan and web app are not in the deployed template; cannot currently be requested."},
            {"id": "azure-sql", "name": "Azure SQL Database", "description": "Managed relational database.", "details": "SQL server, database, networking, and credentials are not provisioned by this project yet."},
            {"id": "storage", "name": "Azure Storage Account", "description": "Blob and file storage.", "details": "Storage account and data protection settings are not provisioned by this project yet."},
            {"id": "key-vault", "name": "Azure Key Vault", "description": "Tenant-scoped secret and key management.", "details": "Vault, access model, and private network configuration are not provisioned by this project yet."},
            {"id": "container-apps", "name": "Azure Container Apps", "description": "Managed container application hosting.", "details": "Environment, registry integration, and app deployment are not provisioned by this project yet."},
        ],
        "additional_message": "These catalogue entries are visible for planning only. They cannot currently be selected or provisioned.",
        "actual_costs_available": False,
    }


@app.get("/tenants")
def get_tenants(_: dict = Depends(require_admin)):
    return [public_record(record) for record in list_records()]


@app.get("/admin/evaluation/evidence.csv")
def evaluation_evidence(_: dict = Depends(require_admin)):
    """Export observed lifecycle and verification data for the proposal evaluation."""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([
        "tenant_id", "tenant_name", "subscription_id", "isolation_model", "request_status",
        "submitted_at_utc", "completed_at_utc", "provisioning_seconds", "manual_baseline_seconds",
        "policy_checks_passed", "policy_checks_total", "azure_month_to_date_cost",
        "cost_currency", "cross_tenant_cost_isolation_test", "sample_workload_state",
        "sample_workload_run_url",
    ])
    platform_subscription = platform_subscription_id()
    for tenant in list_records():
        with db_session() as connection:
            events = db_execute(connection,
                "SELECT status,phase,created_at FROM tenant_request_events WHERE tenant_id=? ORDER BY id",
                (tenant["tenant_id"],),
            ).fetchall()
        completion = next((row["created_at"] for row in reversed(events)
                           if row["status"] == "success" and row["phase"] == "complete"), None)
        started = tenant.get("created_at")
        duration_seconds = ""
        try:
            start_dt = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(str(completion).replace("Z", "+00:00"))
            duration_seconds = round((end_dt - start_dt).total_seconds(), 2)
        except (TypeError, ValueError):
            pass
        report = tenant.get("verification_report") or {}
        policy_checks = [check for check in report.get("checks", []) if "policy" in str(check.get("name", "")).lower()]
        cost = report.get("cost") or {}
        writer.writerow([
            tenant.get("tenant_id"), tenant.get("tenant_name"), tenant.get("subscription_id"),
            "shared subscription; isolated tenant resource groups" if platform_subscription and tenant.get("subscription_id") == platform_subscription else "legacy dedicated subscription" if tenant.get("subscription_id") else "not provisioned",
            tenant.get("status"), started or "", completion or "", duration_seconds, "",
            sum(bool(check.get("passed")) for check in policy_checks) if report else "",
            len(policy_checks) if report else "",
            cost.get("month_to_date") if cost.get("state") == "available" else "",
            cost.get("currency") or "",
            "not measured",
            tenant.get("sample_workload_state") or "not configured",
            tenant.get("sample_workload_run_url") or "",
        ])
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=cloudinabox-evaluation-evidence.csv"},
    )


@app.get("/tenants/{tenant_id}")
def get_tenant(tenant_id: str, _: dict = Depends(require_admin)):
    tenant = get_record(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant request not found.")
    return public_record(tenant)


@app.post("/internal/tenants/{tenant_id}/sample-workload")
def update_sample_workload_status(tenant_id: str, payload: TenantPipelineUpdate, request: Request):
    """Accept a signed pipeline callback without exposing the admin key to GitHub."""
    secret = os.getenv("GITHUB_CALLBACK_SECRET", "")
    if len(secret) < 32:
        raise HTTPException(status_code=503, detail="Sample workload callbacks are not configured.")
    canonical = "\n".join([
        tenant_id, payload.subscription_id, payload.state,
        payload.application_url or "", payload.workflow_run_url or "",
    ])
    expected = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    supplied = request.headers.get("x-cib-signature-256", "")
    if not supplied.startswith("sha256=") or not hmac.compare_digest(supplied[7:], expected):
        raise HTTPException(status_code=401, detail="The sample workload callback signature is invalid.")
    tenant = get_record(tenant_id)
    if not tenant or tenant.get("status") != "success" or tenant.get("subscription_id") != payload.subscription_id:
        raise HTTPException(status_code=404, detail="The tenant subscription was not found.")
    store_record({
        **tenant,
        "sample_workload_state": payload.state,
        "sample_workload_url": payload.application_url,
        "sample_workload_run_url": payload.workflow_run_url,
    })
    append_history(tenant_id, "success", "sample-workload", f"GitHub Actions sample workload deployment {payload.state}.")
    return {"accepted": True, "state": payload.state}


@app.put("/tenants/{tenant_id}/access")
def assign_tenant_access(
    tenant_id: str,
    request: TenantAccessRequest,
    _: dict = Depends(require_admin),
):
    tenant = get_record(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant request not found.")
    if tenant.get("status") != "success" or not tenant.get("subscription_id"):
        raise HTTPException(status_code=409, detail="Tenant access can be assigned after its subscription is provisioned.")
    from automation.arm_client import AzureArmClient
    try:
        arm = AzureArmClient(tenant["subscription_id"])
        shared_subscription_id = platform_subscription_id()
        role_id = "b24988ac-6180-42a0-ab88-20f7382dd24c"
        if shared_subscription_id and tenant["subscription_id"] == shared_subscription_id:
            raise HTTPException(
                status_code=409,
                detail=("The hosted worker intentionally cannot manage Azure role assignments at subscription scope. "
                        "For a shared-subscription tenant, assign the customer group only to this tenant's four "
                        "resource groups using a subscription Owner; no Azure role changes were made."),
            )
        else:
            arm.assign_subscription_role(request.tenant_group_object_id, role_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Azure could not assign tenant Contributor access: {exc}") from exc
    store_record({**tenant, "tenant_group_object_id": request.tenant_group_object_id})
    append_history(tenant_id, tenant["status"], "access", "Tenant Entra group Contributor access was assigned at the tenant isolation scope.")
    return public_record(get_record(tenant_id))


@app.get("/tenants/{tenant_id}/history")
def tenant_history(tenant_id: str, _: dict = Depends(require_admin)):
    tenant = get_record(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant request not found.")
    with db_session() as connection:
        rows = db_execute(connection,
            "SELECT status,phase,message,created_at FROM tenant_request_events WHERE tenant_id=? ORDER BY id",
            (tenant_id,),
        ).fetchall()
    return [dict(row) for row in rows]


@app.post("/tenants/{tenant_id}/verify", status_code=202)
def verify_tenant(tenant_id: str, background_tasks: BackgroundTasks, _: dict = Depends(require_admin)):
    tenant = get_record(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant request not found.")
    if tenant.get("status") != "success":
        raise HTTPException(status_code=409, detail="Only successfully provisioned tenants can be verified.")
    if tenant.get("verification_state") in {"queued", "verifying"}:
        raise HTTPException(status_code=409, detail="Azure verification is already in progress.")
    store_record({**tenant, "verification_state": "queued", "verification_report": None})
    append_history(tenant_id, tenant["status"], "verification", "Azure resource verification queued by an administrator.")
    try:
        enqueue_job("verify", tenant_id, background_tasks, run_verification_job)
    except Exception as exc:
        current = get_record(tenant_id) or tenant
        store_record({**current, "verification_state": "failed",
                      "verification_report": {"all_passed": False, "checks": [], "error": str(exc)}})
        append_history(tenant_id, tenant["status"], "verification", f"Could not queue Azure verification: {exc}")
        raise HTTPException(status_code=503, detail="Could not queue Azure verification. No Azure resources were changed.") from exc
    return public_record(get_record(tenant_id))


@app.post("/requests/{tenant_id}/verify", status_code=202)
def verify_public_request(tenant_id: str, request: Request, background_tasks: BackgroundTasks):
    """Let a customer request a read-only snapshot of their own tenant using its private token."""
    tenant = get_record(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Request not found.")
    require_request_token(tenant, request)
    if tenant.get("status") != "success":
        raise HTTPException(status_code=409, detail="Only successfully provisioned requests can be inspected.")
    if tenant.get("verification_state") in {"queued", "verifying"}:
        return customer_request_view(tenant)
    store_record({**tenant, "verification_state": "queued", "verification_report": None})
    append_history(tenant_id, tenant["status"], "verification", "Azure environment snapshot queued by the request owner.")
    try:
        enqueue_job("verify", tenant_id, background_tasks, run_verification_job)
    except Exception as exc:
        current = get_record(tenant_id) or tenant
        store_record({**current, "verification_state": "failed", "verification_report": {
            "verified_at": utc_now(), "tenant_id": tenant_id, "subscription_id": tenant.get("subscription_id"),
            "all_passed": False, "checks": [], "error": str(exc),
        }})
        append_history(tenant_id, tenant["status"], "verification", f"Could not queue Azure environment snapshot: {exc}")
        raise HTTPException(status_code=503, detail="Could not queue the Azure environment snapshot. No Azure resources were changed.") from exc
    return customer_request_view(get_record(tenant_id))


@app.get("/requests/{tenant_id}")
def get_public_request(tenant_id: str, request: Request):
    tenant = get_record(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Request not found.")
    require_request_token(tenant, request)
    return customer_request_view(tenant)


@app.get("/requests/{tenant_id}/history")
def get_public_request_history(tenant_id: str, request: Request):
    tenant = get_record(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Request not found.")
    require_request_token(tenant, request)
    with db_session() as connection:
        rows = db_execute(connection,
            "SELECT status,phase,message,created_at FROM tenant_request_events WHERE tenant_id=? ORDER BY id",
            (tenant_id,),
        ).fetchall()
    return customer_history_view(rows, tenant)


def retry_existing_request(tenant: dict, background_tasks: BackgroundTasks) -> dict:
    if tenant["status"] != "failed":
        raise HTTPException(status_code=409, detail="Only failed tenant requests can be retried.")
    required = ("tenant_name", "environment", "owner", "location", "monthly_budget")
    if any(tenant.get(key) is None for key in required):
        raise HTTPException(status_code=409, detail="This request is missing the original form details and cannot be retried safely.")
    if MAX_REQUEST_BUDGET_EUR > 0 and int(tenant["monthly_budget"]) > MAX_REQUEST_BUDGET_EUR:
        raise HTTPException(status_code=422, detail=f"The maximum monthly budget for a public request is €{MAX_REQUEST_BUDGET_EUR}.")
    store_record({**tenant, "status": "provisioning", "phase": "queued", "error": None})
    append_history(tenant["tenant_id"], "provisioning", "queued", "Retry accepted by the portal.")
    dispatch_job("provision", tenant["tenant_id"], background_tasks, run_provisioning_job)
    return get_record(tenant["tenant_id"])


@app.post("/tenants", status_code=202)
def create_tenant(request: TenantRequest, background_tasks: BackgroundTasks):
    if MAX_REQUEST_BUDGET_EUR > 0 and request.monthly_budget > MAX_REQUEST_BUDGET_EUR:
        raise HTTPException(status_code=422, detail=f"The maximum monthly budget for a public request is €{MAX_REQUEST_BUDGET_EUR}.")
    enforce_public_submission_limit(request.owner_email)
    token = secrets.token_urlsafe(32)
    tenant = {
        **request.model_dump(exclude={"owner_email"}),
        "owner": request.owner_email,
        "customer_subject": None,
        "request_token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
    }
    record = schedule_request(tenant, background_tasks)
    return {**customer_request_view(record), "request_token": token}


@app.post("/requests/{tenant_id}/retry", status_code=202)
def retry_public_request(tenant_id: str, request: Request, background_tasks: BackgroundTasks):
    existing = get_record(tenant_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Request not found.")
    require_request_token(existing, request)
    return customer_request_view(retry_existing_request(existing, background_tasks))


@app.post("/tenants/{tenant_id}/retry", status_code=202)
def retry_tenant(tenant_id: str, background_tasks: BackgroundTasks, principal: dict = Depends(require_principal)):
    existing = get_record(tenant_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Tenant request not found.")
    if "Portal.Admin" not in principal["roles"]:
        raise HTTPException(status_code=403, detail="Administrator access is required.")
    return public_record(retry_existing_request(existing, background_tasks))


@app.delete("/tenants/{tenant_id}", status_code=204)
def remove_failed_tenant(tenant_id: str, principal: dict = Depends(require_admin)):
    existing = get_record(tenant_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Tenant request not found.")
    if existing["status"] != "failed":
        raise HTTPException(status_code=409, detail="Only failed request records can be removed here.")
    with db_session() as connection:
        db_execute(connection, "DELETE FROM tenant_request_events WHERE tenant_id = ?", (tenant_id,))
        db_execute(connection, "DELETE FROM tenant_requests WHERE tenant_id = ?", (tenant_id,))
        db_execute(connection, "DELETE FROM tenant_network_allocations WHERE tenant_id = ?", (tenant_id,))
    return None


@app.post("/tenants/{tenant_id}/deprovision", status_code=202)
def deprovision_tenant_request(
    tenant_id: str,
    confirmation: DeprovisionConfirmation,
    background_tasks: BackgroundTasks,
    principal: dict = Depends(require_admin),
):
    existing = get_record(tenant_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Tenant request not found.")
    if confirmation.confirm_tenant_id != tenant_id:
        raise HTTPException(status_code=400, detail="Type the exact tenant ID to confirm deprovisioning.")
    if existing["status"] not in {"success", "failed", "deprovision_failed"}:
        raise HTTPException(status_code=409, detail="Only completed tenants, failed deployments that may have partial resources, or incomplete deprovisioning operations can be cleaned up.")
    if not existing.get("subscription_id"):
        raise HTTPException(status_code=409, detail="This older tenant record has no recorded subscription ID, so Azure resources cannot be targeted safely.")
    store_record({**existing, "status": "deprovisioning", "phase": "queued", "error": None})
    append_history(tenant_id, "deprovisioning", "queued", "Deprovisioning confirmed and queued.")
    dispatch_job("deprovision", tenant_id, background_tasks, run_deprovisioning)
    return public_record(get_record(tenant_id))
