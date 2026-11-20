"""
member_im_new.py — "I'm new here" in the member app.

Kevin, 2026-11-18, on the approved member app redesign ("Lumen"): its Connect
tab's "Your next step" opens with "I'm new here — Tell the church you're new,
and get a simple path to find your place." The app had no step for
newcomers; "the i'm new here build it". The guest side (a guest texts NEW,
new_here.py) already existed: this is the same welcome for someone already
signed in to the member app, and it lands in the same places.

  THE CARD     new_here_card(business, ctx, request): Connect's "Your next
               step". Start before the member has told the church, Your path
               afterwards. Whether they told is kept (member_cache.Kept, per
               server copy): TOLD_SECONDS once they have, NOT_YET_SECONDS
               before, and a failed read never (the card then says Start,
               which opens a page that reads again).
  THE FORM     GET /my/new, one screen, in the member's own words: first time
               or been coming a while; how they heard (new_here.HEARD, the
               guest card's list); kids, yes or no, and their ages; what
               they'd like (a group, to serve, to be baptized, a class, to
               talk with a pastor); and a prayer only the pastors see.
  SAVING       POST /my/new. Who it is comes from the session, never the form.
                 · their answers on their own record, beside the text New
                   here's keys: contacts.metadata.new_here.app (no migration)
                 · a first timer tagged "first-time guest", as New here tags
                   one; someone who's been coming a while, "new here"
                 · a prayer kept as a confidential care request (pastors
                   only, never the prayer team), as the New here card keeps
                   one, and never in the follow-up
                 · a follow-up through church_follow_up.start, routed as New
                   here routes (kind connect, its answers never re-routing
                   it: the welcome role first), card_key app:new_here
               One follow-up per member, ever: its source_event is
               app-new-here:<contact id> (church_follow_ups has a unique index
               on it), and saving again updates its answers and leaves a
               note. Someone who texted NEW and has that follow-up open gets
               a note on it instead of a second one. Saving the same answers
               again writes nothing. Nothing is texted or emailed to the
               member. Rate-limited per member (member_im_new, member_action).
  YOUR PATH    after saving, built from what the church really has, and only
               that: its next-steps path in the academy (or a class to join),
               groups taking new people, serving, a baptism (Ask the church,
               Plan a life event) and a pastor (Ask the church, Talk to a
               pastor). What they asked for comes first.
  THE STAFF    the New here room (new_here.guests_of) lists them with this
               week's guests who texted, and Follow-up has their card ("New
               here (member app) card").
  THE PATH     since 2026-11-20, with the Welcome Path on (guest_path), a
               member who's new joins the same path as a guest who texts the
               word (new_here.enroll, door "app"): the welcome texts when
               they tick "Text me" (shown only where the church's texts would
               go, kept as an sms_consents row, source member_app_new), and
               the call either way (join_path). Someone already handed on by
               another door gets a note there, never a second follow-up.

WHO. Both switches must say yes:
  MEMBER_LUMEN  member_lumen.visible: the redesign's own (preview by default:
                only the platform owner's preview and own sign-in)
  MEMBER_IM_NEW off is the way back; on when unset
Churches only, in the Church space, for adults (a teen's prayer goes the
youth way, and Youth has its own app). The owner's preview shows the pages
and saves nothing.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

import member_cache
import sb_clients

logger = logging.getLogger("member_im_new")
router = APIRouter(tags=["member-portal"])

SWITCH = "MEMBER_IM_NEW"
PATH = "/my/new"
CARD_KEY = "app:new_here"                    # church_follow_ups.card_key
CARD_NAME = "New here (member app) card"     # its lane on the Follow-up board
SOURCE = "Member app, I'm new here"          # ministry_care_requests submission.source
FIRST_TAG = "first-time guest"               # the tag new_here.save_card and text_room give a first timer
NEW_TAG = "new here"                         # someone who's been coming a while
BACK = ("/my/groups", "Connect")

TOLD_SECONDS = 600.0
NOT_YET_SECONDS = 60.0
AGES_MAX = 60
PRAYER_MAX = 1500

# What they'd like, in their own words, and the words a leader reads.
WANTS: Dict[str, str] = {
    "group": "Find a group",
    "serve": "Serve",
    "baptism": "Get baptized",
    "class": "Take a class or learn the faith",
    "pastor": "Talk with a pastor",
}
WANT_WORDS: Dict[str, str] = {
    "group": "find a group", "serve": "serve", "baptism": "get baptized",
    "class": "take a class or learn the faith", "pastor": "talk with a pastor",
}
# The boxes two by two on a phone, the long one last across the row.
SHOWN_ORDER = ("group", "serve", "baptism", "pastor", "class")
ANSWERS = ("first_time", "heard", "kids", "ages", "wants")
# The Welcome Path's two more (asked only while it's on; guest_brief reads
# them for the caller's brief): who invited them, and the best way to reach
# them. Kept beside ANSWERS, so a member whose church doesn't ask them saves
# exactly what they saved before.
PATH_ANSWERS = ("invited", "reach")
REACH = {"call": "A call is fine", "text": "Text me instead"}
INVITED_MAX = 120

_TOLD = member_cache.Kept("im_new_told", TOLD_SECONDS)
_NOT_YET = member_cache.Kept("im_new_not_yet", NOT_YET_SECONDS)
_LOCKS: Dict[Tuple[str, str], threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _e(v: Any) -> str:
    from member_portal import _e as esc
    return esc(v)


def _plain(v: Any, top: int) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:top]


def _words(v: Any, top: int) -> str:
    """A member's own words: line breaks kept, nothing past `top`."""
    s = str(v or "").replace("\r\n", "\n").replace("\r", "\n")
    s = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in s.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", s).strip()[:top]


def _rows(path: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(path)
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else None


# ─── who sees it ──────────────────────────────────────────────────────


def on() -> bool:
    """MEMBER_IM_NEW: anything but off is on (unset is on)."""
    return (os.environ.get(SWITCH) or "on").strip().lower() not in ("off", "0", "false", "no")


def is_church(business: Optional[Mapping[str, Any]]) -> bool:
    try:
        import church_follow_up
        return church_follow_up.is_church(dict(business or {}))
    except Exception:  # noqa: BLE001
        return False


def adult(me: Optional[Mapping[str, Any]]) -> bool:
    """Not a teen and not a child by the member app's own rule (member_spaces)."""
    if not me:
        return False
    import member_spaces as msp
    return not (msp.is_youth(dict(me)) or msp.is_child(dict(me)))


def lumen(request: Any, business: Mapping[str, Any], session: Optional[Mapping[str, Any]]) -> bool:
    """The redesign's switch (member_lumen.visible). A failure is a no."""
    try:
        import member_lumen
        return bool(member_lumen.visible(request, {"business": dict(business or {}), "session": session}))
    except Exception:  # noqa: BLE001
        logger.warning("im new: the Lumen switch couldn't be read", exc_info=True)
        return False


def open_here(request: Any, business: Mapping[str, Any], session: Optional[Mapping[str, Any]]) -> bool:
    """Both switches, and a church. Sync: member_lumen may read the church's
    owner (kept ten minutes); call it in a thread from async code."""
    return on() and is_church(business) and lumen(request, business, session)


# ─── has this member told the church? ─────────────────────────────────


def _clean_app(raw: Any) -> Dict[str, Any]:
    return dict(raw) if isinstance(raw, dict) and raw.get("at") else {}


def read_app(business_id: str, contact_id: str) -> Optional[Dict[str, Any]]:
    """What this member told the church ({} for nothing yet), read now, or
    None when it couldn't be read. Keeps the answer for the card."""
    rows = _rows(f"/contacts?id=eq.{_q(contact_id)}&business_id=eq.{_q(business_id)}"
                 "&select=id,app:metadata->new_here->app&limit=1")
    if rows is None:
        return None
    app = _clean_app(rows[0].get("app")) if rows else {}
    remember(business_id, contact_id, app)
    return app


def remember(business_id: str, contact_id: str, app: Dict[str, Any]) -> None:
    key = (str(business_id), str(contact_id))
    if app.get("at"):
        _NOT_YET.forget(lambda k, _tag: k == key)
        _TOLD.put(key, app, tag=str(business_id))
    else:
        _TOLD.forget(lambda k, _tag: k == key)
        _NOT_YET.put(key, {}, tag=str(business_id))


def told_state(business_id: str, contact_id: str) -> Optional[Dict[str, Any]]:
    """read_app, from what's kept when it can be: the card's check costs a
    read at most once a minute per member before they tell, once every ten
    minutes after."""
    key = (str(business_id), str(contact_id))
    for kept in (_TOLD, _NOT_YET):
        hit, app = kept.get(key)
        if hit:
            return app
    return read_app(*key)


# ─── the form ─────────────────────────────────────────────────────────


def clean(form: Mapping[str, Any], wants: Optional[List[str]] = None, *, path: bool = False) -> Dict[str, Any]:
    """The answers, tidied: anything that isn't one of the choices is dropped.
    `wants` is the form's checked boxes (a form posts one value per box).
    `path`: the Welcome Path is on, so who invited them and the best way to
    reach them are read too."""
    import new_here
    first = str(form.get("first") or "yes") != "no"
    heard = str(form.get("heard") or "")
    kids = "yes" if str(form.get("kids") or "") == "yes" else "no"
    picked = set(str(w) for w in (wants or []))
    out = {
        "first_time": first,
        "heard": heard if heard in new_here.HEARD else "",
        "kids": kids,
        "ages": _plain(form.get("ages"), AGES_MAX) if kids == "yes" else "",
        "wants": [k for k in WANTS if k in picked],
        "prayer": _words(form.get("prayer"), PRAYER_MAX),
    }
    if path:
        reach = str(form.get("reach") or "")
        out.update(invited=_plain(form.get("invited"), INVITED_MAX), reach=reach if reach in REACH else "")
    return out


def answers_for(a: Mapping[str, Any]) -> List[Dict[str, str]]:
    """What the leader reads on the follow-up (never the prayer: prayer is the
    pastors'). "First time?" reads as New here's card reads, so
    church_reads.first_time_guests counts a first timer."""
    out = [{"q": "First time?", "a": "Yes" if a.get("first_time") else "Been coming a while"}]
    if a.get("heard"):
        out.append({"q": "How they heard", "a": str(a["heard"])})
    if a.get("kids") == "yes":
        out.append({"q": "Kids", "a": f"Yes, ages {a['ages']}" if a.get("ages") else "Yes"})
    wants = [WANT_WORDS[k] for k in a.get("wants") or [] if k in WANT_WORDS]
    if wants:
        said = ", ".join(wants[:-1]) + (" and " if len(wants) > 1 else "") + wants[-1]
        out.append({"q": "They'd like to", "a": said[0].upper() + said[1:]})
    if a.get("invited"):
        out.append({"q": "Who invited them", "a": str(a["invited"])})
    if a.get("reach") in REACH:
        out.append({"q": "Best way to reach them", "a": REACH[str(a["reach"])]})
    out.append({"q": "Where", "a": "Told the church in the member app"})
    return out


# ─── saving ───────────────────────────────────────────────────────────


def _lock(business_id: str, contact_id: str) -> threading.Lock:
    """One save at a time per member on this server copy (a double tap); the
    unique source_event keeps it to one follow-up across copies."""
    key = (business_id, contact_id)
    with _LOCKS_GUARD:
        if len(_LOCKS) > 2000:
            _LOCKS.clear()
        return _LOCKS.setdefault(key, threading.Lock())


def source_event(contact_id: str) -> str:
    return f"app-new-here:{contact_id}"[:80]


def hand_on(business_id: str, contact_id: str, a: Mapping[str, Any]) -> bool:
    """The member's follow-up, never a second one. True when one is in place
    (started, updated, or a note on the New here follow-up they already
    have); False when it couldn't be (a read failed, or no row saved): the
    next save tries again. Never raises."""
    import church_follow_up as cfu
    import new_here
    biz, cid = str(business_id), str(contact_id)
    try:
        answers = answers_for(a)
        said = "; ".join(f"{x['q']} {x['a']}" for x in answers)[:1500]
        found = _rows(f"/church_follow_ups?business_id=eq.{_q(biz)}&contact_id=eq.{_q(cid)}"
                      f"&card_key=like.{_q('*:new_here')}&select=id,card_key,status&order=created_at.desc&limit=10")
        if found is None:
            logger.warning("im new: follow-up check failed (business %s)", biz[:8])
            return False
        mine = next((f for f in found if f.get("card_key") == CARD_KEY), None)
        if mine:
            saved = sb_clients.sb_patch_as_service(
                f"/church_follow_ups?id=eq.{_q(mine['id'])}&business_id=eq.{_q(biz)}",
                {"answers": answers, "updated_at": _iso(_now())})
            cfu._note(biz, str(mine["id"]), "chief", "note", f"Changed what they told the church in the member app. {said}")
            return saved is not None
        texted = next((f for f in found if f.get("card_key") == new_here.CARD_KEY
                       and f.get("status") in ("open", "handed_back")), None)
        if texted:
            return cfu._note(biz, str(texted["id"]), "chief", "note",
                             f"Also told the church in the member app. {said}") is not None
        # The Welcome Path: handed on by another door (the kids desk, the
        # website's card): a note there, never a second follow-up.
        if new_here.second_door(biz, cid, CARD_KEY, answers, "Also told the church in the member app."):
            return True
        row = cfu.start(biz, cid, card_key=CARD_KEY, card_name=CARD_NAME, kind="connect", answers=answers,
                        source_event=source_event(cid), what="New here cards", route_answers=[])
        if row:
            return True
        # None is also "already there" (the same member on another server
        # copy a moment ago): the unique source_event says which.
        had = _rows(f"/church_follow_ups?business_id=eq.{_q(biz)}&source_event=eq.{_q(source_event(cid))}"
                    "&select=id&limit=1")
        return bool(had)
    except Exception:  # noqa: BLE001
        logger.warning("im new: follow-up not handed on (business %s)", biz[:8], exc_info=True)
        return False


def keep_prayer(business_id: str, person: Mapping[str, Any], prayer: str) -> bool:
    """A prayer as a confidential care request: pastors only, never the
    prayer team, as the New here card keeps one. The same words sent again
    (a double tap, saving again) are kept once. False when it didn't save."""
    import church_prayer
    biz, cid = str(business_id), str(person["id"])
    have = _rows(f"/ministry_care_requests?business_id=eq.{_q(biz)}&contact_id=eq.{_q(cid)}"
                 f"&submission->>source=eq.{_q(SOURCE)}&select=id,submission&order=created_at.desc&limit=20")
    if have is None:
        return False
    if any(isinstance(r.get("submission"), dict) and r["submission"].get("prayer_request") == prayer for r in have):
        return True
    submission = {"name": _plain(person.get("name"), 120), "email": person.get("email") or "",
                  "phone": person.get("phone") or "", "prayer_request": prayer, "confidential": "yes",
                  "source": SOURCE}
    rows = sb_clients.sb_post_as_service("/ministry_care_requests", {
        "business_id": biz, "form_id": None, "contact_id": cid, "status": "new", "submission": submission,
        **church_prayer.consent_columns(submission, share=False)})
    if not (isinstance(rows, list) and rows):
        return False
    try:
        church_prayer.on_new(biz, rows[0])
    except Exception:  # noqa: BLE001
        logger.warning("im new: prayer hand-off skipped (business %s)", biz[:8], exc_info=True)
    return True


def save(business: Mapping[str, Any], me: Mapping[str, Any], a: Dict[str, Any]) -> Tuple[bool, str]:
    """(saved, what to say). Codes: saved, same (nothing changed, nothing
    written), noprayer (saved, but the prayer didn't keep), care (saved, and
    the prayer has words that need the crisis line), error (nothing saved).
    Sync; call it in a thread."""
    biz, cid = str(business["id"]), str(me["id"])
    a = dict(a)
    prayer = str(a.pop("prayer", "") or "")
    with _lock(biz, cid):
        rows = _rows(f"/contacts?id=eq.{_q(cid)}&business_id=eq.{_q(biz)}"
                     "&select=id,name,email,phone,tags,metadata&limit=1")
        if not rows:
            return False, "error"
        person = rows[0]
        meta = dict(person.get("metadata") or {}) if isinstance(person.get("metadata"), dict) else {}
        mine = dict(meta.get("new_here") or {}) if isinstance(meta.get("new_here"), dict) else {}
        before = _clean_app(mine.get("app"))
        changed = not before or any(before.get(k) != a.get(k) for k in ANSWERS) or any(
            (before.get(k) or "") != (a.get(k) or "") for k in PATH_ANSWERS if k in a)
        tags = [t for t in (person.get("tags") or []) if isinstance(t, str)]
        tag = FIRST_TAG if a["first_time"] else NEW_TAG
        was_handed = bool(before.get("follow_up"))
        handed = was_handed
        if changed or not was_handed:
            # A follow-up that was in place stays in place when an update
            # to it fails.
            handed = hand_on(biz, cid, a) or was_handed
        if not (changed or handed != was_handed or tag not in tags or (prayer and not before.get("prayer"))):
            if not prayer:
                remember(biz, cid, before)
                return True, "same"
            app = before
        else:
            now = _iso(_now())
            app = {**{k: a.get(k) for k in ANSWERS},
                   **{k: a[k] if k in a else before.get(k) for k in PATH_ANSWERS if k in a or k in before},
                   "at": before.get("at") or now,
                   "changed_at": now if changed else (before.get("changed_at") or before.get("at") or now),
                   "prayer": bool(before.get("prayer") or prayer), "follow_up": handed}
            mine["app"] = app
            meta["new_here"] = mine
            patch: Dict[str, Any] = {"metadata": meta}
            if tag not in tags:
                patch["tags"] = tags + [tag]
            if sb_clients.sb_patch_as_service(f"/contacts?id=eq.{_q(cid)}&business_id=eq.{_q(biz)}", patch) is None:
                return False, "error"
        remember(biz, cid, app)
        if prayer:
            if not keep_prayer(biz, person, prayer):
                logger.warning("im new: prayer not kept (business %s)", biz[:8])
                return True, "noprayer"
            try:
                from msg_screen import CRISIS_RE
                if CRISIS_RE.search(prayer):
                    return True, "care"
            except Exception:  # noqa: BLE001
                pass
        return True, "saved"


# ─── Your path ────────────────────────────────────────────────────────


def classes_part(business: Mapping[str, Any], me: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """The church's next-steps path in the academy (member_portal_classes):
    a program they're on, else a program's first class they can join, else
    any class they can join. None when it couldn't be read."""
    import member_portal_classes as mcl
    data = mcl.classes_for(str(business["id"]), dict(me))
    if data is None:
        return None
    out: Dict[str, Any] = {"program": None, "open_program": "", "open_n": len(data.get("open") or [])}
    for p in data.get("programs") or []:
        tracks = [t for t in p.get("tracks") or [] if isinstance(t, dict)]
        names = [mcl.short_title(str(t.get("title") or ""), p.get("title")) for t in tracks]
        at = next((i for i, t in enumerate(tracks) if t.get("state") in ("now", "open")), None)
        if at is None and tracks and all(t.get("state") == "done" for t in tracks):
            continue
        out["program"] = {"title": str(p.get("title") or ""), "now": names[at] if at is not None else "",
                          "next": names[at + 1:at + 3] if at is not None else []}
        break
    if not out["program"]:
        out["open_program"] = next((str(c.get("program")) for c in data.get("open") or [] if c.get("program")), "")
    return out


def groups_part(business: Mapping[str, Any], me: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Groups taking new people (the group finder's rule: active, not by
    invitation, not one they're in, not a youth group), serving teams among
    them, and whether they already serve on a Sunday team (sunday_serving).
    None when it couldn't be read."""
    import member_portal_church as mpc
    import sunday_serving as ss
    biz, cid = str(business["id"]), str(me["id"])
    groups = _rows(f"/groups?business_id=eq.{_q(biz)}&active=eq.true"
                   "&select=id,kind,join_mode,open_to_join,youth&limit=500")
    mine = _rows(f"/group_members?business_id=eq.{_q(biz)}&contact_id=eq.{_q(cid)}&select=group_id&limit=500")
    if groups is None or mine is None:
        return None
    serving_on = ss.on()
    teams: set = set()
    if serving_on:
        got = _rows(f"/serve_teams?business_id=eq.{_q(biz)}&select=group_id&limit=500")
        if got is None:
            serving_on = False
        else:
            teams = {str(t.get("group_id")) for t in got}
    in_ = {str(m.get("group_id")) for m in mine}
    joinable = [g for g in groups if str(g.get("id")) not in in_ and not g.get("youth") and mpc.join_mode(g) != "invite"]

    def is_team(g: Mapping[str, Any]) -> bool:
        return str(g.get("id")) in teams or g.get("kind") == "team"
    return {"groups": sum(1 for g in joinable if not is_team(g)),
            "teams_open": sum(1 for g in joinable if is_team(g)),
            "serves": bool(serving_on and in_ & teams)}


def asks_part(business: Mapping[str, Any], me: Mapping[str, Any]) -> Optional[List[str]]:
    """The Ask the church asks this member is offered (member_asks.entry)."""
    import member_asks
    try:
        return member_asks.entry(dict(business), dict(me))
    except Exception:  # noqa: BLE001
        logger.warning("im new: asks couldn't be read", exc_info=True)
        return None


def _and(names: List[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def path_rows(classes: Optional[Dict[str, Any]], groups: Optional[Dict[str, Any]], asks: Optional[List[str]],
              wants: List[str], *, handed: bool) -> List[Dict[str, Any]]:
    """Your path: only what the church has (a part that couldn't be read is
    left out), what they asked for first. A wish with no door at this church
    is said as passed on, only when a follow-up carries it."""
    rows: List[Dict[str, Any]] = []

    def add(key: str, title: str, sub: str, href: str, icon: str, hue: str) -> None:
        rows.append({"key": key, "title": title, "sub": sub, "href": href, "icon": icon, "hue": hue,
                     "picked": key in wants})
    if classes:
        p = classes.get("program")
        if p:
            sub = (f"{p['now']} now" + (f", then {_and(p['next'])}" if p.get("next") else "")) if p.get("now") else \
                "Your next steps, one class at a time"
            add("class", f"Keep going on {p['title']}", sub, "/my/classes", "cap", "gold")
        elif classes.get("open_program"):
            add("class", f"Start {classes['open_program']}", "Your church's next steps, one class at a time",
                "/my/classes", "cap", "gold")
        elif classes.get("open_n"):
            add("class", "Take a class", "Learn the faith with others. Join with one tap.", "/my/classes", "cap", "gold")
    if groups:
        if groups.get("groups"):
            add("group", "Try a group", "Find one that fits, and join from the list", "/my/groups", "users", "teal")
        if groups.get("serves"):
            add("serve", "Your serving", "Your Sundays, your teams and your away days", "/my/serving", "hand", "violet")
        elif groups.get("teams_open"):
            add("serve", "Serve on a team", "Teams that take new people are in Groups", "/my/groups", "hand", "violet")
    if asks is not None:
        if "life_event" in asks:
            add("baptism", "Get baptized", "Ask the church to plan it with you", "/my/ask/life?pick=baptism",
                "drop", "teal")
        if "visit" in asks:
            add("pastor", "Talk with a pastor", "It goes straight to the people who care for members",
                "/my/ask/visit?pick=talk", "chat", "coral")
        elif "help" in asks:
            add("pastor", "Ask for a visit or help", "It goes straight to the people who care for members",
                "/my/ask/help", "chat", "coral")
    if handed:
        have = {r["key"] for r in rows}
        for k in wants:
            if k not in have:
                add(k, WANTS[k], "You told the church. Someone will talk with you about it.", "", "check", "brand")
    return sorted(rows, key=lambda r: not r["picked"])


# ─── the look (Lumen, accent level 2) ─────────────────────────────────

ICONS = {
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "cap": '<path d="m2 9 10-5 10 5-10 5z"/><path d="M6 11v5c3 2 9 2 12 0v-5"/>',
    "users": ('<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
              '<path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>'),
    "hand": '<path d="M12 21s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 11c0 5.6-7 10-7 10z"/>',
    "drop": '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/>',
    "chat": '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-4.9A8 8 0 1 1 21 12z"/>',
    "chev": '<path d="m9 18 6-6-6-6"/>',
    "lock": '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
}
HUE_INK = {"gold": "var(--gold-ink)", "teal": "var(--teal-ink)", "violet": "var(--violet-ink)",
           "coral": "var(--coral-ink)", "brand": "var(--acc)"}


def icon(name: str, size: int = 18) -> str:
    return (f'<svg class="ln-ico" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" '
            f'focusable="false">{ICONS[name]}</svg>')


# The mock's pieces (Main.dc.html: .mast, .disp, .newcard, .aic, .wrow, .ch,
# .ta, .btn, .sent, the al-2 accents) on the member app's own tokens: the
# church's base and colour (member_app_ui), the colour family for the icons.
CARD_CSS = """
.imn{--ln-fill:var(--acc-fill);--ln-ink:var(--acc);--ln-on:var(--on-acc);
  --ln-tint:color-mix(in srgb,var(--acc-fill) 8%,var(--bg));--ln-tint2:color-mix(in srgb,var(--acc-fill) 12%,var(--bg));}
.imn .ln-ico{display:block;flex:none;}
.imn .ln-newcard{display:flex;align-items:center;gap:14px;padding:16px;border-radius:18px;background:var(--s1);margin:0 0 10px;}
.imn .ln-aic{width:40px;height:40px;border-radius:50%;display:grid;place-items:center;flex:none;color:var(--k,var(--ln-ink));background:var(--s1);}
.imn.al-2 .ln-aic{background:var(--ln-tint);}
.imn .ln-newcard .ln-aic{background:var(--bg);}
.imn.al-2 .ln-newcard .ln-aic{background:var(--ln-tint);}
.imn .ln-wt{flex:1;min-width:0;}
.imn .ln-wt b{display:block;font:650 16px/1.25 var(--mb-ui);letter-spacing:-.01em;color:var(--fg);}
.imn .ln-wt b+span{display:block;margin-top:3px;font:400 13.5px/1.35 var(--mb-ui);color:var(--fg2);}
.imn .ln-new{display:inline-flex;align-items:center;height:18px;padding:0 6px;margin-left:4px;border-radius:5px;background:var(--fg);color:var(--bg);
  font:800 9.5px/1 var(--mb-ui);letter-spacing:.1em;vertical-align:middle;}
.imn .ln-btn{height:46px;padding:0 22px;border-radius:23px;border:0;background:var(--ln-fill);color:var(--ln-on);font:650 15px/1 var(--mb-ui);
  display:inline-flex;align-items:center;justify-content:center;gap:8px;text-decoration:none;cursor:pointer;transition:transform .15s ease;}
.imn .ln-btn:active{transform:scale(.97);}
.imn .ln-btn.sm{height:38px;padding:0 16px;font-size:13.5px;border-radius:19px;flex:none;}
.imn .ln-btn.ghost{background:var(--bg);color:var(--fg);box-shadow:inset 0 0 0 1px var(--line);}
.imn .ln-btn.block{width:100%;height:56px;border-radius:18px;font-size:16px;}
.imn a:focus-visible,.imn button:focus-visible,.imn input:focus-visible,.imn select:focus-visible,.imn textarea:focus-visible{outline:2px solid var(--ln-ink);outline-offset:2px;}
"""

PAGE_CSS = """
.imn .ln-mast{margin:6px 0 4px;}
.imn .ln-eb{margin:0;display:flex;align-items:center;gap:8px;font:650 11px/1.2 var(--mb-ui);letter-spacing:.14em;text-transform:uppercase;color:var(--fg2);}
.imn.al-2 .ln-eb{color:var(--ln-ink);}
.imn .ln-disp{margin:10px 0 0;font:400 40px/1.02 var(--mb-serif);letter-spacing:-.025em;text-wrap:balance;color:var(--fg);}
.imn .ln-disp em{font-style:italic;}
.imn.al-2 .ln-disp em{color:var(--ln-ink);}
.imn .ln-sub{margin:12px 0 0;font:400 15px/1.55 var(--mb-ui);color:var(--fg2);max-width:340px;}
.imn .ln-sec{display:flex;align-items:baseline;justify-content:space-between;margin:34px 0 12px;}
.imn .ln-h2{margin:0;font:700 19px/1.2 var(--mb-ui);letter-spacing:-.02em;color:var(--fg);}
.imn fieldset{border:0;margin:30px 0 0;padding:0;min-width:0;}
.imn legend{padding:0;}
.imn legend.ln-q{margin:0 0 12px;}
.imn .ln-q{display:block;margin:30px 0 12px;font:700 17px/1.25 var(--mb-ui);letter-spacing:-.015em;color:var(--fg);}
.imn .ln-hint{font:500 12.5px/1.35 var(--mb-ui);color:var(--fg3);margin:-6px 0 12px;}
.imn .ln-choice{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;}
.imn .ln-ch{position:relative;display:flex;gap:10px;align-items:flex-start;text-align:left;padding:14px;border-radius:14px;background:var(--s1);color:var(--fg);
  cursor:pointer;transition:box-shadow .25s,background-color .25s;}
.imn .ln-ch input{margin:2px 0 0;width:18px;height:18px;flex:none;accent-color:var(--ln-fill);}
.imn .ln-ch b{display:block;font:650 14px/1.2 var(--mb-ui);}
.imn .ln-ch span span{display:block;margin-top:5px;font:400 12px/1.35 var(--mb-ui);color:var(--fg2);}
.imn .ln-ch:has(input:checked){box-shadow:inset 0 0 0 1.5px var(--ln-fill);}
.imn.al-2 .ln-ch:has(input:checked){background:var(--ln-tint);}
.imn .ln-wants .ln-ch{align-items:center;}
.imn .ln-wants .ln-ch.wide{grid-column:1/-1;}
.imn .ln-field{display:block;width:100%;height:50px;padding:0 16px;border:0;border-radius:14px;background:var(--s1);color:var(--fg);
  font:400 15px/1 var(--mb-ui);appearance:auto;}
.imn .ln-kids{display:flex;gap:8px;flex-wrap:wrap;}
.imn .ln-chip{display:inline-flex;align-items:center;gap:8px;height:42px;padding:0 16px;border-radius:21px;background:var(--s1);color:var(--fg2);
  font:650 14px/1 var(--mb-ui);cursor:pointer;}
.imn .ln-chip input{margin:0;width:16px;height:16px;accent-color:var(--ln-fill);}
.imn .ln-chip:has(input:checked){background:var(--fg);color:var(--bg);}
.imn .ln-ages{display:none;margin-top:12px;}
.imn .ln-kidsq:has(input[value=yes]:checked) .ln-ages{display:block;}
.imn .ln-ages label{display:block;margin:0 0 8px;font:600 13px/1.3 var(--mb-ui);color:var(--fg2);}
.imn .ln-ta{display:block;width:100%;min-height:130px;padding:16px 18px;border:0;border-radius:16px;resize:vertical;background:var(--s1);color:var(--fg);
  font:400 italic 19px/1.45 var(--mb-serif);outline:none;transition:box-shadow .25s;}
.imn .ln-ta:focus{box-shadow:inset 0 0 0 1.5px var(--ln-fill);}
.imn .ln-ta::placeholder{color:var(--fg3);}
.imn .ln-send{margin-top:28px;}
.imn .ln-texts{margin-top:18px;}
.imn .ln-fine{display:flex;gap:10px;align-items:flex-start;margin:14px 0 0;font:400 12.5px/1.45 var(--mb-ui);color:var(--fg3);}
.imn .ln-fine .ln-ico{margin-top:1px;}
.imn .ln-err{margin:18px 0 0;padding:12px 14px;border-radius:14px;background:var(--s1);color:var(--error);font:600 14px/1.4 var(--mb-ui);}
.imn .ln-lead{margin:18px 0 0;padding:18px 18px 20px;border-radius:18px;background:var(--s1);display:flex;gap:14px;align-items:flex-start;}
.imn.al-2 .ln-lead{margin-left:-20px;margin-right:-20px;border-radius:0;padding:20px;background:var(--ln-tint);}
.imn .ln-ok{width:44px;height:44px;border-radius:50%;display:grid;place-items:center;flex:none;color:var(--ln-ink);box-shadow:inset 0 0 0 1.5px var(--ln-fill);}
.imn .ln-lead b{display:block;font:400 24px/1.1 var(--mb-serif);letter-spacing:-.015em;color:var(--fg);}
.imn .ln-lead b em{font-style:italic;color:var(--ln-ink);}
.imn .ln-lead p{margin:6px 0 0;font:400 14px/1.5 var(--mb-ui);color:var(--fg2);}
.imn .ln-lead p a{color:var(--ln-ink);font-weight:650;}
.imn .ln-list{border-top:1px solid var(--line);}
.imn .ln-wrow{display:grid;grid-template-columns:54px minmax(0,1fr) auto;gap:12px;align-items:center;width:100%;padding:14px 0;
  color:var(--fg);text-decoration:none;border-bottom:1px solid var(--line);}
.imn .ln-wrow .ln-chev{color:var(--fg3);}
.imn .ln-pick{display:inline-flex;align-items:center;height:20px;padding:0 7px;margin-left:6px;border-radius:10px;font:700 10.5px/1 var(--mb-ui);
  letter-spacing:.04em;vertical-align:middle;background:var(--s1);color:var(--fg2);}
.imn.al-2 .ln-pick{background:var(--ln-tint2);color:var(--ln-ink);}
.imn .ln-none{margin:6px 0 0;font:400 15px/1.55 var(--mb-ui);color:var(--fg2);}
.imn .ln-again{display:inline-flex;margin:22px 0 0;padding:8px 0;color:var(--ln-ink);font:650 14px/1 var(--mb-ui);text-decoration:none;}
"""

ERRORS = {
    "preview": "This is a preview, so nothing is saved.",
    "slow": "That's a lot at once. Wait a few minutes, then try again.",
    "error": "That didn't save just now. Please try again in a moment.",
}


def _wrap(body: str, *, page: bool) -> str:
    css = CARD_CSS + (PAGE_CSS if page else "")
    return f'<style>{css}</style><div class="imn al-2">{body}</div>'


def card_html(told: bool) -> str:
    """Connect's "Your next step" card (the mock's .newcard)."""
    if told:
        return _wrap(
            f'<div class="ln-newcard"><span class="ln-aic" style="--k:var(--acc)">{icon("check")}</span>'
            '<span class="ln-wt"><b>Your path</b><span>You told the church you\'re new. Here are your next steps.</span></span>'
            f'<a class="ln-btn sm ghost" href="{PATH}">Open</a></div>', page=False)
    return _wrap(
        f'<div class="ln-newcard"><span class="ln-aic" style="--k:var(--acc)">{icon("plus")}</span>'
        '<span class="ln-wt"><b>I\'m new here <span class="ln-new">NEW</span></b>'
        '<span>Tell the church you\'re new, and get a simple path to find your place.</span></span>'
        f'<a class="ln-btn sm" href="{PATH}">Start</a></div>', page=False)


def _radio(name: str, value: str, title: str, sub: str, checked: bool) -> str:
    sub_html = f"<span>{_e(sub)}</span>" if sub else ""
    return (f'<label class="ln-ch"><input type="radio" name="{name}" value="{value}"{" checked" if checked else ""}>'
            f'<span><b>{_e(title)}</b>{sub_html}</span></label>')


TEXTS_NAME = "texts"         # the "Text me" box's field


def text_me(business: Mapping[str, Any], me: Mapping[str, Any]) -> Tuple[str, str]:
    """(the "Text me" box's words, the mobile it texts) for this member, or
    ("", "") for no box: the Welcome Path on, the church's texts would go
    (new_here.text_me_words), and a mobile on their record (a member who
    signed in by email has it read once). Never raises."""
    try:
        import new_here
        words = new_here.text_me_words(dict(business))
        if not words:
            return "", ""
        phone = new_here.mobile((me or {}).get("phone"))
        if not phone and (me or {}).get("id"):
            rows = _rows(f"/contacts?id=eq.{_q(me['id'])}&business_id=eq.{_q(business['id'])}&select=phone&limit=1")
            phone = new_here.mobile((rows or [{}])[0].get("phone"))
        return (words, phone) if phone else ("", "")
    except Exception:  # noqa: BLE001
        return "", ""


def render_form(business: Mapping[str, Any], site: Any, request: Request, me: Mapping[str, Any],
                app: Optional[Dict[str, Any]], *, preview: bool = False) -> str:
    """GET /my/new: the one screen."""
    import new_here
    from member_portal import _shell
    church = _e((business.get("name") or "").strip() or "the church")
    app = app or {}
    err = str(request.query_params.get("err") or "")
    first = app.get("first_time", True) is not False
    kids = app.get("kids") == "yes"
    wants = set(app.get("wants") or [])
    heard = "".join(f'<option value="{_e(h)}"{" selected" if app.get("heard") == h else ""}>{_e(h)}</option>'
                    for h in new_here.HEARD)
    boxes = "".join(
        f'<label class="ln-ch{" wide" if k == "class" else ""}"><input type="checkbox" name="wants" value="{k}"'
        f'{" checked" if k in wants else ""}><span><b>{_e(WANTS[k])}</b></span></label>' for k in SHOWN_ORDER)
    shown = f'<p class="ln-err" role="alert">{_e(ERRORS[err])}</p>' if err in ERRORS else ""
    if preview and not shown:
        shown = f'<p class="ln-err" role="note">{_e(ERRORS["preview"])}</p>'
    words, phone = text_me(business, me)
    # The Welcome Path's two more questions, while it's on.
    path = new_here.path_on(business.get("id"))
    ages_label = "Their names and ages (optional)" if path else "Their ages (optional)"
    more = ""
    if path:
        reach = app.get("reach") if app.get("reach") in REACH else "call"
        more = (f'<label class="ln-q" for="imn-invited">Who invited you? <span class="ln-hint">Optional</span></label>'
                f'<input class="ln-field" id="imn-invited" name="invited" maxlength="{INVITED_MAX}" autocomplete="off" '
                f'value="{_e(app.get("invited") or "")}">'
                f'<fieldset><legend class="ln-q">Best way to reach you</legend><div class="ln-choice">'
                f'{_radio("reach", "call", REACH["call"], "", reach == "call")}'
                f'{_radio("reach", "text", REACH["text"], "", reach == "text")}</div></fieldset>')
    texts = (f'<label class="ln-ch ln-texts"><input type="checkbox" name="{TEXTS_NAME}" value="yes">'
             f'<span><b>Text me</b><span>{_e(words)} We\u2019ll text {_e(new_here.pretty_phone(phone))}.'
             '</span></span></label>') if words else ""
    fine = ("Only your church sees this, and your prayer goes only to the pastors. Nothing is posted, and texts "
            "come only if you tick Text me." if words else
            "Only your church sees this, and your prayer goes only to the pastors. Nothing is posted, and "
            "nothing is sent to you from it.")
    body = f"""<header class="ln-mast"><p class="ln-eb">I'm new here</p><h1 class="ln-disp">Tell us about <em>you</em></h1>
<p class="ln-sub">Tell {church} you're new, and get a simple path to find your place. It takes a minute.</p></header>{shown}
<form method="post" action="{PATH}">
<fieldset><legend class="ln-q">Is this new for you?</legend><div class="ln-choice">
{_radio("first", "yes", "I'm new", "First time, or just started coming", first)}
{_radio("first", "no", "I've been coming a while", "But I'd like to find my place", not first)}
</div></fieldset>
<label class="ln-q" for="imn-heard">How did you hear about us?</label>
<select class="ln-field" id="imn-heard" name="heard"><option value="">Choose one (optional)</option>{heard}</select>
<fieldset class="ln-kidsq"><legend class="ln-q">Do you have kids?</legend><div class="ln-kids">
<label class="ln-chip"><input type="radio" name="kids" value="no"{"" if kids else " checked"}>No</label>
<label class="ln-chip"><input type="radio" name="kids" value="yes"{" checked" if kids else ""}>Yes</label></div>
<div class="ln-ages"><label for="imn-ages">{ages_label}</label>
<input class="ln-field" id="imn-ages" name="ages" maxlength="{AGES_MAX}" autocomplete="off" placeholder="Like 4 and 7" value="{_e(app.get("ages") or "")}"></div>
</fieldset>
<fieldset class="ln-wants"><legend class="ln-q">I'd like to…</legend><p class="ln-hint">Pick any. You can change these later.</p>
<div class="ln-choice">{boxes}</div></fieldset>{more}
<label class="ln-q" for="imn-prayer">Anything we can pray for?</label>
<textarea class="ln-ta" id="imn-prayer" name="prayer" rows="4" maxlength="{PRAYER_MAX}" placeholder="Only our pastors see this."></textarea>
{texts}<div class="ln-send"><button class="ln-btn block" type="submit">Tell the church</button></div>
<p class="ln-fine">{icon("lock", 15)}<span>{_e(fine)}</span></p>
</form>"""
    return _shell(dict(business), site, "I'm new here", _wrap(body, page=True), tab="connect", who=dict(me), back=BACK)


DONE_WORDS = {
    "saved": "{church} knows you're here.",
    "same": "{church} already has this. Nothing changed.",
    "noprayer": "{church} knows you're here.",
    "care": "{church} knows you're here.",
}


def render_path(business: Mapping[str, Any], site: Any, request: Request, me: Mapping[str, Any],
                app: Dict[str, Any], rows: List[Dict[str, Any]]) -> str:
    """Your path, after they've told the church."""
    from member_portal import _shell
    import member_portal_church as mpc
    church = (business.get("name") or "").strip() or "the church"
    done = str(request.query_params.get("done") or "")
    handed = bool(app.get("follow_up"))
    lead = ""
    if done in DONE_WORDS:
        first = _plain(me.get("name"), 80).split(" ")[0] if _plain(me.get("name"), 80) else ""
        said = DONE_WORDS[done].format(church=_e(church))
        extra = ""
        if done == "noprayer":
            extra = ('<p>Your prayer didn\'t send just now. You can send it from '
                     '<a href="/my/prayer">Prayer</a>.</p>')
        elif done == "care":
            extra = f'<p role="alert">{_e(mpc.DONE["care"])}</p>'
        elif app.get("prayer") and done == "saved":
            extra = "<p>Your prayer went only to the pastors.</p>"
        lead = (f'<div class="ln-lead"><span class="ln-ok">{icon("check", 20)}</span><div>'
                f'<b>Thank you{", " + _e(first) if first else ""}. <em>Welcome.</em></b><p>{said}</p>{extra}</div></div>')
    items = []
    for r in rows:
        ink = HUE_INK.get(r["hue"], "var(--acc)")
        pick = '<span class="ln-pick">Your pick</span>' if r["picked"] else ""
        inner = (f'<span class="ln-aic" style="--k:{ink}">{icon(r["icon"])}</span>'
                 f'<span class="ln-wt"><b>{_e(r["title"])}{pick}</b><span>{_e(r["sub"])}</span></span>')
        if r["href"]:
            items.append(f'<a class="ln-wrow" href="{_e(r["href"])}">{inner}<span class="ln-chev">{icon("chev")}</span></a>')
        else:
            items.append(f'<div class="ln-wrow">{inner}<span></span></div>')
    reach = " Someone from the church will reach out to you soon." if handed else ""
    path = (f'<div class="ln-list">{"".join(items)}</div>' if items else
            f'<p class="ln-none">{_e(church)} will help you find your next step.{_e(reach)}</p>')
    body = f"""<header class="ln-mast"><p class="ln-eb">I'm new here</p><h1 class="ln-disp">Your <em>path</em></h1>
<p class="ln-sub">A few simple next steps at {_e(church)}.{_e(reach) if items else ""}</p></header>{lead}
<div class="ln-sec"><h2 class="ln-h2">Your next steps</h2></div>{path}
<a class="ln-again" href="{PATH}?edit=1">Change what you told us</a>"""
    return _shell(dict(business), site, "Your path", _wrap(body, page=True), tab="connect", who=dict(me), back=BACK)


# ─── the pages ────────────────────────────────────────────────────────


def _go(target: str, **q: str) -> RedirectResponse:
    from member_portal import _SECURE_HEADERS
    if target not in (PATH, "/my"):
        target = "/my"
    q = {k: v for k, v in q.items() if v}
    return RedirectResponse(f"{target}?{urlencode(q)}" if q else target, status_code=303, headers=_SECURE_HEADERS)


def _space_ok() -> bool:
    """The Church space: not Kids, and not Youth (a teen's, or an adult
    leader who switched in)."""
    import member_spaces as msp
    return (msp.CURRENT.get() or {}).get("space", "church") == "church"


async def serve(request: Request, church: Mapping[str, Any], sess: Mapping[str, Any], me: Mapping[str, Any]):
    """GET /my/new (member_portal._serve_page): the form before they've told
    the church (or with ?edit=1), Your path after. (html, status) or a
    redirect. A read that fails is "try again", never a 500."""
    from member_portal import render_try_again
    biz, site = church["business"], church.get("site")
    if not _space_ok() or not adult(me) or not await asyncio.to_thread(open_here, request, biz, sess):
        return _go("/my")
    try:
        app = await asyncio.to_thread(read_app, str(biz["id"]), str(me["id"]))
        if app is None:
            return render_try_again(biz, site), 503
        if not app.get("at") or request.query_params.get("edit") == "1":
            return render_form(biz, site, request, me, app, preview=bool(sess.get("preview"))), 200
        classes, groups, asks = await asyncio.gather(asyncio.to_thread(classes_part, biz, me),
                                                     asyncio.to_thread(groups_part, biz, me),
                                                     asyncio.to_thread(asks_part, biz, me))
        rows = path_rows(classes, groups, asks, list(app.get("wants") or []), handed=bool(app.get("follow_up")))
        return render_path(biz, site, request, me, app, rows), 200
    except Exception:  # noqa: BLE001
        logger.warning("im new: the page failed", exc_info=True)
        return render_try_again(biz, site), 503


def _allowed(business: Mapping[str, Any], me: Mapping[str, Any]) -> bool:
    """Its own budget per member (member_im_new), on top of the member app's
    (member_action). Fails closed."""
    import rate_limit
    key = f"{business['id']}|{me['id']}"
    return rate_limit.allow_strict("member_im_new", key) and rate_limit.allow_strict("member_action", key)


@router.post(PATH, include_in_schema=False)
async def post_new(request: Request):
    """Save what they told the church. Same-origin, the live session decides
    who (never the form), the owner's preview saves nothing."""
    import member_portal as mp
    church = await mp._church_or_404(request)
    biz = church["business"]
    sess = await asyncio.to_thread(mp._session_for, request, church)
    form = await request.form()
    if not sess:
        return _go("/my")
    if sess.get("unavailable"):
        return _go(PATH, err="error")
    if not await asyncio.to_thread(open_here, request, biz, sess):
        return _go("/my")
    if sess.get("preview"):
        return _go(PATH, err="preview")
    me = sess.get("me")
    if not me or not adult(me):
        return _go("/my")
    if not await asyncio.to_thread(_allowed, biz, me):
        return _go(PATH, err="slow", edit="1")
    import new_here
    answers = clean(form, form.getlist("wants") if hasattr(form, "getlist") else form.get("wants") or [],
                    path=await asyncio.to_thread(new_here.path_on, biz.get("id")))
    ok, code = await asyncio.to_thread(save, biz, me, answers)
    if not ok:
        return _go(PATH, err=code, edit="1")
    import rate_limit
    await asyncio.to_thread(join_path, biz, me, answers, texts_ok=str(form.get(TEXTS_NAME) or "") == "yes",
                            ip=rate_limit.trusted_client_ip(request) or "",
                            user_agent=request.headers.get("user-agent") or "")
    return _go(PATH, done=code)


def join_path(business: Mapping[str, Any], me: Mapping[str, Any], a: Mapping[str, Any], *, texts_ok: bool,
              ip: str = "", user_agent: str = "") -> Optional[Dict[str, Any]]:
    """The Welcome Path (2026-11-20): a member's "Text me" yes is kept
    (sms_consents, source member_app_new) for the mobile on their record,
    and a member who's new ("I'm new") joins the path, door "app": the
    welcome texts with that yes, the call either way. One guest, one path:
    someone already on one this week starts nothing new. New here's
    metadata as it stands, or None (the path is off, they've been coming a
    while, a read failed). Sync; never raises: what they told the church is
    already saved."""
    import new_here
    biz = str(business["id"])
    try:
        if not new_here.path_on(biz):
            return None
        rows = _rows(f"/contacts?id=eq.{_q(me['id'])}&business_id=eq.{_q(biz)}"
                     "&select=id,name,phone,metadata&limit=1")
        if not rows:
            return None
        person = rows[0]
        church = new_here._business(biz)
        # The box shows only where the church's texts would go: a yes from
        # anywhere else (an old page, a hand-made post) isn't one.
        texts_ok = bool(texts_ok and church and new_here.can_text(church)
                        and new_here.keep_yes(biz, person.get("phone"), source=new_here.YES_SOURCES["app"],
                                              name=person.get("name") or "", ip=ip, user_agent=user_agent))
        if not a.get("first_time") or not church:
            return None
        return new_here.enroll(church, person, door="app", texts_ok=texts_ok)
    except Exception:  # noqa: BLE001
        logger.warning("im new: the Welcome Path wasn't joined (business %s)", biz[:8], exc_info=True)
        return None


# ─── Connect's card ───────────────────────────────────────────────────


def _me_of(ctx: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    ctx = ctx or {}
    me = ctx.get("me") or (ctx.get("session") or {}).get("me")
    return dict(me) if isinstance(me, Mapping) and me.get("id") else None


def new_here_card(business: Mapping[str, Any], ctx: Optional[Mapping[str, Any]], request: Any) -> str:
    """Connect's "Your next step" card: Start before the member has told the
    church, Your path after. "" where it doesn't show (a switch, not a
    church, Youth or Kids, a teen, no member).

    ctx: {"me": the signed-in member} or {"session": member_portal's session}
    (either works), and "space" when the caller knows it (else
    member_spaces.CURRENT). The page wears the redesign already when this is
    drawn (member_lumen.here()); with here() unset, it asks
    member_lumen.visible (pass the session for the preview's rules).

    Sync, and it may read the database once on a miss (told_state keeps the
    answer); from async code call card_async. Never raises."""
    try:
        me = _me_of(ctx)
        if not me or not on() or not is_church(business) or not adult(me):
            return ""
        space = (ctx or {}).get("space")
        if space is None:
            import member_spaces as msp
            space = (msp.CURRENT.get() or {}).get("space", "church")
        if space != "church":
            return ""
        import member_lumen
        session = (ctx or {}).get("session") or {"me": me}
        if not member_lumen.here() and not lumen(request, business, session):
            return ""
        state = told_state(str(business["id"]), str(me["id"]))
        return card_html(bool(state and state.get("at")))
    except Exception:  # noqa: BLE001
        logger.warning("im new: the card was left out", exc_info=True)
        return ""


async def card_async(business: Mapping[str, Any], ctx: Optional[Mapping[str, Any]], request: Any) -> str:
    """new_here_card off the event loop (it may read once)."""
    return await asyncio.to_thread(new_here_card, business, ctx, request)
