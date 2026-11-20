"""payroll_reminders.py — the hourly nudge before a payroll date (Payroll, the free version, 2026-11-19).

Three days before an approve-by day, a tax deposit or a form's due date that
is still open, one alert goes to the people who work payroll at that church
or business: the owner, its Admins, and (with the giving tick switched on,
CHURCH_MONEY_TICKS) the logins the owner gave giving at Work, except that an
approve-by day goes only to those who can approve (the owner and Admins). An
IRS deposit's alert says EFTPS needs it by 8 p.m. Eastern the day before it's
due (Publication 15). The day before,
if it's still open, one more to the owner alone. Through the existing alert
path (a phone alert and an email to each person, as church_help._tell and
church_money_levels._tell send them).

    THE SWITCH ..... PAYROLL_REMINDERS = off | owner (the platform owner's
                     own church) | on (the default)
    NEVER TWICE .... each (business, key, audience) is claimed in
                     payroll_reminders_sent before its alert goes
                     (payroll_deposits.claim_reminder); a claim that fails
                     sends nothing, and the next hour tries again
    SKIPPED ........ sample churches, businesses with no runs since January
                     1 of last year, quiet hours (before 8 AM or from 9 PM
                     where the church is), and everything until the
                     migration is applied
    THE DATES ...... payroll_calendar.build_events, the calendar's own
                     events: a reminder and the page never disagree

Logs carry ids and counts only: never a name, an email or an amount.
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set
from urllib.parse import quote

import payroll_calendar as pcal
import payroll_deposits as pdep
import sb_clients

logger = logging.getLogger("payroll_reminders")

TEAM, OWNER = "team", "owner"
TEAM_DAYS = 3            # the team hears within three days of the date
QUIET_BEFORE, QUIET_FROM = 8, 21
NAV = "operate:pay-staff"


def mode() -> str:
    m = (os.environ.get("PAYROLL_REMINDERS") or "on").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def open_for(business_id: Any) -> bool:
    m = mode()
    if m == "on":
        return True
    if m == "owner":
        try:
            import member_asks
            return bool(member_asks.platform_church(business_id))
        except Exception:  # noqa: BLE001 — couldn't tell: nothing goes
            return False
    return False


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _zone(business_id: str):
    from zoneinfo import ZoneInfo
    try:
        import outside_calendar
        return ZoneInfo(outside_calendar.business_timezone(business_id) or "UTC")
    except Exception:  # noqa: BLE001 — the platform's clock, then
        return ZoneInfo("UTC")


def audience_for(days_left: int) -> Optional[str]:
    """Who hears about a date this many days away: the team within three
    days (not on the last day), the owner alone on the day before."""
    if days_left == 1:
        return OWNER
    if 1 < days_left <= TEAM_DAYS:
        return TEAM
    return None


def key_of(e: Dict[str, Any]) -> Optional[str]:
    if e.get("deposit_key"):
        return e["deposit_key"]
    if e["kind"] == "approve" and e.get("run_id"):
        return f"approve:{e['run_id']}"
    return None


def due_items(biz_row: Dict[str, Any], today: date) -> List[Dict[str, Any]]:
    """The open to-dos due within the next three days, each with its key and
    who should hear about it today."""
    rows = pcal.load(str(biz_row["id"]), *pcal.window(today, today + timedelta(days=TEAM_DAYS)))
    if not rows["runs"]:
        return []
    events = pcal.build_events(runs=rows["runs"], settings=pcal.settings_of(biz_row), marked=rows["marked"],
                               frequencies=rows["frequencies"], latest=rows["latest"],
                               start=today + timedelta(days=1), end=today + timedelta(days=TEAM_DAYS), today=today)
    out = []
    for e in events:
        if e["kind"] not in pcal.TO_DO or e["status"] != "open":
            continue
        key, who = key_of(e), audience_for((e["date"] - today).days)
        if key and who:
            out.append({**e, "key": key, "audience": who})
    return out


# ─── Who hears ────────────────────────────────────────────────────────

def team(biz_row: Dict[str, Any]) -> Set[str]:
    """The owner, the active Admin seats and, with the giving tick on for
    this church, the logins that hold it at Work."""
    return people(biz_row)[1]


def approvers(biz_row: Dict[str, Any]) -> Set[str]:
    """Who can approve a run (payroll_router.approve_run asks for an Admin):
    the owner and the active Admin seats. A Work tick marks deposits but
    doesn't approve, so it never hears about an approve-by day."""
    return people(biz_row)[0]


def people(biz_row: Dict[str, Any]):
    """(the approvers, the whole payroll team) at one business."""
    biz = str(biz_row["id"])
    out = {str(biz_row["owner_id"])} if biz_row.get("owner_id") else set()
    seats = sb_clients.sb_get_as_service(
        f"/business_users?business_id=eq.{_q(biz)}&status=eq.active&select=user_id,role&limit=200")
    for s in seats if isinstance(seats, list) else []:
        if s.get("role") == "admin" and s.get("user_id"):
            out.add(str(s["user_id"]))
    can_approve = set(out)
    try:
        import church_money_ticks as cmt
        if cmt.mode() != "off" and cmt.open_for(biz):
            for s in seats if isinstance(seats, list) else []:
                uid = str(s.get("user_id") or "")
                if uid and uid not in out:
                    t = cmt.holder(biz, uid)
                    if t and (t.get("can_work") is True or t.get("seat_role") == "admin"):
                        out.add(uid)
    except Exception:  # noqa: BLE001 — the owner and Admins still hear
        logger.warning("[payroll] reminders: the giving holders couldn't be read biz=%s", biz[:8])
    return can_approve, out


def _emails(biz_row: Dict[str, Any], to: Set[str]) -> Dict[str, str]:
    biz = str(biz_row["id"])
    out: Dict[str, str] = {}
    seats = sb_clients.sb_get_as_service(
        f"/business_users?business_id=eq.{_q(biz)}&status=eq.active&select=user_id,invited_email&limit=200")
    for s in seats if isinstance(seats, list) else []:
        if str(s.get("user_id")) in to:
            out[str(s["user_id"])] = str(s.get("invited_email") or "").strip()
    owner = str(biz_row.get("owner_id") or "")
    if owner in to:
        try:
            import messaging_router
            out[owner] = (messaging_router.owner_email_read(owner) or "").strip()
        except Exception:  # noqa: BLE001
            out[owner] = ""
    return out


# ─── The words ────────────────────────────────────────────────────────

def _sentence(s: str) -> str:
    s = (s or "").strip().rstrip(".")
    return f"{s[:1].upper()}{s[1:]}." if s else ""


def words(e: Dict[str, Any], church: bool, audience: str = TEAM) -> Dict[str, str]:
    """A title, a line, and a short form for a list, for one to-do. An IRS
    deposit says when EFTPS needs it: by 8 p.m. Eastern the day BEFORE the
    due date (IRS Publication 15, "How To Deposit"), so the owner's
    day-before alert says "today"."""
    when = pcal.day_words(e["date"])
    bank = "the church’s bank" if church else "your bank"
    tomorrow = audience == OWNER
    if e["kind"] == "approve":
        title = f"{e['title']} by {when}"
        return {"title": ("Tomorrow: " if tomorrow else "") + title, "line": f"{title}.",
                "body": "Approving two bank days before payday gives the bank time for direct deposit. Nothing "
                        f"moves until you pay from {bank}."}
    if e["kind"] == "deposit_federal":
        amt = pcal.money(e["amount"]) if e.get("amount") else ""
        about = _sentence(e.get("_for") or e["sub"])
        if tomorrow:
            title = f"Tomorrow: IRS deposit {amt}".strip()
            eftps = "Submit it on EFTPS today by 8 p.m. Eastern."
        else:
            title = f"IRS deposit due {when}" + (f": {amt}" if amt else "")
            eftps = pcal.eftps_words(e["date"])[:-1] + ", the day before it’s due."
        return {"title": title, "line": f"IRS deposit due {when}" + (f" ({amt})" if amt else "") + f". {eftps}",
                "body": f"{about} {eftps} Pay from {bank}, then mark it sent on Pay staff."}
    if e["kind"] == "deposit_state":
        amt = f": {pcal.money(e['amount'])}" if e.get("amount") else ""
        title = f"{e['title']} due {when}{amt}"
        return {"title": ("Tomorrow: " if tomorrow else "") + title, "line": f"{title}.",
                "body": f"{_sentence(e['sub'])} Pay it on your state’s site, then mark it sent on Pay staff."}
    title = f"{e['title']} due {when}"
    return {"title": ("Tomorrow: " if tomorrow else "") + title, "line": f"{title}.",
            "body": f"{_sentence(e['sub'])} Solutionist’s worksheet has the numbers; you or your accountant "
                    "file it."}


def message(items: List[Dict[str, Any]], audience: str, church: bool) -> Dict[str, str]:
    lines = [words(e, church, audience) for e in items]
    if len(lines) == 1:
        title, body = lines[0]["title"], lines[0]["body"]
    else:
        title = (f"Tomorrow: {len(lines)} payroll dates" if audience == OWNER
                 else f"{len(lines)} payroll dates in the next {TEAM_DAYS} days")
        body = " ".join(w["line"] for w in lines)
    return {"title": title[:150], "body": body}


def _tell(biz_row: Dict[str, Any], to: Set[str], title: str, body: str, tag: str) -> None:
    """A phone alert and an email to each person, off the sweep's thread;
    one that fails never stops the rest (church_help._tell's path)."""
    if not to:
        return
    emails = _emails(biz_row, to)
    biz = str(biz_row["id"])

    def run() -> None:
        import asyncio
        for uid in sorted(to):
            try:
                import push_notifications
                push_notifications.send_to_user(uid, title=title, body=body[:160], nav=NAV, tag=tag,
                                                business_id=biz)
            except Exception:  # noqa: BLE001
                logger.warning("[payroll] reminders: a phone alert failed biz=%s", biz[:8])
            email = emails.get(uid, "")
            if "@" not in email:
                continue
            try:
                import app_base
                import email_sender
                asyncio.run(email_sender.send_via_resend(
                    to_email=email, to_name=None,
                    from_email=os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app",
                    from_name=biz_row.get("name") or "Your church", subject=title[:150], reply_to=None,
                    business_id=biz, idempotency_key=f"{tag}-{uid}",
                    body=f"{title}\n\n{body}\n\nOpen Pay staff:\n{app_base.app_base_url()}/?nav={NAV}\n"))
            except Exception:  # noqa: BLE001
                logger.warning("[payroll] reminders: an email failed biz=%s", biz[:8])
    threading.Thread(target=run, daemon=True).start()


# ─── The sweep ────────────────────────────────────────────────────────

def _businesses(since: date) -> List[str]:
    """Every business with a non-cancelled run since `since`."""
    try:
        rows = sb_clients.sb_get_all_as_service(
            f"/pay_runs?status=neq.cancelled&pay_date=gte.{since.isoformat()}&select=id,business_id", strict=True)
    except sb_clients.PartialRead:
        return []
    return sorted({str(r["business_id"]) for r in rows or [] if r.get("business_id")})


def sweep(now: Optional[datetime] = None) -> Dict[str, Any]:
    """One hour's reminders. Returns counts."""
    out: Dict[str, Any] = {"businesses": 0, "alerts": 0, "items": 0}
    if mode() == "off":
        return {**out, "skipped": "off"}
    if not pdep.ready(pdep.DEPOSITS) or not pdep.ready(pdep.REMINDERS):
        return {**out, "skipped": "not_ready"}
    now = now or datetime.now(timezone.utc)
    ids = _businesses(date(now.year - 1, 1, 1))
    try:
        import sample_church
        ids = sample_church.drop_samples(ids)
    except Exception:  # noqa: BLE001 — couldn't tell which are samples: send nothing this hour
        return {**out, "skipped": "samples_unknown"}
    for biz in ids:
        if not open_for(biz):
            continue
        try:
            out["alerts"] += _one(biz, now, out)
        except Exception as e:  # noqa: BLE001 — one business never stops the rest
            logger.warning("[payroll] reminders failed biz=%s: %s", biz[:8], type(e).__name__)
    logger.info("[payroll] reminders businesses=%d alerts=%d items=%d", out["businesses"], out["alerts"],
                out["items"])
    return out


def _one(biz: str, now: datetime, stats: Dict[str, Any]) -> int:
    import church_follow_up
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(biz)}&select=id,name,type,owner_id,settings&limit=1")
    if not isinstance(rows, list) or not rows:
        return 0
    biz_row = rows[0]
    local = now.astimezone(_zone(biz))
    if not QUIET_BEFORE <= local.hour < QUIET_FROM:
        return 0
    today = local.date()
    items = due_items(biz_row, today)
    if not items:
        return 0
    stats["businesses"] += 1
    church = church_follow_up.is_church(biz_row)
    sent = 0
    for audience in (TEAM, OWNER):
        mine = []
        for e in items:
            if e["audience"] != audience:
                continue
            got = pdep.claim_reminder(biz, e["key"], audience, today)
            if got:
                mine.append(e)
        if not mine:
            continue
        stats["items"] += len(mine)
        # Who hears what: an approve-by day only those who can approve (the
        # owner, Admins); deposits and forms the whole payroll team. People
        # who'd hear the same things share one alert.
        if audience == TEAM:
            can_approve, everyone = people(biz_row)
            groups: Dict[tuple, Set[str]] = {}
            for uid in sorted(everyone):
                keys = tuple(e["key"] for e in mine if e["kind"] != "approve" or uid in can_approve)
                if keys:
                    groups.setdefault(keys, set()).add(uid)
        else:
            owner = str(biz_row.get("owner_id") or "")
            groups = {tuple(e["key"] for e in mine): {owner}} if owner else {}
        import hashlib
        for keys, to in groups.items():
            msg = message([e for e in mine if e["key"] in keys], audience, church)
            which = hashlib.sha1("|".join(sorted(keys)).encode()).hexdigest()[:10]
            _tell(biz_row, to, msg["title"], msg["body"], tag=f"payroll-{audience}-{today.isoformat()}-{which}")
            sent += 1
    return sent


async def tick() -> Dict[str, Any]:
    """Hourly on the scheduler's leader. Off: nothing is read."""
    if mode() == "off":
        return {"skipped": "off"}
    import asyncio
    try:
        return await asyncio.to_thread(sweep)
    except Exception as e:  # noqa: BLE001 — the next hour tries again
        logger.warning("[payroll] reminders sweep failed: %s", type(e).__name__)
        return {"error": type(e).__name__}
