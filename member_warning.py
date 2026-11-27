"""
member_warning.py — "Pastor will never ask you for gift cards."

The most common church scam isn't a website card. It's a text or an email to
members, from a number or address the church can't see, that uses the pastor's
name: "Are you available? I need a favour... gift cards for the outreach,
keep it quiet." (inbound-safety proposal, L7; Kevin 2026-11-27: "the member
warning per church, offered by Chief".)

The defence is members who already know. This module keeps one church's
choice and the words. Sending is the office's own tap, through the routes the
app already has, each with its own gate:

    News post         POST /church/news                     (church_news)
    App note          POST /member-portal/{id}/announce     (member_push)
    Text (optional)   POST /sms/broadcast                   (sms_routing)

and a line on the Give page (hosted /give, a hand-built site's give form, the
member app's Give) when the church turns it on.

OFF BY DEFAULT for every church. Nothing here sends anything, and nothing
shows on a Give page until the church saves give_line on.

    settings.member_warning = {on, pastor, give_line, sent_at, sent_by, sent,
                               declined}

ROUTES (a Manager seat and up, as an announcement)
    GET /church/member-warning?business_id=    the choice, the words, the
                                               suggested pastor's name
    PUT /church/member-warning?business_id=    {on?, pastor?, give_line?,
                                               sent?: [parts sent], declined?}

CHIEF offers it (turn_line): only at a church that hasn't sent one or said
"don't offer this again" (declined), only on a turn that talks about scams,
fake messages or gift cards, and not when gift cards come up only as giving
to record. It points to the page; it never sends.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

import sb_clients
from auth_supabase import UserSession
from business_access import business_access

router = APIRouter(tags=["church"])

KEY = "member_warning"
MIN_ROLE = "manager"
PASTOR_MAX = 40
PARTS = ("news", "app", "text")
# member_push's own limits for an app note.
APP_TITLE_MAX, APP_BODY_MAX = 60, 180


def _plain(v: Any) -> str:
    return " ".join(str(v or "").split())


def settings_of(business: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    s = ((business or {}).get("settings") or {}).get(KEY)
    s = s if isinstance(s, dict) else {}
    sent = s.get("sent") if isinstance(s.get("sent"), list) else []
    return {
        "on": s.get("on") is True,
        "pastor": _plain(s.get("pastor"))[:PASTOR_MAX],
        "give_line": s.get("give_line") is True,
        "sent_at": s.get("sent_at") if isinstance(s.get("sent_at"), str) else None,
        "sent_by": _plain(s.get("sent_by"))[:120],
        "sent": [p for p in sent if p in PARTS],
        "declined": s.get("declined") is True,
    }


def suggested_pastor(business: Dict[str, Any]) -> str:
    """"Pastor James" from the church's senior role, or ""."""
    try:
        import guest_path_weeks as gpw
        import member_pastor
        p = member_pastor.who(business)
        if not p:
            return ""
        return gpw.pastor_signature(p.get("name") or "", p.get("title") or "")[:PASTOR_MAX]
    except Exception:  # noqa: BLE001 — no suggestion, never a broken page
        return ""


def pastor_of(business: Dict[str, Any]) -> str:
    """The name the words use: the church's own, else the suggestion, else "Our pastor"."""
    return settings_of(business)["pastor"] or suggested_pastor(business) or "Our pastor"


def words(pastor: str, church: str) -> Dict[str, str]:
    """The ready words, filled in. Plain and short: a member reads it once and
    remembers one thing."""
    p = _plain(pastor) or "Our pastor"
    first_ref = p if p.lower() not in ("our pastor", "the pastor") else "our pastor"
    church = _plain(church) or "the church"
    one = (f"{p} will never ask you for gift cards, money or codes by text or email. "
           f"If someone does, it isn't {first_ref}. Tell the office.")
    return {
        "title": f"{p} will never ask you for gift cards"[:120],
        "news": (f"{p} will never text or email you to ask for gift cards, money, codes or a favour that has "
                 f"to stay quiet. If a message like that uses {first_ref}'s name, it isn't from {first_ref}: "
                 "don't reply, don't click anything in it, and tell the church office. "
                 f"When you give to {church}, give only on our own Give page or in person."),
        "app_title": f"A note from {church}"[:APP_TITLE_MAX],
        "app_body": one[:APP_BODY_MAX],
        "text": one,
        "give": (f"{p} will never ask you to give by text, email or gift card. "
                 "Give only here or in person."),
    }


def give_line_html(business: Optional[Dict[str, Any]]) -> str:
    """The Give page's line, escaped, or "" (off unless the church turned it on)."""
    try:
        if not business:
            return ""
        s = settings_of(business)
        if not (s["on"] and s["give_line"]):
            return ""
        text = words(pastor_of(business), business.get("name") or "")["give"]
        return ('<p class="gv-safe" role="note" style="margin:14px 0 0;padding:10px 12px;border-radius:10px;'
                'font-size:13.5px;line-height:1.45;text-align:left;'
                'background:color-mix(in srgb, currentColor 7%, transparent)">'
                f'{html.escape(text)}</p>')
    except Exception:  # noqa: BLE001 — a Give page never breaks for a line
        return ""


def _business(bid: str) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{bid}&select=id,name,type,owner_id,settings&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, "That couldn't be read just now. Try again in a minute.")
    if not rows:
        raise HTTPException(404, "business not found")
    return rows[0]


def view(business: Dict[str, Any]) -> Dict[str, Any]:
    s = settings_of(business)
    suggested = suggested_pastor(business)
    pastor = s["pastor"] or suggested or "Our pastor"
    return {**s, "suggested_pastor": suggested, "words": words(pastor, business.get("name") or ""),
            "limits": {"app_title": APP_TITLE_MAX, "app_body": APP_BODY_MAX}}


@router.get("/church/member-warning")
def get_warning(business_id: str = Query(...), biz: Dict[str, Any] = Depends(business_access(MIN_ROLE)),
                session: UserSession = Depends(sb_clients.authed_request)):
    import church_follow_up as cfu
    business = _business(str(biz["id"]))
    if not cfu.is_church(business):
        raise HTTPException(404, "This is for churches.")
    return view(business)


@router.put("/church/member-warning")
def put_warning(business_id: str = Query(...), body: Any = Body(default=None),
                biz: Dict[str, Any] = Depends(business_access(MIN_ROLE)),
                session: UserSession = Depends(sb_clients.authed_request)):
    """Save the church's choice, the name, the Give line, "don't offer this
    again", or that it was sent.

    `sent` is the office's own screen reporting which parts it posted (each
    through its own route, with its own gate). Nothing here checks that they
    were delivered: it is a record that stops Chief offering the warning and
    tells the office when it went, never proof that a member got it. Each
    `sent` replaces the list, so the screen sends every part that has gone."""
    import business_settings
    import church_follow_up as cfu
    bid = str(biz["id"])
    business = _business(bid)
    if not cfu.is_church(business):
        raise HTTPException(404, "This is for churches.")
    b = body if isinstance(body, dict) else {}
    cur = dict(((business.get("settings") or {}).get(KEY) or {}))
    if "on" in b:
        cur["on"] = b["on"] is True
    if "pastor" in b:
        name = _plain(b.get("pastor"))
        if len(name) > PASTOR_MAX:
            raise HTTPException(400, f"Keep the name to {PASTOR_MAX} characters.")
        if re.search(r"[<>{}\[\]]", name):
            raise HTTPException(400, "Use just the name, as members know it.")
        cur["pastor"] = name
    if "give_line" in b:
        cur["give_line"] = b["give_line"] is True
    if "declined" in b:
        cur["declined"] = b["declined"] is True
    if isinstance(b.get("sent"), list):
        parts = [p for p in b["sent"] if p in PARTS]
        if parts:
            cur.update(on=True, sent=sorted(set(parts)),
                       sent_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                       sent_by=_plain(getattr(session.user, "email", "") or "").split("@")[0][:120])
    out = business_settings.merge(bid, set={KEY: cur})
    if out is None:
        raise HTTPException(503, "That didn't save. Nothing changed. Try again.")
    business["settings"] = out
    return {"ok": True, **view(business)}


# ─── Chief offers it ──────────────────────────────────────────────────

_SCAM_TALK = re.compile(
    r"\b(scams?|scammers?|scammed|phish\w*|fraud\w*|fake (?:text|message|email|number|account)s?|"
    r"gift ?cards?|impersonat\w*|pretend\w* to be|spoof\w*|someone (?:is )?using (?:my|the pastor'?s|pastor'?s) name)\b",
    re.I)
_GIFT_CARD = re.compile(r"\bgift ?cards?\b", re.I)
# Gift cards as giving to record ("how do we record gift-card offerings?"),
# not as a scam.
_GIVING_TALK = re.compile(
    r"\b(record\w*|log(?:ged|ging)?|enter\w*|count\w*|deposit\w*|receipt\w*|offerings?|tithes?|donat\w*|"
    r"contribution\w*|bookkeep\w*|categor\w*|funds?|statements?)\b", re.I)


def scam_talk(message: str) -> bool:
    """A turn about scams. Gift cards alone, in a turn about recording
    giving, isn't one."""
    m = message or ""
    if not _SCAM_TALK.search(m):
        return False
    if _SCAM_TALK.search(_GIFT_CARD.sub(" ", m)):
        return True
    return not _GIVING_TALK.search(m)


BLOCK = (
    "MEMBER WARNING (this church hasn't sent one): when this conversation is about scams, fake messages using the "
    "pastor's name, gift cards or money asks, offer once to send the church's member warning. It's a ready note, with "
    "the pastor's name filled in, that the pastor will never ask for gift cards, money or codes by text or email. It "
    "goes as a News post and an app note, a text too if they want, and a line on the Give page if they turn it on. "
    "It's the church's choice and nothing goes out until they send it themselves from Members (Needs a look, Warn "
    "your members). Open it with "
    '[ACTION:{"type":"navigate","tab":"operate","sub":"contacts"}] and say where it is. Never say it was sent.\n')


def turn_line(business: Dict[str, Any], user_id: Any, message: str) -> str:
    """The offer, for the turn's tail; '' unless it fits (a church, not sent
    yet, a turn about scams) or on any failure."""
    try:
        if not user_id or not scam_talk(message):
            return ""
        import church_follow_up as cfu
        if not cfu.is_church(business or {}):
            return ""
        s = settings_of(business)
        if s["sent_at"] or s["declined"]:
            return ""
        return BLOCK
    except Exception:  # noqa: BLE001
        return ""
