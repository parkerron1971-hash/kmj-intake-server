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
from fastapi.responses import JSONResponse, Response
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


def _require_owner_for_tx(transaction_id: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/plaid_transactions?transaction_id=eq.{transaction_id}"
        f"&select=transaction_id,business_id&limit=1"
    ) or []
    if not rows:
        raise HTTPException(404, "transaction not found")
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

    # Arc 19 F-A2 — per-tier connected-account limit (gate-ready;
    # enforced only with BILLING_ENFORCE=on; grandfathered bypass).
    import billing_limits as _bl
    _cap = _bl.can_connect_account(body.business_id)
    if _cap.get("enforce") and not _cap.get("allowed"):
        raise HTTPException(402, {
            "error": "plaid_connection_cap",
            "message": f"Your plan includes {_cap.get('limit')} connected bank "
                       f"account(s) — this business has {_cap.get('count')}. "
                       "Upgrade in Settings → Billing to connect more.",
        })

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
        f"mask,last_balance,last_balance_at,iso_currency,included_in_bookkeeping,"
        f"is_trust_account"
        f"&order=name.asc"
    ) or []
    return {"ok": True, "accounts": rows}


class AccountPatchBody(BaseModel):
    included_in_bookkeeping: Optional[bool] = None
    is_trust_account: Optional[bool] = None    # I.7 — lawyer IOLTA routing


@router.patch("/accounts/{account_id}")
def update_account(
    account_id: str,
    body: AccountPatchBody,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Toggle an account in/out of bookkeeping, or mark it a TRUST account
    (I.7 — its activity then books to the trust ledger 1200 ↔ 2200, never
    income/expense). Both toggles re-route what the GL wants for every
    transaction on the account, so we enqueue them all for the live sync —
    no manual Reverse + Backfill needed. Reversible."""
    acct_row = _require_owner_for_account(account_id, user)
    fields: Dict[str, Any] = {}
    if body.included_in_bookkeeping is not None:
        fields["included_in_bookkeeping"] = bool(body.included_in_bookkeeping)
    if body.is_trust_account is not None:
        fields["is_trust_account"] = bool(body.is_trust_account)
    if not fields:
        raise HTTPException(422, "No account fields to update.")
    sb_clients.sb_patch_as_service(
        f"/plaid_accounts?account_id=eq.{account_id}",
        {**fields, "updated_at": _now_iso()},
    )
    # Converge the GL: every settled transaction on this account may now want
    # a different entry shape. Best-effort — the divergence tick is backstop.
    try:
        biz = str(acct_row.get("business_id") or "")
        if biz:
            txs = sb_clients.sb_get_as_service(
                f"/plaid_transactions?account_id=eq.{account_id}&business_id=eq.{biz}"
                f"&pending=eq.false&select=transaction_id&limit=20000") or []
            if txs:
                sb_clients.sb_post_as_service("/gl_sync_queue", [
                    {"business_id": biz, "source_table": "plaid_transactions",
                     "source_id": t["transaction_id"]} for t in txs], prefer=None)
    except Exception as e:
        logger.warning(f"[plaid] account-toggle GL enqueue failed: {e}")
    return {"ok": True, **fields}


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


_TX_SELECT = (
    "select=transaction_id,account_id,amount,iso_currency_code,date,"
    "authorized_date,datetime,name,merchant_name,"
    "plaid_category_primary,plaid_category_detail,"
    "business_category,business_subcategory,pending,excluded_from_books,trust_contact_id,"
    "reconciled_to_payout_id,reconciled_to_charge_id,reconciled_to_transfer_id,"
    "reconciliation_status,practitioner_notes,notes"
)

_SORT_COLUMNS = {
    "date": "date",
    "amount": "amount",
    "merchant": "merchant_name",
    "bucket": "business_category",
}


def _sanitize_search(q: str) -> str:
    """Strip characters that would break the PostgREST or=() / ilike
    grammar, and encode spaces. Keeps single + multi-word merchant search
    working without admitting clause injection."""
    cleaned = "".join(c for c in q if c not in "(),*.")
    return cleaned.strip().replace(" ", "%20")


def _bucket_clause(buckets: List[str]) -> Optional[str]:
    """Build a PostgREST predicate for a 5-bucket multi-select that may
    include the synthetic 'uncategorized' (business_category IS NULL)."""
    wants_null = "uncategorized" in buckets
    named = [b for b in buckets if b in plaid_categorization.ALL_BUCKETS]
    if wants_null and named:
        return f"or=(business_category.is.null,business_category.in.({','.join(named)}))"
    if wants_null:
        return "business_category=is.null"
    if named:
        return f"business_category=in.({','.join(named)})"
    return None


@router.get("/transactions")
def list_transactions(
    biz: str,
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,        # back-compat single recon status (Needs Review)
    account_id: Optional[str] = None,    # back-compat single-account drilldown
    accounts: Optional[str] = None,      # csv account_ids (multi-select)
    buckets: Optional[str] = None,       # csv 5-bucket incl. 'uncategorized'
    plaid_primaries: Optional[str] = None,  # csv Plaid PFC primaries
    recon: Optional[str] = None,         # csv reconciliation_status
    search: Optional[str] = None,        # merchant/name free text
    date_from: Optional[str] = None,     # yyyy-mm-dd
    date_to: Optional[str] = None,       # yyyy-mm-dd
    include_excluded: bool = False,      # show excluded_from_books rows
    sort: str = "date",
    direction: str = "desc",
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Paginated, filterable transactions list. Powers both the Needs
    Review modal (status=unmatched) and the dedicated Transactions panel.

    Excluded-from-books rows are hidden unless include_excluded=true, so
    existing callers (Needs Review) keep their pre-v1.5 behavior."""
    _require_owner(biz, user)

    # Account scope: explicit selection wins; otherwise all included
    # accounts. Removed accounts never appear.
    if account_id:
        acct_ids = [account_id]
    elif accounts:
        acct_ids = [a for a in accounts.split(",") if a]
    else:
        acct_ids = _included_account_ids(biz)
    if not acct_ids:
        return {"ok": True, "transactions": [], "has_more": False}

    parts = [f"business_id=eq.{biz}", _account_in_clause(acct_ids)]

    if not include_excluded:
        parts.append("excluded_from_books=eq.false")
    if status:
        parts.append(f"reconciliation_status=eq.{status}")
    if recon:
        rec = [r for r in recon.split(",") if r]
        if rec:
            parts.append(f"reconciliation_status=in.({','.join(rec)})")
    if buckets:
        bc = _bucket_clause([b for b in buckets.split(",") if b])
        if bc:
            parts.append(bc)
    if plaid_primaries:
        pp = [p for p in plaid_primaries.split(",") if p]
        if pp:
            parts.append(f"plaid_category_primary=in.({','.join(pp)})")
    if date_from:
        parts.append(f"date=gte.{date_from}")
    if date_to:
        parts.append(f"date=lte.{date_to}")
    if search and search.strip():
        q = _sanitize_search(search)
        if q:
            parts.append(f"or=(merchant_name.ilike.*{q}*,name.ilike.*{q}*)")

    col = _SORT_COLUMNS.get(sort, "date")
    dir_ = "asc" if direction == "asc" else "desc"
    # Secondary date key keeps ordering stable when the primary ties.
    order = f"{col}.{dir_}" if col == "date" else f"{col}.{dir_},date.desc"

    capped = max(1, min(int(limit), 200))
    parts.append(_TX_SELECT)
    # Fetch one extra row to cheaply decide has_more without a count query.
    parts.append(f"order={order}&limit={capped + 1}&offset={int(offset)}")

    rows = sb_clients.sb_get_as_service(f"/plaid_transactions?{'&'.join(parts)}") or []
    has_more = len(rows) > capped
    return {"ok": True, "transactions": rows[:capped], "has_more": has_more}


@router.get("/transactions/{transaction_id}")
def get_transaction(
    transaction_id: str,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Single-transaction detail for the drawer, with the owning account's
    name/mask/subtype joined in."""
    _require_owner_for_tx(transaction_id, user)
    rows = sb_clients.sb_get_as_service(
        f"/plaid_transactions?transaction_id=eq.{transaction_id}&{_TX_SELECT}&limit=1"
    ) or []
    if not rows:
        raise HTTPException(404, "transaction not found")
    tx = rows[0]
    acct = sb_clients.sb_get_as_service(
        f"/plaid_accounts?account_id=eq.{tx.get('account_id')}"
        f"&select=name,official_name,mask,subtype,type,is_trust_account&limit=1"
    ) or []
    tx["account"] = acct[0] if acct else None
    return {"ok": True, "transaction": tx}


class TxPatchBody(BaseModel):
    business_category: Optional[str] = None
    business_subcategory: Optional[str] = None
    excluded_from_books: Optional[bool] = None
    notes: Optional[str] = None
    trust_contact_id: Optional[str] = None    # I.10 — per-client trust tagging ("" clears)
    override_reason: Optional[str] = None     # required to edit a closed-period txn


@router.patch("/transactions/{transaction_id}")
def update_transaction(
    transaction_id: str,
    body: TxPatchBody,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Per-transaction edit from the detail drawer: bucket, subcategory,
    exclude-from-books, notes. Only provided fields are written."""
    tx = _require_owner_for_tx(transaction_id, user)
    # Phase I.3 PR2 — soft-lock: edits to a closed-period transaction need a reason.
    import period_lock
    cur = sb_clients.sb_get_as_service(
        f"/plaid_transactions?transaction_id=eq.{transaction_id}&select=date,business_id&limit=1") or [{}]
    period_lock.guard(str(tx.get("business_id")), (cur[0].get("date") or "")[:10],
                      source_type="plaid_transaction", source_id=transaction_id,
                      reason=body.override_reason, override_by=str(user.id),
                      pre=cur[0], post=body.model_dump())
    patch: Dict[str, Any] = {"updated_at": _now_iso()}
    if body.business_category is not None:
        if body.business_category not in plaid_categorization.ALL_BUCKETS:
            raise HTTPException(400, f"business_category must be one of {plaid_categorization.ALL_BUCKETS}")
        patch["business_category"] = body.business_category
    if body.business_subcategory is not None:
        patch["business_subcategory"] = body.business_subcategory or None
    if body.excluded_from_books is not None:
        patch["excluded_from_books"] = bool(body.excluded_from_books)
    if body.notes is not None:
        patch["notes"] = body.notes or None
    if body.trust_contact_id is not None:
        patch["trust_contact_id"] = body.trust_contact_id or None
    sb_clients.sb_patch_as_service(
        f"/plaid_transactions?transaction_id=eq.{transaction_id}", patch,
    )
    return {"ok": True}


class BulkCategorizeBody(BaseModel):
    business_id: str
    transaction_ids: List[str]
    business_category: str
    business_subcategory: Optional[str] = None


@router.post("/transactions/bulk-categorize")
def bulk_categorize(
    body: BulkCategorizeBody,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Categorize many transactions in one atomic UPDATE (single PostgREST
    request → single SQL statement → all-or-none)."""
    _require_owner(body.business_id, user)
    if body.business_category not in plaid_categorization.ALL_BUCKETS:
        raise HTTPException(400, f"business_category must be one of {plaid_categorization.ALL_BUCKETS}")
    ids = [t for t in body.transaction_ids if t]
    if not ids:
        return {"ok": True, "updated": 0}
    res = sb_clients.sb_patch_as_service(
        f"/plaid_transactions?business_id=eq.{body.business_id}"
        f"&transaction_id=in.({','.join(ids)})",
        {
            "business_category": body.business_category,
            "business_subcategory": body.business_subcategory or None,
            "updated_at": _now_iso(),
        },
    )
    return {"ok": True, "updated": len(res or [])}


class BulkExcludeBody(BaseModel):
    business_id: str
    transaction_ids: List[str]
    excluded_from_books: bool


@router.post("/transactions/bulk-exclude")
def bulk_exclude(
    body: BulkExcludeBody,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Exclude/include many transactions in one atomic UPDATE."""
    _require_owner(body.business_id, user)
    ids = [t for t in body.transaction_ids if t]
    if not ids:
        return {"ok": True, "updated": 0}
    res = sb_clients.sb_patch_as_service(
        f"/plaid_transactions?business_id=eq.{body.business_id}"
        f"&transaction_id=in.({','.join(ids)})",
        {
            "excluded_from_books": bool(body.excluded_from_books),
            "updated_at": _now_iso(),
        },
    )
    return {"ok": True, "updated": len(res or [])}


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
            f"&date=gte.{date_gte}&pending=eq.false&excluded_from_books=eq.false&{acct_clause}"
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
        f"&reconciliation_status=eq.unmatched&pending=eq.false&excluded_from_books=eq.false&{acct_clause}"
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


# ═════════════════════════════════════════════════════════════════════
# Reconciliation UI — Phase F.2 v1.6
# ═════════════════════════════════════════════════════════════════════
# Visibility + manual-match surface over the auto-match worker. Stripe
# payouts (left) ↔ Plaid deposits (right). All reads scope to included
# accounts + not-excluded transactions.

_MATCHED_STATUSES = ("auto_matched", "manual_matched")
# Manual-match suggestion tolerance (F.2 v1.6 ruling).
_SUGGEST_DAYS = 5
_SUGGEST_AMOUNT_PCT = 0.05


def _recon_date_floor(date_range: Optional[str]) -> Optional[str]:
    """Map a date_range token to a yyyy-mm-dd floor, or None for all-time."""
    if not date_range or date_range == "all":
        return None
    now = datetime.now(timezone.utc)
    if date_range == "mtd":
        return now.replace(day=1).date().isoformat()
    if date_range == "ytd":
        return now.replace(month=1, day=1).date().isoformat()
    from datetime import timedelta
    days = {"7d": 7, "30d": 30, "90d": 90}.get(date_range)
    if days:
        return (now - timedelta(days=days)).date().isoformat()
    return None


def _recon_scope(biz: str, account_id: Optional[str] = None) -> Optional[str]:
    """Account-scope clause for reconciliation reads, or None if there are
    no included accounts (caller returns empty)."""
    if account_id:
        return _account_in_clause([account_id])
    included = _included_account_ids(biz)
    if not included:
        return None
    return _account_in_clause(included)


def _recon_matched_rows(
    biz: str, scope: str, *, floor: Optional[str] = None,
    match_type: Optional[str] = None, limit: int = 1000, offset: int = 0,
) -> List[Dict[str, Any]]:
    parts = [
        f"business_id=eq.{biz}", scope, "excluded_from_books=eq.false",
        "reconciled_to_payout_id=not.is.null",
    ]
    if match_type == "auto":
        parts.append("reconciliation_status=eq.auto_matched")
    elif match_type == "manual":
        parts.append("reconciliation_status=eq.manual_matched")
    else:
        parts.append(f"reconciliation_status=in.({','.join(_MATCHED_STATUSES)})")
    if floor:
        parts.append(f"date=gte.{floor}")
    parts.append(
        "select=transaction_id,account_id,amount,iso_currency_code,date,name,"
        "merchant_name,reconciliation_status,reconciled_to_payout_id,"
        "reconciled_payout_amount,reconciled_payout_date,manual_match_reason"
    )
    parts.append(f"order=date.desc&limit={int(limit)}&offset={int(offset)}")
    return sb_clients.sb_get_as_service(f"/plaid_transactions?{'&'.join(parts)}") or []


def _recon_unmatched_plaid(
    biz: str, scope: str, *, floor: Optional[str] = None,
    limit: int = 1000, offset: int = 0,
) -> List[Dict[str, Any]]:
    """Plaid deposits (inflow → negative amount) with no Stripe match."""
    parts = [
        f"business_id=eq.{biz}", scope, "excluded_from_books=eq.false",
        "pending=eq.false", "reconciliation_status=eq.unmatched", "amount=lt.0",
    ]
    if floor:
        parts.append(f"date=gte.{floor}")
    parts.append(
        "select=transaction_id,account_id,amount,iso_currency_code,date,name,"
        "merchant_name,reconciliation_status"
    )
    parts.append(f"order=date.desc&limit={int(limit)}&offset={int(offset)}")
    return sb_clients.sb_get_as_service(f"/plaid_transactions?{'&'.join(parts)}") or []


def _matched_payout_ids(biz: str) -> set:
    rows = sb_clients.sb_get_as_service(
        f"/plaid_transactions?business_id=eq.{biz}"
        f"&reconciled_to_payout_id=not.is.null&select=reconciled_to_payout_id"
    ) or []
    return {r["reconciled_to_payout_id"] for r in rows if r.get("reconciled_to_payout_id")}


def _recon_unmatched_stripe(biz: str, floor: Optional[str]) -> List[Dict[str, Any]]:
    """Stripe payouts with no Plaid match, within the date window."""
    stripe_acct = plaid_reconciliation.stripe_account_for_business(biz)
    if not stripe_acct:
        return []
    from datetime import date as _date, timedelta
    today = datetime.now(timezone.utc).date()
    if floor:
        try:
            y, m, d = (int(p) for p in floor.split("-"))
            start = _date(y, m, d)
        except Exception:
            start = today - timedelta(days=90)
    else:
        start = today - timedelta(days=90)
    payouts = plaid_reconciliation.fetch_stripe_payouts_range(stripe_acct, start, today)
    matched = _matched_payout_ids(biz)
    out = []
    for po in payouts:
        if po.get("id") in matched:
            continue
        out.append({
            "stripe_payout_id": po.get("id"),
            "amount": round((po.get("amount") or 0) / 100.0, 2),
            "currency": (po.get("currency") or "usd").upper(),
            "arrival_date": plaid_reconciliation._payout_arrival_iso(po),
            "status": po.get("status"),
        })
    return out


@router.get("/reconciliation/summary")
def reconciliation_summary(
    biz: str, user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    _require_owner(biz, user)
    empty = {"count": 0, "total": 0.0, "mtd_count": 0, "mtd_total": 0.0}
    scope = _recon_scope(biz)
    if scope is None:
        return {"ok": True, "matched": empty, "unmatched": empty, "rate": 0.0, "last_run": None}

    month_start = datetime.now(timezone.utc).replace(day=1).date().isoformat()

    def _agg(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        total = mtd_total = 0.0
        mtd_count = 0
        for r in rows:
            amt = abs(float(r.get("amount") or 0))
            total += amt
            if (r.get("date") or "") >= month_start:
                mtd_total += amt
                mtd_count += 1
        return {"count": len(rows), "total": round(total, 2),
                "mtd_count": mtd_count, "mtd_total": round(mtd_total, 2)}

    matched = sb_clients.sb_get_as_service(
        f"/plaid_transactions?business_id=eq.{biz}&{scope}"
        f"&excluded_from_books=eq.false"
        f"&reconciliation_status=in.({','.join(_MATCHED_STATUSES)})"
        f"&select=amount,date&limit=5000"
    ) or []
    unmatched = sb_clients.sb_get_as_service(
        f"/plaid_transactions?business_id=eq.{biz}&{scope}"
        f"&excluded_from_books=eq.false&pending=eq.false"
        f"&reconciliation_status=eq.unmatched&amount=lt.0"
        f"&select=amount,date&limit=5000"
    ) or []

    m_agg, u_agg = _agg(matched), _agg(unmatched)
    denom = m_agg["count"] + u_agg["count"]
    rate = round(100.0 * m_agg["count"] / denom, 1) if denom else 0.0

    items = sb_clients.sb_get_as_service(
        f"/plaid_items?business_id=eq.{biz}&select=last_sync_at"
    ) or []
    stamps = sorted([i["last_sync_at"] for i in items if i.get("last_sync_at")])
    last_run = stamps[-1] if stamps else None

    return {"ok": True, "matched": m_agg, "unmatched": u_agg, "rate": rate, "last_run": last_run}


@router.get("/reconciliation/matches")
def reconciliation_matches(
    biz: str, limit: int = 50, offset: int = 0,
    date_range: Optional[str] = None, account_id: Optional[str] = None,
    match_type: Optional[str] = None,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    _require_owner(biz, user)
    scope = _recon_scope(biz, account_id)
    if scope is None:
        return {"ok": True, "matches": [], "has_more": False}
    capped = max(1, min(int(limit), 200))
    rows = _recon_matched_rows(
        biz, scope, floor=_recon_date_floor(date_range),
        match_type=match_type, limit=capped + 1, offset=offset,
    )
    return {"ok": True, "matches": rows[:capped], "has_more": len(rows) > capped}


@router.get("/reconciliation/unmatched")
def reconciliation_unmatched(
    biz: str, side: str = "plaid", limit: int = 50, offset: int = 0,
    date_range: Optional[str] = None,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    _require_owner(biz, user)
    floor = _recon_date_floor(date_range)
    if side == "stripe":
        return {"ok": True, "side": "stripe", "unmatched": _recon_unmatched_stripe(biz, floor), "has_more": False}
    scope = _recon_scope(biz)
    if scope is None:
        return {"ok": True, "side": "plaid", "unmatched": [], "has_more": False}
    capped = max(1, min(int(limit), 200))
    rows = _recon_unmatched_plaid(biz, scope, floor=floor, limit=capped + 1, offset=offset)
    return {"ok": True, "side": "plaid", "unmatched": rows[:capped], "has_more": len(rows) > capped}


@router.get("/reconciliation/suggestions")
def reconciliation_suggestions(
    biz: str, side: str, id: str,
    amount: Optional[float] = None, date: Optional[str] = None,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Suggest counterpart matches within ±5 days and ±5% amount.

    side='stripe': `id` is a payout; pass its amount (dollars) + date so we
      can find Plaid deposits without a live Stripe retrieve.
    side='plaid': `id` is a deposit; we read its amount/date from the row
      and search Stripe payouts in range."""
    _require_owner(biz, user)
    from datetime import date as _date, timedelta

    def _parse(d: str) -> Optional[_date]:
        try:
            y, m, dd = (int(p) for p in d.split("-"))
            return _date(y, m, dd)
        except Exception:
            return None

    if side == "stripe":
        if amount is None or not date:
            raise HTTPException(400, "stripe suggestions need amount + date")
        anchor = _parse(date)
        if not anchor:
            raise HTTPException(400, "bad date")
        lo = (anchor - timedelta(days=_SUGGEST_DAYS)).isoformat()
        hi = (anchor + timedelta(days=_SUGGEST_DAYS)).isoformat()
        scope = _recon_scope(biz)
        if scope is None:
            return {"ok": True, "suggestions": []}
        rows = sb_clients.sb_get_as_service(
            f"/plaid_transactions?business_id=eq.{biz}&{scope}"
            f"&excluded_from_books=eq.false&reconciliation_status=eq.unmatched&amount=lt.0"
            f"&date=gte.{lo}&date=lte.{hi}"
            f"&select=transaction_id,account_id,amount,date,name,merchant_name&limit=50"
        ) or []
        tol = abs(float(amount)) * _SUGGEST_AMOUNT_PCT
        sugg = [r for r in rows if abs(abs(float(r.get("amount") or 0)) - abs(float(amount))) <= tol]
        return {"ok": True, "suggestions": sugg}

    # side == 'plaid'
    dep = sb_clients.sb_get_as_service(
        f"/plaid_transactions?transaction_id=eq.{id}&business_id=eq.{biz}"
        f"&select=amount,date&limit=1"
    ) or []
    if not dep:
        raise HTTPException(404, "transaction not found")
    dep_amt = abs(float(dep[0].get("amount") or 0))
    anchor = _parse(dep[0].get("date") or "")
    if not anchor:
        return {"ok": True, "suggestions": []}
    stripe_acct = plaid_reconciliation.stripe_account_for_business(biz)
    if not stripe_acct:
        return {"ok": True, "suggestions": []}
    payouts = plaid_reconciliation.fetch_stripe_payouts_range(
        stripe_acct, anchor - timedelta(days=_SUGGEST_DAYS), anchor + timedelta(days=_SUGGEST_DAYS),
    )
    matched = _matched_payout_ids(biz)
    tol = dep_amt * _SUGGEST_AMOUNT_PCT
    sugg = []
    for po in payouts:
        if po.get("id") in matched:
            continue
        po_amt = (po.get("amount") or 0) / 100.0
        if abs(po_amt - dep_amt) <= tol:
            sugg.append({
                "stripe_payout_id": po.get("id"),
                "amount": round(po_amt, 2),
                "arrival_date": plaid_reconciliation._payout_arrival_iso(po),
            })
    return {"ok": True, "suggestions": sugg}


class MatchBody(BaseModel):
    business_id: str
    plaid_transaction_id: str
    stripe_payout_id: str
    payout_amount: Optional[float] = None   # dollars
    payout_date: Optional[str] = None       # yyyy-mm-dd
    reason: Optional[str] = "manual_match"


@router.post("/reconciliation/match")
def reconciliation_match(
    body: MatchBody, user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Create a manual match. Idempotent: re-matching the same pair is a
    no-op; matching a payout already bound to a *different* deposit → 409."""
    _require_owner(body.business_id, user)
    _require_owner_for_tx(body.plaid_transaction_id, user)

    existing = sb_clients.sb_get_as_service(
        f"/plaid_transactions?business_id=eq.{body.business_id}"
        f"&reconciled_to_payout_id=eq.{body.stripe_payout_id}"
        f"&select=transaction_id"
    ) or []
    for r in existing:
        if r.get("transaction_id") != body.plaid_transaction_id:
            raise HTTPException(409, "that payout is already matched to another transaction")

    patch: Dict[str, Any] = {
        "reconciled_to_payout_id": body.stripe_payout_id,
        "reconciliation_status": "manual_matched",
        "manual_match_reason": body.reason or "manual_match",
        "ignored_at": None,
        "updated_at": _now_iso(),
    }
    if body.payout_amount is not None:
        patch["reconciled_payout_amount"] = round(float(body.payout_amount), 2)
    if body.payout_date:
        patch["reconciled_payout_date"] = body.payout_date
    sb_clients.sb_patch_as_service(
        f"/plaid_transactions?transaction_id=eq.{body.plaid_transaction_id}"
        f"&business_id=eq.{body.business_id}", patch,
    )
    return {"ok": True}


class UnmatchBody(BaseModel):
    business_id: str
    plaid_transaction_id: str


@router.post("/reconciliation/unmatch")
def reconciliation_unmatch(
    body: UnmatchBody, user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Reverse a match (auto or manual) back to unmatched."""
    _require_owner(body.business_id, user)
    _require_owner_for_tx(body.plaid_transaction_id, user)
    sb_clients.sb_patch_as_service(
        f"/plaid_transactions?transaction_id=eq.{body.plaid_transaction_id}"
        f"&business_id=eq.{body.business_id}",
        {
            "reconciled_to_payout_id": None,
            "reconciled_payout_amount": None,
            "reconciled_payout_date": None,
            "manual_match_reason": None,
            "reconciliation_status": "unmatched",
            "updated_at": _now_iso(),
        },
    )
    return {"ok": True}


class IgnoreBody(BaseModel):
    business_id: str
    plaid_transaction_id: str
    reason: Optional[str] = None


@router.post("/reconciliation/ignore")
def reconciliation_ignore(
    body: IgnoreBody, user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Mark a Plaid deposit as deliberately not-reconcilable."""
    _require_owner(body.business_id, user)
    _require_owner_for_tx(body.plaid_transaction_id, user)
    sb_clients.sb_patch_as_service(
        f"/plaid_transactions?transaction_id=eq.{body.plaid_transaction_id}"
        f"&business_id=eq.{body.business_id}",
        {
            "reconciliation_status": "ignored",
            "ignored_at": _now_iso(),
            "manual_match_reason": body.reason or None,
            "updated_at": _now_iso(),
        },
    )
    return {"ok": True}


@router.post("/reconciliation/run")
def reconciliation_run(
    body: SyncBody, user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Trigger the auto-match worker over the business's unmatched deposits."""
    _require_owner(body.business_id, user)
    attempted, matched = plaid_reconciliation.reconcile_business(body.business_id)
    return {"ok": True, "attempted": attempted, "matched": matched}


@router.get("/reconciliation/export")
def reconciliation_export(
    biz: str, format: str = "csv", date_range: Optional[str] = None,
    user: AuthedUser = Depends(require_user),
) -> Response:
    """Generate a reconciliation report as a direct download (no server-side
    storage). CSV always available; PDF when reportlab is present."""
    biz_row = _require_owner(biz, user)
    biz_name = (biz_row.get("name") or "Business")
    floor = _recon_date_floor(date_range)
    scope = _recon_scope(biz)
    matched = _recon_matched_rows(biz, scope, floor=floor, limit=5000) if scope else []
    un_plaid = _recon_unmatched_plaid(biz, scope, floor=floor, limit=5000) if scope else []
    un_stripe = _recon_unmatched_stripe(biz, floor)

    if format == "pdf":
        import pdf_reports
        settings_rows = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{biz}&select=settings&limit=1") or []
        settings = (settings_rows[0].get("settings") if settings_rows else None)
        meta = pdf_reports.build_meta(
            business_name=biz_name, settings=settings,
            report_title="Reconciliation Report",
            period_label=(f"Window: {date_range}" if date_range else "All time"),
            basis_label="Cash Basis", currency="USD",
            generated_by=(getattr(user, "email", None) or ""))
        try:
            pdf = pdf_reports.render("reconciliation", {
                "matched": matched, "unmatched_plaid": un_plaid, "unmatched_stripe": un_stripe,
            }, meta)
        except ImportError:
            raise HTTPException(503, "PDF export unavailable on this server (reportlab missing). Use format=csv.")
        return Response(
            content=pdf, media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="reconciliation.pdf"'},
        )

    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["section", "date", "stripe_payout_id", "payout_amount",
                "plaid_transaction_id", "plaid_amount", "plaid_name", "match_type"])
    for r in matched:
        w.writerow([
            "matched", r.get("date"), r.get("reconciled_to_payout_id"),
            r.get("reconciled_payout_amount"), r.get("transaction_id"),
            r.get("amount"), r.get("merchant_name") or r.get("name"),
            r.get("reconciliation_status"),
        ])
    for r in un_plaid:
        w.writerow(["unmatched_plaid", r.get("date"), "", "",
                    r.get("transaction_id"), r.get("amount"),
                    r.get("merchant_name") or r.get("name"), ""])
    for r in un_stripe:
        w.writerow(["unmatched_stripe", r.get("arrival_date"), r.get("stripe_payout_id"),
                    r.get("amount"), "", "", "", ""])
    return Response(
        content=buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="reconciliation.csv"'},
    )


def _render_recon_pdf(biz_name, date_range, matched, un_plaid, un_stripe) -> bytes:
    """ReportLab summary + tables. Raises ImportError when reportlab is
    absent so the endpoint can fall back to a clear 503."""
    import io
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    )
    from reportlab.lib.styles import getSampleStyleSheet

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, title="Reconciliation Report")
    styles = getSampleStyleSheet()
    story = []
    story.append(Paragraph("Reconciliation Report", styles["Title"]))
    story.append(Paragraph(biz_name, styles["Heading2"]))
    story.append(Paragraph(f"Window: {date_range or 'all time'}", styles["Normal"]))
    story.append(Spacer(1, 0.2 * inch))

    m_total = sum(abs(float(r.get("amount") or 0)) for r in matched)
    up_total = sum(abs(float(r.get("amount") or 0)) for r in un_plaid)
    us_total = sum(abs(float(r.get("amount") or 0)) for r in un_stripe)
    story.append(Paragraph(
        f"Matched: {len(matched)} (${m_total:,.2f}) · "
        f"Unmatched deposits: {len(un_plaid)} (${up_total:,.2f}) · "
        f"Unmatched payouts: {len(un_stripe)} (${us_total:,.2f})",
        styles["Normal"],
    ))
    story.append(Spacer(1, 0.2 * inch))

    def _table(title, header, rows):
        story.append(Paragraph(title, styles["Heading3"]))
        data = [header] + rows if rows else [header, ["—"] * len(header)]
        t = Table(data, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#222")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f4f4")]),
        ]))
        story.append(t)
        story.append(Spacer(1, 0.2 * inch))

    _table(
        "Matched", ["Date", "Stripe Payout", "Payout $", "Plaid Deposit", "Type"],
        [[r.get("date"), (r.get("reconciled_to_payout_id") or "")[:18],
          f"${float(r.get('reconciled_payout_amount') or 0):,.2f}",
          f"${abs(float(r.get('amount') or 0)):,.2f}", r.get("reconciliation_status")]
         for r in matched[:200]],
    )
    _table(
        "Unmatched bank deposits", ["Date", "Name", "Amount"],
        [[r.get("date"), (r.get("merchant_name") or r.get("name") or "")[:40],
          f"${abs(float(r.get('amount') or 0)):,.2f}"] for r in un_plaid[:200]],
    )
    _table(
        "Unmatched Stripe payouts", ["Arrival", "Payout", "Amount"],
        [[r.get("arrival_date"), (r.get("stripe_payout_id") or "")[:18],
          f"${float(r.get('amount') or 0):,.2f}"] for r in un_stripe[:200]],
    )
    story.append(Spacer(1, 0.4 * inch))
    story.append(Paragraph("_______________________________", styles["Normal"]))
    story.append(Paragraph("Reviewed by / date", styles["Normal"]))
    doc.build(story)
    return buf.getvalue()
