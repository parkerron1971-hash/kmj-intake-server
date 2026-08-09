"""
quickbooks_router.py — Rails Arc 1: the QuickBooks bridge.

The bridge is PUSH-ONLY by ruling: we send clean entries out; we never
run a live two-way sync (that is where reconciliation nightmares come
from). The one thing built well here is the MAPPING LAYER — our chart
of accounts → their chart of accounts, configured once per business.
Every export (IIF today, QBO API journal pushes in Arc 1b) resolves
account names through it.

Surface:
  GET    /quickbooks/mappings?biz=  — our COA joined with any mappings,
                                      plus the business's book-of-record
  PUT    /quickbooks/mappings?biz=  — upsert mappings; empty name clears
  GET    /connect/quickbooks        — Intuit OAuth entry (signed state)
  GET    /connect/quickbooks/callback
  GET    /quickbooks/status?biz=
  DELETE /quickbooks/disconnect?biz=
  POST   /quickbooks/sync-accounts?biz= — their real COA (id+name) for
                                      the mapping picklist; auto-links
                                      exact-name matches
  POST   /quickbooks/push?biz=      — the year's journal entries into
                                      QBO, idempotent via
                                      quickbooks_pushed_entries; refuses
                                      cleanly while accounts are unmapped

Env: QB_CLIENT_ID / QB_CLIENT_SECRET (Railway), QB_ENVIRONMENT
(sandbox default), QB_REDIRECT_URI (defaults to the production
callback registered in the Intuit portal), QB_FRONTEND_RETURN_URL.

Book-of-record (source-of-truth ruling, set per business):
  businesses.settings.financial.book_of_record = 'solutionist' (default)
  | 'quickbooks'. Smaller clients: we are the record and QB is optional;
  bigger clients already living in QB: they are the record, we sync out.
  Stored in settings by the frontend; surfaced here so one GET paints
  the whole admin section.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

import oauth_connect_ticket
import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("quickbooks_router")

router = APIRouter(prefix="/quickbooks", tags=["quickbooks"])
# OAuth entry/callback live outside the /quickbooks prefix so the
# redirect URI registered in the Intuit portal
# (…/connect/quickbooks/callback) matches exactly.
connect_router = APIRouter(tags=["quickbooks"])

PROVIDER = "quickbooks"

# ─── Intuit endpoints ────────────────────────────────────────────────
QB_AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
QB_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
QB_REVOKE_URL = "https://developer.api.intuit.com/v2/oauth2/tokens/revoke"
QB_SCOPE = "com.intuit.quickbooks.accounting"
QB_MINORVERSION = "75"
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=15.0, pool=10.0)
# QBO caps DocNumber at 21 chars — a breadcrumb, not the dedupe (the
# quickbooks_pushed_entries table is).
DOCNUMBER_MAX = 21


def _client_id() -> str:
    v = os.environ.get("QB_CLIENT_ID", "").strip()
    if not v:
        raise HTTPException(500, "QB_CLIENT_ID not configured")
    return v


def _client_secret() -> str:
    v = os.environ.get("QB_CLIENT_SECRET", "").strip()
    if not v:
        raise HTTPException(500, "QB_CLIENT_SECRET not configured")
    return v


def _environment() -> str:
    v = (os.environ.get("QB_ENVIRONMENT") or "sandbox").strip().lower()
    return v if v in ("sandbox", "production") else "sandbox"


def _api_base() -> str:
    return ("https://quickbooks.api.intuit.com" if _environment() == "production"
            else "https://sandbox-quickbooks.api.intuit.com")


def _redirect_uri() -> str:
    return os.environ.get(
        "QB_REDIRECT_URI",
        "https://kmj-intake-server-production.up.railway.app/connect/quickbooks/callback")


def _frontend_return_url() -> str:
    return os.environ.get("QB_FRONTEND_RETURN_URL",
                          os.environ.get("META_FRONTEND_RETURN_URL",
                                         "https://mysolutionist.app"))


# ─── State signing (CSRF protection, stateless — meta_oauth pattern).
# HMAC key = the client secret: server-side already, no new env var.

def _make_state(business_id: str) -> str:
    payload = {"business_id": business_id, "ts": int(time.time())}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    sig = hmac.new(_client_secret().encode("utf-8"),
                   body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _verify_state(state: str, max_age_s: int = 900) -> Optional[str]:
    """Returns the business_id, or None on any tamper/expiry."""
    try:
        body, sig = (state or "").split(".", 1)
        expected = hmac.new(_client_secret().encode("utf-8"),
                            body.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        pad = "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(body + pad))
        if int(time.time()) - int(payload.get("ts") or 0) > max_age_s:
            return None
        return payload.get("business_id") or None
    except Exception:
        return None


def _owner(biz: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,owner_id,settings&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    return rows[0]


def get_mappings(biz: str) -> Dict[str, Dict[str, Any]]:
    """account_code -> mapping row. The export path calls this directly."""
    rows = sb_clients.sb_get_as_service(
        f"/coa_external_mappings?business_id=eq.{biz}&provider=eq.{PROVIDER}"
        f"&select=account_code,external_name,external_id,external_type&limit=500") or []
    return {r["account_code"]: r for r in rows}


def _activity_by_code(lines: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Ledger lines -> {code: {entries, volume}}. Volume = total money
    moved through the account (debits + credits) — the friendliest
    single signal for 'is this account one you actually use'."""
    out: Dict[str, Dict[str, Any]] = {}
    for l in lines:
        code = l.get("account_code") or ""
        if not code:
            continue
        a = out.setdefault(code, {"entries": 0, "volume": 0.0})
        a["entries"] += 1
        a["volume"] += float(l.get("debit") or 0) + float(l.get("credit") or 0)
    for a in out.values():
        a["volume"] = round(a["volume"], 2)
    return out


# ─── The suggestion engine (bookkeeping-UX mandate, 7/31) ────────────
# The user should never hand-translate our chart of accounts into
# QuickBooks vocabulary — the system knows both languages. Rubric, not
# lookup table: class guard first (an income account never maps to
# their expense account), then exact name, then a synonym pass for the
# terms the two systems genuinely name differently, then fuzzy match.

_QBO_TYPE_CLASS = {
    "Bank": "asset", "Other Current Asset": "asset", "Fixed Asset": "asset",
    "Other Asset": "asset", "Accounts Receivable": "asset",
    "Accounts Payable": "liability", "Credit Card": "liability",
    "Other Current Liability": "liability", "Long Term Liability": "liability",
    "Equity": "equity",
    "Income": "income", "Other Income": "income",
    "Expense": "expense", "Other Expense": "expense",
    "Cost of Goods Sold": "expense",
}

# our normalized token -> tokens that mean the same thing in QBO-land.
_SYNONYMS = {
    "cash": ("checking", "bank", "cash on hand"),
    "contractors": ("subcontractors", "contract labor", "contractor"),
    "contractor payments": ("subcontractors", "contract labor"),
    "owner pay": ("owner's pay", "owner draw", "distributions", "personal"),
    "owner draw": ("owner's pay", "distributions"),
    "revenue": ("sales", "services", "income", "service income"),
    "sales": ("sales of product income", "sales", "income"),
    "software": ("dues & subscriptions", "dues and subscriptions", "office expenses"),
    "supplies": ("supplies & materials", "supplies and materials", "job supplies"),
    "tax": ("taxes & licenses", "taxes and licenses", "payroll tax"),
    "savings": ("savings",),
    "marketing": ("advertising", "advertising & marketing"),
}


def _norm(s: str) -> str:
    return " ".join((s or "").lower().replace("&", "and").split())


def suggest_qbo_match(our_account: Dict[str, Any],
                      qbo_accounts: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Best QBO account for one of ours, or None below confidence.
    Returns {external_id, external_name, external_type, confidence}."""
    import difflib

    our_type = (our_account.get("type") or "").lower()
    our_name = _norm(our_account.get("name") or "")
    if not our_name:
        return None

    candidates = [a for a in qbo_accounts
                  if _QBO_TYPE_CLASS.get(a.get("type") or "", "?") == our_type]
    if not candidates:
        return None

    best, best_score = None, 0.0
    syn = _SYNONYMS.get(our_name, ())
    for a in candidates:
        qn = _norm(a.get("name") or "")
        if not qn:
            continue
        if qn == our_name:
            score = 1.0
        elif qn in syn or any(s in qn for s in syn):
            score = 0.9
        else:
            score = difflib.SequenceMatcher(None, our_name, qn).ratio() * 0.85
        if score > best_score:
            best, best_score = a, score

    if not best or best_score < 0.55:
        return None
    return {"external_id": best.get("id"), "external_name": best.get("name"),
            "external_type": best.get("type"),
            "confidence": round(best_score, 2)}


@router.get("/mappings")
def list_mappings(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    b = _owner(biz, user)
    accounts = sb_clients.sb_get_as_service(
        f"/chart_of_accounts?business_id=eq.{biz}"
        f"&select=code,name,type,profit_first_bucket&order=code.asc&limit=500") or []
    mapped = get_mappings(biz)
    # Bookkeeping-UX mandate: show which accounts the business actually
    # USES, so mapping stops being a guessing game over 17 rows.
    lines = sb_clients.sb_get_as_service(
        f"/ledger_entries?business_id=eq.{biz}"
        f"&select=account_code,debit,credit&limit=100000") or []
    activity = _activity_by_code(lines)
    book_of_record = (((b.get("settings") or {}).get("financial") or {})
                      .get("book_of_record") or "solutionist")
    return {
        "book_of_record": book_of_record,
        "accounts": [
            {
                "code": a["code"],
                "name": a.get("name") or a["code"],
                "type": a.get("type"),
                "external_name": (mapped.get(a["code"]) or {}).get("external_name"),
                "external_id": (mapped.get(a["code"]) or {}).get("external_id"),
                "entries": (activity.get(a["code"]) or {}).get("entries", 0),
                "volume": (activity.get(a["code"]) or {}).get("volume", 0.0),
            }
            for a in accounts
        ],
        "mapped_count": len(mapped),
    }


class MappingItem(BaseModel):
    account_code: str
    external_name: str = ""
    # Set when the name was picked from the live QBO list / suggestions —
    # links the mapping immediately instead of waiting for the next
    # sync-accounts auto-link pass.
    external_id: str = ""


class PutMappingsBody(BaseModel):
    mappings: List[MappingItem]


@router.put("/mappings")
def put_mappings(biz: str, body: PutMappingsBody,
                 user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Upsert the business's mappings. An empty external_name clears the
    mapping (the export falls back to our account name)."""
    _owner(biz, user)
    valid_codes = {a["code"] for a in (sb_clients.sb_get_as_service(
        f"/chart_of_accounts?business_id=eq.{biz}&select=code&limit=500") or [])}

    saved, cleared, skipped = 0, 0, []
    for item in body.mappings:
        code = (item.account_code or "").strip()
        name = (item.external_name or "").strip()
        if code not in valid_codes:
            skipped.append(code)
            continue
        if not name:
            sb_clients.sb_delete_as_service(
                f"/coa_external_mappings?business_id=eq.{biz}"
                f"&provider=eq.{PROVIDER}&account_code=eq.{code}")
            cleared += 1
            continue
        row = {"business_id": biz, "provider": PROVIDER,
               "account_code": code, "external_name": name[:120],
               "updated_at": datetime.now(timezone.utc).isoformat()}
        if (item.external_id or "").strip():
            row["external_id"] = item.external_id.strip()[:40]
        sb_clients.sb_post_as_service(
            "/coa_external_mappings?on_conflict=business_id,provider,account_code",
            row, prefer="resolution=merge-duplicates,return=representation")
        saved += 1

    logger.info(f"[qb] mappings updated biz={biz[:8]} saved={saved} "
                f"cleared={cleared} skipped={len(skipped)}")
    return {"ok": True, "saved": saved, "cleared": cleared, "skipped": skipped}


# ═══════════════════════════════════════════════════════════════════════
# Arc 1b — the live QBO connection (OAuth, account sync, journal push)
# ═══════════════════════════════════════════════════════════════════════

def _get_connection(biz: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/quickbooks_connections?business_id=eq.{biz}&limit=1") or []
    return rows[0] if rows else None


def _save_tokens(biz: str, tok: Dict[str, Any], realm_id: Optional[str] = None,
                 company_name: Optional[str] = None) -> None:
    """Upsert the token pair. Intuit ROTATES the refresh token — always
    store the pair returned by the latest exchange/refresh."""
    now = datetime.now(timezone.utc)
    row: Dict[str, Any] = {
        "business_id": biz,
        "access_token": tok["access_token"],
        "refresh_token": tok["refresh_token"],
        "access_expires_at": (now + timedelta(seconds=int(tok.get("expires_in") or 3600))).isoformat(),
        "refresh_expires_at": (now + timedelta(seconds=int(tok.get("x_refresh_token_expires_in") or 8726400))).isoformat(),
        "environment": _environment(),
        "status": "connected",
        "last_error": None,
        "updated_at": now.isoformat(),
    }
    if realm_id:
        row["realm_id"] = realm_id
    if company_name:
        row["company_name"] = company_name
    sb_clients.sb_post_as_service(
        "/quickbooks_connections?on_conflict=business_id", row,
        prefer="resolution=merge-duplicates,return=representation")


async def _token_request(form: Dict[str, str]) -> Dict[str, Any]:
    basic = base64.b64encode(f"{_client_id()}:{_client_secret()}".encode()).decode()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.post(QB_TOKEN_URL, data=form, headers={
            "Authorization": f"Basic {basic}",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        })
    if r.status_code >= 400:
        logger.error(f"[qb] token endpoint {r.status_code}: {r.text[:300]}")
        raise HTTPException(502, f"Intuit token exchange failed ({r.status_code})")
    return r.json()


async def _fresh_access_token(biz: str) -> Tuple[str, str]:
    """(access_token, realm_id) — refreshing (and re-storing the rotated
    pair) when the access token is expired or nearly so."""
    conn = _get_connection(biz)
    if not conn or conn.get("status") != "connected":
        raise HTTPException(409, "QuickBooks is not connected for this business")
    exp = conn.get("access_expires_at") or ""
    try:
        expires = datetime.fromisoformat(exp.replace("Z", "+00:00"))
    except ValueError:
        expires = datetime.now(timezone.utc)
    if expires > datetime.now(timezone.utc) + timedelta(minutes=3):
        return conn["access_token"], conn["realm_id"]
    tok = await _token_request({
        "grant_type": "refresh_token",
        "refresh_token": conn["refresh_token"],
    })
    _save_tokens(biz, tok, realm_id=conn["realm_id"])
    return tok["access_token"], conn["realm_id"]


async def _qbo_get(biz: str, path: str, params: Dict[str, str]) -> Dict[str, Any]:
    access, realm = await _fresh_access_token(biz)
    url = f"{_api_base()}/v3/company/{realm}{path}"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.get(url, params={**params, "minorversion": QB_MINORVERSION},
                        headers={"Authorization": f"Bearer {access}",
                                 "Accept": "application/json"})
    if r.status_code >= 400:
        logger.error(f"[qb] GET {path} {r.status_code}: {r.text[:300]}")
        raise HTTPException(502, f"QuickBooks API error ({r.status_code})")
    return r.json()


async def _qbo_post(biz: str, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    access, realm = await _fresh_access_token(biz)
    url = f"{_api_base()}/v3/company/{realm}{path}"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.post(url, params={"minorversion": QB_MINORVERSION}, json=body,
                         headers={"Authorization": f"Bearer {access}",
                                  "Accept": "application/json"})
    if r.status_code >= 400:
        logger.error(f"[qb] POST {path} {r.status_code}: {r.text[:400]}")
        raise HTTPException(502, f"QuickBooks API error ({r.status_code}): {r.text[:200]}")
    return r.json()


# ─── OAuth entry + callback (mounted WITHOUT the /quickbooks prefix) ──

def _require_owner(business_id: str, user: AuthedUser) -> None:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=owner_id&limit=1") or []
    if not rows:
        raise HTTPException(status_code=404, detail="business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized for this business")


@connect_router.get("/connect/quickbooks/start")
async def qb_connect_start(business_id: str, user: AuthedUser = Depends(require_user)):
    """The authenticated half of the connect handshake.

    The redirect below cannot check ownership — it is opened with
    window.open and carries no bearer token, which is why the check was
    absent rather than merely forgotten. It happens here instead, and
    the caller gets a short-lived ticket to redirect with.
    """
    _require_owner(business_id, user)
    return {"authorize_url":
            f"/connect/quickbooks?ticket={oauth_connect_ticket.mint(business_id, user.id)}"}


@connect_router.get("/connect/quickbooks")
async def qb_connect(business_id: str = "", ticket: str = ""):
    """Redirect to Intuit's consent screen.

    A signed `state` proves the state came from our server — NOT that
    whoever holds it owns the business it names. Without that second
    fact anyone could open this URL with a stranger's business_id,
    authorise with their own Intuit account, and have their realm bound
    to that tenant. `ticket` carries the missing fact.
    """
    if ticket:
        verified_biz, _uid = oauth_connect_ticket.verify(ticket)
        if not verified_biz:
            raise HTTPException(400, "this connect link expired — start again from the app")
        business_id = verified_biz
    elif business_id:
        if not oauth_connect_ticket.legacy_business_id_allowed():
            raise HTTPException(400, "connect must be started from the app")
        oauth_connect_ticket.warn_legacy("quickbooks", business_id)
    if not business_id:
        raise HTTPException(400, "business_id required")
    params = {
        "client_id": _client_id(),
        "response_type": "code",
        "scope": QB_SCOPE,
        "redirect_uri": _redirect_uri(),
        "state": _make_state(business_id),
    }
    return RedirectResponse(url=f"{QB_AUTH_URL}?{urlencode(params)}", status_code=302)


@connect_router.get("/connect/quickbooks/callback")
async def qb_callback(code: str = "", state: str = "", realmId: str = "", error: str = ""):
    ret = _frontend_return_url()
    if error or not code:
        return RedirectResponse(f"{ret}?qb=error&reason={error or 'no_code'}", status_code=302)
    biz = _verify_state(state)
    if not biz:
        return RedirectResponse(f"{ret}?qb=error&reason=bad_state", status_code=302)
    if not realmId:
        return RedirectResponse(f"{ret}?qb=error&reason=no_realm", status_code=302)

    tok = await _token_request({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _redirect_uri(),
    })
    _save_tokens(biz, tok, realm_id=realmId)

    # Company name — best-effort nicety for the status card.
    try:
        info = await _qbo_get(biz, f"/companyinfo/{realmId}", {})
        name = ((info.get("CompanyInfo") or {}).get("CompanyName") or "").strip()
        if name:
            sb_clients.sb_patch_as_service(
                f"/quickbooks_connections?business_id=eq.{biz}",
                {"company_name": name})
    except Exception as e:
        logger.warning(f"[qb] companyinfo fetch skipped: {e}")

    logger.info(f"[qb] connected biz={biz[:8]} realm={realmId} env={_environment()}")
    return RedirectResponse(f"{ret}?qb=connected", status_code=302)


# ─── Status / disconnect ─────────────────────────────────────────────

@router.get("/status")
def qb_status(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    conn = _get_connection(biz)
    if not conn:
        return {"connected": False, "environment": _environment(),
                "configured": bool(os.environ.get("QB_CLIENT_ID"))}
    pushed = sb_clients.sb_get_as_service(
        f"/quickbooks_pushed_entries?business_id=eq.{biz}"
        f"&select=pushed_at&order=pushed_at.desc&limit=1") or []
    return {
        "connected": conn.get("status") == "connected",
        "status": conn.get("status"),
        "company_name": conn.get("company_name"),
        "environment": conn.get("environment"),
        "connected_at": conn.get("connected_at"),
        "last_error": conn.get("last_error"),
        "last_push_at": pushed[0]["pushed_at"] if pushed else None,
        "configured": True,
    }


@router.delete("/disconnect")
async def qb_disconnect(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    conn = _get_connection(biz)
    if not conn:
        return {"ok": True, "was_connected": False}
    try:
        basic = base64.b64encode(f"{_client_id()}:{_client_secret()}".encode()).decode()
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            await c.post(QB_REVOKE_URL, json={"token": conn["refresh_token"]},
                         headers={"Authorization": f"Basic {basic}",
                                  "Content-Type": "application/json"})
    except Exception as e:
        logger.warning(f"[qb] revoke call failed (continuing): {e}")
    sb_clients.sb_patch_as_service(
        f"/quickbooks_connections?business_id=eq.{biz}",
        {"status": "disconnected", "updated_at": datetime.now(timezone.utc).isoformat()})
    return {"ok": True, "was_connected": True}


# ─── Account sync (their real chart of accounts) ─────────────────────

@router.post("/sync-accounts")
async def qb_sync_accounts(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Fetch the connected company's Account list so the mapping editor
    offers THEIR real accounts (name + id) instead of free typing.
    Also backfills external_id on any mapping whose external_name
    exactly matches a QBO account."""
    _owner(biz, user)
    data = await _qbo_get(biz, "/query", {
        "query": "select Id, Name, AccountType, AccountSubType from Account "
                 "where Active = true maxresults 1000"})
    accounts = ((data.get("QueryResponse") or {}).get("Account")) or []
    out = [{"id": a.get("Id"), "name": a.get("Name"),
            "type": a.get("AccountType"), "subtype": a.get("AccountSubType")}
           for a in accounts]

    # Backfill external_id where names already line up.
    by_name = {(a["name"] or "").strip().lower(): a for a in out}
    linked = 0
    mapped = get_mappings(biz)
    for code, m in mapped.items():
        if m.get("external_id"):
            continue
        hit = by_name.get((m.get("external_name") or "").strip().lower())
        if hit:
            sb_clients.sb_patch_as_service(
                f"/coa_external_mappings?business_id=eq.{biz}"
                f"&provider=eq.{PROVIDER}&account_code=eq.{code}",
                {"external_id": hit["id"], "external_type": hit["type"]})
            linked += 1

    # Bookkeeping-UX mandate: the system speaks both vocabularies, so
    # it does the matching. Suggestions for every account not yet
    # mapped — the user reviews and saves instead of translating.
    ours = sb_clients.sb_get_as_service(
        f"/chart_of_accounts?business_id=eq.{biz}"
        f"&select=code,name,type&order=code.asc&limit=500") or []
    suggestions = []
    for a in ours:
        if (mapped.get(a["code"]) or {}).get("external_id"):
            continue
        s = suggest_qbo_match(a, out)
        if s:
            suggestions.append({"code": a["code"], **s})

    return {"ok": True, "accounts": out, "count": len(out),
            "auto_linked": linked, "suggestions": suggestions}


# ─── The push (push-only by ruling; idempotent by ledger) ────────────

def _build_qbo_journal(je: Dict[str, Any], lines: List[Dict[str, Any]],
                       account_id_by_code: Dict[str, str]) -> Dict[str, Any]:
    """Our journal entry + lines -> a QBO JournalEntry payload. Raises
    ValueError naming any account code that has no mapped QBO id —
    callers surface that as 'map these accounts first', before anything
    is pushed."""
    qbo_lines = []
    missing: List[str] = []
    for l in lines:
        code = l.get("account_code") or ""
        acct_id = account_id_by_code.get(code)
        if not acct_id:
            missing.append(code)
            continue
        debit = float(l.get("debit") or 0)
        credit = float(l.get("credit") or 0)
        amount = round(debit if debit > 0 else credit, 2)
        if amount <= 0:
            continue
        qbo_lines.append({
            "Amount": amount,
            "DetailType": "JournalEntryLineDetail",
            "Description": (l.get("memo") or je.get("description") or "")[:4000],
            "JournalEntryLineDetail": {
                "PostingType": "Debit" if debit > 0 else "Credit",
                "AccountRef": {"value": acct_id},
            },
        })
    if missing:
        raise ValueError(",".join(sorted(set(missing))))
    return {
        "TxnDate": je.get("entry_date"),
        "DocNumber": f"SOL-{(je.get('id') or '').replace('-', '')[:17]}"[:DOCNUMBER_MAX],
        "PrivateNote": f"Solutionist System journal {je.get('id')}"[:4000],
        "Line": qbo_lines,
    }


class PushBody(BaseModel):
    year: int
    limit: int = 200


@router.post("/push")
async def qb_push(biz: str, body: PushBody,
                  user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Push the year's active, non-reversal journal entries to QBO,
    skipping anything already in the idempotency ledger. Refuses cleanly
    (nothing pushed) when any touched account lacks a mapped QBO id."""
    _owner(biz, user)

    mappings = get_mappings(biz)
    account_id_by_code = {c: m["external_id"] for c, m in mappings.items()
                          if m.get("external_id")}

    jes = sb_clients.sb_get_as_service(
        f"/journal_entries?business_id=eq.{biz}&status=eq.active"
        f"&entry_date=gte.{body.year}-01-01&entry_date=lte.{body.year}-12-31"
        f"&order=entry_date.asc,created_at.asc"
        f"&select=id,entry_date,description,source_type,is_reversal&limit=10000") or []
    jes = [j for j in jes if not j.get("is_reversal")]

    already = {r["journal_entry_id"] for r in (sb_clients.sb_get_as_service(
        f"/quickbooks_pushed_entries?business_id=eq.{biz}"
        f"&select=journal_entry_id&limit=100000") or [])}
    todo = [j for j in jes if j["id"] not in already][: max(1, min(body.limit, 500))]
    if not todo:
        return {"ok": True, "pushed": 0, "skipped_already": len(already),
                "remaining": 0, "note": "Everything in range is already in QuickBooks."}

    # Lines for the batch.
    lines_by_je: Dict[str, List[Dict[str, Any]]] = {}
    ids = [j["id"] for j in todo]
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        rows = sb_clients.sb_get_as_service(
            f"/ledger_entries?journal_entry_id=in.({','.join(chunk)})"
            f"&select=journal_entry_id,account_code,debit,credit,memo&limit=10000") or []
        for l in rows:
            lines_by_je.setdefault(l["journal_entry_id"], []).append(l)

    # Pre-flight the WHOLE batch before pushing anything.
    unmapped: set = set()
    payloads: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for j in todo:
        lines = lines_by_je.get(j["id"]) or []
        if not lines:
            continue
        try:
            payloads.append((j, _build_qbo_journal(j, lines, account_id_by_code)))
        except ValueError as e:
            unmapped.update(str(e).split(","))
    if unmapped:
        return {"ok": False, "pushed": 0,
                "unmapped_accounts": sorted(unmapped),
                "note": "Map these accounts to QuickBooks accounts first "
                        "(run Load QuickBooks accounts, then save mappings)."}

    pushed = 0
    for je, payload in payloads:
        res = await _qbo_post(biz, "/journalentry", payload)
        qbo_id = ((res.get("JournalEntry") or {}).get("Id")) or ""
        sb_clients.sb_post_as_service(
            "/quickbooks_pushed_entries?on_conflict=business_id,journal_entry_id",
            {"business_id": biz, "journal_entry_id": je["id"],
             "qbo_journal_id": qbo_id},
            prefer="resolution=merge-duplicates,return=representation")
        pushed += 1

    remaining = len(jes) - len(already) - pushed
    logger.info(f"[qb] push biz={biz[:8]} year={body.year} pushed={pushed} "
                f"remaining={max(0, remaining)}")
    return {"ok": True, "pushed": pushed,
            "skipped_already": len(already & {j['id'] for j in jes}),
            "remaining": max(0, remaining)}
