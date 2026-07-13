"""
account_lifecycle.py — data export + account/business deletion.

Hardening pass 1 (2026-07-03). Closes the two biggest lifecycle gaps
from the business-readiness audit: practitioners had no way to get
their data OUT and no way to delete a business or their account
(GDPR/CCPA portability + erasure).

Endpoints (all require the caller's Supabase JWT):
  GET    /account/export                 → JSON bundle of every owned
                                           business + its core records
  DELETE /account/business/{business_id} → delete ONE owned business
                                           (children first, then the row)
  DELETE /account                        → delete ALL owned businesses,
                                           then the auth user itself

Design notes:
  • Ownership is verified server-side on every call — the service-role
    key does the reads/deletes, but only after confirming
    businesses.owner_id == the JWT's user id.
  • Deletion walks a curated child-table list before removing the
    business row, so it works whether or not each FK is ON DELETE
    CASCADE. Tables that don't exist (migration not run) are skipped.
  • Export mirrors the same table list — what we delete is what we
    export. Keep BUSINESS_CHILD_TABLES in sync when adding tables.
  • Deletions are LOGGED loudly. There is no undo.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, Depends, HTTPException

from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("account_lifecycle")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] account: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

router = APIRouter(prefix="/account", tags=["account-lifecycle"])

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)

# Every table that hangs off a business via business_id. Order matters
# for deletion (children before parents where tables reference each
# other). Missing tables (404) are skipped silently so this list can be
# a superset of any one deployment's schema.
BUSINESS_CHILD_TABLES: List[str] = [
    "events",
    "agent_queue",
    "chief_memories",
    "chief_conversations",
    "chief_activity",
    "chief_proposals",
    "chief_jobs",             # beta-readiness audit: was surviving deletion
    "chief_scheduled_actions",
    "chief_insights",
    "notifications",
    "sessions",
    "tasks",
    # Message content — MUST precede the thread/parent tables below so
    # their NO-ACTION foreign keys don't 409 the delete mid-way.
    "sms_messages",
    "sms_consents",
    "sms_keywords",
    "sms_bindings",
    "sms_opt_outs",
    "email_replies",
    "invoices",
    "bills",
    "orders",
    "order_items",
    "credit_ledger",
    "offerings",
    "documents",
    "foundation_documents",
    "projects",
    "products",
    "intake_forms",
    "custom_modules",
    "module_records",
    "module_entries",
    "module_specs",
    "business_sites",
    "business_profiles",
    "business_customers",
    "social_accounts",
    "social_posts",
    "design_rationales",
    "design_feedback",
    "goals",
    "support_tickets",
    "workflows",
    "workflow_definitions",
    "bank_accounts",
    "bank_transactions",
    "plaid_items",
    "plaid_transactions",
    "reconciliations",
    "journal_entries",
    "ledger_entries",
    "ledger_accounts",
    "email_threads",
    "sms_threads",
    "contacts",          # after the tables that reference contacts
]

# User-scoped tables (keyed by user_id, not business_id) — cleaned up in
# delete_account only, since they belong to the person, not a business.
USER_CHILD_TABLES: List[str] = [
    "push_subscriptions",
    "user_profiles",
]

# Supabase Storage buckets holding business-scoped files (logos, brand,
# site assets). Objects are stored under a "{business_id}/…" prefix.
STORAGE_BUCKETS: List[str] = ["business-assets"]


def _service_headers() -> Dict[str, str]:
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


async def _owned_businesses(client: httpx.AsyncClient, user_id: str) -> List[Dict[str, Any]]:
    r = await client.get(
        f"{SUPABASE_URL}/rest/v1/businesses",
        headers=_service_headers(),
        params={"owner_id": f"eq.{user_id}", "select": "*"},
    )
    if r.status_code >= 400:
        raise HTTPException(502, f"Failed to load businesses: {r.text[:200]}")
    return r.json() or []


async def _fetch_table(client: httpx.AsyncClient, table: str, business_id: str) -> List[Dict[str, Any]]:
    """All rows of `table` for this business; [] if the table doesn't
    exist or has no business_id column."""
    r = await client.get(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers=_service_headers(),
        params={"business_id": f"eq.{business_id}", "select": "*", "limit": "10000"},
    )
    if r.status_code >= 400:
        return []
    return r.json() or []


async def _delete_table_rows(client: httpx.AsyncClient, table: str, business_id: str) -> int:
    r = await client.delete(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers={**_service_headers(), "Prefer": "return=representation"},
        params={"business_id": f"eq.{business_id}", "select": "id"},
    )
    if r.status_code >= 400:
        # 404/42P01 table missing, or no business_id column — skip.
        return 0
    try:
        return len(r.json() or [])
    except Exception:
        return 0


# ─── Export ─────────────────────────────────────────────────────────────

@router.get("/export")
async def export_account(user: AuthedUser = Depends(require_user)):
    """Everything the practitioner owns, as one JSON document. The
    frontend offers it as a file download. Portability first — pretty
    formats can come later; JSON is complete and machine-readable."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        businesses = await _owned_businesses(client, user.id)
        out: Dict[str, Any] = {
            "export_version": 1,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "user": {"id": user.id, "email": user.email},
            "businesses": [],
        }
        for biz in businesses:
            bundle: Dict[str, Any] = {"business": biz, "tables": {}}
            for table in BUSINESS_CHILD_TABLES:
                rows = await _fetch_table(client, table, biz["id"])
                if rows:
                    bundle["tables"][table] = rows
            out["businesses"].append(bundle)
    logger.info(f"export user={user.id} businesses={len(out['businesses'])}")
    return out


# ─── Deletion ───────────────────────────────────────────────────────────

async def _delete_storage_objects(client: httpx.AsyncClient, business_id: str) -> int:
    """Delete every uploaded file under the business's prefix in each
    storage bucket (beta-readiness audit: these survived account deletion
    before). Best-effort — never blocks the row deletion."""
    removed = 0
    for bucket in STORAGE_BUCKETS:
        try:
            lr = await client.post(
                f"{SUPABASE_URL}/storage/v1/object/list/{bucket}",
                headers={**_service_headers(), "Content-Type": "application/json"},
                json={"prefix": f"{business_id}/", "limit": 1000},
            )
            if lr.status_code >= 400:
                continue
            names = [f"{business_id}/{o['name']}" for o in (lr.json() or []) if o.get("name")]
            if not names:
                continue
            dr = await client.request(
                "DELETE",
                f"{SUPABASE_URL}/storage/v1/object/{bucket}",
                headers={**_service_headers(), "Content-Type": "application/json"},
                json={"prefixes": names},
            )
            if dr.status_code < 400:
                removed += len(names)
        except Exception as e:
            logger.warning(f"storage cleanup {bucket} for {business_id} failed (non-fatal): {e}")
    return removed


async def _delete_business(client: httpx.AsyncClient, biz: Dict[str, Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for table in BUSINESS_CHILD_TABLES:
        n = await _delete_table_rows(client, table, biz["id"])
        if n:
            counts[table] = n
    storage_removed = await _delete_storage_objects(client, biz["id"])
    if storage_removed:
        counts["_storage_files"] = storage_removed
    r = await client.delete(
        f"{SUPABASE_URL}/rest/v1/businesses",
        headers=_service_headers(),
        params={"id": f"eq.{biz['id']}"},
    )
    if r.status_code >= 400:
        raise HTTPException(502, f"Business row delete failed: {r.text[:300]}")
    return counts


async def _delete_user_rows(client: httpx.AsyncClient, user_id: str) -> Dict[str, int]:
    """Delete the person-scoped rows (keyed by user_id). Missing tables
    and missing user_id columns skip silently."""
    counts: Dict[str, int] = {}
    for table in USER_CHILD_TABLES:
        try:
            r = await client.delete(
                f"{SUPABASE_URL}/rest/v1/{table}",
                headers={**_service_headers(), "Prefer": "return=representation"},
                params={"user_id": f"eq.{user_id}", "select": "user_id"},
            )
            if r.status_code < 400:
                counts[table] = len(r.json() or [])
        except Exception:
            pass
    return counts


@router.delete("/business/{business_id}")
async def delete_business(business_id: str, user: AuthedUser = Depends(require_user)):
    """Permanently delete ONE business the caller owns. No undo."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        businesses = await _owned_businesses(client, user.id)
        target = next((b for b in businesses if b["id"] == business_id), None)
        if not target:
            raise HTTPException(404, "Business not found or not yours")
        logger.warning(f"DELETE business {business_id} ({target.get('name')}) by user={user.id}")
        counts = await _delete_business(client, target)
    return {"ok": True, "deleted_business": business_id, "rows_removed": counts}


@router.delete("")
async def delete_account(user: AuthedUser = Depends(require_user)):
    """Permanently delete EVERY owned business, then the auth user.
    The session becomes invalid immediately after. No undo."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        businesses = await _owned_businesses(client, user.id)
        logger.warning(f"DELETE ACCOUNT user={user.id} email={user.email} businesses={len(businesses)}")
        removed = []
        for biz in businesses:
            await _delete_business(client, biz)
            removed.append(biz["id"])
        # Person-scoped rows (push subscriptions, profile) — keyed by
        # user_id, so they'd survive the per-business sweep otherwise.
        await _delete_user_rows(client, user.id)
        # Finally, the auth user itself (Supabase admin API).
        r = await client.delete(
            f"{SUPABASE_URL}/auth/v1/admin/users/{user.id}",
            headers={
                "apikey": os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
                "Authorization": f"Bearer {os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')}",
            },
        )
        if r.status_code >= 400:
            raise HTTPException(
                502,
                f"Businesses removed but auth-user delete failed ({r.status_code}) — contact support",
            )
    return {"ok": True, "deleted_businesses": removed, "account_deleted": True}
