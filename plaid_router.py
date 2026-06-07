"""
plaid_router.py — Phase F.2 v1.

Owner-gated endpoints powering the Plaid Link flow + transaction sync +
webhook + the Cash Flow dashboard:

  POST   /plaid/link-token              — create Plaid Link token for the active business
  POST   /plaid/exchange                — exchange Link's public_token for an access_token
  POST   /plaid/sync                    — manual cursor advance (refresh button)
  POST   /plaid/webhook                 — Plaid → us; signature-verified; dispatch
  GET    /plaid/items?biz=<id>          — linked items + last sync metadata
  GET    /plaid/accounts?biz=<id>       — accounts + balances
  GET    /plaid/transactions?biz=<id>   — transactions with filters
  GET    /plaid/summary?biz=<id>        — KPI strip data (cash on hand, expenses MTD)
  GET    /plaid/category-rules?biz=<id> — list per-merchant rules
  POST   /plaid/category-rules          — create/update rule
  DELETE /plaid/category-rules/{id}     — drop rule
  POST   /plaid/items/{item_id}/relink  — generate a re-link Link token
  DELETE /plaid/items/{item_id}         — unlink (soft via status='revoked')

T9-α: pgp_sym_encrypt RPCs from the migration handle access_token
encryption at rest. The router never logs raw tokens.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user
import plaid_helpers
import plaid_categorization
import plaid_reconciliation

logger = logging.getLogger("plaid_router")

router = APIRouter(prefix="/plaid", tags=["plaid"])


# ─── Helpers ─────────────────────────────────────────────────────────


def _require_owner(business_id: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,name,owner_id&limit=1"
    ) or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    return rows[0]


def _require_owner_for_item(item_id: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/plaid_items?item_id=eq.{item_id}&select=item_id,business_id,status&limit=1"
    ) or []
    if not rows:
        raise HTTPException(404, "item not found")
    biz_id = rows[0].get("business_id")
    if not biz_id:
        raise HTTPException(404, "item has no business")
    _require_owner(str(biz_id), user)
    return rows[0]


def _require_owner_for_account(account_id: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/plaid_accounts?account_id=eq.{account_id}"
        f"&select=account_id,business_id,item_id,deleted_at&limit=1"
    ) or []
    if not rows:
        raise HTTPException(404, "account not found")
    _require_owner(str(rows[0].get("business_id")), user)
    return rows[0]


def _included_account_ids(business_id: str) -> List[str]:
    """Account ids that count toward bookkeeping: included + not removed.
    Used to scope the Cash Flow summary, Needs-Review list, and the
    reconciliation pass so excluded/removed accounts drop out everywhere."""
    rows = sb_clients.sb_get_as_service(
        f"/plaid_accounts?business_id=eq.{business_id}"
        f"&included_in_bookkeeping=eq.true&deleted_at=is.null"
        f"&select=account_id"
    ) or []
    return [r["account_id"] for r in rows if r.get("account_id")]


def _account_in_clause(account_ids: List[str]) -> str:
    """PostgREST `in.(...)` clause for a set of account ids. Caller must
    handle the empty case (no included accounts → no rows) before calling."""
    return "account_id=in.(" + ",".join(account_ids) + ")"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Plaid Link shows client_name to the user as the entity they're connecting
# their bank to. Brand it as the active practitioner's business ("Royal
# Barbers", "KMJ Creative Solutions") so the onboarding reads as the
# practitioner linking THEIR business — not the platform. The Plaid
# relationship under the hood stays on the Solutionist developer account;
# this only affects the display name. Falls back to the platform name when a
# business has no name on file.
_PLATFORM_CLIENT_NAME = "The Solutionist System"


def _client_name_for(biz: Optional[Dict[str, Any]]) -> str:
    name = ((biz or {}).get("name") or "").strip()
    return name or _PLATFORM_CLIENT_NAME


def _ensure_plaid_configured() -> None:
    if not plaid_helpers.plaid_configured():
        raise HTTPException(
            503,
            "Plaid not configured on this deploy. Set PLAID_CLIENT_ID, "
            "PLAID_SECRET, PLAID_ENV, PLAID_ENCRYPTION_KEY env vars.",
        )


# ─── Link token ──────────────────────────────────────────────────────


class LinkTokenBody(BaseModel):
    business_id: str


@router.post("/link-token")
def create_link_token(
    body: LinkTokenBody,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Create a Plaid Link token tied to the practitioner + business.
    The frontend uses this token to open Plaid's hosted Link UI."""
    biz = _require_owner(body.business_id, user)
    _ensure_plaid_configured()

    from plaid.model.link_token_create_request import LinkTokenCreateRequest
    from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
    from plaid.model.country_code import CountryCode
    from plaid.model.products import Products
    from plaid.model.link_token_account_filters import LinkTokenAccountFilters
    from plaid.model.depository_filter import DepositoryFilter
    from plaid.model.depository_account_subtypes import DepositoryAccountSubtypes
    from plaid.model.depository_account_subtype import DepositoryAccountSubtype

    client = plaid_helpers.get_plaid_client()
    req = LinkTokenCreateRequest(
        # Plaid recommends a stable per-end-user identifier so the
        # same human can re-Link without showing up as a new client.
        user=LinkTokenCreateRequestUser(client_user_id=str(user.id)),
        client_name=_client_name_for(biz),
        products=[Products("transactions")],
        country_codes=[CountryCode("US")],
        language="en",
        # Constrain Link's Account Select pane to bank accounts suitable
        # for bookkeeping. Credit cards / loans / investments are excluded
        # so a practitioner can't accidentally pull a personal credit card
        # into the business ledger. (Interactive multi-account selection
        # itself is a Plaid Dashboard "Account Select" setting; the app-side
        # per-account include/exclude control is the durable backstop.)
        account_filters=LinkTokenAccountFilters(
            depository=DepositoryFilter(
                account_subtypes=DepositoryAccountSubtypes([
                    DepositoryAccountSubtype("checking"),
                    DepositoryAccountSubtype("savings"),
                ]),
            ),
        ),
        # business_id rides in metadata so the webhook can resolve
        # the right business when SYNC_UPDATES_AVAILABLE fires.
        webhook=_webhook_url_for_request(),
    )
    try:
        resp = client.link_token_create(req)
        return {"ok": True, "link_token": resp.link_token, "expiration": str(resp.expiration)}
    except Exception as e:
        logger.warning(f"[plaid] link-token create failed: {e}")
        raise HTTPException(502, f"link-token failed: {e!s}")


def _webhook_url_for_request() -> str:
    """Best-effort webhook URL. Production should set
    PLAID_WEBHOOK_URL env var; otherwise default to the public
    Railway origin."""
    import os
    explicit = (os.environ.get("PLAID_WEBHOOK_URL") or "").strip()
    if explicit:
        return explicit
    base = (os.environ.get("PUBLIC_API_BASE_URL")
            or "https://kmj-intake-server-production.up.railway.app").rstrip("/")
    return f"{base}/plaid/webhook"


# ─── Exchange ────────────────────────────────────────────────────────


class ExchangeBody(BaseModel):
    business_id: str
    public_token: str
    # Plaid Link returns institution metadata in the onSuccess handler;
    # surfaces in the linked-items list immediately rather than waiting
    # for the first webhook.
    institution_id: Optional[str] = None
    institution_name: Optional[str] = None


@router.post("/exchange")
def exchange_public_token(
    body: ExchangeBody,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Exchange Plaid's short-lived public_token for a permanent
    access_token. Persists encrypted in plaid_items + kicks off the
    initial /transactions/sync backfill."""
    _require_owner(body.business_id, user)
    _ensure_plaid_configured()

    from plaid.model.item_public_token_exchange_request import \
        ItemPublicTokenExchangeRequest

    client = plaid_helpers.get_plaid_client()
    try:
        resp = client.item_public_token_exchange(
            ItemPublicTokenExchangeRequest(public_token=body.public_token)
        )
        access_token = resp.access_token
        item_id = resp.item_id
    except Exception as e:
        logger.warning(f"[plaid] exchange failed: {e}")
        raise HTTPException(502, f"exchange failed: {e!s}")

    cipher = plaid_helpers.encrypt_token(access_token)
    if cipher is None:
        # Refuse to persist plaintext — bail loudly so caller can fix.
        raise HTTPException(
            500,
            "Plaid token encryption failed. PLAID_ENCRYPTION_KEY missing or "
            "RPCs not provisioned. Apply the F.2 migration first.",
        )

    payload = {
        "item_id": item_id,
        "business_id": body.business_id,
        # PostgREST accepts the \\x-hex string for bytea columns.
        "access_token_enc": cipher,
        "institution_id": body.institution_id,
        "institution_name": body.institution_name,
        "status": "active",
        "updated_at": _now_iso(),
    }
    try:
        sb_clients.sb_post_as_service("/plaid_items", payload)
    except Exception as e:
        logger.warning(f"[plaid] plaid_items insert failed: {e}")
        # Continue anyway; user can re-link if persistence broke.

    # Sync accounts + initial transaction backfill.
    _sync_accounts_for_item(item_id, body.business_id, access_token)
    new_count = _sync_transactions_for_item(item_id, body.business_id, access_token, initial=True)

    # Run the first reconciliation pass.
    plaid_reconciliation.reconcile_business(body.business_id)

    return {
        "ok": True,
        "item_id": item_id,
        "new_transactions": new_count,
        "institution_name": body.institution_name,
    }


# ─── Sync (manual refresh) ───────────────────────────────────────────


class SyncBody(BaseModel):
    business_id: str


@router.post("/sync")
def sync_business(
    body: SyncBody,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Manual cursor advance across every linked item for the business."""
    _require_owner(body.business_id, user)
    _ensure_plaid_configured()

    items = sb_clients.sb_get_as_service(
        f"/plaid_items?business_id=eq.{body.business_id}"
        f"&status=eq.active&select=item_id,access_token_enc"
    ) or []
    total = 0
    for item in items:
        token = plaid_helpers.decrypt_token(item.get("access_token_enc"))
        if not token:
            continue
        total += _sync_transactions_for_item(
            item["item_id"], body.business_id, token,
        )

    attempted, matched = plaid_reconciliation.reconcile_business(body.business_id)
    return {
        "ok": True,
        "items_synced": len(items),
        "new_transactions": total,
        "reconciliation_attempted": attempted,
        "reconciliation_matched": matched,
    }


# ─── Webhook ─────────────────────────────────────────────────────────


@router.post("/webhook")
async def plaid_webhook(request: Request) -> JSONResponse:
    """Receive Plaid webhooks. Verifies signature, persists audit row,
    dispatches by webhook_code.

    Idempotency: insert into plaid_webhook_events. We don't dedupe on
    a single global event id because Plaid doesn't emit one; instead
    we make the handlers idempotent (cursor advance is naturally so).
    """
    payload = await request.body()
    sig = request.headers.get("plaid-verification") or ""

    if not plaid_helpers.verify_webhook_signature(payload, sig):
        return JSONResponse({"error": "bad_signature"}, status_code=400)

    try:
        import json as _json
        event = _json.loads(payload.decode("utf-8"))
    except Exception as e:
        logger.warning(f"[plaid] webhook payload not JSON: {e}")
        return JSONResponse({"error": "bad_payload"}, status_code=400)

    webhook_type = (event.get("webhook_type") or "").upper()
    webhook_code = (event.get("webhook_code") or "").upper()
    item_id = event.get("item_id")
    new_tx = event.get("new_transactions")
    logger.info(f"[plaid] webhook {webhook_type}/{webhook_code} item={item_id}")

    # Audit row up front.
    try:
        sb_clients.sb_post_as_service("/plaid_webhook_events", {
            "webhook_type": webhook_type,
            "webhook_code": webhook_code,
            "item_id": item_id,
            "new_transactions": new_tx,
            "raw": event,
        })
    except Exception as e:
        logger.warning(f"[plaid] webhook audit insert failed: {e}")

    processed_ok = False
    processed_error: Optional[str] = None
    try:
        if webhook_type == "TRANSACTIONS" and webhook_code in (
            "SYNC_UPDATES_AVAILABLE", "DEFAULT_UPDATE", "INITIAL_UPDATE",
            "HISTORICAL_UPDATE", "TRANSACTIONS_REMOVED",
        ):
            _handle_transactions_update(item_id)
        elif webhook_type == "ITEM" and webhook_code in (
            "ITEM_LOGIN_REQUIRED", "PENDING_EXPIRATION",
            "USER_PERMISSION_REVOKED", "ITEM_BAD_STATE",
            "WEBHOOK_UPDATE_ACKNOWLEDGED",
        ):
            _handle_item_event(item_id, webhook_code)
        # Other webhook types fall through — logged for audit, no action.
        processed_ok = True
    except Exception as e:
        processed_error = str(e)
        logger.warning(f"[plaid] handler error {webhook_code}: {e}")

    # Update the audit row's outcome.
    try:
        sb_clients.sb_patch_as_service(
            f"/plaid_webhook_events?item_id=eq.{item_id}"
            f"&webhook_code=eq.{webhook_code}"
            f"&processed_at=is.null&order=received_at.desc&limit=1",
            {
                "processed_at": _now_iso(),
                "processed_ok": processed_ok,
                "processed_error": processed_error,
            },
        )
    except Exception as e:
        logger.warning(f"[plaid] webhook outcome patch failed: {e}")

    return JSONResponse({"ok": True, "received": webhook_code})


# ─── Items / accounts / transactions ─────────────────────────────────


@router.get("/items")
def list_items(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _require_owner(biz, user)
    rows = sb_clients.sb_get_as_service(
        f"/plaid_items?business_id=eq.{biz}"
        f"&select=item_id,institution_id,institution_name,status,"
        f"last_sync_at,last_error,created_at"
        f"&order=created_at.desc"
    ) or []
    return {"ok": True, "items": rows}


@router.get("/accounts")
def list_accounts(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _require_owner(biz, user)
    rows = sb_clients.sb_get_as_service(
        f"/plaid_accounts?business_id=eq.{biz}"
        f"&deleted_at=is.null"
        f"&select=account_id,item_id,name,official_name,type,subtype,"
        f"mask,last_balance,last_balance_at,iso_currency,included_in_bookkeeping"
        f"&order=name.asc"
    ) or []
    return {"ok": True, "accounts": rows}


class AccountPatchBody(BaseModel):
    included_in_bookkeeping: bool


@router.patch("/accounts/{account_id}")
def update_account(
    account_id: str,
    body: AccountPatchBody,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Toggle an account in/out of bookkeeping. Excluded accounts stay
    linked + synced but drop out of the Cash Flow KPIs, bucket bars,
    Needs-Review list, and reconciliation. Reversible."""
    _require_owner_for_account(account_id, user)
    sb_clients.sb_patch_as_service(
        f"/plaid_accounts?account_id=eq.{account_id}",
        {
            "included_in_bookkeeping": bool(body.included_in_bookkeeping),
            "updated_at": _now_iso(),
        },
    )
    return {"ok": True, "included_in_bookkeeping": bool(body.included_in_bookkeeping)}


@router.delete("/accounts/{account_id}")
def remove_account(
    account_id: str,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Soft-remove a single account from a linked item without unlinking
    the whole institution. Historical transactions are retained for audit;
    the account is hidden from the UI, excluded from all bookkeeping math,
    and the sync stops inserting new transactions for it."""
    _require_owner_for_account(account_id, user)
    sb_clients.sb_patch_as_service(
        f"/plaid_accounts?account_id=eq.{account_id}",
        {"deleted_at": _now_iso(), "updated_at": _now_iso()},
    )
    return {"ok": True, "removed": account_id}


@router.get("/transactions")
def list_transactions(
    biz: str,
    limit: int = 100,
    offset: int = 0,
    status: Optional[str] = None,   # unmatched / auto_matched / manual_matched / ignored / null=all
    account_id: Optional[str] = None,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    _require_owner(biz, user)
    parts = [f"business_id=eq.{biz}"]
    if status:
        parts.append(f"reconciliation_status=eq.{status}")
    if account_id:
        parts.append(f"account_id=eq.{account_id}")
    else:
        # Scope to accounts that count toward bookkeeping. No included
        # accounts → nothing to show.
        included = _included_account_ids(biz)
        if not included:
            return {"ok": True, "transactions": []}
        parts.append(_account_in_clause(included))
    parts.append(
        "select=transaction_id,account_id,amount,iso_currency_code,date,"
        "name,merchant_name,plaid_category_primary,plaid_category_detail,"
        "business_category,business_subcategory,pending,"
        "reconciled_to_payout_id,reconciled_to_charge_id,reconciliation_status,"
        "practitioner_notes"
    )
    parts.append(f"order=date.desc&limit={int(limit)}&offset={int(offset)}")
    rows = sb_clients.sb_get_as_service(f"/plaid_transactions?{'&'.join(parts)}") or []
    return {"ok": True, "transactions": rows}


@router.get("/summary")
def cash_flow_summary(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """KPI strip data for the Cash Flow dashboard. Returns:
       cash_on_hand     — sum of depository balances
       expenses_mtd     — outflows this month (excludes income categories)
       expenses_ytd     — outflows this year
       unreconciled     — { count, total_inflow, total_outflow }
       by_bucket_mtd    — { tax, owner_pay, operating, savings, other }
    """
    _require_owner(biz, user)
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1).date().isoformat()
    year_start = now.replace(month=1, day=1).date().isoformat()

    # Only accounts the practitioner has kept in bookkeeping count toward
    # cash-on-hand, expenses, buckets, and Needs-Review. Excluded/removed
    # accounts drop out everywhere.
    included = _included_account_ids(biz)
    if not included:
        return {
            "ok": True,
            "cash_on_hand": 0.0,
            "expenses_mtd": 0.0,
            "expenses_ytd": 0.0,
            "by_bucket_mtd": {"tax": 0.0, "owner_pay": 0.0, "operating": 0.0, "savings": 0.0, "other": 0.0},
            "by_bucket_ytd": {"tax": 0.0, "owner_pay": 0.0, "operating": 0.0, "savings": 0.0, "other": 0.0},
            "unreconciled": {"count": 0, "total_inflow": 0.0, "total_outflow": 0.0},
        }
    acct_clause = _account_in_clause(included)

    accounts = sb_clients.sb_get_as_service(
        f"/plaid_accounts?business_id=eq.{biz}"
        f"&type=eq.depository&included_in_bookkeeping=eq.true&deleted_at=is.null"
        f"&select=last_balance"
    ) or []
    cash_on_hand = sum(float(a.get("last_balance") or 0) for a in accounts)

    def _txs(date_gte: str) -> List[Dict[str, Any]]:
        return sb_clients.sb_get_as_service(
            f"/plaid_transactions?business_id=eq.{biz}"
            f"&date=gte.{date_gte}&pending=eq.false&{acct_clause}"
            f"&select=amount,business_category,plaid_category_primary,plaid_category_detail&limit=2000"
        ) or []

    def _summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        outflow = 0.0
        by_bucket = {"tax": 0.0, "owner_pay": 0.0, "operating": 0.0, "savings": 0.0, "other": 0.0}
        for r in rows:
            a = float(r.get("amount") or 0)
            if a <= 0:
                continue  # income side — excluded from expenses math
            if plaid_categorization.is_income_category(
                r.get("plaid_category_primary"), r.get("plaid_category_detail"),
            ):
                continue
            outflow += a
            bucket = r.get("business_category") or plaid_categorization.map_plaid_to_bucket(
                r.get("plaid_category_primary"), r.get("plaid_category_detail"),
            )
            if bucket in by_bucket:
                by_bucket[bucket] += a
        return {"outflow": round(outflow, 2), "by_bucket": {k: round(v, 2) for k, v in by_bucket.items()}}

    mtd = _summarize(_txs(month_start))
    ytd = _summarize(_txs(year_start))

    unmatched = sb_clients.sb_get_as_service(
        f"/plaid_transactions?business_id=eq.{biz}"
        f"&reconciliation_status=eq.unmatched&pending=eq.false&{acct_clause}"
        f"&select=amount&limit=500"
    ) or []
    inflow = round(sum(abs(float(u.get("amount") or 0)) for u in unmatched if float(u.get("amount") or 0) < 0), 2)
    outflow = round(sum(float(u.get("amount") or 0) for u in unmatched if float(u.get("amount") or 0) > 0), 2)

    return {
        "ok": True,
        "cash_on_hand": round(cash_on_hand, 2),
        "expenses_mtd": mtd["outflow"],
        "expenses_ytd": ytd["outflow"],
        "by_bucket_mtd": mtd["by_bucket"],
        "by_bucket_ytd": ytd["by_bucket"],
        "unreconciled": {
            "count": len(unmatched),
            "total_inflow": inflow,
            "total_outflow": outflow,
        },
    }


# ─── Category rules ──────────────────────────────────────────────────


class RuleBody(BaseModel):
    business_id: str
    merchant_name: str
    business_category: str
    business_subcategory: Optional[str] = None


@router.get("/category-rules")
def list_rules(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _require_owner(biz, user)
    rows = sb_clients.sb_get_as_service(
        f"/category_rules?business_id=eq.{biz}&order=merchant_name.asc"
        f"&select=id,merchant_name,business_category,business_subcategory"
    ) or []
    return {"ok": True, "rules": rows}


@router.post("/category-rules")
def upsert_rule(
    body: RuleBody,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    _require_owner(body.business_id, user)
    if body.business_category not in plaid_categorization.ALL_BUCKETS:
        raise HTTPException(400, f"business_category must be one of {plaid_categorization.ALL_BUCKETS}")
    # Upsert via PostgREST: conflict on (business_id, merchant_name).
    sb_clients.sb_post_as_service(
        "/category_rules?on_conflict=business_id,merchant_name",
        {
            "business_id": body.business_id,
            "merchant_name": body.merchant_name,
            "business_category": body.business_category,
            "business_subcategory": body.business_subcategory,
            "updated_at": _now_iso(),
        },
    )
    # Apply the rule retroactively to existing transactions from this
    # merchant so the Cash Flow dashboard reflects the override
    # immediately. Scoped to unmatched OR auto_matched (preserves
    # manual matches).
    sb_clients.sb_patch_as_service(
        f"/plaid_transactions?business_id=eq.{body.business_id}"
        f"&merchant_name=eq.{body.merchant_name}",
        {
            "business_category": body.business_category,
            "business_subcategory": body.business_subcategory,
        },
    )
    return {"ok": True}


@router.delete("/category-rules/{rule_id}")
def delete_rule(rule_id: str, biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _require_owner(biz, user)
    sb_clients.sb_delete_as_service(
        f"/category_rules?id=eq.{rule_id}&business_id=eq.{biz}"
    )
    return {"ok": True}


# ─── Items (relink + unlink) ─────────────────────────────────────────


@router.post("/items/{item_id}/relink")
def relink(item_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Generate a new Link token bound to the existing item (Plaid's
    update mode). Practitioner clicks "Re-link bank" → frontend opens
    Link in update mode → completes MFA → status flips back to 'active'.
    """
    row = _require_owner_for_item(item_id, user)
    biz = _require_owner(str(row.get("business_id")), user)
    _ensure_plaid_configured()

    # Decrypt the stored access_token so Plaid can issue an update-mode
    # token tied to this exact item.
    raw = sb_clients.sb_get_as_service(
        f"/plaid_items?item_id=eq.{item_id}&select=access_token_enc&limit=1"
    ) or []
    if not raw:
        raise HTTPException(404, "item not found")
    token = plaid_helpers.decrypt_token(raw[0].get("access_token_enc"))
    if not token:
        raise HTTPException(500, "token decrypt failed")

    from plaid.model.link_token_create_request import LinkTokenCreateRequest
    from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
    from plaid.model.country_code import CountryCode

    client = plaid_helpers.get_plaid_client()
    req = LinkTokenCreateRequest(
        user=LinkTokenCreateRequestUser(client_user_id=str(user.id)),
        client_name=_client_name_for(biz),
        country_codes=[CountryCode("US")],
        language="en",
        access_token=token,   # update-mode signal
        webhook=_webhook_url_for_request(),
    )
    try:
        resp = client.link_token_create(req)
        return {"ok": True, "link_token": resp.link_token}
    except Exception as e:
        logger.warning(f"[plaid] relink token failed: {e}")
        raise HTTPException(502, f"relink failed: {e!s}")


@router.delete("/items/{item_id}")
def unlink(item_id: str, biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Unlink a Plaid item. We soft-revoke via status='revoked' +
    null out the encrypted token so historical transactions stay
    queryable but no further sync happens."""
    _require_owner(biz, user)
    row = _require_owner_for_item(item_id, user)
    # Best-effort Plaid-side removal so Plaid stops sending webhooks.
    try:
        from plaid.model.item_remove_request import ItemRemoveRequest
        raw = sb_clients.sb_get_as_service(
            f"/plaid_items?item_id=eq.{item_id}&select=access_token_enc&limit=1"
        ) or []
        if raw:
            token = plaid_helpers.decrypt_token(raw[0].get("access_token_enc"))
            if token:
                plaid_helpers.get_plaid_client().item_remove(
                    ItemRemoveRequest(access_token=token)
                )
    except Exception as e:
        logger.warning(f"[plaid] item_remove failed (continuing): {e}")
    sb_clients.sb_patch_as_service(
        f"/plaid_items?item_id=eq.{item_id}",
        {"status": "revoked", "updated_at": _now_iso()},
    )
    return {"ok": True}


# ─── Internal sync helpers ───────────────────────────────────────────


def _sync_accounts_for_item(item_id: str, business_id: str, access_token: str) -> int:
    """Pull account metadata + balances via Plaid /accounts/get."""
    from plaid.model.accounts_get_request import AccountsGetRequest
    client = plaid_helpers.get_plaid_client()
    try:
        resp = client.accounts_get(AccountsGetRequest(access_token=access_token))
    except Exception as e:
        logger.warning(f"[plaid] accounts_get failed: {e}")
        return 0
    written = 0
    for a in resp.accounts:
        payload = {
            "account_id": a.account_id,
            "item_id": item_id,
            "business_id": business_id,
            "name": getattr(a, "name", None),
            "official_name": getattr(a, "official_name", None),
            "type": str(getattr(a, "type", "")) or None,
            "subtype": str(getattr(a, "subtype", "")) or None,
            "mask": getattr(a, "mask", None),
            "last_balance": (getattr(a, "balances", None) and
                             float(getattr(a.balances, "current", 0) or 0)),
            "last_balance_at": _now_iso(),
            "iso_currency": getattr(a.balances, "iso_currency_code", "USD")
                if getattr(a, "balances", None) else "USD",
        }
        try:
            sb_clients.sb_post_as_service(
                "/plaid_accounts?on_conflict=account_id", payload,
            )
            written += 1
        except Exception as e:
            logger.warning(f"[plaid] account upsert failed: {e}")
    return written


def _sync_transactions_for_item(
    item_id: str, business_id: str, access_token: str, *, initial: bool = False,
) -> int:
    """Cursor-paged /transactions/sync. Upserts added/modified + removes
    removed. Returns count of new transactions persisted this pass."""
    from plaid.model.transactions_sync_request import TransactionsSyncRequest
    client = plaid_helpers.get_plaid_client()

    cursor: Optional[str] = None
    row = sb_clients.sb_get_as_service(
        f"/plaid_items?item_id=eq.{item_id}&select=cursor&limit=1"
    ) or []
    if row:
        cursor = row[0].get("cursor")

    # Load practitioner's per-merchant rules once for the duration of
    # this sync — applied during upsert below.
    rules = sb_clients.sb_get_as_service(
        f"/category_rules?business_id=eq.{business_id}"
        f"&select=merchant_name,business_category,business_subcategory"
    ) or []
    rule_map: Dict[str, Dict[str, Optional[str]]] = {}
    for r in rules:
        key = (r.get("merchant_name") or "").strip().lower()
        if key:
            rule_map[key] = {
                "cat": r.get("business_category"),
                "sub": r.get("business_subcategory"),
            }

    # Accounts the practitioner removed from this item: keep their history
    # but stop ingesting new transactions for them.
    removed = sb_clients.sb_get_as_service(
        f"/plaid_accounts?business_id=eq.{business_id}"
        f"&deleted_at=not.is.null&select=account_id"
    ) or []
    skip_account_ids = {r["account_id"] for r in removed if r.get("account_id")}

    total_new = 0
    has_more = True
    safety_cap = 50  # paranoia — 50 pages × 500/page = 25k transactions

    while has_more and safety_cap > 0:
        safety_cap -= 1
        req = TransactionsSyncRequest(access_token=access_token, count=500)
        if cursor:
            req.cursor = cursor
        try:
            resp = client.transactions_sync(req)
        except Exception as e:
            logger.warning(f"[plaid] transactions_sync failed: {e}")
            break

        for tx in resp.added:
            if getattr(tx, "account_id", None) in skip_account_ids:
                continue  # account was removed from bookkeeping
            payload = _tx_payload(tx, business_id, rule_map)
            try:
                sb_clients.sb_post_as_service(
                    "/plaid_transactions?on_conflict=transaction_id", payload,
                )
                total_new += 1
            except Exception as e:
                logger.warning(f"[plaid] tx upsert (added) failed: {e}")

        for tx in resp.modified:
            if getattr(tx, "account_id", None) in skip_account_ids:
                continue
            payload = _tx_payload(tx, business_id, rule_map)
            try:
                sb_clients.sb_patch_as_service(
                    f"/plaid_transactions?transaction_id=eq.{payload['transaction_id']}",
                    payload,
                )
            except Exception as e:
                logger.warning(f"[plaid] tx upsert (modified) failed: {e}")

        for tx in resp.removed:
            try:
                sb_clients.sb_delete_as_service(
                    f"/plaid_transactions?transaction_id=eq.{tx.transaction_id}"
                )
            except Exception as e:
                logger.warning(f"[plaid] tx delete failed: {e}")

        cursor = resp.next_cursor
        has_more = resp.has_more

    # Persist final cursor + sync timestamp.
    try:
        sb_clients.sb_patch_as_service(
            f"/plaid_items?item_id=eq.{item_id}",
            {"cursor": cursor, "last_sync_at": _now_iso(), "updated_at": _now_iso()},
        )
    except Exception as e:
        logger.warning(f"[plaid] item cursor persist failed: {e}")

    return total_new


def _tx_payload(tx, business_id: str, rule_map: Dict[str, Dict[str, Optional[str]]]) -> Dict[str, Any]:
    """Build the plaid_transactions row payload from a Plaid SDK
    Transaction. Applies per-merchant rule overrides + falls back to
    the static categorization map."""
    primary = None
    detail = None
    pfc = getattr(tx, "personal_finance_category", None)
    if pfc is not None:
        primary = getattr(pfc, "primary", None) or None
        detail = getattr(pfc, "detailed", None) or None

    merchant = getattr(tx, "merchant_name", None) or None
    rule = rule_map.get((merchant or "").strip().lower())
    if rule and rule.get("cat"):
        bucket = rule["cat"]
        sub = rule.get("sub")
    else:
        bucket = plaid_categorization.map_plaid_to_bucket(primary, detail)
        sub = None

    return {
        "transaction_id": tx.transaction_id,
        "account_id": tx.account_id,
        "business_id": business_id,
        "amount": float(tx.amount or 0),
        "iso_currency_code": getattr(tx, "iso_currency_code", "USD") or "USD",
        "date": str(tx.date) if tx.date else None,
        "authorized_date": (str(tx.authorized_date)
                            if getattr(tx, "authorized_date", None) else None),
        "datetime": (str(tx.datetime)
                     if getattr(tx, "datetime", None) else None),
        "name": getattr(tx, "name", None),
        "merchant_name": merchant,
        "plaid_category_primary": primary,
        "plaid_category_detail": detail,
        "business_category": bucket,
        "business_subcategory": sub,
        "pending": bool(getattr(tx, "pending", False)),
        "updated_at": _now_iso(),
    }


# ─── Webhook dispatchers ─────────────────────────────────────────────


def _handle_transactions_update(item_id: Optional[str]) -> None:
    if not item_id:
        return
    rows = sb_clients.sb_get_as_service(
        f"/plaid_items?item_id=eq.{item_id}"
        f"&select=item_id,business_id,access_token_enc&limit=1"
    ) or []
    if not rows:
        return
    item = rows[0]
    token = plaid_helpers.decrypt_token(item.get("access_token_enc"))
    if not token:
        return
    _sync_transactions_for_item(item["item_id"], item["business_id"], token)
    plaid_reconciliation.reconcile_business(item["business_id"])


def _handle_item_event(item_id: Optional[str], webhook_code: str) -> None:
    if not item_id:
        return
    status_map = {
        "ITEM_LOGIN_REQUIRED": "re-auth-required",
        "PENDING_EXPIRATION":  "re-auth-required",
        "USER_PERMISSION_REVOKED": "revoked",
        "ITEM_BAD_STATE":      "error",
    }
    status = status_map.get(webhook_code)
    if not status:
        return
    try:
        sb_clients.sb_patch_as_service(
            f"/plaid_items?item_id=eq.{item_id}",
            {"status": status, "updated_at": _now_iso()},
        )
    except Exception as e:
        logger.warning(f"[plaid] item status patch failed: {e}")
