"""
church_shepherd_signals.py — what Chief watches for every shepherded
family, and who is told (canvas 31su6kdYmYecH5b2NxjBJN, board 4).

Kevin, 2026-10-17: drifting is judged on Sundays only, never giving; any
attendance counts (checked in at church, at the Kids kiosk as the parent,
on their phone, or "I'm here" online); nobody is flagged in the first
month. Then the late chain the church already uses, applied to shepherds.

  Drifting       a family with a shepherd missed the 3 newest recorded
                 Sundays AND came to at least 2 of the (up to) 6 recorded
                 Sundays before them. A recorded Sunday is a date on the
                 church's check-in weekday that has any attendance at all:
                 a Sunday nobody recorded (check-in was off) is nobody's
                 miss. Fewer than 5 recorded Sundays: nobody drifts.
  Who is told    the shepherd, in Monday's email. A week with no call,
                 visit, text or talk logged since the first missed Sunday:
                 the person the shepherd answers to (church_roles.
                 chain_above, vacant roles passed over). A week more: one
                 step up. It stops at the top. They come back to church:
                 resolved.
  Birthdays      this week's, in the shepherd's Monday email (a child by
                 first name only).
  A care need    a card handed to the Deacons or the Care team for someone
                 in a shepherded family: the shepherd hears the same hour
                 that it's in hand, never the card's words.
  The brief      the Lead Pastor, on Monday, only when something needs them.

Every email is sent once (church_shepherd_notices). The sweep runs hourly
(kmj_intake_automation); the Monday part once a week per church, at or
after 7:00 on the church's clock.

  drift(days, here)                the rule, pure
  recorded(biz)                    the church's recorded Sundays and who came
  sweep / run_church               the hourly job
  office_view(biz, ctx)            the drift numbers Shepherding shows
  family_extras(biz, family)       a family page's drift tag and care lines
  chief_lines(biz, name)           what Chief answers about shepherding
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote
from zoneinfo import ZoneInfo

import sb_clients

logger = logging.getLogger("church_shepherd_signals")

MISSED = 3           # Sundays in a row
GUARD_SPAN = 6       # the Sundays before those
GUARD_MIN = 2        # …of which they came to at least this many
WINDOW_WEEKS = 12
MONDAY_HOUR = 7
CLIMB_AFTER = timedelta(days=6, hours=12)
CARE_LOOKBACK = timedelta(days=3)
LONG_DAYS = 60
BRIEF_UNREACHED = 3
OFFICE_LINK = "https://system.mysolutionist.app/#/operate/shepherding"
_CHUNK = 100


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _plain(v: Any) -> str:
    return " ".join(str(v or "").split())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse(ts: Any) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _day(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _rows(path: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(path)
    return rows if isinstance(rows, list) else None


def _chunks(ids: List[str]) -> List[List[str]]:
    return [ids[i:i + _CHUNK] for i in range(0, len(ids), _CHUNK)]


def label(d: Optional[date]) -> str:
    """'Sept 28', the way the boards say a date."""
    if not d:
        return ""
    month = "Sept" if d.month == 9 else d.strftime("%b")
    return f"{month} {d.day}"


# ─── the rule ─────────────────────────────────────────────────────────

def drift(days: List[date], here: Iterable[date]) -> Optional[Dict[str, Any]]:
    """Given the church's recorded Sundays (newest first) and the ones a
    family came to: {'since': the first Sunday of the three missed,
    'last_seen': the newest Sunday they came} when they are drifting,
    else None."""
    came = set(here)
    if len(days) < MISSED + GUARD_MIN:
        return None
    recent, before = days[:MISSED], days[MISSED:MISSED + GUARD_SPAN]
    if any(d in came for d in recent):
        return None
    if sum(1 for d in before if d in came) < GUARD_MIN:
        return None
    seen = [d for d in days if d in came]
    return {"since": recent[-1], "last_seen": seen[0] if seen else None}


# ─── who came, on which Sunday ────────────────────────────────────────

def sunday_rule(biz: Dict[str, Any]) -> Optional[Tuple[ZoneInfo, int]]:
    """The church's clock and its service weekday (church_checkin's
    settings; Sunday on the church's own time zone, else New York)."""
    import church_checkin as cck
    st = cck.settings(biz)
    if st is None:
        return None
    tz = cck._zone(st.get("timezone") or "") or ZoneInfo("America/New_York")
    return tz, int(st.get("weekday", 6))


def _entry_days(b: str, rows: List[Dict[str, Any]], tz: ZoneInfo) -> Optional[Dict[str, Optional[date]]]:
    """Each attendance row's occasion, as the day it was for: a check-in
    occasion's own `_checkin_day`, else the day its first check-in landed.
    A class night (academy_class_nights) is None: counted in attendance,
    never a Sunday to this rule (Kevin 2026-10-18, "Count class nights")."""
    first: Dict[str, datetime] = {}
    for r in rows:
        eid = str(r.get("entry_id") or "")
        at = _parse(r.get("checked_in_at"))
        if eid and at and (eid not in first or at < first[eid]):
            first[eid] = at
    out: Dict[str, Optional[date]] = {}
    for chunk in _chunks(sorted(first)):
        got = _rows(f"/module_entries?business_id=eq.{_q(b)}&id=in.({','.join(_q(i) for i in chunk)})&select=id,data")
        if got is None:
            return None
        for e in got:
            data = e.get("data") if isinstance(e.get("data"), dict) else {}
            if data.get("_class_session"):
                out[str(e["id"])] = None
                continue
            d = _day(data.get("_checkin_day"))
            if d:
                out[str(e["id"])] = d
    for eid, at in first.items():
        out.setdefault(eid, at.astimezone(tz).date())
    return out


def _attended(b: str, rows: List[Dict[str, Any]], tz: ZoneInfo, weekday: int,
              today: date) -> Optional[Tuple[List[date], Dict[str, Set[date]]]]:
    days_of = _entry_days(b, rows, tz)
    if days_of is None:
        return None
    days: Set[date] = set()
    seen: Dict[str, Set[date]] = {}
    for r in rows:
        eid = str(r.get("entry_id") or "")
        at = _parse(r.get("checked_in_at"))
        d = days_of.get(eid) if eid else (at.astimezone(tz).date() if at else None)
        if not d or d.weekday() != weekday or d > today:
            continue
        days.add(d)
        if r.get("contact_id"):
            seen.setdefault(str(r["contact_id"]), set()).add(d)
    return sorted(days, reverse=True), seen


def recorded(biz: Dict[str, Any], *, now: Optional[datetime] = None,
             rule: Optional[Tuple[ZoneInfo, int]] = None) -> Optional[Dict[str, Any]]:
    """{'days': recorded Sundays newest first (12 weeks), 'seen': contact
    id → the Sundays they came, 'tz', 'weekday'}. None when a read failed."""
    now = now or _now()
    rule = rule or sunday_rule(biz)
    if rule is None:
        return None
    tz, weekday = rule
    b = str(biz["id"])
    cutoff = _iso(now - timedelta(weeks=WINDOW_WEEKS, days=1))
    rows = _rows(f"/attendance?business_id=eq.{_q(b)}&checked_in_at=gte.{_q(cutoff)}"
                 "&select=entry_id,contact_id,checked_in_at&limit=50000")
    if rows is None:
        return None
    got = _attended(b, rows, tz, weekday, now.astimezone(tz).date())
    if got is None:
        return None
    return {"days": got[0], "seen": got[1], "tz": tz, "weekday": weekday}


def last_here(biz: Dict[str, Any], contact_ids: List[str], *, now: Optional[datetime] = None) -> Tuple[bool, Optional[date]]:
    """(read ok, the newest Sunday any of these people came) — one family's
    attendance only, for its page."""
    now = now or _now()
    rule = sunday_rule(biz)
    ids = [i for i in contact_ids if i]
    if rule is None:
        return False, None
    if not ids:
        return True, None
    tz, weekday = rule
    b = str(biz["id"])
    cutoff = _iso(now - timedelta(weeks=WINDOW_WEEKS, days=1))
    rows = _rows(f"/attendance?business_id=eq.{_q(b)}&contact_id=in.({','.join(_q(i) for i in ids)})"
                 f"&checked_in_at=gte.{_q(cutoff)}&select=entry_id,contact_id,checked_in_at&limit=2000")
    if rows is None:
        return False, None
    got = _attended(b, rows, tz, weekday, now.astimezone(tz).date())
    if got is None:
        return False, None
    return True, (got[0][0] if got[0] else None)


def _family_people(ctx: Dict[str, Any], hid: str) -> List[str]:
    return ctx["adults_of"].get(hid, []) + [str(k["contact_id"]) for k in ctx["kids_of"].get(hid, [])
                                             if k.get("contact_id")]


def open_signals(b: str) -> Optional[Dict[str, Dict[str, Any]]]:
    rows = _rows(f"/church_shepherd_signals?business_id=eq.{_q(b)}&kind=eq.drift&resolved_at=is.null"
                 "&select=id,household_id,started_on,last_seen,level,told_at&limit=10000")
    if rows is None:
        return None
    return {str(r["household_id"]): r for r in rows}


def _chain(ctx: Dict[str, Any], sid: str) -> List[Tuple[Dict[str, Any], List[Dict[str, Any]]]]:
    import church_roles as cr
    s = ctx["shepherds"].get(sid)
    if not s:
        return []
    return cr.chain_above(s["role_def"], ctx["defs"], ctx["holders"], skip=[sid])


def told_name(ctx: Dict[str, Any], sid: str, level: int) -> str:
    """Who heard last: the shepherd at level 0, then each step up."""
    if level <= 0:
        return ctx["shepherds"].get(sid, {}).get("name") or ""
    chain = _chain(ctx, sid)
    if not chain:
        return ""
    _role, people = chain[min(level, len(chain)) - 1]
    return " and ".join(_plain(p.get("name")) for p in people[:2] if p.get("name"))


def _reached_since(ctx: Dict[str, Any], hid: str, since: date, tz: ZoneInfo) -> bool:
    t = ctx["last_touch"].get(hid)
    at = _parse((t or {}).get("created_at"))
    return bool(at and at.astimezone(tz).date() >= since)


# ─── the office's numbers ─────────────────────────────────────────────

def office_view(biz: Dict[str, Any], ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """What Shepherding adds from the signals: who is drifting (as told),
    how many Sundays are recorded, and the families not reached in 60 days.
    None when a read failed."""
    import church_shepherding as shep
    b = str(biz["id"])
    rec = recorded(biz, now=ctx["now"])
    opens = open_signals(b)
    if rec is None or opens is None:
        return None
    by_household: Dict[str, Dict[str, Any]] = {}
    drifting: List[Dict[str, Any]] = []
    long_ = 0
    for u in ctx["units"]:
        hid = u["household_id"]
        sid = shep._placed(ctx, u)
        if not sid:
            continue
        sig = opens.get(hid)
        if sig:
            level = int(sig.get("level") or 0)
            row = {"since": sig.get("started_on"), "last_seen": sig.get("last_seen"), "level": level}
            by_household[hid] = row
            drifting.append({"household_id": hid, "name": u["name"], "shepherd_contact_id": sid,
                             "shepherd_name": ctx["shepherds"][sid]["name"], "since": sig.get("started_on"),
                             "last_seen": sig.get("last_seen"), "level": level, "told": told_name(ctx, sid, level)})
        t = ctx["last_touch"].get(hid)
        at = _parse((t or {}).get("created_at")) or _parse(ctx["assigned"][hid].get("assigned_at"))
        if at and ctx["now"] - at > timedelta(days=LONG_DAYS):
            long_ += 1
    drifting.sort(key=lambda d: (str(d["since"] or ""), d["name"].casefold()))
    return {"by_household": by_household, "drifting": drifting, "sundays_recorded": len(rec["days"]),
            "not_reached_60": long_}


# ─── a family's page ──────────────────────────────────────────────────

def _role_titles(b: str) -> Dict[str, str]:
    rows = _rows(f"/church_role_defs?business_id=eq.{_q(b)}&select=key,title&limit=500") or []
    return {str(r["key"]): _plain(r.get("title")) for r in rows}


def care_lines(b: str, contact_ids: List[str]) -> Optional[List[str]]:
    """One line per open card on this family's people that a shepherd may
    know about: a care need is in someone's hands; a pastor has one. Never
    the card's words."""
    import church_follow_up as cfu
    ids = [i for i in contact_ids if i]
    if not ids:
        return []
    fus = _rows(f"/church_follow_ups?business_id=eq.{_q(b)}&contact_id=in.({','.join(_q(i) for i in ids)})"
                "&status=in.(open,handed_back)&select=id,leader_contact_id,leader_role,path_kind,answers,created_at"
                "&order=created_at.asc&limit=200")
    if fus is None:
        return None
    lines: List[str] = []
    titles: Optional[Dict[str, str]] = None
    names: Dict[str, str] = {}
    pastor = False
    for f in fus:
        stream, _why = cfu.stream_for(f.get("path_kind") or "", f.get("answers") or [])
        if stream == "pastor_ask":
            pastor = True
        elif stream == "care_need":
            if titles is None:
                titles = _role_titles(b)
                lids = sorted({str(x["leader_contact_id"]) for x in fus if x.get("leader_contact_id")})
                if lids:
                    ppl = _rows(f"/contacts?business_id=eq.{_q(b)}&id=in.({','.join(_q(i) for i in lids)})&select=id,name")
                    names = {str(p["id"]): _plain(p.get("name")) for p in ppl or []}
            who = _holder_words(f, titles, names)
            when = _parse(f.get("created_at"))
            lines.append(f"{who} has a care need for this family since {label(when.date() if when else None)}. "
                         "It’s in hand; the card’s words stay with them.")
    if pastor:
        lines.append("A pastor has this one.")
    return lines


def _holder_words(f: Dict[str, Any], titles: Dict[str, str], names: Dict[str, str]) -> str:
    name = names.get(str(f.get("leader_contact_id") or ""), "")
    title = titles.get(str(f.get("leader_role") or ""), "")
    if name and title:
        return f"{name} ({title})"
    return name or "The church office"


def family_extras(biz: Dict[str, Any], fam: Dict[str, Any], *, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """{'drifting': {since, last_seen, level} | None, 'last_here': date |
    None, 'lines': [...]} for one family's page. None when a read failed."""
    b = str(biz["id"])
    hid = str(fam["household_id"])
    adults = _rows(f"/household_adults?household_id=eq.{_q(hid)}&business_id=eq.{_q(b)}&select=contact_id&limit=40")
    kids = _rows(f"/children?household_id=eq.{_q(hid)}&business_id=eq.{_q(b)}&select=contact_id&limit=40")
    sig = _rows(f"/church_shepherd_signals?household_id=eq.{_q(hid)}&business_id=eq.{_q(b)}&kind=eq.drift"
                "&resolved_at=is.null&select=started_on,last_seen,level&limit=1")
    if adults is None or kids is None or sig is None:
        return None
    ids = [str(a["contact_id"]) for a in adults] + [str(k["contact_id"]) for k in kids if k.get("contact_id")]
    ok, here = last_here(biz, ids, now=now)
    lines = care_lines(b, ids)
    if not ok or lines is None:
        return None
    s = sig[0] if sig else None
    return {"drifting": ({"since": s.get("started_on"), "last_seen": s.get("last_seen"), "level": int(s.get("level") or 0)}
                         if s else None),
            "last_here": here.isoformat() if here else None, "lines": lines}


def tag_for(extras: Optional[Dict[str, Any]]) -> str:
    """'Drifting · last here Sept 28' or 'At church Oct 12' (or '')."""
    if not extras:
        return ""
    d = extras.get("drifting")
    if d:
        seen = _day(d.get("last_seen"))
        return f"Drifting · last here {label(seen)}" if seen else "Drifting"
    here = _day(extras.get("last_here"))
    return f"At church {label(here)}" if here else ""


# ─── the emails' sent-once ledger ─────────────────────────────────────

def _sent(b: str, pattern: str) -> Optional[Set[str]]:
    """The keys already sent that match a like-pattern (`*` is any run)."""
    rows = _rows(f"/church_shepherd_notices?business_id=eq.{_q(b)}&key=like.{_q(pattern)}&select=key&limit=5000")
    if rows is None:
        return None
    return {str(r["key"]) for r in rows}


def _mark(b: str, key: str) -> None:
    try:
        sb_clients.sb_post_as_service("/church_shepherd_notices?on_conflict=business_id,key",
                                      {"business_id": b, "key": key[:200], "sent_at": _iso(_now())},
                                      prefer="return=minimal,resolution=ignore-duplicates")
    except Exception:
        logger.warning("shepherding: notice %s not recorded", key[:40], exc_info=True)


# ─── Monday ───────────────────────────────────────────────────────────

def _birthday(born: Any, week: List[date]) -> Optional[Tuple[date, int]]:
    b = _day(born)
    if not b:
        return None
    for d in week:
        if (b.month, b.day) == (d.month, d.day) or (b.month == 2 and b.day == 29 and (d.month, d.day) == (2, 28)
                                                    and not _leap(d.year)):
            return d, d.year - b.year
    return None


def _leap(y: int) -> bool:
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def _first(name: str) -> str:
    return (_plain(name).split(" ") or ["They"])[0] or "They"


def _the(name: str) -> str:
    return "the " + name[4:] if name.startswith("The ") else name


def monday_plan(biz: Dict[str, Any], now: datetime, rule: Tuple[ZoneInfo, int]) -> Optional[Dict[str, Any]]:
    """Everything Monday does, worked out before anything is sent or
    written: the signals to open, climb and resolve, and the emails. None
    when a read failed (nothing is done that week until it works)."""
    import church_families as cf
    import church_shepherding as shep
    b = str(biz["id"])
    tz, _weekday = rule
    ctx = shep.load(b, now=now)
    rec = recorded(biz, now=now, rule=rule)
    opens = open_signals(b)
    if ctx is None or rec is None or opens is None:
        return None
    today = now.astimezone(tz).date()
    week = [today + timedelta(days=i) for i in range(7)]
    days, seen = rec["days"], rec["seen"]
    new: List[Dict[str, Any]] = []
    climb: List[Dict[str, Any]] = []
    resolve: List[str] = []
    seen_update: List[Tuple[str, Optional[date]]] = []
    digest: Dict[str, Dict[str, List[str]]] = {}
    told_up: Dict[str, Dict[str, Any]] = {}
    placed: Dict[str, str] = {}
    for u in ctx["units"]:
        sid = shep._placed(ctx, u)
        if sid:
            placed[u["household_id"]] = sid
    names = {u["household_id"]: u["name"] for u in ctx["units"] if u["household_id"]}

    for hid, sig in opens.items():
        if hid not in placed:
            resolve.append(str(sig["id"]))
    for hid, sid in placed.items():
        came: Set[date] = set()
        for p in _family_people(ctx, hid):
            came |= seen.get(p, set())
        sig = opens.get(hid)
        mine = digest.setdefault(sid, {"new": [], "still": [], "birthdays": []})
        if sig:
            started = _day(sig.get("started_on")) or today
            if any(d >= started for d in came):
                resolve.append(str(sig["id"]))
                continue
            last = _day(sig.get("last_seen"))
            if _reached_since(ctx, hid, started, tz):
                continue
            mine["still"].append(f"{names[hid]} still hasn’t been at church"
                                 + (f" since {label(last)}" if last else "") + ", and no call or visit is logged yet.")
            told_at = _parse(sig.get("told_at")) or now
            level = int(sig.get("level") or 0)
            chain = _chain(ctx, sid)
            if now - told_at >= CLIMB_AFTER and level < len(chain):
                _role, people = chain[level]
                climb.append({"id": str(sig["id"]), "level": level + 1})
                for p in people:
                    cid = str(p["contact_id"])
                    slot = told_up.setdefault(cid, {"person": p, "lines": []})
                    slot["lines"].append(
                        f"{names[hid]} ({ctx['shepherds'][sid]['name']} shepherds them) has missed three Sundays in a row"
                        + (f", last here {label(last)}," if last else "")
                        + " and hasn’t been reached in a week.")
            continue
        st = drift(days, came)
        if st:
            new.append({"household_id": hid, "started_on": st["since"], "last_seen": st["last_seen"]})
            mine["new"].append(f"{names[hid]} hasn’t been at church since {label(st['last_seen'])}."
                               if st["last_seen"] else f"{names[hid]} has missed the last three Sundays.")
    # Birthdays this week, in each shepherd's families: the adults who are
    # members, and children by first name only.
    for hid, sid in placed.items():
        mine = digest.setdefault(sid, {"new": [], "still": [], "birthdays": []})
        for cid in ctx["adults_of"].get(hid, []):
            m = ctx["members"].get(cid)
            hit = _birthday((m or {}).get("birthdate"), week) if m else None
            if hit:
                mine["birthdays"].append(f"{cf.first_name(m)} turns {hit[1]} on {hit[0].strftime('%A')}.")
        for k in ctx["kids_of"].get(hid, []):
            hit = _birthday(k.get("birthdate"), week)
            if hit:
                mine["birthdays"].append(f"{_plain(k.get('first_name')) or 'A child'} turns {hit[1]} on {hit[0].strftime('%A')}.")
    for hid, sig in opens.items():
        if hid in placed and str(sig["id"]) not in resolve:
            came = set()
            for p in _family_people(ctx, hid):
                came |= seen.get(p, set())
            newest = max((d for d in came), default=None)
            if newest and str(newest) != str(sig.get("last_seen") or ""):
                seen_update.append((str(sig["id"]), newest))

    stamp = today.isoformat()
    emails: List[Dict[str, Any]] = []
    import church_follow_up as cfu
    origin = cfu.site_origin(b)
    church = _plain(biz.get("name")) or "your church"
    for sid, d in digest.items():
        s = ctx["shepherds"].get(sid)
        if not s or not s.get("email") or not (d["new"] or d["still"] or d["birthdays"]):
            continue
        lines = [f"{html.escape(_first(s['name']))}, here are your families at {html.escape(church)} this week."]
        lines += [html.escape(x) for x in d["new"] + d["still"]]
        if d["birthdays"]:
            lines.append("Birthdays this week: " + " ".join(html.escape(x) for x in d["birthdays"]))
        lines.append("Drifting is judged on Sundays alone. Their giving is never part of it, and never shown to you.")
        emails.append({"key": f"digest-{sid}-{stamp}", "to": s["email"], "name": s["name"],
                       "subject": ("One of your families needs you this week" if len(d["new"] + d["still"]) == 1
                                   else f"{len(d['new'] + d['still'])} of your families need you this week")
                       if d["new"] or d["still"] else "Birthdays in your families this week",
                       "body": cfu._mail_html(lines, f"{origin}/my/lead/families" if origin else "", "Open your families")})
    for cid, slot in told_up.items():
        p = slot["person"]
        if not p.get("email"):
            continue
        lines = [f"{html.escape(_first(_plain(p.get('name'))))}, this is the shepherding chain at {html.escape(church)}."]
        lines += [html.escape(x) for x in slot["lines"]]
        lines.append("Please check in with their shepherd, or reach the family yourself. Drifting is judged on "
                     "Sundays alone; giving is never part of it.")
        emails.append({"key": f"up-{cid}-{stamp}", "to": p["email"], "name": _plain(p.get("name")),
                       "subject": (f"{_plain(slot['lines'][0].split(' (')[0])} hasn’t been reached in a week"
                                   if len(slot["lines"]) == 1 else f"{len(slot['lines'])} families haven’t been reached in a week"),
                       "body": cfu._mail_html(lines, "", "")})
    brief = _brief(ctx, placed, opens, new, resolve, tz)
    if brief:
        for d in ctx["defs"]:
            if d.get("job") != "senior":
                continue
            for h in ctx["holders"].get(d["key"], []):
                if not h.get("email"):
                    continue
                lines = [f"{html.escape(_first(_plain(h.get('name'))))}, your Monday brief on shepherding at "
                         f"{html.escape(church)}."] + [html.escape(x) for x in brief]
                emails.append({"key": f"brief-{h['contact_id']}-{stamp}", "to": h["email"], "name": _plain(h.get("name")),
                               "subject": "Your Monday brief: shepherding",
                               "body": cfu._mail_html(lines, OFFICE_LINK, "Open Shepherding")})
    return {"new": new, "climb": climb, "resolve": resolve, "seen_update": seen_update, "emails": emails,
            "stamp": stamp}


def _brief(ctx: Dict[str, Any], placed: Dict[str, str], opens: Dict[str, Dict[str, Any]],
           new: List[Dict[str, Any]], resolve: List[str], tz: ZoneInfo) -> List[str]:
    """The Lead Pastor's Monday lines, only when something needs them."""
    import church_shepherding as shep
    rhythm = int(ctx["settings"]["rhythm_days"])
    reached = sum(1 for hid in placed if shep._reached(ctx, hid))
    names = {u["household_id"]: u["name"] for u in ctx["units"] if u["household_id"]}
    still = [hid for hid, s in opens.items() if hid in placed and str(s["id"]) not in resolve]
    drifting = sorted(set(still) | {n["household_id"] for n in new}, key=lambda h: names.get(h, "").casefold())
    unreached: Dict[str, int] = {}
    for hid, sid in placed.items():
        if not shep._reached(ctx, hid):
            unreached[sid] = unreached.get(sid, 0) + 1
    heavy = [(sid, n) for sid, n in unreached.items() if n >= BRIEF_UNREACHED]
    waiting = len(shep.waiting_units(ctx))
    if not drifting and not heavy and not waiting:
        return []
    lines = [f"{reached} of {len(placed)} families heard from their shepherd in the last {rhythm} days."]
    if drifting:
        shown = [f"{names.get(h, 'A family')} ({ctx['shepherds'][placed[h]]['name']})" for h in drifting[:8]]
        more = f" and {len(drifting) - 8} more" if len(drifting) > 8 else ""
        lines.append(f"{len(drifting)} drifting: " + ", ".join(shown) + more
                     + ". Their shepherds were told; a week with no reach goes up the chain.")
    for sid, n in sorted(heavy, key=lambda x: -x[1]):
        lines.append(f"{ctx['shepherds'][sid]['name']} has {n} families not reached in {rhythm} days.")
    if waiting:
        lines.append(f"{waiting} {'family waits' if waiting == 1 else 'families wait'} for a shepherd. "
                     "Ask Chief for a proposal on Shepherding.")
    return lines


def _apply(b: str, plan: Dict[str, Any], now: datetime) -> Dict[str, int]:
    """Write what Monday decided (after its emails went)."""
    done = {"drifting": 0, "climbed": 0, "resolved": 0}
    stamp = _iso(now)
    for n in plan["new"]:
        saved = sb_clients.sb_post_as_service("/church_shepherd_signals", {
            "business_id": b, "household_id": n["household_id"], "kind": "drift",
            "started_on": n["started_on"].isoformat(),
            "last_seen": n["last_seen"].isoformat() if n["last_seen"] else None,
            "level": 0, "told_at": stamp})
        done["drifting"] += 1 if isinstance(saved, list) and saved else 0
    for c in plan["climb"]:
        sb_clients.sb_patch_as_service(f"/church_shepherd_signals?id=eq.{_q(c['id'])}&business_id=eq.{_q(b)}",
                                       {"level": c["level"], "told_at": stamp})
        done["climbed"] += 1
    for sid in plan["resolve"]:
        sb_clients.sb_patch_as_service(f"/church_shepherd_signals?id=eq.{_q(sid)}&business_id=eq.{_q(b)}",
                                       {"resolved_at": stamp})
        done["resolved"] += 1
    for sid, d in plan["seen_update"]:
        sb_clients.sb_patch_as_service(f"/church_shepherd_signals?id=eq.{_q(sid)}&business_id=eq.{_q(b)}",
                                       {"last_seen": d.isoformat()})
    return done


# ─── a care need, the same hour ───────────────────────────────────────

def care_plan(biz: Dict[str, Any], now: datetime) -> Optional[List[Dict[str, Any]]]:
    """A card handed to the Deacons or the Care team for someone in a
    shepherded family: their shepherd hears it is in hand (never the
    card's words), once. None when a read failed."""
    import church_follow_up as cfu
    import church_shepherding as shep
    b = str(biz["id"])
    since = _iso(now - CARE_LOOKBACK)
    fus = _rows(f"/church_follow_ups?business_id=eq.{_q(b)}&status=in.(open,handed_back)&created_at=gte.{_q(since)}"
                "&select=id,contact_id,leader_contact_id,leader_role,path_kind,answers,created_at&limit=500")
    if fus is None:
        return None
    cares = [f for f in fus if cfu.stream_for(f.get("path_kind") or "", f.get("answers") or [])[0] == "care_need"]
    if not cares:
        return []
    sent = _sent(b, "care-*")
    if sent is None:
        return None
    cares = [f for f in cares if f"care-{f['id']}" not in sent]
    if not cares:
        return []
    ctx = shep.load(b, now=now)
    if ctx is None:
        return None
    titles = _role_titles(b)
    lids = sorted({str(f["leader_contact_id"]) for f in cares if f.get("leader_contact_id")})
    names: Dict[str, str] = {}
    if lids:
        ppl = _rows(f"/contacts?business_id=eq.{_q(b)}&id=in.({','.join(_q(i) for i in lids)})&select=id,name")
        if ppl is None:
            return None
        names = {str(p["id"]): _plain(p.get("name")) for p in ppl}
    unit_by_home = {u["household_id"]: u for u in ctx["units"] if u["household_id"]}
    origin = cfu.site_origin(b)
    out: List[Dict[str, Any]] = []
    for f in cares:
        for hid in sorted(ctx["homes_of"].get(str(f["contact_id"]), set())):
            u = unit_by_home.get(hid)
            sid = shep._placed(ctx, u) if u else None
            if not sid or sid == str(f.get("leader_contact_id") or ""):
                continue
            s = ctx["shepherds"][sid]
            if not s.get("email"):
                continue
            who = _holder_words(f, titles, names)
            line = f"{who} has a care need for {_the(u['name'])}. It’s in hand; the card’s words stay with them."
            out.append({"key": f"care-{f['id']}", "to": s["email"], "name": s["name"],
                        "subject": f"A care need in {_the(u['name'])}",
                        "body": cfu._mail_html([f"{html.escape(_first(s['name']))}, {html.escape(line)}",
                                                "You don’t need to do anything about the need itself. A call to say "
                                                "you’re praying for them is always welcome."],
                                               f"{origin}/my/lead/family/{hid}" if origin else "", "Open the family")})
            break
    return out


# ─── the hourly job ───────────────────────────────────────────────────

async def run_church(biz: Dict[str, Any], now: datetime, stats: Dict[str, int]) -> None:
    import church_follow_up as cfu
    b = str(biz["id"])
    cares = await asyncio.to_thread(care_plan, biz, now)
    for m in cares or []:
        if await cfu._email(biz, m["to"], m["name"], m["subject"], m["body"], f"shep-{b}-{m['key']}"):
            await asyncio.to_thread(_mark, b, m["key"])
            stats["care"] += 1
    rule = await asyncio.to_thread(sunday_rule, biz)
    if rule is None:
        return
    local = now.astimezone(rule[0])
    if local.weekday() != 0 or local.hour < MONDAY_HOUR:
        return
    week_key = f"monday-{local.date().isoformat()}"
    # This week's keys all end with Monday's date.
    sent = await asyncio.to_thread(_sent, b, f"*{local.date().isoformat()}")
    if sent is None or week_key in sent:
        return
    plan = await asyncio.to_thread(monday_plan, biz, now, rule)
    if plan is None:
        return
    for m in plan["emails"]:
        if m["key"] in sent:
            continue
        if await cfu._email(biz, m["to"], m["name"], m["subject"], m["body"], f"shep-{b}-{m['key']}"):
            await asyncio.to_thread(_mark, b, m["key"])
            stats["emails"] += 1
    done = await asyncio.to_thread(_apply, b, plan, now)
    for k, v in done.items():
        stats[k] += v
    await asyncio.to_thread(_mark, b, week_key)


async def sweep(now: Optional[datetime] = None) -> Dict[str, int]:
    """Hourly, across churches that have given families shepherds: care
    needs the same hour; on Monday morning (the church's clock), drifting,
    the chain, birthdays and the Lead Pastor's brief. A church that fails
    never stops the others."""
    import church_follow_up as cfu
    now = now or _now()
    stats = {"churches": 0, "care": 0, "emails": 0, "drifting": 0, "climbed": 0, "resolved": 0}
    rows = await asyncio.to_thread(_rows, "/church_shepherds?select=business_id&limit=50000")
    ids = sorted({str(r["business_id"]) for r in rows or []})
    for chunk in _chunks(ids):
        bizs = await asyncio.to_thread(
            _rows, f"/businesses?id=in.({','.join(_q(i) for i in chunk)})&select=id,name,type,settings&limit={_CHUNK}")
        for biz in bizs or []:
            if not cfu.is_church(biz):
                continue
            stats["churches"] += 1
            try:
                await run_church(biz, now, stats)
            except Exception:
                logger.warning("shepherding sweep failed for business %s", str(biz.get("id"))[:8], exc_info=True)
    return stats


# ─── what Chief answers ───────────────────────────────────────────────

_TITLES = re.compile(r"^(pastor|elder|minister|deacon|bishop|rev(erend)?|dr|apostle|evangelist|mother|brother|sister)\.?\s+",
                     re.I)


def norm_name(text: str) -> str:
    t = _plain(text).casefold().replace("’", "'")
    t = re.sub(r"^the\s+", "", t)
    t = re.sub(r"\s+family$", "", t)
    t = re.sub(r"'s$", "", t)
    while _TITLES.match(t):
        t = _TITLES.sub("", t, count=1)
    return t.strip()


def _family_matches(ctx: Dict[str, Any], query: str) -> List[Dict[str, Any]]:
    """The units a name means: a family's name ("the Carters", "Carter
    family"), or a member's name (their family)."""
    q = norm_name(query)
    if not q:
        return []
    qs = {q, q[:-1] if q.endswith("s") else q, q[:-2] if q.endswith("es") else q}
    out = []
    for u in ctx["units"]:
        fam = norm_name(u["name"])
        people = [norm_name((ctx["members"].get(p) or {}).get("name") or "") for p in u["people"]]
        if fam in qs or any(p == q for p in people if p):
            out.append(u)
    if not out:
        for u in ctx["units"]:
            people = [norm_name((ctx["members"].get(p) or {}).get("name") or "") for p in u["people"]]
            if any(q in p.split(" ") for p in people if p) or q in norm_name(u["name"]).split(" "):
                out.append(u)
    return out


def chief_lines(biz: Dict[str, Any], name: str = "") -> Optional[List[str]]:
    """Shepherding as Chief tells it to the owner or a manager: who has
    whom, who's drifting, who hasn't been reached. Never giving, never a
    note's words, a child as first name and age. None when a read failed."""
    import church_families as cf
    import church_shepherding as shep
    b = str(biz["id"])
    ctx = shep.load(b)
    if ctx is None:
        return None
    view = office_view(biz, ctx)
    if view is None:
        return None
    rhythm = int(ctx["settings"]["rhythm_days"])
    drifting = view["by_household"]
    today = ctx["now"].date()
    if name:
        found = _family_matches(ctx, name)
        if not found:
            return [f"No member family matches “{_plain(name)[:60]}”. Shepherding covers members only; visitors stay "
                    "with the Welcome role. Ask which family they mean."]
        if len(found) > 3:
            return [f"“{_plain(name)[:60]}” matches {len(found)} families: "
                    + ", ".join(u["name"] for u in found[:8]) + ". Ask which one."]
        lines = []
        for u in found:
            who = []
            for p in u["people"]:
                m = ctx["members"].get(p)
                if not m:
                    continue
                if cf.is_child(m, today):
                    a = cf.age(m.get("birthdate"), today)
                    who.append(f"{cf.first_name(m)} ({a})" if a is not None else cf.first_name(m))
                else:
                    who.append(_plain(m.get("name")))
            for k in ctx["kids_of"].get(u["household_id"] or "", []):
                if not k.get("contact_id"):
                    a = cf.age(k.get("birthdate"), today)
                    who.append(f"{_plain(k.get('first_name'))} ({a})" if a is not None else _plain(k.get("first_name")))
            head = f"{u['name']}" + (f" ({', '.join(who)})" if who else "")
            sid = shep._placed(ctx, u)
            if not sid:
                lines.append(f"{head}: waiting for a shepherd. Nobody shepherds them yet; a proposal on Shepherding "
                             "would place them.")
                continue
            a = ctx["assigned"][u["household_id"]]
            since = _parse(a.get("assigned_at"))
            s = ctx["shepherds"][sid]
            line = (f"{head}: shepherded by {s['name']} ({s['role']})"
                    + (f" since {label(since.date())}" if since else "")
                    + (f"; why: {_plain(a.get('reason'))}" if _plain(a.get("reason")) else "") + ".")
            t = ctx["last_touch"].get(u["household_id"])
            at = _parse((t or {}).get("created_at"))
            line += (f" Last reached {label(at.date())} ({shep.KINDS.get(t.get('kind'), 'reached').lower()})."
                     if at else " Not reached yet.")
            d = drifting.get(u["household_id"])
            if d:
                seen = _day(d.get("last_seen"))
                line += (" Drifting: missed the last three Sundays" + (f", last here {label(seen)}" if seen else "")
                         + f"; {told_name(ctx, sid, int(d['level']))} has been told.")
            lines.append(line)
        return lines

    placed: Dict[str, str] = {}
    for u in ctx["units"]:
        sid = shep._placed(ctx, u)
        if sid:
            placed[u["household_id"]] = sid
    waiting = len(ctx["units"]) - len(placed)
    reached = sum(1 for hid in placed if shep._reached(ctx, hid))
    lines = [f"Shepherding: {len(placed)} member {'family has' if len(placed) == 1 else 'families have'} a shepherd "
             f"and {waiting} {'waits' if waiting == 1 else 'wait'} for one. "
             f"{len(ctx['shepherds'])} shepherds (pastors and elders who said yes): "
             + (", ".join(f"{s['name']} ({s['role']}, {sum(1 for x in placed.values() if x == cid)} of {s['cap']})"
                          for cid, s in ctx["shepherds"].items()) or "none yet") + ".",
             f"Reached in the last {rhythm} days: {reached} of {len(placed)} shepherded families.",
             f"Recorded Sundays in the last {WINDOW_WEEKS} weeks: {view['sundays_recorded']}"
             + (" (drifting needs at least 5, so nobody can be flagged yet)." if view["sundays_recorded"] < MISSED + GUARD_MIN
                else ".")]
    if view["drifting"]:
        lines.append(f"Drifting (missed the last three Sundays in a row; judged on Sundays only, never giving) "
                     f"({len(view['drifting'])}):")
        for d in view["drifting"]:
            seen = _day(d.get("last_seen"))
            lines.append(f"- {d['name']} (shepherd {d['shepherd_name']})"
                         + (f": last here {label(seen)}" if seen else "") + f"; {d['told']} has been told.")
    else:
        lines.append("Drifting: nobody right now.")
    unreached: Dict[str, int] = {}
    for hid, sid in placed.items():
        if not shep._reached(ctx, hid):
            unreached[sid] = unreached.get(sid, 0) + 1
    if unreached:
        lines.append(f"Not reached in the last {rhythm} days, by shepherd:")
        for sid, n in sorted(unreached.items(), key=lambda x: -x[1]):
            held = sum(1 for x in placed.values() if x == sid)
            lines.append(f"- {ctx['shepherds'][sid]['name']}: {n} of {held}")
    if view["not_reached_60"]:
        lines.append(f"{view['not_reached_60']} families have not been reached in {LONG_DAYS} days.")
    lines.append("Chief can draft moves (draft_shepherd_moves) for the office to approve on Shepherding; nothing "
                 "moves and no shepherd is told until they approve.")
    return lines
