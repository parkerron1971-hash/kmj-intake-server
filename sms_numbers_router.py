"""
sms_numbers_router.py — dedicated SMS numbers, phase C: provisioning.

A practitioner gets a number of their own. It is bought on the PLATFORM's
Twilio account (we are not a reseller; they rent a service that includes
a line), added to the one Messaging Service so it rides the existing 10DLC
campaign, and recorded in sms_numbers — which phase B already reads on
both sides: inbound routes by To, outbound sends from it.

The practitioner never hears "Twilio", "PN…", or "Messaging Service".
They hear "your number".

Endpoints (mounted in kmj_intake_automation.py):
  GET    /sms/numbers?business_id=…                 viewer  the live row + whether they can get one
  GET    /sms/numbers/available?business_id&area_code viewer  up to 10 choices, local + SMS-capable
  POST   /sms/numbers  {business_id, phone_number?, area_code?}
                                                    admin   buy → attach → active
  DELETE /sms/numbers/{number_id}?business_id=…     admin   active → releasing (grace window)
  POST   /sms/numbers/{number_id}/restore {business_id}
                                                    admin   releasing → active (inside the window)

The work itself lives in provision_core / release_core / restore_core,
callable IN-PROCESS — the endpoints wrap them with the access check, and
Chief's verbs (chief_sms_actions) call them directly, the same way
send_sms_core serves both /sms/send and Chief's send_sms. The plan gate
lives in the core, so Chief cannot route around it.

Lifecycle: provisioning → active → releasing → released. The row is
written FIRST (the partial unique index makes a double-provision race a
409, not two numbers), then the purchase, then the attach. A purchase
that fails deletes the row; an attach that fails releases the number
and marks the row released — never a paid, unattached line.

Refuses to run unless TWILIO_PLATFORM_NUMBER is set: the moment a second
number enters the pool, any unpinned send could go out from it, and the
platform number is what phase A pins the shared lane to.

Env:
  SMS_NUMBERS_CAMPAIGN_CAP        default 49 — a standard 10DLC campaign's
                                  number limit before Twilio wants a
                                  number-pool justification. Warns at 80%.
  SMS_NUMBER_RELEASE_GRACE_DAYS   default 14 — how long a released line
                                  stays recoverable before the sweep
                                  hands it back to Twilio.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from auth_supabase import require_user, AuthedUser
from sms_service import (
    _pq, _sb_get, _sb_post, _sb_patch, _sb_headers, _sb_url, _log_event,
    normalize_phone, _twilio_configured,
)
import twilio_sms

logger = logging.getLogger("sms_numbers")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] numbers: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

router = APIRouter(tags=["sms-numbers"])

FEATURE = "dedicated_sms_number"
LIVE_STATUSES = ("provisioning", "active", "suspended", "releasing")
ROW_FIELDS = ("id,business_id,phone_number,status,area_code,friendly_label,"
              "purchased_at,release_after,released_at")


def campaign_cap() -> int:
    try:
        return max(1, int(os.environ.get("SMS_NUMBERS_CAMPAIGN_CAP") or 49))
    except ValueError:
        return 49


def release_grace_days() -> int:
    try:
        return max(0, int(os.environ.get("SMS_NUMBER_RELEASE_GRACE_DAYS") or 14))
    except ValueError:
        return 14


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─── Row helpers ──────────────────────────────────────────────────────

async def _live_row(client: httpx.AsyncClient, business_id: str) -> Optional[Dict[str, Any]]:
    rows = await _sb_get(
        client,
        f"/sms_numbers?business_id=eq.{business_id}"
        f"&status=in.({','.join(LIVE_STATUSES)})&select={ROW_FIELDS}&limit=1",
    ) or []
    return rows[0] if rows else None


async def _row_for(client: httpx.AsyncClient, number_id: str,
                   business_id: str) -> Optional[Dict[str, Any]]:
    """Scoped by business as well as id — a number id is not a capability."""
    rows = await _sb_get(
        client,
        f"/sms_numbers?id=eq.{_pq(number_id)}&business_id=eq.{business_id}"
        f"&select={ROW_FIELDS},provider_sid,messaging_service_sid&limit=1",
    ) or []
    return rows[0] if rows else None


async def _live_count(client: httpx.AsyncClient) -> int:
    rows = await _sb_get(
        client,
        f"/sms_numbers?status=in.({','.join(LIVE_STATUSES)})&select=id&limit=1000",
    ) or []
    return len(rows)


async def _sb_delete(client: httpx.AsyncClient, path: str) -> None:
    try:
        r = await client.delete(f"{_sb_url()}/rest/v1{path}", headers=_sb_headers(), timeout=15.0)
        if r.status_code >= 400:
            logger.warning(f"supabase DELETE {path}: {r.status_code} {r.text[:200]}")
    except httpx.HTTPError as e:
        logger.warning(f"supabase DELETE {path} failed: {e}")


def _public(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """What the desk sees. Provider ids stay server-side."""
    if not row:
        return None
    return {k: row.get(k) for k in ROW_FIELDS.split(",")}


async def _default_area_code(client: httpx.AsyncClient, business_id: str) -> Optional[str]:
    """Best effort: the business's own phone, from its settings. A local
    number is what people expect on a card; a random state is not."""
    rows = await _sb_get(
        client, f"/businesses?id=eq.{business_id}&select=settings&limit=1",
    ) or []
    settings = (rows[0].get("settings") if rows else None) or {}
    for cand in (settings.get("phone"), settings.get("business_phone"),
                 (settings.get("contact") or {}).get("phone") if isinstance(settings.get("contact"), dict) else None):
        digits = normalize_phone(cand)
        if digits and digits.startswith("+1") and len(digits) == 12:
            return digits[2:5]
    return None


# ─── Eligibility (shared by GET, POST and Chief) ──────────────────────

def _ready_or_raise() -> None:
    if not _twilio_configured():
        raise HTTPException(503, {"error": "sms_not_configured",
                                  "message": "Texting isn't set up on the platform yet."})
    if not twilio_sms.platform_number():
        # Phase A's guarantee: every send pins a sender. Adding a second
        # number to the pool before the platform number is pinned would
        # let a shared-lane text go out from someone's private line.
        raise HTTPException(503, {"error": "platform_number_unpinned",
                                  "message": "Texting isn't ready for private numbers yet."})


def _plan_allows(business_id: str) -> Optional[str]:
    """None when allowed; otherwise the required plan (the 402 reason)."""
    import billing_limits
    try:
        billing_limits.require_feature(business_id, FEATURE)
        return None
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, dict) else {}
        return str(detail.get("required_plan") or "practice")


def _valid_area_code(code: str) -> None:
    if code and not (code.isdigit() and len(code) == 3):
        raise HTTPException(400, {"error": "bad_area_code",
                                  "message": "An area code is three digits."})


# ─── The cores — endpoints and Chief both call these ──────────────────

async def provision_core(client: httpx.AsyncClient, business_id: str, *,
                         phone_number: Optional[str] = None,
                         area_code: Optional[str] = None,
                         friendly_label: Optional[str] = None) -> Dict[str, Any]:
    """Buy → attach → active. Raises HTTPException with a practitioner-
    readable {error, message} detail; returns the public row."""
    required_plan = _plan_allows(business_id)
    if required_plan:
        raise HTTPException(402, {"error": "feature_locked", "feature": FEATURE,
                                  "required_plan": required_plan,
                                  "message": "A private texting number comes with the "
                                             f"{required_plan.title()} plan."})
    _ready_or_raise()
    biz = business_id

    existing = await _live_row(client, biz)
    if existing:
        raise HTTPException(409, {"error": "already_has_number",
                                  "number": _public(existing),
                                  "message": "This business already has a number."})

    used, cap = await _live_count(client), campaign_cap()
    if used >= cap:
        logger.error(f"campaign cap reached ({used}/{cap}) — request a number pool from Twilio")
        raise HTTPException(409, {"error": "campaign_full",
                                  "message": "Private numbers are fully allocated right now — "
                                             "we're adding capacity. Try again soon."})
    if used + 1 >= int(cap * 0.8):
        logger.warning(f"campaign at {used + 1}/{cap} numbers — time to request a number pool")

    # Which number?
    phone = normalize_phone(phone_number) if phone_number else ""
    code = (area_code or "").strip()
    if phone:
        code = code or phone[2:5]
    else:
        _valid_area_code(code)
        code = code or await _default_area_code(client, biz) or ""
        if not code:
            raise HTTPException(400, {"error": "area_code_required",
                                      "message": "Which area code would you like?"})
        try:
            found = await run_in_threadpool(twilio_sms.search_numbers, code, 1)
        except Exception as e:
            logger.warning(f"search failed area_code={code}: {e}")
            raise HTTPException(502, {"error": "search_failed",
                                      "message": "Couldn't look up numbers right now — try again in a minute."})
        if not found:
            raise HTTPException(404, {"error": "no_numbers",
                                      "message": f"No local numbers in {code} right now — try a nearby area code."})
        phone = normalize_phone(found[0]["phone_number"])

    # 1. The row, first. The partial unique index turns a concurrent
    #    second provision into a failed insert here, not a second
    #    purchase.
    rows = await _sb_post(client, "/sms_numbers", {
        "business_id": biz, "phone_number": phone, "status": "provisioning",
        "area_code": code or None,
        "friendly_label": (friendly_label or "").strip()[:60] or None,
    })
    if not rows:
        raise HTTPException(409, {"error": "provision_conflict",
                                  "message": "That number is being set up already — refresh in a moment."})
    row = rows[0] if isinstance(rows, list) else rows
    row_id = row.get("id")

    # 2. Buy.
    try:
        bought = await run_in_threadpool(twilio_sms.buy_number, phone)
    except Exception as e:
        logger.error(f"buy failed {phone} biz={biz[:8]}: {e}")
        await _sb_delete(client, f"/sms_numbers?id=eq.{_pq(row_id)}")
        raise HTTPException(502, {"error": "purchase_failed",
                                  "message": "That number couldn't be reserved — pick another or try again."})

    # 3. Attach to the Messaging Service (the 10DLC campaign). A line
    #    that isn't attached can't send compliantly and won't route
    #    inbound through our webhook — so it's not a line we keep.
    try:
        mg = await run_in_threadpool(twilio_sms.attach_to_service, bought["sid"])
    except Exception as e:
        logger.error(f"attach failed {phone} sid={bought['sid']}: {e} — releasing")
        try:
            await run_in_threadpool(twilio_sms.release_number, bought["sid"])
        except Exception as e2:
            logger.error(f"release after failed attach ALSO failed sid={bought['sid']}: {e2} — orphan on the account")
        await _sb_patch(client, f"/sms_numbers?id=eq.{_pq(row_id)}", {
            "status": "released", "provider_sid": bought["sid"],
            "released_at": _now().isoformat(), "updated_at": _now().isoformat(),
        })
        raise HTTPException(502, {"error": "attach_failed",
                                  "message": "The number couldn't be connected — nothing was kept. Try again."})

    await _sb_patch(client, f"/sms_numbers?id=eq.{_pq(row_id)}", {
        "status": "active", "provider_sid": bought["sid"],
        "messaging_service_sid": mg, "updated_at": _now().isoformat(),
    })
    await _log_event(client, biz, None, "sms_number_provisioned",
                     {"phone_number": phone, "area_code": code})
    row = await _live_row(client, biz) or {**row, "status": "active"}
    logger.info(f"provisioned {phone} for biz {biz[:8]}")
    return _public(row)


async def release_core(client: httpx.AsyncClient, business_id: str,
                       number_id: Optional[str] = None) -> Dict[str, Any]:
    """active → releasing with a grace window. number_id may be omitted
    (Chief doesn't know row ids) — the business's live row is used."""
    if number_id:
        row = await _row_for(client, number_id, business_id)
    else:
        row = await _live_row(client, business_id)
    if not row:
        raise HTTPException(404, {"error": "not_found",
                                  "message": "There's no number to release."})
    if row.get("status") not in ("active", "suspended"):
        raise HTTPException(409, {"error": "not_releasable", "status": row.get("status"),
                                  "number": _public(row),
                                  "message": "That number is already being released."
                                  if row.get("status") == "releasing" else
                                  "That number can't be released right now."})
    release_after = _now() + timedelta(days=release_grace_days())
    await _sb_patch(client, f"/sms_numbers?id=eq.{_pq(row['id'])}", {
        "status": "releasing", "release_after": release_after.isoformat(),
        "updated_at": _now().isoformat(),
    })
    await _log_event(client, business_id, None, "sms_number_release_requested",
                     {"phone_number": row.get("phone_number"),
                      "release_after": release_after.isoformat()})
    logger.info(f"release requested {row.get('phone_number')} biz={business_id[:8]} after={release_after.date()}")
    return {"ok": True, "status": "releasing", "release_after": release_after.isoformat(),
            "grace_days": release_grace_days(),
            "number": _public({**row, "status": "releasing",
                               "release_after": release_after.isoformat()})}


async def restore_core(client: httpx.AsyncClient, business_id: str,
                       number_id: Optional[str] = None) -> Dict[str, Any]:
    """releasing → active, inside the window."""
    if number_id:
        row = await _row_for(client, number_id, business_id)
    else:
        row = await _live_row(client, business_id)
    if not row:
        raise HTTPException(404, {"error": "not_found",
                                  "message": "There's no number to bring back."})
    if row.get("status") != "releasing":
        raise HTTPException(409, {"error": "not_restorable", "status": row.get("status"),
                                  "message": "That number is no longer held."})
    await _sb_patch(client, f"/sms_numbers?id=eq.{_pq(row['id'])}", {
        "status": "active", "release_after": None, "updated_at": _now().isoformat(),
    })
    await _log_event(client, business_id, None, "sms_number_restored",
                     {"phone_number": row.get("phone_number")})
    return {"ok": True, "status": "active",
            "number": _public({**row, "status": "active", "release_after": None})}


# ─── GET /sms/numbers ─────────────────────────────────────────────────

@router.get("/sms/numbers")
async def get_number(business_id: str, user: AuthedUser = Depends(require_user)):
    import business_access
    business_access.assert_access(str(business_id), user, "viewer")
    async with httpx.AsyncClient() as client:
        row = await _live_row(client, business_id)
        used = await _live_count(client)
    cap = campaign_cap()
    required_plan = _plan_allows(business_id)
    ready = _twilio_configured() and bool(twilio_sms.platform_number())
    eligible = row is None and required_plan is None and ready and used < cap
    reason = None
    if row is None and not eligible:
        reason = ("plan" if required_plan else
                  "not_ready" if not ready else
                  "capacity")
    return {
        "number": _public(row),
        "eligible": eligible,
        "reason": reason,
        "required_plan": required_plan,
        "grace_days": release_grace_days(),
    }


# ─── GET /sms/numbers/available ───────────────────────────────────────

@router.get("/sms/numbers/available")
async def available_numbers(business_id: str, area_code: Optional[str] = None,
                            user: AuthedUser = Depends(require_user)):
    import business_access
    business_access.assert_access(str(business_id), user, "viewer")
    _ready_or_raise()
    code = (area_code or "").strip()
    _valid_area_code(code)
    async with httpx.AsyncClient() as client:
        if not code:
            code = await _default_area_code(client, business_id) or ""
    if not code:
        raise HTTPException(400, {"error": "area_code_required",
                                  "message": "Which area code would you like?"})
    try:
        found = await run_in_threadpool(twilio_sms.search_numbers, code, 10)
    except Exception as e:
        logger.warning(f"search failed area_code={code}: {e}")
        raise HTTPException(502, {"error": "search_failed",
                                  "message": "Couldn't look up numbers right now — try again in a minute."})
    return {"area_code": code, "numbers": found}


# ─── POST /sms/numbers — buy → attach → active ────────────────────────

class ProvisionBody(BaseModel):
    business_id: str
    phone_number: Optional[str] = None   # a specific choice from /available
    area_code: Optional[str] = None      # else: the first local number here
    friendly_label: Optional[str] = None


@router.post("/sms/numbers")
async def provision_number(body: ProvisionBody, user: AuthedUser = Depends(require_user)):
    import business_access
    business_access.assert_access(str(body.business_id), user, "admin")
    async with httpx.AsyncClient() as client:
        row = await provision_core(
            client, body.business_id, phone_number=body.phone_number,
            area_code=body.area_code, friendly_label=body.friendly_label)
    return {"ok": True, "number": row}


# ─── DELETE /sms/numbers/{id} — releasing, with a way back ────────────

@router.delete("/sms/numbers/{number_id}")
async def release_number(number_id: str, business_id: str,
                         user: AuthedUser = Depends(require_user)):
    import business_access
    business_access.assert_access(str(business_id), user, "admin")
    async with httpx.AsyncClient() as client:
        return await release_core(client, business_id, number_id)


class RestoreBody(BaseModel):
    business_id: str


@router.post("/sms/numbers/{number_id}/restore")
async def restore_number(number_id: str, body: RestoreBody,
                         user: AuthedUser = Depends(require_user)):
    import business_access
    business_access.assert_access(str(body.business_id), user, "admin")
    async with httpx.AsyncClient() as client:
        return await restore_core(client, body.business_id, number_id)


# ─── The release sweep (hourly, APScheduler) ──────────────────────────

async def release_sweep() -> Dict[str, int]:
    """Hand back every line whose grace window has passed: detach from
    the Messaging Service, release on Twilio, mark released. Each row
    is its own try — one bad release must not hold the others."""
    stats = {"checked": 0, "released": 0, "failed": 0}
    async with httpx.AsyncClient() as client:
        due = await _sb_get(
            client,
            f"/sms_numbers?status=eq.releasing&release_after=lt.{_pq(_now().isoformat())}"
            f"&select=id,business_id,phone_number,provider_sid&limit=100",
        ) or []
        for row in due:
            stats["checked"] += 1
            sid = row.get("provider_sid")
            try:
                if sid:
                    await run_in_threadpool(twilio_sms.detach_from_service, sid)
                    await run_in_threadpool(twilio_sms.release_number, sid)
                await _sb_patch(client, f"/sms_numbers?id=eq.{_pq(row['id'])}", {
                    "status": "released", "released_at": _now().isoformat(),
                    "updated_at": _now().isoformat(),
                })
                await _log_event(client, row["business_id"], None, "sms_number_released",
                                 {"phone_number": row.get("phone_number")})
                stats["released"] += 1
                logger.info(f"released {row.get('phone_number')} biz={str(row.get('business_id'))[:8]}")
            except Exception as e:
                stats["failed"] += 1
                logger.error(f"release failed {row.get('phone_number')} sid={sid}: {e}")
    return stats
