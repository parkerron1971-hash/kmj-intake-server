"""
lifecycle_emails.py — the three emails a practitioner's first week deserves.

THE GAP THIS CLOSES
  A business was created, a trial started, a trial ran out, and the
  platform said nothing by email at any of those moments. The trial
  countdown lived in Settings → Billing and the platform-owner panels;
  enforcement is ON, so a practitioner who stopped opening the app was
  locked out with no warning. This module sends exactly three
  transactional emails, each once per business:

    welcome        — the moment their FIRST business is created
    trial_ending   — TRIAL_ENDING_DAYS before trial_ends_at, while trialing
    trial_ended    — once the trial has lapsed (calendar or credit tank)

WHAT THIS JOB IS ALLOWED TO BE
  * It reads /businesses only — the row that already carries
    subscription_status, trial_ends_at and comp_tier. No new table.
  * Idempotency rides on businesses.settings.lifecycle_emails, a small
    dict of ISO stamps ({"welcome_at", "trial_ending_at",
    "trial_ended_at"}). Read-modify-write on settings, stamped AFTER a
    successful send: a send that fails is retried by the next pass; a
    stamp that fails after a send costs at most one duplicate. Never the
    silent-never-sent failure this module exists to fix.
  * Grandfathered owners and comped businesses never trial, so they never
    get trial mail. They still get the welcome.
  * The ENDED email fires only inside ENDED_LOOKBACK_DAYS of
    trial_ends_at. The first deploy must not write to everyone whose
    trial lapsed months ago (the first-pass-is-silent rule).
  * Nothing raises out of the public entry points. Both callers sit on
    paths where failing loudly costs something real — a business signup
    and a scheduler tick.
  * Kill switch: LIFECYCLE_EMAILS=off.

Transactional, not marketing: these go to the account holder about the
account. send_via_resend still attaches List-Unsubscribe to every send
and honours the suppression list, as it does for all platform mail.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

import sb_clients
from app_base import app_base_url

logger = logging.getLogger("lifecycle_emails")

SETTINGS_KEY = "lifecycle_emails"
FROM_NAME = "The Solutionist System"
DEFAULT_FROM = "noreply@mysolutionist.app"

# Send "your trial ends soon" when this many days (or fewer) remain.
TRIAL_ENDING_DAYS = 2
# "Your trial ended" is only sent within this many days AFTER the end.
ENDED_LOOKBACK_DAYS = 3

_BIZ_SELECT = ("id,name,type,owner_id,subscription_status,trial_ends_at,"
               "comp_tier,settings,created_at")


# ─── Config ──────────────────────────────────────────────────────────

def enabled() -> bool:
    return (os.environ.get("LIFECYCLE_EMAILS") or "on").strip().lower() != "off"


def trial_ending_days() -> int:
    try:
        return max(1, int(os.environ.get("LIFECYCLE_TRIAL_ENDING_DAYS") or TRIAL_ENDING_DAYS))
    except ValueError:
        return TRIAL_ENDING_DAYS


def _trial_days() -> int:
    try:
        return max(0, int(os.environ.get("BILLING_TRIAL_DAYS") or "7"))
    except ValueError:
        return 7


def _from_email() -> str:
    return (os.environ.get("RESEND_FROM_EMAIL") or DEFAULT_FROM).strip()


def _support_email() -> str:
    try:
        import platform_addresses
        return platform_addresses.public_contact_email()
    except Exception:
        return "info@mysolutionist.app"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _first_name(full: Optional[str]) -> str:
    return (full or "").strip().split(" ")[0] or "there"


# ─── Copy ────────────────────────────────────────────────────────────
# Plain text on purpose: it lands in every client, renders in dark mode,
# and reads like a person wrote it. Links are bare so they stay clickable.

def welcome_body(*, business_name: str, first_name: str) -> str:
    app = app_base_url()
    days = _trial_days()
    trial_line = (f"Your first {days} days on any plan are free. "
                  if days else "")
    return (
        f"Hi {first_name},\n\n"
        f"{business_name} is set up. Chief has read what you told it and is "
        f"ready when you are.\n\n"
        f"Three moves that make the first week count:\n\n"
        f"1. Bring your people in. Add a contact, or import the spreadsheet "
        f"you already have (Operate → Contacts → Import).\n"
        f"   {app}/?nav=operate:contacts\n\n"
        f"2. Put something on the shelf. Add the service, session or product "
        f"you sell most, so bookings and invoices have something to point at.\n"
        f"   {app}/?nav=build\n\n"
        f"3. Ask Chief for tomorrow. Open Chief and say what you want done "
        f"this week. It plans, drafts and follows up — you approve.\n"
        f"   {app}/\n\n"
        f"{trial_line}Reply to this email if anything is unclear — a person "
        f"reads it.\n\n"
        f"— The Solutionist System\n"
        f"{_support_email()}"
    )


def trial_ending_body(*, business_name: str, first_name: str,
                      days_left: int, ends_at: datetime) -> str:
    app = app_base_url()
    when = "tomorrow" if days_left <= 1 else f"in {days_left} days"
    return (
        f"Hi {first_name},\n\n"
        f"The free trial for {business_name} ends {when} "
        f"({ends_at.strftime('%B %d')}).\n\n"
        f"If your card is on file, nothing changes: your plan continues and "
        f"you are billed from that day. If it is not, the app locks at the "
        f"end of the trial. Nothing is deleted — your data stays put and "
        f"stays exportable — but Chief stops working until a plan is chosen.\n\n"
        f"Choose or confirm your plan here:\n"
        f"   {app}/?settings=billing\n\n"
        f"Not the right fit? Reply and say so — no forms, no hoops.\n\n"
        f"— The Solutionist System\n"
        f"{_support_email()}"
    )


def trial_ended_body(*, business_name: str, first_name: str,
                     reason: str) -> str:
    app = app_base_url()
    why = ("You used the trial's full allowance of Chief work before the "
           "calendar ran out — which usually means it earned its keep."
           if reason == "trial_credits_spent" else
           "The trial window has closed.")
    return (
        f"Hi {first_name},\n\n"
        f"The free trial for {business_name} has ended. {why}\n\n"
        f"Everything you built is still there: contacts, bookings, invoices, "
        f"Chief's notes — all of it. Pick a plan and it is exactly where you "
        f"left it:\n"
        f"   {app}/?settings=billing\n\n"
        f"If you would rather take your data with you, the export lives in "
        f"Settings → Your Data, and it keeps working after the trial.\n\n"
        f"Questions, or a reason the trial didn't fit? Reply here.\n\n"
        f"— The Solutionist System\n"
        f"{_support_email()}"
    )


# ─── Plumbing ────────────────────────────────────────────────────────

async def _send(*, to_email: str, to_name: Optional[str],
                subject: str, body: str) -> bool:
    from email_sender import send_via_resend
    await send_via_resend(
        to_email=to_email, to_name=to_name,
        from_email=_from_email(), from_name=FROM_NAME,
        subject=subject, body=body, reply_to=_support_email())
    return True


async def _owner_email(owner_id: str) -> Optional[str]:
    """Auth Admin lookup — the only place a user's email lives."""
    base = sb_clients.sb_url()
    key = sb_clients.sb_service_role()
    if not base or not key or not owner_id:
        return None
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f"{base}/auth/v1/admin/users/{owner_id}",
                        headers={"apikey": key, "Authorization": f"Bearer {key}"})
    if r.status_code >= 400:
        return None
    j = r.json() or {}
    email = (j.get("email") or "").strip()
    return email or None


def _stamps(row: Dict[str, Any]) -> Dict[str, Any]:
    s = row.get("settings")
    s = s if isinstance(s, dict) else {}
    le = s.get(SETTINGS_KEY)
    return le if isinstance(le, dict) else {}


def _stamp(business_id: str, key: str) -> None:
    """Read-modify-write settings.lifecycle_emails.<key> = now.

    Fresh read on purpose: the row we sized the send from may be minutes
    old and the practitioner may have changed a setting since. Merging
    into the LIVE settings blob is what keeps this write from clobbering
    theirs."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,settings&limit=1") or []
    settings = (rows[0].get("settings") if rows else None) or {}
    if not isinstance(settings, dict):
        settings = {}
    le = dict(settings.get(SETTINGS_KEY) or {})
    le[key] = _now().strftime("%Y-%m-%dT%H:%M:%SZ")
    settings[SETTINGS_KEY] = le
    sb_clients.sb_patch_as_service(f"/businesses?id=eq.{business_id}",
                                   {"settings": settings})


def _is_grandfathered(owner_id: Optional[str]) -> bool:
    try:
        import usage_metering
        return bool(usage_metering.is_grandfathered_user(owner_id))
    except Exception:
        return False


def _tank_spent(row: Dict[str, Any]) -> bool:
    try:
        import usage_metering
        return bool(usage_metering.trial_credits_exhausted(str(row.get("id")), row))
    except Exception:
        return False


# ─── Welcome (door 1: business creation) ─────────────────────────────

async def send_welcome(business: Dict[str, Any], to_email: Optional[str],
                       user_name: Optional[str] = None) -> Dict[str, Any]:
    """Called from launch_access.create_business as a background task.

    Sends once, for the owner's FIRST business only. A second or third
    business is not a new arrival and gets no welcome. Never raises."""
    biz_id = str(business.get("id") or "")
    try:
        if not enabled():
            return {"sent": False, "reason": "disabled"}
        if not biz_id or not to_email:
            return {"sent": False, "reason": "no_recipient"}
        if _stamps(business).get("welcome_at"):
            return {"sent": False, "reason": "already_sent"}
        owner_id = str(business.get("owner_id") or "")
        if owner_id:
            others = sb_clients.sb_get_as_service(
                f"/businesses?owner_id=eq.{owner_id}&id=neq.{biz_id}"
                f"&select=id&limit=1") or []
            if others:
                return {"sent": False, "reason": "not_first_business"}
        name = (business.get("name") or "Your business").strip()
        await _send(
            to_email=to_email, to_name=user_name or None,
            subject=f"{name} is set up — three moves for your first week",
            body=welcome_body(business_name=name,
                              first_name=_first_name(user_name)))
        _stamp(biz_id, "welcome_at")
        logger.info(f"[lifecycle] welcome sent biz={biz_id}")
        return {"sent": True}
    except Exception as e:
        logger.warning(f"[lifecycle] welcome not sent biz={biz_id}: {e}")
        return {"sent": False, "reason": "error", "error": str(e)[:200]}


# ─── Trial sweep (door 2: the daily tick) ────────────────────────────

def _classify(row: Dict[str, Any], now: datetime) -> Optional[Dict[str, Any]]:
    """Which trial email, if any, does this row need right now?

    Pure over the row plus the clock; the tank check is the one read.
    Returns {"kind": "trial_ending"|"trial_ended", ...} or None."""
    status = (row.get("subscription_status") or "").strip().lower()
    if (row.get("comp_tier") or "").strip():
        return None
    ends = _parse(row.get("trial_ends_at"))
    stamps = _stamps(row)

    if status == "trialing":
        if ends is None:
            return None
        if ends > now:
            # The tank can run dry with days still on the calendar, and
            # it can happen AFTER the ending-soon mail went out — so the
            # tank is checked first and against its own stamp.
            if _tank_spent(row):
                if stamps.get("trial_ended_at"):
                    return None
                return {"kind": "trial_ended", "reason": "trial_credits_spent"}
            if stamps.get("trial_ending_at"):
                return None
            days_left = (ends - now).total_seconds() / 86400.0
            if days_left <= trial_ending_days():
                # Nearest day, floor 1: a trial ending 30 hours after a
                # morning sweep ends "tomorrow", not "in 2 days".
                return {"kind": "trial_ending", "days_left": max(1, int(days_left + 0.5)),
                        "ends_at": ends}
            return None
        # Lapsed on the calendar and Stripe has not flipped the status yet.
        if stamps.get("trial_ended_at"):
            return None
        if now - ends > timedelta(days=ENDED_LOOKBACK_DAYS):
            return None
        return {"kind": "trial_ended", "reason": "trial_expired"}

    if status == "canceled" and ends is not None:
        # Stripe's end_behavior=cancel: the trial closed without a card.
        if stamps.get("trial_ended_at"):
            return None
        if ends > now or now - ends > timedelta(days=ENDED_LOOKBACK_DAYS):
            return None
        return {"kind": "trial_ended", "reason": "trial_expired"}
    return None


async def sweep_tick() -> Dict[str, Any]:
    """Daily. Reads every active business that could be in or just past a
    trial and sends whichever of the two trial emails is due. Never
    raises — a scheduler tick that throws is a scheduler tick that
    silently stops being scheduled."""
    out: Dict[str, Any] = {"ok": True, "scanned": 0, "sent": 0, "skipped": 0,
                           "failed": 0, "sent_kinds": []}
    if not enabled():
        out["ok"] = False
        out["reason"] = "disabled"
        return out
    try:
        import feature_gates
        if not feature_gates.enforcement_on():
            # Nothing locks while enforcement is off, so "your trial ended"
            # would describe a lock that never happens. Ending-soon mail
            # would be equally hollow. Stay quiet until the gate is real.
            out["ok"] = False
            out["reason"] = "enforcement_off"
            return out
        rows: List[Dict[str, Any]] = sb_clients.sb_get_as_service(
            f"/businesses?select={_BIZ_SELECT}&is_active=eq.true"
            f"&subscription_status=in.(trialing,canceled)"
            f"&trial_ends_at=not.is.null&limit=1000") or []
    except Exception as e:
        logger.warning(f"[lifecycle] sweep read failed: {e}")
        out["ok"] = False
        out["reason"] = f"read_failed: {str(e)[:120]}"
        return out

    now = _now()
    for row in rows:
        out["scanned"] += 1
        try:
            need = _classify(row, now)
            if not need:
                out["skipped"] += 1
                continue
            owner_id = str(row.get("owner_id") or "")
            if _is_grandfathered(owner_id):
                out["skipped"] += 1
                continue
            to = await _owner_email(owner_id)
            if not to:
                out["skipped"] += 1
                continue
            name = (row.get("name") or "Your business").strip()
            first = "there"
            if need["kind"] == "trial_ending":
                await _send(
                    to_email=to, to_name=None,
                    subject=f"Your {name} trial ends "
                            + ("tomorrow" if need["days_left"] <= 1
                               else f"in {need['days_left']} days"),
                    body=trial_ending_body(business_name=name, first_name=first,
                                           days_left=need["days_left"],
                                           ends_at=need["ends_at"]))
                _stamp(str(row["id"]), "trial_ending_at")
            else:
                await _send(
                    to_email=to, to_name=None,
                    subject=f"Your {name} trial has ended — your work is still here",
                    body=trial_ended_body(business_name=name, first_name=first,
                                          reason=need["reason"]))
                _stamp(str(row["id"]), "trial_ended_at")
            out["sent"] += 1
            out["sent_kinds"].append(need["kind"])
        except Exception as e:
            out["failed"] += 1
            logger.warning(f"[lifecycle] send failed biz={row.get('id')}: {e}")
    logger.info(f"[lifecycle] sweep scanned={out['scanned']} sent={out['sent']} "
                f"failed={out['failed']}")
    return out
