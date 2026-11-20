"""guest_replies.py — a guest's reply reaches their caller, and the automatic
texts wait for a person (the Welcome Path, step 4).

Kevin, 2026-11-20, on the Welcome Path mock (canvas WmRiSK8seJky8pJUK5nztE:
"The guest's phone", "The caller's phone", and the rule "A reply holds the
automatic texts until a person answers"), then "build". Before this, a
guest's answer to the Monday note landed in the Text room, where anyone or
no one might see it, and the next automatic text went out anyway.

Everything here is behind guest_path.switched_on(biz). Off, nothing runs.

A REPLY (on_reply; sms_routing.route_inbound hands it over on its
own-number path, in a thread of its own, after the text is recorded): a
plain text to the church's own number from a guest on the Welcome Path
(contacts.metadata.new_here.texted_at within PATH_DAYS, the path not ended).
Never STOP, START, HELP, GIVE, DAILY, the church's New here word or its
texting keyword. It:
  * holds their automatic texts: metadata.new_here.hold = true and
    hold_since (the first reply still waiting; a second one keeps it),
    beside every other key (new_here.run_scheduled reads `hold`)
  * notes it on their open guest follow-up, "Answered the church's text"
    with the reply, so the caller can answer it. The words stay out of
    church_history and Chief's feed (its lines say only that a guest
    answered)
  * tells whoever has the guest: their caller, an office login by a push
    and an email (guest_calls.tell_login) that open the guest's texts, or a
    member by email with the reply, the guest's number and their Lead tab;
    no caller, whoever does First-time guests (guest_calls.first_guests_login);
    nobody who can be told, the office's alert. In the church's quiet hours
    (member_push.quiet_hour) the telling waits for the sweep, as the
    hand-off does. At most one alert a guest every BURST: the telling is
    claimed in the guest's own row first (hold_tell, hold_told_at), so two
    replicas never both send.

ANSWERED (on_person_text, on_outcome): a text a person from the church sends
the guest (POST /sms/send, the Text room; Chief's texts and the automatic
ones never count), or the caller logging Talked or Left a message on the
guest's follow-up (church_follow_up._note), lets the texts go on: hold
false, and "Answered by <name>." on the follow-up.

STILL WAITING (sweep, every 10 minutes, on the scheduler): a reply the
quiet hours held is told; a day after the reply the caller is reminded,
once; three days after, the office's alert, once. A hold never ends by
itself: only a person answering ends it.

The guest's keys (contacts.metadata.new_here, no migration):
  hold, hold_since          a reply waits on a person
  hold_reply_at             their latest reply
  hold_tell, hold_told_at   an alert is owed / when the last one went
  hold_reminded_at          the day-later reminder went (this hold)
  hold_alerted_at           the three-day office alert went (this hold)
  hold_answered_at, _by     who let the texts go on, and when
  hold_v                    this module's write count: every write is a
                            compare-and-swap on it, so a reply, a sweep and
                            an answer on different replicas never undo each
                            other (a write that loses reads again)
A read that fails decides nothing: no hold, no clearing, nobody told wrong.
"""
from __future__ import annotations

import asyncio
import logging
import re
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

import guest_path
import sb_clients

logger = logging.getLogger(__name__)

PATH_DAYS = 42                      # the path's six weeks
BURST = timedelta(minutes=10)       # at most one alert a guest in this
REMIND_AFTER = timedelta(hours=24)
OFFICE_AFTER = timedelta(days=3)
QUOTE_PUSH = 90
QUOTE_MAIL = 600
NOTE_MAX = 1500
TRIES = 3
TEXT_NAV = "operate:sms"            # the Text room; ":<contact id>" opens their texts
HELD_PAGE = 500                     # held guests read a page at a time
HELD_MAX = 5000                     # ... and at most this many a church a sweep


class Unread(Exception):
    """A read or write that failed: decide nothing."""


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _plain(v: Any) -> str:
    return " ".join(str(v or "").split())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _rows(path: str) -> Optional[List[Dict[str, Any]]]:
    rows = sb_clients.sb_get_as_service(path)
    return rows if isinstance(rows, list) else None


def _need(path: str) -> List[Dict[str, Any]]:
    rows = _rows(path)
    if rows is None:
        raise Unread(path.split("?")[0])
    return rows


def _trim(text: Any, n: int) -> str:
    t = _plain(text)
    if len(t) <= n:
        return t
    cut = t[:n].rsplit(" ", 1)[0] if " " in t[:n] else t[:n]
    return cut.rstrip(",.;:!?") + "…"


# ─── Off the request path ─────────────────────────────────────────────

def later(fn: Callable[..., Any], *args: Any) -> None:
    """Run fn(*args) in a thread of its own: never waits, never raises. The
    switch off: nothing starts."""
    try:
        if guest_path.mode() == "off":
            return
        threading.Thread(target=_quietly, args=(fn, *args), daemon=True, name="guest-replies").start()
    except Exception:  # noqa: BLE001
        logger.info("guest replies: a hand-off didn't start", exc_info=True)


def _quietly(fn: Callable[..., Any], *args: Any) -> None:
    try:
        fn(*args)
    except Exception as e:  # noqa: BLE001
        print(f"[guest_replies] {getattr(fn, '__name__', 'work')} stopped ({type(e).__name__})", flush=True)


# ─── Who is a guest on the path ───────────────────────────────────────

def on_path(mine: Dict[str, Any], now: datetime) -> bool:
    """Started within PATH_DAYS and not ended (guest_path_weeks: path.ended
    on this path's own record, e.g. they joined a group)."""
    start = _parse(mine.get("texted_at"))
    if not start or start > now + timedelta(minutes=5) or now - start > timedelta(days=PATH_DAYS):
        return False
    path = mine.get("path") if isinstance(mine.get("path"), dict) else {}
    if path.get("ended") and str(path.get("for") or "") == str(mine.get("texted_at") or ""):
        return False
    return not (mine.get("ended") or mine.get("ended_at"))


_LETTERS = re.compile(r"[^A-Za-z ]")


def is_keyword(body: str, *words: str) -> bool:
    """STOP, START, HELP (or a text that starts with one), GIVE, DAILY, or
    one of `words` (the church's New here word, its texting keyword) alone."""
    import devotional_daily
    import sms_routing as sr
    tokens = (body or "").split()
    if tokens and tokens[0].upper() in sr.RESERVED_WORDS:
        return True
    one = _LETTERS.sub(" ", body or "").split()
    if len(one) != 1:
        return False
    w = one[0].upper()
    return w in sr.RESERVED_WORDS or w in sr.GIVE_WORDS or w in devotional_daily.DAILY_WORDS or (
        w in {str(x or "").upper() for x in words if x})


def _business(biz: str) -> Optional[Dict[str, Any]]:
    rows = _rows(f"/businesses?id=eq.{_q(biz)}&select=id,name,type,owner_id,settings&limit=1")
    if rows is None:
        raise Unread("businesses")
    return rows[0] if rows else None


def _is_church(business: Dict[str, Any]) -> bool:
    import church_follow_up as cfu
    return cfu.is_church(business)


def _own_words(business: Dict[str, Any], body: str) -> bool:
    """The church's own words for a one-word text: New here's word (even
    while New here is off) and its texting keyword. Raises on a failed read."""
    import new_here
    word = new_here.settings_of(business).get("word") or ""
    if is_keyword(body, word):
        return True
    tok = re.sub(r"[^A-Za-z0-9]", "", body or "").upper()
    if len((body or "").split()) != 1 or not 3 <= len(tok) <= 20:
        return False
    rows = _need(f"/sms_keywords?business_id=eq.{_q(business['id'])}&keyword=eq.{_q(tok)}&select=keyword&limit=1")
    return bool(rows)


def _by_phone(biz: str, phone: str, *, sel: str = "select=id,name,phone,metadata,created_at") -> List[Dict[str, Any]]:
    """The church's contacts for this number: exact, else its last ten
    digits (sms_service._find_contact_by_phone's match). Raises on a failed read."""
    rows = _need(f"/contacts?business_id=eq.{_q(biz)}&phone=eq.{_q(phone)}&{sel}&order=created_at.asc&limit=5")
    if rows:
        return rows
    last10 = "".join(ch for ch in str(phone or "") if ch.isdigit())[-10:]
    if len(last10) != 10:
        return []
    return _need(f"/contacts?business_id=eq.{_q(biz)}&phone=like.%25{last10}&{sel}&order=created_at.asc&limit=5")


def _guest(biz: str, phone: str, now: datetime) -> Optional[Dict[str, Any]]:
    """The guest on the path for this number (the latest path when two
    records share it), else None."""
    on = [r for r in _by_phone(biz, phone) if on_path(guest_path.guest_meta(r), now)]
    return max(on, key=lambda r: str(guest_path.guest_meta(r).get("texted_at") or "")) if on else None


def _follow_up(biz: str, cid: str) -> Optional[Dict[str, Any]]:
    """Their newest guest follow-up that's still with someone (open) or
    handed back. Raises on a failed read."""
    rows = _need(f"/church_follow_ups?business_id=eq.{_q(biz)}&contact_id=eq.{_q(cid)}"
                 "&status=in.(open,handed_back)"
                 "&select=id,contact_id,leader_contact_id,leader_role,assigned_by,card_key,path_kind,status,created_at"
                 "&order=created_at.desc&limit=20")
    mine = sorted((r for r in rows if guest_path.is_guest_follow_up(r)),
                  key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return mine[0] if mine else None


# ─── The guest's keys: compare-and-swap on hold_v ─────────────────────

def _change(biz: str, cid: str, fn: Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]
            ) -> Tuple[Dict[str, Any], Dict[str, Any], bool]:
    """Read the guest's new_here keys, let fn change them (None: nothing to
    change), and save them only if nobody else wrote them in between; a lost
    race reads again. (before, after, wrote). Raises Unread when the guest
    can't be read or saved."""
    for _ in range(TRIES):
        rows = _need(f"/contacts?id=eq.{_q(cid)}&business_id=eq.{_q(biz)}&select=id,metadata&limit=1")
        if not rows:
            raise Unread("contact gone")
        meta = rows[0].get("metadata") if isinstance(rows[0].get("metadata"), dict) else {}
        mine = dict(meta.get("new_here")) if isinstance(meta.get("new_here"), dict) else {}
        new = fn(dict(mine))
        if new is None:
            return mine, mine, False
        try:
            v = int(mine.get("hold_v") or 0)
        except (TypeError, ValueError):
            v = 0
        new["hold_v"] = v + 1
        guard = f"&metadata->new_here->>hold_v=eq.{v}" if mine.get("hold_v") not in (None, "") else \
            "&metadata->new_here->>hold_v=is.null"
        saved = sb_clients.sb_patch_as_service(
            f"/contacts?id=eq.{_q(cid)}&business_id=eq.{_q(biz)}{guard}", {"metadata": {**meta, "new_here": new}})
        if isinstance(saved, list) and saved:
            return mine, new, True
        if not isinstance(saved, list):
            raise Unread("contact write")
    raise Unread("contact busy")


def _held(now: datetime) -> Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]:
    def go(m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not on_path(m, now):
            return None
        out = dict(m)
        if not m.get("hold"):
            out.update(hold=True, hold_since=_iso(now))
            for k in ("hold_reminded_at", "hold_alerted_at", "hold_answered_at", "hold_answered_by"):
                out.pop(k, None)
        out.update(hold_reply_at=_iso(now), hold_tell=True)
        return out
    return go


def _claim_tell(now: datetime) -> Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]:
    def go(m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not (m.get("hold") and m.get("hold_tell")):
            return None
        told = _parse(m.get("hold_told_at"))
        if told and now - told < BURST:
            return None
        return {**m, "hold_tell": False, "hold_told_at": _iso(now)}
    return go


def _unclaim_tell(stamp: str, prev: Any) -> Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Nothing went: the alert is owed again (the next sweep tries)."""
    def go(m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if m.get("hold_told_at") != stamp or not m.get("hold"):
            return None
        out = {**m, "hold_tell": True}
        if prev:
            out["hold_told_at"] = prev
        else:
            out.pop("hold_told_at", None)
        return out
    return go


def _claim_stamp(key: str, since: str, now: datetime, also: Tuple[str, ...] = ()
                 ) -> Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]:
    def go(m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not m.get("hold") or m.get(key) or str(m.get("hold_since") or "") != since:
            return None
        out = {**m, key: _iso(now)}
        for k in also:
            out.setdefault(k, _iso(now))
        return out
    return go


def _unclaim_stamp(key: str, stamp: str) -> Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]:
    def go(m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if m.get(key) != stamp:
            return None
        out = dict(m)
        out.pop(key, None)
        return out
    return go


def _let_go(now: datetime, name: str) -> Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]:
    def go(m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not m.get("hold"):
            return None
        out = dict(m)
        for k in ("hold_since", "hold_tell", "hold_reminded_at", "hold_alerted_at"):
            out.pop(k, None)
        out.update(hold=False, hold_answered_at=_iso(now), hold_answered_by=_plain(name)[:120])
        return out
    return go


# ─── The words ────────────────────────────────────────────────────────

def guest_name(contact: Dict[str, Any]) -> str:
    import new_here
    import text_room
    name = _plain(contact.get("name"))
    if name and not text_room.nameless(name):
        return name[:80]
    pretty = new_here.pretty_phone(str(contact.get("phone") or ""))
    return f"A guest at {pretty}" if pretty else "A guest"


def when_words(dt: Optional[datetime], business: Dict[str, Any], now: datetime) -> str:
    """"today", "yesterday", "on Monday" on the church's clock."""
    if not dt:
        return "recently"
    import new_here
    tz = new_here.tz_of(business)
    d, today = dt.astimezone(tz).date(), now.astimezone(tz).date()
    if d == today:
        return "today"
    if d == today - timedelta(days=1):
        return "yesterday"
    return f"on {dt.astimezone(tz).strftime('%A')}"


def reply_words(pname: str, reply: str, first: str, *, theirs: bool, member: bool = False,
                number: str = "") -> Dict[str, str]:
    """A reply has come in. `theirs`: to the guest's own caller; else to
    whoever does First-time guests (nobody has the call)."""
    q = _trim(reply, QUOTE_PUSH)
    who = "you reply" if theirs else "someone replies"
    lines = [f"Hi {first}," if first else "Hello,", f"{pname} answered the church’s text:"]
    if reply:
        lines.append(f"“{_trim(reply, QUOTE_MAIL)}”")
    if member:
        lines.append((f"Their number is {number}. " if number else "")
                     + "Call or text them yourself. Their automatic texts are on hold until someone answers: "
                       "when you’ve reached them, note it on your Lead tab (Talked or Left a message) and the "
                       "texts go on.")
    else:
        lines.append(("" if theirs else "No one has their welcome call yet. ")
                     + "Their automatic texts are on hold until someone from the church answers. Open their "
                       "texts to reply yourself.")
    return {
        "title": f"{pname} answered the church’s text",
        "body": (f"“{q}” " if q else "") + f"Their texts are on hold until {who}.",
        "subject": f"{pname} answered the church’s text",
        "text": "\n\n".join(lines),
        "lines": lines,
    }


def remind_words(pname: str, reply: str, first: str, when: str, *, theirs: bool, member: bool = False,
                 number: str = "") -> Dict[str, str]:
    q = _trim(reply, QUOTE_PUSH)
    who = "you reply" if theirs else "someone replies"
    lines = [f"Hi {first}," if first else "Hello,",
             f"{pname} answered the church’s text {when}, and it’s still waiting for an answer:"]
    if reply:
        lines.append(f"“{_trim(reply, QUOTE_MAIL)}”")
    if member:
        lines.append((f"Their number is {number}. " if number else "")
                     + "When you’ve reached them, note it on your Lead tab (Talked or Left a message) and their "
                       "automatic texts go on.")
    else:
        lines.append("Their automatic texts are on hold until someone from the church answers. Open their texts "
                     "to reply yourself.")
    return {
        "title": f"{pname} is still waiting on a reply",
        "body": (f"“{q}” " if q else "") + f"They texted {when}. Their texts are on hold until {who}.",
        "subject": f"{pname} is still waiting on a reply",
        "text": "\n\n".join(lines),
        "lines": lines,
    }


def office_words(pname: str, when: str, caller: str, *, days: int = 0) -> Dict[str, str]:
    """The office's alert. Never the guest's words."""
    has = f"{caller} has their call." if caller else "No one has their call yet."
    if days:
        return {"title": f"{pname} has waited three days for a reply",
                "body": (f"They answered the church’s text {when}, and no one has answered yet. Their automatic "
                         f"texts are on hold until someone does. {has} Open their texts in Text to reply.")}
    return {"title": f"{pname} answered the church’s text",
            "body": (f"Their automatic texts are on hold until someone from the church answers. {has} "
                     "Open their texts in Text to reply.")}


# ─── Telling ──────────────────────────────────────────────────────────

def text_nav(cid: str) -> str:
    return f"{TEXT_NAV}:{cid}"


def text_link(cid: str) -> str:
    import app_base
    return f"{app_base.app_base_url()}/?nav={text_nav(cid)}"


def who_hears(business: Dict[str, Any], fu: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Whoever is told about this guest: their caller (an office login, or a
    member), else whoever does First-time guests, else the office. Raises
    when it can't be read."""
    import guest_calls as gc
    from fastapi import HTTPException
    ch = gc._church(business)
    try:
        lid = str((fu or {}).get("leader_contact_id") or "") if (fu or {}).get("status") == "open" else ""
        if lid:
            p = _need(f"/contacts?business_id=eq.{_q(ch.b)}&id=eq.{_q(lid)}&select=id,name,email&limit=1")
            name = _plain((p[0] if p else {}).get("name")) or "Their caller"
            uid = gc.logins(ch).get(lid)
            if uid:
                return {"kind": "login", "uid": uid, "name": name, "contact_id": lid, "ch": ch, "theirs": True}
            if p:
                return {"kind": "member", "name": name, "email": _plain(p[0].get("email")), "contact_id": lid,
                        "ch": ch, "theirs": True}
        uid = gc.first_guests_login(ch, {})
        if uid:
            return {"kind": "first_guests", "uid": uid, "name": ch.login_name(uid), "ch": ch, "theirs": False}
    except HTTPException as e:
        raise Unread("who") from e
    return {"kind": "office", "name": "", "ch": ch, "theirs": False}


def _first_name(name: str) -> str:
    n = _plain(name)
    if not n or n in ("The owner", "An office login", "Their caller"):
        return ""
    return n.split(" ")[0]


def tell(business: Dict[str, Any], contact: Dict[str, Any], fu: Optional[Dict[str, Any]], *, what: str,
         reply: str, now: datetime) -> bool:
    """One alert about this guest to whoever hears it (what: reply | remind).
    True when it went (or the office's alert stands). Raises Unread when who
    to tell couldn't be read."""
    import church_follow_up as cfu
    import guest_calls as gc
    import new_here
    biz, cid = str(business["id"]), str(contact["id"])
    who = who_hears(business, fu)
    pname = guest_name(contact)
    meta = guest_path.guest_meta(contact)
    when = when_words(_parse(meta.get("hold_since")) or now, business, now)
    first = _first_name(who.get("name") or "")
    number = new_here.pretty_phone(str(contact.get("phone") or ""))
    member = who["kind"] == "member"

    def words() -> Dict[str, str]:
        if what == "remind":
            return remind_words(pname, reply, first, when, theirs=who["theirs"], member=member, number=number)
        return reply_words(pname, reply, first, theirs=who["theirs"], member=member, number=number)

    ref = f"gr-{what}-{cid}-{_iso(now)}"
    if who["kind"] in ("login", "first_guests"):
        ctx = SimpleNamespace(ch=who["ch"], conf=gc.conf_for(business))
        if gc.tell_login(ctx, who["uid"], words(), ref, nav=text_nav(cid), link=text_link(cid),
                         label="Open their texts"):
            return True
    elif member and who.get("email"):
        w = words()
        origin = cfu.site_origin(biz)
        import html
        body = cfu._mail_html([html.escape(line) for line in w["lines"]], f"{origin}/my/lead" if origin else "",
                              "Open your Lead tab")
        if asyncio.run(cfu._email(business, who["email"], who["name"], w["subject"], body, ref)):
            return True
    # Nobody who could be told: the office's alert (deduplicated for the hold).
    caller = who["name"] if who.get("theirs") else ""
    ow = office_words(pname, when, caller)
    if member and not who.get("email"):
        ow["body"] = ow["body"].replace(f"{caller} has their call.", f"{caller} has their call, with no email on file.")
    return asyncio.run(gc.office_alert(biz, ow["title"], ow["body"],
                                       f"guest-reply-{'' if what == 'reply' else what + '-'}{cid}-"
                                       f"{meta.get('hold_since') or ''}", cid,
                                       action="Open Text"))


def _history(biz: str, fu: Optional[Dict[str, Any]], verb: str, line: str) -> None:
    if not fu:
        return
    import church_history
    church_history.note(biz, verb, line, target_type="church_follow_up", target_id=fu["id"])


def _note(biz: str, fu: Optional[Dict[str, Any]], body: str) -> bool:
    """A note on the guest's follow-up. False (and said in the log) when it
    didn't save: the alert still carries the words, and the text is in Text."""
    if not fu:
        return False
    import church_follow_up as cfu
    if cfu._note(biz, str(fu["id"]), "chief", "note", body):
        return True
    print(f"[guest_replies] a note didn't save (business {biz[:8]}, follow-up {str(fu['id'])[:8]})", flush=True)
    return False


def _tell_claimed(business: Dict[str, Any], contact: Dict[str, Any], fu: Optional[Dict[str, Any]], reply: str,
                  now: datetime) -> bool:
    """Claim the owed alert (one replica wins, one alert a BURST), then send
    it; nothing went: it's owed again."""
    biz, cid = str(business["id"]), str(contact["id"])
    before, after, wrote = _change(biz, cid, _claim_tell(now))
    if not wrote:
        return False
    stamp = after["hold_told_at"]
    try:
        ok = tell(business, {**contact, "metadata": {"new_here": after}}, fu, what="reply", reply=reply, now=now)
    except Unread:
        ok = False
    if not ok:
        try:
            _change(biz, cid, _unclaim_tell(stamp, before.get("hold_told_at")))
        except Unread:
            pass
        return False
    return True


# ─── A guest texts back ───────────────────────────────────────────────

def on_reply(business_id: Any, phone: Any, body: Any, now: Optional[datetime] = None) -> str:
    """A text to the church's own number (sms_routing, routed_direct). What
    happened, in a word: held, told, keyword, not_a_guest, off, unread, ...
    Never raises."""
    biz = str(business_id or "")
    try:
        return _on_reply(biz, str(phone or ""), " ".join(str(body or "").split()), now or _now())
    except Unread as e:
        print(f"[guest_replies] a reply decided nothing: {e} unread (business {biz[:8]})", flush=True)
        return "unread"
    except Exception as e:  # noqa: BLE001
        print(f"[guest_replies] a reply was passed over ({type(e).__name__}, business {biz[:8]})", flush=True)
        return "error"


def _on_reply(biz: str, phone: str, text: str, now: datetime) -> str:
    if not biz or not phone or not text:
        return "nothing"
    if is_keyword(text):
        return "keyword"
    if not guest_path.switched_on(biz):
        return "off"
    business = _business(biz)
    if not business or not _is_church(business):
        return "not_church"
    if _own_words(business, text):
        return "keyword"
    guest = _guest(biz, phone, now)
    if not guest:
        return "not_a_guest"
    cid = str(guest["id"])
    before, after, wrote = _change(biz, cid, _held(now))
    if not wrote or not after.get("hold"):
        return "not_a_guest"
    try:
        fu = _follow_up(biz, cid)
    except Unread:
        # Held, and nobody told wrong: the sweep tells once it can read.
        return "held"
    _note(biz, fu, f"Answered the church’s text: “{_trim(text, NOTE_MAX)}”")
    if not before.get("hold"):
        _history(biz, fu, "church:guest_replied",
                 "A guest answered the church’s text. Their automatic texts wait until someone answers")
    import member_push
    if member_push.quiet_hour(business, now):
        return "held"
    contact = {**guest, "metadata": {"new_here": after}}
    return "told" if _tell_claimed(business, contact, fu, text, now) else "held"


# ─── A person answers ─────────────────────────────────────────────────

def answered(business: Dict[str, Any], cid: str, name: str, *, now: Optional[datetime] = None,
             fu: Optional[Dict[str, Any]] = None, how: str = "") -> str:
    """Let the guest's texts go on, with a note. answered | not_held."""
    now = now or _now()
    biz = str(business["id"])
    _, _, wrote = _change(biz, cid, _let_go(now, name))
    if not wrote:
        return "not_held"
    if fu is None:
        try:
            fu = _follow_up(biz, cid)
        except Unread:
            fu = None
    _note(biz, fu, f"Answered by {name}." if name else (how or "Answered."))
    _history(biz, fu, "church:guest_answered",
             "Someone answered a guest’s text. Their automatic texts go on")
    return "answered"


def on_person_text(business_id: Any, contact_id: Any, phone: Any, user_id: Any) -> str:
    """A person from the church texted someone from Text (POST /sms/send,
    after it went). A guest whose reply was waiting is answered. Never raises."""
    biz = str(business_id or "")
    try:
        if not biz or not guest_path.switched_on(biz):
            return "off"
        business = _business(biz)
        if not business or not _is_church(business):
            return "not_church"
        ids: List[str] = []
        if contact_id:
            ids = [str(contact_id)]
        elif phone:
            import sms_service
            number = sms_service.normalize_phone(str(phone)) or str(phone)
            ids = [str(r["id"]) for r in _by_phone(biz, number) if guest_path.guest_meta(r).get("hold")]
        if not ids:
            return "not_held"
        name = ""
        try:
            import church_over
            name = church_over.Church(business).login_name(str(user_id or ""))
        except Exception:  # noqa: BLE001 — the hold lets go without a name
            name = ""
        name = {"The owner": "the owner", "An office login": ""}.get(name, name)
        out = "not_held"
        for cid in ids:
            got = answered(business, cid, name, how="Answered in Text.")
            out = got if got == "answered" else out
        return out
    except Unread as e:
        print(f"[guest_replies] a text from the church decided nothing: {e} unread (business {biz[:8]})", flush=True)
        return "unread"
    except Exception as e:  # noqa: BLE001
        print(f"[guest_replies] a text from the church was passed over ({type(e).__name__})", flush=True)
        return "error"


def on_outcome(business_id: Any, follow_up_id: Any, who: str = "") -> str:
    """The caller logged Talked or Left a message (church_follow_up._note).
    A guest whose reply was waiting is answered. Never raises."""
    biz = str(business_id or "")
    try:
        if not biz or not guest_path.switched_on(biz):
            return "off"
        rows = _need(f"/church_follow_ups?id=eq.{_q(follow_up_id)}&business_id=eq.{_q(biz)}"
                     "&select=id,contact_id,leader_contact_id,leader_role,assigned_by,card_key,path_kind,status"
                     "&limit=1")
        if not rows or not guest_path.is_guest_follow_up(rows[0]):
            return "not_a_guest"
        business = _business(biz)
        if not business or not _is_church(business):
            return "not_church"
        return answered(business, str(rows[0]["contact_id"]), _plain(who), fu=rows[0],
                        how="Answered by their caller.")
    except Unread as e:
        print(f"[guest_replies] an outcome decided nothing: {e} unread (business {biz[:8]})", flush=True)
        return "unread"
    except Exception as e:  # noqa: BLE001
        print(f"[guest_replies] an outcome was passed over ({type(e).__name__})", flush=True)
        return "error"


# ─── Still waiting: the sweep ─────────────────────────────────────────

def _last_reply(biz: str, cid: str) -> str:
    rows = _need(f"/sms_messages?business_id=eq.{_q(biz)}&contact_id=eq.{_q(cid)}&direction=eq.inbound"
                 "&select=message,created_at&order=created_at.desc&limit=1")
    return str(rows[0].get("message") or "") if rows else ""


def _burst_over(mine: Dict[str, Any], now: datetime) -> bool:
    told = _parse(mine.get("hold_told_at"))
    return not told or now - told >= BURST


def sweep_one(business: Dict[str, Any], contact: Dict[str, Any], now: datetime, quiet: Callable[[], bool],
              stats: Dict[str, int]) -> None:
    """One held guest: an owed alert, the day-later reminder, the three-day
    office alert. One of them a sweep."""
    biz, cid = str(business["id"]), str(contact["id"])
    mine = guest_path.guest_meta(contact)
    if not mine.get("hold"):
        return
    stats["waiting"] = stats.get("waiting", 0) + 1
    since_s = str(mine.get("hold_since") or "")
    since = _parse(since_s)
    if mine.get("hold_tell") and _burst_over(mine, now):
        if quiet():
            return
        fu = _follow_up(biz, cid)
        if _tell_claimed(business, contact, fu, _last_reply(biz, cid), now):
            stats["told"] = stats.get("told", 0) + 1
        return
    if not since:
        return
    if now - since >= OFFICE_AFTER and not mine.get("hold_alerted_at"):
        fu = _follow_up(biz, cid)
        _, after, wrote = _change(biz, cid, _claim_stamp("hold_alerted_at", since_s, now, ("hold_reminded_at",)))
        if not wrote:
            return
        caller = ""
        try:
            who = who_hears(business, fu)
            caller = who["name"] if who.get("theirs") else ""
        except Unread:
            caller = ""
        ow = office_words(guest_name(contact), when_words(since, business, now), caller, days=3)
        import guest_calls as gc
        if asyncio.run(gc.office_alert(biz, ow["title"], ow["body"], f"guest-reply-waited-{cid}-{since_s}", cid,
                                       action="Open Text")):
            _history(biz, fu, "church:guest_reply_late",
                     "A guest’s text has waited three days for an answer. Asked the office to answer it")
            stats["office"] = stats.get("office", 0) + 1
        else:
            _change(biz, cid, _unclaim_stamp("hold_alerted_at", after["hold_alerted_at"]))
        return
    if now - since >= REMIND_AFTER and not mine.get("hold_reminded_at") and _burst_over(mine, now):
        if quiet():
            return
        fu = _follow_up(biz, cid)
        reply = _last_reply(biz, cid)
        _, after, wrote = _change(biz, cid, _claim_stamp("hold_reminded_at", since_s, now))
        if not wrote:
            return
        try:
            ok = tell(business, contact, fu, what="remind", reply=reply, now=now)
        except Unread:
            ok = False
        if ok:
            _history(biz, fu, "church:guest_reply_late",
                     "A guest’s text has waited a day for an answer. Reminded their caller")
            stats["reminded"] = stats.get("reminded", 0) + 1
        else:
            _change(biz, cid, _unclaim_stamp("hold_reminded_at", after["hold_reminded_at"]))


def held_guests(biz: str) -> Optional[List[Dict[str, Any]]]:
    """The church's held guests with something still to do (an alert owed,
    or the three-day alert not yet raised), a page at a time. A hold that has
    had everything waits for a person without being read again. None when a
    page couldn't be read."""
    out: List[Dict[str, Any]] = []
    while len(out) < HELD_MAX:
        page = _rows(f"/contacts?business_id=eq.{_q(biz)}&metadata->new_here->>hold=eq.true"
                     "&or=(metadata->new_here->>hold_tell.eq.true,metadata->new_here->>hold_alerted_at.is.null)"
                     f"&select=id,name,phone,metadata&order=created_at.asc,id.asc&limit={HELD_PAGE}&offset={len(out)}")
        if page is None:
            return None
        out += page
        if len(page) < HELD_PAGE:
            break
    return out


def sweep(now: Optional[datetime] = None) -> Dict[str, int]:
    """Every 10 minutes (the scheduler): each church with its own number and
    the Welcome Path on, each guest whose reply waits. A church that can't
    be read is passed over; one guest never stops the rest."""
    stats = {"churches": 0, "waiting": 0, "told": 0, "reminded": 0, "office": 0}
    if guest_path.mode() == "off":
        return stats
    now = now or _now()
    nums = _rows("/sms_numbers?status=eq.active&select=business_id&limit=2000")
    if nums is None:
        print("[guest_replies] sweep skipped: the numbers couldn't be read", flush=True)
        return stats
    ids = sorted({str(n["business_id"]) for n in nums if n.get("business_id")})
    try:
        import sample_church
        ids = [str(b) for b in sample_church.drop_samples(ids)]
    except Exception:  # noqa: BLE001
        pass
    import member_push
    for biz in ids:
        try:
            if not guest_path.switched_on(biz):
                continue
            business = _business(biz)
            if not business or not _is_church(business):
                continue
            held = held_guests(biz)
            if held is None:
                continue
            stats["churches"] += 1
            memo: Dict[str, bool] = {}

            def quiet(b: Dict[str, Any] = business) -> bool:
                if "q" not in memo:
                    memo["q"] = bool(member_push.quiet_hour(b, now))
                return memo["q"]
            for c in held:
                try:
                    sweep_one(business, c, now, quiet, stats)
                except Exception as e:  # noqa: BLE001 — one guest never stops the rest
                    print(f"[guest_replies] a waiting guest was passed over ({type(e).__name__}, business {biz[:8]})",
                          flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[guest_replies] a church was passed over ({type(e).__name__}, business {biz[:8]})", flush=True)
    if stats["told"] or stats["reminded"] or stats["office"]:
        print(f"[guest_replies] sweep {stats}", flush=True)
    return stats
