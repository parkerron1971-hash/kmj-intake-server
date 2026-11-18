"""care_handoff.py — a Prayer & care request handed to an office login: the
heads-up, the due time, and nobody waits.

Kevin, 2026-11-18: "build the heads-up and due time for logins". A hand-off
to a login showed only on that login's My week: nobody was told, nothing
was due, nobody heard when it waited. A hand-off to the prayer team
(church_prayer) already had all three; this gives a login's the same.

    handed on ......... private_care.update_request stamps assigned_due_at a
                        day out and clears the rest (a hand-off back to the
                        one who handed it, or taken back, clears it all)
    the heads-up ...... the login hears once (assigned_told_at): a push to the
                        office app and an email. Two minutes after the
                        hand-off, so an Undo on the desk tells nobody, and
                        outside the church's quiet hours, except a request
                        that needs a pastor, which goes at once
    a first step ...... a note, "I'm on it", marked prayed or done
                        (assigned_acted_at, private_care). Nothing is late
                        after it
    nobody waits ...... when it's due, the login is reminded; a day late, the
                        one who handed it to them hears; three days late, the
                        office's alerts ask to hand it to someone else. Never
                        in quiet hours

WHAT A NOTICE SAYS. That a request is theirs, who handed it, and when it's
due. Never the request's words, the person's name or what kind of request
it is: a lock screen and an inbox are not private, and Prayer & care asks
for a password to open. The sweep never reads `submission`, so nothing
below this line can say it.

TOLD ONCE. Every notice is a claim first: an update of assigned_told_at
(or assigned_late_level) that lands only while the mark is as it was read
and the request is still with the same login, so one caller wins. It is
let go when nothing could be sent, and the next sweep tries again.

CARE_HEADS_UP=off is the rollback: nothing is sent and nothing is claimed.
Due times are still set and shown on the desk.

Every five minutes, on the worker (kmj_intake_automation). Before
supabase/APPLY-2026-11-18-care-login-due.sql the reads fail and the sweep
does nothing.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import HTTPException

import sb_clients

logger = logging.getLogger("care_handoff")

DUE_DAYS = 1
SETTLE_SECONDS = 120          # an Undo on the desk lands well inside this
# (days past due, level, kind): the prayer team's ladder (church_prayer.LATE_LADDER)
LATE_LADDER = ((0, 1, "nudged"), (1, 2, "handed_by_told"), (3, 3, "office_asked"))
NAV = "operate:care"
OFFICE = "The church office"
LIMIT = 200
FIELDS = ("id,business_id,assigned_to,assigned_by,assigned_at,assigned_due_at,assigned_told_at,"
          "assigned_late_level,needs_pastor")


def mode() -> str:
    return "off" if (os.environ.get("CARE_HEADS_UP") or "on").strip().lower() == "off" else "on"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _parse(ts: Any) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def due_from(now: datetime) -> str:
    """When a hand-off made now owes its first step."""
    return _iso(now + timedelta(days=DUE_DAYS))


def late_step(row: Dict[str, Any], now: datetime) -> Optional[tuple]:
    """The highest rung this request has reached and not yet climbed:
    (level, kind), or None."""
    due = _parse(row.get("assigned_due_at"))
    if not due or now < due:
        return None
    level = int(row.get("assigned_late_level") or 0)
    best = None
    for days, lvl, kind in LATE_LADDER:
        if now >= due + timedelta(days=days) and lvl > level:
            best = (lvl, kind)
    return best


# ─── Words ────────────────────────────────────────────────────────────

def at_words(ts: Any, biz: Dict[str, Any], now: Optional[datetime] = None) -> str:
    """A time as a notice says it, in the church's own zone: "today 6:30 PM",
    "tomorrow 9:15 AM", "Thu 9:15 AM"."""
    dt = _parse(ts)
    if not dt:
        return "soon"
    try:
        import business_marketing
        zone = business_marketing.business_tz(biz)
        dt, today = dt.astimezone(zone), (now or _now()).astimezone(zone).date()
    except Exception:
        today = (now or _now()).date()
    clock = dt.strftime("%I:%M %p").lstrip("0")
    if dt.date() == today:
        return f"today {clock}"
    if dt.date() == today + timedelta(days=1):
        return f"tomorrow {clock}"
    return f"{dt.strftime('%a')} {clock}"


def told_words(by: str, due: str, crisis: bool, first: str) -> Dict[str, str]:
    title = "A request that needs a pastor is yours" if crisis else "A Prayer & care request is yours"
    hello = f"Hi {first}," if first and first != OFFICE else "Hello,"
    return {
        "hello_name": first if first and first != OFFICE else "the login", "due": due,
        "title": title,
        "body": f"{by} handed it to you. A first step is due {due}.",
        "subject": title,
        "text": "\n\n".join([
            hello,
            f"{by} handed you a request in Prayer & care. It’s private, so it isn’t in this email. "
            "Open Prayer & care to read it.",
            f"A first step is due {due}: a note, “I’m on it”, or marking it prayed or done.",
            f"If it waits, you’ll get a reminder when it’s due, and a day later {by} will hear.",
        ]),
    }


def nudge_words(by: str, first: str) -> Dict[str, str]:
    hello = f"Hi {first}," if first and first != OFFICE else "Hello,"
    return {
        "title": "A Prayer & care request is due",
        "body": f"The request {by} handed you is due now. A note or “I’m on it” answers it.",
        "subject": "A Prayer & care request is due",
        "text": "\n\n".join([
            hello,
            f"The request {by} handed you in Prayer & care is due now, and nobody has taken a first step yet.",
            "A note, “I’m on it”, or marking it prayed or done answers it. If it isn’t yours to take, "
            "give it back from the same page.",
        ]),
    }


def late_words(holder: str, late: str, asked: bool) -> Dict[str, str]:
    title = "Hand a care request to someone else?" if asked else "A care request is waiting"
    return {
        "title": title,
        "body": f"The request you handed {holder} has waited {late} past due.",
        "subject": title,
        "text": "\n\n".join([
            "Hello,",
            f"The Prayer & care request you handed {holder} has waited {late} past due, with no first step yet.",
            "Check in with them, or hand it to someone else from Prayer & care."
            + (" The office’s alerts have the same question." if asked else ""),
        ]),
    }


# ─── Sending ──────────────────────────────────────────────────────────

def _link() -> str:
    import app_base
    return f"{app_base.app_base_url()}/?nav={NAV}"


def _called(ch: Any, uid: str) -> str:
    """A login by a name a notice can say (the leaders schedule's rule): a
    first name, the owner by the church's name for them, else the office."""
    try:
        import church_schedule_tell as cst
        return cst._login_called(ch, uid)
    except HTTPException:
        return OFFICE
    except Exception:  # noqa: BLE001
        logger.info("care hand-off: a name couldn't be read", exc_info=True)
        return OFFICE


def _is_login(ch: Any, uid: str) -> bool:
    """Still the owner or an active seat. A read that fails is a 503."""
    return bool(uid) and (uid == ch.owner or uid in ch.seats)


def tell(ch: Any, uid: str, words: Dict[str, str], ref: str) -> bool:
    """One notice to one office login: a push to the office app and an email
    to its sign-in address. True when either went. An address that couldn't
    be read sends nothing, so the caller claims nothing. Never raises."""
    import church_assignments as cas
    import church_leader_tasks as clt
    import church_office_tasks as cot
    try:
        email = cas._login_email(ch, uid)
    except Exception:  # noqa: BLE001
        email = None
    if email is None:
        return False
    rang = 0
    try:
        import push_notifications
        rang = push_notifications.send_to_user(uid, title=words["title"][:80], body=words["body"][:160], nav=NAV,
                                               tag=ref[:60], business_id=ch.b)
    except Exception:  # noqa: BLE001
        logger.info("care hand-off: a push didn't go (business %s)", ch.b[:8], exc_info=True)
    mailed = False
    if email:
        try:
            html = cot.render(ch.business, words["text"], words["title"], _link(), "Open Prayer & care")
            clt.deliver(ch.business, email, "", words["subject"], html, ref, reply_to=clt._office_email(ch.business))
            mailed = True
        except Exception:  # noqa: BLE001
            logger.warning("care hand-off: an email didn't go (business %s)", ch.b[:8], exc_info=True)
    return bool(rang) or mailed


def office_alert(biz_id: str, title: str, body: str, key: str) -> bool:
    """The office's alerts (deduplicated on `key` for a week). True when it
    was raised or already stands."""
    async def go() -> None:
        import httpx
        import notification_engine
        async with httpx.AsyncClient(timeout=20) as client:
            await notification_engine.create_urgent_alert(
                client, biz_id, title, body, dedup_key=key, dedup_hours=24 * 7,
                suggested_action="Open Prayer & care")
    try:
        asyncio.run(go())
        return True
    except Exception:  # noqa: BLE001
        logger.warning("care hand-off: an office alert failed (business %s)", biz_id[:8], exc_info=True)
        return False


# ─── The claim ────────────────────────────────────────────────────────

def _claim(row: Dict[str, Any], patch: Dict[str, Any], guard: str) -> bool:
    """Take this notice while the request is as it was read: still with the
    same login, handed at the same moment, no first step (`guard` adds the
    mark's own state). One caller wins."""
    got = sb_clients.sb_patch_as_service(
        f"/ministry_care_requests?id=eq.{_q(row['id'])}&business_id=eq.{_q(row['business_id'])}"
        f"&assigned_to=eq.{_q(row['assigned_to'])}&assigned_at=eq.{_q(row['assigned_at'])}"
        f"&assigned_acted_at=is.null{guard}&select=id", patch)
    return isinstance(got, list) and bool(got)


def _release(row: Dict[str, Any], patch: Dict[str, Any], guard: str) -> None:
    try:
        sb_clients.sb_patch_as_service(
            f"/ministry_care_requests?id=eq.{_q(row['id'])}&business_id=eq.{_q(row['business_id'])}"
            f"&assigned_to=eq.{_q(row['assigned_to'])}{guard}&select=id", patch)
    except Exception:  # noqa: BLE001
        logger.warning("care hand-off: a claim wasn't let go (request %s)", str(row.get("id"))[:8], exc_info=True)


# ─── The sweep ────────────────────────────────────────────────────────

def _open() -> str:
    """Neither finished nor taken back: the filter every read carries."""
    return "&assigned_to=not.is.null&prayed_at=is.null&status=neq.closed"


def _rows(path: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(path)
    return rows if isinstance(rows, list) else None


def sweep_tick(now: Optional[datetime] = None) -> Dict[str, int]:
    stats = {"told": 0, "nudged": 0, "handed_by_told": 0, "office_asked": 0, "held": 0, "unsent": 0, "gone": 0}
    if mode() == "off":
        return stats
    now = now or _now()
    import sample_church
    skip = sample_church.exclude()
    settled = _iso(now - timedelta(seconds=SETTLE_SECONDS))
    untold = _rows(f"/ministry_care_requests?assigned_told_at=is.null&assigned_due_at=not.is.null"
                   f"&assigned_acted_at=is.null&assigned_at=lt.{_q(settled)}{_open()}&select={FIELDS}"
                   f"&order=assigned_at.asc&limit={LIMIT}{skip}")
    late = _rows(f"/ministry_care_requests?assigned_told_at=not.is.null&assigned_acted_at=is.null"
                 f"&assigned_late_level=lt.3&assigned_due_at=lt.{_q(_iso(now))}{_open()}&select={FIELDS}"
                 f"&order=assigned_due_at.asc&limit={LIMIT}{skip}")
    if untold is None and late is None:
        return stats   # before the migration, or the database didn't answer
    by_biz: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for key, rows in (("untold", untold or []), ("late", late or [])):
        for r in sample_church.drop_samples(rows):
            by_biz.setdefault(str(r["business_id"]), {"untold": [], "late": []})[key].append(r)
    for biz_id, todo in by_biz.items():
        try:
            _sweep_church(biz_id, todo, now, stats)
        except Exception:  # noqa: BLE001 — one church never stops the rest
            logger.warning("care hand-off sweep failed for business %s", biz_id[:8], exc_info=True)
    if any(stats.values()):
        print(f"[care_handoff] {stats}", flush=True)
    return stats


def _sweep_church(biz_id: str, todo: Dict[str, List[Dict[str, Any]]], now: datetime,
                  stats: Dict[str, int]) -> None:
    import church_over as co
    import member_push
    got = _rows(f"/businesses?id=eq.{_q(biz_id)}&select=id,name,type,owner_id,settings&limit=1")
    if not got:
        return
    biz = got[0]
    ch = co.Church(biz)
    quiet = member_push.quiet_hour(biz, now)
    for r in todo["untold"]:
        if quiet and not r.get("needs_pastor"):
            stats["held"] += 1
            continue
        _tell_new(ch, r, now, stats)
    for r in todo["late"]:
        rung = late_step(r, now)
        if not rung:
            continue
        if quiet:
            stats["held"] += 1
            continue
        _climb(ch, r, rung, now, stats)


def _tell_new(ch: Any, r: Dict[str, Any], now: datetime, stats: Dict[str, int]) -> None:
    uid, by_id = str(r["assigned_to"]), str(r.get("assigned_by") or "")
    stamp = _iso(now)
    guard = "&assigned_told_at=is.null"
    if uid == by_id:
        # Handed to themselves (a keeper taking one): nobody to tell.
        _claim(r, {"assigned_told_at": stamp}, guard)
        return
    if not _is_login(ch, uid):
        # The login left the office: the office hears instead, once.
        if not _claim(r, {"assigned_told_at": stamp}, guard):
            return
        if office_alert(ch.b, "A care request is with someone who left",
                        "A Prayer & care request was handed to a login that is no longer on the team. "
                        "Hand it to someone else.", f"care-gone-{r['id']}"):
            stats["gone"] += 1
        else:
            _release(r, {"assigned_told_at": None}, f"&assigned_told_at=eq.{_q(stamp)}")
            stats["unsent"] += 1
        return
    if not _claim(r, {"assigned_told_at": stamp}, guard):
        return
    words = told_words(_called(ch, by_id) if by_id else OFFICE, at_words(r.get("assigned_due_at"), ch.business, now),
                       bool(r.get("needs_pastor")), _called(ch, uid))
    if tell(ch, uid, words, f"care-told-{r['id']}-{r.get('assigned_at')}"):
        stats["told"] += 1
        try:
            import church_history
            church_history.note(ch.b, "church:care_told",
                                f"Told {words['hello_name']} a Prayer & care request is theirs, due {words['due']}",
                                target_type="care_request", target_id=str(r["id"]))
        except Exception:  # noqa: BLE001
            logger.info("care hand-off: history line skipped", exc_info=True)
    else:
        _release(r, {"assigned_told_at": None}, f"&assigned_told_at=eq.{_q(stamp)}")
        stats["unsent"] += 1


def _climb(ch: Any, r: Dict[str, Any], rung: tuple, now: datetime, stats: Dict[str, int]) -> None:
    level, kind = rung
    was = int(r.get("assigned_late_level") or 0)
    uid, by_id = str(r["assigned_to"]), str(r.get("assigned_by") or "")
    if not _claim(r, {"assigned_late_level": level}, f"&assigned_late_level=eq.{was}"):
        return
    due = r.get("assigned_due_at")
    sent = False
    if kind == "nudged":
        if _is_login(ch, uid):
            sent = tell(ch, uid, nudge_words(_called(ch, by_id) if by_id else OFFICE, _called(ch, uid)),
                        f"care-due-{r['id']}-{due}")
        else:
            sent = True    # nobody to remind; the next rung tells whoever handed it
    else:
        holder = _called(ch, uid) if _is_login(ch, uid) else "someone who has left"
        if holder == OFFICE:
            holder = "a teammate"
        asked = kind == "office_asked"
        words = late_words(holder, "three days" if asked else "a day", asked)
        # Whoever handed it, while they're still on the team; else the owner.
        to = by_id if by_id and by_id != uid and _is_login(ch, by_id) else ch.owner
        told = bool(to) and to != uid and tell(ch, to, words, f"care-{kind}-{r['id']}-{due}-{to}")
        if asked:
            alerted = office_alert(ch.b, words["title"],
                                   f"A Prayer & care request has waited three days past due with {holder}, "
                                   "with no first step yet.", f"care-asked-{r['id']}-{due}")
            sent = alerted
        else:
            sent = told
    if sent:
        stats[kind] += 1
        try:
            import church_history
            line = {"nudged": "Reminded the login a Prayer & care request was handed to: it’s due",
                    "handed_by_told": "A Prayer & care request handed to a login waited a day past due: "
                                      "told whoever handed it",
                    "office_asked": "A Prayer & care request handed to a login waited three days past due: "
                                    "asked the office to hand it on"}[kind]
            church_history.note(ch.b, "church:care_late", line, target_type="care_request", target_id=str(r["id"]))
        except Exception:  # noqa: BLE001
            logger.info("care hand-off: history line skipped", exc_info=True)
    else:
        _release(r, {"assigned_late_level": was}, f"&assigned_late_level=eq.{level}")
        stats["unsent"] += 1
