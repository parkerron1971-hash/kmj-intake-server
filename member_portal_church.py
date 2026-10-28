"""
member_portal_church.py — the member page, part 2: coming up, prayer, my details.

Part 1 (member_portal.py) signs a member in and shows their giving. This
adds the three things Kevin asked the page to do next, each acting as the
signed-in person — no name or email to type, because the church already
knows who they are:

  COMING UP  The church's upcoming occasions (every active Services &
             Events room, the same list the public events page builds).
             "I'm coming", serve in an open role, or "Can't make it".
             One signup per person per occasion: acting again replaces
             their earlier answer. Capacity, the occasion's own roles and
             role fills are the public page's rules (events_rsvp_router),
             and every write carries the entry's updated_at, so a
             concurrent change is re-read rather than overwritten.
  PRAYER     A request goes to Prayer & care (ministry_care_requests —
             owner-only, never scored, never followed up automatically),
             linked to the member's record.
  MY DETAILS Phone and mailing address, written onto their own contact
             (metadata.mailing_address). Email is how they sign in, so it
             changes only through the church office.

Every route: same-origin POST, a live session re-checked against the
records, a per-person rate limit, and a redirect back with a short code
(never a name or an address in the URL).
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

import sb_clients

logger = logging.getLogger("member_portal_church")

router = APIRouter(tags=["member-portal"])

PRAYER_MAX = 4000
FIELD_MAX = 120
PHONE_RE = re.compile(r"^[0-9+()\-.\s]{7,25}(\s*(x|ext\.?)\s*\d{1,6})?$", re.IGNORECASE)

DONE = {
    "coming": "You're on the list. See you there.",
    "serving": "Thank you for serving. You're on the roster.",
    "cant": "Thanks for letting us know.",
    "prayer": "Your prayer request was sent privately to the pastor.",
    "details": "Your details are saved.",
    "photo": "Your photo is saved.",
    "photo_removed": "Your photo is removed.",
    "posted": "Posted to Youth.",
    "post_removed": "Your post is removed.",
    "released": "Released. They're on their way home.",
    "lesson_posted": "Lesson posted. Parents see it now.",
    "lesson_removed": "Your lesson is removed.",
    "joined": "You're in. The group's leader will see you on the list.",
    "left": "You've left that group.",
    "here": "Thanks for joining us. You're counted as here today.",
    "meeting_ended": "The meeting has ended for everyone.",
    "sent": "Sent.",
    "held": "Your message was held for review by the church's safety officers. Only you can see it for now.",
    "care": "You're not alone. If you're thinking about hurting yourself, call or text 988 (the Suicide & Crisis "
            "Lifeline) any time, day or night. If you're in danger right now, call 911. Someone from the church "
            "will reach out to you.",
    "accepted": "You can message each other now.",
    "ignored": "Request ignored. They aren't told.",
    "blocked": "Blocked. They can't message you, and they aren't told.",
    "reported": "Thanks. The church's safety officers will look at it. The sender isn't told who reported it.",
    "welcome_msgs": "Welcome to messaging.",
    "group_interest": "Thanks. The church office knows you'd like to join a group and can reach out when one starts.",
    "class_joined": "You're in. Your class is below, and your teacher sees you on the list.",
    "class_already": "You're already in that class. It's below.",
    # A group's own page (member_portal_groups.py).
    "asked": "Asked. A leader of the group will say yes soon.",
    "withdrawn": "Your request is taken back.",
    "said_yes": "They're in. They'll see the group now.",
    "not_now": "Okay. They aren't added, and the church office can help them find another group.",
    "post_up": "Posted to the Board. Everyone in the group sees it.",
    "post_later": "Scheduled. It goes out then; until then only the group's leaders see it.",
    # A group's prayer wall (group_prayer).
    "prayer_up": "It's on the wall. Your group can pray with you now.",
    "prayer_pastors": "Sent privately to the pastors. The group won't see it.",
    "prayer_pastor_first": "This went straight to a pastor, not the wall. They'll reach out to you.",
    "praying": "Thank you for praying.",
    "praised": "Praise God!",
    "unmarked": "Taken back.",
    "answered": "Marked answered. Praise God!",
    "prayer_down": "Taken off the wall.",
    # Gatherings (group_gatherings).
    "rsvp_going": "You're going. See you there!",
    "rsvp_maybe": "Marked maybe.",
    "rsvp_no": "Thanks for letting your group know.",
    "here": "You're counted. Welcome!",
    "roll_saved": "Attendance saved. Thank you.",
    "schedule_saved": "Saved. Everyone sees the new time.",
    "skipped": "That gathering is skipped. Your group sees it.",
    "unskipped": "That gathering is back on.",
    "bring_added": "Added to the list. Your group can pick it now.",
    "guest_added": "Added. The office will welcome them as a first-time guest.",
    "guest_removed": "Taken off the list.",
    "bring_removed": "Taken off the list.",
    "bring_claimed": "Thank you! Your group sees you're bringing it.",
    "bring_undone": "Done. It's open again for someone else.",
    "study_posted": "Posted. Your group sees this week's study now.",
    "study_saved": "Saved. Your group sees the changes.",
    # How you hear about a group's chat (group_chat_notify).
    "chat_every": "You'll get a note for each message.",
    "chat_evening": "You'll get one note at 7 PM when there's something new.",
    "chat_replies": "You'll hear only when someone replies to you.",
    "post_down": "That post is taken down.",
    "pinned": "Pinned to the top.",
    "unpinned": "Unpinned.",
    "names_full": "The group shows full names now.",
    "extras_on": "Photos and polls are on in the group's chat.",
    "extras_off": "Photos and polls are off in the group's chat.",
    "voted": "Your vote is in.",
    "unvoted": "Your vote is taken back.",
    "names_first": "The group shows first names now.",
    "hidden": "Taken down. The church's safety officers will look at it.",
    # The member directory (member_directory).
    "dir_on": "You're in the directory. Only your name and photo show until you turn more on.",
    "dir_saved": "Saved. The directory shows only what you chose.",
    "dir_off": "You're out of the directory.",
    # Event sign-ups (church_event_signups).
    "signup_paid": "Thank you. You're signed up, and your receipt is on its way to your email.",
    "signup_done": "You're signed up. The details are on their way to your email.",
    "signup_waiting": "You're on the waitlist. If a place opens, we'll email you a link to take it.",
    "signup_already": "You're already signed up for that one.",
}
ERRORS = {
    "full": "That one is full now.",
    "role": "That role was just filled, or isn't on this event any more.",
    "gone": "That event isn't available any more.",
    "past": "That event has already happened.",
    "busy": "Someone else was updating that event at the same moment. Please try again.",
    "error": "That didn't save. Please try again in a moment.",
    "slow": "That's a lot at once. Wait a few minutes, then try again.",
    "empty": "Write your prayer request first.",
    "phone": "That phone number doesn't look right.",
    "group_full": "That group is full now. Ask the church office about the next one.",
    "group_closed": "That group isn't taking new people right now.",
    "group_gone": "That group isn't running any more.",
    "class_closed": "That class isn't taking sign-ups right now.",
    "class_dropped": "That class can't be joined again here. The church office can add you back.",
    "leader": "You lead this group, so to step down, talk to the church office.",
    "preview": "This is a preview, so nothing is saved.",
    "photo_bad": "That file isn't a photo we can use. Choose a JPG, PNG or WebP under 12 MB.",
    "photo_no": "That picture can't be used as your photo. Choose another.",
    "photo_busy": "Photos can't be checked just now, so nothing was saved. Please try again in a minute.",
    "not_leader": "Only leaders the church office approved can post to Youth.",
    "empty_post": "Write your post first.",
    "post_no": "That post can't go out as written. Change it, or talk to the church office.",
    "post_busy": "Posts can't be checked just now, so nothing went out. Please try again in a minute.",
    "prayer_no": "That can't go on the wall as written. Change it, or send it to the pastors instead.",
    "prayer_gone": "That prayer isn't on the wall any more.",
    "not_yours": "Only the person who asked can do that.",
    "no_gathering": "There's no gathering coming up to answer for.",
    "here_closed": "“I'm here” opens 30 minutes before the gathering starts.",
    "roll_closed": "Attendance opens on the day of the gathering.",
    "schedule_bad": "Choose a day and a time.",
    "bring_empty": "Write what to bring first.",
    "guest_empty": "Write their first name first.",
    "bring_full": "That list is full. Take something off first.",
    "bring_gone": "That isn't on the list any more.",
    "bring_taken": "Someone just picked that one. Choose another.",
    "bring_one_each": "You're already bringing something. Undo it first to pick another.",
    "study_gone": "That study isn't here any more.",
    "later_bad": "Pick a time from 5 minutes to 30 days from now.",
    "post_gone": "That post isn't on the Board any more.",
    "notes_off": "Notes go through member messaging, and it's off at your church right now.",
    "notes_none": "Everyone has been coming lately. Nobody needs a note right now.",
    "study_empty": "Keep at least one question.",
    "not_kids_leader": "Only Kids leaders the church office approved can do that.",
    "lesson_incomplete": "Add a title and what they learned.",
    "lesson_link": "A video link has to start with https://",
    "lesson_room": "Choose one of the rooms you lead.",
    "not_live": "The service isn't live right now.",
    "chat_closed": "The chat is closed right now.",
    "muted": "The host has paused your chat for this service.",
    "link": "Links can't be shared in the chat.",
    "empty_chat": "Write a message first.",
    "slow_chat": "That's a lot of messages at once. Wait a moment, then try again.",
    "signed_out": "Your sign-in ended. Open the page again to sign back in.",
    "video_off": "Live meetings aren't available right now. Please try again later.",
    "not_host": "Only leaders the church has approved can host a group meeting.",
    "msg_off": "Messaging isn't turned on at this church yet.",
    "screen_off": "Messages can't be checked right now, so nothing was sent. Please try again in a moment.",
    "gone_chat": "That chat isn't available.",
    "cant_send": "You can't post in this chat right now.",
    "teen_adult": "Private messages between a teen and an adult who isn't their parent aren't allowed.",
    "recipient_off": "You can't message this person right now.",
    "two_adults": "This group's chat opens once two adult leaders can message.",
    "not_enabled": "Ask the church office to turn on messaging for you.",
    "no_birthdate": "Messaging needs your birthdate on your record.",
    "declined": "You ignored this request.",
    "group_invite": "This group is by invitation. Ask one of its leaders or the church office.",
    "group_ask": "This group's leaders say yes to new people. Ask to join from the group's page.",
    "not_group_leader": "Only the group's leaders can do that.",
    "not_in_group": "That's for people in the group.",
    "answered": "Someone already answered that request.",
    "group_board_only": "This group uses its Board only, so its chat is closed.",
    "leaders_write": "Only the group's leaders write in this chat. You can still react.",
    "poll_choices": "A poll needs at least two different choices.",
    "poll_where": "Polls are for group chats.",
    "polls_off": "This group's leaders have turned photos and polls off.",
    "photo_where": "Photos are for group chats.",
    "photo_teen": "Photos aren't shared in a chat with teens in it.",
    "chat_photo_no": "That photo can't be shared in the group. Choose another.",
    "poll_closed": "Voting on that poll has closed.",
    "poll_gone": "That poll isn't there any more.",
    "dir_closed": "The directory isn't open at your church right now.",
    "dir_adults": "The directory is for adult members.",
    "dir_members": "The directory is for members. If you're a member, ask the church office to mark you as one.",
    "dir_birthdate": "To list you, the church office needs your birthdate on your record. Ask the office to add it.",
    "dir_removed": "The church office took you out of the directory, so you can't add yourself back. Ask the office.",
    "alert_used": "You've already sent an after-hours alert tonight. Turn it off to send this; it reaches phones in the morning.",
    # Event sign-ups (church_event_signups).
    "signup": "That event takes sign-ups. Use Sign up on it below.",
    "signup_check": "Check your tickets and answers, then try again.",
    "signup_full": "That event just filled up. You can join its waitlist below.",
    "signup_closed": "Sign-ups for that event aren't open online right now.",
    "signup_gone": "That place has gone to the next person on the waitlist. Please call the church office.",
}


# ─── Occasions ────────────────────────────────────────────────────────


def _norm_name(s: Any) -> str:
    return " ".join(str(s or "").split()).casefold()


def is_mine(signup: Dict[str, Any], me: Dict[str, Any]) -> bool:
    """A signup belongs to this person when it carries their contact id —
    or carries NO contact id and exactly their name: the office typed
    "Ana Rivers" onto the roster before Ana ever signed in, and her own
    answer must replace that line, not sit beside it."""
    cid = str(signup.get("contact_id") or "")
    if cid:
        return cid == str(me["id"])
    mine = _norm_name(me.get("name"))
    return bool(mine) and _norm_name(signup.get("name")) == mine


def can_see(data: Dict[str, Any], f: Dict[str, Any], me: Dict[str, Any]) -> bool:
    """Public: yes. Private: never (the church only). Invite only: when it
    was shared with them, or they are on its roster — by record, or by the
    name the office typed before they had one."""
    import events_rsvp_router as er
    v = er.occasion_visibility(data)
    if v != "invite":
        return v == "public"
    return er.visible_to_member(data, str(me["id"]), f["signups_field"]) or any(
        is_mine(s, me) for s in er.read_signups(data, f["signups_field"]))


def _roster_modules(business_id: str) -> Optional[List[Dict[str, Any]]]:
    """The church's active Services & Events rooms, or None when the read
    failed ("try again", never "that event is gone")."""
    mods = sb_clients.sb_get_as_service(
        f"/custom_modules?business_id=eq.{quote(str(business_id), safe='')}"
        f"&archetype=eq.event_roster&is_active=eq.true&select=id,name,archetype_params&limit=50")
    return mods if isinstance(mods, list) else None


def upcoming_for(business_id: str, me: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """The church's upcoming occasions, each with this person's answer.
    None when the read failed (the page says so; it never shows "nothing
    coming up" for a failed read).

    Each room is read NEWEST first: occasions stay active after they
    happen, so an oldest-first read with a cap would, after a year of
    Sundays, return only the past and drop what is actually coming."""
    import events_rsvp_router as er
    mods = _roster_modules(business_id)
    if mods is None:
        return None
    if not mods:
        return []
    by_mod: Dict[str, List[Dict[str, Any]]] = {}
    entries: Dict[str, Dict[str, Any]] = {}
    for m in mods:
        rows = sb_clients.sb_get_as_service(
            f"/module_entries?module_id=eq.{quote(str(m['id']), safe='')}"
            f"&business_id=eq.{quote(str(business_id), safe='')}&status=eq.active"
            f"&select=id,module_id,data,updated_at&order=created_at.desc&limit=200")
        if not isinstance(rows, list):
            return None
        by_mod[str(m["id"])] = rows
        entries.update({str(r.get("id")): r for r in rows})
    fields = {str(m["id"]): er.resolve_fields(m.get("archetype_params")) for m in mods}
    out = er.build_occasions(mods, by_mod, include=lambda data, f: can_see(data, f, me))
    for o in out:
        entry = entries.get(str(o.get("entry_id"))) or {}
        f = fields.get(str(o.get("module_id")))
        signups = er.read_signups(entry.get("data") or {}, f["signups_field"]) if f else []
        mine = next((s for s in signups if is_mine(s, me)), None)
        o["mine"] = ({"status": mine.get("status") or "yes", "role": mine.get("role")} if mine else None)
    import church_event_signups
    return church_event_signups.annotate(str(business_id), out, contact_id=str(me["id"]))


def _registration_key(business_id: str, entry_id: str, email: str) -> str:
    """The key the public events page stores when someone RSVPs there
    (events_rsvp_router.public_event_rsvp) — so an answer given here can
    clear it and the public page does not later say "already registered"."""
    import hashlib
    return hashlib.sha256(f"{business_id}:{entry_id}:{str(email or '').strip().lower()}".encode()).hexdigest()


def member_rsvp(business_id: str, me: Dict[str, Any], entry_id: str, action: str,
                role_id: str = "") -> Tuple[bool, str]:
    """Record this person's answer for one occasion. Returns (ok, code):
    a DONE code on success, an ERRORS code otherwise. Their earlier answer
    for the occasion is replaced, never duplicated, and keeps whatever the
    office wrote on it (a note, say)."""
    import events_rsvp_router as er
    if action not in ("coming", "serve", "cant"):
        return False, "error"
    cid = str(me["id"])
    name = (me.get("name") or "").strip() or "A member"
    for _ in range(4):
        rows = sb_clients.sb_get_as_service(
            f"/module_entries?id=eq.{quote(entry_id, safe='')}&business_id=eq.{quote(str(business_id), safe='')}"
            f"&status=eq.active&select=id,module_id,data,updated_at&limit=1")
        if not isinstance(rows, list):
            return False, "error"
        if not rows:
            return False, "gone"
        entry = rows[0]
        mods = _roster_modules(business_id)
        if mods is None:
            return False, "error"
        module = next((m for m in mods if str(m.get("id")) == str(entry.get("module_id"))), None)
        if not module:
            return False, "gone"
        f = er.resolve_fields(module.get("archetype_params"))
        data = dict(entry.get("data") or {})
        signups = er.read_signups(data, f["signups_field"])
        # Private, or invite-only and not shared with them: it does not
        # exist as far as their page is concerned.
        if not can_see(data, f, me):
            return False, "gone"
        day = er._parse_day(data.get(f["date_field"]))
        if day is None or day < date.today():
            return False, "past"
        old = next((s for s in signups if is_mine(s, me)), None) or {}
        others = [s for s in signups if not is_mine(s, me)]
        base = {k: v for k, v in old.items() if k != "role"}
        if action == "coming":
            import church_event_signups
            if church_event_signups.blocks_free_rsvp(str(business_id), str(entry["id"])):
                return False, "signup"
        if action in ("coming", "serve"):
            cap = er._capacity_of(data, f["capacity_field"])
            if cap is not None and er.attending_count(others) >= cap:
                return False, "full"
            new: Dict[str, Any] = {**base, "name": name, "status": "yes", "contact_id": cid}
            if action == "serve":
                role = next((r for r in er.occasion_roles(data, f["roles"]) if r.get("id") == role_id), None)
                if not role or er.role_fill(role, others)["full"]:
                    return False, "role"
                new["role"] = role_id
            others.append(new)
            done = "serving" if action == "serve" else "coming"
        else:
            others.append({**base, "name": name, "status": "no", "contact_id": cid})
            keys = data.get("_registration_keys")
            if isinstance(keys, dict):
                data["_registration_keys"] = {
                    k: v for k, v in keys.items()
                    if k != _registration_key(str(business_id), str(entry["id"]), me.get("email") or "")}
            done = "cant"
        data[f["signups_field"]] = others
        revision = entry.get("updated_at")
        if not revision:
            return False, "error"
        saved = sb_clients.sb_patch_as_service(
            f"/module_entries?id=eq.{quote(str(entry['id']), safe='')}"
            f"&business_id=eq.{quote(str(business_id), safe='')}"
            f"&updated_at=eq.{quote(str(revision), safe='')}", {"data": data})
        if isinstance(saved, list) and saved:
            return True, done
        # A concurrent change (or a failed write): read again and retry.
    return False, "busy"


# ─── Prayer and details ──────────────────────────────────────────────


def save_prayer(business_id: str, me: Dict[str, Any], text: str, confidential: bool, youth: bool = False,
                wants_call: bool = False, source: str = "") -> bool:
    """A prayer request from the member page. `confidential` keeps it with
    the pastors; otherwise the person agreed to share it with the prayer
    team (church_prayer hands it to a member who leads prayer). A youth
    request is always the pastors'."""
    import church_prayer
    text = (text or "").strip()[:PRAYER_MAX]
    submission = {
        "name": (me.get("name") or "").strip(), "email": me.get("email") or "",
        "phone": me.get("phone") or "", "prayer_request": text,
        "confidential": "yes" if confidential or youth else "no",
        "source": source or ("Member page, Youth" if youth else "Member page"),
    }
    rows = sb_clients.sb_post_as_service("/ministry_care_requests", {
        "business_id": str(business_id), "form_id": None, "contact_id": str(me["id"]),
        "status": "new", "submission": submission,
        **church_prayer.consent_columns(submission, share=not (confidential or youth), wants_call=wants_call),
    })
    if isinstance(rows, list) and rows:
        church_prayer.on_new(str(business_id), rows[0])
        return True
    return False


def load_me(business_id: str, contact_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/contacts?id=eq.{quote(str(contact_id), safe='')}&business_id=eq.{quote(str(business_id), safe='')}"
        f"&select=id,name,email,phone,metadata,updated_at&limit=1")
    if not isinstance(rows, list) or not rows:
        return None
    return rows[0]


def clean_details(form: Dict[str, Any], stored_phone: str = "") -> Tuple[Optional[Dict[str, Any]], str]:
    phone = str(form.get("phone") or "").strip()
    # The number the office already stored is never re-judged: a member
    # changing only their address must not be stopped by its format.
    if phone and phone != (stored_phone or "").strip() and (
            not PHONE_RE.match(phone) or len(re.sub(r"\D", "", phone)) < 7):
        return None, "phone"
    addr = {k: str(form.get(k) or "").strip()[:FIELD_MAX] for k in ("line1", "line2", "city", "state", "postal")}
    return {"phone": phone, "address": addr}, ""


def update_details(business_id: str, contact_id: str, details: Dict[str, Any]) -> bool:
    """Write phone + mailing address onto the member's own contact, guarded
    by its updated_at so an office edit at the same moment is not lost."""
    for _ in range(3):
        me = load_me(business_id, contact_id)
        if not me or not me.get("updated_at"):
            return False
        meta = dict(me.get("metadata") or {})
        addr = {k: v for k, v in details["address"].items() if v}
        if addr:
            meta["mailing_address"] = addr
        else:
            meta.pop("mailing_address", None)
        meta["details_updated_by_member_at"] = datetime.now(timezone.utc).isoformat()
        saved = sb_clients.sb_patch_as_service(
            f"/contacts?id=eq.{quote(str(contact_id), safe='')}&business_id=eq.{quote(str(business_id), safe='')}"
            f"&updated_at=eq.{quote(str(me['updated_at']), safe='')}",
            {"phone": details["phone"] or None, "metadata": meta})
        if isinstance(saved, list) and saved:
            return True
    return False


# ─── Pages ────────────────────────────────────────────────────────────


# ─── Groups ───────────────────────────────────────────────────────────
# "My groups": the groups this member belongs to, and the current ones
# open to new people that they could join. A member sees when and where a
# group meets and its leaders' FIRST names — never who else belongs (the
# member directory, member_directory.py, is its own opt-in page). Joining an open group adds them as a member at
# once; the leader sees them on the Groups page. A leader can't leave
# here (they talk to the office), so a group is never left leaderless by
# a tap.

GROUP_KINDS = {"small_group": "Small group", "team": "Serving team", "class": "Class", "ministry": "Ministry"}


def _first(name: Any) -> str:
    return (str(name or "").strip().split(" ") or [""])[0]


def groups_for(business_id: str, me: Dict[str, Any]) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    """{'mine': [...], 'open': [...]}, or None when the records couldn't be
    read (the page says "try again" rather than showing no groups)."""
    groups = sb_clients.sb_get_as_service(
        f"/groups?business_id=eq.{business_id}&active=eq.true"
        f"&select=id,name,kind,description,meets,location,capacity,open_to_join,join_mode,youth&order=name.asc&limit=500")
    members = sb_clients.sb_get_as_service(
        f"/group_members?business_id=eq.{business_id}&select=group_id,contact_id,role,can_host_live&limit=20000")
    if groups is None or members is None:
        return None
    # The groups this person already asked to join (member_portal_groups);
    # a failed read only loses the "Asked" mark.
    import member_portal_groups as mpg
    asked = mpg.my_requests(business_id, str(me["id"])) or set()
    leader_ids = sorted({str(m["contact_id"]) for m in members if m.get("role") == "leader"})
    names: Dict[str, str] = {}
    for i in range(0, len(leader_ids), 150):
        rows = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{business_id}&id=in.({','.join(leader_ids[i:i + 150])})&select=id,name")
        if rows is None:
            return None
        names.update({str(r["id"]): _first(r.get("name")) for r in rows})
    me_id = str(me["id"])
    my_role = {str(m["group_id"]): m.get("role") for m in members if str(m["contact_id"]) == me_id}
    my_host = {str(m["group_id"]) for m in members
               if str(m["contact_id"]) == me_id and m.get("role") == "leader" and m.get("can_host_live")}
    count: Dict[str, int] = {}
    for m in members:
        count[str(m["group_id"])] = count.get(str(m["group_id"]), 0) + 1
    mine, open_ = [], []
    for g in groups:
        gid = str(g["id"])
        item = {
            "id": gid, "name": g.get("name") or "", "kind": GROUP_KINDS.get(g.get("kind"), "Group"),
            "about": g.get("description") or "", "meets": g.get("meets") or "", "location": g.get("location") or "",
            "leaders": [names[str(m["contact_id"])] for m in members
                        if str(m["group_id"]) == gid and m.get("role") == "leader" and str(m["contact_id"]) in names],
            "full": bool(g.get("capacity")) and count.get(gid, 0) >= int(g["capacity"]),
            "mode": join_mode(g), "asked": gid in asked,
        }
        if gid in my_role:
            mine.append({**item, "role": my_role[gid], "host": gid in my_host, "youth": bool(g.get("youth"))})
        elif item["mode"] != "invite" and not item["full"]:
            open_.append(item)
    # Live group meetings (member_portal_group_live.py) for the groups
    # this person is in. A failed read only hides the Join buttons.
    if mine:
        import member_portal_group_live as mgl
        live = mgl.open_sessions(business_id, [g["id"] for g in mine]) or {}
        for g in mine:
            g["live"] = live.get(g["id"])
    return {"mine": mine, "open": open_}


def join_mode(g: Dict[str, Any]) -> str:
    """open | ask | invite (groups.join_mode, 2026-10-20). A row read without
    the column keeps the older rule: open_to_join means join right away."""
    mode = g.get("join_mode")
    if mode in ("open", "ask", "invite"):
        return mode
    return "open" if g.get("open_to_join") else "invite"


def member_join(business_id: str, me: Dict[str, Any], group_id: str) -> Tuple[bool, str]:
    """Join a group that lets people straight in. A group whose leaders say
    yes is asked from its page instead (member_portal_groups.ask)."""
    rows = sb_clients.sb_get_as_service(
        f"/groups?id=eq.{quote(group_id, safe='')}&business_id=eq.{business_id}"
        f"&select=id,active,open_to_join,join_mode,capacity&limit=1")
    if rows is None:
        return False, "error"
    if not rows or not rows[0].get("active"):
        return False, "group_gone"
    g = rows[0]
    mode = join_mode(g)
    if mode == "invite":
        return False, "group_closed"
    if mode == "ask":
        return False, "group_ask"
    return add_member(business_id, me, g)


def add_member(business_id: str, me: Dict[str, Any], g: Dict[str, Any]) -> Tuple[bool, str]:
    """Put this person in the group as a member: room permitting, and
    harmless when they're already in."""
    if g.get("capacity"):
        members = sb_clients.sb_get_as_service(f"/group_members?group_id=eq.{g['id']}&select=contact_id&limit=10001")
        if members is None:
            return False, "error"
        if any(str(m["contact_id"]) == str(me["id"]) for m in members):
            return True, "joined"
        if len(members) >= int(g["capacity"]):
            return False, "group_full"
    saved = sb_clients.sb_post_as_service(
        "/group_members?on_conflict=group_id,contact_id",
        {"group_id": g["id"], "contact_id": str(me["id"]), "business_id": business_id, "role": "member"},
        prefer="return=representation,resolution=ignore-duplicates")
    if saved is None:
        return False, "error"
    return True, "joined"


def member_leave(business_id: str, me: Dict[str, Any], group_id: str) -> Tuple[bool, str]:
    rows = sb_clients.sb_get_as_service(
        f"/group_members?group_id=eq.{quote(group_id, safe='')}&contact_id=eq.{me['id']}"
        f"&business_id=eq.{business_id}&select=role&limit=1")
    if rows is None:
        return False, "error"
    if not rows:
        return True, "left"
    if rows[0].get("role") == "leader":
        return False, "leader"
    ok = sb_clients.sb_delete_as_service(
        f"/group_members?group_id=eq.{quote(group_id, safe='')}&contact_id=eq.{me['id']}"
        f"&business_id=eq.{business_id}&role=eq.member")
    return (True, "left") if ok else (False, "error")


def _group_card(g: Dict[str, Any], action: str, pal: Dict[str, str], pool: Optional[List[str]] = None,
                used: Optional[set] = None, biz: Optional[Dict[str, Any]] = None) -> str:
    """A group on Connect. Mine: a row (its photo, name, when it meets,
    what's on) with its actions under it. One to join: a card in the
    "Find a group" row, with Join. Its picture is the one the church put
    on it, or a photo named for it, else the groups default picture
    (member_app_photos.choose)."""
    import member_app_ui as ui
    import member_app_photos as photos
    from member_portal import _e
    gid = _e(g["id"])
    title_id = f"mp-grp-{gid}"
    pic, look = photos.choose(biz or {}, f"group:{g['id']}", pool or [], title=g.get("name") or "", used=used)
    import member_app_samples as samples
    sample = ui.sample_tag() if samples.is_sample(g) else ""
    # The group's own page (member_portal_groups); a preview's sample has none.
    page = "" if sample else f"/my/groups/{gid}"
    name_html = (f'<a href="{page}" style="color:inherit;text-decoration:none">{_e(g.get("name") or "")}</a>'
                 if page else _e(g.get("name") or ""))
    picture = ui.picture(pic, look, "youth" if g.get("youth") else "groups")
    facts = " · ".join(_e(x) for x in (g.get("meets"), g.get("location")) if x)
    leaders = g.get("leaders") or []
    if action == "join":
        about = f'<p>{_e(g["about"])}</p>' if g.get("about") else ""
        led = f'<span>Led by {_e(", ".join(leaders))}</span>' if leaders else ""
        if g.get("asked") and page:
            # Asked already: the group's page shows where it stands.
            go = (f'<a class="mp-go mp-go-2" href="{page}" aria-describedby="{title_id}">'
                  f'{ui.icon("clock", 16)}Asked · waiting</a>')
        else:
            label = "Ask to join" if g.get("mode") == "ask" else "Join"
            go = (f'<form method="post" action="/my/groups/ask"><input type="hidden" name="group_id" value="{gid}">'
                  f'<button class="mp-go" type="submit" aria-describedby="{title_id}">{label}</button></form>')
        return (f'<article class="mb-find" aria-labelledby="{title_id}"><span class="mb-find-p">{picture}{sample}</span>'
                f'<div class="mb-find-b"><h3 id="{title_id}">{name_html}</h3>'
                f'{f"<span>{facts}</span>" if facts else ""}{led}{about}{go}</div></article>')
    live = g.get("live") or {}
    if live.get("status") == "live":
        chip = '<span class="mb-live-badge"><span class="mb-live-dot" aria-hidden="true"></span>Meeting now</span>'
    elif g.get("role") == "leader":
        chip = '<span class="mb-chip">You lead this group</span>'
    elif leaders:
        chip = f'<span>Led by {_e(", ".join(leaders))}</span>'
    else:
        chip = ""
    meet = ""
    if live:
        label = ("Join live meeting" if live.get("status") == "live" or g.get("host")
                 else "Meeting starting — waiting for leaders")
        meet = (f'<a class="mp-go" href="/my/groups/live/{_e(live["id"])}" aria-describedby="{title_id}">'
                f'<span class="mb-live-dot" aria-hidden="true"></span>{label}</a>')
    elif g.get("host"):
        meet = (f'<form method="post" action="/my/groups/live/start" class="mb-start">'
                f'<input type="hidden" name="group_id" value="{gid}">'
                f'<label class="mp-sr" for="mb-mode-{gid}">Kind of meeting</label>'
                f'<select class="mp-input" id="mb-mode-{gid}" name="mode">'
                f'<option value="meeting">Meeting: everyone can be on camera</option>'
                f'<option value="broadcast">Broadcast: only leaders on camera</option></select>'
                f'<button class="mp-go mb-soft" type="submit" aria-describedby="{title_id}">Start live meeting</button></form>'
                + ('<p class="mp-muted" style="margin:0;font-size:12px">A youth group meeting opens once a second '
                   'approved adult leader joins.</p>' if g.get("youth") else ''))
    if g.get("chat_on"):
        meet += f'<a class="mp-go mp-go-2" href="/my/messages/group/{gid}" aria-describedby="{title_id}">Open chat</a>'
    # The group's own page (member_portal_groups): its Board, who's in it.
    if page:
        meet = f'<a class="mp-go" href="{page}" aria-describedby="{title_id}">Open the group</a>' + meet
    leave = ""
    if g.get("role") != "leader":
        leave = (f'<form method="post" action="/my/groups"><input type="hidden" name="group_id" value="{gid}">'
                 f'<input type="hidden" name="action" value="leave">'
                 f'<button class="mp-link" type="submit" aria-describedby="{title_id}">Leave this group</button></form>')
    about = f'<div class="mb-grp-more"><p>{_e(g["about"])}</p></div>' if g.get("about") else ""
    return f"""<article class="mb-grp mp-occ" aria-labelledby="{title_id}">
  <div class="mb-grp-top"><span class="mb-grp-pic">{picture}</span>
  <div class="mb-grp-t"><h3 id="{title_id}">{name_html}{sample}</h3>{f'<span>{facts}</span>' if facts else ''}{chip}</div></div>
  {about}
  <div class="mp-actions">{meet}{leave}</div>
</article>"""


def render_groups(biz, site, request: Request, data: Optional[Dict[str, List[Dict[str, Any]]]],
                  who: Optional[Dict[str, Any]] = None, room: bool = False, serving: bool = False) -> str:
    """Connect: your groups, then groups to join. `room`: this member is in
    the church's All group leaders room (messaging on), so it has a door.
    `serving`: they're on a Sunday team (sunday_serving), so My serving does."""
    import member_app_ui as ui
    import member_app_photos as photos
    import member_portal_messaging as mpm
    from member_portal import _e, _shell, palette_for
    pal = palette_for(biz, site)
    pool = photos.photos(biz, site)
    if data is not None:
        on = mpm.turned_on(biz)
        for g in data["mine"]:
            g["chat_on"] = on
    if data is None:
        body = '<p class="mp-err" role="alert">Groups couldn\'t load just now. Please try again in a moment.</p>'
    elif not data["mine"] and not data["open"]:
        # Nothing to belong to yet: a designed page, never an empty list.
        church = _e(biz.get("name") or "the church")
        pic, look = photos.choose(biz, "groups", pool)
        art = ui.picture(pic, look, "groups", night=True)
        body = (f'<section class="mb-soon">{art}<div class="mb-soon-in"><span class="mb-kick">Starting soon</span>'
                f'<h2>Groups are coming</h2><p>Small groups at {church} will show up here: when they meet, who leads them, '
                f'and a way to join.</p></div></section>'
                f'<form method="post" action="/my/groups/interest" style="margin-top:14px">'
                f'<button class="mp-go" type="submit">{ui.icon("users", 18)}I\'d like to join a group</button></form>'
                f'<p class="mp-muted" style="margin-top:10px;text-align:center;font-size:14px">The church office hears from you '
                f'and can reach out when a group starts.</p>')
    else:
        used: set = set()
        mine = "".join(_group_card(g, "leave", pal, pool, used, biz) for g in data["mine"]) or \
            '<p class="mp-muted">You\'re not in a group yet. Find one below.</p>'
        open_ = "".join(_group_card(g, "join", pal, pool, used, biz) for g in data["open"])
        open_ = (f'<div class="mb-rail">{open_}</div>' if open_ else
                 '<p class="mp-muted">No groups are taking new people right now. Ask the church office what\'s starting soon.</p>')
        import member_app_samples as samples
        hint = (ui.sample_hint(samples.WHERE["groups"])
                if any(samples.is_sample(g) for g in data["mine"] + data["open"]) else "")
        lead = ""
        if room:
            lead = (f'<section aria-labelledby="mp-lead-h">{ui.section("For leaders", hid="mp-lead-h")}'
                    f'<ul class="mb-list mb-cards"><li><a href="/my/groups/leaders"><span class="mb-thumb mb-chat-av">{ui.icon("users", 18)}</span>'
                    f'<span class="mb-list-text"><strong>All group leaders</strong><span>Every group leader and your pastors, '
                    f'in one chat</span></span>{ui.icon("chevron", 16)}</a></li></ul></section>')
        if serving:
            lead = (f'<section aria-labelledby="mp-serve-h">{ui.section("Serving", hid="mp-serve-h")}'
                    f'<ul class="mb-list mb-cards"><li><a href="/my/serving"><span class="mb-thumb mb-chat-av">{ui.icon("clock", 18)}</span>'
                    f'<span class="mb-list-text"><strong>My serving</strong><span>Your Sundays, away dates and swaps</span></span>'
                    f'{ui.icon("chevron", 16)}</a></li></ul></section>') + lead
        body = (f'{hint}<section aria-labelledby="mp-mine-h">{ui.section("Your groups", hid="mp-mine-h")}{mine}</section>{lead}'
                f'<section aria-labelledby="mp-open-h">{ui.section("Find a group", hid="mp-open-h")}{open_}</section>')
    return _shell(biz, site, "Connect", f"""
<div class="mb-lt"><h1>Connect</h1></div>
{connect_tabs(biz, "groups") or '<p class="mb-sub">Smaller circles to belong to: small groups, serving teams and classes.</p>'}
{_flash(request)}
{body}""", tab="connect", who=who)


def _flash(request: Request) -> str:
    from member_portal import _e
    done = DONE.get(request.query_params.get("done") or "")
    err = ERRORS.get(request.query_params.get("err") or "")
    if err:
        return f'<p class="mp-err mp-flash" role="alert">{_e(err)}</p>'
    if done:
        return f'<p class="mp-ok mp-flash" role="status">{_e(done)}</p>'
    return ""


def _status_line(o: Dict[str, Any]) -> str:
    from member_portal import _e
    mine = o.get("mine")
    if not mine:
        return ""
    if mine["status"] == "no":
        return '<p class="mp-mine">You said you can\'t make it.</p>'
    if mine["status"] == "maybe":
        return '<p class="mp-mine">You said maybe.</p>'
    if mine.get("role"):
        label = next((r["label"] for r in o.get("roles") or [] if r.get("id") == mine["role"]), "serving")
        return f'<p class="mp-mine">You\'re serving: <strong>{_e(label)}</strong></p>'
    return '<p class="mp-mine">You\'re coming.</p>'


def occasion_card(o: Dict[str, Any], back: str, level: int = 2) -> str:
    """One occasion with the actions that fit this person's answer.
    Nothing offered can only fail: on a full occasion someone not already
    coming is not offered "I'm coming" OR a role (servers count toward the
    headcount). Each button names the occasion for a screen reader."""
    from member_portal import _e
    eid = _e(o.get("entry_id"))
    title_id = f"mp-occ-{eid}"
    facts = [o.get("location") or ""]
    if o.get("capacity") is not None and not o.get("signup"):   # a sign-up's places are its own
        facts.append("Full" if o.get("full") else f"{o.get('spots_left')} places left")
    facts_html = " · ".join(_e(x) for x in facts if x)
    mine = o.get("mine") or {}
    coming = bool(mine) and mine.get("status") == "yes"
    serving_role = mine.get("role") if coming else None
    can_join = coming or not o.get("full")
    hidden = f'<input type="hidden" name="entry_id" value="{eid}"><input type="hidden" name="back" value="{_e(back)}">'
    about = f'aria-describedby="{title_id}"'
    actions = []
    signup = ""
    if o.get("signup"):
        # An event that takes sign-ups (tickets, maybe a price, a waitlist):
        # its sign-up stands where "I'm coming" would. Serving still works.
        import church_event_signups
        signup = church_event_signups.member_block(o, _e)
        coming = True
    if (not coming or serving_role) and can_join and not signup:
        label = "Just attend instead" if serving_role else "I'm coming"
        actions.append(f'<form method="post" action="/my/rsvp">{hidden}<input type="hidden" name="action" value="coming">'
                       f'<button class="{"mp-link" if serving_role else "mp-go mb-soft"}" type="submit" {about}>{label}</button></form>')
    open_roles = [r for r in o.get("roles") or [] if not r.get("full") and r.get("id") != serving_role]
    if open_roles and can_join:
        opts = "".join(f'<option value="{_e(r["id"])}">{_e(r["label"])} — {r["needed"] - r["filled"]} needed</option>'
                       for r in open_roles)
        actions.append(f'<form method="post" action="/my/rsvp" class="mp-serve">{hidden}<input type="hidden" name="action" value="serve">'
                       f'<label class="mp-sr" for="mp-role-{eid}">Role to serve in</label>'
                       f'<select class="mp-input" id="mp-role-{eid}" name="role">{opts}</select>'
                       f'<button class="mp-go mp-go-2" type="submit" {about}>Serve</button></form>')
    if mine.get("status") != "no" and (not signup or serving_role):
        actions.append(f'<form method="post" action="/my/rsvp">{hidden}<input type="hidden" name="action" value="cant">'
                       f'<button class="mp-link" type="submit" {about}>Can\'t make it</button></form>')
    h = "h3" if level == 3 else "h2"
    import member_app_samples as samples
    import member_app_ui as ui
    sample = ui.sample_tag() if samples.is_sample(o) else ""
    return f"""<article class="mp-card mp-occ" aria-labelledby="{title_id}">
  <p class="mp-when">{_e(o.get('date_label') or '')}{sample}</p>
  <{h} id="{title_id}">{_e(o.get('title') or '')}</{h}>
  {f'<p class="mp-muted">{facts_html}</p>' if facts_html else ''}
  {_status_line(o) if not signup or serving_role else ''}
  {signup}
  <div class="mp-actions">{''.join(actions)}</div>
</article>"""


def render_events(biz, site, request: Request, occasions: Optional[List[Dict[str, Any]]],
                  who: Optional[Dict[str, Any]] = None) -> str:
    import member_app_ui as ui
    from member_portal import _shell
    if occasions is None:
        body = '<p class="mp-err" role="alert">What\'s coming up couldn\'t load just now. Please try again in a moment.</p>'
    elif not occasions:
        body = '<p class="mp-muted">Nothing is on the calendar yet. Check back soon.</p>'
    else:
        import member_app_samples as samples
        hint = ui.sample_hint(samples.WHERE["events"]) if any(samples.is_sample(o) for o in occasions) else ""
        body = hint + "".join(occasion_card(o, "/my/events") for o in occasions)
        if any(o.get("signup") for o in occasions):
            import church_event_signups
            body = church_event_signups.MEMBER_CSS + body
    return _shell(biz, site, "Coming up", f"""
<div class="mb-lt"><h1>Coming up</h1></div>
<p class="mb-sub" style="margin-bottom:18px">Let the church know you're coming, or sign up to serve.</p>
{_flash(request)}
{body}""", tab="events", who=who, back=("/my", "Home"))


def render_prayer(biz, site, request: Request, who: Optional[Dict[str, Any]] = None) -> str:
    from member_portal import _e, _shell
    church = _e(biz.get("name") or "the church")
    youth = request.query_params.get("for") == "youth"
    heading = "Talk to a youth leader" if youth else "How can we pray for you?"
    return _shell(biz, site, "Prayer", f"""
<div class="mb-lt"><h1>{heading}</h1></div>
<p class="mb-sub" style="margin-bottom:18px">{'Your request goes privately to the pastors at ' + church + '. It isn’t posted anywhere or shared with other members.' if youth else 'The pastors at ' + church + ' see every request. If you choose, our prayer team prays over it with you too. Nothing is ever posted.'}</p>
{_flash(request)}
<form class="mp-form" method="post" action="/my/prayer">
  {'<input type="hidden" name="for" value="youth">' if youth else ''}
  <label class="mp-sr" for="mp-prayer">Your prayer request</label>
  <textarea class="mp-input mp-text" id="mp-prayer" name="request" rows="7" maxlength="{PRAYER_MAX}" placeholder="Your prayer request" required></textarea>
  {'' if youth else '''<fieldset class="mp-choice" style="border:0;padding:0;margin:10px 0 4px">
    <legend style="font-weight:600;margin-bottom:6px">Who prays with you?</legend>
    <label class="mp-check" style="margin:4px 0"><input type="radio" name="share" value="team" required> Our prayer team may pray over this with you</label>
    <label class="mp-check" style="margin:4px 0"><input type="radio" name="share" value="pastors"> Keep this with the pastors only</label>
  </fieldset>
  <label class="mp-check" style="margin:6px 0 8px"><input type="checkbox" name="wants_call" value="yes"> I’d like someone to call me</label>'''}
  <button class="mp-go" type="submit">Send</button>
</form>""", tab="prayer", who=who, back=("/my", "Home"))


def render_details(biz, site, request: Request, me: Dict[str, Any], directory: str = "") -> str:
    """`directory` is the member directory's part (member_directory.details_block),
    its own form below the details: '' while the church has it off."""
    from member_portal import _e, _shell
    addr = (me.get("metadata") or {}).get("mailing_address") or {}
    if not isinstance(addr, dict):
        addr = {}
    field = lambda k, label, auto: (
        f'<label for="mp-{k}">{label}</label>'
        f'<input class="mp-input" id="mp-{k}" name="{k}" autocomplete="{auto}" maxlength="{FIELD_MAX}" value="{_e(addr.get(k) or "")}">')
    return _shell(biz, site, "My details", f"""
<div class="mb-lt"><h1>My details</h1></div>
<p class="mb-sub" style="margin-bottom:18px">Keep the church's records up to date, so they can reach you by phone or mail.</p>
{_flash(request)}
<form class="mp-form" method="post" action="/my/details">
  <p class="mp-flash" style="margin:0 0 6px">Email: <strong>{_e(me.get('email') or '')}</strong>. It's how you sign in, so to change it, ask the church office.</p>
  <label for="mp-phone">Phone</label>
  <input class="mp-input" id="mp-phone" name="phone" type="tel" autocomplete="tel" maxlength="25" value="{_e(me.get('phone') or '')}">
  {field('line1', 'Street address', 'address-line1')}
  {field('line2', 'Apartment, suite (optional)', 'address-line2')}
  {field('city', 'City', 'address-level2')}
  {field('state', 'State', 'address-level1')}
  {field('postal', 'ZIP code', 'postal-code')}
  <button class="mp-go" type="submit" style="margin-top:8px">Save my details</button>
</form>{directory}""", tab="me", who=me, back=("/my/me", "Me"))


# ─── Home (member app, 2026-09-30) ────────────────────────────────────
# Home answers "what's next, and what's mine this week": the next
# gathering, the latest message (member_portal_sermons), the things this
# person said yes to plus their groups, then what they haven't answered.


def _day(iso: str) -> Optional[date]:
    try:
        return date.fromisoformat(str(iso)[:10])
    except ValueError:
        return None


def _in_days(d: date, today: date) -> str:
    n = (d - today).days
    return "Today" if n <= 0 else ("Tomorrow" if n == 1 else f"in {n} days")


def _my_answer(o: Dict[str, Any]) -> str:
    """'Serving: Greeter' / 'Going' for an occasion they said yes to, else ''."""
    mine = o.get("mine") or {}
    if mine.get("status") != "yes":
        return ""
    role = next((r["label"] for r in o.get("roles") or [] if r.get("id") == mine.get("role")), "")
    return f"Serving: {role}" if role else "Going"


def next_card(occasions: Optional[List[Dict[str, Any]]], today: Optional[date] = None, *,
              pic: str = "", church: str = "", look: str = "church") -> str:
    """Home's lead: the first thing on the calendar, on the church's own
    photo — when, what, where, how many are coming (a number, never names),
    and their answer — or "I'm coming" right there. '' when nothing is
    coming (or the read failed; Coming up says so)."""
    import member_app_ui as ui
    from member_portal import _e
    if not occasions:
        return ""
    o = occasions[0]
    d = _day(o.get("date") or "")
    if not d:
        return ""
    eid = _e(o.get("entry_id"))
    title_id = f"mb-next-{eid}"
    import member_app_samples as samples
    sample = ui.sample_tag() if samples.is_sample(o) else ""
    hint = ui.sample_hint(samples.WHERE["events"]) if sample else ""
    answer = _my_answer(o)
    mine = o.get("mine") or {}
    soon = _in_days(d, today or date.today())
    when = soon[:1].upper() + soon[1:]
    count = int(o.get("attending") or 0)
    if answer and count >= 2:
        going = f"You and {count - 1} other{'' if count == 2 else 's'} are coming"
    elif not answer and count >= 2:
        going = f"{count} people are coming"
    else:
        going = ""
    going = f'<span class="mb-going">{ui.icon("users", 16)}<span>{going}</span></span>' if going else ""
    details = f'<a class="mp-go mp-go-2" href="/my/events" aria-describedby="{title_id}">Details</a>'
    if answer:
        label = "You're coming" if answer == "Going" else answer
        acts = f'<span class="mb-chip">{ui.icon("check", 13)}{_e(label)}</span>{going}'
    elif o.get("signup"):
        su = o["signup"]
        mine_su = su.get("mine") or {}
        if mine_su.get("status") in ("paid", "confirmed"):
            acts = f'<span class="mb-chip">{ui.icon("check", 13)}You\'re signed up</span>{going}'
        else:
            acts = f'<a class="mp-go" href="/my/events" aria-describedby="{title_id}">Sign up</a>'
    elif o.get("full"):
        acts = f'<span class="mb-chip">Full</span>{details}'
    else:
        said_no = '<span class="mb-chip">You said you can\'t make it</span>' if mine.get("status") == "no" else ""
        acts = (f'<form method="post" action="/my/rsvp">'
                f'<input type="hidden" name="entry_id" value="{eid}"><input type="hidden" name="back" value="/my">'
                f'<input type="hidden" name="action" value="coming">'
                f'<button class="mp-go" type="submit" aria-describedby="{title_id}">I\'m coming</button></form>'
                f'{said_no or going or details}')
    where = " · ".join(_e(x) for x in (o.get("date_label") or "", o.get("location") or "") if x)
    art = ui.picture(pic, look, "welcome", eager=True, night=True)
    return (f'<section class="mb-hero" aria-labelledby="{title_id}">{art}<div class="mb-hero-in">'
            f'<span class="mb-when">{_e(when)}</span>{sample}'
            f'<h2 id="{title_id}">{_e(o.get("title"))}</h2>{f"<p>{where}</p>" if where else ""}'
            f'<div class="mb-hero-row">{acts}</div>{hint}</div></section>')


def week_cards(occasions: Optional[List[Dict[str, Any]]],
               groups: Optional[Dict[str, List[Dict[str, Any]]]], *,
               pal: Optional[Dict[str, str]] = None, pool: Optional[List[str]] = None, avoid: str = "",
               used: Optional[set] = None, skip: str = "", biz: Optional[Dict[str, Any]] = None,
               edit: bool = False) -> str:
    """'This week', a row to swipe: what's on the calendar (the date on a
    coral tab; what this person said yes to, or serves at, in teal), then
    their groups and when they meet. Each card wears the picture the church
    put on it (an event by its name, so a weekly one keeps it), a photo
    named for it, or the default picture. No faces or member names — a
    member never sees who else is in a group, only its leaders' first names.
    `skip` is the one Home already leads with. '' when there's nothing.
    `edit`: each card opens its picture instead (member_app_pictures)."""
    import member_app_ui as ui
    import member_app_photos as photos
    from member_portal import _e

    import member_app_samples as samples
    used = used if used is not None else set()
    if avoid:
        used.add(avoid)
    any_sample = False

    def cov(key: str, title: str, item: Dict[str, Any], tab: str, kind: str) -> str:
        nonlocal any_sample
        pic, look = photos.choose(biz or {}, key, pool or [], title=title, used=used)
        art = ui.picture(pic, look, kind)
        tag = ui.sample_tag() if samples.is_sample(item) else ""
        any_sample = any_sample or bool(tag)
        return f'<span class="mb-ev-p">{art}{tab}{tag}{ui.pin("", link=False) if edit else ""}</span>'

    def to(key: str, href: str) -> str:
        return f"/my/pictures/spot?key={quote(key, safe=':')}&amp;back=home" if edit else href
    cards = []
    for o in (occasions or []):
        d = _day(o.get("date") or "")
        if not d or (skip and str(o.get("entry_id")) == skip):
            continue
        answer = _my_answer(o)
        line = (f'<span class="mb-mine">{_e("You\'re coming" if answer == "Going" else answer)}</span>' if answer else
                f'<span>{_e(o.get("location") or o.get("date_label") or "")}</span>')
        tab = f'<span class="mb-datebox" aria-hidden="true"><small>{d.strftime("%a").upper()}</small><b>{d.day}</b></span>'
        ekey = event_key(o.get("title"))
        cards.append(f'<a class="mb-ev" href="{to(ekey, "/my/events")}">{cov(ekey, o.get("title") or "", o, tab, "events")}'
                     f'<span class="mb-ev-b"><strong>{_e(o.get("title"))}</strong>'
                     f'<span class="mp-sr">{_e(o.get("date_label") or "")}</span>{line}</span></a>')
        if len(cards) == 6:
            break
    for g in (groups or {}).get("mine", [])[:3]:
        led = ", ".join(g.get("leaders") or [])
        href = f"/my/groups/live/{_e(g['live']['id'])}" if g.get("live") else f"/my/groups/{_e(g['id'])}"
        tab = ('<span class="mb-datebox" aria-hidden="true" style="width:auto;padding:6px 9px"><small>Group</small></span>')
        line = ('<span class="mb-mine">Meeting now</span>' if g.get("live") else
                '<span class="mb-mine">You lead</span>' if g.get("role") == "leader" else
                f'<span>{_e(g.get("meets") or g.get("location") or "")}</span>')
        led_html = f'<span>Led by {_e(led)}</span>' if led and g.get("role") != "leader" and not g.get("live") else ""
        gkey = "group:" + str(g.get("id"))
        cards.append(f'<a class="mb-ev" href="{to(gkey, href)}">{cov(gkey, g.get("name") or "", g, tab, "groups")}'
                     f'<span class="mb-ev-b"><strong>{_e(g.get("name"))}</strong>{line}{led_html}</span></a>')
    if not cards:
        return ""
    hint = ui.sample_hint(samples.WHERE["week"]) if any_sample else ""
    return (f'<section class="h-coral" aria-labelledby="mb-week">{ui.section("This week", "/my/events", "Calendar", hid="mb-week")}'
            f'{hint}<div class="mb-rail">{"".join(cards)}</div></section>')


def event_key(title: Any) -> str:
    """A calendar event's picture spot, by its name: 'event:sunday-worship',
    so a weekly gathering keeps the picture the church gave it."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(title or "").lower()).strip("-")[:60]
    return f"event:{slug or 'untitled'}"


def coming_up(occasions: Optional[List[Dict[str, Any]]], skip: str = "") -> str:
    """The next two occasions this person hasn't answered, with the same
    actions as the Coming up page. `skip` is the one Home's next card
    already shows; with it, nothing left to answer leaves the section out."""
    if occasions is None:
        body = '<p class="mp-err" role="alert">What\'s coming up couldn\'t load just now.</p>'
    else:
        open_ = [o for o in occasions if not o.get("mine") and not (skip and str(o.get("entry_id")) == skip)]
        if not occasions:
            body = '<p class="mp-muted">Nothing is on the calendar yet.</p>'
        elif not open_ and skip:
            return ""
        elif not open_:
            body = '<p class="mp-muted">You\'ve answered everything on the calendar. <a href="/my/events">See it all</a></p>'
        else:
            body = "".join(occasion_card(o, "/my", level=3) for o in open_[:2])
            if len(occasions) > 2:
                body += f'<p><a class="mp-link" href="/my/events">See all {len(occasions)} coming up</a></p>'
    return f'<section aria-labelledby="mp-coming"><h2 id="mp-coming" class="mp-sect">Coming up</h2>{body}</section>'


# ─── POST ─────────────────────────────────────────────────────────────


async def _signed_in(request: Request):
    """(church, me, unavailable): me is None without a live session;
    unavailable is True when the records could not be read, so the route
    says "try again" instead of dropping the member at sign-in, and
    "preview" in the owner's preview (nothing saves)."""
    import asyncio
    from member_portal import _church_or_404, _session_for
    church = await _church_or_404(request)
    sess = await asyncio.to_thread(_session_for, request, church)
    if sess and sess.get("unavailable"):
        return church, None, True
    if sess and sess.get("preview"):
        # The owner's preview reads; it never writes as the member.
        return church, None, "preview"
    if not sess or not sess.get("me"):
        return church, None, False
    return church, sess["me"], False


def _back(target: str, **q: str) -> RedirectResponse:
    from member_portal import _SECURE_HEADERS
    allowed = ("/my", "/my/me", "/my/events", "/my/prayer", "/my/details", "/my/groups", "/my/classes", "/my/live", "/my/messages",
               "/my/notifications", "/my/directory",
               "/my/kids/stories", "/my/kids/sundays", "/my/kids/family")
    if (target not in allowed and not re.fullmatch(r"/my/(groups/live|messages)/[0-9a-f-]{36}", target)
            and not re.fullmatch(r"/my/groups/([0-9a-fA-F-]{36}(/(board|people|chat|prayer|meet))?|leaders)", target)
            and not re.fullmatch(r"/my/lead/groups/[0-9a-fA-F-]{36}", target)):
        target = "/my"
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    return RedirectResponse(f"{target}?{qs}" if qs else target, status_code=303, headers=_SECURE_HEADERS)


def _allowed(church, me) -> bool:
    import rate_limit
    return rate_limit.allow_strict("member_action", f"{church['business']['id']}|{me['id']}")


@router.post("/my/rsvp", include_in_schema=False)
async def rsvp(request: Request):
    import asyncio
    church, me, unavailable = await _signed_in(request)
    form = await request.form()
    back = str(form.get("back") or "/my")
    if unavailable:
        return _back(back, err="preview" if unavailable == "preview" else "error")
    if not me:
        return _back("/my")
    if not _allowed(church, me):
        return _back(back, err="slow")
    ok, code = await asyncio.to_thread(
        member_rsvp, church["business"]["id"], me, str(form.get("entry_id") or ""),
        str(form.get("action") or ""), str(form.get("role") or ""))
    return _back(back, **({"done": code} if ok else {"err": code}))


@router.post("/my/prayer", include_in_schema=False)
async def prayer(request: Request):
    import asyncio
    church, me, unavailable = await _signed_in(request)
    if unavailable:
        return _back("/my/prayer", err="preview" if unavailable == "preview" else "error")
    if not me:
        return _back("/my")
    form = await request.form()
    text = str(form.get("request") or "").strip()
    if not text:
        return _back("/my/prayer", err="empty")
    if not _allowed(church, me):
        return _back("/my/prayer", err="slow")
    full = await asyncio.to_thread(load_me, church["business"]["id"], me["id"]) or me
    # Shared with the prayer team only when they chose it; an older form
    # (or none chosen) stays with the pastors.
    ok = await asyncio.to_thread(save_prayer, church["business"]["id"], full, text,
                                 str(form.get("share") or "") != "team", str(form.get("for") or "") == "youth",
                                 str(form.get("wants_call") or "") == "yes")
    return _back("/my", done="prayer") if ok else _back("/my/prayer", err="error")


@router.post("/my/details", include_in_schema=False)
async def details(request: Request):
    import asyncio
    church, me, unavailable = await _signed_in(request)
    if unavailable:
        return _back("/my/details", err="preview" if unavailable == "preview" else "error")
    if not me:
        return _back("/my")
    form = await request.form()
    stored = await asyncio.to_thread(load_me, church["business"]["id"], me["id"])
    if not stored:
        return _back("/my/details", err="error")
    cleaned, err = clean_details(dict(form), stored.get("phone") or "")
    if not cleaned:
        return _back("/my/details", err=err)
    if not _allowed(church, me):
        return _back("/my/details", err="slow")
    ok = await asyncio.to_thread(update_details, church["business"]["id"], me["id"], cleaned)
    resp = _back("/my/details", **({"done": "details"} if ok else {"err": "error"}))
    # Signed in by mobile number and changed it: the session follows the
    # new number, or the save would sign them out mid-page.
    if ok:
        import member_portal as mp
        biz = church["business"]
        claims = mp.read_session(request.cookies.get(mp.SESSION_COOKIE) or "", biz["id"], epoch=mp._epoch(biz))
        if claims and mp.is_phone(claims["em"]):
            new = mp.norm_ident(cleaned["phone"]) if cleaned["phone"] else ""
            if new and new != claims["em"]:
                mp._set_session(resp, mp.mint_session(biz["id"], new, str(me["id"])))
    return resp


def save_group_interest(business_id: str, me: Dict[str, Any]) -> bool:
    """A member at a church with no groups yet says they'd like to join
    one. It lands in Prayer & care (ministry_care_requests), the inbox the
    office already works from, once per person while it's still new."""
    have = sb_clients.sb_get_as_service(
        f"/ministry_care_requests?business_id=eq.{quote(str(business_id), safe='')}"
        f"&contact_id=eq.{quote(str(me['id']), safe='')}&status=eq.new"
        f"&submission->>kind=eq.group_interest&select=id&limit=1")
    if isinstance(have, list) and have:
        return True
    rows = sb_clients.sb_post_as_service("/ministry_care_requests", {
        "business_id": str(business_id), "form_id": None, "contact_id": str(me["id"]), "status": "new",
        "submission": {
            "name": (me.get("name") or "").strip(), "email": me.get("email") or "", "phone": me.get("phone") or "",
            "prayer_request": "I'd like to join a group. Please let me know when one starts.",
            "confidential": "no", "source": "Member page", "kind": "group_interest",
        },
    })
    return isinstance(rows, list) and bool(rows)


@router.post("/my/groups/interest", include_in_schema=False)
async def group_interest(request: Request):
    import asyncio
    church, me, unavailable = await _signed_in(request)
    if unavailable:
        return _back("/my/groups", err="preview" if unavailable == "preview" else "error")
    if not me:
        return _back("/my")
    if not _allowed(church, me):
        return _back("/my/groups", err="slow")
    full = await asyncio.to_thread(load_me, church["business"]["id"], me["id"]) or me
    ok = await asyncio.to_thread(save_group_interest, church["business"]["id"], full)
    return _back("/my/groups", **({"done": "group_interest"} if ok else {"err": "error"}))


@router.post("/my/groups", include_in_schema=False)
async def groups(request: Request):
    import asyncio
    church, me, unavailable = await _signed_in(request)
    if unavailable:
        return _back("/my/groups", err="preview" if unavailable == "preview" else "error")
    if not me:
        return _back("/my")
    form = await request.form()
    group_id = str(form.get("group_id") or "")
    action = str(form.get("action") or "")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", group_id) or action not in ("join", "leave"):
        return _back("/my/groups", err="group_gone")
    if not _allowed(church, me):
        return _back("/my/groups", err="slow")
    if action == "join":
        # Joining goes the group's way: in right away, or asked
        # (member_portal_groups.ask), and lands on the group's page.
        import member_portal_groups as mpg
        ok, code = await asyncio.to_thread(mpg.ask, church["business"], me, group_id)
        if ok:
            return mpg._go(f"/my/groups/{group_id}", done=code)
        return _back("/my/groups", err=code)
    ok, code = await asyncio.to_thread(member_leave, church["business"]["id"], me, group_id)
    return _back("/my/groups", **({"done": code} if ok else {"err": code}))


def connect_tabs(biz, current: str) -> str:
    """Connect's pages under one title: Groups; Classes when the church has
    a published class (member_portal_classes.TAB, set for this request);
    Messages when the church has messaging on; Directory when the church has
    its member directory on, in Church (never in Youth or Kids). '' when
    Groups is alone."""
    import member_app_ui as ui
    import member_directory
    import member_portal_classes as mcl
    import member_portal_messaging as mpm
    import member_spaces as msp
    tabs = [("groups", "/my/groups", "Groups")]
    if mcl.TAB.get():
        tabs.append(("classes", "/my/classes", "Classes"))
    if mpm.turned_on(biz):
        tabs.append(("messages", "/my/messages", "Messages"))
    ctx = msp.CURRENT.get() or {}
    if member_directory.church_on(biz) and ctx.get("space", "church") == "church" and not ctx.get("youth"):
        tabs.append(("directory", "/my/directory", "Directory"))
    if len(tabs) == 1:
        return ""
    return ui.segmented(tuple(tabs), current, "Connect")


def live_hero(live: Dict[str, Any], pic: str, church: str, look: str = "church") -> str:
    """While the church is live: the one thing Home leads with."""
    import member_app_ui as ui
    from member_portal import _e
    art = ui.picture(pic, look, "worship", eager=True, night=True)
    return (f'<a class="mb-hero" href="/my/live" aria-label="Live now: {_e(live.get("title"))}">{art}<span class="mb-hero-in">'
            f'<span class="mb-when is-live"><span class="mb-live-dot" aria-hidden="true"></span>Live now</span>'
            f'<h2>{_e(live.get("title"))}</h2><p>Watch and chat with your church</p>'
            f'<span class="mb-hero-row"><span class="mp-go">Watch now</span></span></span></a>')


def church_hero(pic: str, church: str, look: str = "church") -> str:
    """Home's lead when nothing is on the calendar: the church itself."""
    import member_app_ui as ui
    from member_portal import _e
    art = ui.picture(pic, look, "welcome", eager=True, night=True)
    return (f'<section class="mb-hero" aria-label="{_e(church)}">{art}<div class="mb-hero-in">'
            f'<span class="mb-when">Welcome home</span><h2>{_e(church)}</h2>'
            f'<p>Messages, prayer and your church family, all week.</p>'
            f'<div class="mb-hero-row"><a class="mp-go" href="/my/sermons">Watch a message</a>'
            f'<a class="mp-go mp-go-2" href="/my/bible">Read</a></div></div></section>')


TILE_MAX = 6


def clean_tiles(raw: Any) -> Optional[List[Dict[str, str]]]:
    """The church's own Home tiles (settings.member_portal.tiles), as the
    owner saves them: [{title, sub, href, photo}]. None when the list is
    not one. A tile needs a title (≤40) and a link that is a page of the
    church's own address ("/…") or https; its photo is https or one of
    the site's own assets. Bad entries are dropped; the first six good
    ones are kept."""
    if not isinstance(raw, list):
        return None
    out: List[Dict[str, str]] = []
    for t in raw[:50]:
        if len(out) == TILE_MAX:
            break
        if not isinstance(t, dict):
            continue
        title = re.sub(r"\s+", " ", str(t.get("title") or "")).strip()[:40]
        sub = re.sub(r"\s+", " ", str(t.get("sub") or "")).strip()[:60]
        href = str(t.get("href") or "").strip()
        photo = str(t.get("photo") or "").strip()
        if not title or len(href) > 500:
            continue
        if not (re.fullmatch(r"/(?!/)[^\s<>\"']*", href) or re.fullmatch(r"https://[^\s<>\"']+", href)):
            continue
        if photo and not (re.fullmatch(r"https://[^\s<>\"']{1,500}", photo)
                          or re.fullmatch(r"/public/site-assets/[\w.-]+/[\w.-]+", photo)):
            photo = ""
        import member_app_photos as photos
        import member_app_ui as ui
        look = t.get("look") if t.get("look") in photos.LOOKS else "colour"
        kind = t.get("kind") if t.get("kind") in ui.DEFAULT_KINDS else ""
        out.append({"title": title, "sub": sub, "href": href, "photo": photo, "look": look, "kind": kind})
    return out


def tile_kind(href: str) -> str:
    """Which default picture a tile wears, by where it goes."""
    for start, kind in (("/my/groups", "groups"), ("/my/events", "events"), ("/my/prayer", "prayer"),
                        ("/my/sermons", "messages"), ("/my/live", "worship"), ("/watch", "worship"),
                        ("/my/give", "giving"), ("/give", "giving"), ("/my/bible", "word"), ("/my/reading", "word"),
                        ("/my/classes", "classes"), ("/my/kids", "kids"), ("/my/youth", "youth")):
        if href == start or href.startswith(start + "/") or href.startswith(start + "?"):
            return kind
    return "welcome"


def tile_key(title: str) -> str:
    """A Home tile's picture spot, by its title."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(title or "").lower()).strip("-")[:60]
    return f"tile:{slug or 'untitled'}"


# Photo names that suit the default tiles.
_TILE_WORDS = {"/my/groups": ("team", "serv", "volunteer", "fellowship", "group"),
               "/my/events": ("community", "family", "day", "event"),
               "/my/prayer": ("pray",),
               "/": ("service", "worship", "stage", "sanctuary")}


def _short_name(name: str) -> str:
    """'Love City Church' → 'Love City'; a name that is only 'Church' stays."""
    n = (name or "").strip()
    short = re.sub(r"\s+(Church|Ministries|Ministry)$", "", n, flags=re.I)
    return short or n or "your church"


def home_tiles(biz: Dict[str, Any], site, pool: Optional[List[str]] = None, used: Optional[set] = None,
               edit: bool = False) -> str:
    """"At Love City": the church's own tiles on one grid (a wide one, two
    squares, a band, then squares) — what its Subsplash Home held. Without
    any saved, the ways in every church has: groups, the calendar, prayer
    and its website. `edit`: each tile opens its picture instead
    (member_app_pictures)."""
    import member_app_ui as ui
    import member_app_photos as photos
    from member_portal import _e, portal_settings
    saved = clean_tiles(portal_settings(biz.get("settings")).get("tiles")) or []
    tiles = saved or [
        {"title": "Ministries", "sub": "Find your place", "href": "/my/groups", "photo": ""},
        {"title": "Church calendar", "sub": "Every date, one place", "href": "/my/events", "photo": ""},
        {"title": "Prayer", "sub": "Private to the pastors", "href": "/my/prayer", "photo": ""},
        {"title": f"{_short_name(biz.get('name') or '')} online", "sub": "Our website: visit, beliefs and more",
         "href": "/", "photo": ""},
    ]
    shapes = ["is-wide", "is-sq", "is-sq", "is-band", "is-sq", "is-sq"]
    if len(tiles) == 2:
        shapes = ["is-sq", "is-sq"]
    elif len(tiles) == 1:
        shapes = ["is-wide"]
    used = used if used is not None else set()
    out = []
    for t, shape in zip(tiles, shapes):
        key = tile_key(t["title"])
        got = photos.assigned(biz, key)
        if got is not None:
            pic, look = got["url"], got["look"]
        elif t.get("photo"):
            pic, look = t["photo"], t.get("look") or "colour"
        else:
            pic, look = photos.choose(biz, key, pool or [], title=t["title"],
                                      words=_TILE_WORDS.get(t["href"], ()), used=used)
        if pic:
            used.add(pic)
        art = ui.picture(pic, look, t.get("kind") or tile_kind(t["href"]))
        outside = t["href"].startswith("https://") and not edit
        attrs = ' target="_blank" rel="noopener"' if outside else ""
        href = f"/my/pictures/spot?key={quote(key, safe=':')}&amp;back=home" if edit else _e(t["href"])
        art += ui.pin("", link=False) if edit else ""
        out.append(f'<a class="mb-bt {shape}{"" if pic else " is-def"}" href="{href}"{attrs}>{art}<span class="mb-bt-t">'
                   f'<strong>{_e(t["title"])}{ui.icon("out", 15) if outside else ""}</strong>'
                   f'{f"<span>{_e(t["sub"])}</span>" if t["sub"] else ""}</span></a>')
    return (f'<section aria-labelledby="mb-at">{ui.section("At " + _short_name(biz.get("name") or ""), hid="mb-at")}'
            f'<div class="mb-bento">{"".join(out)}</div></section>')
