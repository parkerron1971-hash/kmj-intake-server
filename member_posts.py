"""
member_posts.py — members post, the way Kevin approved (Look 5.1).

Kevin, approving Look 5.1 (2026-11-20), on who posts: leaders post anytime
(today's News, member_portal_write and church_news.can_post); members post
freely inside their own groups; a post to the whole church goes through a
pastor, who approves it first (today's Share good news, news_share); every
member post is checked like a comment (msg_screen: shown, held for a safety
officer, or care with 988); each church can turn member posting off.

  GET  /my/post[?group=<id>&type=praise|prayer|photo]   the composer (the new look only)
  POST /my/post                 a member's post
  POST /my/post/remove          {id}: its writer, or a leader of its group
  POST /my/post/switch          {on}: the church owner (their preview), members posting on or off

WHAT A MEMBER CAN POST, AND WHERE IT GOES
  * Praise or Photo, to one of their groups: a church_posts row for that
    group (group_id; source 'member'), so only the group's people see it
    (church_news.reaches), on the group's page and in their Home and News.
    Text up to TEXT_MAX, up to PHOTOS_MAX photos (checked like News photos,
    for a church audience that includes teens: member_portal_write._photos).
    The writer picks comments on, prayers only or off (COMMENT_MODES). It
    never rings phones (alerted_at is set when it's saved): a member's post
    isn't the church's news.
  * Prayer request, to one of their groups: the group's own prayer wall
    (group_prayer.ask: its own check, crisis words to a pastor first).
  * To the whole church: Praise or Photo is good news a pastor posts
    (news_share.share, the existing queue: one photo, what happened);
    Prayer request goes to the pastors and the prayer and care desk
    (member_portal_church.save_prayer, as /my/prayer does).

THE CHECK. The words are checked first (msg_screen). 'ok' shows. 'harm' is
held: the post is saved as waiting (status 'waiting', attach.held 'harm'),
the writer sees it on the group's page marked as held, nobody else does, and
the church's safety officers find it with the held comments (church_news
held list: Let it through or Keep it hidden). 'self_harm' is held the same
way, the pastor is told (Prayer & care, member_portal_messaging.care_alert)
and the writer is shown 988. If the check can't run, nothing is posted.

WHO MAY POST IN A GROUP. Someone in the group, at a church that has member
posting on (settings.member_portal.member_posts, on unless the church turns
it off) and has its two safety officers (as comments and group chat need:
messaging_router.MIN_OFFICERS). Teens follow messaging's rules
(member_messaging_rules): we have to know their age, a teen needs the
church's messaging switch on for them, a group with a teen in it needs two
approved adult leaders, and nobody shares a photo into a group with a teen
in it (as chat photos).

THEIR BIRTHDAY, ASKED ONCE (Kevin, 2026-11-20: "yes ask for the birthday
when they tap post"). Posting's age is the office's birthdate
(contacts.birthdate) when it has one, else the birthday the member gave the
first time they posted in a group: contacts.metadata.member_birthdate on
their own record (posting_birthdate). The composer asks for it, above Post,
only while they have neither and a group is picked; Post saves it and the
post in one submit (save_birthdate: their own record, guarded by updated_at,
never changed from the app once given; the office's birthdate wins). A real
date, not in the future, under 110; under 13 isn't kept and doesn't post
(kids come in through a parent: member_spaces.is_child). It counts for
posting only. Messaging, and messaging's approved adult leaders, read
contacts.birthdate alone (member_messaging_rules is unchanged): a birthday
a member typed never opens messaging, and never makes anyone one of a
group's two adults. A typed birthday that says someone is a teen does make
them a teen here (it only ever narrows what a group allows).

TAKING ONE DOWN. Its writer, or a leader of its group (here); the office
(church_news' remove, any post).

The owner's preview reads; the composer saves nothing there, but the owner
can turn member posting on or off from it (the posting switch, like the
picture spots and the pastor's note).
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

import sb_clients

logger = logging.getLogger("member_posts")
router = APIRouter(tags=["member-portal"])

SWITCH = "member_posts"
TEXT_MAX = 2000
PHOTOS_MAX = 4
TYPES = (("praise", "Praise"), ("prayer", "Prayer request"), ("photo", "Photo"))
TYPE_KEYS = tuple(k for k, _ in TYPES)
HINT = {"praise": "What is God doing? Tell them…", "prayer": "What can we pray about?",
        "photo": "Say something about it…"}
UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
# The birthday a member gives once, for posting (contacts.metadata; the
# session's record reads it as `bday`: member_portal.contacts_for_email).
BDAY_KEY = "member_birthdate"
BDAY_MAX_AGE = 110
ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

DONE = {
    "posted": "It's up. Your group can see it now.",
    "post_held": "Thanks. A safety officer looks at this one before it shows.",
    "care": ("You're not alone. If you're thinking about hurting yourself, call or text 988 (the Suicide & Crisis "
             "Lifeline) any time. Your pastor has been told so they can reach out."),
    "prayer_up": "It's on your group's prayer wall.",
    "prayer_pastor_first": "A pastor reads this one first. Your group sees that a pastor has it.",
    "shared": "Sent. Your pastors read it first, then it goes up for the church.",
    "prayer_sent": "Your pastors have it.",
    "removed": "Taken down.",
    "switch_on": "Members can post in their groups.",
    "switch_off": "Member posting is off. Leaders still post, and members can still share good news.",
}
ERRORS = {
    "post_off": "Posting by members is off at your church right now.",
    "post_officers": "Posting opens once your church has its two safety officers.",
    "post_where": "Choose one of your groups, or the whole church.",
    "post_not_member": "You can post only in groups you're in.",
    "post_empty": "Write something first.",
    "post_long": f"That's a little long. Keep it under {TEXT_MAX} letters.",
    "post_photo": "Add a photo first.",
    "post_photos": f"Add up to {PHOTOS_MAX} photos at a time.",
    "post_teen_photos": "Photos can't be shared in a group with teens in it.",
    "post_birthday": "Add your birthday to post in a group. We ask once.",
    "post_birthday_bad": "That date doesn't look right. Check your birthday and try again.",
    "post_child": "Members under 13 can't post in groups. Please ask a parent or the church office.",
    "post_teen_off": "Your church hasn't turned messaging on for you yet, so you can't post in groups.",
    "post_two_adults": "This group needs two adult leaders before people can post in it.",
    "post_busy": "We couldn't check your words just now, so nothing was posted. Please try again.",
    "post_kind": "Choose what happened first.",
    "post_gone": "That post isn't there any more, or it isn't yours to take down.",
    "prayer_no": "That can't go on the wall. If you need help, talk to a pastor.",
    "photo_bad": "One of those files isn't a photo we can use. Choose JPG, PNG or WebP photos under 12 MB.",
    "photo_no": "One of those photos can't be posted here. Nothing was posted. Take it out and try again.",
    "photo_busy": "We couldn't check the photos just now, so nothing was posted. Please try again.",
    "share_many": "You have three waiting with your pastors already. They'll get to them soon.",
    "preview": "This is a preview, so nothing is saved.",
    "slow": "That was quick. Wait a moment and try again.",
    "error": "Something went wrong, so nothing was posted. Please try again.",
}


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _e(v: Any) -> str:
    from html import escape
    return escape(str(v if v is not None else ""), quote=True)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─── who may post ────────────────────────────────────────────────────


def on(biz: Dict[str, Any]) -> bool:
    """The church's switch: on unless the church turned member posting off
    (settings.member_portal.member_posts = false), as comments are."""
    cfg = ((biz or {}).get("settings") or {}).get("member_portal") or {}
    return not (isinstance(cfg, dict) and cfg.get(SWITCH) is False)


def closed(biz: Dict[str, Any]) -> str:
    """'' when members may post in their groups here; else why not ('off',
    'officers'). The officers' count is a read (messaging_router)."""
    if not on(biz):
        return "off"
    import messaging_router as mr
    try:
        return "" if mr.officer_count(str(biz["id"])) >= mr.MIN_OFFICERS else "officers"
    except Exception:  # noqa: BLE001 — a failed read never opens posting
        return "officers"


def groups_of(business_id: str, me_id: str) -> Optional[List[Dict[str, Any]]]:
    """The running groups this member is in: [{id, name}], by name. None
    on a failed read."""
    mine = sb_clients.sb_get_as_service(
        f"/group_members?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(me_id)}&select=group_id,role&limit=500")
    if mine is None:
        return None
    ids = sorted({str(r["group_id"]) for r in mine})
    if not ids:
        return []
    rows = sb_clients.sb_get_as_service(
        f"/groups?business_id=eq.{_q(business_id)}&id=in.({','.join(_q(i) for i in ids)})&active=eq.true"
        f"&select=id,name&order=name.asc")
    if rows is None:
        return None
    role = {str(r["group_id"]): r.get("role") for r in mine}
    return sorted(({"id": str(g["id"]), "name": g.get("name") or "Your group", "role": role.get(str(g["id"]))}
                   for g in rows), key=lambda g: g["name"].lower())


def given_birthdate(person: Optional[Dict[str, Any]]) -> Optional[str]:
    """The birthday a member gave when they first posted in a group
    (contacts.metadata.member_birthdate; the session's record carries it as
    `bday`), when it's a usable one; else None."""
    import member_messaging_rules as mr_rules
    person = person or {}
    v = person.get("bday")
    if v is None and isinstance(person.get("metadata"), dict):
        v = person["metadata"].get(BDAY_KEY)
    if not isinstance(v, str) or not ISO_DAY.match(v):
        return None
    a = mr_rules.age(v)
    return v if a is not None and a < BDAY_MAX_AGE else None


def posting_birthdate(person: Optional[Dict[str, Any]]) -> Any:
    """Posting's birthdate: the office's (contacts.birthdate) when it has
    one, else the one the member gave. For posting only: messaging
    (member_messaging_rules) reads contacts.birthdate alone."""
    import member_messaging_rules as mr_rules
    office = (person or {}).get("birthdate")
    if mr_rules.age(office) is not None:
        return office
    return given_birthdate(person)


def _as_posting(person: Dict[str, Any]) -> Dict[str, Any]:
    """A group's person as posting's teen rules see them: the office's
    birthdate; with none, the birthday they gave only when it says they're a
    teen. So a typed birthday can make someone a teen here (a narrower group)
    but never one of a group's approved adults (can_message needs the
    office's birthdate)."""
    import member_messaging_rules as mr_rules
    if mr_rules.age(person.get("birthdate")) is not None:
        return person
    given = given_birthdate(person)
    return {**person, "birthdate": given if given and mr_rules.is_teen({"birthdate": given}) else None}


def check_birthdate(raw: Any) -> Tuple[str, str]:
    """(yyyy-mm-dd, '') for a birthday a member typed that posting keeps;
    else ('', why): post_birthday (none given), post_birthday_bad (not a real
    date, in the future, or 110 or more years ago), post_child (under 13:
    kids come in through a parent, member_spaces.is_child, and nothing is
    kept)."""
    import member_messaging_rules as mr_rules
    import member_spaces as msp
    s = str(raw or "").strip()
    if not s:
        return "", "post_birthday"
    if not ISO_DAY.match(s):
        return "", "post_birthday_bad"
    try:
        d = date.fromisoformat(s)
    except ValueError:
        return "", "post_birthday_bad"
    a = mr_rules.age(d)
    if a is None or a >= BDAY_MAX_AGE:
        return "", "post_birthday_bad"
    if msp.is_child({"birthdate": d}):
        return "", "post_child"
    return d.isoformat(), ""


def save_birthdate(business_id: str, contact_id: str, iso: str) -> Optional[str]:
    """The birthday a member typed, on their own record only
    (contacts.metadata.member_birthdate), guarded by updated_at so an office
    edit at the same moment isn't lost (as member_feed_more.toggle_saved).
    'saved'; 'kept' when the record already has one (the office's
    birthdate, or one they gave before: never changed from the app); None
    when it couldn't save."""
    for _ in range(3):
        rows = sb_clients.sb_get_as_service(
            f"/contacts?id=eq.{_q(contact_id)}&business_id=eq.{_q(business_id)}"
            f"&select=id,birthdate,metadata,updated_at&limit=1")
        if not isinstance(rows, list) or not rows:
            return None
        rec = rows[0]
        meta = dict(rec.get("metadata") or {}) if isinstance(rec.get("metadata"), dict) else {}
        if posting_birthdate({"birthdate": rec.get("birthdate"), "metadata": meta}) is not None:
            return "kept"
        meta[BDAY_KEY] = iso
        guard = f"eq.{_q(rec['updated_at'])}" if rec.get("updated_at") else "is.null"
        got = sb_clients.sb_patch_as_service(
            f"/contacts?id=eq.{_q(contact_id)}&business_id=eq.{_q(business_id)}&updated_at={guard}",
            {"metadata": meta})
        if isinstance(got, list) and got:
            return "saved"
    return None


def rules(biz: Dict[str, Any], me: Dict[str, Any], group_id: str) -> Tuple[str, Dict[str, Any]]:
    """('', {group, teens}) when this member may post in this group; else an
    error code. Reads the group, its people, and (for teens and the leaders
    of a group with teens) messaging's switches. The member's age is
    posting's (posting_birthdate); everyone else's as _as_posting sees it."""
    import member_messaging_rules as mr_rules
    import member_portal_groups as mpg
    import member_portal_messaging as mpm
    biz_id = str(biz["id"])
    why = closed(biz)
    if why:
        return f"post_{why}", {}
    g = mpg.group_row(biz_id, group_id)
    if g is None:
        return "error", {}
    if not g:
        return "post_not_member", {}
    people = mpg.roster(biz_id, group_id)
    if people is None:
        return "error", {}
    mine = next((p for p in people if p["id"] == str(me["id"])), None)
    if not mine:
        return "post_not_member", {}
    mine_born = posting_birthdate(mine)
    if mr_rules.age(mine_born) is None:
        return "post_birthday", {}
    people = [_as_posting(p) for p in people]
    teens = any(mr_rules.is_teen(p) for p in people)
    if mr_rules.is_teen({"birthdate": mine_born}):
        full = mpm._me_profile(biz_id, me)
        if full is None:
            return "error", {}
        if not mr_rules.can_message(full):
            return "post_teen_off", {}
    if teens:
        leaders = [p["id"] for p in people if p.get("role") == "leader"]
        folks = mpm.people(biz_id, leaders) if leaders else {}
        if folks is None:
            return "error", {}
        members = [{**p, "enabled": (folks.get(p["id"]) or {}).get("enabled", False)} for p in people]
        ok, _why = mr_rules.group_chat(members)
        if not ok:
            return "post_two_adults", {}
    return "", {"group": g, "teens": teens, "leader": mine.get("role") == "leader"}


# ─── posting ─────────────────────────────────────────────────────────


def clean(text: Any) -> str:
    return re.sub(r"[ \t]+\n", "\n", str(text or "")).strip()


async def to_group(biz: Dict[str, Any], me: Dict[str, Any], group_id: str, kind: str, text: str,
                   files: List[bytes], comments: str = "on") -> Tuple[bool, str, str]:
    """A member's Praise, Photo or Prayer request in one of their groups.
    (ok, code, post id or ''). Codes: posted, post_held, care, prayer_up,
    prayer_pastor_first, and ERRORS' keys."""
    import church_news as cn
    import msg_screen
    biz_id, me_id = str(biz["id"]), str(me["id"])
    if kind not in TYPE_KEYS:
        kind = "praise"
    if not UUID.match(str(group_id or "")):
        return False, "post_where", ""
    text = clean(text)
    if len(text) > TEXT_MAX:
        return False, "post_long", ""
    if kind == "photo" and not files:
        return False, "post_photo", ""
    if not text and not files:
        return False, "post_empty", ""
    if len(files) > PHOTOS_MAX:
        return False, "post_photos", ""
    why, ctx = await asyncio.to_thread(rules, biz, me, group_id)
    if why:
        return False, why, ""
    if kind == "prayer":
        import group_prayer
        ok, code = await group_prayer.ask(biz, me, ctx["group"], text, False)
        return ok, code, ""
    if files and ctx["teens"]:
        return False, "post_teen_photos", ""
    verdict = "ok"
    if text:
        try:
            verdict = await msg_screen.screen(biz_id, text)
        except msg_screen.ScreenUnavailable:
            return False, "post_busy", ""
    att: Dict[str, Any] = {"member": kind}
    if files:
        import member_portal_write as mpw
        pics, code = await mpw._photos(biz_id, files)
        if pics is None:
            return False, code, ""
        att["pics"] = pics
    held = verdict in ("harm", "self_harm")
    if held:
        att["held"] = "care" if verdict == "self_harm" else "harm"
    comments = comments if comments in cn.COMMENT_MODES else "on"
    row = await asyncio.to_thread(cn.insert, biz_id, {
        "kind": "photos" if kind == "photo" else "praise", "title": "", "body": text[:cn.BODY_MAX],
        "group_id": str(ctx["group"]["id"]), "posted_by": me_id, "source": "member",
        "status": "waiting" if held else "posted", "comments": comments, "attach": att,
        # A member's post never rings phones (news_alerts reads this as done).
        "alerted_at": _now().isoformat()})
    if not row:
        import chat_photos
        for p in att.get("pics") or []:
            await asyncio.to_thread(chat_photos.drop, p["path"])
        return False, "error", ""
    if verdict == "self_harm":
        import member_portal_messaging as mpm
        try:
            await asyncio.to_thread(mpm.care_alert, biz_id, me)
        except Exception:  # noqa: BLE001 — the post is saved and held; the alert is best effort, and logged
            logger.warning("member post care alert failed", exc_info=True)
        return True, "care", str(row["id"])
    return True, ("post_held" if held else "posted"), str(row["id"])


# The whole church's good-news kinds (news_share.KINDS), for Praise and Photo.
async def to_church(biz: Dict[str, Any], me: Dict[str, Any], kind: str, text: str, share_kind: str,
                    photo: Optional[bytes]) -> Tuple[bool, str]:
    """To the whole church, through a pastor. (ok, code): Praise and Photo
    wait as good news for the owner or an admin to post (news_share);
    a Prayer request goes to the pastors (member_portal_church.save_prayer)."""
    import member_portal_church as mpc
    import news_share as ns
    biz_id = str(biz["id"])
    text = clean(text)
    if kind == "prayer":
        if not text:
            return False, "post_empty"
        full = await asyncio.to_thread(mpc.load_me, biz_id, me["id"]) or me
        ok = await asyncio.to_thread(mpc.save_prayer, biz_id, full, text, True, False, False, "Member app post")
        return (True, "prayer_sent") if ok else (False, "error")
    if kind == "photo" and not photo:
        return False, "post_photo"
    if share_kind not in ns.KIND_KEYS:
        return False, "post_kind"
    ok, code, _pid = await ns.share(biz, me, share_kind, text, "all", photo)
    if not ok:
        return False, {"share_empty": "post_empty", "share_long": "post_long", "share_kind": "post_kind"}.get(code, code)
    return True, code


def _post(business_id: str, post_id: str) -> Optional[Dict[str, Any]]:
    if not UUID.match(str(post_id or "")):
        return {}
    rows = sb_clients.sb_get_as_service(
        f"/church_posts?id=eq.{_q(post_id)}&business_id=eq.{_q(business_id)}&source=eq.member&group_id=not.is.null"
        f"&removed_at=is.null&select=id,group_id,posted_by,status,attach&limit=1")
    if rows is None:
        return None
    return rows[0] if rows else {}


def remove(business_id: str, me: Dict[str, Any], post_id: str) -> Tuple[bool, str, str]:
    """A member's group post taken down by its writer or a leader of its
    group. (ok, code, group id)."""
    import chat_photos
    import member_portal_groups as mpg
    p = _post(business_id, post_id)
    if p is None:
        return False, "error", ""
    if not p:
        return False, "post_gone", ""
    gid = str(p["group_id"])
    if str(p.get("posted_by") or "") != str(me["id"]):
        lead = mpg._is_leader(business_id, gid, str(me["id"]))
        if lead is None:
            return False, "error", gid
        if not lead:
            return False, "post_gone", gid
    done = sb_clients.sb_patch_as_service(
        f"/church_posts?id=eq.{_q(p['id'])}&business_id=eq.{_q(business_id)}&removed_at=is.null",
        {"status": "removed", "removed_at": _now().isoformat(), "pinned_until": None})
    if done is None:
        return False, "error", gid
    for pic in ((p.get("attach") or {}).get("pics") or []):
        path = str((pic or {}).get("path") or "")
        if path.startswith(f"{business_id}/news-photos/"):
            chat_photos.drop(path)
    return True, "removed", gid


# ─── reading: a group's posts, the held ones ─────────────────────────


GROUP_READ = 20


def group_feed(business_id: str, group_id: str, me_id: str) -> Optional[List[Dict[str, Any]]]:
    """The posts for one group (a leader's News for the group, and its
    members' posts), newest first, as Home's feed draws them (church_news
    ._decorate): the live ones, and this member's own held ones (marked
    "held"). None when a read failed."""
    import church_news as cn
    rows = sb_clients.sb_get_as_service(
        f"/church_posts?business_id=eq.{_q(business_id)}&group_id=eq.{_q(group_id)}&status=in.(posted,waiting)"
        f"&removed_at=is.null&select={cn.POST_SELECT}&order=created_at.desc&limit={GROUP_READ}")
    if rows is None:
        return None
    now = _now()
    out = []
    for r in rows:
        mine = str(r.get("posted_by") or "") == str(me_id)
        att = r.get("attach") if isinstance(r.get("attach"), dict) else {}
        if cn.is_live(r, now):
            out.append(r)
        elif mine and r.get("status") == "waiting" and r.get("source") == "member" and att.get("held"):
            out.append({**r, "held": True})
    out.sort(key=cn.when_of, reverse=True)
    if not out:
        return []
    done = cn._decorate(business_id, out, me_id, previews=True, batch=True)
    return done


def held_posts(business_id: str) -> List[Dict[str, Any]]:
    """Members' group posts the check held, newest first, for the safety
    officers' list beside the held comments: {id, post_id, post_title,
    body, contact_id, created_at, kind: 'post'}."""
    rows = sb_clients.sb_get_as_service(
        f"/church_posts?business_id=eq.{_q(business_id)}&source=eq.member&status=eq.waiting&group_id=not.is.null"
        f"&removed_at=is.null&select=id,group_id,posted_by,body,attach,created_at&order=created_at.desc&limit=50")
    if not isinstance(rows, list):
        return []
    rows = [r for r in rows if isinstance(r.get("attach"), dict) and r["attach"].get("held")]
    gids = sorted({str(r["group_id"]) for r in rows})
    names: Dict[str, str] = {}
    if gids:
        got = sb_clients.sb_get_as_service(
            f"/groups?business_id=eq.{_q(business_id)}&id=in.({','.join(_q(g) for g in gids)})&select=id,name")
        names = {str(g["id"]): g.get("name") or "" for g in (got or [])}
    return [{"id": str(r["id"]), "post_id": str(r["id"]),
             "post_title": f"their own post in {names.get(str(r['group_id'])) or 'a group'}",
             "body": r.get("body") or "", "contact_id": r.get("posted_by"), "created_at": r.get("created_at"),
             "kind": "post"} for r in rows]


def decide_held(business_id: str, post_id: str, show: bool) -> Optional[bool]:
    """A safety officer's answer on a held post: Let it through (posted) or
    Keep it hidden (taken down). True done, False no such held post, None on
    a failed write."""
    if not UUID.match(str(post_id or "")):
        return False
    rows = sb_clients.sb_get_as_service(
        f"/church_posts?id=eq.{_q(post_id)}&business_id=eq.{_q(business_id)}&source=eq.member&status=eq.waiting"
        f"&group_id=not.is.null&removed_at=is.null&select=id,attach&limit=1")
    if rows is None:
        return None
    if not rows or not (rows[0].get("attach") or {}).get("held"):
        return False
    att = dict(rows[0].get("attach") or {})
    att["held_decided"] = "shown" if show else "hidden"
    patch = ({"status": "posted", "attach": att} if show else
             {"status": "removed", "removed_at": _now().isoformat(), "attach": att})
    done = sb_clients.sb_patch_as_service(
        f"/church_posts?id=eq.{_q(post_id)}&business_id=eq.{_q(business_id)}&status=eq.waiting", patch)
    return None if done is None else True


# ─── the switch ──────────────────────────────────────────────────────


def save_switch(business_id: str, value: bool) -> bool:
    """Member posting on or off in this church's settings (read right before
    the write, so nothing changed meanwhile is undone)."""
    fresh = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(business_id)}&select=settings&limit=1")
    if not isinstance(fresh, list) or not fresh:
        return False
    settings = dict(fresh[0].get("settings") or {})
    cfg = dict(settings.get("member_portal") or {}) if isinstance(settings.get("member_portal"), dict) else {}
    if value:
        cfg.pop(SWITCH, None)
    else:
        cfg[SWITCH] = False
    settings["member_portal"] = cfg
    return bool(sb_clients.sb_patch_as_service(f"/businesses?id=eq.{_q(business_id)}", {"settings": settings}))


# ─── the composer ────────────────────────────────────────────────────


def _flash(request: Request) -> str:
    q = request.query_params
    err = ERRORS.get(q.get("err") or "")
    if err:
        return f'<p class="mp-err mp-flash" role="alert">{_e(err)}</p>'
    done = DONE.get(q.get("done") or "")
    if done:
        return f'<p class="mp-ok mp-flash" role="status">{_e(done)}</p>'
    return ""


def render(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any], groups: Optional[List[Dict[str, Any]]],
           *, why: str, owner: bool) -> str:
    """The composer: who's posting, what kind (Praise · Prayer request ·
    Photo), where (one of my groups, or the whole church with a pastor
    first), the words, photos, comments, and Post."""
    import church_news as cn
    import member_app_ui as ui
    import member_lumen_connect as lc
    import member_photos as ph
    import news_share as ns
    from member_portal import _shell
    q = request.query_params
    want_group = str(q.get("group") or "")
    kind = q.get("type") if q.get("type") in TYPE_KEYS else "praise"
    mine = ph.src(me) if me else ""
    face = (f'<span class="lm-gme"><img src="{_e(mine)}" alt=""></span>' if mine
            else f'<span class="lm-gme" aria-hidden="true">{_e(ui.initials(me.get("name")))}</span>')
    groups = groups or []
    group_ok = not why and groups
    pick = want_group if any(g["id"] == want_group for g in groups) else (groups[0]["id"] if groups else "")
    types = "".join(
        f'<label class="lm-pchip"><input type="radio" name="type" value="{k}"{" checked" if k == kind else ""}>'
        f'<span>{_e(label)}</span></label>' for k, label in TYPES)
    where = []
    for g in groups if group_ok else []:
        where.append(f'<label class="lm-pwhere"><input type="radio" name="to" value="{_e(g["id"])}"'
                     f'{" checked" if g["id"] == pick else ""}><span><b>{_e(g["name"])}</b>'
                     f'<small>Only the people in this group see it</small></span></label>')
    church_checked = "" if group_ok else " checked"
    where.append(f'<label class="lm-pwhere"><input type="radio" name="to" value="church"{church_checked}><span>'
                 f'<b>The whole church (a pastor approves)</b><small>Your pastors read it first</small></span></label>')
    note = ""
    if why == "off":
        note = ('<p class="lm-pnote">Posting in groups is off at your church right now. You can still send good news '
                'or a prayer request to your pastors.</p>')
    elif why == "officers":
        note = ('<p class="lm-pnote">Posting in groups opens once your church has its two safety officers. '
                'You can still send good news or a prayer request to your pastors.</p>')
    elif not groups:
        note = '<p class="lm-pnote">Join a group to post in it. You can still send good news to your pastors.</p>'
    kinds = "".join(f'<label class="lm-pchip"><input type="radio" name="share_kind" value="{k}"><span>{_e(label)}</span></label>'
                    for k, label, _hint in ns.KINDS)
    modes = (("on", "Comments on"), ("prayers", "Prayers only"), ("off", "Off"))
    comments = "".join(f'<label class="lm-pchip"><input type="radio" name="comments" value="{k}"{" checked" if k == "on" else ""}>'
                       f'<span>{_e(label)}</span></label>' for k, label in modes)
    # Their birthday, asked once (above Post): only while posting has no
    # age for them and a group is on offer; the script shows it only while
    # a group is picked.
    bday = ""
    if group_ok and posting_birthdate(me) is None:
        today = date.today()
        oldest = today.replace(year=today.year - BDAY_MAX_AGE, day=min(today.day, 28))
        bday = (f'<fieldset class="lm-pset lm-pbday" id="lm-pbday"><legend id="lm-pbday-l">Your birthday</legend>'
                f'<div class="lm-field lm-find"><input type="date" name="birthday" autocomplete="bday" '
                f'min="{oldest.isoformat()}" max="{today.isoformat()}" aria-labelledby="lm-pbday-l" '
                f'aria-describedby="lm-pbday-n"></div>'
                f'<p class="lm-pguard" id="lm-pbday-n"><span>We ask once. It keeps teens safe in groups.</span></p></fieldset>')
    switch = ""
    if owner:
        state = "on" if on(biz) else "off"
        flip = "0" if state == "on" else "1"
        switch = (f'<form class="lm-pswitch" method="post" action="/my/post/switch"><input type="hidden" name="on" value="{flip}">'
                  f'<span><b>Members posting in their groups</b><small>{"On" if state == "on" else "Off"} at your church. '
                  f'Only you see this.</small></span>'
                  f'<button class="lm-cpill sm" type="submit">{"Turn off" if state == "on" else "Turn on"}</button></form>')
    body = (f'{switch}<header class="lm-ctop"><h1 class="lm-ctt">New post</h1>'
            f'<p class="lm-ctsub">Share a praise or a prayer</p></header>{_flash(request)}{note}'
            f'<form class="lm-mpform" id="lm-post" method="post" action="/my/post" enctype="multipart/form-data">'
            f'<div class="lm-pme">{face}<b>{_e(me.get("name") or "")}</b></div>'
            f'<fieldset class="lm-pset"><legend>What is it?</legend><div class="lm-pchips">{types}</div></fieldset>'
            f'<fieldset class="lm-pset"><legend>Who sees it</legend><div class="lm-pwheres">{"".join(where)}</div></fieldset>'
            f'<fieldset class="lm-pset lm-pkinds"><legend>For the whole church: what happened?</legend>'
            f'<div class="lm-pchips">{kinds}</div></fieldset>'
            f'<label class="lm-pbox"><span class="mp-sr">Your words</span><textarea name="body" rows="5" maxlength="{TEXT_MAX}" '
            f'placeholder="{_e(HINT[kind])}"></textarea></label>'
            f'<label class="lm-pphoto">{lc.ic("image", 22)}<span><b>Add photos</b><small>Up to {PHOTOS_MAX} in a group, one for '
            f'the whole church. Each is checked first.</small></span>'
            f'<input type="file" name="photos" accept="image/jpeg,image/png,image/webp" multiple></label>'
            f'<fieldset class="lm-pset lm-pcomments"><legend>Comments</legend><div class="lm-pchips">{comments}</div></fieldset>'
            f'<p class="lm-pguard">{lc.ic("shield", 16)}<span>Every post is checked before anyone sees it. '
            f'A prayer request goes on your group\'s prayer wall.</span></p>{bday}'
            f'<button class="lm-cpill pri" type="submit">Post</button></form>')
    # Back: the group it was opened from, else wherever they came from (a
    # pushed page: the browser's history, Home without it).
    back = None
    if want_group and pick == want_group:
        back = (f"/my/groups/{pick}", next(g["name"] for g in groups if g["id"] == pick))
    return _shell(biz, site, "New post", f'<div class="lm-cx">{body}</div>', tab="news", who=me,
                  back=back, script=POST_JS)


# The words' hint follows the kind; the whole church's "what happened"
# shows only for the whole church, and the birthday only for a group, where
# it's needed (without script, they always show).
POST_JS = """<script>(function(){var f=document.getElementById('lm-post');if(!f)return;f.classList.add('js');
var H={praise:"What is God doing? Tell them\\u2026",prayer:"What can we pray about?",photo:"Say something about it\\u2026"};
function sync(){var t=f.querySelector('input[name=type]:checked'),w=f.querySelector('input[name=to]:checked');
var k=t?t.value:'praise',c=w&&w.value==='church';f.classList.toggle('is-church',!!c);f.classList.toggle('is-prayer',k==='prayer');
var a=f.querySelector('textarea');if(a)a.placeholder=H[k]||'';
var b=document.getElementById('lm-pbday');if(b){b.hidden=!!c;var d=b.querySelector('input');if(d){d.disabled=!!c;d.required=!c;}}}
f.addEventListener('change',sync);sync();
f.addEventListener('submit',function(){var b=f.querySelector('button[type=submit]');if(b){b.disabled=true;b.textContent='Posting\\u2026';}});})();</script>"""


async def serve(request: Request, biz: Dict[str, Any], site, me: Dict[str, Any], *, owner: bool = False) -> Tuple[str, int]:
    """GET /my/post: the composer (member_portal.serve; the new look only)."""
    groups, why = await asyncio.gather(asyncio.to_thread(groups_of, str(biz["id"]), str(me["id"])),
                                       asyncio.to_thread(closed, biz))
    return render(biz, site, request, me, groups, why=why, owner=owner), 200


# ─── the routes ──────────────────────────────────────────────────────


# A group's page shows member_portal_church.DONE, where "posted" is the Youth
# space's words ("Posted to Youth."). A member's post landing on a group's
# page carries its own code there, worded as DONE above.
ON_GROUP_PAGE = {"posted": "group_posted", "post_held": "group_post_held", "removed": "group_post_removed"}


def _go(path: str = "/my/post", **q: str) -> RedirectResponse:
    from member_portal import _SECURE_HEADERS
    ok = path == "/my/post" or re.fullmatch(r"/my/groups/[0-9a-fA-F-]{36}(/prayer)?", path)
    if ok and path != "/my/post" and q.get("done") in ON_GROUP_PAGE:
        q = {**q, "done": ON_GROUP_PAGE[q["done"]]}
    qs = "&".join(f"{k}={v}" for k, v in q.items() if v)
    return RedirectResponse((path if ok else "/my/post") + (f"?{qs}" if qs else ""), status_code=303,
                            headers=_SECURE_HEADERS)


async def _signed_in(request: Request):
    """(church, sess, me) for a member's POST, or a redirect: this church's
    address and the same site (member_portal._church_or_404), a live
    session (never the owner's preview: nothing saves there), and the new
    look showing to this session (member_lumen: off, it goes Home and
    writes nothing)."""
    import member_lumen
    import member_portal as mp
    church = await mp._church_or_404(request)
    sess = await asyncio.to_thread(mp._session_for, request, church)
    if sess and sess.get("unavailable"):
        return church, sess, None, _go(err="error")
    if sess and sess.get("preview"):
        return church, sess, None, _go(err="preview")
    if not sess or not sess.get("me"):
        return church, sess, None, RedirectResponse("/my", status_code=303, headers=mp._SECURE_HEADERS)
    if not await member_lumen.decide(request, {"business": church["business"], "session": sess}):
        return church, sess, None, RedirectResponse("/my", status_code=303, headers=mp._SECURE_HEADERS)
    import rate_limit
    if not rate_limit.allow_strict("member_action", f"{church['business']['id']}|{sess['me']['id']}"):
        return church, sess, None, _go(err="slow")
    return church, sess, sess["me"], None


@router.post("/my/post", include_in_schema=False)
async def post_route(request: Request):
    import member_photos
    church, sess, me, stop = await _signed_in(request)
    if stop:
        return stop
    biz = church["business"]
    try:
        form = await request.form()
    except Exception:  # noqa: BLE001
        return _go(err="error")
    kind = str(form.get("type") or "praise")
    kind = kind if kind in TYPE_KEYS else "praise"
    to = str(form.get("to") or "")
    files: List[bytes] = []
    for up in form.getlist("photos"):
        if hasattr(up, "read"):
            raw = await up.read(member_photos.MAX_BYTES + 1)
            if raw:
                files.append(raw)
    text = str(form.get("body") or "")
    if to == "church":
        ok, code = await to_church(biz, me, kind, text, str(form.get("share_kind") or ""), files[0] if files else None)
        return _go(**({"done": code} if ok else {"err": code}))
    if not UUID.match(to):
        return _go(err="post_where")
    if posting_birthdate(me) is None and str(form.get("birthday") or "").strip():
        # Their birthday, asked once, saved with the post (posting only).
        # Without one, the rules say so (they read the record fresh).
        born, why = check_birthdate(form.get("birthday"))
        if why:
            return _go(err=why, group=to)
        saved = await asyncio.to_thread(save_birthdate, str(biz["id"]), str(me["id"]), born)
        if saved is None:
            return _go(err="error", group=to)
        import member_feed_more
        member_feed_more.forget_record(biz["id"], me)
    ok, code, _pid = await to_group(biz, me, to, kind, text, files, str(form.get("comments") or "on"))
    if not ok:
        return _go(err=code, group=to)
    return _go(f"/my/groups/{to}" + ("/prayer" if kind == "prayer" else ""), done=code)


@router.post("/my/post/remove", include_in_schema=False)
async def remove_route(request: Request):
    """Take a member's group post down: its writer, or a leader of its group.
    Works whatever the look (taking something down is never switched off)."""
    import member_portal_church as mpc
    church, me, unavailable = await mpc._signed_in(request)
    if unavailable:
        return _go(err="preview" if unavailable == "preview" else "error")
    if not me:
        return mpc._back("/my")
    if not mpc._allowed(church, me):
        return _go(err="slow")
    form = await request.form()
    ok, code, gid = await asyncio.to_thread(remove, str(church["business"]["id"]), me, str(form.get("id") or ""))
    return _go(f"/my/groups/{gid}" if gid else "/my/post", **({"done": code} if ok else {"err": code}))


@router.post("/my/post/switch", include_in_schema=False)
async def switch_route(request: Request):
    """Member posting on or off: the church owner, from their preview (the
    picture spots' and the pastor's note's way in), where the new look shows."""
    import member_app_pictures as mapic
    import member_cache
    import member_lumen
    import member_portal as mp
    import rate_limit
    church = await mp._church_or_404(request)
    biz = church["business"]
    sess = await asyncio.to_thread(mp._session_for, request, church)
    by = mapic.may_edit(sess, biz) or ""
    if not by.startswith("owner:"):
        return RedirectResponse("/my", status_code=303, headers=mp._SECURE_HEADERS)
    if not await member_lumen.decide(request, {"business": biz, "session": sess}):
        return RedirectResponse("/my", status_code=303, headers=mp._SECURE_HEADERS)
    if not rate_limit.allow_strict("member_action", f"{biz['id']}|post_switch|{by}"):
        return _go(err="slow")
    form = await request.form()
    value = str(form.get("on") or "") == "1"
    ok = await asyncio.to_thread(save_switch, str(biz["id"]), value)
    if ok:
        member_cache.forget_church(biz["id"])
        logger.info("member posting switched", extra={"business_id": biz["id"], "on": value, "by": by})
    return _go(**({"done": "switch_on" if value else "switch_off"} if ok else {"err": "error"}))
