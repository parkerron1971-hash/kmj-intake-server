"""
member_alerts.py — the member app's recent alerts: the bell's list and its dot.

Kevin, 2026-11-18, on the approved member app redesign ("Lumen"): "yes build
the bell list". The redesign's top bar has a bell that opens "Your alerts"
(/my/notifications): a "Recent" list on top, the existing "What reaches
this phone" settings under it, and a dot on the bell when something arrived
since the member last opened that page.

WHAT COUNTS AS AN ALERT (recent_alerts). Only what was really sent to this
member, from records that already exist; nothing new is recorded:

  * The church's notes, while church threads are open for the church
    (church_threads.open_for, CHURCH_THREADS): church_thread_notes rows from
    the church (direction 'church') that were recorded for this member (one
    row per person a note named: event reminders, class nights, a prayer
    answered, kids check-in, serving, news, a group's Board post or prayer
    request), the church-wide ones (contact_id null: announcements, live,
    new sermons), and the office's replies in their church conversation.
  * Otherwise (threads closed for the church), member_push_sends, the claim
    log, which names no recipients. Only what can be told exactly from it:
    the church-wide kinds (announcements, live, sermons: always sent to
    everyone with the kind on) and "Someone prayed for you" (a prayed:<id>
    claim for a request this member made, ministry_care_requests).
  * Chat messages ("messages"): the chats whose new messages reach this
    member as a note (member_push.chat_recipients' rule): a direct chat they
    haven't declined or muted, and the group chats (and the leaders room)
    they are in with messaging on and "Every message" chosen. One row per
    chat, its newest message from someone else, like the lock screen (one
    note per chat).

Every row also needs the member's kinds: the church's switch for the kind
(member_push.church_kinds) and not turned off by the member. An office reply
follows "New messages" only (push_reply's rule). Not here: youth posts (the
Youth room is their place, as church_threads leaves them out too), a group
chat set to Evening summary or Off (its evening note isn't kept), and, while
threads are closed, the targeted notes member_push_sends can't name a person
for (events, classes, kids, groups, news, serving). member_push_held is only
a waiting room for notes that are recorded above anyway.

PRIVACY is the lock screen's (member_push): a row shows the words member_push
chose for the lock screen, never a message's or a prayer request's text. A
chat row says "New message" (or "New message in <group>"); an office reply
says "New message from the church", never what it says.

SEEN (alerts_unseen, mark_seen). No migration: when the member last opened
the page is one church_thread_reads row with thread 'alerts' (that table
holds when each member last opened each conversation; 'alerts' is never a
note's thread). The dot is True when the newest alert is newer than that,
kept DOT_SECONDS per member per server copy. Opening /my/notifications marks
everything seen (the owner's preview never writes). While church_thread_reads
is missing, the dot stays hidden and the list still shows.

WHO SEES IT. shown(): the redesign's switch (member_lumen: MEMBER_LUMEN,
decided once per request by member_portal.serve) and this list's own
rollback, MEMBER_ALERTS_LIST=off (on when unset). Off, the page
is exactly the old settings page and nothing here is read.

SPEED. The list reads only on /my/notifications. The dot is cached: a miss
costs one round of parallel reads (the member's chats are kept CHATS_SECONDS
for it). Never raises: a failed read answers None (the page shows without
the list) or False (no dot).
"""
from __future__ import annotations

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any, Callable, Dict, Iterable, List, Optional, Set
from urllib.parse import quote

import sb_clients

logger = logging.getLogger("member_alerts")

ENV = "MEMBER_ALERTS_LIST"
SEEN_THREAD = "alerts"                 # its church_thread_reads row
LIMIT = 20
WINDOW_DAYS = 60                       # church_threads.CHURCH_WIDE_DAYS
DOT_SECONDS = 45.0
CHATS_SECONDS = 300.0
WIDE_KINDS = ("announcements", "live", "sermons")      # always sent to everyone
CHAT_MESSAGES = 400                    # newest messages read to find each chat's newest
MAX_CHATS = 200
LINE_MAX = 180
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

# kind: (the family colour its icon wears, member_app_ui.ICONS)
LOOK = {
    "announcements": ("h-brand", "bell"),
    "live": ("h-violet", "live"),
    "messages": ("h-teal", "chat"),
    "sermons": ("h-violet", "play"),
    "events": ("h-coral", "calendar"),
    "classes": ("h-gold", "book"),
    "prayer": ("h-brand", "pray"),
    "groups": ("h-teal", "users"),
    "youth": ("h-violet", "star"),
    "kids": ("h-coral", "check"),
    "news": ("h-brand", "doc"),
    "serving": ("h-teal", "heart"),
}

# Reads run side by side here (never nested: a stage's reads don't start
# reads of their own), so a page waits for one round, not one after another.
_POOL = ThreadPoolExecutor(max_workers=24, thread_name_prefix="member-alerts")


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _plain(v: Any, top: int = LINE_MAX) -> str:
    return " ".join(str(v or "").split())[:top]


def _rows(path: str) -> Optional[List[Dict[str, Any]]]:
    got = sb_clients.sb_get_as_service(path)
    return got if isinstance(got, list) else None


def _together(jobs: Dict[str, Callable[[], Any]]) -> Dict[str, Any]:
    """Run each job at once; a job that raised answers None."""
    futures = {name: _POOL.submit(fn) for name, fn in jobs.items()}
    out: Dict[str, Any] = {}
    for name, f in futures.items():
        try:
            out[name] = f.result(timeout=20)
        except Exception:
            logger.warning("member alerts: a read failed (%s)", name, exc_info=True)
            out[name] = None
    return out


def _at(iso: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _iso(iso: Any) -> str:
    d = _at(iso)
    return d.astimezone(timezone.utc).isoformat(timespec="microseconds") if d else ""


def _since(now: Optional[datetime] = None) -> str:
    return ((now or datetime.now(timezone.utc)) - timedelta(days=WINDOW_DAYS)).isoformat()


# ─── The switches ─────────────────────────────────────────────────────


def switched_on() -> bool:
    """MEMBER_ALERTS_LIST: on unless it says off."""
    return (os.environ.get(ENV) or "on").strip().lower() not in ("off", "0", "false", "no")


def shown() -> bool:
    """Whether the member page being drawn shows the list: this list's
    switch, then the redesign's (member_lumen: MEMBER_LUMEN, which
    member_portal.serve decides once per request with member_lumen.visible
    and keeps for the page, here()). Closed when either can't be told."""
    if not switched_on():
        return False
    try:
        import member_lumen
        return bool(member_lumen.here())
    except Exception:
        logger.warning("member alerts: the redesign's switch couldn't be read", exc_info=True)
        return False


# ─── What reaches this member ─────────────────────────────────────────


def my_kinds(business: Dict[str, Any], off: Iterable[str]) -> Set[str]:
    """The kinds this member hears: the church's switch, less theirs."""
    import member_push
    return member_push.church_kinds(business.get("settings")) - set(off or ())


def labels() -> Dict[str, str]:
    import member_push
    return {k: label for k, label, _ in member_push.KINDS}


def _row(kind: str, title: str, body: str, when: Any, link: str) -> Dict[str, Any]:
    import member_push
    title, body = _plain(title), _plain(body)
    return {"kind": kind, "label": labels().get(kind, ""), "title": title or body,
            "body": "" if (not title or body.casefold() == title.casefold()) else body,
            "when": _iso(when), "link": member_push._safe_url(link) if link else ""}


def _church_name(business: Dict[str, Any]) -> str:
    return _plain(business.get("name"), 120)


def _note_row(business: Dict[str, Any], r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One church_thread_notes row, in the lock screen's words."""
    kind = str(r.get("kind") or "")
    if kind == "reply":
        # The office's reply: that it came, never what it says.
        return _row("messages", "New message from the church", "", r.get("created_at"), "/my/inbox/church")
    title, body = _plain(r.get("title")), _plain(r.get("body"))
    name = _church_name(business)
    if name and title.casefold() == name.casefold():
        # News and birthdays carry the church's name as their title.
        title, body = body, ""
    if not title and not body:
        return None
    return _row(kind, title, body, r.get("created_at"), str(r.get("url") or ""))


def _thread_notes(biz_id: str, cid: str, since: str, n: int) -> Optional[List[Dict[str, Any]]]:
    import church_threads as ct
    kinds = ",".join(list(ct.THREAD_KINDS) + ["reply"])
    return _rows(f"/{ct.NOTES}?business_id=eq.{_q(biz_id)}&direction=eq.church&kind=in.({kinds})"
                 f"&or=(contact_id.eq.{_q(cid)},and(contact_id.is.null,thread.eq.{ct.CHURCH}))"
                 f"&created_at=gte.{_q(since)}&select=id,kind,title,body,url,created_at"
                 f"&order=created_at.desc&limit={n}")


def _wide_sends(biz_id: str, since: str, n: int) -> Optional[List[Dict[str, Any]]]:
    return _rows(f"/member_push_sends?business_id=eq.{_q(biz_id)}&kind=in.({','.join(WIDE_KINDS)})"
                 f"&created_at=gte.{_q(since)}&select=kind,title,body,url,created_at"
                 f"&order=created_at.desc&limit={n}")


def _my_prayed(biz_id: str, cid: str, since: str, n: int) -> Optional[List[Dict[str, Any]]]:
    return _rows(f"/ministry_care_requests?business_id=eq.{_q(biz_id)}&contact_id=eq.{_q(cid)}"
                 f"&prayed_at=gte.{_q(since)}&select=id&order=prayed_at.desc&limit={n}")


def _prayed_sends(biz_id: str, request_ids: List[str]) -> Optional[List[Dict[str, Any]]]:
    refs = ",".join(_q(f'"prayed:{i}"') for i in request_ids)
    return _rows(f"/member_push_sends?business_id=eq.{_q(biz_id)}&kind=eq.prayer&ref_id=in.({refs})"
                 f"&select=kind,title,body,url,created_at")


# ─── Chats ────────────────────────────────────────────────────────────

_CHATS: Any = None


def _chats_kept():
    global _CHATS
    if _CHATS is None:
        import member_cache
        _CHATS = member_cache.Kept("alert-chats", CHATS_SECONDS)
    return _CHATS


def _chat_first(biz_id: str, cid: str) -> Dict[str, Callable[[], Any]]:
    """The first round of the chats' reads: is messaging on for them, the
    chats they have a place in, and their groups."""
    import member_portal_messaging as mpm
    b, c = _q(biz_id), _q(cid)
    return {
        "chat_member": lambda: _rows(f"/msg_members?business_id=eq.{b}&contact_id=eq.{c}&select=enabled&limit=1"),
        "chat_parts": lambda: _rows(f"/msg_participants?business_id=eq.{b}&contact_id=eq.{c}"
                                    f"&select=thread_id,state,muted,notify&limit=500"),
        "chat_groups": lambda: mpm.my_groups(biz_id, cid),
    }


def _chat_threads(biz_id: str, tids: List[str], gids: List[str]) -> Optional[List[Dict[str, Any]]]:
    ors = []
    if tids:
        ors.append(f"id.in.({','.join(_q(t) for t in tids)})")
    if gids:
        ors.append(f"and(kind.eq.group,group_id.in.({','.join(_q(g) for g in gids)}))")
    if not ors:
        return []
    where = f"or=({','.join(ors)})" if len(ors) > 1 else (
        f"id=in.({','.join(_q(t) for t in tids)})" if tids else f"kind=eq.group&group_id=in.({','.join(_q(g) for g in gids)})")
    return _rows(f"/msg_threads?business_id=eq.{_q(biz_id)}&{where}&select=id,kind,group_id&limit=500")


def _chat_set(biz_id: str, cid: str, first: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """{"chats": [{"id", "kind", "group_id"}]}: the chats whose new messages
    reach this member as a note (member_push.chat_recipients: never declined
    or muted; a group's or the leaders room's only with messaging on and
    "Every message"; a group's only while they're in the group). None when a
    read failed."""
    import group_chat_notify as gcn
    member, parts, groups = first.get("chat_member"), first.get("chat_parts"), first.get("chat_groups")
    if member is None or parts is None or groups is None:
        return None
    enabled = bool(member and member[0].get("enabled"))
    by = {str(p.get("thread_id")): p for p in parts if p.get("thread_id")}
    gids = sorted({str(g["group_id"]) for g in groups if g.get("group_id")})
    threads = _chat_threads(biz_id, sorted(by), gids if enabled else [])
    if threads is None:
        return None
    mine_g = set(gids)
    out = []
    for t in threads:
        tid, kind = str(t.get("id") or ""), str(t.get("kind") or "")
        p = by.get(tid) or {}
        if not tid or p.get("muted") or p.get("state") == "declined":
            continue
        if kind == "direct":
            if not p:
                continue
        elif kind == "group":
            if not enabled or str(t.get("group_id") or "") not in mine_g or not gcn.hears_each(t, p):
                continue
        elif kind == "leaders":
            if not enabled or not p or not gcn.hears_each(t, p):
                continue
        else:
            continue
        out.append({"id": tid, "kind": kind, "group_id": str(t.get("group_id") or "")})
    return {"chats": out[:MAX_CHATS]}


def _chat_rows(biz_id: str, cid: str, chats: List[Dict[str, Any]], since: str,
               n: int, named: bool = True) -> Optional[List[Dict[str, Any]]]:
    """One row per chat: its newest message from someone else, in
    member_push's words ("New message", "New message in <group>").
    `named=False` (the dot) skips reading the groups' names."""
    import member_portal_messaging as mpm
    if not chats:
        return []
    tids = ",".join(_q(c["id"]) for c in chats)
    gids = sorted({c["group_id"] for c in chats if c["kind"] == "group" and c["group_id"]}) if named else []
    got = _together({
        "msgs": lambda: _rows(f"/msg_messages?business_id=eq.{_q(biz_id)}&thread_id=in.({tids})&status=eq.delivered"
                              f"&sender_contact_id=neq.{_q(cid)}&created_at=gte.{_q(since)}"
                              f"&select=thread_id,created_at&order=created_at.desc&limit={n}"),
        "names": (lambda: _rows(f"/groups?business_id=eq.{_q(biz_id)}&id=in.({','.join(_q(g) for g in gids)})"
                                f"&select=id,name&limit=500")) if gids else (lambda: []),
    })
    msgs, names = got.get("msgs"), got.get("names")
    if msgs is None or names is None:
        return None
    named = {str(g["id"]): _plain(g.get("name"), 80) for g in names}
    by = {c["id"]: c for c in chats}
    out, done = [], set()
    for m in msgs:                         # newest first
        tid = str(m.get("thread_id") or "")
        c = by.get(tid)
        if not c or tid in done:
            continue
        done.add(tid)
        if c["kind"] == "group":
            title = f"New message in {named.get(c['group_id']) or 'your group'}"
            link = f"/my/groups/{c['group_id']}/chat"
        elif c["kind"] == "leaders":
            title, link = f"New message in {mpm.LEADERS_ROOM}", "/my/groups/leaders"
        else:
            title, link = "New message", f"/my/messages/{tid}"
        out.append(_row("messages", title, "", m.get("created_at"), link))
    return out


# ─── The list ─────────────────────────────────────────────────────────


def _threads_open(business: Dict[str, Any]) -> bool:
    import church_threads as ct
    try:
        return bool(ct.open_for(business) and ct.tables_ready())
    except Exception:
        logger.warning("member alerts: church threads couldn't be checked", exc_info=True)
        return False


def _collect(business: Dict[str, Any], contact_id: Any, limit: int, *, off: Optional[Iterable[str]] = None,
             fresh: bool = True, extra: Optional[Dict[str, Callable[[], Any]]] = None,
             now: Optional[datetime] = None):
    """(rows or None, what each `extra` job answered). Reads in at most
    three rounds, each side by side."""
    import church_threads as ct
    import member_portal_messaging as mpm
    import member_push
    biz_id, cid = str(business.get("id") or ""), str(contact_id or "")
    if not UUID_RE.match(biz_id) or not UUID_RE.match(cid):
        return None, {}
    since = _since(now)
    church = member_push.church_kinds(business.get("settings"))
    threads = _threads_open(business)
    # Notes a member turned off still use up the read's rows: read enough.
    n = max(limit * 3, 30)
    jobs: Dict[str, Callable[[], Any]] = dict(extra or {})
    if off is None:
        jobs["off"] = lambda: member_push.turned_off(biz_id, cid)
    if threads:
        jobs["notes"] = lambda: _thread_notes(biz_id, cid, since, n)
    else:
        if church & set(WIDE_KINDS):
            jobs["wide"] = lambda: _wide_sends(biz_id, since, n)
        if "prayer" in church:
            jobs["prayed"] = lambda: _my_prayed(biz_id, cid, since, limit)
    chats_on = ("messages" in church and mpm.turned_on(business)
                and (off is None or "messages" not in set(off)))
    kept = _chats_kept()
    chat_set = None
    if chats_on:
        if not fresh:
            hit, got = kept.get((biz_id, cid))
            chat_set = got if hit else None
        if chat_set is None:
            jobs.update(_chat_first(biz_id, cid))
    first = _together(jobs)
    extras = {k: first.get(k) for k in (extra or {})}
    if off is None:
        off = first.get("off")
        if off is None:
            return None, extras
    mine = church - set(off)
    rows: List[Dict[str, Any]] = []
    if threads:
        notes = first.get("notes")
        if notes is None:
            return None, extras
        for r in notes:
            kind = str(r.get("kind") or "")
            if (kind == "reply" and "messages" not in set(off)) or kind in mine:
                row = _note_row(business, r)
                if row:
                    rows.append(row)
    else:
        wide = first.get("wide") if "wide" in jobs else []
        if wide is None:
            return None, extras
        rows += [_row(str(r["kind"]), r.get("title"), r.get("body"), r.get("created_at"), str(r.get("url") or ""))
                 for r in wide if str(r.get("kind") or "") in mine]
        if "prayed" in jobs and "prayer" in mine:
            asked = first.get("prayed")
            if asked is None:
                return None, extras
            ids = [str(a["id"]) for a in asked if UUID_RE.match(str(a.get("id") or ""))]
            if ids:
                sent = _prayed_sends(biz_id, ids)
                if sent is None:
                    return None, extras
                rows += [_row("prayer", r.get("title"), r.get("body"), r.get("created_at"), str(r.get("url") or ""))
                         for r in sent]
    if chats_on and "messages" in mine:
        if chat_set is None:
            chat_set = _chat_set(biz_id, cid, first)
            if chat_set is None:
                return None, extras
            kept.put((biz_id, cid), chat_set, tag=biz_id)
        chat = _chat_rows(biz_id, cid, chat_set.get("chats") or [], since, 1 if limit == 1 else CHAT_MESSAGES,
                          named=limit > 1)
        if chat is None:
            return None, extras
        rows += chat
    rows = [r for r in rows if r["when"]]
    rows.sort(key=lambda r: r["when"], reverse=True)
    return rows[:max(0, int(limit))], extras


def recent_alerts(business: Dict[str, Any], contact_id: Any, limit: int = LIMIT, *,
                  off: Optional[Iterable[str]] = None, fresh: bool = True) -> Optional[List[Dict[str, Any]]]:
    """This member's recent alerts, newest first, at most `limit`:
    [{"kind", "label", "title", "body", "when", "link"}]. `when` is the
    UTC ISO time it was sent; `link` a /my page or ''. `title` and `body`
    are the lock screen's words. None when a read failed. Never raises."""
    try:
        rows, _ = _collect(business, contact_id, limit, off=off, fresh=fresh)
        return rows
    except Exception:
        logger.warning("member alerts: the list was skipped", exc_info=True)
        return None


# ─── Seen, and the dot ────────────────────────────────────────────────

_DOT: Any = None


def _dot_kept():
    global _DOT
    if _DOT is None:
        import member_cache
        _DOT = member_cache.Kept("alert-dot", DOT_SECONDS, copy_value=False)
    return _DOT


def seen_at(business: Dict[str, Any], contact_id: Any) -> Optional[str]:
    """When this member last opened their alerts: an ISO time, '' when
    never, None when it can't be read (the table missing too)."""
    import church_threads as ct
    try:
        biz_id, cid = str(business.get("id") or ""), str(contact_id or "")
        if not UUID_RE.match(biz_id) or not UUID_RE.match(cid) or not ct.tables_ready():
            return None
        rows = _rows(f"/{ct.READS}?business_id=eq.{_q(biz_id)}&contact_id=eq.{_q(cid)}"
                     f"&thread=eq.{SEEN_THREAD}&select=read_at&limit=1")
        if rows is None:
            return None
        return _iso(rows[0].get("read_at")) if rows else ""
    except Exception:
        logger.warning("member alerts: the last look couldn't be read", exc_info=True)
        return None


def is_new(row: Dict[str, Any], seen: Optional[str]) -> bool:
    """Arrived after the member last opened the page (never, when that
    can't be told)."""
    if seen is None:
        return False
    when = _at(row.get("when"))
    last = _at(seen) if seen else None
    return when is not None and (last is None or when > last)


def alerts_unseen(business: Dict[str, Any], contact_id: Any) -> bool:
    """The bell's dot: something arrived since this member last opened
    their alerts. Kept DOT_SECONDS per member on this server copy; a miss
    is one round of reads side by side (their chats are kept longer).
    False when the switch is off, the seen record can't be kept (its table
    missing), or a read failed (a failure is never kept). Never raises."""
    try:
        if not switched_on():
            return False
        biz_id, cid = str((business or {}).get("id") or ""), str(contact_id or "")
        if not UUID_RE.match(biz_id) or not UUID_RE.match(cid):
            return False
        kept = _dot_kept()
        hit, got = kept.get((biz_id, cid))
        if hit:
            return bool(got)
        import church_threads as ct
        if not ct.tables_ready():
            return False
        rows, extras = _collect(business, cid, 1, fresh=False,
                                extra={"seen": lambda: seen_at(business, cid)})
        seen = extras.get("seen")
        if rows is None or seen is None:
            return False
        dot = bool(rows) and is_new(rows[0], seen)
        kept.put((biz_id, cid), dot, tag=biz_id)
        return dot
    except Exception:
        logger.warning("member alerts: the dot was skipped", exc_info=True)
        return False


def mark_seen(business: Dict[str, Any], contact_id: Any, now: Optional[datetime] = None) -> bool:
    """The member opened their alerts: everything up to now is seen. The
    dot goes at once on this server copy. Never raises; whether it saved."""
    import church_threads as ct
    try:
        biz_id, cid = str(business.get("id") or ""), str(contact_id or "")
        if not UUID_RE.match(biz_id) or not UUID_RE.match(cid):
            return False
        _dot_kept().put((biz_id, cid), False, tag=biz_id)
        if not ct.tables_ready():
            return False
        got = sb_clients.sb_post_as_service(
            f"/{ct.READS}?on_conflict=business_id,contact_id,thread",
            {"business_id": biz_id, "contact_id": cid, "thread": SEEN_THREAD,
             "read_at": (now or datetime.now(timezone.utc)).isoformat()},
            prefer="resolution=merge-duplicates,return=minimal")
        return got is not None
    except Exception:
        logger.warning("member alerts: the last look wasn't saved", exc_info=True)
        return False


def mark_seen_later(business: Dict[str, Any], contact_id: Any) -> None:
    """mark_seen off the page's path (the dot goes at once all the same)."""
    try:
        _dot_kept().put((str(business.get("id") or ""), str(contact_id or "")), False,
                        tag=str(business.get("id") or ""))
    except Exception:
        pass
    import member_push
    member_push._later(mark_seen, business, contact_id)


def forget() -> None:
    """For the tests."""
    for k in (_DOT, _CHATS):
        if k is not None:
            k.clear()


# ─── The church's clock ───────────────────────────────────────────────


def zone_of(business: Dict[str, Any]):
    """The church's own clock for the times (group_gatherings.zone), else
    PLATFORM_DEFAULT_TZ, else UTC. Never raises."""
    from zoneinfo import ZoneInfo
    try:
        import group_gatherings
        z = group_gatherings.zone(business)
        if z is not None:
            return z
    except Exception:
        logger.warning("member alerts: the church's clock couldn't be read", exc_info=True)
    try:
        name = (os.environ.get("PLATFORM_DEFAULT_TZ") or "").strip()
        return ZoneInfo(name) if name else timezone.utc
    except Exception:
        return timezone.utc


def when_label(iso: Any, zone, now: Optional[datetime] = None) -> str:
    """9:12 AM today, Yesterday, Fri this week, else Nov 3 (Nov 3, 2025 in
    another year), on the church's clock."""
    d = _at(iso)
    if d is None:
        return ""
    d = d.astimezone(zone)
    today = (now or datetime.now(timezone.utc)).astimezone(zone).date()
    days = (today - d.date()).days
    if days <= 0:
        return d.strftime("%I:%M %p").lstrip("0")
    if days == 1:
        return "Yesterday"
    if days < 7:
        return d.strftime("%a")
    return f"{d.strftime('%b')} {d.day}" + (f", {d.year}" if d.year != today.year else "")


# ─── The page's Recent section ────────────────────────────────────────

CSS = """
.al{margin-top:4px;}
.al .mp-sect{margin-top:22px;}
.al-list{list-style:none;margin:0;padding:0;border-top:1px solid var(--line);}
.al-row{display:grid;grid-template-columns:40px minmax(0,1fr) auto;gap:12px;align-items:center;padding:14px 0;
  border-bottom:1px solid var(--line);color:var(--fg);text-decoration:none;}
a.al-row:focus-visible{outline:2px solid var(--acc);outline-offset:2px;border-radius:8px;}
.al-ic{width:40px;height:40px;border-radius:50%;display:grid;place-items:center;color:var(--h-ink,var(--acc));background:var(--s1);}
.al-ic .mb-ic{width:18px;height:18px;}
.al-tx{min-width:0;}
.al-kind{display:block;font-size:10.5px;font-weight:650;line-height:1;letter-spacing:.12em;text-transform:uppercase;color:var(--fg3);}
.al-tx b{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;margin-top:5px;
  font-size:14.5px;font-weight:600;line-height:1.35;letter-spacing:-.01em;}
.al-sub{display:block;margin-top:2px;font-size:13px;line-height:1.35;color:var(--fg2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.al-time{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:500;line-height:1;color:var(--fg3);
  font-variant-numeric:tabular-nums;white-space:nowrap;}
.al-row.is-new .al-time{color:var(--acc);font-weight:650;}
.al-row.is-new .al-time::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--acc);}
.al-empty{margin:0;padding:18px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line);}
.al-empty b{display:block;font-size:15px;font-weight:650;}
.al-empty span{display:block;margin-top:3px;font-size:13px;color:var(--fg2);}
.al-vh{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;}
.al-next{margin-top:30px;}
"""


def _icon(kind: str) -> str:
    import member_app_ui as ui
    return ui.icon(LOOK.get(kind, ("h-brand", "bell"))[1], 18)


def render_recent(rows: Optional[List[Dict[str, Any]]], *, zone=None, seen: Optional[str] = None,
                  now: Optional[datetime] = None) -> str:
    """The Recent section: one row per alert (its kind's coloured icon, the
    kind, the lock screen's words, the time on the church's clock), each
    opening its page where it has one; "Nothing yet" when there's none. ''
    when the list couldn't be read: the page shows without it."""
    if rows is None:
        return ""
    try:
        return _render_recent(rows, zone or timezone.utc, seen, now)
    except Exception:
        logger.warning("member alerts: the list couldn't be drawn", exc_info=True)
        return ""


def _render_recent(rows: List[Dict[str, Any]], zone, seen: Optional[str], now: Optional[datetime]) -> str:
    if not rows:
        items = ('<p class="al-empty"><b>Nothing yet</b>'
                 '<span>When your church sends you something, it shows here.</span></p>')
    else:
        out = []
        for r in rows:
            kind = str(r.get("kind") or "")
            hue = LOOK.get(kind, ("h-brand", "bell"))[0]
            new = is_new(r, seen)
            sub = f'<span class="al-sub">{escape(r["body"])}</span>' if r.get("body") else ""
            flag = '<span class="al-vh">New, </span>' if new else ""
            inner = (f'<span class="al-ic {hue}" aria-hidden="true">{_icon(kind)}</span>'
                     f'<span class="al-tx"><span class="al-kind">{escape(r.get("label") or "")}</span>'
                     f'<b>{escape(r.get("title") or "")}</b>{sub}</span>'
                     f'<span class="al-time">{flag}'
                     f'{escape(when_label(r.get("when"), zone, now))}</span>')
            cls = "al-row is-new" if new else "al-row"
            link = str(r.get("link") or "")
            out.append(f'<li><a class="{cls}" href="{escape(link, quote=True)}">{inner}</a></li>' if link
                       else f'<li><div class="{cls}">{inner}</div></li>')
        items = f'<ul class="al-list">{"".join(out)}</ul>'
    import member_lumen
    if member_lumen.page():
        # The new look's section heading (member_lumen_people), NEW while
        # something here is new.
        new = any(is_new(r, seen) for r in rows)
        chip = ' <span class="lm-new" aria-hidden="true">NEW</span>' if new else ""
        return (f'<style>{CSS}</style><section class="al" aria-labelledby="al-recent">'
                f'<div class="lm-sec"><h2 id="al-recent" class="lm-h2">Recent{chip}</h2></div>{items}</section>')
    return (f'<style>{CSS}</style><section class="al" aria-labelledby="al-recent">'
            f'<h2 id="al-recent" class="mp-sect">Recent</h2>{items}</section>')
