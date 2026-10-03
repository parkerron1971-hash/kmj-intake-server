"""Account lifecycle emails: welcome, first-week guidance and trial notices.

Durable delivery claims and Resend idempotency protect retries. Legacy
business settings stamps remain readable and prevent historical resends.
Signup reminders require explicit business intent; all sending honors
LIFECYCLE_EMAILS and the shared suppression gate.
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

# stripe_subscription_id is load-bearing: a trial that began without a
# card and has since added one still carries the no-card marker, and only
# this column tells the two apart (no_card_trial.is_no_card) — without it
# the tank check would measure a carded trial against the no-card tank.
_BIZ_SELECT = ("id,name,type,owner_id,subscription_status,trial_ends_at,"
               "stripe_subscription_id,comp_tier,settings,created_at")


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
        f"this week. It plans, drafts and follows up with your approval.\n"
        f"   {app}/\n\n"
        f"{trial_line}Reply to this email if anything is unclear. A person "
        f"reads it.\n\n"
        f"The Solutionist System\n"
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
        f"end of the trial. Nothing is deleted. Your data stays available and "
        f"exportable, but Chief stops working until a plan is chosen.\n\n"
        f"Choose or confirm your plan here:\n"
        f"   {app}/?settings=billing\n\n"
        f"Not the right fit? Reply and let us know.\n\n"
        f"The Solutionist System\n"
        f"{_support_email()}"
    )


def trial_ended_body(*, business_name: str, first_name: str,
                     reason: str) -> str:
    app = app_base_url()
    if reason == "no_card_trial_expired":
        # The reverse trial: the workspace keeps working without a card;
        # Chief and the live site wait for one.
        return (
            f"Hi {first_name},\n\n"
            f"The free trial for {business_name} has ended, and your workspace "
            f"keeps working: contacts, bookings, invoices and your books are all "
            f"still yours to use.\n\n"
            f"Chief and your website are what wait for a card. Add one and both "
            f"come back where you left them:\n"
            f"   {app}/?settings=billing\n\n"
            f"If you would rather take your data with you, the export lives in "
            f"Settings → Your Data.\n\n"
            f"Questions, or a reason the trial didn't fit? Reply here.\n\n"
            f"The Solutionist System\n"
            f"{_support_email()}"
        )
    if reason == "no_card_credits_spent":
        # The no-card trial's tank ran dry with days left. The trial has
        # NOT ended: a card keeps its end date and adds the rest of the
        # full tank (no_card_trial.py), so this mail asks for the card.
        import pricing_config
        extra = max(0, pricing_config.trial_credits()
                    - pricing_config.trial_credits_no_card())
        more = f" and {extra:,} more credits" if extra else ""
        return (
            f"Hi {first_name},\n\n"
            f"You've used the free credits in the trial for {business_name} "
            f"before the week was out.\n\n"
            f"Add a card and Chief keeps going: the rest of your trial{more}, "
            f"and nothing is charged until the trial ends.\n"
            f"   {app}/?settings=billing\n\n"
            f"Everything you built is still there: contacts, bookings, "
            f"invoices, your site and Chief's notes.\n\n"
            f"Questions, or a reason the trial didn't fit? Reply here.\n\n"
            f"The Solutionist System\n"
            f"{_support_email()}"
        )
    why = ("You used the trial's full allowance of Chief work before the "
           "calendar ran out."
           if reason == "trial_credits_spent" else
           "The trial window has closed.")
    return (
        f"Hi {first_name},\n\n"
        f"The free trial for {business_name} has ended. {why}\n\n"
        f"Everything you built is still there: contacts, bookings, invoices, "
        f"and Chief's notes. Pick a plan and it is exactly where you "
        f"left it:\n"
        f"   {app}/?settings=billing\n\n"
        f"If you would rather take your data with you, the export lives in "
        f"Settings → Your Data, and it keeps working after the trial.\n\n"
        f"Questions, or a reason the trial didn't fit? Reply here.\n\n"
        f"The Solutionist System\n"
        f"{_support_email()}"
    )


# ─── Plumbing ────────────────────────────────────────────────────────

async def _send(*, to_email: str, to_name: Optional[str],
                subject: str, body: str, delivery_key: str) -> bool:
    from lifecycle_delivery import send_once
    await send_once(delivery_key, dict(
        to_email=to_email, to_name=to_name,
        from_email=_from_email(), from_name=FROM_NAME,
        subject=subject, body=body, reply_to=_support_email()))
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
        f"/businesses?id=eq.{business_id}&select=id,settings&limit=1")
    if not rows:
        raise RuntimeError("Cannot save lifecycle stamp without current business settings")
    settings = (rows[0].get("settings") if rows else None) or {}
    if not isinstance(settings, dict):
        settings = {}
    le = dict(settings.get(SETTINGS_KEY) or {})
    le[key] = _now().strftime("%Y-%m-%dT%H:%M:%SZ")
    settings[SETTINGS_KEY] = le
    result = sb_clients.sb_patch_as_service(f"/businesses?id=eq.{business_id}",
                                           {"settings": settings})
    if result is None:
        raise RuntimeError("Lifecycle send stamp was not saved")


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
            first = sb_clients.sb_get_as_service(
                f"/businesses?owner_id=eq.{owner_id}"
                f"&select=id&order=created_at.asc,id.asc&limit=1")
            if first is None:
                raise RuntimeError("Could not establish first business")
            if not first or str(first[0].get("id")) != biz_id:
                return {"sent": False, "reason": "not_first_business"}
        name = (business.get("name") or "Your business").strip()
        await _send(
            delivery_key=f"business/{biz_id}/welcome",
            to_email=to_email, to_name=user_name or None,
            subject=f"{name} is set up. Three moves for your first week",
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
                import no_card_trial
                return {"kind": "trial_ended",
                        "reason": ("no_card_credits_spent" if no_card_trial.is_no_card(row)
                                   else "trial_credits_spent")}
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
        return {"kind": "trial_ended", "reason": _expired_reason(row)}

    if status == "canceled" and ends is not None:
        # Stripe's end_behavior=cancel: the trial closed without a card.
        if stamps.get("trial_ended_at"):
            return None
        if ends > now or now - ends > timedelta(days=ENDED_LOOKBACK_DAYS):
            return None
        return {"kind": "trial_ended", "reason": _expired_reason(row)}
    return None


def _expired_reason(row: Dict[str, Any]) -> str:
    """A no-card trial's calendar end keeps a free workspace (the reverse
    trial), so its mail says what still works instead of "it ended"."""
    try:
        import no_card_trial
        import pricing_config
        if pricing_config.no_card_free_workspace() and no_card_trial.is_no_card(row):
            return "no_card_trial_expired"
    except Exception:
        pass
    return "trial_expired"


async def sweep_tick() -> Dict[str, Any]:
    """Hourly. Reads every active business that could be in or just past a
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
                    delivery_key=f"business/{row['id']}/{need['kind']}",
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
                    delivery_key=f"business/{row['id']}/{need['kind']}",
                    to_email=to, to_name=None,
                    subject=(f"Your {name} trial credits are used up. Add a card to keep going"
                             if need["reason"] == "no_card_credits_spent" else
                             f"Your {name} trial has ended. Your workspace keeps working"
                             if need["reason"] == "no_card_trial_expired" else
                             f"Your {name} trial has ended. Your work is still here"),
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


# ─── The week: day three and day seven ───────────────────────────────
#
# Wave C (2026-09-02). The welcome goes out on day one and the trial
# mail at the end; in between, nothing reached out, and nobody who
# signed up in August came back after day one. Two beats, each with ONE
# ask, each built from the practitioner's own setup state (the same
# plug-in probes Chief reads), so the email and Chief say the same thing.
#
#   day_three — "here is where you are; here is the one next thing"
#   day_seven — the share kit if their site is up; else the same shape
#               as day three, a week in.
#
# Any active business created in the window, whatever it pays (a comped
# account gets its first week too). Grandfathered owners are skipped like
# the trial mail. Stamped in settings.lifecycle_emails.<kind>_at.

DAY_THREE_FROM = 2.5   # days since creation
DAY_THREE_UNTIL = 5.0
DAY_SEVEN_FROM = 6.5
DAY_SEVEN_UNTIL = 9.0


def _age_days(row: Dict[str, Any], now: datetime) -> Optional[float]:
    created = _parse(row.get("created_at"))
    if not created:
        return None
    return (now - created).total_seconds() / 86400.0


def _classify_week(row: Dict[str, Any], now: datetime) -> Optional[str]:
    """Choose a first-week message only while the business retains full access."""
    import feature_gates
    if feature_gates.enforcement_on():
        state = feature_gates.access_state(row, trial_spent=_tank_spent(row))
        if state["state"] != "full":
            return None
    age = _age_days(row, now)
    if age is None:
        return None
    stamps = _stamps(row)
    if DAY_THREE_FROM <= age < DAY_THREE_UNTIL and not stamps.get("day_three_at"):
        return "day_three"
    if DAY_SEVEN_FROM <= age < DAY_SEVEN_UNTIL and not stamps.get("day_seven_at"):
        return "day_seven"
    return None


def _setup_state(row: Dict[str, Any]) -> Dict[str, Any]:
    """done / total / the next unblocked move, from the plug-in probes.
    Empty on failure — the email still goes, shorter."""
    try:
        import business_track_router as btr
        items = btr.resolve_plugins(row) or []
    except Exception as e:
        logger.warning(f"[lifecycle] plugins read failed: {e}")
        return {}
    undone = [p for p in items if not p.get("done")]
    nxt = next((p for p in undone if not (p.get("blocked_by") or [])), undone[0] if undone else None)
    return {"done": len(items) - len(undone), "total": len(items), "next": nxt}


def _site_link(row: Dict[str, Any]) -> Optional[str]:
    try:
        sites = sb_clients.sb_get_as_service(
            f"/business_sites?business_id=eq.{row['id']}&status=eq.published"
            f"&select=id,slug,site_config&limit=1") or []
        if not sites:
            return None
        import brand_engine
        return brand_engine.public_site_url(sites[0])
    except Exception as e:
        logger.warning(f"[lifecycle] site link failed: {e}")
        return None


def _email_sentence(value: Optional[str]) -> str:
    """Format optional setup descriptions as ordinary email prose."""
    import re
    return re.sub(r"\s*[—–]\s*", ", ", (value or "").strip())


def day_three_body(*, business_name: str, first_name: str,
                   done: int, total: int, next_title: Optional[str],
                   next_why: Optional[str]) -> str:
    app = app_base_url()
    where = (f"So far {done} of {total} pieces of {business_name} are plugged in."
             if total else f"{business_name} is set up and waiting for its first pieces.")
    if next_title:
        ask = (f"The one thing to do today: {next_title}.\n"
               f"{_email_sentence(next_why)}\n\n"
               f"Open Chief and say \"let's do this one.\" It walks you through the next step.\n"
               f"   {app}/")
    else:
        ask = (f"Everything on the list is connected. Open Chief and ask what "
               f"it would do this week.\n   {app}/")
    return (
        f"Hi {first_name},\n\n"
        f"Day three. {where}\n\n"
        f"{ask}\n\n"
        f"Spend twenty minutes with Chief when you have time so it can learn how you "
        f"actually run. You can work at your own pace.\n\n"
        f"The Solutionist System\n"
        f"{_support_email()}"
    )


def day_seven_body(*, business_name: str, first_name: str, site_url: Optional[str],
                   done: int, total: int, next_title: Optional[str]) -> str:
    app = app_base_url()
    if site_url:
        middle = (
            f"Your site is up: {site_url}\n\n"
            f"Send it to one person today: a regular, a friend who asks what you do, "
            f"or your group chat. Chief can write the message for you: "
            f"open it and say \"write a text sending my site to a regular.\"\n   {app}/"
        )
    elif next_title:
        middle = (
            f"{done} of {total} pieces are plugged in. The one that gets you a link you can "
            f"send someone: {next_title}. Open Chief and say \"let's do this one.\"\n   {app}/"
        )
    else:
        middle = f"Everything is connected. Open Chief and ask what it would do this week.\n   {app}/"
    return (
        f"Hi {first_name},\n\n"
        f"One week in with {business_name}.\n\n"
        f"{middle}\n\n"
        f"The Solutionist System\n"
        f"{_support_email()}"
    )


async def week_beats_tick() -> Dict[str, Any]:
    """Hourly. Every active business created in the last ten days gets its
    day-three and day-seven beats, once each. Never raises."""
    out: Dict[str, Any] = {"ok": True, "scanned": 0, "sent": 0, "skipped": 0,
                           "failed": 0, "sent_kinds": []}
    if not enabled():
        out["ok"] = False
        out["reason"] = "disabled"
        return out
    now = _now()
    since = (now - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        rows: List[Dict[str, Any]] = sb_clients.sb_get_as_service(
            f"/businesses?select={_BIZ_SELECT},stripe_account_id&is_active=eq.true"
            f"&created_at=gte.{since}&limit=1000") or []
    except Exception as e:
        logger.warning(f"[lifecycle] week sweep read failed: {e}")
        out["ok"] = False
        out["reason"] = f"read_failed: {str(e)[:120]}"
        return out

    for row in rows:
        out["scanned"] += 1
        try:
            kind = _classify_week(row, now)
            if not kind:
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
            first = _first_name(((row.get("settings") or {}).get("practitioner_name")) or None)
            st = _setup_state(row)
            nxt = st.get("next") or {}
            if kind == "day_three":
                await _send(
                    delivery_key=f"business/{row['id']}/{kind}",
                    to_email=to, to_name=None,
                    subject=f"Day three with {name}: one thing to do today",
                    body=day_three_body(business_name=name, first_name=first,
                                        done=int(st.get("done") or 0), total=int(st.get("total") or 0),
                                        next_title=nxt.get("title"), next_why=nxt.get("why")))
                _stamp(str(row["id"]), "day_three_at")
            else:
                site = _site_link(row)
                await _send(
                    delivery_key=f"business/{row['id']}/{kind}",
                    to_email=to, to_name=None,
                    subject=(f"One week in: send {name}'s site to one person" if site
                             else f"One week in with {name}"),
                    body=day_seven_body(business_name=name, first_name=first, site_url=site,
                                        done=int(st.get("done") or 0), total=int(st.get("total") or 0),
                                        next_title=nxt.get("title")))
                _stamp(str(row["id"]), "day_seven_at")
            out["sent"] += 1
            out["sent_kinds"].append(kind)
        except Exception as e:
            out["failed"] += 1
            logger.warning(f"[lifecycle] week beat failed biz={row.get('id')}: {e}")
    logger.info(f"[lifecycle] week beats scanned={out['scanned']} sent={out['sent']} "
                f"failed={out['failed']}")
    return out


async def welcome_retry_tick() -> Dict[str, Any]:
    """Recover interrupted/failed first-business welcomes, including restarts.

    The business row is the durable source. Only the first 72 hours are
    eligible, so installing this job does not email the historic customer list.
    """
    out = {"ok": True, "scanned": 0, "sent": 0, "failed": 0}
    if not enabled():
        return dict(out, ok=False, reason="disabled")
    since = (_now() - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        rows = sb_clients.sb_get_as_service(
            f"/businesses?select={_BIZ_SELECT}&is_active=eq.true"
            f"&created_at=gte.{since}&order=created_at.asc,id.asc&limit=1000")
        if rows is None:
            raise RuntimeError("Welcome candidate read failed")
        for row in rows:
            if _stamps(row).get("welcome_at"):
                continue
            out["scanned"] += 1
            result = await send_welcome(
                row, await _owner_email(str(row.get("owner_id") or "")),
                (row.get("settings") or {}).get("practitioner_name"))
            out["sent"] += int(bool(result.get("sent")))
            out["failed"] += int(result.get("reason") == "error")
    except Exception:
        logger.exception("[lifecycle] welcome recovery failed")
        out["ok"] = False
    return out


def signup_reminder_body(first_name: str, *, final: bool = False) -> str:
    intro = ("Your business setup is still waiting for you. This is our last setup reminder."
             if final else "Your account is ready. The next step is to finish setting up your business.")
    return (f"Hi {_first_name(first_name)},\n\n{intro}\n\n"
            "Sign in, tell us your name and what you do, and choose how you want Chief "
            "to communicate. You can continue here:\n"
            f"{app_base_url()}/\n\n"
            "If you need a hand, reply to this email and tell us where you got stuck.\n\n"
            f"The Solutionist System\n{_support_email()}")


async def signup_reminders_tick() -> Dict[str, Any]:
    """Two setup reminders at day one/day three, only for business intent.

    The SQL eligibility check excludes unverified, invited, banned, staff,
    grandfathered and business-owning accounts. It stops after seven days.
    It is checked again immediately before a send, after enumeration.
    """
    from lifecycle_delivery import rpc
    out = {"ok": True, "scanned": 0, "sent": 0, "failed": 0}
    if not enabled():
        return dict(out, ok=False, reason="disabled")
    try:
        rows = rpc("lifecycle_signup_candidates", {})
        for row in rows:
            out["scanned"] += 1
            try:
                current = rpc("lifecycle_signup_candidates", {"p_user_id": row["user_id"]})
                if not current:
                    continue
                recipient = current[0]
                kind = recipient["kind"]
                await _send(
                    delivery_key=f"signup/{recipient['user_id']}/{kind}",
                    to_email=recipient["email"], to_name=None,
                    subject=("Ready to finish setting up your business?" if kind == "signup_day_one"
                             else "Your business setup is here when you are ready"),
                    body=signup_reminder_body(recipient.get("first_name") or "",
                                             final=kind == "signup_day_three"))
                out["sent"] += 1
            except Exception:
                out["failed"] += 1
                logger.exception("[lifecycle] setup reminder failed")
    except Exception:
        out["ok"] = False
        logger.exception("[lifecycle] setup reminder sweep failed")
    return out
