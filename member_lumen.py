"""member_lumen.py — who sees the member app's new look ("Lumen").

Kevin, 2026-11-18, on the member app at /my: it "feels like ai built it but
not creative designer". After several rounds he approved the "clean Lumen"
mock (version 29, accent level 2): a white page, serif headings, the
church's colour on buttons and the current tab, full-bleed photos, Home ·
Watch · Bible · Connect · Give, Messages from a bubble at the top. It is
built in steps behind this one switch, so nobody sees a half-built page.

THE SWITCH. MEMBER_LUMEN = off | preview | owner | on, preview by default.

  off ...... nobody. Every page is the look members have today.
  preview .. only the platform owner, and only at a church the platform
             owner owns (member_asks.platform_church): their "Preview as a
             member" session (member_portal_preview), or their own member
             sign-in there (the signed-in record's email, or the address
             they signed in with, is PLATFORM_OWNER_EMAIL). Another church's
             owner previewing their own app keeps today's look.
  owner .... every member at the platform owner's own church.
  on ....... every church.

Anything unknown reads as off. A failed read (the church's owner couldn't
be looked up) is a no: members see today's look rather than a new one
nobody switched on.

HOW PAGES ASK. member_portal.serve() decides once per request, after the
session is known, and keeps the answer for the page being drawn (CURRENT):
anything drawing a member page calls here(). Code that has the request and
the session itself can call visible(request, ctx).

COST. off, on and preview for an ordinary member cost no read. The church
owner lookup (member_asks.platform_church) runs only for a preview session
or the platform owner's own address under preview, and for every page
under owner; it is kept ten minutes per server copy.
"""
from __future__ import annotations

import asyncio
import contextvars
import os
from typing import Any, Dict, Mapping, Optional

ENV = "MEMBER_LUMEN"
MODES = ("off", "preview", "owner", "on")
DEFAULT = "preview"

# The page being drawn: whether it wears the new look. member_portal.serve
# sets it per request; a page drawn anywhere else (a POST's reply, the
# sign-in pages before a session) reads the default, today's look.
CURRENT: contextvars.ContextVar[bool] = contextvars.ContextVar("member_lumen", default=False)


def mode() -> str:
    m = (os.environ.get(ENV) or DEFAULT).strip().lower()
    return m if m in MODES else "off"


def _platform_email() -> str:
    import member_asks
    return member_asks._platform_email()


def _platform_church(business_id: Any) -> bool:
    import member_asks
    try:
        return bool(member_asks.platform_church(business_id))
    except Exception:
        return False


def _norm(v: Any) -> str:
    return str(v or "").strip().lower()


def is_platform_owner(session: Optional[Mapping[str, Any]]) -> bool:
    """A real member session (not a preview) whose person is the platform
    owner: the record's email, or the address they signed in with."""
    if not session or session.get("preview") or session.get("unavailable"):
        return False
    want = _platform_email()
    if not want:
        return False
    me = session.get("me") or {}
    claims = session.get("claims") or {}
    return _norm(me.get("email")) == want or _norm(claims.get("em")) == want


def visible(request: Any, ctx: Optional[Mapping[str, Any]]) -> bool:
    """Whether this member page wears the new look.

    ctx = {"business": the church's row (needs "id"),
           "session": member_portal._session_for's answer, or None}.
    `request` is the page's request (kept for callers that have nothing
    else; the decision reads only ctx)."""
    m = mode()
    if m == "off":
        return False
    ctx = ctx or {}
    biz: Dict[str, Any] = dict(ctx.get("business") or {})
    session = ctx.get("session")
    if m == "on":
        return True
    if not biz.get("id"):
        return False
    if m == "owner":
        return _platform_church(biz["id"])
    # preview: the platform owner only, at a church they own.
    if not session or session.get("unavailable") or not session.get("me"):
        return False
    if session.get("preview") or is_platform_owner(session):
        return _platform_church(biz["id"])
    return False


def here() -> bool:
    """Whether the member page being drawn wears the new look (set by
    member_portal.serve for this request)."""
    return bool(CURRENT.get())


def _needs_lookup(ctx: Optional[Mapping[str, Any]]) -> bool:
    """Whether visible() may read the church's owner (member_asks keeps it
    ten minutes, but its first read is a network call: off the event loop)."""
    m = mode()
    if m in ("off", "on"):
        return False
    if m == "owner":
        return True
    session = (ctx or {}).get("session")
    return bool(session and (session.get("preview") or is_platform_owner(session)))


async def decide(request: Any, ctx: Optional[Mapping[str, Any]]) -> bool:
    """visible(), kept for the page being drawn (here()). An ordinary
    member under preview, and off and on, decide without a read."""
    if _needs_lookup(ctx):
        yes = await asyncio.to_thread(visible, request, ctx)
    else:
        yes = visible(request, ctx)
    CURRENT.set(bool(yes))
    return bool(yes)
