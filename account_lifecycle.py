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

from audit_log import LEDGER_EXPORT_SELECT
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
#
# S11 trust audit (2026-07-31): reconciled against the live schema —
# the list had drifted badly since it was written (time_entries,
# customer_ledger, campaigns, the whole GL cluster, the audit/undo
# logs and every 7/2x-era table were missing, so export was incomplete
# and deletion left orphans). "What we delete is what we export" is
# the module's contract; keep BOTH honest by keeping THIS list honest.
#
# Deliberately EXCLUDED (checked, not forgotten):
#   stripe_webhook_events   — platform-global Stripe event-dedup log,
#                             no business_id column.
#   site_events             — anonymous marketing-site traffic, no
#                             business_id by design (privacy).
#   vertical_knowledge      — Feed 2 cross-account learning; has NO
#                             business_id ON PURPOSE (k-anonymity).
#   usage_* / api_usage / product_events / credit grants internals —
#                             platform metering + billing records the
#                             platform must retain for its own books.
#   email_suppressions      — recipient-keyed deliverability protection;
#                             deleting it would let a deleted business's
#                             bounces be re-mailed by the platform.
#   entity_groups           — owner-keyed (owner_id), no business_id
#                             column; consolidation groups die with the
#                             auth user, not with one business.
#   mcp_oauth_* / referrals / waitlist / scheduler_lease / fx_rates /
#   platform_* / inference_cache — platform- or user-keyed, not
#                             business children.
BUSINESS_CHILD_TABLES: List[str] = [
    "events",
    "agent_queue",
    "agent_runs",             # MCP agent access trail (business-scoped)
    "mcp_tokens",             # business-scoped agent tokens
    "chief_memories",
    "chief_conversations",
    "chief_activity",
    "chief_proposals",
    "chief_bookkeeping_proposals",
    "chief_learning_signals",
    "chief_patterns",
    "chief_playbooks",
    "chief_templates",
    "chief_actions",
    "chief_suggestions",
    "chief_notifications",
    "chief_jobs",             # beta-readiness audit: was surviving deletion
    "chief_scheduled_actions",
    "chief_insights",
    "chief_undo_log",
    "insights",
    "notifications",
    "sessions",
    "tasks",
    # Rules/automation — runs reference their rule.
    "rule_runs",
    "practitioner_rules",
    # Campaigns — sends reference campaigns AND contacts.
    "campaign_sends",
    "campaigns",
    # Message content — MUST precede the thread/parent tables below so
    # their NO-ACTION foreign keys don't 409 the delete mid-way.
    "sms_messages",
    "sms_consents",
    "sms_keywords",
    "sms_bindings",
    "sms_opt_outs",
    "email_replies",
    # Money ABOUT the business — ledgers before the rows they cite.
    "customer_ledger",        # references contacts, invoices, offerings
    "time_entries",           # references contacts
    "invoices",
    "bills",
    "orders",
    "order_items",
    "credit_ledger",
    "business_expenses",
    "business_budgets",
    "category_rules",
    "offerings",
    "documents",
    "esign_documents",
    "foundation_documents",
    "projects",
    "products",
    "intake_forms",
    "custom_modules",
    "module_records",
    "module_entries",
    "module_specs",
    # Restricted (clinical/giving) class — entries + their access trail.
    "restricted_module_access_log",
    "restricted_module_entries",
    "business_sites",
    "site_chat_history",
    "site_content_overrides",
    "business_profiles",
    "business_customers",
    "social_accounts",
    "social_posts",
    "design_rationales",
    "design_feedback",
    "goals",
    "growth_milestones",
    "growth_objectives",
    "strategy_tracks",
    "business_tracks",
    "support_tickets",
    "workflows",
    "workflow_definitions",
    # Academy — lessons/enrollments reference courses.
    "academy_lessons",
    "academy_enrollments",
    "academy_courses",
    "bank_accounts",
    "bank_transactions",
    "plaid_accounts",
    "plaid_items",
    "plaid_transactions",
    "reconciliations",
    "connectors",
    # GL cluster — queue/alarms/pushed-entries cite journal entries, so
    # they go first; periods and the chart go after the entries that
    # cite them; the QuickBooks connection row goes last of the cluster.
    "gl_sync_queue",
    "gl_divergence_alarms",
    "gl_admin_actions",
    "quickbooks_pushed_entries",
    "journal_entries",
    "ledger_entries",
    "ledger_accounts",
    "period_edit_overrides",  # references accounting_periods
    "accounting_periods",
    "coa_external_mappings",  # references chart_of_accounts rows
    "chart_of_accounts",
    "quickbooks_connections",
    # Payroll/contractors — transfers reference contractors.
    "outbound_transfers",
    "payroll_interest",
    "contractors",
    "email_threads",
    "sms_threads",
    # Team seats + invites die with the business.
    "business_users",
    "business_collaborators",
    "invite_tokens",
    "contacts",          # after the tables that reference contacts
    # THE LEDGER GOES LAST, on purpose. Deleting the business row
    # cascades into audit_log, and audit_log's append-only trigger
    # refuses that cascade — so the ledger must already be erased (via
    # the tombstone-writing RPC in _delete_table_rows) by the time the
    # business row is removed. Erasing it last also shrinks the window
    # in which some other writer appends a row that would re-block the
    # cascade; if that race ever fires, the business delete 502s loudly
    # and a retry re-runs the erasure. Failing closed is correct here.
    "audit_log",
]

# User-scoped tables (keyed by user_id, not business_id) — cleaned up in
# delete_account only, since they belong to the person, not a business.
USER_CHILD_TABLES: List[str] = [
    "push_subscriptions",
    "user_profiles",
]

# Supabase Storage buckets holding business-scoped files (logos, brand,
# site assets, receipt photos, digital product files). Objects are
# stored under a "{business_id}/…" prefix; business-documents nests one
# level deeper ("{business_id}/receipts/…") and product-files likewise
# ("{business_id}/{offering_id}/…"), which _delete_storage_objects
# handles by descending one folder level.
STORAGE_BUCKETS: List[str] = ["business-assets", "business-documents",
                              "product-files"]


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


# audit_log is the one table this export does not take wholesale. Its
# payload/result columns hold copies of the records an action touched,
# and the ledger's standing invariant is that no surface returns them —
# an invariant only worth having if it has no quiet exceptions. Nothing
# is lost: the tables those copies were made FROM travel in the same
# export under their own names, and the hash columns come along so the
# chain stays independently verifiable. See audit_log.LEDGER_EXPORT_SELECT.
_TABLE_SELECT = {"audit_log": LEDGER_EXPORT_SELECT}


async def _fetch_table(client: httpx.AsyncClient, table: str, business_id: str) -> List[Dict[str, Any]]:
    """All rows of `table` for this business; [] if the table doesn't
    exist or has no business_id column."""
    r = await client.get(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers=_service_headers(),
        params={"business_id": f"eq.{business_id}",
                "select": _TABLE_SELECT.get(table, "*"), "limit": "10000"},
    )
    if r.status_code >= 400:
        return []
    return r.json() or []


async def _erase_ledger(client: httpx.AsyncClient, business_id: str,
                        requested_by: str = "account_erasure") -> int:
    """The ONE sanctioned removal path for the action ledger.

    audit_log is append-only at the DATABASE level now — a plain DELETE
    raises, including the cascade from deleting the business row. GDPR
    still beats append-only, but never silently: this RPC writes a
    ledger_tombstones row (count + sequence range + the prior chain hash)
    BEFORE removing anything, and deliberately does not reset
    ledger_chain_state, so the erased range stays visible afterwards as a
    gap the tombstone explains.
    """
    try:
        r = await client.post(
            f"{SUPABASE_URL}/rest/v1/rpc/ledger_erase_business",
            headers=_service_headers(),
            json={"p_business_id": business_id, "p_reason": "gdpr_erasure",
                  "p_requested_by": requested_by})
        if r.status_code >= 400:
            logger.error(f"ledger erasure failed for {business_id}: {r.text[:300]}")
            return 0
        return int(r.json() or 0)
    except Exception as e:
        logger.error(f"ledger erasure raised for {business_id}: {e}")
        return 0


async def _delete_table_rows(client: httpx.AsyncClient, table: str, business_id: str) -> int:
    # audit_log never takes the plain path — see _erase_ledger.
    if table == "audit_log":
        return await _erase_ledger(client, business_id)
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
            names: List[str] = []
            for o in (lr.json() or []):
                if not o.get("name"):
                    continue
                # Folder entries come back with no id (receipts live at
                # "{business_id}/receipts/…") — descend one level so the
                # files inside don't survive the deletion.
                if o.get("id") is None:
                    sub = await client.post(
                        f"{SUPABASE_URL}/storage/v1/object/list/{bucket}",
                        headers={**_service_headers(), "Content-Type": "application/json"},
                        json={"prefix": f"{business_id}/{o['name']}/", "limit": 1000},
                    )
                    if sub.status_code < 400:
                        names.extend(
                            f"{business_id}/{o['name']}/{s['name']}"
                            for s in (sub.json() or [])
                            if s.get("name") and s.get("id") is not None)
                else:
                    names.append(f"{business_id}/{o['name']}")
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
