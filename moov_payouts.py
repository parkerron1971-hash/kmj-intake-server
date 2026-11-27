"""moov_payouts.py — a church pays its 1099 people through Moov, from the
church's OWN bank (test mode only in this build).

Kevin, 2026-11-27 (Money desk, M-6 step 3): guest speakers, musicians,
contractors and reimbursements, sent by the church, so the church is the
payer and Solutionist never is. Available "if people like it": off unless
MOOV_PAYOUTS opens it (off | owner | on) AND the church's owner opts in.

    WHO ............ seeing the payouts: church_money_gate ("see", "send"),
                     the owner, an Admin, the accountant. Sending: ("work",
                     "send"), the owner or an Admin, plus a password step-up
                     (ledger_unlock.SCOPE_PAY) for this church. The church's
                     own Moov account, its opt-in and its caps: ("work",
                     "setup"), the owner alone
    THE CHURCH ..... its own Moov business account, made by Moov's hosted form
                     (KYB, and the church links its bank there; micro-deposits
                     are free). Kept: Moov's account id, the invite code, a
                     status, whether a bank is ready. Never a bank number
    A PAYEE ........ a contractor row, invited to Moov's hosted form to add
                     their bank or debit card. Their W-9 stays the app's own
                     (contractors_router tax-profile, Reports > 1099s): Moov's
                     form checks who they are, and this build reads no TIN
                     back from Moov
    A PAYOUT ....... from a bill or from "Pay people". Next-day ACH by default;
                     same-day and instant can be chosen, with Moov's fee
                     shown first (moov_client.fee_for). The bill exists from
                     the moment it is sent (made here, or the one picked,
                     marked 'scheduled'), and is marked PAID only when Moov
                     says completed: paid_via 'moov', is_1099_eligible from the
                     contractor, contractor linked. So the books and the 1099
                     summary count it once (reports_router._summary_1099 reads
                     paid 1099 bills). A failure before it lands puts the bill
                     back (cancelled if made here, else as it was); a return
                     after it landed reopens it the same way
    ONCE ........... the client sends an idempotency key; it is unique on the
                     payout row and is Moov's X-Idempotency-Key, so a retry
                     never pays twice. A bill can have one payout in flight or
                     paid (a unique index). An answer we couldn't read leaves
                     the payout 'created' and the same request may be sent
                     again safely
    NEVER FROM US .. the source is a payment method of the church's own Moov
                     account, checked here (the church row for this business)
                     and again in moov_client.create_transfer (Moov's own list
                     of that account's methods; never the partner account)
    CAPS ........... per payment and per day, set by the owner up to the
                     platform's ceilings (MOOV_MAX_PAYMENT_USD,
                     MOOV_MAX_DAILY_USD)
    WEBHOOK ........ /moov/webhook. Moov signs only timestamp|nonce|webhook-id,
                     not the body, so a verified delivery is a "go and look":
                     every status is read back from Moov's API before anything
                     changes. Fails closed (webhook_guard)
    AUDIT .......... every opt-in, invite, cap change, send and status change
                     is an audit_log row; no keys, no bank numbers

Migration: supabase/APPLY-2026-11-27-moov-payouts.sql. Contract and the
go-live steps: docs/MOOV_PAYOUTS.md.
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel

import church_money_gate
import moov_client
import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("moov_payouts")

router = APIRouter(prefix="/moov", tags=["moov"])

_BUCKETS = ("tax", "owner_pay", "operating", "savings", "other")
OPEN_BILL = ("draft", "pending", "scheduled", "overdue")
LIVE = ("created", "queued", "pending", "completed")
MOOV_STATUSES = ("created", "queued", "pending", "completed", "failed", "reversed", "canceled")

NOT_ON = "Sending with Moov isn't switched on for this church."
CHURCH_ONLY = "Sending with Moov is for churches."
NOT_OPTED_IN = "The church hasn't turned on sending with Moov. The owner turns it on in Pay people."
CHURCH_NOT_READY = "The church's Moov account isn't ready to send yet. The owner finishes Moov's form and links the bank."
PAYEE_NOT_READY = "{name} hasn't finished adding a bank or card with Moov yet."
SPEED_NOT_AVAILABLE = "{speed} isn't available for {name}. Next-day bank transfer is."
OVER_PAYMENT_CAP = "That's over the church's limit of ${cap:,.2f} for one payment."
OVER_DAILY_CAP = "That would pass the church's limit of ${cap:,.2f} a day (${sent:,.2f} sent today)."
READ_503 = "Payouts couldn't be read just now. Nothing was sent."
SAVE_503 = "That didn't save. Nothing was sent."
SENT_UNSURE = ("Moov didn't confirm in time. Nothing is lost: press Send again and it won't pay twice, or check "
               "the payout in a minute.")
REFUSED = "Moov didn't accept that payment. Nothing was sent, and the bill is as it was."

SPEED_WORDS = {"next_day": "Next-day bank transfer", "same_day": "Same-day bank transfer",
               "instant": "Instant"}
STATUS_WORDS = {
    "created": "Getting ready",
    "queued": "Waiting its turn at Moov",
    "pending": "On its way",
    "completed": "Paid",
    "failed": "Didn't go through. Nothing was taken from the church's bank.",
    "canceled": "Canceled. Nothing was sent.",
    "reversed": "Sent back by the bank. The bill is open again.",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _q(v: Any) -> str:
    return quote(str(v), safe="")


_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _uuid(v: Any, what: str = "id") -> str:
    s = str(v or "").strip()
    if not _UUID.match(s):
        raise HTTPException(400, f"{what} isn't valid")
    return s


def _one(res: Any) -> Optional[Dict[str, Any]]:
    if isinstance(res, list):
        return res[0] if res else None
    return res if isinstance(res, dict) else None


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


CAP_DEFAULTS = {"per_payment_cap": 1000.0, "daily_cap": 2500.0}


def _cap(row: Optional[Dict[str, Any]], name: str) -> float:
    """The church's own limit, or the default when none is saved yet."""
    v = _num((row or {}).get(name))
    return v if v > 0 else CAP_DEFAULTS[name]


# ─── The switch ───────────────────────────────────────────────────────

def switch_mode() -> str:
    m = (os.environ.get("MOOV_PAYOUTS") or "off").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def open_for(business_id: Any) -> bool:
    """MOOV_PAYOUTS: off (nobody), owner (the platform owner's churches), on
    (every church that opts in). A check that fails is a no."""
    m = switch_mode()
    if m == "on":
        return bool(business_id)
    if m == "owner":
        try:
            import member_asks
            return bool(member_asks.platform_church(business_id))
        except Exception:  # noqa: BLE001 — couldn't tell: closed
            return False
    return False


def platform_caps() -> Dict[str, float]:
    def _f(name: str, default: float) -> float:
        v = _num(os.environ.get(name) or default)
        return v if v > 0 else default
    return {"per_payment": _f("MOOV_MAX_PAYMENT_USD", 5000.0), "daily": _f("MOOV_MAX_DAILY_USD", 10000.0)}


# ─── Who, and which church ────────────────────────────────────────────

def _business(biz: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{_q(biz)}&select=id,name,type,owner_id&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, READ_503)
    if not rows:
        raise HTTPException(404, "business not found")
    return rows[0]


def _church(biz: Any, user: AuthedUser, need: str, part: str = "send") -> Dict[str, Any]:
    """The church row, after the one money gate for this person. A shop, or a
    church the switch doesn't open, is refused before anything else is read."""
    biz = _uuid(biz, "business_id")
    row = _business(biz)
    church_money_gate.require_money(biz, user, need, part, business=row)
    import church_follow_up
    if not church_follow_up.is_church(row):
        raise HTTPException(403, CHURCH_ONLY)
    if not open_for(biz):
        raise HTTPException(404, NOT_ON)
    return row


def _church_account(biz: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/moov_accounts?business_id=eq.{_q(biz)}&kind=eq.church&mode=eq.{moov_client.mode()}&select=*&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, READ_503)
    return rows[0] if rows else None


def _payee_account(contractor_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/moov_accounts?contractor_id=eq.{_q(contractor_id)}&kind=eq.payee"
        f"&mode=eq.{moov_client.mode()}&select=*&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, READ_503)
    return rows[0] if rows else None


def _contractor(biz: str, contractor_id: Any) -> Dict[str, Any]:
    cid = _uuid(contractor_id, "contractor_id")
    rows = sb_clients.sb_get_as_service(
        f"/contractors?id=eq.{_q(cid)}&business_id=eq.{_q(biz)}&select=*&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, READ_503)
    if not rows:
        raise HTTPException(404, "That person isn't on this church's list.")
    return rows[0]


def _audit(biz: str, user_id: Optional[str], verb: str, summary: str, *, ok: bool = True,
           target_id: Optional[str] = None, payload: Optional[Dict[str, Any]] = None,
           actor_type: str = "user") -> None:
    try:
        import audit_log
        audit_log.record(biz, actor_type=actor_type, actor_id=user_id or "moov", verb=verb, ok=ok,
                         summary=summary, target_type="moov_payout" if verb.startswith("moov_payout") else
                         "moov_account", target_id=target_id, payload=payload or {},
                         source="moov_payouts", authorized_by="church_money_gate.send")
    except Exception:  # noqa: BLE001 — the audit never blocks the money path
        logger.warning("[moov] audit %s not written", verb)


def _moov_error_words(e: moov_client.MoovError) -> str:
    return f"Moov said no ({e.status})."


# ─── Views ────────────────────────────────────────────────────────────

def _account_view(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    row = row or {}
    return {
        "opted_in": bool(row.get("opted_in")),
        "status": row.get("status") or "off",
        "bank_ready": bool(row.get("bank_ready")),
        "has_moov_account": bool(row.get("moov_account_id")),
        "per_payment_cap": _cap(row, "per_payment_cap"),
        "daily_cap": _cap(row, "daily_cap"),
    }


def _payout_view(p: Dict[str, Any]) -> Dict[str, Any]:
    status = p.get("status") or "created"
    return {
        "id": p.get("id"), "contractor_id": p.get("contractor_id"), "bill_id": p.get("bill_id"),
        "amount": _num(p.get("amount")), "speed": p.get("speed"),
        "speed_words": SPEED_WORDS.get(p.get("speed") or "", ""),
        "fee_estimate": _num(p.get("fee_estimate")), "status": status,
        "status_words": STATUS_WORDS.get(status, status), "return_code": p.get("return_code"),
        "failure_reason": p.get("failure_reason"), "needs_review": bool(p.get("needs_review")),
        "description": p.get("description"), "mode": p.get("mode"),
        "created_at": p.get("created_at"), "completed_at": p.get("completed_at"),
    }


def _speeds(amount: float) -> List[Dict[str, Any]]:
    return [{"speed": s, "words": SPEED_WORDS[s], "fee": moov_client.fee_for(s, amount),
             "default": s == moov_client.DEFAULT_SPEED} for s in moov_client.SPEEDS]


# ─── The Contractors page's slot ──────────────────────────────────────

def shows_for(biz: Any, user: Any) -> bool:
    """`payouts.moov` on GET /contractors (W5's ContractorSendSlot, FE #1719):
    whether this church's Contractors page should draw the Moov part at all.
    The switch opens it for this church and the person may see payouts. Never
    raises: a read that fails is a no. The slot then reads /moov/status."""
    try:
        if not open_for(biz):
            return False
        row = _business(_uuid(biz, "biz"))
        import church_follow_up
        return bool(church_follow_up.is_church(row)
                    and church_money_gate.may_money(row["id"], user, "see", "send", business=row))
    except Exception:  # noqa: BLE001 — unread is not a yes
        return False


# ─── Status ───────────────────────────────────────────────────────────

@router.get("/status")
def status(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """What Pay people needs to draw the Moov part. `switched_on` false: draw
    nothing. Readable by whoever may see payouts."""
    biz = _uuid(biz, "biz")
    row = _business(biz)
    church_money_gate.require_money(biz, user, "see", "send", business=row)
    import church_follow_up
    if not church_follow_up.is_church(row) or not open_for(biz):
        return {"ok": True, "switched_on": False}
    acct = _church_account(biz)
    return {
        "ok": True, "switched_on": True, "mode": moov_client.mode(),
        "ready": moov_client.configured(), "reason": moov_client.why_not(),
        "church": _account_view(acct), "platform_caps": platform_caps(),
        "speeds": _speeds(100.0),
        "may_send": church_money_gate.may_money(biz, user, "work", "send", business=row),
        "may_set_up": church_money_gate.may_money(biz, user, "work", "setup", business=row),
    }


# ─── The church's own account ─────────────────────────────────────────

class OptInBody(BaseModel):
    business_id: str
    on: bool


@router.post("/church/opt-in")
def church_opt_in(body: OptInBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """The owner turns sending with Moov on or off for the church. Off stops
    new payouts; ones already sent finish."""
    row = _church(body.business_id, user, "work", "setup")
    biz = str(row["id"])
    acct = _church_account(biz)
    patch = {"opted_in": bool(body.on), "opted_in_by": str(user.id), "opted_in_at": _now_iso(),
             "updated_at": _now_iso()}
    if acct:
        ok = sb_clients.sb_patch_as_service(f"/moov_accounts?id=eq.{_q(acct['id'])}", patch)
    else:
        ok = sb_clients.sb_post_as_service("/moov_accounts", {
            "business_id": biz, "kind": "church", "mode": moov_client.mode(), "status": "off", **patch})
    if ok is None:
        raise HTTPException(503, SAVE_503)
    _audit(biz, str(user.id), "moov_church_opt_in" if body.on else "moov_church_opt_out",
           "Turned on sending with Moov" if body.on else "Turned off sending with Moov")
    return {"ok": True, "church": _account_view(_church_account(biz))}


class BizBody(BaseModel):
    business_id: str


def _return_url(tag: str) -> str:
    from app_base import app_base_url
    return f"{app_base_url()}?moov_onboarding={tag}"


@router.post("/church/onboarding")
def church_onboarding(body: BizBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """A link to Moov's own form, where the church proves who it is (KYB) and
    links its bank. The owner opens it; nothing about the bank comes back here
    but Moov's ids."""
    row = _church(body.business_id, user, "work", "setup")
    biz = str(row["id"])
    acct = _church_account(biz)
    if not acct or not acct.get("opted_in"):
        raise HTTPException(409, NOT_OPTED_IN)
    if acct.get("moov_account_id") and acct.get("status") == "active":
        return {"ok": True, "already": True, "church": _account_view(acct)}
    try:
        invite = moov_client.create_onboarding_invite(
            account_type="business", foreign_id=biz, capabilities=moov_client.church_capabilities(),
            prefill_profile={"business": {"legalBusinessName": (row.get("name") or "Church")[:64]}},
            return_url=_return_url("church"))
    except moov_client.MoovError as e:
        raise HTTPException(502, _moov_error_words(e))
    code = str(invite.get("code") or "")
    if not code or not invite.get("link"):
        raise HTTPException(502, moov_client.MOOV_502)
    if sb_clients.sb_patch_as_service(f"/moov_accounts?id=eq.{_q(acct['id'])}", {
            "invite_code": code, "status": "invited" if not acct.get("moov_account_id") else acct.get("status"),
            "updated_at": _now_iso()}) is None:
        raise HTTPException(503, SAVE_503)
    _audit(biz, str(user.id), "moov_church_invite", "Opened Moov's form for the church's account")
    return {"ok": True, "link": invite["link"]}


def _account_status(account: Dict[str, Any], wanted: List[str]) -> str:
    caps = moov_client.capabilities_of(account)
    need = [c for c in wanted if c != "transfers"] or ["transfers"]
    states = [caps.get(c, "") for c in need]
    if states and all(s == "enabled" for s in states):
        return "active"
    if any(s == "disabled" for s in states):
        return "restricted"
    return "pending"


def _refresh_account(acct: Dict[str, Any], wanted: List[str], bank_types: tuple) -> Dict[str, Any]:
    """Read the account back from Moov: its id (from the redeemed invite), its
    capabilities and whether a usable payment method is there."""
    patch: Dict[str, Any] = {"updated_at": _now_iso()}
    moov_id = acct.get("moov_account_id")
    if not moov_id and acct.get("invite_code"):
        invite = moov_client.get_onboarding_invite(acct["invite_code"])
        moov_id = invite.get("redeemedAccountID") or None
        if moov_id:
            if moov_id == moov_client.partner_account_id():
                raise HTTPException(409, "That Moov account can't be used here.")
            patch["moov_account_id"] = moov_id
    if moov_id:
        account = moov_client.get_account(moov_id)
        patch["status"] = _account_status(account, wanted)
        methods = moov_client.list_payment_methods(moov_id)
        patch["bank_ready"] = any(m.get("paymentMethodType") in bank_types for m in methods)
    if sb_clients.sb_patch_as_service(f"/moov_accounts?id=eq.{_q(acct['id'])}", patch) is None:
        # The unique index refuses a Moov account that another row holds.
        raise HTTPException(409 if patch.get("moov_account_id") else 503,
                            "That Moov account is already linked elsewhere." if patch.get("moov_account_id")
                            else SAVE_503)
    return {**acct, **patch}


PAYEE_TYPES = tuple(t for ts in moov_client.DEST_TYPES.values() for t in ts)


@router.post("/church/refresh")
def church_refresh(body: BizBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    row = _church(body.business_id, user, "see")
    acct = _church_account(str(row["id"]))
    if not acct:
        return {"ok": True, "church": _account_view(None)}
    try:
        acct = _refresh_account(acct, moov_client.church_capabilities(), ("ach-debit-fund",))
    except moov_client.MoovError as e:
        raise HTTPException(502, _moov_error_words(e))
    return {"ok": True, "church": _account_view(acct)}


class CapsBody(BaseModel):
    business_id: str
    per_payment_cap: float
    daily_cap: float


@router.patch("/church/caps")
def church_caps(body: CapsBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """The owner's own limits, never above the platform's ceilings."""
    row = _church(body.business_id, user, "work", "setup")
    biz = str(row["id"])
    top = platform_caps()
    if not (0 < body.per_payment_cap <= top["per_payment"]) or not (0 < body.daily_cap <= top["daily"]):
        raise HTTPException(400, f"Limits go up to ${top['per_payment']:,.0f} a payment and "
                                 f"${top['daily']:,.0f} a day.")
    if body.per_payment_cap > body.daily_cap:
        raise HTTPException(400, "One payment can't be more than the day's limit.")
    acct = _church_account(biz)
    if not acct:
        raise HTTPException(409, NOT_OPTED_IN)
    if sb_clients.sb_patch_as_service(f"/moov_accounts?id=eq.{_q(acct['id'])}", {
            "per_payment_cap": round(body.per_payment_cap, 2), "daily_cap": round(body.daily_cap, 2),
            "updated_at": _now_iso()}) is None:
        raise HTTPException(503, SAVE_503)
    _audit(biz, str(user.id), "moov_church_caps",
           f"Set Moov limits: ${body.per_payment_cap:,.2f} a payment, ${body.daily_cap:,.2f} a day")
    return {"ok": True, "church": _account_view(_church_account(biz))}


# ─── Payees ───────────────────────────────────────────────────────────

def _split_name(name: str) -> Dict[str, str]:
    parts = (name or "").strip().split()
    if not parts:
        return {"firstName": "Payee", "lastName": "Payee"}
    return {"firstName": parts[0][:64], "lastName": (" ".join(parts[1:]) or parts[0])[:64]}


@router.post("/payees/{contractor_id}/invite")
async def payee_invite(contractor_id: str, body: BizBody,
                       user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """A link to Moov's own form for this person to add their bank or debit
    card. Emailed when the person has an email; always returned to share."""
    row = _church(body.business_id, user, "work")
    biz = str(row["id"])
    church = _church_account(biz)
    if not church or not church.get("opted_in"):
        raise HTTPException(409, NOT_OPTED_IN)
    c = _contractor(biz, contractor_id)
    payee = _payee_account(str(c["id"]))
    if payee and payee.get("status") == "active" and payee.get("bank_ready"):
        return {"ok": True, "already": True, "payee": _account_view(payee)}
    profile: Dict[str, Any] = {"individual": {"name": _split_name(c.get("name") or "")}}
    if c.get("email"):
        profile["individual"]["email"] = c["email"]
    try:
        invite = moov_client.create_onboarding_invite(
            account_type="individual", foreign_id=str(c["id"]), capabilities=moov_client.payee_capabilities(),
            prefill_profile=profile, return_url=_return_url("payee"))
    except moov_client.MoovError as e:
        raise HTTPException(502, _moov_error_words(e))
    code, link = str(invite.get("code") or ""), invite.get("link")
    if not code or not link:
        raise HTTPException(502, moov_client.MOOV_502)
    if payee:
        saved = sb_clients.sb_patch_as_service(f"/moov_accounts?id=eq.{_q(payee['id'])}", {
            "invite_code": code, "updated_at": _now_iso(),
            "status": payee.get("status") if payee.get("moov_account_id") else "invited"})
    else:
        saved = sb_clients.sb_post_as_service("/moov_accounts", {
            "business_id": biz, "kind": "payee", "contractor_id": str(c["id"]), "mode": moov_client.mode(),
            "invite_code": code, "status": "invited"})
    if saved is None:
        raise HTTPException(503, SAVE_503)
    email_sent = False
    if c.get("email"):
        church_name = row.get("name") or "Your church"
        try:
            from email_sender import send_via_resend
            await send_via_resend(
                to_email=c["email"], to_name=c.get("name"),
                from_email="payments@mysolutionist.app", from_name=church_name[:60], reply_to=None,
                subject=f"{church_name} would like to pay you",
                body=(f"{church_name} sends payments through Moov, a payments company.\n\n"
                      f"Add the bank account or debit card you'd like to be paid to here:\n{link}\n\n"
                      f"It takes a few minutes. The money comes from {church_name}'s own bank."))
            email_sent = True
        except Exception:  # noqa: BLE001 — the link is still returned
            logger.warning("[moov] payee invite email not sent")
    _audit(biz, str(user.id), "moov_payee_invite", f"Invited {c.get('name') or 'a payee'} to Moov",
           target_id=str(c["id"]))
    return {"ok": True, "link": link, "email_sent": email_sent, "w9_on_file": bool(c.get("tin_encrypted")),
            "w9_words": ("Moov's form checks who they are. Keep their W-9 here too, in Reports > 1099s, "
                         "so the church's 1099 is ready.")}


@router.post("/payees/{contractor_id}/refresh")
def payee_refresh(contractor_id: str, body: BizBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    row = _church(body.business_id, user, "see")
    c = _contractor(str(row["id"]), contractor_id)
    payee = _payee_account(str(c["id"]))
    if not payee:
        return {"ok": True, "payee": _account_view(None)}
    try:
        payee = _refresh_account(payee, moov_client.payee_capabilities(), PAYEE_TYPES)
    except moov_client.MoovError as e:
        raise HTTPException(502, _moov_error_words(e))
    return {"ok": True, "payee": _account_view(payee)}


# ─── Quote ────────────────────────────────────────────────────────────

class QuoteBody(BaseModel):
    business_id: str
    contractor_id: str
    amount: float


def _cents(amount: float) -> int:
    cents = round(float(amount) * 100)
    if cents <= 0 or abs(float(amount) * 100 - cents) > 1e-6:
        raise HTTPException(400, "Enter an amount in dollars and cents, more than zero.")
    return int(cents)


def _sent_today(biz: str) -> float:
    day = datetime.now(timezone.utc).date().isoformat()
    try:
        rows = sb_clients.sb_get_all_as_service(
            f"/moov_payouts?business_id=eq.{_q(biz)}&created_at=gte.{day}"
            f"&status=in.(created,queued,pending,completed)&select=id,amount", strict=True)
    except Exception:  # noqa: BLE001 — a short read must never read as zero
        raise HTTPException(503, READ_503)
    if not isinstance(rows, list):
        raise HTTPException(503, READ_503)
    return round(sum(_num(r.get("amount")) for r in rows), 2)


def _routes(church: Dict[str, Any], payee: Dict[str, Any], amount_cents: int) -> Dict[str, Any]:
    """Moov's own options for this pair: the church's bank-debit method, and
    the payee's methods by speed."""
    opts = moov_client.transfer_options(source_account_id=church["moov_account_id"],
                                        destination_account_id=payee["moov_account_id"],
                                        amount_cents=amount_cents)
    source = next((o for o in (opts.get("sourceOptions") or [])
                   if o.get("paymentMethodType") == "ach-debit-fund"), None)
    dests = {o.get("paymentMethodType"): o for o in (opts.get("destinationOptions") or [])}
    by_speed: Dict[str, Optional[str]] = {}
    for speed, types in moov_client.DEST_TYPES.items():
        hit = next((dests[t] for t in types if t in dests), None)
        by_speed[speed] = str(hit["paymentMethodID"]) if hit and hit.get("paymentMethodID") else None
    return {"source": str(source["paymentMethodID"]) if source and source.get("paymentMethodID") else None,
            "by_speed": by_speed}


def _ready_pair(biz: str, c: Dict[str, Any]) -> tuple:
    church = _church_account(biz)
    if not church or not church.get("opted_in"):
        raise HTTPException(409, NOT_OPTED_IN)
    if church.get("status") != "active" or not church.get("bank_ready") or not church.get("moov_account_id"):
        raise HTTPException(409, CHURCH_NOT_READY)
    payee = _payee_account(str(c["id"]))
    if not payee or payee.get("status") != "active" or not payee.get("moov_account_id"):
        raise HTTPException(409, PAYEE_NOT_READY.format(name=c.get("name") or "This person"))
    if payee["moov_account_id"] in (church["moov_account_id"], moov_client.partner_account_id()):
        raise HTTPException(409, "That payee's Moov account can't be used here.")
    return church, payee


@router.post("/quote")
def quote_payout(body: QuoteBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """What sending this would cost at each speed, and which speeds Moov offers
    for this person. Sends nothing."""
    row = _church(body.business_id, user, "see")
    biz = str(row["id"])
    cents = _cents(body.amount)
    c = _contractor(biz, body.contractor_id)
    church, payee = _ready_pair(biz, c)
    try:
        routes = _routes(church, payee, cents)
    except moov_client.MoovError as e:
        raise HTTPException(502, _moov_error_words(e))
    amount = cents / 100
    return {"ok": True, "amount": amount, "sent_today": _sent_today(biz),
            "per_payment_cap": _cap(church, "per_payment_cap"), "daily_cap": _cap(church, "daily_cap"),
            "church_bank_ok": bool(routes["source"]),
            "speeds": [{**s, "available": bool(routes["source"] and routes["by_speed"].get(s["speed"]))}
                       for s in _speeds(amount)]}


# ─── Pay ──────────────────────────────────────────────────────────────

class PayBody(BaseModel):
    business_id: str
    contractor_id: str
    amount: float
    idempotency_key: str
    speed: str = moov_client.DEFAULT_SPEED
    bill_id: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None


def _payout_by_key(key: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(f"/moov_payouts?idempotency_key=eq.{_q(key)}&select=*&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, READ_503)
    return rows[0] if rows else None


def _payout(payout_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(f"/moov_payouts?id=eq.{_q(payout_id)}&select=*&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, READ_503)
    return rows[0] if rows else None


def _bill(biz: str, bill_id: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/bills?id=eq.{_q(_uuid(bill_id, 'bill_id'))}&business_id=eq.{_q(biz)}&select=*&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, READ_503)
    if not rows:
        raise HTTPException(404, "bill not found")
    return rows[0]


def _send(p: Dict[str, Any], c: Dict[str, Any], church: Dict[str, Any], row: Dict[str, Any]) -> Dict[str, Any]:
    """Ask Moov to move it, with the payout's own key. Returns the payout as
    saved after Moov's answer."""
    try:
        transfer = moov_client.create_transfer(
            source_account_id=church["moov_account_id"],
            source_payment_method_id=p["source_payment_method_id"],
            destination_payment_method_id=p["destination_payment_method_id"],
            amount_cents=int(round(_num(p["amount"]) * 100)), idempotency_key=p["idempotency_key"],
            description=(p.get("description") or f"{row.get('name') or 'Church'} payment to {c.get('name')}"),
            metadata={"business_id": str(p["business_id"]), "payout_id": str(p["id"]),
                      "contractor_id": str(c["id"])},
            foreign_id=str(p["id"]))
    except moov_client.MoovError as e:
        if e.status == 409 and isinstance(e.body, dict) and e.body.get("transferID"):
            transfer = e.body        # the key was used already: that is our transfer
        elif e.status in (429,) or e.status >= 500:
            return {**p, "_unsure": True}
        else:
            _audit(str(p["business_id"]), None, "moov_payout_refused", f"Moov refused a payout ({e.status})",
                   ok=False, target_id=str(p["id"]), actor_type="system")
            return _apply(p, {"status": "failed", "failureReason": f"refused-{e.status}"}, refused=True)
    except HTTPException as e:
        if e.status_code == 403:
            # Not the church's own account: refused before Moov was asked.
            _apply(p, {"status": "failed", "failureReason": "not-the-churchs-account"}, refused=True)
            raise
        return {**p, "_unsure": True}        # no answer we could read: Moov may have it
    tid = transfer.get("transferID")
    if not tid:
        return {**p, "_unsure": True}
    if sb_clients.sb_patch_as_service(f"/moov_payouts?id=eq.{_q(p['id'])}",
                                      {"moov_transfer_id": tid, "updated_at": _now_iso()}) is None:
        logger.error("[moov] payout %s sent as %s but the id didn't save", str(p["id"])[:8], tid)
    p = {**p, "moov_transfer_id": tid}
    if transfer.get("status") in MOOV_STATUSES:
        return _apply(p, transfer)
    return p


@router.post("/pay")
def pay(body: PayBody, request: Request, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Send one payout from the church's bank to this person. Owner or Admin,
    with a fresh password confirmation for this church."""
    row = _church(body.business_id, user, "work")
    biz = str(row["id"])
    from financial_policy import require_operational_write
    require_operational_write(biz)
    import ledger_unlock
    ledger_unlock.require_unlock(request, str(user.id), scope=ledger_unlock.SCOPE_PAY, business_id=biz)
    import billing_limits
    billing_limits.require_feature(biz, "contractor_payments")
    reason = moov_client.why_not()
    if reason:
        raise HTTPException(503, reason)

    key = (body.idempotency_key or "").strip()
    if not (8 <= len(key) <= 128) or not re.match(r"^[A-Za-z0-9_-]+$", key):
        raise HTTPException(400, "idempotency_key must be 8 to 128 letters, digits, - or _.")
    if body.speed not in moov_client.SPEEDS:
        raise HTTPException(400, f"speed must be one of {moov_client.SPEEDS}")
    cents = _cents(body.amount)
    amount = cents / 100
    c = _contractor(biz, body.contractor_id)

    # The same request again: never a second payment. Resend only when Moov
    # never gave us a transfer id (the key makes that safe).
    seen = _payout_by_key(key)
    if seen:
        if str(seen.get("business_id")) != biz:
            raise HTTPException(409, "That request id was used for another church.")
        if seen.get("status") == "created" and not seen.get("moov_transfer_id"):
            church = _church_account(biz) or {}
            if not church.get("opted_in") or church.get("moov_account_id") != seen.get("source_account_id"):
                raise HTTPException(409, CHURCH_NOT_READY)
            seen = _send(seen, c, church, row)
        return _pay_answer(seen)

    church, payee = _ready_pair(biz, c)
    if amount > _cap(church, "per_payment_cap"):
        raise HTTPException(409, OVER_PAYMENT_CAP.format(cap=_cap(church, "per_payment_cap")))
    top = platform_caps()
    if amount > top["per_payment"]:
        raise HTTPException(409, OVER_PAYMENT_CAP.format(cap=top["per_payment"]))
    sent = _sent_today(biz)
    daily = min(_cap(church, "daily_cap"), top["daily"])
    if sent + amount > daily:
        raise HTTPException(409, OVER_DAILY_CAP.format(cap=daily, sent=sent))

    bill = None
    if body.bill_id:
        bill = _bill(biz, body.bill_id)
        if bill.get("status") not in OPEN_BILL:
            raise HTTPException(409, "That bill isn't waiting to be paid.")
        if round(_num(bill.get("amount")) * 100) != cents:
            raise HTTPException(409, "The amount must match the bill.")
        if bill.get("contractor_id") and str(bill["contractor_id"]) != str(c["id"]):
            raise HTTPException(409, "That bill is for someone else.")
    category = body.category or (bill or {}).get("category") or c.get("default_category") or "operating"
    if category not in _BUCKETS:
        raise HTTPException(400, f"category must be one of {_BUCKETS}")

    try:
        routes = _routes(church, payee, cents)
    except moov_client.MoovError as e:
        raise HTTPException(502, _moov_error_words(e))
    if not routes["source"]:
        raise HTTPException(409, CHURCH_NOT_READY)
    dest = routes["by_speed"].get(body.speed)
    if not dest:
        raise HTTPException(409, SPEED_NOT_AVAILABLE.format(speed=SPEED_WORDS[body.speed],
                                                           name=c.get("name") or "this person"))

    description = (body.description or "").strip()[:200] or None
    today = datetime.now(timezone.utc).date().isoformat()
    if not bill:
        import period_lock
        period_lock.guard(biz, today, source_type="bill", source_id=key, reason=None, override_by=str(user.id))
    p = _one(sb_clients.sb_post_as_service("/moov_payouts", {
        "business_id": biz, "contractor_id": str(c["id"]), "mode": moov_client.mode(),
        "amount": amount, "speed": body.speed, "fee_estimate": moov_client.fee_for(body.speed, amount),
        "description": description, "status": "created", "idempotency_key": key,
        "source_account_id": church["moov_account_id"], "source_payment_method_id": routes["source"],
        "destination_account_id": payee["moov_account_id"], "destination_payment_method_id": dest,
        "approved_by": str(user.id), "created_at": _now_iso(),
        "bill_id": str(bill["id"]) if bill else None, "bill_was_status": (bill or {}).get("status"),
    }, redact=True))
    if not p:
        again = _payout_by_key(key)         # two presses at once: the other one won
        if again and str(again.get("business_id")) == biz:
            return _pay_answer(again)
        raise HTTPException(409 if bill else 503,
                            "That bill already has a payment on its way." if bill else SAVE_503)

    # The bill: the one picked is marked on its way; otherwise one is made.
    if bill:
        sb_clients.sb_patch_as_service(f"/bills?id=eq.{_q(bill['id'])}&business_id=eq.{_q(biz)}", {
            "status": "scheduled", "contractor_id": str(c["id"]), "updated_at": _now_iso()})
    else:
        made = _one(sb_clients.sb_post_as_service("/bills", {
            "business_id": biz, "vendor_name": c.get("name") or "Payee",
            "description": description or "Sent with Moov",
            "amount": amount, "category": category, "subcategory": "contractor", "status": "scheduled",
            "due_date": today, "is_1099_eligible": bool(c.get("is_1099_eligible", True)),
            "contractor_id": str(c["id"]), "recurrence_index": 0, "notes": "Sent with Moov",
        }))
        if not made:
            sb_clients.sb_patch_as_service(f"/moov_payouts?id=eq.{_q(p['id'])}",
                                           {"status": "canceled", "failure_reason": "bill_not_saved",
                                            "updated_at": _now_iso()})
            raise HTTPException(503, SAVE_503)
        sb_clients.sb_patch_as_service(f"/moov_payouts?id=eq.{_q(p['id'])}",
                                       {"bill_id": made["id"], "bill_made_here": True})
        p = {**p, "bill_id": made["id"], "bill_made_here": True}

    _audit(biz, str(user.id), "moov_payout_sent",
           f"Sent ${amount:,.2f} to {c.get('name') or 'a payee'} with Moov ({SPEED_WORDS[body.speed]})",
           target_id=str(p["id"]), payload={"amount": amount, "speed": body.speed, "mode": moov_client.mode()})
    return _pay_answer(_send(p, c, church, row))


def _pay_answer(p: Dict[str, Any]) -> Dict[str, Any]:
    out = {"ok": True, "payout": _payout_view(p)}
    if p.get("_unsure"):
        out["note"] = SENT_UNSURE
    if p.get("status") == "failed":
        out["ok"] = False
        out["note"] = REFUSED
    return out


# ─── Applying Moov's answer ───────────────────────────────────────────

def _return_code(t: Dict[str, Any]) -> Optional[str]:
    for leg in ("source", "destination"):
        ach = ((t.get(leg) or {}).get("achDetails") or {})
        code = (ach.get("return") or {}).get("code")
        if code:
            return str(code)[:10]
    return None


def _reopen_bill(p: Dict[str, Any], was_paid: bool) -> bool:
    """Put the bill back: cancelled if this payout made it, else as it was.
    A paid bill in a closed month is left as it is and the payout marked for a
    person to look at. Returns False when it was left."""
    if not p.get("bill_id"):
        return True
    biz = str(p["business_id"])
    if was_paid:
        import period_lock
        bill = _one(sb_clients.sb_get_as_service(f"/bills?id=eq.{_q(p['bill_id'])}&select=paid_at&limit=1")) or {}
        day = str(bill.get("paid_at") or "")[:10]
        if day and period_lock.locked_period(biz, day):
            return False
    patch: Dict[str, Any] = {"paid_at": None, "paid_amount": None, "paid_via": None, "updated_at": _now_iso()}
    patch["status"] = "cancelled" if p.get("bill_made_here") else (
        p.get("bill_was_status") if p.get("bill_was_status") in OPEN_BILL else "pending")
    sb_clients.sb_patch_as_service(f"/bills?id=eq.{_q(p['bill_id'])}&business_id=eq.{_q(biz)}", patch)
    return True


def _apply(p: Dict[str, Any], t: Dict[str, Any], *, refused: bool = False) -> Dict[str, Any]:
    """Make the payout and its bill say what Moov says. Safe to run any number
    of times: each change is conditional on the row not already being there."""
    new = str(t.get("status") or "")
    if new not in MOOV_STATUSES:
        return p                                  # a leg's sub-status: not ours to copy
    old = p.get("status")
    patch: Dict[str, Any] = {"status": new, "updated_at": _now_iso()}
    if t.get("failureReason"):
        patch["failure_reason"] = str(t["failureReason"])[:80]
    code = _return_code(t)
    if code:
        patch["return_code"] = code
    biz = str(p["business_id"])
    if new == "completed" and not p.get("bill_settled_at"):
        if p.get("bill_id"):
            c = _one(sb_clients.sb_get_as_service(
                f"/contractors?id=eq.{_q(p.get('contractor_id'))}&select=is_1099_eligible&limit=1")) or {}
            sb_clients.sb_patch_as_service(
                f"/bills?id=eq.{_q(p['bill_id'])}&business_id=eq.{_q(biz)}&status=neq.paid", {
                    "status": "paid", "paid_at": _now_iso(), "paid_amount": _num(p.get("amount")),
                    "paid_via": "moov", "contractor_id": p.get("contractor_id"),
                    "is_1099_eligible": bool(c.get("is_1099_eligible", True)), "updated_at": _now_iso()})
        patch["completed_at"] = _now_iso()
        patch["bill_settled_at"] = _now_iso()
    elif new in ("failed", "canceled", "reversed") and old != new:
        was_paid = bool(p.get("bill_settled_at"))
        if not _reopen_bill(p, was_paid):
            patch["needs_review"] = True
        patch["failed_at"] = _now_iso()
    if old == new and not refused and set(patch) <= {"status", "updated_at"}:
        return p
    sb_clients.sb_patch_as_service(f"/moov_payouts?id=eq.{_q(p['id'])}", patch)
    if old != new:
        _audit(biz, None, f"moov_payout_{new}", f"A Moov payout is now: {STATUS_WORDS.get(new, new)}",
               ok=new not in ("failed", "reversed"), target_id=str(p["id"]),
               payload={"return_code": code} if code else None, actor_type="system")
    return {**p, **patch}


def refresh_payout(p: Dict[str, Any]) -> Dict[str, Any]:
    """Read the transfer from Moov and apply it."""
    if not p.get("moov_transfer_id"):
        return p
    return _apply(p, moov_client.get_transfer(p["moov_transfer_id"]))


@router.get("/payouts")
def list_payouts(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    row = _church(biz, user, "see")
    rows = sb_clients.sb_get_as_service(
        f"/moov_payouts?business_id=eq.{_q(row['id'])}&order=created_at.desc&select=*&limit=200")
    if not isinstance(rows, list):
        raise HTTPException(503, READ_503)
    return {"ok": True, "payouts": [_payout_view(p) for p in rows]}


@router.post("/payouts/{payout_id}/refresh")
def refresh(payout_id: str, body: BizBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    row = _church(body.business_id, user, "work")
    p = _payout(_uuid(payout_id, "payout_id"))
    if not p or str(p.get("business_id")) != str(row["id"]):
        raise HTTPException(404, "payout not found")
    try:
        p = refresh_payout(p)
    except moov_client.MoovError as e:
        raise HTTPException(502, _moov_error_words(e))
    return {"ok": True, "payout": _payout_view(p)}


# ─── Webhook ──────────────────────────────────────────────────────────

def _handle_event(event: Dict[str, Any]) -> None:
    """Never trusts the body's statuses: it names what to look at, and Moov's
    API says what happened."""
    kind = str(event.get("type") or "")
    data = event.get("data") or {}
    try:
        if kind.startswith("transfer."):
            tid = str(data.get("transferID") or "")
            if not tid:
                return
            rows = sb_clients.sb_get_as_service(
                f"/moov_payouts?moov_transfer_id=eq.{_q(tid)}&select=*&limit=1") or []
            if rows:
                refresh_payout(rows[0])
        elif kind.split(".")[0] in ("account", "capability", "bankAccount", "paymentMethod"):
            aid = str(data.get("accountID") or "")
            if not aid:
                return
            for acct in sb_clients.sb_get_as_service(
                    f"/moov_accounts?moov_account_id=eq.{_q(aid)}&select=*&limit=5") or []:
                if acct.get("kind") == "church":
                    _refresh_account(acct, moov_client.church_capabilities(), ("ach-debit-fund",))
                else:
                    _refresh_account(acct, moov_client.payee_capabilities(), PAYEE_TYPES)
    except Exception as e:  # noqa: BLE001 — a refresh button and the next event catch up
        logger.warning("[moov] webhook %s not applied: %s", kind, type(e).__name__)


@router.post("/webhook")
async def webhook(request: Request, background: BackgroundTasks) -> Dict[str, Any]:
    import webhook_guard
    raw = await request.body()
    if not moov_client.webhook_secret():
        if not webhook_guard.unsigned_allowed("moov"):
            webhook_guard.reject_unsigned("moov", "MOOV_WEBHOOK_SECRET is not set")
            return {"ok": False}
    elif not moov_client.signature_ok(request.headers):
        raise HTTPException(400, "bad signature")
    try:
        event = json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(400, "bad body")
    if not isinstance(event, dict):
        raise HTTPException(400, "bad body")
    eid = str(event.get("eventID") or "")[:100]
    if eid:
        saved = sb_clients.sb_post_as_service("/moov_webhook_events?select=event_id",
                                              {"event_id": eid, "type": str(event.get("type") or "")[:60]})
        if not saved:
            seen = sb_clients.sb_get_as_service(f"/moov_webhook_events?event_id=eq.{_q(eid)}&select=event_id")
            if isinstance(seen, list) and seen:
                return {"ok": True, "duplicate": True}
    # Moov wants an answer within five seconds; the reads happen after it.
    background.add_task(_handle_event, event)
    return {"ok": True}
