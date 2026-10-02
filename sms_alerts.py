"""
sms_alerts.py — AUTOMATED A2P alerts (2026-07-07, campaign approved).

The 10DLC campaign's declared traffic covers booking confirmations,
appointment reminders, account notifications, and support replies.
Support replies + manual sends + broadcast already flow through
sms_service / sms_routing. This module adds the two AUTOMATED legs:

  1. BOOKING CONFIRMATION — send_booking_confirmation(), called by
     booking_widget_router right after a successful /book or /book-anon
     (immediately after the consent audit row is recorded). Best-effort:
     it NEVER raises into the booking response.

  2. APPOINTMENT REMINDER — reminder_sweep(), an hourly APScheduler job
     (registered in kmj_intake_automation, hermes pattern) over the
     sessions table: status=scheduled, scheduled_for 22-26h out.

THE CONSENT RULE (has_sms_consent — shared by both alert types):
  a customer phone may receive an automated alert from a business iff
    (  an sms_consents row exists for this phone scoped to this
       business (booking-form checkbox, source='booking')
    OR a platform web-form consent exists for this phone
       (source='web_form', business_id NULL — the public /sms page)
    OR an sms_bindings row exists for (phone, business) — texting the
       business keyword is an explicit opt-in; route_inbound confirmed
       it with the connection+consent reply )
  AND the phone is NOT opted out (sms_opt_outs via is_opted_out —
  STOP always wins, platform-wide under the Direct model).

QUIET HOURS (reminders only): sends happen 9am-8pm America/New_York.
Outside that band the sweep skips entirely; the 22-26h eligibility
window is 4h wide and shifts hourly, so a daytime pass exists for any
appointment whose local clock time isn't itself in the dead of night.
Confirmations are exempt — they are a direct response to a customer
action seconds earlier.

DEDUPE (reminders): an events row event_type='sms_reminder_sent' with
the session id in data marks a session as reminded; the sweep queries
events before sending. The event is logged only AFTER a successful
send, so a failed send is retried on the next hourly pass.

CONTROLS:
  • env SMS_ALERTS_ENABLED — platform kill-switch, default '1' (on).
    '0'/'false'/'off' disables both alert types without a deploy.
  • businesses.settings.sms_alerts = {"confirmations": bool,
    "reminders": bool} — per-practitioner toggle, default TRUE when
    absent (approved traffic, consented recipients). Honored via
    Chief/settings edits today; frontend toggle can come later.

Every outbound is recorded exactly like SmsHub sends: an sms_messages
row (_store_sms, direction=outbound) + an events row (_log_event), and
composed under sender_brand() — the platform brand, per the Direct
model. Message copy tracks the approved campaign samples #1 and #2.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx

from sms_service import (
    _pq,
    _sb_get, _store_sms, _log_event, _find_contact_by_phone,
    normalize_phone, is_opted_out,
)
from sms_routing import _send_platform_sms, sender_brand

logger = logging.getLogger("sms_alerts")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] alert: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


# ─── Tunables ─────────────────────────────────────────────────────────

QUIET_TZ = ZoneInfo("America/New_York")
QUIET_SEND_START_HOUR = 9    # inclusive — 9:00 AM ET
QUIET_SEND_END_HOUR = 20     # exclusive — 8:00 PM ET
REMINDER_WINDOW_MIN_HOURS = 22
REMINDER_WINDOW_MAX_HOURS = 26
SEND_PACING_SEC = 0.25       # same gentle pacing as /sms/broadcast


def alerts_enabled() -> bool:
    """Platform kill-switch. SMS_ALERTS_ENABLED default '1' (on)."""
    v = (os.environ.get("SMS_ALERTS_ENABLED") or "1").strip().lower()
    return v not in ("0", "false", "off", "no")


def _alert_setting(settings: Optional[Dict[str, Any]], kind: str) -> bool:
    """Per-practitioner toggle: settings.sms_alerts = {'confirmations':
    bool, 'reminders': bool}. Default TRUE when the key (or the whole
    dict) is absent — this is approved traffic to consented recipients;
    the practitioner opts OUT, not in."""
    sa = (settings or {}).get("sms_alerts")
    if not isinstance(sa, dict):
        return True
    v = sa.get(kind)
    return True if v is None else bool(v)


def _paused(biz: Optional[Dict[str, Any]]) -> bool:
    """settings.automations_paused — the practitioner's blanket stop.

    Distinct from the sms_alerts.reminders toggle above: that one says
    "not this kind of message, ever", this one says "nothing automatic,
    for now". Both have to be off for the sweep to text anyone.

    Delegates to rules_engine so there is one reading of the flag. Falls
    back to the row we already hold rather than defaulting either way —
    guessing "paused" silences a working alert rail on an import error,
    guessing "running" discards the practitioner's instruction."""
    try:
        import rules_engine
        return bool(rules_engine.business_paused(biz))
    except Exception as e:
        logger.warning(f"[ALERT] pause predicate unavailable, reading directly: {e}")
        return bool(((biz or {}).get("settings") or {}).get("automations_paused"))


# ─── Consent (the shared rule) ────────────────────────────────────────

async def _positive_consent(client: httpx.AsyncClient, business_id: str,
                            phone: str) -> bool:
    """The affirmative half of the rule: business-scoped consent OR
    platform web-form consent OR a keyword binding to this business."""
    rows = await _sb_get(
        client,
        f"/sms_consents?phone=eq.{_pq(phone)}"
        f"&or=(business_id.eq.{business_id},source.eq.web_form)"
        f"&select=id&limit=1",
    ) or []
    if rows:
        return True
    rows = await _sb_get(
        client,
        f"/sms_bindings?customer_phone=eq.{_pq(phone)}"
        f"&business_id=eq.{business_id}&select=id&limit=1",
    ) or []
    return bool(rows)


async def has_sms_consent(client: httpx.AsyncClient, business_id: str,
                          phone: str) -> bool:
    """THE CONSENT RULE for automated alerts (see module docstring):
    (sms_consents row for this business OR platform web_form consent OR
    sms_bindings row for this business) AND NOT opted out. STOP always
    wins regardless of any recorded consent."""
    phone = normalize_phone(phone) or (phone or "")
    if not phone:
        return False
    if await is_opted_out(client, phone, business_id):
        return False
    return await _positive_consent(client, business_id, phone)


# ─── Formatting helpers ───────────────────────────────────────────────

def _business_tz(business: Dict[str, Any]) -> ZoneInfo:
    """Display timezone for date/time in message copy:
    settings.availability.timezone when set, else America/New_York
    (the platform's home tz — better than confusing customers with
    UTC)."""
    settings = business.get("settings") or {}
    tz = ((settings.get("availability") or {}).get("timezone") or "").strip()
    if tz:
        try:
            return ZoneInfo(tz)
        except Exception:
            pass
    return QUIET_TZ


def _fmt_local(iso_str: str, tz: ZoneInfo) -> Dict[str, str]:
    """Windows-safe (no %-d) local formatting. Raises on unparsable
    input — callers treat that as 'skip, do not send garbage copy'."""
    s = str(iso_str).replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    loc = dt.astimezone(tz)
    return {
        "date": loc.strftime("%A, %B %d").replace(" 0", " "),
        "day": loc.strftime("%A"),
        "time": loc.strftime("%I:%M %p").lstrip("0"),
    }


def confirmation_text(first_name: str, business_name: str,
                      date_str: str, time_str: str) -> str:
    """Campaign sample #1 shape."""
    return (
        f"{sender_brand()}: Hi {first_name}, your booking with {business_name} "
        f"is confirmed for {date_str} at {time_str}. Reply to this message "
        f"with any questions. Reply STOP to opt out."
    )


def reminder_text(business_name: str, day_str: str, time_str: str) -> str:
    """Campaign sample #2 shape."""
    return (
        f"{sender_brand()}: Reminder from {business_name} — your appointment "
        f"is {day_str} at {time_str}. Reply to this message if you need to "
        f"make a change. Reply STOP to unsubscribe."
    )


# ─── Alert #1: booking confirmation ───────────────────────────────────

async def send_booking_confirmation(
    *,
    business: Dict[str, Any],
    entry_data: Dict[str, Any],
    customer_name: str,
    appointment_iso: str,
) -> Dict[str, Any]:
    """Fire the booking-confirmation text after a successful booking.

    Best-effort by contract: NEVER raises — every failure path returns a
    status dict (useful for logs + tests) and the booking response is
    already on its way regardless. Consent/kill-switch/toggle checks all
    live HERE so the router hook stays a one-liner."""
    try:
        if not alerts_enabled():
            return {"status": "disabled"}
        if not _alert_setting(business.get("settings"), "confirmations"):
            return {"status": "toggled_off"}

        raw = (entry_data.get("phone") or entry_data.get("customer_phone")
               or entry_data.get("mobile") or "")
        phone = normalize_phone(str(raw))
        if not phone:
            return {"status": "no_phone"}

        biz_id = business.get("id")
        biz_name = business.get("name") or "the business"
        try:
            parts = _fmt_local(appointment_iso, _business_tz(business))
        except Exception:
            logger.info(f"[ALERT] confirmation skipped — unparsable datetime {appointment_iso!r}")
            return {"status": "no_datetime"}

        async with httpx.AsyncClient() as client:
            if not await has_sms_consent(client, biz_id, phone):
                logger.info(f"[ALERT] confirmation skipped — no consent {phone} biz={str(biz_id)[:8]}")
                return {"status": "no_consent"}

            first = (customer_name or "").strip().split()[0] if (customer_name or "").strip() else "there"
            body = confirmation_text(first, biz_name, parts["date"], parts["time"])

            provider_id = await _send_platform_sms(
                phone, body, business_id=biz_id, client=client)

            # Record exactly like /sms/send does: sms_messages row + event.
            contact = await _find_contact_by_phone(client, biz_id, phone)
            contact_id = contact.get("id") if contact else None
            msg_id = await _store_sms(
                client, business_id=biz_id, contact_id=contact_id,
                phone_number=phone, message=body, direction="outbound",
                telnyx_id=provider_id, status="sent", sent_by="system",
            )
            await _log_event(client, biz_id, contact_id, "sms_confirmation_sent", {
                "to": phone,
                "preview": body[:200],
                "appointment_at": appointment_iso,
                "telnyx_id": provider_id,
                "sms_id": msg_id,
            })
        logger.info(f"[ALERT] confirmation sent to {phone} biz={str(biz_id)[:8]}")
        return {"status": "sent", "sms_id": msg_id}
    except Exception as e:
        # Contract: a confirmation text must never fail the booking.
        logger.warning(f"[ALERT] booking confirmation failed (non-fatal): {e}")
        return {"status": "error", "error": str(e)[:200]}


# ─── Alert #2: appointment reminder sweep (hourly) ────────────────────

def _in_send_window(now_local: Optional[datetime] = None) -> bool:
    """Quiet-hours gate: True 9:00am-7:59pm America/New_York."""
    now_local = now_local or datetime.now(QUIET_TZ)
    return QUIET_SEND_START_HOUR <= now_local.hour < QUIET_SEND_END_HOUR


async def reminder_sweep() -> Dict[str, int]:
    """Hourly job (kmj_intake_automation, hermes pattern).

    Finds sessions with scheduled_for 22-26h from now, status=scheduled,
    not yet reminded (no prior sms_reminder_sent event carrying the
    session id), resolves the contact's phone, applies the shared
    consent rule + the per-business reminders toggle, and sends the
    campaign-sample-#2 reminder. Quiet hours: outside 9am-8pm ET the
    whole sweep skips — the 4h-wide eligibility window shifts hourly so
    a later daytime pass picks the session up. Never raises (scheduler
    job); returns counters for logs + tests."""
    stats = {"sent": 0, "failed": 0, "deduped": 0, "skipped_no_consent": 0,
             "skipped_optout": 0, "skipped_quiet": 0, "skipped_no_phone": 0,
             "skipped_toggled_off": 0}
    try:
        if not alerts_enabled():
            logger.info("[ALERT] reminder sweep skipped — SMS_ALERTS_ENABLED off")
            return stats
        if not _in_send_window():
            stats["skipped_quiet"] = 1
            logger.info("[ALERT] reminder sweep skipped — quiet hours (send window 9am-8pm ET); "
                        "next daytime pass will catch the 22-26h window")
            return stats

        now = datetime.now(timezone.utc)
        lo = (now + timedelta(hours=REMINDER_WINDOW_MIN_HOURS)).isoformat()
        hi = (now + timedelta(hours=REMINDER_WINDOW_MAX_HOURS)).isoformat()

        async with httpx.AsyncClient() as client:
            sessions = await _sb_get(
                client,
                f"/sessions?scheduled_for=gte.{lo}&scheduled_for=lte.{hi}"
                f"&status=eq.scheduled&contact_id=not.is.null"
                f"&select=id,business_id,contact_id,scheduled_for,title,session_type"
                f"&order=scheduled_for.asc&limit=500",
            ) or []
            if not sessions:
                logger.info("[ALERT] reminder sweep: no sessions in the 22-26h window")
                return stats

            # Dedupe — one reminder per session, marked by the event we
            # log after a successful send.
            session_ids = [s["id"] for s in sessions if s.get("id")]
            already = set()
            for i in range(0, len(session_ids), 50):
                chunk = ",".join(str(sid) for sid in session_ids[i:i + 50])
                rows = await _sb_get(
                    client,
                    f"/events?event_type=eq.sms_reminder_sent"
                    f"&data->>session_id=in.({chunk})&select=data&limit=200",
                ) or []
                for r in rows:
                    sid = (r.get("data") or {}).get("session_id")
                    if sid:
                        already.add(str(sid))

            # Batch-load businesses (name + settings toggle) + contacts.
            biz_ids = sorted({s["business_id"] for s in sessions if s.get("business_id")})
            contact_ids = sorted({s["contact_id"] for s in sessions if s.get("contact_id")})
            biz_map: Dict[str, Dict[str, Any]] = {}
            if biz_ids:
                rows = await _sb_get(
                    client,
                    f"/businesses?id=in.({','.join(biz_ids)})&select=id,name,settings",
                ) or []
                biz_map = {r["id"]: r for r in rows}
            contact_map: Dict[str, Dict[str, Any]] = {}
            if contact_ids:
                rows = await _sb_get(
                    client,
                    f"/contacts?id=in.({','.join(contact_ids)})&select=id,name,phone",
                ) or []
                contact_map = {r["id"]: r for r in rows}

            for s in sessions:
                sid = str(s.get("id"))
                if sid in already:
                    stats["deduped"] += 1
                    continue
                biz = biz_map.get(s.get("business_id"))
                if not biz:
                    stats["skipped_no_phone"] += 1  # unresolvable — count with unsendables
                    continue
                if not _alert_setting(biz.get("settings"), "reminders"):
                    stats["skipped_toggled_off"] += 1
                    continue
                # The pause switch. Counted with the toggle because that
                # is what it is — a second, broader "not right now" that
                # this sweep has never read, so a practitioner who paused
                # their automations still had Chief texting their clients
                # the next morning. Reminders resume on the hourly pass
                # after it is switched back on; a session whose window has
                # closed by then simply does not get one, which is the
                # correct reading of "pause my automations".
                if _paused(biz):
                    stats["skipped_toggled_off"] += 1
                    continue
                contact = contact_map.get(s.get("contact_id")) or {}
                phone = normalize_phone(contact.get("phone"))
                if not phone:
                    stats["skipped_no_phone"] += 1
                    continue
                if await is_opted_out(client, phone, biz["id"]):
                    stats["skipped_optout"] += 1
                    continue
                if not await _positive_consent(client, biz["id"], phone):
                    stats["skipped_no_consent"] += 1
                    continue
                try:
                    parts = _fmt_local(s.get("scheduled_for"), _business_tz(biz))
                except Exception:
                    stats["skipped_no_phone"] += 1
                    continue

                body = reminder_text(biz.get("name") or "the business",
                                     parts["day"], parts["time"])
                try:
                    provider_id = await _send_platform_sms(
                        phone, body, business_id=biz["id"], client=client)
                    msg_id = await _store_sms(
                        client, business_id=biz["id"],
                        contact_id=contact.get("id"), phone_number=phone,
                        message=body, direction="outbound",
                        telnyx_id=provider_id, status="sent", sent_by="system",
                    )
                    # The dedupe marker — logged AFTER a successful send
                    # so failures retry on the next hourly pass.
                    await _log_event(client, biz["id"], contact.get("id"),
                                     "sms_reminder_sent", {
                                         "session_id": sid,
                                         "to": phone,
                                         "scheduled_for": s.get("scheduled_for"),
                                         "preview": body[:200],
                                         "telnyx_id": provider_id,
                                         "sms_id": msg_id,
                                     })
                    stats["sent"] += 1
                except Exception as e:
                    stats["failed"] += 1
                    logger.warning(f"[ALERT] reminder send failed to {phone}: {e}")
                await asyncio.sleep(SEND_PACING_SEC)
    except Exception as e:
        logger.warning(f"[ALERT] reminder sweep errored (non-fatal): {e}")

    logger.info(
        "[ALERT] reminder sweep: "
        f"sent={stats['sent']} failed={stats['failed']} deduped={stats['deduped']} "
        f"skipped_no_consent={stats['skipped_no_consent']} "
        f"skipped_optout={stats['skipped_optout']} "
        f"skipped_quiet={stats['skipped_quiet']} "
        f"skipped_no_phone={stats['skipped_no_phone']} "
        f"skipped_toggled_off={stats['skipped_toggled_off']}"
    )
    return stats
