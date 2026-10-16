"""
member_spaces_kids.py — the Kids space in the member app (member_spaces).

Kevin approved the concept (https://claude.ai/artifact/74AnMSE4vsHyEFdpxLaKDi)
and its five calls 2026-10-15. Children under 13 never sign in themselves
(call 1); they come in here, through a parent.

  A PARENT (a household adult with an active child on record, kids_router)
  switches to Kids: their children, the Sunday pass (the family's live
  pickup code while a child is checked in, from kids_checkin), what each
  child learned this week (a leader's lesson for the child's room), who can
  pick them up, past Sundays, and Kids mode.

  KIDS MODE (/my/kids/play) is for the child, on the parent's phone: the
  week's Bible story (read aloud), a memory-verse game and a drawing pad.
  No messages, no links out, nothing saved on the server. A grown-up leaves
  by holding a button for three seconds (call 4). It is a soft lock for a
  child, not a security boundary: the page is the parent's own session.

  A KIDS LEADER (approved by the office for some rooms, or every room)
  sees today's roster for their rooms: first name and last initial, the
  time in, allergies, and a flag when the family has a custody note (call
  3: the notes themselves, and medical notes, stay with the office). They
  check a pickup code and release a child to someone on the family's list
  through kids_checkin.do_release, never as a manager, so a custody family
  goes to the office; and they post the week's lesson for parents.

Not here, on purpose: checking in from a phone. A child on the room roster
must be one a person saw arrive, so check-in stays with the team, the
station and the kiosk (kids_station).
"""
from __future__ import annotations

import contextvars
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

import sb_clients
import member_spaces as msp

logger = logging.getLogger("member_spaces_kids")
router = APIRouter(tags=["member-portal"])

TITLE_MAX, BODY_MAX, REF_MAX, VERSE_MAX, QUESTIONS_MAX, VIDEO_MAX = 120, 2000, 160, 400, 1000, 500
# A child still in from this morning; yesterday's check-ins are history.
LIVE_HOURS = 16
DOTS = ("k-c0", "k-c1", "k-c2", "k-c3", "k-c4")


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _ids(values) -> str:
    return ",".join(_q(v) for v in sorted({str(v) for v in values}))


def _texts(values) -> str:
    """A PostgREST in.() list of text values (a room can hold a space or
    a comma), each in double quotes."""
    return ",".join("%22" + _q(str(v).replace('"', "")) + "%22" for v in values)


def _get(path: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(path)
    return rows if isinstance(rows, list) else None


def _since(hours: int) -> str:
    return _q((datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat())


def in_rooms(room: Any, rooms: Optional[List[str]]) -> bool:
    """A leader's rooms; none listed means every room."""
    return not rooms or str(room or "").strip().casefold() in {str(r).strip().casefold() for r in rooms}


def leader_rooms(ctx: Dict[str, Any]) -> Optional[List[str]]:
    """The Kids rooms this person leads ([] = every room), or None when
    they don't lead Kids."""
    row = (ctx.get("leader") or {}).get("kids")
    return None if row is None else [str(r) for r in (row.get("rooms") or []) if str(r).strip()]


# ─── a parent's family ───────────────────────────────────────────────


def family(business_id: str, contact_id: str) -> Optional[Dict[str, Any]]:
    """This parent's households, their active children (with allergies,
    never medical or custody notes), and who may pick the children up.
    None when a read failed."""
    b = _q(business_id)
    links = _get(f"/household_adults?business_id=eq.{b}&contact_id=eq.{_q(contact_id)}&select=household_id")
    if links is None:
        return None
    hids = sorted({str(l["household_id"]) for l in links})
    out: Dict[str, Any] = {"households": hids, "children": [], "pickups": []}
    if not hids:
        return out
    kids = _get(f"/children?business_id=eq.{b}&household_id=in.({_ids(hids)})&active=eq.true"
                f"&select=id,first_name,last_name,birthdate,room,household_id&order=birthdate.asc.nullslast")
    adults = _get(f"/household_adults?business_id=eq.{b}&household_id=in.({_ids(hids)})&select=contact_id,relationship")
    extra = _get(f"/household_pickups?business_id=eq.{b}&household_id=in.({_ids(hids)})&select=name,relationship")
    if kids is None or adults is None or extra is None:
        return None
    notes: Dict[str, str] = {}
    if kids:
        rows = _get(f"/child_care_notes?business_id=eq.{b}&child_id=in.({_ids(k['id'] for k in kids)})"
                    f"&select=child_id,allergies")
        if rows is None:
            return None
        notes = {str(r["child_id"]): str(r.get("allergies") or "").strip() for r in rows}
    names: Dict[str, str] = {}
    if adults:
        people = _get(f"/contacts?business_id=eq.{b}&id=in.({_ids(a['contact_id'] for a in adults)})&select=id,name")
        if people is None:
            return None
        names = {str(p["id"]): str(p.get("name") or "").strip() for p in people}
    out["children"] = [{**k, "allergies": notes.get(str(k["id"]), "")} for k in kids]
    seen = set()
    for a in adults:
        n = names.get(str(a["contact_id"]), "")
        if n and n.casefold() not in seen:
            seen.add(n.casefold())
            out["pickups"].append({"name": n, "relationship": str(a.get("relationship") or "parent")})
    for p in extra:
        n = str(p.get("name") or "").strip()
        if n and n.casefold() not in seen:
            seen.add(n.casefold())
            out["pickups"].append({"name": n, "relationship": str(p.get("relationship") or "")})
    return out


def live(business_id: str, household_ids: List[str]) -> Optional[List[Dict[str, Any]]]:
    """The family's children checked in now (not yet picked up)."""
    if not household_ids:
        return []
    return _get(f"/child_checkins?business_id=eq.{_q(business_id)}&household_id=in.({_ids(household_ids)})"
                f"&checked_out_at=is.null&checked_in_at=gte.{_since(LIVE_HOURS)}"
                f"&select=id,child_id,room,code,checked_in_at,entry_id&order=checked_in_at.asc")


def _titles(business_id: str, entry_ids) -> Dict[str, str]:
    import kids_checkin as kc
    ids = sorted({str(i) for i in entry_ids if i})
    if not ids:
        return {}
    rows = _get(f"/module_entries?business_id=eq.{_q(business_id)}&id=in.({_ids(ids)})&select=id,data") or []
    return {str(r["id"]): kc._title(r) for r in rows}


def history(business_id: str, household_ids: List[str], limit: int = 60) -> Optional[List[Dict[str, Any]]]:
    """The family's past check-ins, newest first, with the service's name."""
    if not household_ids:
        return []
    rows = _get(f"/child_checkins?business_id=eq.{_q(business_id)}&household_id=in.({_ids(household_ids)})"
                f"&select=child_id,room,checked_in_at,checked_out_at,released_to,entry_id"
                f"&order=checked_in_at.desc&limit={int(limit)}")
    if rows is None:
        return None
    titles = _titles(business_id, (r.get("entry_id") for r in rows))
    return [{**r, "title": titles.get(str(r.get("entry_id")), "Service")} for r in rows]


def lessons(business_id: str, rooms: Optional[List[str]], limit: int = 12) -> Optional[List[Dict[str, Any]]]:
    """Leaders' lessons, newest first: for these rooms and every-room ones
    (rooms None = all of them)."""
    room_q = f"&room=in.({_texts(list(rooms) + [''])})" if rooms is not None else ""
    rows = _get(f"/space_posts?business_id=eq.{_q(business_id)}&space=eq.kids&kind=eq.lesson{room_q}"
                f"&select=id,room,title,body,scripture,verse,questions,video_url,posted_by,created_at"
                f"&order=created_at.desc&limit={int(limit)}")
    if rows is None:
        return None
    ids = sorted({str(r["posted_by"]) for r in rows if r.get("posted_by")})
    names: Dict[str, str] = {}
    if ids:
        people = _get(f"/contacts?business_id=eq.{_q(business_id)}&id=in.({_ids(ids)})&select=id,name") or []
        names = {str(p["id"]): str(p.get("name") or "") for p in people}
    for r in rows:
        r["author"] = (names.get(str(r.get("posted_by") or ""), "") or "A leader").split(" ")[0]
    return rows


def lesson_for(all_lessons: Optional[List[Dict[str, Any]]], room: Any) -> Optional[Dict[str, Any]]:
    """The newest lesson for this room (or for every room)."""
    for l in all_lessons or []:
        if not l.get("room") or str(l["room"]).casefold() == str(room or "").casefold():
            return l
    return None


# ─── a leader's room ─────────────────────────────────────────────────


def todays(business_id: str) -> Optional[List[Dict[str, Any]]]:
    import kids_station as ks
    try:
        return ks.todays_occasions(business_id)
    except HTTPException:
        return None


def roster(business_id: str, rooms: Optional[List[str]]) -> Optional[Dict[str, Any]]:
    """Today's children in this leader's rooms: in, and gone home. No
    medical or custody notes (kids_checkin._shape, not private)."""
    import kids_checkin as kc
    occ = todays(business_id)
    if occ is None:
        return None
    if not occ:
        return {"occasions": [], "rows": []}
    rows = _get(f"/child_checkins?business_id=eq.{_q(business_id)}&entry_id=in.({_ids(o['id'] for o in occ)})"
                f"&checked_in_at=gte.{_since(LIVE_HOURS)}&select=*&order=checked_in_at.asc&limit=600")
    if rows is None:
        return None
    rows = [r for r in rows if in_rooms(r.get("room"), rooms)]
    try:
        shaped = kc._shape(rows, str(business_id), False)
    except HTTPException:
        return None
    titles = {str(o["id"]): o["title"] for o in occ}
    for s, r in zip(shaped, rows):
        s["occasion"] = titles.get(str(r.get("entry_id")), "")
        s.pop("custody", None)
        s.pop("code", None)                 # the code is the parent's, read off their phone or tag
    return {"occasions": occ, "rows": shaped}


def find_code(business_id: str, code: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(today's occasion holding children with this pickup code, error)."""
    import kids_checkin as kc
    occ = todays(business_id)
    if occ is None:
        return None, "unavailable"
    for o in occ:
        try:
            if kc._waiting(str(business_id), o["id"], code):
                return o, None
        except HTTPException:
            return None, "unavailable"
    return None, "not_found"


# ─── the week's story, when no leader has posted one ─────────────────

# Retold in our own words; the verses are the King James Version.
STORIES: Tuple[Dict[str, Any], ...] = (
    {"title": "God made everything", "ref": "Genesis 1",
     "story": "In the beginning, God made everything: light and dark, sky and sea, land and plants, the sun, the "
              "moon and the stars, fish and birds and every animal. Last of all, God made people. God looked at "
              "everything he had made, and it was very good.",
     "verse": "In the beginning God created the heaven and the earth.", "verse_ref": "Genesis 1:1",
     "questions": ["What is your favorite thing God made?", "How can we take care of what God made?"]},
    {"title": "Noah builds the ark", "ref": "Genesis 6 to 9",
     "story": "God told Noah to build a huge boat called an ark. Noah obeyed, even when other people didn't "
              "understand. Noah's family and two of every kind of animal went inside, and it rained for forty "
              "days and forty nights. When the water went down, God put a rainbow in the sky as a promise.",
     "verse": "The LORD is good to all: and his tender mercies are over all his works.", "verse_ref": "Psalm 145:9",
     "questions": ["What did Noah do when God asked him?", "What does a rainbow remind us of?"]},
    {"title": "David and Goliath", "ref": "1 Samuel 17",
     "story": "A giant soldier named Goliath scared everyone in Israel's army. David was just a young shepherd, "
              "but he knew God was with him. With a sling and one smooth stone, David stopped the giant. David "
              "was brave because he trusted God.",
     "verse": "What time I am afraid, I will trust in thee.", "verse_ref": "Psalm 56:3",
     "questions": ["What made David brave?", "When do you need to be brave?"]},
    {"title": "Daniel and the lions", "ref": "Daniel 6",
     "story": "Daniel prayed to God every day, even when a new law said he couldn't. So Daniel was put in a den "
              "of hungry lions. But God sent an angel to shut the lions' mouths, and in the morning Daniel was "
              "safe.",
     "verse": "My God hath sent his angel, and hath shut the lions' mouths.", "verse_ref": "Daniel 6:22",
     "questions": ["What did Daniel keep doing every day?", "When can you talk to God?"]},
    {"title": "Jonah and the big fish", "ref": "Jonah 1 to 3",
     "story": "God asked Jonah to go to the city of Nineveh, but Jonah got on a ship going the other way. A big "
              "storm came, and a great fish swallowed Jonah. Inside the fish, Jonah prayed, and God gave him a "
              "second chance. This time Jonah went where God sent him.",
     "verse": "Salvation is of the LORD.", "verse_ref": "Jonah 2:9",
     "questions": ["Where did Jonah pray?", "Has someone ever given you a second chance?"]},
    {"title": "Jesus calms the storm", "ref": "Mark 4",
     "story": "Jesus and his friends were crossing the lake in a boat when a big storm came. Waves splashed in, "
              "and his friends were scared. Jesus stood up and spoke to the wind and the waves, and everything "
              "became calm.",
     "verse": "Peace, be still.", "verse_ref": "Mark 4:39",
     "questions": ["What did Jesus say to the storm?", "What can you do when you feel scared?"]},
    {"title": "A boy shares his lunch", "ref": "John 6",
     "story": "A big crowd came to hear Jesus, and they got hungry. A boy shared his lunch: five small loaves of "
              "bread and two fish. Jesus thanked God and shared it out, and everyone ate until they were full, "
              "with twelve baskets left over.",
     "verse": "I am the bread of life.", "verse_ref": "John 6:35",
     "questions": ["What did the boy share?", "What can you share this week?"]},
    {"title": "The lost sheep", "ref": "Luke 15",
     "story": "A shepherd had one hundred sheep, and one went missing. He left the ninety-nine to look for the "
              "one until he found it. Then he carried it home on his shoulders and threw a party. Jesus said God "
              "loves each of us like that.",
     "verse": "For the Son of man is come to seek and to save that which was lost.", "verse_ref": "Luke 19:10",
     "questions": ["How did the shepherd feel when he found his sheep?", "How does God feel about you?"]},
)


def week_key(today: Optional[date] = None) -> str:
    y, w, _ = (today or date.today()).isocalendar()
    return f"{y}-{w:02d}"


def story_of_week(today: Optional[date] = None) -> Dict[str, Any]:
    y, w, _ = (today or date.today()).isocalendar()
    return STORIES[(y * 53 + w) % len(STORIES)]


# A reference typed at the end of a verse ("... be not afraid. Joshua 1:9"),
# so the verse game never blanks out the book's name.
_REF_TAIL = re.compile(r"[\s(–—-]*((?:[1-3] ?)?[A-Z][a-z]+(?: [A-Z][a-z]+)* \d{1,3}:\d{1,3}(?:[-–]\d{1,3})?)\)?\s*$")


def split_ref(verse: str) -> Tuple[str, str]:
    """(the verse, its reference) from what a leader typed."""
    v = (verse or "").strip()
    m = _REF_TAIL.search(v)
    if not m or m.start() == 0:
        return v, ""
    return v[:m.start()].rstrip(" -–—("), m.group(1)


def as_story(lesson: Optional[Dict[str, Any]], today: Optional[date] = None) -> Dict[str, Any]:
    """The week's story for a child: their room's lesson, else one of ours."""
    base = story_of_week(today)
    if not lesson:
        return {**base, "from_leader": False}
    qs = [q.strip(" -•\t") for q in str(lesson.get("questions") or "").splitlines() if q.strip(" -•\t")]
    verse, vref = split_ref(lesson.get("verse") or "")
    return {"title": lesson.get("title") or base["title"], "ref": lesson.get("scripture") or "",
            "story": lesson.get("body") or "", "verse": verse or base["verse"],
            "verse_ref": vref if verse else base["verse_ref"],
            "questions": qs[:5], "video_url": lesson.get("video_url") or "", "from_leader": True,
            "author": lesson.get("author") or ""}


# ─── pages ───────────────────────────────────────────────────────────


def _dot(i: int, name: str) -> str:
    from member_portal import _e
    import member_app_ui as ui
    return f'<span class="k-dot {DOTS[i % len(DOTS)]}" aria-hidden="true">{_e(ui.initials(name)[:1])}</span>'


def _age(child: Dict[str, Any]) -> str:
    a = msp.age(child)
    return f" · {a}" if a is not None else ""


def _hm(iso: Any) -> str:
    """'9:52 AM' on the church's clock."""
    try:
        t = _local(datetime.fromisoformat(str(iso).replace("Z", "+00:00")))
    except ValueError:
        return ""
    return f'{t.hour % 12 or 12}:{t.minute:02d} {"AM" if t.hour < 12 else "PM"}'


# The church's clock for the page being drawn (set per request).
_ZONE: contextvars.ContextVar[Any] = contextvars.ContextVar("kids_zone", default=None)


def set_zone(biz: Dict[str, Any]) -> None:
    """The church's timezone, for the times on a roster and a history: its
    booking hours' timezone, else the platform's default, else US Eastern.
    (No owner-profile read: a time on a roster is not worth a second trip.)"""
    import os
    from zoneinfo import ZoneInfo
    avail = ((biz or {}).get("settings") or {}).get("availability") or {}
    for name in ((avail.get("timezone") if isinstance(avail, dict) else None),
                 os.environ.get("PLATFORM_DEFAULT_TZ"), "America/New_York"):
        try:
            if name:
                _ZONE.set(ZoneInfo(str(name)))
                return
        except Exception:
            continue


def _local(t: datetime) -> datetime:
    z = _ZONE.get()
    if z is None:
        from zoneinfo import ZoneInfo
        z = ZoneInfo("America/New_York")
    return t.astimezone(z)


def _day_label(iso: Any) -> str:
    try:
        t = _local(datetime.fromisoformat(str(iso).replace("Z", "+00:00")))
    except ValueError:
        return ""
    return f'{t.strftime("%a")} {t.strftime("%b")} {t.day}'


def _lesson_card(story: Dict[str, Any], who: str, *, kick: str = "", extra: str = "") -> str:
    from member_portal import _e
    kick = kick or (f"This week {who} learned" if story.get("from_leader") else "A story for this week")
    ref = f' <span class="k-ref">{_e(story.get("ref"))}</span>' if story.get("ref") else ""
    cite = f' <cite>{_e(story["verse_ref"])}</cite>' if story.get("verse_ref") else ""
    verse = (f'<blockquote class="k-verse">&ldquo;{_e(story["verse"])}&rdquo;{cite}</blockquote>'
             if story.get("verse") else "")
    qs = "".join(f"<li>{_e(q)}</li>" for q in story.get("questions") or [])
    qs = f'<p class="k-sub">Talk about it at dinner</p><ol class="k-qs">{qs}</ol>' if qs else ""
    video = (f'<a class="k-link" href="{_e(story["video_url"])}" target="_blank" rel="noopener">Watch the lesson video</a>'
             if str(story.get("video_url") or "").startswith("https://") else "")
    return (f'<article class="k-card"><p class="k-kick k-sky">{_e(kick)}</p><h3>{_e(story["title"])}</h3>'
            f'<p class="k-body">{_e(story.get("story"))}{ref}</p>{verse}{qs}{video}{extra}</article>')


def _pass(fam: Dict[str, Any], live_rows: Optional[List[Dict[str, Any]]], occasions) -> str:
    """The Sunday pass: the live pickup code while a child is in; else how
    check-in works."""
    from member_portal import _e
    kids = {str(k["id"]): k for k in fam["children"]}
    rows = [r for r in (live_rows or []) if str(r.get("child_id")) in kids]
    if rows:
        code = str(rows[0].get("code") or "")
        boxes = "".join(f"<b>{_e(c)}</b>" for c in code)
        items = "".join(f'<li><strong>{_e(kids[str(r["child_id"])]["first_name"])}</strong>'
                        f'<span>{_e(r.get("room") or "")}{" · " if r.get("room") else ""}in at {_e(_hm(r.get("checked_in_at")))}</span></li>'
                        for r in rows)
        return (f'<section class="k-pass" aria-labelledby="k-pass-h"><p class="k-kick">Checked in</p>'
                f'<h2 id="k-pass-h">Pickup code</h2><div class="k-code" aria-label="Pickup code {_e(" ".join(code))}">{boxes}</div>'
                f'<p>Show this code at pickup. It matches the tag and the text.</p><ul class="k-in">{items}</ul></section>')
    nxt = next((o for o in occasions or [] if o.get("title")), None)
    when = ""
    if nxt:
        import member_portal_church as mpc
        d = mpc._day(nxt.get("date") or "")
        when = f'{d.strftime("%A")}, {d.strftime("%b")} {d.day}' if d else (nxt.get("date_label") or "")
    title = _e(nxt.get("title")) if nxt else "Sunday pass"
    return (f'<section class="k-pass" aria-labelledby="k-pass-h"><p class="k-kick">Sunday pass</p>'
            f'<h2 id="k-pass-h">{title}</h2>{f"<p class=k-when>{_e(when)}</p>" if when else ""}'
            f'<p>Check in at the kids\' door: a team member checks you in, or type your mobile number at the '
            f'kiosk. Your pickup code shows here once they\'re in.</p></section>')


def _family_home(biz, fam: Dict[str, Any], live_rows, occasions, all_lessons) -> str:
    from member_portal import _e
    import member_app_ui as ui
    kids = fam["children"]
    chips = "".join(f'<span class="k-chip">{_dot(i, k["first_name"])}{_e(k["first_name"])}{_e(_age(k))}</span>'
                    for i, k in enumerate(kids))
    cards = []
    shown = set()
    for k in kids:
        st = as_story(lesson_for(all_lessons, k.get("room")))
        key = st["title"]
        if key in shown:
            continue
        shown.add(key)
        who = k["first_name"] if st.get("from_leader") else ""
        same = [x["first_name"] for x in kids if as_story(lesson_for(all_lessons, x.get("room")))["title"] == key]
        who = " and ".join(same[:2]) if len(same) > 1 else who
        cards.append(_lesson_card(st, who))
    play = (f'<a class="k-play" href="/my/kids/play">{ui.icon("play", 28)}<span><b>Kids mode</b>'
            f'<small>The story, a verse game and drawing. A grown-up holds a button to leave.</small></span></a>')
    return (f'<div class="k-chips">{chips}</div>{_pass(fam, live_rows, occasions)}{play}{"".join(cards)}')


def _leader_home(biz, ctx, ros: Optional[Dict[str, Any]], flash: str = "") -> str:
    from member_portal import _e
    import member_app_ui as ui
    rooms = leader_rooms(ctx) or []
    place = " · ".join(rooms) if rooms else "Every room"
    if ros is None:
        return (f'<h1 class="k-hello">{_e(place)}</h1>{flash}<p class="mp-err" role="alert">'
                f'Today\'s rooms couldn\'t load just now. Pull down to try again.</p>')
    rows = ros["rows"]
    occ = ros["occasions"]
    title = rows[0]["occasion"] if rows else (occ[0]["title"] if occ else "")
    head = f'<h1 class="k-hello">{_e(place)}{f"<br><span>{_e(title)}</span>" if title else ""}</h1>'
    here = [r for r in rows if not r.get("checked_out_at")]
    gone = [r for r in rows if r.get("checked_out_at")]
    band = (f'<div class="k-band"><span>{"Today" if occ else "No service today"}</span>'
            f'<b>{len(here)} {"kid" if len(here) == 1 else "kids"} in</b>{ui.icon("check", 20)}</div>')

    def row(r: Dict[str, Any], i: int) -> str:
        name = f'{r["first_name"]} {(r.get("last_name") or "")[:1]}.'.replace(" .", "")
        if r.get("checked_out_at"):
            flag = f'<span class="k-flag k-gone">Home with {_e((r.get("released_to") or "family").split(" ")[0])}</span>'
            sub = f'Out at {_e(_hm(r["checked_out_at"]))}'
        else:
            sub = f'In at {_e(_hm(r["checked_in_at"]))}{" · " + _e(r["room"]) if r.get("room") and len(rooms) != 1 else ""}'
            if r.get("custody_alert"):
                flag = '<span class="k-flag k-office">Office at pickup</span>'
            elif (r.get("allergies") or "").strip():
                flag = f'<span class="k-flag k-allergy" title="{_e(r["allergies"])}">{_e(r["allergies"])}</span>'
            else:
                flag = '<span class="k-flag k-ready">Ready</span>'
        return f'<div class="k-row">{_dot(i, r["first_name"])}<span><b>{_e(name)}</b><small>{sub}</small></span>{flag}</div>'
    listed = "".join(row(r, i) for i, r in enumerate(here + gone))
    roster_html = (f'<div class="k-roster">{listed}</div>' if listed else
                   '<p class="k-empty">Nobody is checked in to your rooms yet. They show here as the team checks them in.</p>')
    pick = ('<h2 class="k-h2">Pickup</h2><form class="k-pick" method="post" action="/my/kids/pickup">'
            '<label class="mp-sr" for="k-code">Parent\'s pickup code</label>'
            '<input class="mp-input" id="k-code" name="code" inputmode="text" autocomplete="off" autocapitalize="characters" '
            'maxlength="4" minlength="4" placeholder="4-letter code" required>'
            '<button class="k-btn" type="submit">Check</button></form>')
    post = ('<a class="k-card k-post-link" href="/my/kids/stories#k-post"><p class="k-kick k-sky">For parents</p>'
            '<h3>Post this week\'s lesson</h3><p class="k-body">It shows on the parents\' phones: the story, the verse, '
            'questions for dinner.</p></a>')
    bg = (ctx.get("leader") or {}).get("kids") or {}
    safe = (f'<p class="k-safe">{ui.icon("shield", 17)}<span>You see first names and allergies. Medical and custody '
            f'notes stay with the church office. Background check on file, {_e(msp._month(bg.get("background_check_on")))}.</span></p>')
    return f'{head}{flash}{band}{roster_html}{pick}{post}{safe}'


def render_home(biz, site, *, me, ctx, fam, live_rows, occasions, all_lessons, ros, flash: str = "") -> str:
    from member_portal import _e, _shell, first_name
    parts = []
    if leader_rooms(ctx) is not None:
        parts.append(_leader_home(biz, ctx, ros, flash))
        flash = ""
    if ctx.get("kids_parent"):
        if fam is None:
            parts.append('<p class="mp-err" role="alert">Your family couldn\'t load just now. Pull down to try again.</p>')
        elif fam["children"]:
            hello = "" if parts else f'<h1 class="k-hello">Hi, <span>{_e(first_name(me.get("name") or "") or "there")}</span></h1>{flash}'
            parts.append((f'<h2 class="k-h2">Your family</h2>' if hello == "" else hello)
                         + _family_home(biz, fam, live_rows, occasions, all_lessons))
    return _shell(biz, site, "Kids", "".join(parts), tab="home", who=me)


def render_stories(biz, site, request: Request, *, me, ctx, fam, all_lessons) -> str:
    """Lessons for the children's rooms (a parent), or a leader's lessons
    with the form to post this week's."""
    from member_portal import _e, _shell
    import member_portal_church as mpc
    rooms = leader_rooms(ctx)
    form = ""
    if rooms is not None:
        choices = rooms or []
        if choices:
            opts = "".join(f'<option value="{_e(r)}">{_e(r)}</option>' for r in choices)
            room_field = (f'<label for="k-room">Room</label><select class="mp-input" id="k-room" name="room">{opts}</select>'
                          if len(choices) > 1 else f'<input type="hidden" name="room" value="{_e(choices[0])}">')
        else:
            room_field = '<input type="hidden" name="room" value="">'
        form = (f'<form class="k-form" id="k-post" method="post" action="/my/kids/lesson">'
                f'<p class="k-kick k-sky">Post this week\'s lesson</p>{room_field}'
                f'<label for="k-t">Title</label><input class="mp-input" id="k-t" name="title" maxlength="{TITLE_MAX}" '
                f'placeholder="David and Goliath" required>'
                f'<label for="k-s">Scripture</label><input class="mp-input" id="k-s" name="scripture" maxlength="{REF_MAX}" '
                f'placeholder="1 Samuel 17">'
                f'<label for="k-b">What they learned</label><textarea class="mp-input" id="k-b" name="body" rows="4" '
                f'maxlength="{BODY_MAX}" placeholder="Being brave because God is with you." required></textarea>'
                f'<label for="k-v">Memory verse</label><textarea class="mp-input" id="k-v" name="verse" rows="2" '
                f'maxlength="{VERSE_MAX}" placeholder="What time I am afraid, I will trust in thee. Psalm 56:3"></textarea>'
                f'<label for="k-qs">Questions for dinner (one a line)</label><textarea class="mp-input" id="k-qs" name="questions" '
                f'rows="3" maxlength="{QUESTIONS_MAX}" placeholder="What was David\'s giant?&#10;When do you need to be brave?"></textarea>'
                f'<label for="k-vid">Video link (optional)</label><input class="mp-input" id="k-vid" name="video_url" type="url" '
                f'maxlength="{VIDEO_MAX}" placeholder="https://">'
                f'<button class="k-btn" type="submit">Post for parents</button>'
                f'<p class="k-fine">Parents of children in {"that room" if len(choices) == 1 else "the room you choose" if choices else "every room"} '
                f'see it on their phones. It\'s checked before it shows, like every message.</p></form>')
    items = []
    for l in all_lessons or []:
        st = as_story(l)
        mine = rooms is not None and str(l.get("posted_by")) == str(me.get("id"))
        remove = (f'<form method="post" action="/my/kids/lesson/remove" class="y-post-x"><input type="hidden" name="id" value="{_e(l["id"])}">'
                  f'<button class="mp-link" type="submit">Remove</button></form>' if mine else "")
        kick = f'{_day_label(l.get("created_at"))} · {l.get("room") or "Every room"} · {l.get("author") or "A leader"}'
        items.append(_lesson_card(st, "", kick=kick, extra=remove))
    if not items:
        st = as_story(None)
        items.append(_lesson_card(st, "", kick="A story for this week"))
    play = ('<a class="k-play" href="/my/kids/play"><span><b>Kids mode</b><small>The story, a verse game and drawing.'
            '</small></span></a>') if ctx.get("kids_parent") else ""
    return _shell(biz, site, "Stories", f'<div class="mb-lt"><h1>Stories</h1></div>{mpc._flash(request)}{form}{play}{"".join(items)}',
                  tab="stories", who=me)


def render_sundays(biz, site, *, me, ctx, fam, past) -> str:
    """A parent's past Sundays: who came, the room, when they went home and
    with whom."""
    from member_portal import _e, _shell
    if fam is None or past is None:
        body = '<p class="mp-err" role="alert">Your Sundays couldn\'t load just now. Pull down to try again.</p>'
    elif not past:
        body = '<p class="k-empty">Your children\'s check-ins show here: the room, and who picked them up.</p>'
    else:
        kids = {str(k["id"]): k for k in fam["children"]}
        days: Dict[str, List[Dict[str, Any]]] = {}
        for r in past:
            days.setdefault(f'{_day_label(r["checked_in_at"])} · {r["title"]}', []).append(r)
        blocks = []
        for label, rows in days.items():
            lines = "".join(
                f'<li><b>{_e((kids.get(str(r["child_id"])) or {}).get("first_name") or "Your child")}</b>'
                f'<span>{_e(r.get("room") or "")}{" · " if r.get("room") else ""}in {_e(_hm(r["checked_in_at"]))}'
                f'{(" · home " + _e(_hm(r["checked_out_at"])) + (" with " + _e(r["released_to"]) if r.get("released_to") else "")) if r.get("checked_out_at") else ""}'
                f'</span></li>' for r in rows)
            blocks.append(f'<section class="k-day"><h2>{_e(label)}</h2><ul>{lines}</ul></section>')
        body = "".join(blocks)
    return _shell(biz, site, "Sundays", f'<div class="mb-lt"><h1>Sundays</h1></div>{body}', tab="sundays", who=me)


def render_family(biz, site, *, me, fam) -> str:
    from member_portal import _e, _shell
    if fam is None:
        body = '<p class="mp-err" role="alert">Your family couldn\'t load just now. Pull down to try again.</p>'
    else:
        cards = []
        for i, k in enumerate(fam["children"]):
            facts = " · ".join(x for x in ((f"Age {msp.age(k)}" if msp.age(k) is not None else ""), k.get("room") or "") if x)
            allergy = (f'<p class="k-al"><span class="k-flag k-allergy">Allergies</span>{_e(k["allergies"])}</p>'
                       if k.get("allergies") else '<p class="k-al k-fine">No allergies on record.</p>')
            cards.append(f'<article class="k-card k-kid">{_dot(i, k["first_name"])}<div><h3>{_e(k["first_name"])} '
                         f'{_e(k.get("last_name") or "")}</h3><p class="k-fine">{_e(facts)}</p>{allergy}</div></article>')
        who = "".join(f'<li><b>{_e(p["name"])}</b><span>{_e(p.get("relationship") or "")}</span></li>' for p in fam["pickups"])
        body = ("".join(cards) +
                f'<h2 class="k-h2">Who can pick up</h2><ul class="k-list">{who}</ul>'
                f'<p class="k-fine">To change a room, an allergy or who can pick up, tell the church office. '
                f'Medical and custody notes are kept by the office only.</p>')
    return _shell(biz, site, "Family", f'<div class="mb-lt"><h1>Family</h1></div>{body}', tab="family", who=me)


def render_play(biz, site, *, me, fam, all_lessons, child_id: str = "") -> str:
    """Kids mode, for one child. With more than one child and none chosen,
    'Who's playing?' first."""
    from member_portal import _e, _shell
    kids = (fam or {}).get("children") or []
    child = next((k for k in kids if str(k["id"]) == child_id), None) or (kids[0] if len(kids) == 1 else None)
    hold = ('<button class="k-hold" id="k-hold" type="button"><span>Grown-ups: hold to leave Kids mode</span></button>')
    if child is None:
        picks = "".join(f'<a class="k-tile {("k-coral", "k-grass", "k-grape", "k-sun")[i % 4]}" href="/my/kids/play?child={_e(k["id"])}">'
                        f'<b>{_e(k["first_name"])}</b><small>Tap to play</small></a>' for i, k in enumerate(kids))
        body = (f'<h1>Who\'s playing?</h1><div class="k-tiles">{picks}</div>{hold}' if kids else
                f'<h1>Kids mode</h1><p class="k-lead">Your children show here once the church adds them to your family.</p>{hold}')
        return _shell(biz, site, "Kids mode", f'<div class="k-mode-in">{body}</div>', bare=True, bar=False, tab="play", who=me,
                      script=PLAY_JS)
    st = as_story(lesson_for(all_lessons, child.get("room")))
    data = json.dumps({"child": str(child["id"]), "week": week_key(),
                       "story": f'{st["title"]}. {st.get("story") or ""}', "verse": st["verse"]}).replace("<", "\\u003c")
    ref = f' <cite>{_e(st.get("verse_ref") or st.get("ref") or "")}</cite>' if (st.get("verse_ref") or st.get("ref")) else ""
    crayons = "".join(f'<button type="button" class="k-crayon" data-col="{c}" style="background:{c}" aria-label="{n}"'
                      f'{" aria-pressed=true" if i == 0 else ""}></button>'
                      for i, (c, n) in enumerate((("#ff6b6b", "Red"), ("#ffc83d", "Yellow"), ("#3cc47c", "Green"),
                                                   ("#4cc3ff", "Blue"), ("#7c5cff", "Purple"), ("#2b1d0e", "Brown"))))
    body = f"""
<p class="k-stars"><span aria-hidden="true">★</span> <span id="k-stars-n">0</span> <span id="k-stars-w">stars</span> this week</p>
<h1>Hi, {_e(child["first_name"])}!</h1>
<p class="k-lead">What do you want to do?</p>
<div class="k-tiles" id="k-tiles">
  <button type="button" class="k-tile k-coral wide" data-open="story"><b>Today's Bible story</b><small>{_e(st["title"])} · listen</small></button>
  <button type="button" class="k-tile k-grass" data-open="verse"><b>Memory verse game</b><small>Fill in the words</small></button>
  <button type="button" class="k-tile k-grape" data-open="draw"><b>Draw the story</b><small>Pick a crayon</small></button>
</div>
<section class="k-panel" id="kp-story" hidden>
  <button type="button" class="k-back" data-close>‹ Back</button>
  <h2>{_e(st["title"])}</h2>
  <p class="k-tell">{_e(st.get("story") or "")}</p>
  <button type="button" class="k-big" id="k-listen">Listen to the story</button>
</section>
<section class="k-panel" id="kp-verse" hidden>
  <button type="button" class="k-back" data-close>‹ Back</button>
  <h2>Memory verse</h2>
  <p class="k-versegame" id="k-verse" aria-live="polite"></p>{ref}
  <div class="k-chipset" id="k-chips"></div>
  <p class="k-yay" id="k-yay" hidden>You did it! ★</p>
</section>
<section class="k-panel" id="kp-draw" hidden>
  <button type="button" class="k-back" data-close>‹ Back</button>
  <h2>Draw {_e(st["title"])}</h2>
  <canvas class="k-canvas" id="k-canvas" aria-label="Drawing pad"></canvas>
  <div class="k-crayons">{crayons}<button type="button" class="k-clear" id="k-clear">Start over</button></div>
  <button type="button" class="k-big" id="k-done">I'm done!</button>
</section>
{hold}
<script type="application/json" id="k-data">{data}</script>"""
    return _shell(biz, site, "Kids mode", f'<div class="k-mode-in">{body}</div>', bare=True, bar=False, tab="play", who=me,
                  script=PLAY_JS)


# The child's side: panels, the read-aloud, the verse game, the drawing pad,
# stars kept on this phone only, and the three-second hold out (call 4).
PLAY_JS = r"""<script>(function(){
document.body.classList.add('k-mode');
var el=document.getElementById('k-data'),D=el?JSON.parse(el.textContent):null;
var key=D?('sol_stars_'+D.child+'_'+D.week):'';
function stars(){try{return +(localStorage.getItem(key)||0)}catch(e){return 0}}
function show(){var n=document.getElementById('k-stars-n'),w=document.getElementById('k-stars-w'),v=stars();if(n)n.textContent=v;if(w)w.textContent=v===1?'star':'stars';}
function add(){if(!D)return;try{localStorage.setItem(key,String(stars()+1))}catch(e){}show();}
show();
var tiles=document.getElementById('k-tiles');
function fit(){var cv=document.getElementById('k-canvas');if(!cv)return;var r=cv.getBoundingClientRect(),d=window.devicePixelRatio||1;
 if(cv.width===Math.round(r.width*d))return;cv.width=Math.round(r.width*d);cv.height=Math.round(r.height*d);
 var c=cv.getContext('2d');c.setTransform(d,0,0,d,0,0);c.fillStyle='#fff';c.fillRect(0,0,r.width,r.height);}
document.querySelectorAll('[data-open]').forEach(function(b){b.addEventListener('click',function(){
 if(!tiles)return;tiles.hidden=true;var p=document.getElementById('kp-'+b.getAttribute('data-open'));p.hidden=false;window.scrollTo(0,0);
 if(b.getAttribute('data-open')==='draw')fit();});});
document.querySelectorAll('[data-close]').forEach(function(b){b.addEventListener('click',function(){
 b.closest('.k-panel').hidden=true;tiles.hidden=false;if(window.speechSynthesis)speechSynthesis.cancel();});});
var lb=document.getElementById('k-listen');
if(lb){if(!('speechSynthesis' in window)){lb.hidden=true;}else{var heard=false;lb.addEventListener('click',function(){
 speechSynthesis.cancel();var u=new SpeechSynthesisUtterance(D.story);u.rate=0.9;u.onend=function(){if(!heard){heard=true;add();}};speechSynthesis.speak(u);});}}
var box=document.getElementById('k-verse'),chips=document.getElementById('k-chips');
if(box&&D){var words=D.verse.split(/\s+/).filter(Boolean),ok=[],blanks=[];
 words.forEach(function(w,i){var m=w.match(/[A-Za-z']+/);if(m&&m[0].length>=4)ok.push(i);});
 var pick=ok.filter(function(_,j){return j%2===0;}).slice(0,4);if(!pick.length&&ok.length)pick=[ok[0]];
 words.forEach(function(w,i){var s=document.createElement('span');var m=w.match(/[A-Za-z']+/);
  if(pick.indexOf(i)>=0&&m){var pre=w.slice(0,m.index),post=w.slice(m.index+m[0].length);s.className='k-blank';
   s.setAttribute('data-word',m[0]);s.setAttribute('data-fill',pre+m[0]+post);s.textContent=pre+'_____'+post;blanks.push(s);}
  else{s.textContent=w;}box.appendChild(s);box.appendChild(document.createTextNode(' '));});
 var order=blanks.map(function(b){return b.getAttribute('data-word');}).slice().sort(function(){return Math.random()-0.5;});
 order.forEach(function(w){var c=document.createElement('button');c.type='button';c.className='k-wchip';c.textContent=w;
  c.addEventListener('click',function(){var next=blanks.filter(function(b){return !b.classList.contains('done');})[0];if(!next)return;
   if(next.getAttribute('data-word').toLowerCase()===w.toLowerCase()){next.textContent=next.getAttribute('data-fill');next.classList.add('done');c.disabled=true;
    if(!blanks.some(function(b){return !b.classList.contains('done');})){document.getElementById('k-yay').hidden=false;add();}}
   else{c.classList.remove('no');void c.offsetWidth;c.classList.add('no');}});chips.appendChild(c);});}
var cv=document.getElementById('k-canvas');
if(cv){var cx=cv.getContext('2d'),col='#ff6b6b',down=false,last=null,starred=false;
 function pt(e){var r=cv.getBoundingClientRect();return{x:e.clientX-r.left,y:e.clientY-r.top};}
 function line(a,b){cx.strokeStyle=col;cx.lineWidth=9;cx.lineCap='round';cx.lineJoin='round';cx.beginPath();cx.moveTo(a.x,a.y);cx.lineTo(b.x,b.y);cx.stroke();}
 cv.addEventListener('pointerdown',function(e){fit();down=true;last=pt(e);try{cv.setPointerCapture(e.pointerId)}catch(x){}line(last,{x:last.x+0.1,y:last.y});});
 cv.addEventListener('pointermove',function(e){if(!down)return;var p=pt(e);line(last,p);last=p;});
 ['pointerup','pointercancel'].forEach(function(n){cv.addEventListener(n,function(){down=false;});});
 document.querySelectorAll('.k-crayon').forEach(function(b){b.addEventListener('click',function(){col=b.getAttribute('data-col');
  document.querySelectorAll('.k-crayon').forEach(function(o){o.setAttribute('aria-pressed',o===b?'true':'false');});});});
 document.getElementById('k-clear').addEventListener('click',function(){var r=cv.getBoundingClientRect();cx.fillStyle='#fff';cx.fillRect(0,0,r.width,r.height);});
 document.getElementById('k-done').addEventListener('click',function(){if(!starred){starred=true;add();}document.querySelector('#kp-draw [data-close]').click();});}
var h=document.getElementById('k-hold'),t=null;
if(h){function go(e){if(e)e.preventDefault();h.classList.add('on');t=setTimeout(function(){location.href='/my';},3000);}
 function stop(){h.classList.remove('on');clearTimeout(t);}
 h.addEventListener('pointerdown',go);['pointerup','pointerleave','pointercancel'].forEach(function(n){h.addEventListener(n,stop);});
 h.addEventListener('keydown',function(e){if((e.key===' '||e.key==='Enter')&&!e.repeat)go(e);});h.addEventListener('keyup',stop);
 h.addEventListener('click',function(e){e.preventDefault();});h.addEventListener('contextmenu',function(e){e.preventDefault();});}
try{history.pushState({k:1},'',location.href);window.addEventListener('popstate',function(){history.pushState({k:1},'',location.href);});}catch(e){}
})();</script>"""


def render_pickup(biz, site, *, me, code: str = "", found: Optional[Dict[str, Any]] = None,
                  entry_id: str = "", rooms: Optional[List[str]] = None, error: str = "") -> str:
    """A leader's pickup check: the children waiting with this code in
    their rooms, and who they may go home with."""
    from member_portal import _e, _shell
    import member_app_ui as ui
    back = '<a class="mb-back" href="/my">Room</a>'
    again = ('<form class="k-pick" method="post" action="/my/kids/pickup"><label class="mp-sr" for="k-code">Pickup code</label>'
             f'<input class="mp-input" id="k-code" name="code" maxlength="4" minlength="4" autocomplete="off" value="{_e(code)}" required>'
             '<button class="k-btn" type="submit">Check</button></form>')
    if error or not found:
        msg = error or "No child is waiting with that code."
        return _shell(biz, site, "Pickup", f'{back}<div class="mb-lt"><h1>Pickup</h1></div>'
                      f'<p class="mp-err mp-flash" role="alert">{_e(msg)}</p>{again}', tab="home", who=me)
    kids = [c for c in found["children"] if in_rooms(c.get("room"), rooms)]
    elsewhere = [c for c in found["children"] if not in_rooms(c.get("room"), rooms)]
    other = (f'<p class="k-fine">{_e(", ".join(c["first_name"] + " (" + (c.get("room") or "another room") + ")" for c in elsewhere))}: '
             f'pickup is at their room.</p>' if elsewhere else "")
    if not kids:
        return _shell(biz, site, "Pickup", f'{back}<div class="mb-lt"><h1>Pickup</h1></div>'
                      f'<p class="mp-err mp-flash" role="alert">Those children aren\'t in your rooms.</p>{other}{again}',
                      tab="home", who=me)
    def kid(c: Dict[str, Any]) -> str:
        allergy = f'<em class="k-flag k-allergy">{_e(c["allergies"])}</em>' if c.get("allergies") else ""
        return (f'<label class="k-kidpick"><input type="checkbox" name="checkin_id" value="{_e(c["id"])}" checked>'
                f'<b>{_e(c["first_name"])} {_e((c.get("last_name") or "")[:1])}.</b><span>{_e(c.get("room") or "")}</span>'
                f'{allergy}</label>')
    names = "".join(kid(c) for c in kids)
    if found.get("custody_alert"):
        body = (f'<div class="k-card"><p class="k-kick">Code {_e(code)}</p><div class="k-who">{names}</div></div>'
                f'<p class="k-safe k-stop">{ui.icon("shield", 17)}<span>This family has a note with the church office. '
                f'A manager releases these children. Keep them with you and get the office.</span></p>')
    else:
        allowed = "".join(f'<label><input type="radio" name="released_to" value="{_e(a["name"])}" required>'
                          f'<b>{_e(a["name"])}</b><span>{_e(a.get("relationship") or "")}</span></label>'
                          for a in found.get("allowed") or [] if a.get("name"))
        body = (f'<form class="k-form" method="post" action="/my/kids/release">'
                f'<input type="hidden" name="code" value="{_e(code)}"><input type="hidden" name="entry_id" value="{_e(entry_id)}">'
                f'<p class="k-kick">Code {_e(code)} · {_e(found.get("family") or "")}</p><div class="k-who">{names}</div>'
                f'<p class="k-sub">Going home with</p><div class="k-who">{allowed}</div>'
                f'<button class="k-btn" type="submit">Release</button>'
                f'<p class="k-fine">Only someone on the family\'s list. Anyone else: the church office decides.</p></form>')
    return _shell(biz, site, "Pickup", f'{back}<div class="mb-lt"><h1>Pickup</h1></div>{body}{other}', tab="home", who=me)


# ─── pages, served from member_portal ────────────────────────────────


async def home(request: Request, church: Dict[str, Any], me: Dict[str, Any], occasions, flash: str) -> HTMLResponse:
    import asyncio
    biz, site = church["business"], church["site"]
    ctx = msp.CURRENT.get() or {}
    set_zone(biz)
    rooms = leader_rooms(ctx)
    fam = await asyncio.to_thread(family, biz["id"], str(me["id"])) if ctx.get("kids_parent") else None
    want_rooms = None if rooms == [] else sorted({*(rooms or []), *[str(k.get("room") or "") for k in (fam or {}).get("children") or []]})
    live_rows, all_lessons, ros = await asyncio.gather(
        asyncio.to_thread(live, biz["id"], (fam or {}).get("households") or []),
        asyncio.to_thread(lessons, biz["id"], want_rooms),
        asyncio.to_thread(roster, biz["id"], rooms) if rooms is not None else asyncio.sleep(0, None))
    from member_portal import _page
    return _page(render_home(biz, site, me=me, ctx=ctx, fam=fam, live_rows=live_rows, occasions=occasions,
                             all_lessons=all_lessons, ros=ros, flash=flash))


async def serve(request: Request, church: Dict[str, Any], me: Dict[str, Any], sub: str):
    """/my/kids/* for someone in the Kids space."""
    import asyncio
    from fastapi.responses import RedirectResponse
    from member_portal import _SECURE_HEADERS, _page
    biz, site = church["business"], church["site"]
    ctx = msp.CURRENT.get() or {}
    if ctx.get("space") != "kids":
        return RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
    set_zone(biz)
    rooms = leader_rooms(ctx)
    parent = bool(ctx.get("kids_parent"))
    fam = await asyncio.to_thread(family, biz["id"], str(me["id"])) if parent else None
    if sub == "/my/kids/stories":
        want = None if rooms == [] else sorted({*(rooms or []), *[str(k.get("room") or "") for k in (fam or {}).get("children") or []]})
        got = await asyncio.to_thread(lessons, biz["id"], want, 20)
        return _page(render_stories(biz, site, request, me=me, ctx=ctx, fam=fam, all_lessons=got))
    if sub == "/my/kids/sundays" and parent:
        past = await asyncio.to_thread(history, biz["id"], (fam or {}).get("households") or []) if fam else None
        return _page(render_sundays(biz, site, me=me, ctx=ctx, fam=fam, past=past))
    if sub == "/my/kids/family" and parent:
        return _page(render_family(biz, site, me=me, fam=fam))
    if sub == "/my/kids/play" and parent:
        want = sorted({str(k.get("room") or "") for k in (fam or {}).get("children") or []})
        got = await asyncio.to_thread(lessons, biz["id"], want, 8)
        return _page(render_play(biz, site, me=me, fam=fam, all_lessons=got,
                                 child_id=str(request.query_params.get("child") or "")))
    return RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)


# ─── a leader's actions ──────────────────────────────────────────────


async def _kids_leader(request: Request):
    """(church, me, ctx, rooms, err): a signed-in adult the office approved
    for Kids, with the Kids space set for the page drawn."""
    import asyncio
    import member_portal_church as mpc
    church, me, unavailable = await mpc._signed_in(request)
    if unavailable:
        return church, None, None, None, ("preview" if unavailable == "preview" else "error")
    if not me:
        return church, None, None, None, "signin"
    ctx = await asyncio.to_thread(msp.resolve, church["business"]["id"], me, "kids")
    rooms = leader_rooms(ctx)
    if rooms is None or not msp.is_adult(me) or ctx.get("space") != "kids":
        return church, me, ctx, None, "not_kids_leader"
    msp.CURRENT.set(ctx)
    return church, me, ctx, rooms, None


@router.post("/my/kids/pickup", include_in_schema=False)
async def pickup_check(request: Request):
    import asyncio
    import kids_checkin as kc
    import member_portal_church as mpc
    from member_portal import _page
    church, me, ctx, rooms, err = await _kids_leader(request)
    if err:
        return mpc._back("/my", **({} if err == "signin" else {"err": err}))
    if not mpc._allowed(church, me):
        return mpc._back("/my", err="slow")
    form = await request.form()
    code = kc.norm_code(str(form.get("code") or ""))
    biz, site = church["business"], church["site"]
    set_zone(biz)
    if not kc.CODE_RE.match(code):
        return _page(render_pickup(biz, site, me=me, code=code, error="A pickup code is four letters and numbers."))
    occ, why = await asyncio.to_thread(find_code, biz["id"], code)
    if why == "unavailable":
        return _page(render_pickup(biz, site, me=me, code=code, error="Pickup couldn't load just now. Please try again."), 503)
    if not occ:
        return _page(render_pickup(biz, site, me=me, code=code,
                                   error="No child is waiting with that code. Check the tag, or ask the parent to show their phone."))
    try:
        found = await asyncio.to_thread(kc.do_lookup, str(biz["id"]), {"id": occ["id"]}, code, False)
    except HTTPException as e:
        return _page(render_pickup(biz, site, me=me, code=code, error=str(e.detail)))
    return _page(render_pickup(biz, site, me=me, code=code, found=found, entry_id=occ["id"], rooms=rooms))


@router.post("/my/kids/release", include_in_schema=False)
async def pickup_release(request: Request):
    import asyncio
    import kids_checkin as kc
    import member_portal_church as mpc
    from member_portal import _page
    church, me, ctx, rooms, err = await _kids_leader(request)
    if err:
        return mpc._back("/my", **({} if err == "signin" else {"err": err}))
    if not mpc._allowed(church, me):
        return mpc._back("/my", err="slow")
    form = await request.form()
    biz, site = church["business"], church["site"]
    set_zone(biz)
    code = kc.norm_code(str(form.get("code") or ""))
    entry_id = str(form.get("entry_id") or "")
    ids = [str(i) for i in form.getlist("checkin_id")][:20]
    to = str(form.get("released_to") or "").strip()[:120]
    occ = await asyncio.to_thread(todays, biz["id"])
    if occ is None:
        return _page(render_pickup(biz, site, me=me, code=code, error="Pickup couldn't load just now. Please try again."), 503)
    if not any(str(o["id"]) == entry_id for o in occ):
        return _page(render_pickup(biz, site, me=me, code=code, error="That pickup is from another day. Check the code again."))
    if not ids or not to:
        return _page(render_pickup(biz, site, me=me, code=code, error="Choose the children and who they're going home with."))
    try:
        found = await asyncio.to_thread(kc.do_lookup, str(biz["id"]), {"id": entry_id}, code, False)
        rooms_of = {str(c["id"]): c.get("room") for c in found["children"]}
        if any(i not in rooms_of or not in_rooms(rooms_of[i], rooms) for i in ids):
            return _page(render_pickup(biz, site, me=me, code=code, error="Those children aren't in your rooms."))
        await asyncio.to_thread(kc.do_release, str(biz["id"]), {"id": entry_id}, code, ids, to, False, None,
                                str(me["id"]))
    except HTTPException as e:
        return _page(render_pickup(biz, site, me=me, code=code, error=str(e.detail)), 200 if e.status_code < 500 else 503)
    return mpc._back("/my", done="released")


def clean_lesson(form) -> Tuple[Optional[Dict[str, str]], str]:
    """The lesson's fields, trimmed to the table's limits, or an error code."""
    def f(name: str, cap: int) -> str:
        return re.sub(r"[ \t]+\n", "\n", str(form.get(name) or "")).strip()[:cap]
    out = {"title": f("title", TITLE_MAX), "body": f("body", BODY_MAX), "scripture": f("scripture", REF_MAX),
           "verse": f("verse", VERSE_MAX), "questions": f("questions", QUESTIONS_MAX), "video_url": f("video_url", VIDEO_MAX),
           "room": re.sub(r"\s+", " ", str(form.get("room") or "")).strip()[:60]}
    if not out["title"] or not out["body"]:
        return None, "lesson_incomplete"
    if out["video_url"] and not re.fullmatch(r"https://[^\s<>\"']+", out["video_url"]):
        return None, "lesson_link"
    return out, ""


@router.post("/my/kids/lesson", include_in_schema=False)
async def lesson_post(request: Request):
    import asyncio
    import member_portal_church as mpc
    import msg_screen
    church, me, ctx, rooms, err = await _kids_leader(request)
    if err:
        return mpc._back("/my/kids/stories" if err != "signin" else "/my", **({} if err == "signin" else {"err": err}))
    if not mpc._allowed(church, me):
        return mpc._back("/my/kids/stories", err="slow")
    form = await request.form()
    lesson, why = clean_lesson(form)
    if not lesson:
        return mpc._back("/my/kids/stories", err=why)
    if rooms and not in_rooms(lesson["room"], rooms):
        return mpc._back("/my/kids/stories", err="lesson_room")
    if rooms:
        lesson["room"] = next(r for r in rooms if r.casefold() == lesson["room"].casefold())
    else:
        lesson["room"] = ""                  # a leader of every room posts for every room
    biz_id = church["business"]["id"]
    text = "\n".join(lesson[k] for k in ("title", "scripture", "body", "verse", "questions") if lesson[k])
    try:
        verdict = await msg_screen.screen(biz_id, text)
    except msg_screen.ScreenUnavailable:
        return mpc._back("/my/kids/stories", err="post_busy")
    if verdict != "ok":
        return mpc._back("/my/kids/stories", err="post_no")
    rows = await asyncio.to_thread(sb_clients.sb_post_as_service, "/space_posts", {
        "business_id": str(biz_id), "space": "kids", "kind": "lesson", **lesson, "posted_by": str(me["id"])})
    if not (isinstance(rows, list) and rows):
        return mpc._back("/my/kids/stories", err="error")
    import member_push
    member_push.tell_kids_lesson(church["business"], str(rows[0].get("id") or ""), lesson["room"], lesson["title"])
    return mpc._back("/my/kids/stories", done="lesson_posted")


@router.post("/my/kids/lesson/remove", include_in_schema=False)
async def lesson_remove(request: Request):
    import asyncio
    import member_portal_church as mpc
    church, me, unavailable = await mpc._signed_in(request)
    if unavailable:
        return mpc._back("/my/kids/stories", err="preview" if unavailable == "preview" else "error")
    if not me:
        return mpc._back("/my")
    form = await request.form()
    pid = str(form.get("id") or "")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", pid):
        return mpc._back("/my/kids/stories")
    biz_id = church["business"]["id"]
    # Only the author removes their own lesson.
    gone = await asyncio.to_thread(
        sb_clients.sb_delete_as_service,
        f"/space_posts?id=eq.{_q(pid)}&business_id=eq.{_q(biz_id)}&space=eq.kids&posted_by=eq.{_q(me['id'])}")
    return mpc._back("/my/kids/stories", **({"done": "lesson_removed"} if gone else {"err": "error"}))
