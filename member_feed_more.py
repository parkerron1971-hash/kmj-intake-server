"""member_feed_more.py — what Home's feed carries besides the church's posts, in
the member app's new look (Look 5.1, member_lumen_feed).

Kevin approved Look 5.1 on 2026-11-20 ("this is awesome. much better design.
lets build this including the new still to build!"). Its feed is one stream:
the church's posts (church_news.home_view, as before) and, merged in by time,

  * THE NEWEST MESSAGE, while it is new: the church's latest published
    message when it was preached in the last MESSAGE_DAYS days (message_of).
    Home already reads the sermon library (member_portal_sermons
    .load_library), so this costs nothing.
  * YOUR GROUPS: the newest Board posts of the groups this member is in
    (group_posts, the group page's Board: member_portal_groups.posts_for's
    rules: a word for the leaders only reaches leaders, a post scheduled
    for later waits), and the open prayer requests on their prayer walls
    (group_prayers: group_prayer.wall's rules: never a "a pastor has it"
    card, never an answered one), each from the last GROUP_DAYS days.
    The request's "I prayed" is the wall's own "I'm praying" mark
    (group_prayer.mark, POST /my/groups/prayer/mark).

READS. Home's gather runs gather() beside its other reads, so it adds no
wait: the member's groups with their names (group_members, the groups row
embedded: one read), then their Board posts and their prayer requests
(group_prayers with their marks embedded) together, then the people on
them (one contacts read). Kept GROUP_SECONDS per member on each server copy
(member_cache.feed), so tapping back to Home reads nothing. A failed read
only leaves that source out (and nothing is kept, so the next Home tries
again). Marking a request forgets this member's copy (forget()), and Home
answering that mark reads fresh (FRESH_DONE).

SAVED. Save on a church post keeps it on the member's own record:
contacts.metadata.member_saved, a list of post ids, newest first, at most
SAVED_MAX (no migration). Written like the member's Look (member_lumen_look
.save: the record's updated_at guards an office edit made at the same
moment; only the signed-in member's own row). Pages read it from the record
the session already reads (member_portal.contacts_for_email / _phone select
saved:metadata->member_saved): no read. Saving forgets that record on this
server copy (member_cache.people) so the next page shows it. The Saved
posts page (/my/news/saved, from Me) reads the posts themselves (saved_view).
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import sb_clients

logger = logging.getLogger("member_feed_more")

MESSAGE_DAYS = 7          # the newest message rides in the feed this long after it was preached
GROUP_DAYS = 14           # group posts and prayer requests from the last two weeks
POSTS_READ = 6            # the newest Board posts read across the member's groups
PRAYERS_READ = 6          # the newest open prayer requests read across them
SHOWN = 2                 # group items Home shows among the church's posts
SAVED_KEY = "member_saved"
SAVED_MAX = 100
SAVED_SHOWN = 30          # the Saved posts page lists this many, newest saved first
FRESH_DONE = ("praying", "unmarked")
UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
PERSON = "id,name,birthdate,metadata"


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ids(xs) -> str:
    return ",".join(_q(x) for x in sorted({str(x) for x in xs if x}))


# ─── the newest message ──────────────────────────────────────────────


def message_of(lib: Optional[Dict[str, Any]], today: date) -> Optional[Dict[str, Any]]:
    """The church's newest published message when it was preached in the
    last MESSAGE_DAYS days (the library is newest first), else None. A
    sample message (the owner's preview of an empty church) never rides in
    the feed."""
    import member_app_samples as samples
    if not lib or not lib.get("sermons"):
        return None
    s = lib["sermons"][0]
    try:
        d = date.fromisoformat(str(s.get("preached_on") or "")[:10])
    except ValueError:
        return None
    if samples.is_sample(s) or not 0 <= (today - d).days <= MESSAGE_DAYS:
        return None
    return s


# ─── your groups ─────────────────────────────────────────────────────


def my_groups(business_id: str, me_id: str) -> Optional[Dict[str, Dict[str, Any]]]:
    """The running groups this member is in: {id: {name, mode, leader}}
    (mode: the group's name display, full or first). One read: the group's
    row rides along (group_members.group_id → groups). None when it failed."""
    rows = sb_clients.sb_get_as_service(
        f"/group_members?business_id=eq.{_q(business_id)}&contact_id=eq.{_q(me_id)}"
        f"&select=group_id,role,groups(id,name,name_display,active)&limit=200")
    if not isinstance(rows, list):
        return None
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        g = r.get("groups") if isinstance(r.get("groups"), dict) else None
        if not g or not g.get("active"):
            continue
        out[str(r["group_id"])] = {"name": g.get("name") or "Your group",
                                   "mode": g.get("name_display") if g.get("name_display") in ("full", "first") else "full",
                                   "leader": r.get("role") == "leader"}
    return out


def _group_posts(business_id: str, groups: Dict[str, Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    """The newest Board posts of these groups (member_portal_groups
    .posts_for's rules), each with `at`, when it went up."""
    import group_post_later as gpl
    since = _q((_now() - timedelta(days=GROUP_DAYS)).isoformat())
    rows = sb_clients.sb_get_as_service(
        f"/group_posts?business_id=eq.{_q(business_id)}&group_id=in.({_ids(groups)})&removed_at=is.null"
        f"&created_at=gte.{since}&select=id,group_id,title,body,posted_by,audience,publish_at,created_at"
        f"&order=created_at.desc&limit={POSTS_READ}")
    if not isinstance(rows, list):
        return None
    out = []
    for r in rows:
        g = groups.get(str(r.get("group_id") or ""))
        if not g or gpl.is_waiting(r) or (r.get("audience") == "leaders" and not g["leader"]):
            continue
        out.append({"id": str(r["id"]), "group_id": str(r["group_id"]), "title": r.get("title") or "",
                    "body": r.get("body") or "", "posted_by": str(r.get("posted_by") or ""),
                    "at": str(r.get("publish_at") or r.get("created_at") or "")})
    return out


def _group_prayers(business_id: str, me_id: str, groups: Dict[str, Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    """The open requests on these groups' prayer walls (group_prayer.wall's
    rules: no pastor card, nothing answered), newest first, with their
    "I'm praying" marks (embedded: group_prayer_marks.prayer_id)."""
    since = _q((_now() - timedelta(days=GROUP_DAYS)).isoformat())
    rows = sb_clients.sb_get_as_service(
        f"/group_prayers?business_id=eq.{_q(business_id)}&group_id=in.({_ids(groups)})&removed_at=is.null"
        f"&answered_at=is.null&to_pastor=is.false&created_at=gte.{since}"
        f"&select=id,group_id,contact_id,body,created_at,group_prayer_marks(contact_id,kind,created_at)"
        f"&order=created_at.desc&limit={PRAYERS_READ}")
    if not isinstance(rows, list):
        return None
    out = []
    for r in rows:
        if str(r.get("group_id") or "") not in groups or not (r.get("body") or "").strip():
            continue
        marks = [m for m in (r.get("group_prayer_marks") or []) if isinstance(m, dict) and m.get("kind") == "praying"]
        marks.sort(key=lambda m: str(m.get("created_at") or ""), reverse=True)
        who = [str(m["contact_id"]) for m in marks if m.get("contact_id")]
        out.append({"id": str(r["id"]), "group_id": str(r["group_id"]), "body": r.get("body") or "",
                    "asker_id": str(r.get("contact_id") or ""), "at": str(r.get("created_at") or ""),
                    "mine": str(r.get("contact_id") or "") == str(me_id), "n": len(set(who)),
                    "i_pray": str(me_id) in who,
                    "face_ids": [c for c in dict.fromkeys(who) if c != str(me_id)][:3]})
    return out


def read(business_id: str, me_id: str) -> Tuple[Optional[Dict[str, Any]], bool]:
    """(what the feed shows from the member's groups, whether every read
    worked). Sequential; gather() runs the same reads with the two middle
    ones together."""
    groups = my_groups(business_id, me_id)
    if groups is None:
        return None, False
    posts = _group_posts(business_id, groups) if groups else []
    prayers = _group_prayers(business_id, me_id, groups) if groups else []
    return _finish(business_id, groups, posts, prayers)


def _finish(business_id: str, groups: Dict[str, Dict[str, Any]], posts: Optional[List[Dict[str, Any]]],
            prayers: Optional[List[Dict[str, Any]]]) -> Tuple[Dict[str, Any], bool]:
    import church_news as cn
    ok = posts is not None and prayers is not None
    posts, prayers = posts or [], prayers or []
    ids = [p["posted_by"] for p in posts] + [p["asker_id"] for p in prayers] + [c for p in prayers for c in p["face_ids"]]
    people = cn._people(business_id, ids) if any(ids) else {}
    if people is None:
        # Without names nothing can be drawn as it should: leave both out.
        return {"groups": groups, "posts": [], "prayers": []}, False
    for p in posts:
        p["author"] = people.get(p["posted_by"]) or {}
    for p in prayers:
        p["asker"] = people.get(p["asker_id"]) or {}
        p["faces"] = [people[c] for c in p["face_ids"] if c in people]
    return {"groups": groups, "posts": posts, "prayers": prayers}, ok


async def gather(biz: Dict[str, Any], me: Dict[str, Any], *, fresh: bool = False) -> Optional[Dict[str, Any]]:
    """Home's group items, beside Home's other reads (read() with the Board
    and the walls read together), kept GROUP_SECONDS per member. None when
    the member's groups couldn't be read. Never raises: a failure only
    leaves the group items out."""
    import member_cache
    business_id, me_id = str(biz["id"]), str(me["id"])
    key = (business_id, me_id)
    if not fresh:
        hit, got = member_cache.feed.get(key)
        if hit:
            return got
    try:
        groups = await asyncio.to_thread(my_groups, business_id, me_id)
        if groups is None:
            return None
        if groups:
            posts, prayers = await asyncio.gather(asyncio.to_thread(_group_posts, business_id, groups),
                                                  asyncio.to_thread(_group_prayers, business_id, me_id, groups))
        else:
            posts, prayers = [], []
        got, ok = await asyncio.to_thread(_finish, business_id, groups, posts, prayers)
    except Exception:  # noqa: BLE001 — the feed's extras never cost Home
        logger.warning("home feed: the group items skipped", exc_info=True)
        return None
    if ok:
        member_cache.feed.put(key, got, tag=business_id)
    return got


def forget(business_id: Any, me_id: Any) -> None:
    """Drop this member's kept group items on this server copy (they just
    marked a request)."""
    import member_cache
    key = (str(business_id), str(me_id))
    member_cache.feed.forget(lambda k, _tag: k == key)


# ─── saved posts ─────────────────────────────────────────────────────


def saved_ids(me: Optional[Dict[str, Any]]) -> List[str]:
    """The posts this member saved, newest first: from the session's record
    (`saved`, read with it) or a whole record's metadata."""
    if not me:
        return []
    v = me.get("saved")
    if v is None and isinstance(me.get("metadata"), dict):
        v = me["metadata"].get(SAVED_KEY)
    if not isinstance(v, list):
        return []
    return [str(x) for x in v if isinstance(x, str) and UUID.match(x)][:SAVED_MAX]


def toggle_saved(business_id: str, contact_id: str, post_id: str) -> Optional[bool]:
    """Save or unsave a post on the member's own record (contacts.metadata
    .member_saved), guarded by updated_at so an office edit at the same
    moment isn't lost (as member_lumen_look.save). The new state (True:
    saved), or None when it couldn't save."""
    import member_portal_church as mpc
    if not UUID.match(str(post_id or "")):
        return None
    for _ in range(3):
        me = mpc.load_me(business_id, contact_id)
        if not me:
            return None
        meta = dict(me.get("metadata") or {}) if isinstance(me.get("metadata"), dict) else {}
        have = saved_ids({"metadata": meta})
        on = post_id not in have
        meta[SAVED_KEY] = ([post_id] + have)[:SAVED_MAX] if on else [x for x in have if x != post_id]
        guard = f"eq.{_q(me['updated_at'])}" if me.get("updated_at") else "is.null"
        got = sb_clients.sb_patch_as_service(
            f"/contacts?id=eq.{_q(contact_id)}&business_id=eq.{_q(business_id)}&updated_at={guard}",
            {"metadata": meta})
        if isinstance(got, list) and got:
            return on
    return None


def forget_record(business_id: Any, me: Dict[str, Any]) -> None:
    """Drop the member's kept session record on this server copy, so the
    next page shows what they just saved (member_cache.people is kept per
    church and email or phone)."""
    import member_cache
    import member_portal as mp
    keys = {(str(business_id), mp.norm_ident(v)) for v in (me.get("email"), me.get("phone")) if v}
    if keys:
        member_cache.people.forget(lambda k, _tag: k in keys)


def saved_view(business_id: str, me_id: str, ids: List[str]) -> Optional[List[Dict[str, Any]]]:
    """The saved posts this member may still see, newest saved first, each
    as the feed draws it (church_news._decorate with its newest comments).
    Taken down, not yet live, or no longer for their groups: left out. None
    when a read failed."""
    import church_news as cn
    ids = [i for i in ids if UUID.match(i)][:SAVED_SHOWN]
    if not ids:
        return []
    rows = sb_clients.sb_get_as_service(
        f"/church_posts?business_id=eq.{_q(business_id)}&id=in.({_ids(ids)})&status=eq.posted&removed_at=is.null"
        f"&select={cn.POST_SELECT}&limit={len(ids)}")
    groups = cn.my_groups(business_id, me_id)
    if rows is None or groups is None:
        return None
    now, mine = _now(), set(groups)
    by = {str(r["id"]): r for r in rows if cn.is_live(r, now) and cn.reaches(r, mine, me_id)}
    shown = [by[i] for i in ids if i in by]
    return cn._decorate(business_id, shown, me_id, previews=True, batch=True)
