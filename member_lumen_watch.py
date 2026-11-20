"""member_lumen_watch.py — Watch in the member app's new look (Look 5.1).

Kevin, 2026-11-20, on the Look 5.1 mock: "this is awesome. much better
design. lets build this including the new still to build!" and, about the
media pages, "make sure we put full thought on flow and function so what i
am seeing is actually how it works." Who sees it is member_lumen.py
(MEMBER_LUMEN); the look is member_lumen_ui.py. These pages read the same
library today's Watch reads (member_portal_sermons.load_library: published
messages and the series); the mock's church is made up, so nothing here is.

WATCH (/my/sermons). The "Watch" title, then Messages | Series (two links:
/my/sermons and ?view=series, so it works without a script).
  Messages: the latest message edge to edge on a rounded card (its art, the
  kicker "Latest · <series>, part n", the title in serif, speaker ·
  scripture · how long it runs when this member's phone has played it);
  Watch, Listen (only with an audio file), Share and Save under it; "Pick up
  where you left off" (messages this member started and hasn't finished,
  newest first, each with how far in and the minutes left); "Saved" (what
  they saved); "Every message" (a thumbnail with how long it runs once they
  have played it, the title, speaker · scripture · date; the first twelve,
  then "See all"); then Watch live: the church's weekly service time with
  Add to calendar when the office set it (check-in's service day and time,
  church_checkin_settings), else the next gathering the way today's row
  says it. While the church is live, Live now sits at the top instead.
  Series: the series two across as posters (the art the app already makes:
  member_portal_sermons._art), each with when it ran and how many messages.

A MESSAGE (/my/sermons/<id>). The player edge to edge with a round Back on
it: the video in its own player (YouTube, Vimeo, Loom, Facebook or our own
recording: sermons_public.player_html's), or, with Listen or a message that
only has audio, our audio player (play, back and forward 15 seconds, the
scrubber with both times, the phone's lock-screen controls). Under it
"<series> · Part n of m", the title in serif, speaker · scripture · date;
Listen (or Video), Share, Save and Give (the church's own Give) four
across; then About (the summary and "Read <passage>", which opens the
Bible reader there), Discuss (the questions numbered, and "Talk about it in
<group>" when the member is in a group whose chat is open to them) and In
this series (every part with how far they got, a check when watched,
Playing on this one). A tab with nothing in it isn't drawn.

A SERIES (/my/sermons?series=<id>). Its art big at the top with Back, the
kicker "Series · <when it ran>", the title in serif, the description, then
Keep watching part n (the part they're in the middle of, else the next one
they haven't watched) or Play part 1, Share, and every part.

PICK UP WHERE YOU LEFT OFF. The player tells us where the member is: our
audio player directly, YouTube and Vimeo through their players' own
messages (Loom, Facebook and our relay recordings don't say, so those
aren't remembered). The page saves it on pause, when the page is hidden
and at most once a minute while it plays (POST /my/sermons/progress), on
the member's own record: contacts.metadata.member_watch.p = {sermon id:
[seconds in, length, when (unix, the server's clock), "v" or "a"]}, the
last 20 (no migration). It is written like the member's Look
(member_lumen_look.save): the record's updated_at guards an office edit at
the same moment, only the signed-in member's own row, same-origin, its own
rate limit (rate_limit "member_watch"). Pages read it from the record the
session already reads (member_portal.contacts_for_email and
contacts_for_phone select watch:metadata->member_watch): no new read. That
record is kept 30 s per server copy, so the phone also keeps its newest
moments for ten minutes (localStorage, per member) and the page lays them
over what the server drew, including on a page the browser kept: a pause
shows on Watch the moment you go back. Watched = within 45 s of the end
(or 95% in); started = 20 s in. The player opens where you left off, a
few seconds back. Video and audio keep their own place (a church's audio
is often the sermon alone, its video the whole service).

SAVE. The bookmark on Watch and on a message: metadata.member_watch.s =
{sermon id: when}, the newest 60. The same route rules (POST
/my/sermons/save, a form without a script). Saved shows on Watch.

SHARE. Church content only (a message, a series), through member_lumen_share
(link, message_link: the public page, the sermon's or the series' id for
Your story); its sheet opens over it, and without a script the link opens
the public page.

ADD TO CALENDAR (GET /my/sermons/live.ics). The church's weekly service,
public (service times are public), on the church's own address: the day,
time and time zone the office set for check-in, every week, with the live
page's link. Kept ten minutes per server copy and an hour by the phone.
No end time: we don't know how long the service runs.

THE PLAYER for the mini player (member_mini, behind its own switch,
MEMBER_MINI_PLAYER): the media element carries data-title data-sub
data-thumb data-href, and data-lm-media where the mini player shows (so
with its switch off the page is what it would be without it). The page keeps the
phone's place in localStorage "lw:<who>" and says each save as a
"lm:progress" event on window ({id, pos, dur, m}).

Pure functions apart from the routes and the two small kept reads
(service_slot, talk_groups).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import time as _time
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from html import escape, unescape
from string import Template
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

logger = logging.getLogger("member_lumen_watch")
router = APIRouter()

KEY = "member_watch"                 # contacts.metadata.member_watch
MAX_PROGRESS = 20
MAX_SAVED = 60
STARTED = 20                         # seconds in before a message counts as started
DONE_LEFT = 45                       # this close to the end it counts as watched
ROWS = 12                            # Every message shows this many before "See all"
RAIL = 10
SLOT_SECONDS = 600.0
GROUP_SECONDS = 60.0
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

# Lumen's own icons for these pages (the rest are member_lumen_ui.ic's).
_ICONS = {
    "save": '<path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z"/>',
    "back15": '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
    "fwd15": '<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>',
    "chevL": '<path d="m15 18-6-6 6-6"/>',
    "listen": '<path d="M3 14h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a9 9 0 0 1 18 0v7a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3'
              'a2 2 0 0 1 2-2h3"/>',
    "bible": '<path d="M2 4h6a4 4 0 0 1 4 4v13a3 3 0 0 0-3-3H2z"/><path d="M22 4h-6a4 4 0 0 0-4 4v13a3 3 0 0 1 3-3h7z"/>',
}
_FILLED = {
    "play": '<path d="M8 5.2v13.6a1 1 0 0 0 1.5.86l11-6.8a1 1 0 0 0 0-1.72l-11-6.8A1 1 0 0 0 8 5.2z"/>',
    "pause": '<rect x="6" y="4.5" width="4" height="15" rx="1"/><rect x="14" y="4.5" width="4" height="15" rx="1"/>',
}


def _e(s: Any) -> str:
    return escape(str(s if s is not None else ""), quote=True)


def icon(name: str, size: int = 20, cls: str = "") -> str:
    if name in _FILLED:
        return (f'<svg class="lm-ic{(" " + cls) if cls else ""}" width="{size}" height="{size}" viewBox="0 0 24 24" '
                f'fill="currentColor" aria-hidden="true" focusable="false">{_FILLED[name]}</svg>')
    if name in _ICONS:
        return (f'<svg class="lm-ic{(" " + cls) if cls else ""}" width="{size}" height="{size}" viewBox="0 0 24 24" '
                f'fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" '
                f'aria-hidden="true" focusable="false">{_ICONS[name]}</svg>')
    import member_lumen_ui as lm
    out = lm.ic(name, size)
    return out.replace('class="lm-ic"', f'class="lm-ic {cls}"') if cls else out


# ─── what a member has watched and saved ─────────────────────────────


def clean(raw: Any) -> Dict[str, Dict[str, Any]]:
    """The stored value, made safe: {"p": {sid: [pos, dur, at, m]}, "s":
    {sid: at}}, ids lower-case, numbers whole and in range, the newest kept."""
    out: Dict[str, Dict[str, Any]] = {"p": {}, "s": {}}
    if not isinstance(raw, dict):
        return out
    p = raw.get("p")
    if isinstance(p, dict):
        for sid, v in p.items():
            if not UUID_RE.match(str(sid)) or not isinstance(v, (list, tuple)) or len(v) < 3:
                continue
            try:
                pos, dur, at = int(v[0]), int(v[1]), int(v[2])
            except (TypeError, ValueError):
                continue
            pos, dur = max(0, min(pos, 86400)), max(0, min(dur, 86400))
            if dur and pos > dur:
                pos = dur
            m = v[3] if len(v) > 3 and v[3] in ("v", "a") else "v"
            out["p"][str(sid).lower()] = [pos, dur, at, m]
    s = raw.get("s")
    if isinstance(s, list):                 # an older shape: a plain list
        s = {x: 0 for x in s}
    if isinstance(s, dict):
        for sid, at in s.items():
            if UUID_RE.match(str(sid)):
                try:
                    out["s"][str(sid).lower()] = int(at or 0)
                except (TypeError, ValueError):
                    out["s"][str(sid).lower()] = 0
    out["p"] = dict(sorted(out["p"].items(), key=lambda kv: kv[1][2], reverse=True)[:MAX_PROGRESS])
    out["s"] = dict(sorted(out["s"].items(), key=lambda kv: kv[1], reverse=True)[:MAX_SAVED])
    return out


def state(me: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """The member's own record's value (the session's read selects it as
    `watch`; a whole record carries it in metadata)."""
    raw = None
    if me:
        raw = me.get("watch")
        if raw is None and isinstance(me.get("metadata"), dict):
            raw = me["metadata"].get(KEY)
    return clean(raw)


def done(pos: int, dur: int) -> bool:
    return bool(dur) and (dur - pos <= DONE_LEFT or pos >= dur * 0.95)


def started(pos: int, dur: int) -> bool:
    return pos >= STARTED and not done(pos, dur)


def with_progress(cur: Any, sid: str, pos: int, dur: int, m: str, now: int) -> Optional[Dict[str, Any]]:
    """The value with this place saved, or None when it already says so
    (a few seconds either way): nothing to write."""
    st = clean(cur)
    if dur and done(pos, dur):
        pos = dur
    old = st["p"].get(sid)
    if old and old[3] == m and abs(old[0] - pos) < 5 and (old[1] == dur or not dur):
        return None
    st["p"][sid] = [int(pos), int(dur or (old[1] if old and old[3] == m else 0)), int(now), m]
    st["p"] = dict(sorted(st["p"].items(), key=lambda kv: kv[1][2], reverse=True)[:MAX_PROGRESS])
    return st


def with_saved(cur: Any, sid: str, on: bool, now: int) -> Optional[Dict[str, Any]]:
    st = clean(cur)
    if on == (sid in st["s"]):
        return None
    if on:
        st["s"][sid] = int(now)
        st["s"] = dict(sorted(st["s"].items(), key=lambda kv: kv[1], reverse=True)[:MAX_SAVED])
    else:
        st["s"].pop(sid, None)
    return st


def _write(business_id: str, contact_id: str, change: Callable[[Any, int], Optional[Dict[str, Any]]]) -> Optional[int]:
    """The change on the member's own record (contacts.metadata), guarded by
    updated_at so an office edit at the same moment isn't lost (as
    member_lumen_look.save). The server's time it saved at, or None."""
    import sb_clients
    import member_portal_church as mpc
    q = lambda v: quote(str(v), safe="")  # noqa: E731
    for _ in range(3):
        me = mpc.load_me(business_id, contact_id)
        if not me:
            return None
        now = int(_time.time())
        meta = dict(me.get("metadata") or {}) if isinstance(me.get("metadata"), dict) else {}
        new = change(meta.get(KEY), now)
        if new is None:
            return now
        meta[KEY] = new
        guard = f"eq.{q(me['updated_at'])}" if me.get("updated_at") else "is.null"
        got = sb_clients.sb_patch_as_service(
            f"/contacts?id=eq.{q(contact_id)}&business_id=eq.{q(business_id)}&updated_at={guard}",
            {"metadata": meta})
        if isinstance(got, list) and got:
            return now
    return None


def save_progress(business_id: str, contact_id: str, sid: str, pos: int, dur: int, m: str) -> Optional[int]:
    return _write(business_id, contact_id, lambda cur, now: with_progress(cur, sid, pos, dur, m, now))


def save_saved(business_id: str, contact_id: str, sid: str, on: bool) -> Optional[int]:
    return _write(business_id, contact_id, lambda cur, now: with_saved(cur, sid, on, now))


def _forget_record(business_id: str, me: Dict[str, Any]) -> None:
    """This server copy reads the member's record again on their next page
    (member_cache keeps it 30 s): what they just saved shows at once here."""
    try:
        import member_cache
        import member_portal as mp
        idents = {mp.norm_ident(x) for x in (me.get("email"), me.get("phone")) if x}
        bid = str(business_id)
        member_cache.people.forget(lambda k, _tag: isinstance(k, tuple) and k[0] == bid and k[1] in idents)
    except Exception:
        pass


def who(me: Optional[Dict[str, Any]]) -> str:
    """A short hash of whose page this is: the phone's own copy is kept per
    member (two people in a household on one phone)."""
    return hashlib.sha256(str((me or {}).get("id") or "").encode()).hexdigest()[:10]


# ─── words ───────────────────────────────────────────────────────────


def clock(sec: int) -> str:
    """'38:12', '1:02:03'."""
    sec = max(0, int(sec))
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def minutes(sec: int) -> str:
    """'38 min', '1 hr 4 min'."""
    m = max(1, round(sec / 60))
    return f"{m // 60} hr {m % 60} min" if m >= 60 and m % 60 else (f"{m // 60} hr" if m >= 60 else f"{m} min")


def left(pos: int, dur: int) -> str:
    return f"{max(1, math.ceil((dur - pos) / 60))} min left" if dur else ""


def _day(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def short_day(v: Any, today: Optional[date] = None) -> str:
    """'Nov 15', or 'Nov 15, 2025' from another year."""
    d = _day(v)
    if not d:
        return ""
    today = today or date.today()
    return f"{d:%b} {d.day}" + (f", {d.year}" if d.year != today.year else "")


def span(msgs: List[Dict[str, Any]]) -> str:
    """When a series ran, from its messages' dates: 'November 2026',
    'Oct – Nov 2026', 'Dec 2025 – Jan 2026'. '' without dates."""
    days = sorted(d for d in (_day(m.get("preached_on")) for m in msgs) if d)
    if not days:
        return ""
    a, b = days[0], days[-1]
    if (a.year, a.month) == (b.year, b.month):
        return f"{a:%B} {a.year}"
    if a.year == b.year:
        return f"{a:%b} – {b:%b} {b.year}"
    return f"{a:%b} {a.year} – {b:%b} {b.year}"


def questions(text: Any) -> List[str]:
    """The questions field as a list: one per line, the numbers and bullets
    the office typed taken off; a single line with "1. … 2. …" in it split
    there."""
    raw = str(text or "").strip()
    if not raw:
        return []
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if len(lines) == 1 and len(re.findall(r"(?:^|\s)\d{1,2}[.)]\s", lines[0])) >= 2:
        lines = [x.strip() for x in re.split(r"(?:^|\s)\d{1,2}[.)]\s", lines[0]) if x.strip()]
    out = []
    for ln in lines:
        ln = re.sub(r"^(?:\d{1,2}[.)]|[-•*–])\s*", "", ln).strip()
        if ln:
            out.append(ln)
    return out


def passages(scripture: Any, bible: str) -> List[Tuple[str, str]]:
    """[(label, href)] for "Read <passage>": each chapter the scripture
    names once ("Read Isaiah 9"), at its first verse, at most three
    (bible_text's references and slugs)."""
    import bible_text as bt
    out: List[Tuple[str, str]] = []
    seen = set()
    for _a, _b, ref in bt.find_refs(str(scripture or "")):
        key = (ref.book, ref.chapter)
        if key in seen:
            continue
        seen.add(key)
        href = f"/my/bible/{bt.slug(ref.book)}/{ref.chapter}" + (f"#v{ref.start}" if ref.start else "")
        out.append((f"{bt.NAME[ref.book]} {ref.chapter}", href))
        if len(out) == 3:
            break
    return out


# ─── the library, arranged ───────────────────────────────────────────


def _titles(lib: Dict[str, Any]) -> Dict[str, str]:
    return {str(x["id"]): x.get("title") or "" for x in lib.get("series") or []}


def arrange(lib: Dict[str, Any]) -> Dict[str, Any]:
    """Once per page: each message's series and part ("Part 3 of 4", the
    oldest is part 1, as member_portal_sermons._part counts), each series'
    messages oldest first."""
    titles = _titles(lib)
    by: Dict[str, List[Dict[str, Any]]] = {}
    for s in lib["sermons"]:
        sid = str(s.get("series_id") or "")
        if sid in titles:
            by.setdefault(sid, []).append(s)
    part: Dict[str, Tuple[int, int, str, str]] = {}
    for sid, msgs in by.items():
        n = len(msgs)
        for i, s in enumerate(msgs):
            part[str(s["id"]).lower()] = (n - i, n, titles[sid], sid)
    oldest = {sid: list(reversed(msgs)) for sid, msgs in by.items()}
    order = sorted(by, key=lambda k: str(by[k][0].get("preached_on")), reverse=True)
    return {"titles": titles, "part": part, "series": oldest, "order": order}


def _sid(s: Dict[str, Any]) -> str:
    return str(s.get("id") or "").lower()


def _src(art_html: str) -> str:
    """The picture's address in a piece of art, '' for a generated poster."""
    m = re.search(r'<img src="([^"]+)"', art_html or "")
    return unescape(m.group(1)) if m else ""


class _Page:
    """What one page draws from: the library arranged, the church's colours
    and photos, this member's places and saves."""

    def __init__(self, biz, site, who_me, lib):
        import member_app_photos as photos
        from member_portal import palette_for
        self.biz, self.site, self.lib = biz, site, lib
        self.pal = palette_for(biz, site)
        self.pool = photos.photos(biz, site)
        self.used: set = set()
        self.ar = arrange(lib)
        self.st = state(who_me)
        self.who = who(who_me)
        self.today = date.today()

    def art(self, s: Dict[str, Any], used: bool = False) -> str:
        import member_portal_sermons as mps
        return mps._art(self.lib, s, self.pal, self.site, self.pool, self.used if used else None)

    def part(self, s: Dict[str, Any]) -> Optional[Tuple[int, int, str, str]]:
        return self.ar["part"].get(_sid(s))

    def prog(self, s: Dict[str, Any], m: Optional[str] = None) -> Optional[List[Any]]:
        p = self.st["p"].get(_sid(s))
        return p if p and (m is None or p[3] == m) else None

    def dur(self, s: Dict[str, Any]) -> int:
        p = self.prog(s)
        return int(p[1]) if p and p[1] else 0

    def saved(self, s: Dict[str, Any]) -> bool:
        return _sid(s) in self.st["s"]

    def json(self) -> str:
        """The server's places and saves, for the page's script to lay the
        phone's newer ones over, and the script itself (its own file, kept a
        year by the phone)."""
        data = {"who": self.who, "now": int(_time.time()), "p": self.st["p"], "s": self.st["s"]}
        return (f'<script type="application/json" id="lw-state">'
                f'{json.dumps(data, separators=(",", ":")).replace("</", "<" + chr(92) + "/")}</script>'
                f'<script src="{js_url()}" defer></script>')


def _meta(*bits: Any) -> str:
    return " · ".join(_e(b) for b in bits if b)


def _bar(pos: int, dur: int) -> str:
    """The progress line on a thumbnail ('' until started)."""
    w = 100 if done(pos, dur) else (min(99, max(2, round(pos * 100 / dur))) if dur else 0)
    return f'<span class="lw-bar"><i style="width:{w}%"></i></span>' if w else '<span class="lw-bar" hidden><i></i></span>'


def _save(s: Dict[str, Any], on: bool, back: str, cls: str, inner_on: str, inner_off: str, label: bool) -> str:
    """Save: a form that posts without a script; the script flips it at once."""
    sid = _e(s["id"])
    aria = "" if label else ' aria-label="' + ("Saved" if on else "Save for later") + '"'
    return (f'<form class="lw-saveform" method="post" action="/my/sermons/save">'
            f'<input type="hidden" name="id" value="{sid}"><input type="hidden" name="on" value="{"0" if on else "1"}">'
            f'<input type="hidden" name="back" value="{_e(back)}">'
            f'<button class="{cls}" type="submit" data-lw-save="{sid}" aria-pressed="{"true" if on else "false"}"'
            f'{aria} data-on="{_e(inner_on)}" data-off="{_e(inner_off)}">'
            f'{inner_on if on else inner_off}</button></form>')


# ─── Watch ───────────────────────────────────────────────────────────


def _live_now(live: Dict[str, Any]) -> str:
    return (f'<a class="lw-live is-live" href="/my/live"><span class="lw-lic">{icon("live", 22)}</span>'
            f'<span class="lw-lt"><span class="lw-kick"><i class="lm-dotlive" aria-hidden="true"></i>Live now</span>'
            f'<b>{_e(live.get("title") or "Live now")}</b><small>Watch and chat with your church</small></span>'
            f'<span class="lw-pill pri sm">Watch</span></a>')


def _when_next(next_occ: Optional[Dict[str, Any]]) -> str:
    if not next_occ:
        return ""
    import member_portal_church as mpc
    d = mpc._day(next_occ.get("date") or "")
    if not d:
        return ""
    soon = mpc._in_days(d, date.today())
    return soon if soon in ("Today", "Tomorrow") else f"{d.strftime('%A')} · {soon}"


def service_words(slot: Dict[str, Any]) -> str:
    """'Sundays at 10:30 AM'."""
    import church_checkin as cc
    hh, mm = (int(x) for x in str(slot["time"]).split(":"))
    return f"{DAYS[int(slot['weekday'])]}s at {cc.clock(datetime(2000, 1, 1, hh, mm))}"


def live_card(service: Optional[Dict[str, Any]], next_occ: Optional[Dict[str, Any]]) -> str:
    """Watch live, at the foot of Messages: the weekly service time and Add
    to calendar when the office set it (check-in's day and time); else the
    next gathering, the way today's row says it. Both open the live page."""
    if service:
        return (f'<div class="lw-card"><a class="lw-cardl" href="/my/live"><span class="lw-cic">{icon("live", 22)}</span>'
                f'<span class="lw-ct"><b>Watch live</b><small>{_e(service_words(service))}</small></span></a>'
                f'<a class="lw-pill sm" href="/my/sermons/live.ics" download>Add to calendar</a></div>')
    title = (next_occ or {}).get("title") or "Live services"
    when = _when_next(next_occ) or "It plays right here"
    return (f'<div class="lw-card"><a class="lw-cardl" href="/my/live"><span class="lw-cic">{icon("live", 22)}</span>'
            f'<span class="lw-ct"><b>Watch live</b><small>{_meta(title if next_occ else "", when)}</small></span>'
            f'{icon("chevron", 18).replace("lm-ic", "lm-ic lm-chev")}</a></div>')


def _sub_for_card(pg: _Page, s: Dict[str, Any], hero_series: str) -> str:
    """'Part 2', or 'Rooted, part 5' when it's another series than the latest's."""
    pt = pg.part(s)
    if not pt:
        return ""
    return f"Part {pt[0]}" if pt[3] == hero_series else f"{pt[2]}, part {pt[0]}"


def _cw(pg: _Page, s: Dict[str, Any], hero_series: str, *, saved: bool = False) -> str:
    """A card on a rail: the picture with how far in, the title, where it
    sits and the minutes left."""
    p = pg.prog(s)
    pos, dur, m = (p[0], p[1], p[3]) if p else (0, 0, "v")
    sub = _sub_for_card(pg, s, hero_series)
    rest = left(pos, dur) if p and started(pos, dur) else ""
    href = f"/my/sermons/{_e(s['id'])}" + ("?listen=1" if m == "a" and rest and (s.get("audio_url") or "").strip() else "")
    return (f'<a class="lw-cw" href="{href}" data-lw-sid="{_e(_sid(s))}"><span class="lw-th">{pg.art(s)}{_bar(pos, dur)}</span>'
            f'<b>{_e(s.get("title"))}</b><small data-lw-sub="{_e(sub)}">{_meta(sub, rest) if not saved else _meta(sub or short_day(s.get("preached_on"), pg.today), rest)}</small></a>')


def _mrow(pg: _Page, s: Dict[str, Any]) -> str:
    """A row of Every message: the picture with how long it runs (once this
    member has played it), the title, speaker · scripture · date."""
    d = pg.dur(s)
    pt = pg.part(s)
    chip = f'<i class="lw-dur">{clock(d)}</i>' if d else '<i class="lw-dur" hidden></i>'
    p = pg.prog(s)
    pos, dur = (p[0], p[1]) if p else (0, 0)
    return (f'<a class="lw-mrow" href="/my/sermons/{_e(s["id"])}" data-lw-sid="{_e(_sid(s))}" '
            f'data-lw-part="{_e(_sub_for_card(pg, s, "") if pt else "")}">'
            f'<span class="lw-th">{pg.art(s)}{chip}{_bar(pos, dur)}</span>'
            f'<span class="lw-mt"><b>{_e(s.get("title"))}</b>'
            f'<small>{_meta(s.get("speaker"), s.get("scripture"), short_day(s.get("preached_on"), pg.today))}</small></span></a>')


def _head(view: str) -> str:
    cur = ' aria-current="page"'
    return (f'<h1 class="lw-t1">Watch</h1><nav class="lw-seg" aria-label="Messages or series">'
            f'<a href="/my/sermons"{cur if view != "series" else ""}>Messages</a>'
            f'<a href="/my/sermons?view=series"{cur if view == "series" else ""}>Series</a></nav>')


def watch_page(biz: Dict[str, Any], site, who_me: Dict[str, Any], lib: Optional[Dict[str, Any]], *,
               live: Optional[Dict[str, Any]] = None, next_occ: Optional[Dict[str, Any]] = None,
               bible: str = "kjv", view: str = "", show_all: bool = False,
               service: Optional[Dict[str, Any]] = None) -> str:
    """Watch (/my/sermons) in Look 5.1: Messages or Series."""
    from member_portal import _shell
    view = "series" if view == "series" else ""
    top = _live_now(live) if live else ""
    if lib is None:
        body = (f'<div class="lw lw-watch">{_head(view)}{top}<p class="mp-err lw-pad" role="alert" style="margin-top:20px">'
                f'Messages couldn\'t load just now. Please try again in a moment.</p>'
                f'{"" if live else live_card(service, next_occ)}</div>')
        return _shell(biz, site, "Watch", body, tab="watch", who=who_me)
    if not lib["sermons"]:
        import member_portal_lumen as mlp
        church = (biz.get("name") or "").strip() or "the church"
        body = (f'<div class="lw lw-watch">{_head(view)}{top}'
                f'<section class="lw-soon" aria-labelledby="lw-soon-h"><p class="lw-kick">Coming soon</p>'
                f'<h2 id="lw-soon-h">Messages are on the way</h2><p>When {_e(church)} posts a message, it shows up '
                f'here, ready to watch or listen, with the scripture and notes.</p></section>'
                f'{"" if live else live_card(service, next_occ)}<div class="lw-pad lw-verse">{mlp.verse_page(bible)}</div></div>')
        return _shell(biz, site, "Watch", body, tab="watch", who=who_me)
    pg = _Page(biz, site, who_me, lib)
    if view == "series":
        body = f'<div class="lw lw-watch" data-lw-who="{pg.who}">{_head(view)}{top}{_series_grid(pg)}</div>'
        return _shell(biz, site, "Series", body, tab="watch", who=who_me, script=pg.json())
    body = (f'<div class="lw lw-watch" data-lw-who="{pg.who}">{_head(view)}{top}{_messages(pg, show_all)}'
            f'{"" if live else live_card(service, next_occ)}</div>')
    return _shell(biz, site, "Watch", body, tab="watch", who=who_me, script=pg.json())


def _messages(pg: _Page, show_all: bool) -> str:
    import member_app_samples as samples
    import member_app_ui as ui
    import member_lumen_share as mls
    lib = pg.lib
    s = lib["sermons"][0]
    pt = pg.part(s)
    hero_series = pt[3] if pt else ""
    kick = f"Latest · {pt[2]}, part {pt[0]}" if pt else f"Latest · {short_day(s.get('preached_on'), pg.today)}".rstrip(" ·")
    d = pg.dur(s)
    href = f"/my/sermons/{_e(s['id'])}"
    art = pg.art(s, used=True)
    audio = bool((s.get("audio_url") or "").strip())
    video = bool((s.get("video_url") or "").strip())
    sample = samples.is_sample(s)
    hint = ui.sample_hint(samples.WHERE["sermons"]) if sample else ""
    play_word = "Watch" if video or not audio else "Listen"
    hero = (f'{hint}<a class="lw-hero" href="{href}" data-lw-sid="{_e(_sid(s))}" aria-label="{_e(play_word)}: {_e(s.get("title"))}">'
            f'<span class="lw-img">{art}</span><span class="lw-scrim"></span>{ui.sample_tag() if sample else ""}'
            f'<span class="lw-tx"><span class="lw-kick">{_e(kick)}</span><h2>{_e(s.get("title"))}</h2>'
            f'<span class="lw-hm" data-lw-heromins>{_meta(s.get("speaker"), s.get("scripture"), minutes(d) if d else "")}</span></span></a>')
    listen = (f'<a class="lw-pill" href="{href}?listen=1">{icon("listen", 15)}Listen</a>' if audio and video else "")
    btns = (f'<div class="lw-btns"><a class="lw-pill pri" href="{href}{"" if video or not audio else "?listen=1"}">'
            f'{icon("play", 14)}{play_word}</a>{listen}'
            + mls.message_link(lib, s, pg.site, pg.pool, f'{icon("share", 15)}Share', cls="lw-pill")
            + _save(s, pg.saved(s), "/my/sermons", "lw-pill lw-sq", icon("save", 19, "on"), icon("save", 19), False)
            + '</div>')
    # Pick up where you left off: started, not finished, newest first.
    by_id = {_sid(x): x for x in lib["sermons"]}
    going = [by_id[k] for k, v in pg.st["p"].items() if k in by_id and started(v[0], v[1])][:RAIL]
    cards = "".join(_cw(pg, x, hero_series) for x in going)
    pick = (f'<section class="lw-sec" data-lw-rail="go" aria-labelledby="lw-go-h"{"" if cards else " hidden"}>'
            f'<div class="lw-sh"><h2 id="lw-go-h">Pick up where you left off</h2></div>'
            f'<div class="lw-rail">{cards}</div></section>')
    keep = [by_id[k] for k in pg.st["s"] if k in by_id][:RAIL]
    scards = "".join(_cw(pg, x, hero_series, saved=True) for x in keep)
    saved = (f'<section class="lw-sec" data-lw-rail="saved" aria-labelledby="lw-sv-h"{"" if scards else " hidden"}>'
             f'<div class="lw-sh"><h2 id="lw-sv-h">Saved</h2></div><div class="lw-rail">{scards}</div></section>')
    rows = lib["sermons"] if show_all else lib["sermons"][:ROWS]
    more = ("" if show_all or len(lib["sermons"]) <= ROWS else
            f'<a class="lw-all" href="/my/sermons?all=1#lw-every">See all {len(lib["sermons"])} messages'
            f'{icon("chevron", 16)}</a>')
    every = (f'<section class="lw-sec" id="lw-every" aria-labelledby="lw-ev-h"><div class="lw-sh"><h2 id="lw-ev-h">Every message</h2>'
             f'</div><div class="lw-rows">{"".join(_mrow(pg, x) for x in rows)}</div>{more}</section>')
    return hero + btns + pick + saved + every


def _series_grid(pg: _Page) -> str:
    """The series two across: the poster, when it ran and how many."""
    tiles = []
    for sid in pg.ar["order"]:
        msgs = pg.ar["series"][sid]
        art = pg.art(msgs[-1], used=True)
        own = "mb-keep" in art                      # the church's own art carries its own title
        n = len(msgs)
        cap = _meta(span(msgs), f"{n} message{'' if n == 1 else 's'}")
        title = pg.ar["titles"][sid]
        tiles.append(f'<a class="lw-ser{" is-own" if own else ""}" href="/my/sermons?series={_e(sid)}">'
                     f'<span class="lw-po">{art}<span class="lw-scrim"></span>'
                     f'{"" if own else f"<b>{_e(title)}</b>"}</span>'
                     f'{f"<strong>{_e(title)}</strong>" if own else ""}<small>{cap}</small></a>')
    if not tiles:
        return '<p class="lw-pad lw-quiet">The church hasn\'t put any messages in a series yet.</p>'
    return f'<div class="lw-grid">{"".join(tiles)}</div>'


# ─── a series ────────────────────────────────────────────────────────


def _prow(pg: _Page, s: Dict[str, Any], *, now_id: str = "", show_scripture: bool = True, listen: bool = False) -> str:
    """One part: the picture with how far in, Part n (· Playing, · New), the
    title, scripture · date · how long or the minutes left, a check when
    watched."""
    pt = pg.part(s)
    p = pg.prog(s)
    pos, dur = (p[0], p[1]) if p else (0, 0)
    is_now = _sid(s) == now_id
    d = _day(s.get("preached_on"))
    fresh = bool(d) and 0 <= (pg.today - d).days <= 7 and not (p and (started(pos, dur) or done(pos, dur)))
    k = f"Part {pt[0]}" + (" · Playing" if is_now else (" · New" if fresh else "")) if pt else ""
    tail = left(pos, dur) if p and started(pos, dur) else (minutes(dur) if dur else "")
    meta = _meta(s.get("scripture") if show_scripture else "", short_day(s.get("preached_on"), pg.today), tail)
    tick = f'<span class="lw-ok" aria-label="Watched">{icon("check", 19)}</span>' if p and done(pos, dur) else \
        f'<span class="lw-ok" hidden>{icon("check", 19)}</span>'
    m = (p[3] if p else "a" if listen else "v")
    href = f"/my/sermons/{_e(s['id'])}" + ("?listen=1" if m == "a" and (s.get("audio_url") or "").strip() else "")
    attrs = ' aria-current="true"' if is_now else ""
    return (f'<a class="lw-prow{" is-now" if is_now else ""}" href="{href}" data-lw-sid="{_e(_sid(s))}"{attrs}>'
            f'<span class="lw-th">{pg.art(s)}{_bar(pos, dur)}</span>'
            f'<span class="lw-mt">{f"<span class=lw-k2>{_e(k)}</span>" if k else ""}<b>{_e(s.get("title"))}</b>'
            f'<small data-lw-tail>{meta}</small></span>{tick}</a>')


def next_part(pg: _Page, msgs: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], str]:
    """(the part to play, its button's words): the part they're in the
    middle of, else the next one after the last they watched, else part 1."""
    for i, s in enumerate(msgs):
        p = pg.prog(s)
        if p and started(p[0], p[1]):
            return s, f"Keep watching part {i + 1}"
    last = -1
    for i, s in enumerate(msgs):
        p = pg.prog(s)
        if p and done(p[0], p[1]):
            last = i
    if 0 <= last < len(msgs) - 1:
        return msgs[last + 1], f"Watch part {last + 2}"
    return (msgs[0], "Play part 1") if msgs else (None, "")


def series_page(biz: Dict[str, Any], site, who_me: Dict[str, Any], lib: Dict[str, Any], series_id: str) -> str:
    """One series (/my/sermons?series=<id>) in Look 5.1."""
    from member_portal import _shell
    pg = _Page(biz, site, who_me, lib)
    msgs = pg.ar["series"].get(series_id) or []
    title = pg.ar["titles"].get(series_id) or "Series"
    about = next((x.get("description") for x in lib["series"] if str(x["id"]) == series_id), "") or ""
    import member_app_ui as ui
    art = pg.art(msgs[-1], used=True) if msgs else ui.poster(series_id, pg.pal, title)
    when = span(msgs)
    first, word = next_part(pg, msgs)
    play = ""
    if first:
        m = (pg.prog(first) or [0, 0, 0, "v"])[3]
        q = "?listen=1" if m == "a" and (first.get("audio_url") or "").strip() else ""
        play = f'<a class="lw-pill pri lw-grow" href="/my/sermons/{_e(first["id"])}{q}">{icon("play", 14)}{_e(word)}</a>'
    n = len(msgs)
    import member_lumen_share as mls
    share = mls.link("series", mls.series_href(series_id), title, f'{icon("share", 15)}Share',
                     sub=unescape(_meta(when, f"{n} message{'' if n == 1 else 's'}")), img=_src(art), sid=series_id,
                     cls="lw-pill")
    rows = "".join(_prow(pg, s) for s in msgs)
    parts = (f'<div class="lw-parts">{rows}</div>' if rows else
             '<p class="lw-pad lw-quiet">No messages in this series are posted yet.</p>')
    body = (f'<div class="lw lw-series" data-lw-who="{pg.who}">'
            f'<header class="lw-shero"><span class="lw-img">{art}</span><span class="lw-scrim"></span>'
            f'<a class="lw-fab" href="/my/sermons?view=series" data-lw-back aria-label="Back to Watch">{icon("chevL", 22)}</a>'
            f'<div class="lw-tx"><p class="lw-kick">Series{" · " + _e(when) if when else ""}</p><h1>{_e(title)}</h1></div></header>'
            f'{f"<p class=lw-about>{_e(about)}</p>" if about else ""}'
            f'<div class="lw-btns lw-sbtns">{play}{share}</div>'
            f'{parts}</div>')
    return _shell(biz, site, title, body, tab="watch", who=who_me, back=("/my/sermons?view=series", "Watch"),
                  script=pg.json())


# ─── a message ───────────────────────────────────────────────────────


def _resume(p: Optional[List[Any]]) -> int:
    """Where the player opens: a few seconds before where they stopped, or
    the start once they've watched it."""
    if not p or not started(p[0], p[1]):
        return 0
    return max(0, int(p[0]) - 3)


def _with_start(src: str, at: int) -> str:
    """The embed's own start: YouTube's start=, Vimeo's #t=; the API on
    for both, so the page hears where the member is."""
    if "youtube" in src:
        q = "&" if "?" in src else "?"
        return src + f"{q}enablejsapi=1&rel=0&playsinline=1" + (f"&start={at}" if at else "")
    if "player.vimeo.com" in src:
        return src + (f"#t={at}s" if at else "")
    return src


def _video(s: Dict[str, Any], at: int, info: Dict[str, str]) -> str:
    """The video in its own player (sermons_public's embed), marked for the
    mini-player; '' when the link isn't one we can play in the page."""
    from sermons_public import video_embed_src
    src = video_embed_src((s.get("video_url") or "").strip())
    if not src:
        return ""
    kind = "yt" if "youtube" in src else ("vimeo" if "player.vimeo.com" in src else "")
    return (f'<div class="lw-vid"><iframe src="{_e(_with_start(src, at))}" title="{_e(s.get("title"))}" '
            f'allowfullscreen referrerpolicy="strict-origin-when-cross-origin" '
            f'allow="autoplay; fullscreen; picture-in-picture; encrypted-media" data-lw-media{_mini()} data-lw-kind="{kind}" '
            f'{_media_attrs(info)}></iframe></div>')


def _mini() -> str:
    """The mini player's mark (the shared contract), where it shows."""
    try:
        import member_mini
        return " data-lm-media" if member_mini.here() else ""
    except Exception:
        return ""


def _media_attrs(info: Dict[str, str]) -> str:
    return " ".join(f'data-{k}="{_e(v)}"' for k, v in info.items())


def _audio(s: Dict[str, Any], art: str, at: int, info: Dict[str, str]) -> str:
    """Our audio player: the art, Listening, the title, back 15 · play ·
    forward 15, the scrubber with both times. The browser's own player
    shows instead without a script."""
    src = (s.get("audio_url") or "").strip()
    return (f'<div class="lw-aud"><span class="lw-aart">{art}</span>'
            f'<div class="lw-atx"><span class="lw-kick">Listening</span><b>{_e(s.get("title"))}</b>'
            f'<div class="lw-actl" hidden><button class="lw-sk" type="button" data-lw-skip="-15" aria-label="Back 15 seconds">'
            f'{icon("back15", 26)}<i>15</i></button>'
            f'<button class="lw-big" type="button" data-lw-play aria-label="Play">{icon("play", 26, "pl")}{icon("pause", 26, "pa")}</button>'
            f'<button class="lw-sk" type="button" data-lw-skip="15" aria-label="Forward 15 seconds">{icon("fwd15", 26)}<i>15</i></button>'
            f'</div></div>'
            f'<audio class="lw-native" controls preload="metadata" src="{_e(src)}" data-lw-media{_mini()} data-lw-at="{at}" '
            f'{_media_attrs(info)}><a href="{_e(src)}">Listen</a></audio>'
            f'<div class="lw-scrub" hidden><input type="range" min="0" max="0" step="1" value="{at}" aria-label="Where you are" '
            f'data-lw-seek><span class="lw-tm"><span data-lw-cur>{clock(at)}</span><span data-lw-len>--:--</span></span></div></div>')


def message_page(biz: Dict[str, Any], site, who_me: Dict[str, Any], lib: Dict[str, Any], sermon_id: str, *,
                 give_url: str = "", bible: str = "kjv", listen: bool = False,
                 groups: Optional[List[Dict[str, Any]]] = None) -> Optional[str]:
    """One message (/my/sermons/<id>) in Look 5.1, or None when it isn't
    published here (the caller sends the member back to Watch)."""
    import bible_text as bt
    import member_app_samples as samples
    import member_app_ui as ui
    from member_portal import _shell
    from sermons_public import day_label
    s = next((x for x in lib["sermons"] if str(x["id"]) == sermon_id), None)
    if not s:
        return None
    pg = _Page(biz, site, who_me, lib)
    pt = pg.part(s)
    audio_url = (s.get("audio_url") or "").strip()
    video_url = (s.get("video_url") or "").strip()
    mode = "a" if audio_url and (listen or not video_url) else "v"
    art = pg.art(s)
    thumb = _src(art)
    series_sub = f"{pt[2]}, part {pt[0]}" if pt else ""
    info = {"title": s.get("title") or "", "sub": unescape(_meta(s.get("speaker"), series_sub)) or (biz.get("name") or ""),
            "thumb": thumb, "href": f"/my/sermons/{s['id']}" + ("?listen=1" if mode == "a" and video_url else "")}
    at = _resume(pg.prog(s, mode))
    back = f"/my/sermons?series={pt[3]}" if pt else "/my/sermons"
    back_name = pt[2] if pt else "Watch"
    fab = f'<a class="lw-fab" href="{_e(back)}" data-lw-back aria-label="Back to {_e(back_name)}">{icon("chevL", 22)}</a>'
    if mode == "a":
        player = _audio(s, art, at, info)
    else:
        player = _video(s, at, info)
        if not player:
            out = (f'<a class="lw-pill pri lw-out" href="{_e(video_url)}" target="_blank" rel="noopener">'
                   f'{icon("play", 14)}Watch this message</a>' if video_url else
                   '<p class="lw-none">The recording for this message isn\'t posted yet.</p>')
            player = f'<div class="lw-still"><span class="lw-img">{art}</span><span class="lw-scrim"></span>{out}</div>'
    sample = (ui.sample_hint("A sample message. " + samples.WHERE["sermons"]) if samples.is_sample(s) else "")
    kick = f"{pt[2]} · Part {pt[0]} of {pt[1]}" if pt and pt[1] > 1 else (pt[2] if pt else "Message")
    meta = _meta(s.get("speaker"), s.get("scripture"), day_label(s.get("preached_on")))
    # Listen | Video, Share, Save, Give: four across, or as many as there are.
    acts = []
    if audio_url and video_url:
        acts.append(f'<a class="lw-pa{" on" if mode == "a" else ""}" href="/my/sermons/{_e(s["id"])}{"" if mode == "a" else "?listen=1"}">'
                    f'{icon("play" if mode == "a" else "listen", 22)}<span>{"Video" if mode == "a" else "Listen"}</span></a>')
    import member_lumen_share as mls
    acts.append(mls.message_link(lib, s, site, pg.pool, f'{icon("share", 22)}<span>Share</span>', cls="lw-pa"))
    acts.append(_save(s, pg.saved(s), f"/my/sermons/{s['id']}", "lw-pa",
                      f'{icon("save", 22, "on")}<span>Saved</span>', f'{icon("save", 22)}<span>Save</span>', True))
    if give_url:
        acts.append(f'<a class="lw-pa" href="{_e(give_url)}">{icon("give", 22)}<span>Give</span></a>')
    # The tabs: About, Discuss, In this series; only the ones with something in them.
    tabs: List[Tuple[str, str, str]] = []
    reads = passages(s.get("scripture"), bible)
    tr = bt.TRANSLATIONS.get(bible, bt.TRANSLATIONS[bt.DEFAULT])["name"]
    about = (f'<p class="lw-sum">{_e(s["summary"])}</p>' if (s.get("summary") or "").strip() else "")
    about += "".join(f'<a class="lw-scrip" href="{_e(h)}"><span class="lw-sic">{icon("bible", 20)}</span>'
                     f'<span class="lw-st"><b>Read {_e(lbl)}</b><small>Opens in your Bible, {_e(tr)}</small></span>'
                     f'{icon("chevron", 18).replace("lm-ic", "lm-ic lm-chev")}</a>' for lbl, h in reads)
    if about:
        tabs.append(("about", "About", about))
    qs = questions(s.get("questions"))
    if qs:
        talk = "".join(f'<a class="lw-pill lw-full" href="/my/groups/{_e(g["id"])}/chat">{icon("users", 15)}'
                       f'Talk about it in {_e(g["name"])}</a>' for g in (groups or [])[:2])
        tabs.append(("discuss", "Discuss", f'<ol class="lw-qs">{"".join(f"<li>{_e(q)}</li>" for q in qs)}</ol>'
                                           f'{f"<div class=lw-talk>{talk}</div>" if talk else ""}'))
    if pt and pt[1] > 1:
        parts = "".join(_prow(pg, x, now_id=_sid(s), show_scripture=False, listen=mode == "a")
                        for x in pg.ar["series"][pt[3]])
        tabs.append(("series", "In this series", f'<div class="lw-parts">{parts}</div>'))
    body_tabs = ""
    if len(tabs) == 1:
        body_tabs = f'<div class="lw-panel lw-one">{tabs[0][2]}</div>'
    elif tabs:
        # Radio tabs: they switch with no script, and arrow keys move between them.
        heads = "".join(f'<input type="radio" name="lw-tab" id="lw-t-{k}" class="lw-tr"{" checked" if i == 0 else ""}>'
                        for i, (k, _, _) in enumerate(tabs))
        labels = "".join(f'<label for="lw-t-{k}" class="lw-tl lw-tl-{k}">{_e(lbl)}</label>' for k, lbl, _ in tabs)
        panels = "".join(f'<section class="lw-panel lw-p-{k}" aria-label="{_e(lbl)}">{html}</section>'
                         for k, lbl, html in tabs)
        body_tabs = f'<div class="lw-tabs">{heads}<div class="lw-tls" role="presentation">{labels}</div>{panels}</div>'
    no_media = not (audio_url or video_url)
    body = (f'<div class="lw lw-msg" data-lw-who="{pg.who}" data-lw-sid="{_e(_sid(s))}" data-lw-m="{mode}">'
            f'<div class="lw-pv{" is-aud" if mode == "a" else ""}{" is-none" if no_media else ""}">{player}{fab}</div>'
            f'{sample}<div class="lw-pinfo"><p class="lw-kick">{_e(kick)}</p><h1>{_e(s.get("title"))}</h1>'
            f'{f"<p class=lw-meta>{meta}</p>" if meta else ""}</div>'
            f'<div class="lw-pacts" style="--n:{len(acts)}">{"".join(acts)}</div>{body_tabs}</div>')
    return _shell(biz, site, s.get("title") or "Message", body, tab="watch", who=who_me, back=(back, back_name),
                  script=pg.json())


# ─── the kept reads: the service time, the member's groups ───────────


def _slots():
    import member_cache
    global _SLOTS
    if _SLOTS is None:
        _SLOTS = member_cache.Kept("watch_service", SLOT_SECONDS)
    return _SLOTS


def _groups_kept():
    import member_cache
    global _GROUPS
    if _GROUPS is None:
        _GROUPS = member_cache.Kept("watch_groups", GROUP_SECONDS)
    return _GROUPS


_SLOTS = None
_GROUPS = None


def service_slot(biz: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The church's weekly service as the office set it for check-in
    (church_checkin_settings: the day, the start time, the time zone, the
    name): {weekday, time "HH:MM", tz, title}, or None when the office never
    saved one (check-in's defaults are not a real time) or the read failed.
    Kept SLOT_SECONDS per server copy; a failed read isn't kept."""
    import church_checkin as cc
    import sb_clients
    bid = str((biz or {}).get("id") or "")
    if not bid:
        return None
    hit, slot = _slots().get(bid)
    if hit:
        return slot or None
    rows = sb_clients.sb_get_as_service(
        f"/church_checkin_settings?business_id=eq.{quote(bid, safe='')}&select=weekday,start_time,timezone,title&limit=1")
    if not isinstance(rows, list):
        return None
    slot = {}
    if rows:
        r = rows[0]
        t = str(r.get("start_time") or "")[:5]
        try:
            wd = int(r.get("weekday"))
        except (TypeError, ValueError):
            wd = -1
        if 0 <= wd <= 6 and re.fullmatch(r"([01][0-9]|2[0-3]):[0-5][0-9]", t):
            tz = str(r.get("timezone") or "")
            slot = {"weekday": wd, "time": t, "tz": tz if cc._zone(tz) else cc.church_zone_name(biz),
                    "title": " ".join(str(r.get("title") or "").split())[:80]}
    _slots().put(bid, slot, tag=bid)
    return slot or None


def talk_groups(biz: Dict[str, Any], me: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The member's groups whose chat is open to them (messaging on, the
    group's chat not off, everyone may write or they lead it), by name: for
    "Talk about it in <group>". Two small reads, kept GROUP_SECONDS per
    member per server copy, only on a message with questions; [] when
    messaging is off or a read failed (the button is left out)."""
    import member_portal_messaging as mpm
    import sb_clients
    try:
        if not mpm.turned_on(biz):
            return []
    except Exception:
        return []
    bid, cid = str(biz.get("id") or ""), str((me or {}).get("id") or "")
    if not bid or not cid:
        return []
    hit, got = _groups_kept().get((bid, cid))
    if hit:
        return got
    q = lambda v: quote(str(v), safe="")  # noqa: E731
    mine = sb_clients.sb_get_as_service(
        f"/group_members?business_id=eq.{q(bid)}&contact_id=eq.{q(cid)}&select=group_id,role&limit=50")
    if not isinstance(mine, list):
        return []
    role = {str(m.get("group_id")): m.get("role") for m in mine if m.get("group_id")}
    out: List[Dict[str, Any]] = []
    ids = [g for g in role if UUID_RE.match(g)]
    if ids:
        rows = sb_clients.sb_get_as_service(
            f"/groups?business_id=eq.{q(bid)}&id=in.({','.join(ids)})&active=eq.true"
            f"&select=id,name,chat_on,chat_writers&limit=50")
        if not isinstance(rows, list):
            return []
        for g in rows:
            if g.get("chat_on") is False:
                continue
            if g.get("chat_writers") == "leaders" and role.get(str(g["id"])) != "leader":
                continue
            out.append({"id": str(g["id"]), "name": g.get("name") or "your group"})
    out.sort(key=lambda g: g["name"].lower())
    _groups_kept().put((bid, cid), out, tag=bid)
    return out


# ─── Add to calendar ─────────────────────────────────────────────────


def _ics_text(v: Any) -> str:
    return str(v or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """Lines of at most 75 octets, continued with a space (RFC 5545)."""
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode("utf-8")) > 75:
            out.append(cur)
            cur = " " + ch
        else:
            cur += ch
    out.append(cur)
    return "\r\n".join(out)


def _offset(td: timedelta) -> str:
    mins = int(td.total_seconds() // 60)
    sign = "+" if mins >= 0 else "-"
    mins = abs(mins)
    return f"{sign}{mins // 60:02d}{mins % 60:02d}"


def _nth(d: date) -> str:
    """'2SU' (the second Sunday) or '-1SU' (the last) for a day of a month."""
    wd = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")[d.weekday()]
    nxt = d + timedelta(days=7)
    return f"-1{wd}" if nxt.month != d.month else f"{(d.day - 1) // 7 + 1}{wd}"


def _changes(tz: ZoneInfo, year: int) -> List[Tuple[timedelta, timedelta, datetime, str]]:
    """The zone's clock changes in `year`: (offset before, offset after,
    the wall time it happened at on the old clock, the new name). Found day
    by day, then to the quarter hour."""
    out = []
    day = datetime(year, 1, 1, 12, tzinfo=timezone.utc)
    prev = day.astimezone(tz).utcoffset()
    while day.year == year:
        nxt = day + timedelta(days=1)
        off = nxt.astimezone(tz).utcoffset()
        if off != prev:
            t = day
            while t.astimezone(tz).utcoffset() == prev:
                t += timedelta(minutes=15)
            out.append((prev, off, t.replace(tzinfo=None) + prev, t.astimezone(tz).tzname() or ""))
            prev = off
        day = nxt
    return out


def _first_1970(month: int, rule: str) -> date:
    """The rule's day ('2SU', '-1SU') in 1970, where a VTIMEZONE starts."""
    want = ("MO", "TU", "WE", "TH", "FR", "SA", "SU").index(rule[-2:])
    days = [date(1970, month, i) for i in range(1, 32) if _ok(1970, month, i) and date(1970, month, i).weekday() == want]
    n = int(rule[:-2])
    return days[n - 1] if n > 0 else days[n]


def _ok(y: int, m: int, d: int) -> bool:
    try:
        date(y, m, d)
        return True
    except ValueError:
        return False


def vtimezone(name: str, year: int) -> List[str]:
    """The zone's rules for calendars that want them (RFC 5545 asks for one
    per TZID): its clock changes in `year` written as yearly rules, or one
    standard offset for a zone with none."""
    tz = ZoneInfo(name)
    lines = ["BEGIN:VTIMEZONE", f"TZID:{name}"]
    changes = _changes(tz, year)
    if not changes:
        jan = datetime(year, 1, 1, 12, tzinfo=tz)
        off = jan.utcoffset() or timedelta(0)
        lines += ["BEGIN:STANDARD", "DTSTART:19700101T000000", f"TZOFFSETFROM:{_offset(off)}",
                  f"TZOFFSETTO:{_offset(off)}", f"TZNAME:{jan.tzname() or ''}", "END:STANDARD"]
    for frm, to, local, abbr in changes:
        kind = "DAYLIGHT" if to > frm else "STANDARD"
        rule = _nth(local.date())
        d70 = _first_1970(local.month, rule)
        lines += [f"BEGIN:{kind}", f"DTSTART:{d70:%Y%m%d}T{local:%H%M%S}",
                  f"RRULE:FREQ=YEARLY;BYMONTH={local.month};BYDAY={rule}",
                  f"TZOFFSETFROM:{_offset(frm)}", f"TZOFFSETTO:{_offset(to)}", f"TZNAME:{abbr}", f"END:{kind}"]
    lines.append("END:VTIMEZONE")
    return lines


def ics(biz: Dict[str, Any], slot: Dict[str, Any], host: str, now: Optional[datetime] = None) -> str:
    """The weekly service as a calendar file: on the church's clock, every
    week, the live page's link. No end time (we don't know how long it runs)."""
    now = now or datetime.now(timezone.utc)
    tz = ZoneInfo(slot["tz"])
    local_today = now.astimezone(tz).date()
    first = local_today + timedelta(days=(int(slot["weekday"]) - local_today.weekday()) % 7)
    hh, mm = (int(x) for x in slot["time"].split(":"))
    church = (biz.get("name") or "").strip() or "Church"
    title = slot.get("title") or f"{DAYS[int(slot['weekday'])]} service"
    url = f"https://{host}/my/live" if host else ""
    byday = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")[int(slot["weekday"])]
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Solutionist//Member app//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{_ics_text(church)}"]
    lines += vtimezone(slot["tz"], first.year)
    lines += ["BEGIN:VEVENT", f"UID:service-{biz.get('id')}@{host or 'solutionist'}", f"DTSTAMP:{now:%Y%m%dT%H%M%SZ}",
              f"DTSTART;TZID={slot['tz']}:{first:%Y%m%d}T{hh:02d}{mm:02d}00", f"RRULE:FREQ=WEEKLY;BYDAY={byday}",
              f"SUMMARY:{_ics_text(title + ' · ' + church)}"]
    if url:
        lines += [f"DESCRIPTION:{_ics_text('Watch live in the app: ' + url)}", f"URL:{url}"]
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"


# ─── routes ──────────────────────────────────────────────────────────


def _json(ok: bool, status: int = 200, **extra) -> JSONResponse:
    import member_portal as mp
    return JSONResponse({"ok": ok, **extra}, status_code=status, headers=mp._SECURE_HEADERS)


async def _who(request: Request):
    """(church, me, refusal): the signed-in member from their own church's
    page (member_portal_church._signed_in: the session and the same-origin
    check), or the JSON refusal to send."""
    import member_portal as mp
    import member_portal_church as mpc
    if not mp._same_origin(request):
        return None, None, _json(False, 403, error="origin")
    church, me, unavailable = await mpc._signed_in(request)
    if unavailable == "preview":
        # The owner's preview reads; it never writes as the member.
        return church, None, _json(False, 200, error="preview")
    if unavailable:
        return church, None, _json(False, 503, error="unavailable")
    if not me:
        return church, None, _json(False, 401, error="signin")
    import rate_limit
    if not rate_limit.allow("member_watch", f"{church['business']['id']}|{me['id']}"):
        return church, me, _json(False, 429, error="slow")
    return church, me, None


@router.post("/my/sermons/progress", include_in_schema=False)
async def progress(request: Request):
    """Where the member is in a message: {id, pos, dur, m} (seconds; m is
    "v" video or "a" audio). JSON in (or the same as text, from a page being
    hidden), JSON out with the server's time it saved at."""
    raw = await request.body()
    church, me, refused = await _who(request)
    if refused:
        return refused
    try:
        body = json.loads(raw.decode("utf-8")) if len(raw) <= 2048 else None
    except Exception:
        body = None
    if not isinstance(body, dict):
        return _json(False, 400, error="bad")
    sid = str(body.get("id") or "").lower()
    m = body.get("m") if body.get("m") in ("v", "a") else ""
    try:
        pos, dur = int(float(body.get("pos"))), int(float(body.get("dur") or 0))
    except (TypeError, ValueError):
        pos, dur = -1, -1
    if not UUID_RE.match(sid) or not m or not 0 <= pos <= 86400 or not 0 <= dur <= 86400:
        return _json(False, 400, error="bad")
    at = await asyncio.to_thread(save_progress, church["business"]["id"], str(me["id"]), sid, pos, dur, m)
    if at is None:
        return _json(False, 503, error="error")
    _forget_record(church["business"]["id"], me)
    return _json(True, at=at)


@router.post("/my/sermons/save", include_in_schema=False)
async def save(request: Request):
    """Save a message for later, or take it off: `id`, `on` (1 or 0). JSON
    for the page's script (Accept: application/json), else back to the page
    it came from (a form without a script)."""
    wants = "application/json" in (request.headers.get("accept") or "")
    try:
        if "application/json" in (request.headers.get("content-type") or ""):
            body = await request.json()
        else:
            body = dict(await request.form())
    except Exception:
        body = {}
    body = body if isinstance(body, dict) else {}
    sid = str(body.get("id") or "").lower()
    on = str(body.get("on") if body.get("on") is not None else "1") in ("1", "true", "True")
    back = str(body.get("back") or "/my/sermons")
    if not re.fullmatch(r"/my/sermons(/[0-9a-fA-F-]{36})?", back):
        back = "/my/sermons"
    church, me, refused = await _who(request)
    if refused is not None and wants:
        return refused
    if refused is not None:
        import member_portal as mp
        return RedirectResponse(back, status_code=303, headers=mp._SECURE_HEADERS)
    if not UUID_RE.match(sid):
        return _json(False, 400, error="bad") if wants else RedirectResponse(back, status_code=303)
    at = await asyncio.to_thread(save_saved, church["business"]["id"], str(me["id"]), sid, on)
    if at is not None:
        _forget_record(church["business"]["id"], me)
    if wants:
        return _json(at is not None, 200 if at is not None else 503, at=at, on=on)
    import member_portal as mp
    return RedirectResponse(back, status_code=303, headers=mp._SECURE_HEADERS)


@router.get("/my/sermons/live.ics", include_in_schema=False)
async def service_ics(request: Request):
    """The church's weekly service for the phone's calendar (Watch → Add to
    calendar). Public on the church's own address: service times are."""
    import member_lumen
    import member_portal as mp
    import public_site
    if member_lumen.mode() == "off":
        # Only the new look links here: switched off, the address is what it was.
        return await mp.serve(request, "/my/sermons/live.ics")
    church = await asyncio.to_thread(mp._church_for_request, request)
    if not church or not mp.portal_active(church["business"]):
        return Response("Not found", status_code=404, media_type="text/plain")
    biz = church["business"]
    slot = await asyncio.to_thread(service_slot, biz)
    if not slot:
        return Response("Not found", status_code=404, media_type="text/plain")
    host = (public_site.public_host(request) or "").split(":")[0].lower()
    name = re.sub(r"[^A-Za-z0-9]+", "-", (biz.get("name") or "church")).strip("-").lower() or "church"
    return Response(ics(biz, slot, host), media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'inline; filename="{name}-service.ics"',
                             "Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff"})


# ─── the script ──────────────────────────────────────────────────────
# One script for Watch, a series and a message, served as its own file
# (GET /my/watch.<hash>.js, kept a year) after the page's state. It keeps the phone's newest
# places and saves (localStorage "lw:<who>", ten minutes, in the server's
# clock), lays them over what the server drew (on load and when the browser
# shows a page it kept), runs the audio player, hears YouTube and Vimeo,
# saves where the member is (on pause, on hide, once a minute while it plays),
# flips Save at once and goes Back through history when the page before was
# ours (not once something has played: then Back is a link, which the mini
# player, member_mini, opens over the message so it plays on). Share is member_lumen_share's sheet (its own script, which _shell adds).
JS = r"""(function(){var w=window,d=document,root=d.querySelector('.lw[data-lw-who]'),sj=d.getElementById('lw-state');
if(!root||!sj)return;var S;try{S=JSON.parse(sj.textContent);}catch(e){return;}
var skew=S.now-Date.now()/1000,K='lw:'+S.who,TTL=600,STARTED=20,LEFT=45;
function now(){return Math.round(Date.now()/1000+skew);}
function load(){try{var v=JSON.parse(localStorage.getItem(K)||'{}');return{p:v.p||{},s:v.s||{}};}catch(e){return{p:{},s:{}};}}
function keep(L){var t=now()-TTL;['p','s'].forEach(function(k){for(var i in L[k]){var a=L[k][i];if((k==='p'?a[2]:a[1])<t)delete L[k][i];}});
try{localStorage.setItem(K,JSON.stringify(L));}catch(e){}}
function merged(){var L=load(),P={},Sv={},i;for(i in S.p)P[i]=S.p[i];for(i in L.p){if(!P[i]||L.p[i][2]>P[i][2])P[i]=L.p[i];}
for(i in S.s)Sv[i]=1;for(i in L.s){var sa=S.s[i];if(sa===undefined||L.s[i][1]>sa){if(L.s[i][0])Sv[i]=1;else delete Sv[i];}}return{p:P,s:Sv};}
function isDone(p,u){return u>0&&(u-p<=LEFT||p>=u*.95);}
function clock(x){x=Math.max(0,Math.floor(x||0));var h=Math.floor(x/3600),m=Math.floor(x%3600/60),s=x%60;
return(h?h+':'+(m<10?'0':''):'')+m+':'+(s<10?'0':'')+s;}
function left(p,u){return Math.max(1,Math.ceil((u-p)/60))+' min left';}
function bar(el,p,u){var b=el.querySelector('.lw-bar');if(!b)return;var pc=isDone(p,u)?100:(u?Math.min(99,Math.max(2,Math.round(p*100/u))):0);
b.hidden=!pc;b.firstChild.style.width=pc+'%';}
function paint(){var M=merged();
[].forEach.call(d.querySelectorAll('[data-lw-sid]'),function(el){var a=M.p[el.getAttribute('data-lw-sid')];if(!a)return;
bar(el,a[0],a[1]);var c=el.querySelector('.lw-dur');if(c&&a[1]){c.textContent=clock(a[1]);c.hidden=false;}
var ok=el.querySelector('.lw-ok');if(ok)ok.hidden=!isDone(a[0],a[1]);});
[].forEach.call(d.querySelectorAll('[data-lw-save]'),function(b){var on=!!M.s[b.getAttribute('data-lw-save')];flip(b,on);});
rails(M);}
function flip(b,on){b.setAttribute('aria-pressed',on?'true':'false');b.innerHTML=b.getAttribute(on?'data-on':'data-off');
if(b.hasAttribute('aria-label'))b.setAttribute('aria-label',on?'Saved':'Save for later');
var f=b.form;if(f&&f.elements.on)f.elements.on.value=on?'0':'1';}
function cardFor(sid,p,saved){var r=d.querySelector('.lw-mrow[data-lw-sid="'+sid+'"]');if(!r)return null;
var a=d.createElement('a');a.className='lw-cw';a.href=r.getAttribute('href');a.setAttribute('data-lw-sid',sid);
var th=r.querySelector('.lw-th').cloneNode(true),c=th.querySelector('.lw-dur');if(c)c.remove();a.appendChild(th);
var b=d.createElement('b');b.textContent=r.querySelector('.lw-mt b').textContent;a.appendChild(b);
var sm=d.createElement('small'),part=r.getAttribute('data-lw-part')||'';sm.setAttribute('data-lw-sub',part);a.appendChild(sm);return a;}
function sub(card,p){var sm=card.querySelector('small');if(!sm||!p)return;var part=sm.getAttribute('data-lw-sub')||'';
if(p[0]>=STARTED&&!isDone(p[0],p[1]))sm.textContent=[part,p[1]?left(p[0],p[1]):''].filter(Boolean).join(' \u00b7 ');}
function rails(M){var go=d.querySelector('[data-lw-rail="go"]'),sv=d.querySelector('[data-lw-rail="saved"]');
if(go){var rail=go.querySelector('.lw-rail'),want=Object.keys(M.p).filter(function(k){var a=M.p[k];return a[0]>=STARTED&&!isDone(a[0],a[1]);})
.sort(function(x,y){return M.p[y][2]-M.p[x][2];}).slice(0,10);
[].forEach.call(rail.querySelectorAll('.lw-cw'),function(c){if(want.indexOf(c.getAttribute('data-lw-sid'))<0)c.remove();});
want.forEach(function(k,i){var c=rail.querySelector('[data-lw-sid="'+k+'"]')||cardFor(k,M.p[k]);if(!c)return;
if(rail.children[i]!==c)rail.insertBefore(c,rail.children[i]||null);bar(c,M.p[k][0],M.p[k][1]);sub(c,M.p[k]);});
go.hidden=!rail.children.length;}
if(sv){var r2=sv.querySelector('.lw-rail');[].forEach.call(r2.querySelectorAll('.lw-cw'),function(c){if(!M.s[c.getAttribute('data-lw-sid')])c.remove();});
Object.keys(M.s).forEach(function(k){if(!r2.querySelector('[data-lw-sid="'+k+'"]')){var c=cardFor(k,M.p[k],1);if(c){
var sm=c.querySelector('small');if(sm)sm.textContent=sm.getAttribute('data-lw-sub')||'';r2.insertBefore(c,r2.firstChild);}}});
sv.hidden=!r2.children.length;}}
function post(url,body,cb,beacon){var s=JSON.stringify(body);
if(beacon&&navigator.sendBeacon){try{if(navigator.sendBeacon(url,new Blob([s],{type:'text/plain'})))return;}catch(e){}}
fetch(url,{method:'POST',credentials:'same-origin',keepalive:!!beacon,headers:{'Content-Type':'application/json','Accept':'application/json'},body:s})
.then(function(r){return r.json();}).then(function(j){cb&&cb(j);},function(){cb&&cb(null);});}
// Save, at once; back if it didn't save.
d.addEventListener('submit',function(e){var f=e.target;if(!f.classList||!f.classList.contains('lw-saveform'))return;e.preventDefault();
var b=f.querySelector('[data-lw-save]'),sid=b.getAttribute('data-lw-save'),on=f.elements.on.value==='1',L=load();
flip(b,on);L.s[sid]=[on?1:0,now()];keep(L);rails(merged());
post('/my/sermons/save',{id:sid,on:on?1:0},function(j){if(j&&j.ok){var L2=load();if(L2.s[sid])L2.s[sid][1]=j.at||L2.s[sid][1];keep(L2);return;}
if(j&&j.error==='preview')return;var L3=load();delete L3.s[sid];keep(L3);paint();});},true);
// Back: through history when the page before was ours.
var fb=d.querySelector('[data-lw-back]');if(fb)fb.addEventListener('click',function(e){if(w.__lwPlayed)return;try{var r=new URL(d.referrer);
if(r.origin===location.origin&&r.pathname.indexOf('/my')===0&&history.length>1){e.preventDefault();history.back();}}catch(x){}});
paint();addEventListener('pageshow',function(e){if(e.persisted)paint();});
// The player.
var sid=root.getAttribute('data-lw-sid'),mode=root.getAttribute('data-lw-m');if(!sid)return;
var pos=0,dur=0,playing=false,last=0,sent=-1;
function remember(beacon){if(!dur&&pos<STARTED)return;if(Math.abs(pos-sent)<2&&!beacon)return;sent=pos;var L=load(),p=Math.round(pos),u=Math.round(dur);
if(isDone(p,u))p=u;L.p[sid]=[p,u,now(),mode];keep(L);
try{window.dispatchEvent(new CustomEvent('lm:progress',{detail:{id:sid,pos:p,dur:u,m:mode,playing:playing}}));}catch(e){}
post('/my/sermons/progress',{id:sid,pos:p,dur:u,m:mode},function(j){if(j&&j.ok&&j.at){var L2=load();if(L2.p[sid])L2.p[sid][2]=j.at;keep(L2);}},beacon);}
function tick(){if(playing&&Date.now()-last>=60000){last=Date.now();remember();}}
setInterval(tick,5000);
addEventListener('pagehide',function(){if(pos)remember(true);});
d.addEventListener('visibilitychange',function(){if(d.visibilityState==='hidden'&&pos)remember(true);});
function local(){var a=merged().p[sid];return a&&a[3]===mode?a:null;}
function resumeAt(){var a=local();return a&&a[0]>=STARTED&&!isDone(a[0],a[1])?Math.max(0,a[0]-3):0;}
var au=root.querySelector('audio[data-lw-media]');
if(au){var ctl=root.querySelector('.lw-actl'),sc=root.querySelector('.lw-scrub'),seek=root.querySelector('[data-lw-seek]'),
cur=root.querySelector('[data-lw-cur]'),len=root.querySelector('[data-lw-len]'),pb=root.querySelector('[data-lw-play]'),dragging=false,begun=false;
au.removeAttribute('controls');au.hidden=true;ctl.hidden=false;sc.hidden=false;
var at=resumeAt()||parseInt(au.getAttribute('data-lw-at')||'0',10);
function meta(){dur=au.duration&&isFinite(au.duration)?au.duration:0;seek.max=Math.floor(dur);len.textContent=dur?clock(dur):'--:--';
seekTo();show();}
function seekTo(){if(!begun&&at&&(au.currentTime||0)<at-2){try{au.currentTime=at;}catch(e){}}}
function here(){var c=au.currentTime||0;return !begun&&at&&c<at-2?at:c;}
function show(){pos=here();if(!dragging){seek.value=Math.floor(pos);}cur.textContent=clock(dragging?seek.value:pos);
seek.style.setProperty('--p',(dur?Math.min(100,seek.value*100/dur):0)+'%');
seek.setAttribute('aria-valuetext',clock(pos)+(dur?' of '+clock(dur):''));
root.querySelector('.lw-pv').classList.toggle('is-playing',!au.paused);pb.setAttribute('aria-label',au.paused?'Play':'Pause');}
au.addEventListener('loadedmetadata',meta);au.addEventListener('durationchange',meta);au.addEventListener('canplay',function(){seekTo();show();});au.addEventListener('timeupdate',show);
au.addEventListener('play',function(){begun=true;playing=true;w.__lwPlayed=1;last=Date.now();show();});
au.addEventListener('pause',function(){playing=false;show();remember();});
au.addEventListener('ended',function(){playing=false;pos=dur;remember();});
if(au.readyState>=1)meta();else if(at){cur.textContent=clock(at);seek.value=at;}
pb.addEventListener('click',function(){if(au.paused){seekTo();au.play().catch(function(){});}else au.pause();});
[].forEach.call(root.querySelectorAll('[data-lw-skip]'),function(b){b.addEventListener('click',function(){
var t=here()+parseInt(b.getAttribute('data-lw-skip'),10);begun=true;au.currentTime=Math.max(0,dur?Math.min(dur-1,t):t);show();});});
seek.addEventListener('input',function(){dragging=true;cur.textContent=clock(seek.value);seek.style.setProperty('--p',(dur?seek.value*100/dur:0)+'%');});
seek.addEventListener('change',function(){dragging=false;au.currentTime=+seek.value;show();remember();});
if('mediaSession' in navigator){try{var th=au.getAttribute('data-thumb');navigator.mediaSession.metadata=new MediaMetadata({
title:au.getAttribute('data-title')||'',artist:au.getAttribute('data-sub')||'',artwork:th?[{src:new URL(th,location.href).href}]:[]});
navigator.mediaSession.setActionHandler('play',function(){au.play();});navigator.mediaSession.setActionHandler('pause',function(){au.pause();});
navigator.mediaSession.setActionHandler('seekbackward',function(){au.currentTime=Math.max(0,au.currentTime-15);});
navigator.mediaSession.setActionHandler('seekforward',function(){au.currentTime=Math.min(dur||1e9,au.currentTime+15);});
navigator.mediaSession.setActionHandler('seekto',function(x){au.currentTime=x.seekTime;});}catch(e){}}
return;}
var fr=root.querySelector('iframe[data-lw-media]');if(!fr)return;var kind=fr.getAttribute('data-lw-kind');if(!kind)return;
var r0=resumeAt(),src=fr.getAttribute('src');
// The phone's newer place than the server drew: open there instead.
if(r0){var srv=kind==='yt'?(/[?&]start=(\d+)/.exec(src)||[])[1]:(/#t=(\d+)s/.exec(src)||[])[1];if(Math.abs((+srv||0)-r0)>5){
src=kind==='yt'?src.replace(/&start=\d+/,'')+'&start='+r0:src.replace(/#t=\d+s/,'')+'#t='+r0+'s';fr.setAttribute('src',src);}}
var origin=kind==='yt'?/^https:\/\/www\.youtube(-nocookie)?\.com$/:/^https:\/\/player\.vimeo\.com$/;
function say(m){try{fr.contentWindow.postMessage(JSON.stringify(m),kind==='yt'?'*':'https://player.vimeo.com');}catch(e){}}
fr.addEventListener('load',function(){if(kind==='yt'){say({event:'listening',id:1,channel:'widget'});}
else{['timeupdate','play','pause','ended','loaded'].forEach(function(v){say({method:'addEventListener',value:v});});}});
window.addEventListener('message',function(e){if(e.source!==fr.contentWindow||!origin.test(e.origin))return;var m;
try{m=typeof e.data==='string'?JSON.parse(e.data):e.data;}catch(x){return;}if(!m)return;
if(kind==='yt'){var i=m.info||{};if(m.event==='onReady')say({event:'listening',id:1,channel:'widget'});
if(typeof i.duration==='number'&&i.duration>0)dur=i.duration;if(typeof i.currentTime==='number')pos=i.currentTime;
if(typeof i.playerState==='number'){var was=playing;playing=i.playerState===1;if(playing){w.__lwPlayed=1;if(!was)last=Date.now();}
if(!playing&&was&&(i.playerState===2||i.playerState===0)){if(i.playerState===0&&dur)pos=dur;remember();}}}
else{var x=m.data||{};if(typeof x.duration==='number'&&x.duration>0)dur=x.duration;if(typeof x.seconds==='number')pos=x.seconds;
if(m.event==='play'){playing=true;w.__lwPlayed=1;last=Date.now();}if(m.event==='pause'||m.event==='ended'){playing=false;if(m.event==='ended'&&dur)pos=dur;remember();}}});
})();"""


@lru_cache(maxsize=None)
def js_file() -> Tuple[bytes, str]:
    """The script's bytes and the 12-hex hash in its address."""
    data = JS.encode("utf-8")
    return data, hashlib.sha256(data).hexdigest()[:12]


def js_url() -> str:
    return f"/my/watch.{js_file()[1]}.js"


@router.get("/my/watch.{tag}.js", include_in_schema=False)
async def watch_js(tag: str):
    """The pages' script, from our own address: kept a year when the hash is
    today's; another hash (a page from before a deploy) gets today's file,
    kept by nobody (as member_lumen_share's script and the fonts are)."""
    data, digest = js_file()
    keep = "public, max-age=31536000, immutable" if tag == digest else "no-store"
    return Response(data, media_type="text/javascript; charset=utf-8",
                    headers={"Cache-Control": keep, "X-Content-Type-Options": "nosniff"})


# ─── the sheet ───────────────────────────────────────────────────────
# Look 5.1's Watch. Every colour is a Lumen token, so Light, Dark and Same as
# my phone all work; the player's own surface is the media's black in any
# look. Under .lm only.
CSS = Template("""
/* Watch, Look 5.1 (member_lumen_watch) */
.lm .mp-shell:has(>.lw){padding-left:0;padding-right:0;}
.lm .mp-shell:has(>.lw)>.mp-foot{padding:0 var(--lw-x);}
.lm .lw{--lw-x:20px;}
.lm .lw-pad{padding:0 var(--lw-x);}
.lm .lw-kick{display:flex;align-items:center;gap:7px;margin:0;font:750 11px/1.2 var(--mb-ui);letter-spacing:.12em;text-transform:uppercase;color:var(--acc);}
.lm .lw-quiet{margin:18px 0 0;font:400 14.5px/1.45 var(--mb-ui);color:var(--fg2);}
/* the title and Messages | Series */
.lm .lw-t1{margin:14px var(--lw-x) 0;font:800 30px/1.1 var(--mb-ui);letter-spacing:-.028em;color:var(--fg);}
.lm .lw-seg{display:flex;margin:14px var(--lw-x) 0;padding:3px;border-radius:14px;background:var(--s1);}
.lm .lw-seg a{flex:1;height:36px;border-radius:11px;display:flex;align-items:center;justify-content:center;font:650 14px/1 var(--mb-ui);
  color:var(--fg2);text-decoration:none;}
.lm .lw-seg a[aria-current]{background:var(--lm-raise);color:var(--fg);box-shadow:0 1px 3px var(--lm-shadow),0 0 0 .5px var(--lm-line);}
/* pills */
.lm .lw-btns{display:flex;gap:8px;align-items:center;padding:12px var(--lw-x) 0;}
.lm .lw-pill{height:38px;min-width:0;padding:0 16px;border-radius:19px;border:1.5px solid var(--lm-line);background:var(--bg);color:var(--fg);
  font:650 14px/1 var(--mb-ui);display:inline-flex;align-items:center;justify-content:center;gap:7px;white-space:nowrap;text-decoration:none;
  cursor:pointer;flex:none;}
.lm .lw-pill.pri{background:var(--acc-fill);border-color:var(--acc-fill);color:var(--on-acc);}
.lm .lw-pill.sm{height:34px;padding:0 14px;font-size:13.5px;}
.lm .lw-pill.lw-sq{width:38px;padding:0;border-color:transparent;background:none;}
.lm .lw-pill.lw-full{width:100%;}
.lm .lw-grow{flex:1;}
.lm .lw-pill .lm-ic.on,.lm .lw-pa .lm-ic.on{fill:var(--acc);color:var(--acc);}
.lm .lw-saveform{display:contents;}
/* live now, and Watch live at the foot */
.lm .lw-live{display:flex;align-items:center;gap:14px;margin:16px var(--lw-x) 0;padding:14px 14px 14px 16px;border-radius:18px;background:var(--s1);
  color:var(--fg);text-decoration:none;}
.lm .lw-live .lw-kick{color:var(--lm-live);}
.lm .lw-lic,.lm .lw-cic{width:44px;height:44px;border-radius:50%;flex:none;display:grid;place-items:center;background:var(--lm-raise);color:var(--acc);}
.lm .lw-live .lw-lic{color:var(--lm-live);}
.lm .lw-lt,.lm .lw-ct{flex:1;min-width:0;}
.lm .lw-lt b,.lm .lw-ct b{display:block;margin-top:3px;font:700 15px/1.25 var(--mb-ui);}
.lm .lw-ct b{margin-top:0;}
.lm .lw-lt small,.lm .lw-ct small{display:block;margin-top:2px;font:400 13px/1.35 var(--mb-ui);color:var(--fg2);}
.lm .lw-card{display:flex;align-items:center;gap:12px;margin:28px var(--lw-x) 0;padding:16px;border-radius:18px;background:var(--s1);}
.lm .lw-cardl{display:flex;align-items:center;gap:14px;flex:1;min-width:0;color:var(--fg);text-decoration:none;}
.lm .lw-card .lw-pill{background:var(--lm-raise);border-color:transparent;}
/* the latest, on a rounded card */
.lm .lw-hero{position:relative;display:block;margin:16px var(--lw-x) 0;height:252px;border-radius:20px;overflow:hidden;background:var(--s2);color:#fff;
  text-decoration:none;}
.lm .lw-img{position:absolute;inset:0;display:block;}
.lm .lw-img>*,.lm .lw-th>.mb-ph,.lm .lw-th>.mb-art,.lm .lw-po>.mb-ph,.lm .lw-po>.mb-art,.lm .lw-aart>*{position:absolute;inset:0;width:100%;
  height:100%;border-radius:0;aspect-ratio:auto;margin:0;}
.lm .lw img{display:block;width:100%;height:100%;object-fit:cover;}
.lm .lw-hero .mb-art-title,.lm .lw-hero .mb-titled b,.lm .lw-th .mb-art-title,.lm .lw-th .mb-titled b,.lm .lw-shero .mb-art-title,
.lm .lw-shero .mb-titled b,.lm .lw-pv .mb-art-title,.lm .lw-pv .mb-titled b,.lm .lw-aart .mb-art-title,.lm .lw-aart .mb-titled b,
.lm .lw .mb-art-kick,.lm .lw .mb-art-play{display:none;}
.lm .lw-scrim{position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,0) 38%,rgba(0,0,0,.74));}
.lm .lw-hero .lw-tx{position:absolute;left:18px;right:18px;bottom:16px;}
.lm .lw-hero .lw-kick,.lm .lw-shero .lw-kick{color:#fff;opacity:.88;}
.lm .lw-hero h2{margin:9px 0 5px;font:400 31px/1.08 var(--mb-serif);font-weight:var(--lm-dw,400);letter-spacing:-.02em;
  font-variation-settings:var(--lm-dvar,normal);font-stretch:var(--lm-dst,100%);color:#fff;text-wrap:balance;}
.lm .lw-hm{display:block;font:500 13.5px/1.35 var(--mb-ui);opacity:.9;}
.lm .lw-hero .mb-sample{position:absolute;top:12px;left:12px;z-index:1;}
/* rails and rows */
.lm .lw-sh{display:flex;align-items:baseline;justify-content:space-between;padding:26px var(--lw-x) 12px;}
.lm .lw-sh h2{margin:0;font:750 18px/1.2 var(--mb-ui);letter-spacing:-.012em;color:var(--fg);}
.lm .lw-rail{display:flex;gap:12px;overflow-x:auto;padding:0 var(--lw-x) 2px;scroll-snap-type:x mandatory;scroll-padding-inline:var(--lw-x);scrollbar-width:none;}
.lm .lw-rail::-webkit-scrollbar{display:none;}
.lm .lw-cw{flex:none;width:222px;scroll-snap-align:start;color:var(--fg);text-decoration:none;}
.lm .lw-th{position:relative;display:block;overflow:hidden;background:var(--s2);}
.lm .lw-cw .lw-th{height:125px;border-radius:14px;}
.lm .lw-cw b{display:block;margin-top:8px;font:650 14.5px/1.3 var(--mb-ui);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.lm .lw-cw small{display:block;margin-top:2px;font:400 12.5px/1.35 var(--mb-ui);color:var(--fg2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.lm .lw-bar{position:absolute;left:0;right:0;bottom:0;z-index:1;height:4px;background:rgba(255,255,255,.45);}
.lm .lw-bar i{display:block;height:100%;background:var(--acc-fill);}
.lm .lw-bar[hidden]{display:none;}
.lm .lw-mrow,.lm .lw-prow{display:flex;align-items:center;gap:14px;width:100%;padding:8px var(--lw-x);color:var(--fg);text-decoration:none;}
.lm .lw-mrow .lw-th{width:112px;height:63px;border-radius:10px;flex:none;}
.lm .lw-dur{position:absolute;right:5px;bottom:7px;z-index:2;height:18px;padding:0 6px;border-radius:9px;background:rgba(0,0,0,.65);color:#fff;
  font:650 10.5px/18px var(--mb-ui);font-style:normal;font-variant-numeric:tabular-nums;}
.lm .lw-dur[hidden]{display:none;}
.lm .lw-mt{flex:1;min-width:0;}
.lm .lw-mt b{display:block;font:650 15px/1.3 var(--mb-ui);}
.lm .lw-mt small{display:block;margin-top:2px;font:400 12.5px/1.35 var(--mb-ui);color:var(--fg2);}
.lm .lw-all{display:flex;align-items:center;justify-content:center;gap:4px;margin:10px var(--lw-x) 0;height:44px;border-radius:14px;background:var(--s1);
  color:var(--fg);font:650 14px/1 var(--mb-ui);text-decoration:none;}
/* nothing posted yet */
.lm .lw-soon{margin:20px var(--lw-x) 0;padding:22px 20px;border-radius:20px;background:var(--lm-tint);}
.lm .lw-soon h2{margin:10px 0 0;font:400 28px/1.1 var(--mb-serif);font-weight:var(--lm-dw,400);letter-spacing:-.02em;color:var(--fg);}
.lm .lw-soon p:last-child{margin:10px 0 0;font:400 14.5px/1.5 var(--mb-ui);color:var(--fg2);}
.lm .lw-verse{margin-top:24px;}
/* Series: posters two across */
.lm .lw-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px 12px;padding:18px var(--lw-x) 0;}
.lm .lw-ser{display:block;min-width:0;color:var(--fg);text-decoration:none;}
.lm .lw-po{position:relative;display:block;height:222px;border-radius:14px;overflow:hidden;background:var(--s2);}
.lm .lw-po .lw-scrim{background:linear-gradient(180deg,rgba(0,0,0,0) 30%,rgba(0,0,0,.72));}
.lm .lw-ser.is-own .lw-scrim{display:none;}
.lm .lw-po .mb-art-title,.lm .lw-po .mb-titled b{display:none;}
.lm .lw-po>b{position:absolute;left:12px;right:10px;bottom:12px;z-index:1;color:#fff;font:400 23px/1.06 var(--mb-serif);
  font-weight:var(--lm-dw,400);letter-spacing:-.01em;font-variation-settings:var(--lm-dvar,normal);overflow-wrap:anywhere;}
.lm .lw-ser strong{display:block;margin-top:8px;font:650 14.5px/1.3 var(--mb-ui);}
.lm .lw-ser small{display:block;margin-top:6px;font:400 12.5px/1.35 var(--mb-ui);color:var(--fg2);}
.lm .lw-ser strong+small{margin-top:2px;}
/* a series: the poster big, with Back on it */
.lm .lw-shero{position:relative;height:330px;overflow:hidden;background:var(--s2);color:#fff;}
.lm .lw-shero .lw-scrim{background:linear-gradient(180deg,rgba(0,0,0,.25) 0,rgba(0,0,0,0) 30%,rgba(0,0,0,.78));}
.lm .lw-shero .lw-tx{position:absolute;left:var(--lw-x);right:var(--lw-x);bottom:20px;}
.lm .lw-shero h1{margin:10px 0 0;font:400 44px/1.02 var(--mb-serif);font-weight:var(--lm-dw,400);letter-spacing:-.025em;
  font-variation-settings:var(--lm-dvar,normal);font-stretch:var(--lm-dst,100%);color:#fff;text-wrap:balance;}
.lm .lw-fab{position:absolute;top:calc(10px + env(safe-area-inset-top,0px));left:12px;z-index:3;width:40px;height:40px;border-radius:50%;
  display:grid;place-items:center;background:rgba(255,255,255,.92);color:#111;box-shadow:0 2px 10px rgba(0,0,0,.12);}
.lm .lw-about{margin:0;padding:16px var(--lw-x) 0;font:400 15px/1.55 var(--mb-ui);color:var(--fg2);text-wrap:pretty;}
.lm .lw-sbtns{padding-top:14px;}
.lm .lw-parts{padding-top:10px;}
.lm .lw-prow{padding:10px var(--lw-x);}
.lm .lw-prow .lw-th{width:96px;height:54px;border-radius:10px;flex:none;}
.lm .lw-prow .lw-bar{height:3px;background:none;}
.lm .lw-k2{display:block;font:700 10.5px/1 var(--mb-ui);letter-spacing:.1em;text-transform:uppercase;color:var(--fg3);}
.lm .lw-prow .lw-k2+b{margin-top:5px;}
.lm .lw-prow.is-now b{color:var(--acc);}
.lm .lw-ok{flex:none;color:var(--lm-mint-ink);}
.lm .lw-ok[hidden]{display:none;}
/* a message: the player edge to edge, Back on it */
.lm .lw-pv{position:relative;padding-top:env(safe-area-inset-top,0px);background:#000;color:#fff;}
.lm .lw-pv .lw-fab{background:rgba(0,0,0,.42);color:#fff;box-shadow:none;}
.lm .lw-vid{position:relative;aspect-ratio:16/9;}
.lm .lw-vid iframe{position:absolute;inset:0;width:100%;height:100%;border:0;}
.lm .lw-still{position:relative;aspect-ratio:16/9;display:grid;place-items:center;}
.lm .lw-still .lw-scrim{background:rgba(0,0,0,.35);}
.lm .lw-out{position:relative;z-index:1;}
.lm .lw-none{position:relative;z-index:1;margin:0 24px;font:500 14.5px/1.4 var(--mb-ui);text-align:center;color:#fff;}
.lm .lw-aud{position:relative;display:grid;grid-template-columns:110px 1fr;gap:16px;align-items:center;min-height:232px;padding:56px var(--lw-x) 64px;
  background:#151513;}
.lm .lw-aart{position:relative;display:block;width:110px;height:110px;border-radius:14px;overflow:hidden;background:#2a2a28;}
.lm .lw-atx{min-width:0;}
.lm .lw-aud .lw-kick{color:var(--acc-lit,var(--acc));}
.lm .lw-atx b{display:block;margin-top:6px;font:400 22px/1.15 var(--mb-serif);font-weight:var(--lm-dw,400);color:#fff;overflow-wrap:anywhere;}
.lm .lw-actl{display:flex;align-items:center;gap:18px;margin-top:14px;}
.lm .lw-actl[hidden],.lm .lw-scrub[hidden]{display:none;}
.lm .lw-big{width:52px;height:52px;border:0;border-radius:50%;padding:0;display:grid;place-items:center;background:#fff;color:#111;cursor:pointer;}
.lm .lw-big .pa,.lm .lw-pv.is-playing .lw-big .pl{display:none;}
.lm .lw-pv.is-playing .lw-big .pa{display:block;}
.lm .lw-sk{position:relative;width:44px;height:44px;border:0;padding:0;display:grid;place-items:center;background:none;color:#fff;cursor:pointer;}
.lm .lw-sk i{position:absolute;top:17px;font:700 9px/1 var(--mb-ui);font-style:normal;}
.lm .lw-native{grid-column:1/-1;width:100%;}
.lm .lw-scrub{position:absolute;left:14px;right:14px;bottom:12px;font:600 11.5px/1 var(--mb-ui);font-variant-numeric:tabular-nums;}
.lm .lw-scrub input{display:block;width:100%;height:24px;margin:0 0 2px;background:none;cursor:pointer;-webkit-appearance:none;appearance:none;}
.lm .lw-scrub input::-webkit-slider-runnable-track{height:3px;border-radius:2px;
  background:linear-gradient(to right,var(--acc-fill) var(--p,0%),rgba(255,255,255,.35) var(--p,0%));}
.lm .lw-scrub input::-webkit-slider-thumb{-webkit-appearance:none;width:12px;height:12px;margin-top:-4.5px;border:0;border-radius:50%;background:#fff;}
.lm .lw-scrub input::-moz-range-track{height:3px;border-radius:2px;background:rgba(255,255,255,.35);}
.lm .lw-scrub input::-moz-range-progress{height:3px;border-radius:2px;background:var(--acc-fill);}
.lm .lw-scrub input::-moz-range-thumb{width:12px;height:12px;border:0;border-radius:50%;background:#fff;}
.lm .lw-scrub input:focus-visible{outline:2px solid #fff;outline-offset:2px;}
.lm .lw-tm{display:flex;justify-content:space-between;opacity:.9;}
.lm .lw-pinfo{padding:16px var(--lw-x) 0;}
.lm .lw-pinfo .lw-kick{color:var(--fg2);}
.lm .lw-pinfo h1{margin:8px 0 4px;font:400 29px/1.12 var(--mb-serif);font-weight:var(--lm-dw,400);letter-spacing:-.02em;
  font-variation-settings:var(--lm-dvar,normal);font-stretch:var(--lm-dst,100%);color:var(--fg);text-wrap:balance;}
.lm .lw-meta{margin:0;font:400 14px/1.4 var(--mb-ui);color:var(--fg2);}
.lm .lw-pacts{display:grid;grid-template-columns:repeat(var(--n,4),minmax(0,1fr));margin:16px var(--lw-x) 0;padding:6px 0;
  border-top:1px solid var(--lm-line);border-bottom:1px solid var(--lm-line);}
.lm .lw-pa{display:flex;flex-direction:column;align-items:center;gap:5px;width:100%;padding:8px 0;border:0;background:none;color:var(--fg);
  font:600 12.5px/1 var(--mb-ui);text-decoration:none;cursor:pointer;}
.lm .lw-pa.on,.lm .lw-pa[aria-pressed=true]{color:var(--acc);}
/* the tabs: radios, so they switch with no script */
.lm .lw-tabs{position:relative;}
.lm .lw-tr{position:absolute;opacity:0;width:1px;height:1px;margin:0;pointer-events:none;}
.lm .lw-tls{display:flex;gap:24px;padding:0 var(--lw-x);margin-top:6px;border-bottom:1px solid var(--lm-line);}
.lm .lw-tl{height:46px;display:flex;align-items:center;font:650 14.5px/1 var(--mb-ui);color:var(--fg3);border-bottom:2px solid transparent;
  margin-bottom:-1px;cursor:pointer;white-space:nowrap;}
.lm .lw-panel{display:none;}
.lm .lw-panel.lw-one{display:block;padding-top:4px;}
.lm #lw-t-about:checked~.lw-tls .lw-tl-about,.lm #lw-t-discuss:checked~.lw-tls .lw-tl-discuss,
.lm #lw-t-series:checked~.lw-tls .lw-tl-series{color:var(--fg);border-bottom-color:var(--acc-fill);}
.lm #lw-t-about:checked~.lw-p-about,.lm #lw-t-discuss:checked~.lw-p-discuss,.lm #lw-t-series:checked~.lw-p-series{display:block;}
.lm #lw-t-about:focus-visible~.lw-tls .lw-tl-about,.lm #lw-t-discuss:focus-visible~.lw-tls .lw-tl-discuss,
.lm #lw-t-series:focus-visible~.lw-tls .lw-tl-series{outline:2px solid var(--acc);outline-offset:2px;}
.lm .lw-sum{margin:0;padding:16px var(--lw-x) 0;font:400 17px/1.6 var(--lm-read,var(--mb-serif));color:var(--fg);text-wrap:pretty;white-space:pre-line;}
.lm .lw-scrip{display:flex;align-items:center;gap:14px;margin:16px var(--lw-x) 0;padding:14px;border-radius:16px;background:var(--lm-paper);
  color:var(--lm-ink);text-decoration:none;}
.lm .lw-sic{width:40px;height:40px;border-radius:12px;flex:none;display:grid;place-items:center;background:#fff;color:var(--lm-ink2);}
.lm .lw-st{flex:1;min-width:0;}
.lm .lw-st b{display:block;font:700 15px/1.25 var(--mb-ui);color:var(--lm-ink);}
.lm .lw-st small{display:block;margin-top:2px;font:400 12.5px/1.35 var(--mb-ui);color:var(--lm-ink2);}
.lm .lw-scrip .lm-chev{color:var(--lm-ink2);}
.lm .lw-qs{list-style:none;margin:0;padding:8px var(--lw-x) 0;counter-reset:lwq;}
.lm .lw-qs li{counter-increment:lwq;display:flex;gap:14px;padding:14px 0;border-bottom:1px solid var(--lm-line);font:400 15.5px/1.45 var(--mb-ui);
  color:var(--fg);}
.lm .lw-qs li::before{content:counter(lwq);flex:none;width:28px;height:28px;border-radius:50%;background:var(--lm-tint-12);color:var(--acc);
  font:700 13px/28px var(--mb-ui);text-align:center;}
.lm .lw-talk{display:grid;gap:8px;padding:14px var(--lw-x) 0;}
/* a phone: the media pages start at the picture, Back sits on it */
@media (max-width:999px){
  .lm:has(.lw-pv) .mb-top,.lm:has(.lw-shero) .mb-top{display:none;}
  .lm .lw-shero{padding-top:env(safe-area-inset-top,0px);}
}
@media (min-width:1000px){
  .lm .lw-fab{display:none;}
  .lm .lw-pv,.lm .lw-shero{border-radius:20px;overflow:hidden;margin:12px var(--lw-x) 0;}
}
/* dark: the paper card and the Back on a picture stay as they are; the rest is tokens */
.lm.lm-dark .lw-sic{background:rgba(255,255,255,.7);}
@media (prefers-color-scheme:dark){.lm.lm-auto .lw-sic{background:rgba(255,255,255,.7);}}
@media (prefers-reduced-motion:no-preference){
  .lm .lw-pill,.lm .lw-cw,.lm .lw-mrow,.lm .lw-prow,.lm .lw-ser,.lm .lw-hero,.lm .lw-pa,.lm .lw-scrip,.lm .lw-big{
    transition:transform .45s var(--lm-spring,ease),background-color .25s,color .25s;}
  .lm .lw-pill:active,.lm .lw-pa:active,.lm .lw-big:active{transform:scale(.94);}
  .lm .lw-cw:active,.lm .lw-mrow:active,.lm .lw-prow:active,.lm .lw-ser:active,.lm .lw-hero:active,.lm .lw-scrip:active{transform:scale(.985);}
}
.lm .lw-seg a:focus-visible,.lm .lw-pill:focus-visible,.lm .lw-cw:focus-visible,.lm .lw-mrow:focus-visible,.lm .lw-prow:focus-visible,
.lm .lw-ser:focus-visible,.lm .lw-hero:focus-visible,.lm .lw-pa:focus-visible,.lm .lw-scrip:focus-visible,.lm .lw-fab:focus-visible,
.lm .lw-big:focus-visible,.lm .lw-sk:focus-visible,.lm .lw-all:focus-visible,.lm .lw-cardl:focus-visible,.lm .lw-live:focus-visible
{outline:2px solid var(--acc);outline-offset:2px;}
""")
