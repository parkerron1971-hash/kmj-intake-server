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
from typing import Any, Dict, List, Optional, Tuple

import ledger_unlock
import httpx
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Request

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
#
# The list above used to be prose only, and prose does not fail a
# test. Every table a migration creates WITH a business_id column now
# has to appear in exactly one of BUSINESS_CHILD_TABLES or
# EXPORT_EXCLUDED (test_export_import pins it, scanning the migrations),
# so the next table someone adds is a decision, not an omission. On
# 2026-09-04 the scan found nine practitioner tables the export had
# never carried — concierge conversations, consent records, the
# business's own document templates, auditor links, push
# subscriptions, the Stripe disputes cache, support-ticket messages,
# and the texting number itself — and sixteen platform-side ones that
# belong here with a reason.

EXPORT_EXCLUDED: Dict[str, str] = {
    # Platform books and metering — the platform must keep these for its
    # own accounts, whatever a business does with theirs.
    "usage_grants":            "platform credit grants; platform billing record",
    "usage_notifications":     "platform allowance notices; platform record",
    "usage_stripe_reports":    "platform usage reports to Stripe; platform record",
    "api_usage":               "platform metering",
    "product_events":          "platform product analytics",
    "stripe_webhook_events":   "platform-global Stripe dedup log",
    # Cross-account learning, k-anonymous by design.
    "vertical_knowledge":      "Feed 2 cross-account learning; no per-business rows on purpose",
    "library_gap_log":         "module-library learning; SET NULL on business delete, kept for the platform",
    "inference_cache":         "Arc 20 inference cache; platform-side, regenerable",
    # An employee's SSN is Fernet ciphertext keyed to the platform's
    # TIN_ENCRYPTION_KEY: unreadable outside this deployment, and an
    # SSN must never travel in an export ZIP anyway. Deleting the
    # business cascades employees → this table, so nothing lingers.
    "employee_tax_profiles":   "W-4 + encrypted SSN; never exported, cascades from employees on delete",
    "inference_gate_decisions": "Arc 20 gate decisions; platform-side learning about the gate, not practitioner records",
    # Keyed to a person or to the platform, not to a business.
    "email_suppressions":      "recipient-keyed deliverability protection; deleting it re-mails bounces",
    "entity_groups":           "owner-keyed consolidation groups; die with the auth user",
    "mcp_oauth_codes":         "user-keyed OAuth codes; short-lived",
    "mcp_oauth_refresh":       "user-keyed OAuth refresh tokens",
    "site_events":             "anonymous marketing-site traffic; no business_id by design",
    # The tamper-evident ledger has its own door. audit_log is exported
    # under its own name and erased through the tombstone RPC; the chain
    # state, anchors, tombstones, redactions and their tickets are the
    # evidence that erasure happened, and bulk-deleting evidence of an
    # erasure defeats the ledger. They stay, and ledger_verify reads them.
    "ledger_chain_state":      "tamper-evident ledger: per-business chain head; erased through the ledger's own RPC",
    "ledger_tombstones":       "tamper-evident ledger: proof rows were erased; must outlive the business",
    "ledger_anchors":          "tamper-evident ledger: external anchors; evidence, outlives the business",
    "ledger_anchor_failures":  "tamper-evident ledger: anchor attempts; evidence",
    "ledger_anchor_upgrades":  "tamper-evident ledger: anchor provider upgrades; evidence",
    "ledger_redactions":       "tamper-evident ledger: what was redacted and why; evidence",
    "ledger_redaction_tickets": "tamper-evident ledger: redaction requests; evidence",
    "ledger_erasure_tickets":  "tamper-evident ledger: erasure requests; evidence",
}
BUSINESS_CHILD_TABLES: List[str] = [
    "events",
    "agent_queue",
    "agent_runs",             # MCP agent access trail (business-scoped)
    "mcp_tokens",             # business-scoped agent tokens
    "chief_memories",
    "chief_conversations",
    "chief_activity",
    "chief_assignments",      # the outcomes they handed Chief + its moves log (9/4)
    "chief_moves",            # what came of each of Chief's moves (9/4)
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
    # The texting number itself. Exported so the record says which line
    # was theirs; on delete the line is handed back to the provider FIRST
    # (_release_sms_lines) — a cascade would drop the row and leave the
    # number billing the platform forever.
    "sms_numbers",
    # Conversations the site concierge had with visitors (references
    # contacts), and the consent a client gave (the record a dispute
    # turns on — it goes with the business that holds it).
    "concierge_conversations",
    "consent_records",
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
    # Children of a module ENTRY, listed before it so the export carries
    # them and the delete never trips an FK. Both cascade at the DB level
    # too; the list is what makes them EXPORTABLE, which is the half a
    # cascade cannot do.
    #
    # deadlines was missing entirely — a pre-existing gap found while
    # adding grant_budget_lines. Its business_id cascades, so erasure was
    # never leaking rows, but "what we delete is what we export" was
    # quietly untrue for every lawyer's docket.
    "grant_budget_lines",
    "deadlines",
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
    # The day-one arc. Cascades on business delete already; listing it is
    # what makes it EXPORTABLE, which is the half a cascade cannot do.
    "first_run_arc",
    # Ticket messages reference their ticket.
    "support_ticket_messages",
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
    # Pay your team (2026-09-05): line items reference runs and
    # employees; runs reference employees through the items. The W-4
    # profile (SSN ciphertext) is NOT exported — see EXPORT_EXCLUDED —
    # and cascades from employees on delete.
    "pay_run_items",
    "pay_runs",
    "employees",
    # Payroll/contractors — transfers reference contractors.
    "outbound_transfers",
    "payroll_interest",
    "contractors",
    "email_threads",
    "sms_threads",
    # The business's own document templates, the auditor links it
    # issued, the devices it pushes to, and Stripe's disputes as cached
    # for it — each keyed to the business and each part of its record.
    "business_doc_templates",
    "auditor_links",
    "push_subscriptions",
    "stripe_disputes_cache",
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


# One page of a table, and the ceiling past which we stop and SAY SO.
#
# The old code asked for limit=10000 and returned whatever came back.
# Nothing paginated and nothing checked, so a business with more than
# 10,000 rows in any table exported the first 10,000 and reported
# success — while deletion, which has no such cap, removed all of them.
# "What we delete is what we export" is this module's stated contract,
# and that made it false in the one direction that cannot be undone.
#
# No table is over the cap today (largest business-scoped table in
# production is ~3k rows), so this was a loaded gun rather than active
# loss. It fires the first time a busy practitioner's events table grows
# up.
_EXPORT_PAGE = 1000
_EXPORT_MAX_ROWS = 500_000


async def _fetch_table(client: httpx.AsyncClient, table: str, business_id: str
                       ) -> Tuple[List[Dict[str, Any]], bool]:
    """Every row of `table` for this business, and whether that is ALL of
    them.

    Returns (rows, complete). `complete` is False only when the safety
    ceiling was reached — and the caller writes that into the export
    document, because a portability file that is quietly partial is
    worse than one that admits it. A missing table (404) or one with no
    business_id column returns ([], True): nothing to export is not the
    same as failing to export.
    """
    rows: List[Dict[str, Any]] = []
    offset = 0
    while True:
        r = await client.get(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers=_service_headers(),
            params={"business_id": f"eq.{business_id}",
                    "select": _TABLE_SELECT.get(table, "*"),
                    "order": "business_id",     # stable paging order
                    "offset": str(offset), "limit": str(_EXPORT_PAGE)},
        )
        if r.status_code >= 400:
            # First page failing means the table is absent or unscoped —
            # expected, and not an incomplete export. A LATER page
            # failing is a real fault and must not look like the end of
            # the data.
            if offset == 0:
                return [], True
            logger.error("export: %s page at offset %d failed (%s) — "
                         "marking incomplete", table, offset, r.status_code)
            return rows, False
        page = r.json() or []
        rows.extend(page)
        if len(page) < _EXPORT_PAGE:
            return rows, True
        offset += _EXPORT_PAGE
        if len(rows) >= _EXPORT_MAX_ROWS:
            logger.error("export: %s hit the %d-row ceiling for %s",
                         table, _EXPORT_MAX_ROWS, business_id)
            return rows, False


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
            # 2 — rows are paginated rather than capped at 10,000, and
            # every bundle now carries row_counts plus an explicit
            # `complete` flag. An importer can tell v1 (which may be
            # silently short) from v2 (which says so).
            "export_version": 2,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "user": {"id": user.id, "email": user.email},
            "businesses": [],
        }
        for biz in businesses:
            bundle: Dict[str, Any] = {"business": biz, "tables": {},
                                      "row_counts": {}, "complete": True,
                                      "incomplete_tables": []}
            for table in BUSINESS_CHILD_TABLES:
                rows, complete = await _fetch_table(client, table, biz["id"])
                if rows:
                    bundle["tables"][table] = rows
                    # Counts ride along so a recipient can check what
                    # they got against what we said we sent, without
                    # trusting either of us.
                    bundle["row_counts"][table] = len(rows)
                if not complete:
                    bundle["complete"] = False
                    bundle["incomplete_tables"].append(table)
            out["businesses"].append(bundle)
    logger.info(f"export user={user.id} businesses={len(out['businesses'])}")
    return out


# ─── Import ─────────────────────────────────────────────────────────────
#
# An export nobody can import is a file, not portability. This restores a
# bundle from GET /account/export into a NEW business owned by the caller.
#
# THE THREE RULES IT WILL NOT BEND
#
# 1. NEVER into an existing business. Merging an export into live data
#    means deciding what wins on every conflicting row, and getting that
#    wrong destroys the thing they were trying to protect. A fresh
#    business has nothing to lose an argument with.
# 2. Row ids are NOT reused. They may already exist here — a bundle can
#    be imported twice, or back into the account it came from — and
#    reusing them would either collide or silently overwrite. New ids
#    are minted and business_id is remapped.
# 3. It reports every table it could not restore. A partial import that
#    claims success is how somebody finds out three months later that
#    their invoices never came back.
#
# WHAT IT DELIBERATELY DOES NOT IMPORT
#
#   audit_log      the ledger is append-only, sequence-numbered per
#                  tenant and hash-chained. Rows imported into a new
#                  business would take new sequences and break the chain
#                  they exist to prove. History belongs to the business
#                  that lived it; the export keeps it readable.
#   agent_runs,    operational logs of a system this is not.
#   chief_jobs
#   mcp_tokens     live credentials. Re-importing them would resurrect
#                  access somebody may have revoked.
#
# Storage FILES are not covered either — the export is JSON and the
# documents live in S3. Stated here rather than discovered later.

_IMPORT_SKIP = {
    "audit_log", "agent_runs", "chief_jobs", "mcp_tokens",
    # A texting number belongs to the provider account that bought it;
    # a restored business provisions its own. Auditor links and push
    # subscriptions are credentials and devices, not records. The
    # disputes cache is Stripe's, re-fetched on demand.
    "sms_numbers", "auditor_links", "push_subscriptions", "stripe_disputes_cache",
}

# Columns the platform owns. Carrying them across would let an import
# assert its own billing state, or claim rows the hash chain wrote.
_IMPORT_STRIP = {"id", "business_id", "created_at", "sequence",
                 "prev_hash", "row_hash", "verb_registered", "redacted_at"}


class ImportBody(BaseModel):
    bundle: Dict[str, Any]
    business_name: Optional[str] = None


@router.post("/import")
async def import_account(body: ImportBody,
                         user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Restore ONE business bundle into a new business owned by the caller."""
    bundle = body.bundle or {}
    version = bundle.get("export_version")

    # v1 exports could be silently short — they capped every table at
    # 10,000 rows with no pagination and no flag. Importing one is
    # allowed, because refusing somebody their own data would be worse,
    # but the response says what it is rather than letting a partial
    # restore look complete.
    warnings: List[str] = []
    if version == 1:
        warnings.append(
            "this export predates pagination: any table with more than "
            "10,000 rows was silently truncated when it was written")
    elif version != 2:
        raise HTTPException(400, "unsupported export_version")

    businesses = bundle.get("businesses") or []
    if len(businesses) != 1:
        # One at a time, on purpose: a failure halfway through three
        # businesses leaves a mess nobody can reason about.
        raise HTTPException(
            400, "import one business at a time - send a single-business bundle")

    src = businesses[0] or {}
    src_biz = src.get("business") or {}
    if src.get("complete") is False:
        bad = ", ".join(src.get("incomplete_tables") or []) or "unknown tables"
        warnings.append("the export declares itself incomplete: " + bad)

    name = (body.business_name or src_biz.get("name") or "Imported business")

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        created = await client.post(
            SUPABASE_URL + "/rest/v1/businesses",
            headers={**_service_headers(), "Prefer": "return=representation"},
            json={"name": str(name)[:200], "owner_id": str(user.id),
                  "type": src_biz.get("type"),
                  "settings": src_biz.get("settings") or {}},
        )
        if created.status_code >= 400:
            logger.error("import: business create failed: %s", created.text[:300])
            raise HTTPException(502, "could not create the business to import into")
        made = created.json() or []
        row0 = made[0] if isinstance(made, list) and made else made
        new_id = str((row0 or {}).get("id") or "")
        if not new_id:
            raise HTTPException(502, "the new business came back without an id")

        restored: Dict[str, int] = {}
        skipped: Dict[str, str] = {}
        # Deletion runs children-first, so restoration runs parents-first.
        for table in reversed(BUSINESS_CHILD_TABLES):
            if table in _IMPORT_SKIP:
                skipped[table] = "not portable by design"
                continue
            src_rows = (src.get("tables") or {}).get(table) or []
            if not src_rows:
                continue
            payload = []
            for r in src_rows:
                if not isinstance(r, dict):
                    continue
                clean = {k: v for k, v in r.items() if k not in _IMPORT_STRIP}
                clean["business_id"] = new_id
                payload.append(clean)
            if not payload:
                continue

            ok = 0
            for i in range(0, len(payload), _EXPORT_PAGE):
                chunk = payload[i:i + _EXPORT_PAGE]
                resp = await client.post(
                    SUPABASE_URL + "/rest/v1/" + table,
                    headers={**_service_headers(), "Prefer": "return=minimal"},
                    json=chunk)
                if resp.status_code >= 400:
                    # Never abort the whole import for one table. A
                    # dropped column or a renamed table should cost that
                    # table, not the other ninety.
                    skipped[table] = str(resp.status_code) + ": " + resp.text[:120]
                    break
                ok += len(chunk)
            if ok:
                restored[table] = ok

    logger.info("import user=%s -> business=%s tables=%d skipped=%d",
                user.id, new_id, len(restored), len(skipped))

    try:
        import audit_log
        audit_log.record(
            new_id, actor_type="user", actor_id=str(user.id),
            verb="import_business", ok=True, source="account",
            summary="imported " + str(sum(restored.values())) + " rows into a new business",
            payload={"tables": len(restored), "skipped": len(skipped)})
    except Exception:
        pass

    return {"ok": True, "business_id": new_id, "name": name,
            "restored": restored, "rows": sum(restored.values()),
            "skipped": skipped, "warnings": warnings}


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


async def _release_sms_lines(client: httpx.AsyncClient, business_id: str) -> int:
    """Hand the business's texting number(s) back to the provider before
    the row that remembers them is deleted. The normal path is a grace
    window and a sweep (sms_numbers_router.release_sweep); a deleted
    business has no later, so this releases now. Each line is its own
    try: a provider error must not stop the deletion, but it is logged
    loudly because the alternative is a number billing the platform
    for a business that no longer exists."""
    released = 0
    try:
        r = await client.get(
            f"{SUPABASE_URL}/rest/v1/sms_numbers", headers=_service_headers(),
            params={"business_id": f"eq.{business_id}",
                    "status": "in.(active,suspended,releasing)",
                    "select": "id,phone_number,provider_sid"})
        rows = r.json() if r.status_code < 400 else []
    except Exception as e:
        logger.warning(f"[lifecycle] could not list sms lines for {business_id}: {e}")
        return 0
    for row in rows or []:
        sid = row.get("provider_sid")
        try:
            if sid:
                import twilio_sms
                from starlette.concurrency import run_in_threadpool
                await run_in_threadpool(twilio_sms.detach_from_service, sid)
                await run_in_threadpool(twilio_sms.release_number, sid)
            released += 1
        except Exception as e:
            logger.error(f"[lifecycle] release of {row.get('phone_number')} (sid={sid}) "
                         f"failed during business delete: {e} — release it by hand")
    return released


async def _delete_business(client: httpx.AsyncClient, biz: Dict[str, Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    lines = await _release_sms_lines(client, biz["id"])
    if lines:
        counts["_sms_lines_released"] = lines
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
async def delete_business(business_id: str, request: Request,
                          user: AuthedUser = Depends(require_user)):
    """Permanently delete ONE business the caller owns. No undo."""
    # STEP-UP. "No undo" is the whole reason: an unattended session must
    # not be able to erase a practice, and a stolen JWT alone must not
    # be enough either.
    ledger_unlock.require_unlock(request, str(user.id), ledger_unlock.SCOPE_DANGER)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        businesses = await _owned_businesses(client, user.id)
        target = next((b for b in businesses if b["id"] == business_id), None)
        if not target:
            raise HTTPException(404, "Business not found or not yours")
        logger.warning(f"DELETE business {business_id} ({target.get('name')}) by user={user.id}")
        counts = await _delete_business(client, target)
    return {"ok": True, "deleted_business": business_id, "rows_removed": counts}


@router.delete("")
async def delete_account(request: Request,
                         user: AuthedUser = Depends(require_user)):
    """Permanently delete EVERY owned business, then the auth user.
    The session becomes invalid immediately after. No undo."""
    # STEP-UP. The most destructive call in the system.
    ledger_unlock.require_unlock(request, str(user.id), ledger_unlock.SCOPE_DANGER)
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
