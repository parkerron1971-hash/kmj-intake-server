"""
church_move_setup.py — set up what a church handed in.

Kevin, 2026-11-14, on the Move-in room's last gap ("What a church hands in
still has to be set up by hand"): "do the not built section because that
allows for it to be setup before this pastor gets it." Until now a
checked hand-in was only words on a page: someone still typed the service
onto the calendar, made each group, invited each login. This turns a
hand-in into the church's real records, on the platform owner's press.

HOW IT WORKS
  plan(biz, key)  -> the steps for one Move-in item, each with a state:
      will    pressing the button does this
      there   it is already so (nothing is done twice)
      cant    it needs a hand, and the words say why
      note    nothing to set up; kept for later
  apply(biz, key) -> runs the `will` steps and answers the same list with
      made | failed in their place. Plan and apply are ONE pass (the `do`
      flag), so what is shown is what is done.

  Everything is idempotent: each step looks at what the church has before
  it writes, so pressing twice makes nothing twice, and a church that set
  something up itself is left as it set it.

WHAT IS SET UP (the canonical way each record is made is named beside it)
  sunday   Sunday check-in from the first service (church_checkin
           .save_settings); each service on the calendar for the next four
           weeks (module_entries in the church's Services & Events room,
           as church_checkin.ensure_occasion writes them); children placed
           in kids rooms by age (children.room); groups, each with its
           leader when the name is one adult on file (groups,
           group_members).
  logins   an office login invited in the lane the words point to
           (business_users_router.make_invite_row + its email). A money
           login is an Admin over the whole church, so that one is left to
           the church's owner.
  safety   the two safety officers (messaging_router's tables): an office
           login that has joined, or a pastor or elder with an active role.
  look     the church colour and the logo into the brand kit
           (brand_engine.save_brand_kit / upload_asset).

WHAT IT NEVER DOES
  It never switches giving, the members' app or messaging on, never
  invites an Admin, never guesses: a time, an age range, a name or an area
  it can't read is a `cant` with the church's own words quoted back.

WHO
  The platform owner, from Mission Control's Move-ins
  (church_move_in.platform_router, /platform/move-in/{church}/setup/{item}).
  It writes as the server into the church's account, so each apply leaves
  one line in the church's own audit log.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote
from zoneinfo import ZoneInfo

import sb_clients

logger = logging.getLogger(__name__)

WILL, THERE, CANT, NOTE, MADE, FAILED = "will", "there", "cant", "note", "made", "failed"
WEEKS_AHEAD = 4
UNREAD = "This couldn't be read just now. Try again."
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
# The lane an area's login is invited in (church_areas.LANES). Giving is
# missing on purpose: a money login is an Admin over the whole church.
LANE_OF_AREA = {"people_care": "people_care", "kids_youth": "people_care", "groups_classes": "people_care",
                "worship_media": "sunday_serving", "website_outreach": "media_comms",
                "office": "office_leadership", "messages_safety": "office_leadership"}


class Unread(Exception):
    """A read failed. Nothing is planned on a guess."""


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _rows(path: str) -> List[Dict[str, Any]]:
    got = sb_clients.sb_get_as_service(path)
    if not isinstance(got, list):
        raise Unread(path.split("?")[0])
    return got


def _plain(v: Any) -> str:
    return " ".join(str(v or "").split())


def _step(state: str, what: str, why: str = "") -> Dict[str, Any]:
    return {"state": state, "what": what, "why": why}


def _done(step: Dict[str, Any], ok: bool, why: str = "") -> Dict[str, Any]:
    step["state"] = MADE if ok else FAILED
    if not ok:
        step["why"] = why or "That didn't save. Try again."
    return step


# ─── Reading the church's words ───────────────────────────────────────

def weekday_of(text: Any) -> Optional[int]:
    """'Sunday', 'Sundays', 'Sun.' -> 6 (Monday is 0). None when no day is named."""
    m = re.search(r"\b(mon|tue|wed|thu|fri|sat|sun)", str(text or "").lower())
    return ("mon", "tue", "wed", "thu", "fri", "sat", "sun").index(m.group(1)) if m else None


def clock_of(text: Any) -> Optional[str]:
    """'10:30 AM', '9am', '6 p.m.', '18:00' -> 'HH:MM'. A time with no AM or
    PM is read only where it can't be mistaken: 8 to 12 is the morning (or
    noon) and 13 on is the 24-hour clock. '6:00' or '7' alone could be
    either (a Wednesday night at 7 is the usual one), so it is None and a
    person decides."""
    s = str(text or "").lower().replace(".", "")
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a|p)?\b", s)
    if not m:
        return None
    h, mins, half = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "")[:1]
    if mins > 59 or h > 23:
        return None
    if half:
        if not 1 <= h <= 12:
            return None
        h = h % 12 + (12 if half == "p" else 0)
    elif h < 8:
        return None
    return f"{h:02d}:{mins:02d}"


def clock_words(hhmm: str) -> str:
    h, m = (int(x) for x in hhmm.split(":"))
    return f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


_GRADE = {"k": 5, "kinder": 5, "kindergarten": 5, "prek": 4, "pre-k": 4}


def ages_of(text: Any) -> Optional[Tuple[int, int]]:
    """'0 to 2', '3-5', 'birth to 2', 'K to 5th', '6th-8th grade', '12+' ->
    the youngest and oldest age in whole years. A grade is that many years
    past five. None when the words can't be read as a range."""
    s = str(text or "").lower().replace("–", "-").replace("—", "-")
    grades = bool(re.search(r"grade|\b\d{1,2}(st|nd|rd|th)\b|\bk\b|kinder|pre-?k", s))

    def one(tok: str) -> Optional[int]:
        tok = tok.strip()
        if tok in ("birth", "newborn", "newborns", "infant", "infants", "baby", "babies"):
            return 0
        if tok in _GRADE:
            return _GRADE[tok]
        m = re.fullmatch(r"(\d{1,2})(st|nd|rd|th)?", tok)
        if not m:
            return None
        n = int(m.group(1))
        return n + 5 if grades and (m.group(2) or "grade" in s) else n

    toks = re.findall(r"birth|newborns?|infants?|baby|babies|pre-?k|kindergarten|kinder|\bk\b|\d{1,2}(?:st|nd|rd|th)?", s)
    vals = [v for v in (one(t) for t in toks) if v is not None]
    if not vals:
        return None
    if len(vals) == 1:
        if re.search(r"\+|and up|and older|or older", s):
            return vals[0], 17
        if re.search(r"under|below|younger", s):
            return 0, max(0, vals[0] - 1)
        return vals[0], vals[0]
    lo, hi = min(vals[0], vals[1]), max(vals[0], vals[1])
    return (lo, hi) if hi <= 18 else None


def _today(biz: Dict[str, Any]) -> date:
    import church_checkin as cc
    return datetime.now(ZoneInfo(cc.church_zone_name(biz))).date()


def _short(d: date) -> str:
    return f"{d.strftime('%b')} {d.day}"


# ─── Sunday: check-in, the calendar, kids rooms, groups ───────────────

def _services(answers: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for r in answers.get("services") or []:
        name = _plain(r.get("name")) or "Sunday service"
        out.append({"name": name[:80], "said": " · ".join(_plain(r.get(k)) for k in ("day", "time", "name") if r.get(k)),
                    "weekday": weekday_of(r.get("day")), "time": clock_of(r.get("time"))})
    return out


def _checkin(biz: Dict[str, Any], services: List[Dict[str, Any]], do: bool) -> List[Dict[str, Any]]:
    import church_checkin as cc
    st = cc.settings(biz)
    if st is None:
        raise Unread("church_checkin_settings")
    if st.get("enabled"):
        w = cc.window(st)
        return [_step(THERE, f"Sunday check-in is already on: {w['weekday']}s at {cc.clock(w['start'])}.")]
    ok = [s for s in services if s["weekday"] is not None and s["time"]]
    first = next((s for s in ok if s["weekday"] == 6), ok[0] if ok else None)
    if not first:
        return [_step(CANT, "Sunday check-in", "No service has a day and a time that can be read. Set it in "
                                                  "the church's Sunday check-in.")]
    step = _step(WILL, f"Switch Sunday check-in on: {DAYS[first['weekday']]}s at {clock_words(first['time'])} "
                       f"({first['name']}).",
                 "Check-in follows one service time. The first Sunday service is used." if len(ok) > 1 else "")
    if do:
        try:
            cc.save_settings(biz, {"enabled": True, "weekday": first["weekday"], "start_time": first["time"],
                                   "title": first["name"]}, None)
            _done(step, True)
        except Exception as e:  # noqa: BLE001  (its reads and writes answer 400 and 503)
            _done(step, False, _plain(getattr(e, "detail", "")) or "")
    return [step]


def _calendar(biz: Dict[str, Any], services: List[Dict[str, Any]], do: bool) -> List[Dict[str, Any]]:
    import church_checkin as cc
    from events_rsvp_router import _parse_day, resolve_fields
    biz_id = str(biz["id"])
    mods = cc._roster(biz_id)
    if mods is None:
        raise Unread("custom_modules")
    if not mods:
        return [_step(CANT, "Services on the calendar", "This church has no Services & Events room to put them in.")]
    mod = next((m for m in mods if "service" in str(m.get("name") or "").lower()), mods[0])
    f = resolve_fields(mod.get("archetype_params"))
    entries = cc._entries(biz_id, [str(mod["id"])])
    if entries is None:
        raise Unread("module_entries")
    have = set()
    for e in entries:
        data = e.get("data") or {}
        day = _parse_day(data.get(f["date_field"]))
        if day:
            have.add((day, _plain(data.get(f["title_field"])).casefold()))
            have.add((day, str(data.get(f["date_field"]) or "")[11:16]))
    today = _today(biz)
    steps = []
    for s in services:
        if s["weekday"] is None or not s["time"]:
            steps.append(_step(CANT, f"“{s['said']}” on the calendar",
                               "The day or the time can't be read. A time needs AM or PM unless it's in the morning."))
            continue
        first = today + timedelta(days=(s["weekday"] - today.weekday()) % 7)
        days = [first + timedelta(days=7 * n) for n in range(WEEKS_AHEAD)]
        missing = [d for d in days if (d, s["name"].casefold()) not in have and (d, s["time"]) not in have]
        when = f"{DAYS[s['weekday']]}s at {clock_words(s['time'])}"
        if not missing:
            steps.append(_step(THERE, f"{s['name']} is on the calendar for the next {WEEKS_AHEAD} weeks ({when})."))
            continue
        step = _step(WILL, f"Put {s['name']} on the calendar, {when}: {', '.join(_short(d) for d in missing)}.")
        if do:
            made = 0
            for d in missing:
                got = sb_clients.sb_post_as_service("/module_entries", {
                    "business_id": biz_id, "module_id": str(mod["id"]), "status": "active", "created_by": "move_in_setup",
                    "data": {f["title_field"]: s["name"], f["date_field"]: f"{d.isoformat()}T{s['time']}",
                             "type": "service", f["signups_field"]: [], "_visibility": "public",
                             "notes": "From the church's Move-in."}})
                if isinstance(got, list) and got:
                    made += 1
                    have.add((d, s["name"].casefold()))
            _done(step, made == len(missing), f"{made} of {len(missing)} were added. Press again for the rest.")
        steps.append(step)
    return steps


def _kids(biz: Dict[str, Any], answers: Dict[str, Any], do: bool) -> List[Dict[str, Any]]:
    import member_messaging_rules as rules
    rooms = [(_plain(r.get("room"))[:60], _plain(r.get("ages"))) for r in answers.get("kids_rooms") or []
             if _plain(r.get("room"))]
    if not rooms:
        return []
    steps, ranges = [], []
    for name, said in rooms:
        got = ages_of(said)
        if got is None:
            steps.append(_step(CANT, f"{name} room", f"The ages “{said or 'none given'}” can't be read as a range."))
        else:
            ranges.append((name, got))
    kids = _rows(f"/children?business_id=eq.{_q(biz['id'])}&active=eq.true&select=id,birthdate,room&limit=2000")
    if not kids:
        return steps + [_step(CANT, "Children in their rooms", "No children are on file yet. Run this again once "
                                                               "the people are in.")]
    today, placed, unplaced = _today(biz), {n: [] for n, _ in ranges}, 0
    for k in kids:
        if _plain(k.get("room")):
            continue
        age = rules.age(k.get("birthdate"), today)
        room = next((n for n, (lo, hi) in ranges if age is not None and lo <= age <= hi), None)
        if room:
            placed[room].append(str(k["id"]))
        else:
            unplaced += 1
    for name, (lo, hi) in ranges:
        ids = placed[name]
        span = f"age {lo}" if lo == hi else f"ages {lo} to {hi}"
        if not ids:
            steps.append(_step(THERE, f"{name} ({span}): no child is waiting for this room."))
            continue
        step = _step(WILL, f"Place {len(ids)} {'child' if len(ids) == 1 else 'children'} in {name} ({span}).")
        if do:
            now = datetime.now(timezone.utc).isoformat()
            ok = sum(1 for cid in ids if isinstance(sb_clients.sb_patch_as_service(
                f"/children?id=eq.{_q(cid)}&business_id=eq.{_q(biz['id'])}", {"room": name, "updated_at": now}), list))
            _done(step, ok == len(ids), f"{ok} of {len(ids)} were placed. Press again for the rest.")
        steps.append(step)
    if unplaced:
        steps.append(_step(CANT, f"{unplaced} {'child has' if unplaced == 1 else 'children have'} no room",
                           "No birthday on file, or an age no room covers. Place them from Kids."))
    return steps


def _one_adult(biz_id: str, name: str) -> Optional[str]:
    """The one adult on file with exactly this name (any case); None for
    nobody or more than one. A guess would make the wrong person a leader."""
    import member_spaces as ms
    safe = re.sub(r"[*%_,()\"\\]", " ", name).strip()
    if not safe:
        return None
    rows = _rows(f"/contacts?business_id=eq.{_q(biz_id)}&name=ilike.{_q(safe)}&select=id,name,birthdate&limit=5")
    adults = [r for r in rows if _plain(r.get("name")).casefold() == _plain(name).casefold() and not ms.is_child(r)]
    return str(adults[0]["id"]) if len(adults) == 1 else None


def _groups(biz: Dict[str, Any], answers: Dict[str, Any], do: bool) -> List[Dict[str, Any]]:
    biz_id = str(biz["id"])
    asked = [(_plain(r.get("name"))[:80], _plain(r.get("leader")), _plain(r.get("meets"))[:120])
             for r in answers.get("groups") or [] if _plain(r.get("name"))]
    if not asked:
        return []
    have = {_plain(g.get("name")).casefold(): str(g["id"])
            for g in _rows(f"/groups?business_id=eq.{_q(biz_id)}&select=id,name&limit=500")}
    led = {str(r.get("group_id")) for r in _rows(
        f"/group_members?business_id=eq.{_q(biz_id)}&role=eq.leader&select=group_id&limit=2000")}
    steps = []
    for name, leader, meets in asked:
        gid = have.get(name.casefold())
        who = _one_adult(biz_id, leader) if leader else None
        lead_words = (f", led by {leader}" if who else "")
        hand = (f" The leader “{leader}” isn't one adult on file, so add them from Groups." if leader and not who else "")
        if gid and (gid in led or not who):
            steps.append(_step(THERE, f"{name} is already a group.", hand.strip()))
            continue
        step = _step(WILL, (f"Add {leader} as the leader of {name}." if gid else
                            f"Make the group {name}{lead_words}" + (f" ({meets})." if meets else ".")), hand.strip())
        if do:
            if not gid:
                got = sb_clients.sb_post_as_service("/groups?select=id", {
                    "business_id": biz_id, "name": name, "kind": "small_group", "join_mode": "ask",
                    **({"meets": meets} if meets else {})})
                gid = str(got[0]["id"]) if isinstance(got, list) and got else None
                if gid:
                    have[name.casefold()] = gid
            ok = bool(gid)
            if ok and who:
                got = sb_clients.sb_post_as_service(
                    "/group_members?on_conflict=group_id,contact_id",
                    {"group_id": gid, "contact_id": who, "business_id": biz_id, "role": "leader"},
                    prefer="return=representation,resolution=merge-duplicates")
                ok = isinstance(got, list) and bool(got)
            _done(step, ok, "The group was made, and its leader wasn't added. Press again." if gid and not ok else "")
        steps.append(step)
    return steps


def _sunday(biz: Dict[str, Any], answers: Dict[str, Any], files: List[Dict[str, Any]], do: bool):
    services = _services(answers)
    steps = _checkin(biz, services, do) if services else []
    steps += _calendar(biz, services, do) if services else []
    steps += _kids(biz, answers, do)
    steps += _groups(biz, answers, do)
    return steps, []


# ─── Office logins ────────────────────────────────────────────────────

def _logins(biz: Dict[str, Any], answers: Dict[str, Any], files: List[Dict[str, Any]], do: bool):
    import billing_limits
    import business_users_router as bur
    import church_areas
    biz_id = str(biz["id"])
    seats = {_plain(s.get("invited_email")).lower() for s in _rows(
        f"/business_users?business_id=eq.{_q(biz_id)}&status=in.(invited,active)&select=invited_email&limit=300")}
    row = (_rows(f"/businesses?id=eq.{_q(biz_id)}&select=id,name,owner_id,subscription_status,"
                 "subscription_plan,comp_tier&limit=1") or [{}])[0]
    cap = billing_limits.can_add_seat(biz_id, row)
    room = (cap["limit"] - cap["count"]) if cap.get("enforce") else None
    steps, mail = [], []
    for p in answers.get("people") or []:
        name, email, looks = _plain(p.get("name")), _plain(p.get("email")).lower(), _plain(p.get("looks_after"))
        who = name or email or "Someone"
        if not email or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]{2,}", email):
            steps.append(_step(CANT, f"Invite {who}", "There's no email to send the invitation to."))
            continue
        if email in seats:
            steps.append(_step(THERE, f"{who} ({email}) is already invited or has joined."))
            continue
        guess = church_areas.guess_area(looks)
        if guess and guess[0] == "giving_money":
            steps.append(_step(CANT, f"Invite {who}", f"“{looks}” is the church's money. That login is an Admin over "
                                                       "the whole church, so the church's owner invites it from Team."))
            continue
        key = LANE_OF_AREA.get(guess[0]) if guess else None
        if not key:
            steps.append(_step(CANT, f"Invite {who}", f"“{looks or 'nothing given'}” doesn't say which part of the "
                                                       "office this is. Invite them from the church's Team page."))
            continue
        if room is not None and room <= 0:
            steps.append(_step(CANT, f"Invite {who}", f"The plan's {cap['limit']} office logins are all taken."))
            continue
        lane = church_areas.lane(key)
        step = _step(WILL, f"Invite {who} ({email}) to {lane['label']}. An email goes to them.",
                     f"From “{looks}”.")
        if do:
            person = bur.match_contact(biz_id, email, name)
            made = bur.make_invite_row(biz_id, email=email, role=lane["role"], lane=lane, person=person,
                                       invited_by=str(biz.get("owner_id") or ""))
            _done(step, bool(made))
            if made:
                seats.add(email)
                mail.append({"step": step, "row": made, "biz_row": row, "email": email, "role": lane["role"],
                             "lane": lane, "person": person})
        if room is not None:
            room -= 1
        steps.append(step)
    return steps, mail


async def send_mail(biz: Dict[str, Any], mail: List[Dict[str, Any]]) -> None:
    """The invitations' emails, after their rows are made. One that doesn't
    send is said on its step: the login is invited and the church can send
    it again from Team."""
    import business_users_router as bur
    for m in mail:
        try:
            sent = await bur.send_invite_email(str(biz["id"]), m["biz_row"], m["row"], email=m["email"],
                                               role=m["role"], lane=m["lane"], person=m["person"])
            ok = bool(sent.get("email_sent"))
        except Exception:  # noqa: BLE001
            logger.warning("move-in setup: an invite email failed for %s", biz.get("id"), exc_info=True)
            ok = False
        if not ok:
            m["step"]["why"] = "They're invited, and the email didn't send. Send it again from the church's Team page."


# ─── Safety officers ──────────────────────────────────────────────────

def _safety(biz: Dict[str, Any], answers: Dict[str, Any], files: List[Dict[str, Any]], do: bool):
    import member_portal as mp
    import messaging_router as mr
    biz_id, owner = str(biz["id"]), str(biz.get("owner_id") or "")
    try:
        named, named_people = set(mr.officers(biz_id)), set(mr.member_officers(biz_id))
        leaders = mr.eligible_leaders(biz_id, owner)
    except Exception as e:  # noqa: BLE001  (its reads answer 503)
        raise Unread("officers") from e
    logins = {mr.owner_email_read(owner) or "": owner}
    for s in _rows(f"/business_users?business_id=eq.{_q(biz_id)}&status=eq.active&user_id=not.is.null"
                   "&select=user_id,invited_email&limit=300"):
        logins[_plain(s.get("invited_email")).lower()] = str(s["user_id"])
    logins.pop("", None)
    steps = []
    for o in answers.get("officers") or []:
        name, contact = _plain(o.get("name")), _plain(o.get("contact"))
        who = name or contact or "Someone"
        email = contact.lower() if "@" in contact else ""
        uid = logins.get(email) if email else None
        cid = None
        if not uid:
            ids = set()
            if email:
                ids = {str(c["id"]) for c in (mp.contacts_for_email(biz_id, email) or [])}
            elif len(mp._last10(contact)) == 10:
                ids = {str(c["id"]) for c in (mp.contacts_for_phone(biz_id, contact) or [])}
            hits = [x for x in leaders if x["contact_id"] in ids] or \
                   [x for x in leaders if name and x["name"].casefold() == name.casefold()]
            cid = hits[0]["contact_id"] if len(hits) == 1 else None
        if (uid and uid in named) or (cid and cid in named_people):
            steps.append(_step(THERE, f"{who} is already a safety officer."))
            continue
        if not uid and not cid:
            steps.append(_step(CANT, f"Name {who} a safety officer",
                               "They aren't an office login that has joined, or a pastor or elder with an active "
                               "role, yet. Invite them or give them their role first, then press again."))
            continue
        step = _step(WILL, f"Name {who} a safety officer" + (" (their office login)." if uid else " (a pastor or elder)."))
        if do:
            got = sb_clients.sb_post_as_service(
                "/msg_safety_officers" if uid else "/msg_member_officers",
                {"business_id": biz_id, "added_by": owner, **({"user_id": uid} if uid else {"contact_id": cid})})
            _done(step, isinstance(got, list) and bool(got))
            (named if uid else named_people).add(uid or cid)
        steps.append(step)
    if steps and all(s["state"] in (THERE, MADE, WILL) for s in steps) and len(steps) >= mr.MIN_OFFICERS:
        steps.append(_step(NOTE, "Member messaging stays off until the church's owner switches it on."))
    return steps, []


# ─── The look ─────────────────────────────────────────────────────────

def _storage_get(path: str) -> Optional[bytes]:
    import httpx
    import church_move_in as mi
    import storage_links
    try:
        r = httpx.get(mi._storage_url(path), headers=storage_links.service_headers(), timeout=30)
        return r.content if r.is_success else None
    except Exception:  # noqa: BLE001
        return None


def _look(biz: Dict[str, Any], answers: Dict[str, Any], files: List[Dict[str, Any]], do: bool):
    import brand_dna
    import brand_engine
    import member_app_ui
    biz_id = str(biz["id"])
    kit = (biz.get("settings") or {}).get("brand_kit")
    kit = dict(kit) if isinstance(kit, dict) else {}
    cols = dict(kit.get("colors")) if isinstance(kit.get("colors"), dict) else {}
    steps = []
    said = _plain(answers.get("colour"))
    if said:
        have = member_app_ui.brand_colour(biz, {})
        want = brand_dna.pref_color_to_hex(said)
        if have:
            steps.append(_step(THERE, f"The church colour is already set ({have})."))
        elif not want:
            steps.append(_step(CANT, "The church colour", f"“{said}” isn't a colour name or code that can be read."))
        elif not member_app_ui.brand_colour({"settings": {"brand_kit": {"colors": {"primary": want}}}}, {}):
            steps.append(_step(CANT, "The church colour", f"“{said}” ({want}) is too close to black, white or grey "
                                                          "for the app to wear. Ask the church for a second colour."))
        else:
            step = _step(WILL, f"Set the church colour to {said} ({want}).")
            if do:
                try:
                    brand_engine.save_brand_kit(biz_id, {**kit, "colors": {**cols, "primary": want},
                                                         "primary_color": want})
                    after = (_rows(f"/businesses?id=eq.{_q(biz_id)}&select=settings&limit=1") or [{}])[0]
                    saved = ((after.get("settings") or {}).get("brand_kit") or {}).get("primary_color") == want
                    _done(step, saved)
                    if saved:
                        kit = ((after.get("settings") or {}).get("brand_kit") or kit)
                except Exception:  # noqa: BLE001
                    logger.warning("move-in setup: the colour didn't save for %s", biz_id, exc_info=True)
                    _done(step, False)
            steps.append(step)
    pictures = [f for f in files if str(f.get("media_type") or "").startswith("image/")]
    logos = [f for f in pictures if "logo" in str(f.get("name") or "").lower()]
    assets = kit.get("assets") if isinstance(kit.get("assets"), dict) else {}
    if kit.get("logo_url") or kit.get("logo") or assets.get("primary"):
        steps.append(_step(THERE, "The church already has a logo."))
    elif len(logos) == 1:
        f = logos[0]
        step = _step(WILL, f"Set the logo from {f['name']}.")
        if do:
            raw = _storage_get(str(f["path"]))
            got = (brand_engine.upload_asset(biz_id, "primary", raw, str(f["name"]), str(f.get("media_type") or ""))
                   if raw else {"ok": False, "error": "The file couldn't be read."})
            _done(step, bool(got.get("ok")), _plain(got.get("error")))
        steps.append(step)
    elif pictures or files:
        steps.append(_step(CANT, "The logo", ("More than one file is named like a logo." if len(logos) > 1 else
                                               "No picture has “logo” in its name (a PDF can't be used). Open the "
                                               "files and set it from the church's brand.")))
    others = len(pictures) - len(logos)
    if others > 0:
        steps.append(_step(NOTE, f"{others} {'photo is' if others == 1 else 'photos are'} kept for the website, "
                                 "which follows after the first Sunday."))
    if _plain(answers.get("sermons")):
        steps.append(_step(NOTE, "The sermons link is kept for the app's sermons. Each message is added as a video link."))
    return steps, []


# ─── The whole item ───────────────────────────────────────────────────

Loader = Callable[[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]], bool], Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]
LOADERS: Dict[str, Loader] = {"sunday": _sunday, "logins": _logins, "safety": _safety, "look": _look}
NOTHING = "There's nothing to set up from this one. It's for us to read."


def can(key: str) -> bool:
    return key in LOADERS


def run(biz: Dict[str, Any], key: str, answers: Dict[str, Any], files: List[Dict[str, Any]], do: bool
        ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """The item's steps, planned (do=False) or carried out (do=True), and
    the emails still to send. A read that fails plans nothing: the answer
    says so instead of a list made on a guess."""
    if key not in LOADERS:
        return {"key": key, "can": False, "steps": [], "words": NOTHING, "will": 0}, []
    try:
        steps, mail = LOADERS[key](biz, answers or {}, files or [], do)
    except Unread:
        return {"key": key, "can": True, "steps": [], "words": UNREAD, "will": 0, "unread": True}, []
    counts = {s: sum(1 for x in steps if x["state"] == s) for s in (WILL, THERE, CANT, NOTE, MADE, FAILED)}
    words = "" if steps else "Nothing was filled in that can be set up."
    return {"key": key, "can": True, "steps": steps, "words": words, **counts}, mail


def record(biz: Dict[str, Any], key: str, answer: Dict[str, Any], by: str) -> None:
    """One line in the church's own audit log for what the platform set up."""
    try:
        import audit_log
        made = [s["what"] for s in answer.get("steps") or [] if s["state"] == MADE]
        if made:
            audit_log.record(str(biz["id"]), actor_type="system", actor_id=by or None, verb="move_in_setup",
                             summary=f"Set up from Move-in ({key}): " + " ".join(made)[:900],
                             source="mission_control", authorized_by="platform_owner")
    except Exception:  # noqa: BLE001
        logger.warning("move-in setup: the audit line didn't save for %s", biz.get("id"), exc_info=True)
