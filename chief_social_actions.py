"""
chief_social_actions.py — Chief posts a picture to the business's accounts.

Marketing suite B1 (2026-10-07, Kevin: "This will work. let's build this.").
One verb, post_image:

  [ACTION:{"type":"post_image",
           "image_id":"<uuid>",                     # a design or photo in Media Library; or
           "image":"latest",                        # the newest ready design of the last day; or neither, for words only
           "platforms":["instagram","facebook"],    # optional; default every connected account
           "caption":"Saturday fades, $20. Book at the link.",
           "when":"2026-10-08T09:00:00-04:00"}]     # optional ISO with a zone; null = now

THE POST ITSELF is image_posting.post_image_for: owner only, the design a
ready artwork of THIS business, the JPEG made under the build actor, the
shared door (social_publish_router.send_post), the 24-hour duplicate guard.
This module turns Chief's words into that call and its answer into plain
words, and refuses early, in Chief's words, where the owner can act on it.

WHICH PICTURE. image_id names one. "latest" takes the newest ready design
(generated or composed in Image Studio, not a clip cover, an upload or a
website capture) made in the last 24 hours, and refuses when more than one
was made within ten minutes of the newest: two designs made together are
two plausible answers, so the owner is asked which, with titles and ids.
Neither: a words-only post (Instagram needs a picture, so it is left out
and the answer says so).

CLASS C. A post is public and cannot be recalled once it is out (a scheduled
one can be cancelled until then). action_registry says so; the class-C gate in
_execute_actions treats the owner's request as the approval, holds a voice
turn for a spoken yes, and counts it against the turn's cap.

THE UNATTENDED GATE, as post_clip's (chief_clip_actions): the `_unattended`
mark set by chief_scheduler and by the door on every run nobody asked for in
this turn. Nothing records an owner's approval of a picture post's words,
accounts and time, so every unattended run is held, before anything is read,
and Chief never posts on its own initiative. A later time needs no
scheduler: `when` goes with the post to the posting service, where it can be
cancelled in Build, Social Media. schedule_action refuses to wrap post_image.

THE ACTING USER is the signed-in person driving this chat turn
(chief_of_staff._TURN_USER_ID). No turn, no post.

NEVER TWICE. The request id is derived from the turn (image_studio's turn id),
the picture, the accounts, the caption and the time. The same turn asking
twice returns the first post; the day's duplicate guard is the second line.

The answer says Sent or Scheduled, never Posted: the networks report back
later, in Build, Social Media.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import HTTPException

from chief_clip_actions import Refusal, _and, _network, _platform, _quoted, _say_time

logger = logging.getLogger("chief_of_staff")

VERB = "post_image"
SOCIAL_NAV = {"tab": "build", "sub": "social-media"}
LIBRARY_NAV = {"tab": "build", "page": "media-library"}
MAX_ACCOUNTS = 10          # the Post door's own limit (social_publish_router.PublishBody)
LATEST_WINDOW = timedelta(hours=24)
TOGETHER = timedelta(minutes=10)
LATEST_SCAN = 20
NOT_POSTED = "Not posted"

UNATTENDED = ("A post goes out only when you ask me to post it, and this came from a "
              "scheduled or automatic run, so nothing was posted. Ask me to post it "
              "(I can set the time), or post it from Build, Social Media.")


def _refused(r: Refusal) -> Dict[str, Any]:
    # Both result and label, always: a missing result blanks the app.
    return {"type": VERB, "result": r.result, "label": r.label, "nav": r.nav,
            "ok": False, "failed": True, **r.extra}


# ─── the gates, each a plain refusal ─────────────────────────────────

def _acting_user() -> str:
    import chief_of_staff as cos
    uid = str(cos._TURN_USER_ID.get() or "")
    if not uid:
        raise Refusal("I can only post for the business when its owner asks me in chat, "
                      "so nothing was posted.", "Ask me in chat to post")
    return uid


async def _require_owner(business_id: str, user_id: str) -> None:
    import image_posting
    try:
        await asyncio.to_thread(image_posting._require_owner, business_id, user_id)
    except HTTPException as e:
        if e.status_code == 403:
            raise Refusal("Only the business owner can post for it, so nothing was posted.",
                          "Only the owner can post")
        raise Refusal("I couldn't confirm this business just now, so nothing was posted. "
                      "Try again in a minute.", NOT_POSTED)


async def _require_posting(business_id: str) -> None:
    import social_publish_router as social
    try:
        await asyncio.to_thread(social._require_pilot, business_id)
    except HTTPException as e:
        if e.status_code == 503:
            raise Refusal("Posting to social accounts isn't set up yet, so nothing was posted.",
                          "Posting isn't set up yet")
        raise Refusal("Posting to your social accounts isn't switched on for this business yet, "
                      "so nothing was posted.", "Posting isn't switched on yet")


def _when(raw: Any) -> Optional[datetime]:
    if raw is None or (isinstance(raw, str) and raw.strip().lower() in ("", "now")):
        return None
    try:
        at = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
    except ValueError:
        raise Refusal(f"I couldn't read the time {str(raw)[:40]!r}, so nothing was posted. "
                      "Tell me the day and time again.", NOT_POSTED)
    if at.tzinfo is None:
        raise Refusal("I need that time with its time zone, so nothing was posted yet. "
                      "Tell me the time again.", NOT_POSTED)
    if at <= datetime.now(timezone.utc):
        raise Refusal(f"{_say_time(at)} has already passed, so nothing was posted. "
                      "Tell me a time later than now, or ask me to post it now.",
                      "That time has passed")
    return at


def _connections(business_id: str) -> List[Dict[str, Any]]:
    import sb_clients
    rows = sb_clients.sb_get_as_service(
        f"/social_connections?business_id=eq.{business_id}&status=eq.connected"
        f"&select=id,platform,username,provider_account_id&order=connected_at.asc")
    if rows is None:
        # A failed read is not "nothing connected".
        raise Refusal("I couldn't read your connected accounts just now, so nothing was posted. "
                      "Try again in a minute.", NOT_POSTED)
    if not rows:
        raise Refusal("No social account is connected yet, so nothing was posted. Connect an "
                      "account in Build, Social Media, then ask me again.",
                      "Connect an account in Build, Social Media", SOCIAL_NAV)
    return rows


def _pick_accounts(rows: List[Dict[str, Any]], platforms: Any) -> List[Dict[str, Any]]:
    """Every connected account, or those on the networks asked for. A network
    asked for with no account is refused, never quietly dropped."""
    if isinstance(platforms, str):
        platforms = [platforms]
    wanted = [p for p in dict.fromkeys(_platform(x) for x in (platforms or [])) if p]
    chosen = rows if not wanted else [r for r in rows if str(r.get("platform") or "").lower() in wanted]
    missing = [p for p in wanted if not any(str(r.get("platform") or "").lower() == p for r in rows)]
    if missing:
        have = _and([f"{_network(r.get('platform'))} ({r.get('username')})" if r.get("username")
                     else _network(r.get("platform")) for r in rows])
        nets = _and([_network(p) for p in missing])
        raise Refusal(f"No {nets} account is connected, so nothing was posted. Connected now: "
                      f"{have}. Connect {nets} in Build, Social Media, or tell me to post to the "
                      "accounts you have.", f"Connect {nets} in Build, Social Media", SOCIAL_NAV)
    if len(chosen) > MAX_ACCOUNTS:
        raise Refusal(f"That is {len(chosen)} accounts at once; I can post to {MAX_ACCOUNTS} at a "
                      "time, so nothing was posted. Tell me which networks.", "Tell me which networks")
    return chosen


# ─── which picture ───────────────────────────────────────────────────

def _created(row: Dict[str, Any]) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(row.get("created_at") or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def _ago(row: Dict[str, Any]) -> str:
    at = _created(row)
    if not at:
        return ""
    minutes = max(0, int((datetime.now(timezone.utc) - at).total_seconds() // 60))
    if minutes < 1:
        return "made just now"
    if minutes < 60:
        return f"made {minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    return f"made {hours} hour{'s' if hours != 1 else ''} ago"


def _named(row: Dict[str, Any]) -> str:
    import image_posting
    return _quoted(image_posting.design_title(row) or "your design")


def _latest(business_id: str) -> Dict[str, Any]:
    """The newest ready design of the last day, when it is the only one made
    around that time."""
    import image_posting
    import sb_clients
    since = (datetime.now(timezone.utc) - LATEST_WINDOW).isoformat().replace("+", "%2B")
    rows = sb_clients.sb_get_as_service(
        f"/image_artworks?business_id=eq.{business_id}&status=eq.ready&storage_path=not.is.null"
        f"&created_at=gte.{since}&director->>clip_id=is.null"
        f"&or=(model.not.is.null,prompt.like.EDITABLE_FLYER_V1*)"
        f"&select={image_posting.COLUMNS}&order=created_at.desc&limit={LATEST_SCAN}")
    if rows is None:
        raise Refusal("I couldn't read your designs just now, so nothing was posted. "
                      "Try again in a minute.", NOT_POSTED)
    rows = [r for r in rows if str(r.get("business_id")) == str(business_id) and not r.get("clip_id")]
    if not rows:
        raise Refusal("I couldn't find a finished design from the last day, so nothing was posted. "
                      "Tell me which design to post (it is in Media Library), or ask me to make one.",
                      "Which design?", LIBRARY_NAV)
    newest = _created(rows[0])
    together = [r for r in rows if newest and _created(r) and newest - _created(r) <= TOGETHER]
    if len(together) > 1:
        some = together[:5]
        listed = "; ".join(f"{_named(r)} ({', '.join(x for x in (_ago(r), 'id ' + str(r.get('id'))) if x)})"
                           for r in some)
        more = f" and {len(together) - 5} more" if len(together) > 5 else ""
        raise Refusal(f"More than one design was made around the same time: {listed}{more}. "
                      "Which one should I post? Nothing was posted.", "Which design?", LIBRARY_NAV,
                      designs=[{"image_id": r.get("id"), "title": image_posting.design_title(r),
                                "created_at": r.get("created_at")} for r in some])
    return rows[0]


def _picture(business_id: str, action: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The picture asked for, or None for a words-only post."""
    import image_posting
    raw_id = str(action.get("image_id") or "").strip()
    pick = str(action.get("image") or "").strip()
    if not raw_id and pick:
        try:
            raw_id = str(UUID(pick))
        except ValueError:
            if pick.lower() not in ("latest", "newest", "last"):
                raise Refusal("Which design should I post? Tell me which one in Media Library. "
                              "Nothing was posted.", "Which design?", LIBRARY_NAV)
    if raw_id:
        try:
            return image_posting.ready_artwork(business_id, raw_id)
        except HTTPException as e:
            if e.status_code == 404:
                raise Refusal("I couldn't find that design in your Media Library, so nothing was "
                              "posted. Tell me which one to post.", "Design not found", LIBRARY_NAV)
            if e.status_code == 409 and "still being made" in str(e.detail):
                raise Refusal("That design is still being made. I can post it once it is ready. "
                              "Nothing was posted.", "Design not ready yet", LIBRARY_NAV)
            if e.status_code == 409:
                raise Refusal("That design didn't finish, so I can't post it. Nothing was posted.",
                              "Design not finished", LIBRARY_NAV)
            raise Refusal("I couldn't read that design just now, so nothing was posted. "
                          "Try again in a minute.", NOT_POSTED)
    if pick:
        return _latest(business_id)
    return None


def _request_id(business_id: str, image_id: Optional[str], accounts: List[Dict[str, Any]],
                caption: str, when: Optional[str]) -> UUID:
    """The same turn asking for the same post gets the same id, so a retried
    turn never posts twice. No turn: a fresh id, and the same-post-today
    check still stands."""
    import image_studio
    from chief_code import turn_scope
    turn = image_studio.turn_id.get() or (turn_scope.get() or {}).get("turn_id") or ""
    if not turn:
        return uuid4()
    blob = json.dumps({"business": business_id, "turn": str(turn), "image": image_id,
                       "accounts": sorted(str(a["id"]) for a in accounts),
                       "caption": caption, "when": when}, sort_keys=True)
    return uuid5(NAMESPACE_URL, "chief-post-image:" + blob)


# ─── the answer, in plain words ──────────────────────────────────────

def _left_out(out: Dict[str, Any], what: str) -> str:
    """Why some accounts were left out, as one sentence (or nothing)."""
    import image_posting
    why = image_posting.why_dropped(out.get("dropped") or [])
    if not why:
        return ""
    return f" {'; '.join(why)}, so {what} didn't go there."


def _answer(out: Dict[str, Any], row: Optional[Dict[str, Any]], caption: str,
            at: Optional[datetime]) -> Dict[str, Any]:
    pub = out.get("publication") or {}
    targets = pub.get("targets") or []
    nets = _and(list(dict.fromkeys(_network(t.get("platform")) for t in targets)))
    where = _and([f"{_network(t.get('platform'))} ({t.get('username')})" if t.get("username")
                  else _network(t.get("platform")) for t in targets])
    image = out.get("image") or {}
    kind = ("design" if image.get("design") else "picture") if row else "post"
    thing = (_quoted(image.get("title")) if image.get("title") else f"your {kind}") if row else "your post"
    shown = caption if len(caption) <= 280 else caption[:280] + "…"
    said = "the caption " + _quoted(shown) if caption else "no caption"
    if not row:
        said = "the words " + _quoted(shown)
    left = _left_out(out, f"the {kind}" if row else "this post")
    base = {"type": VERB, "ok": True, "nav": SOCIAL_NAV, "image_id": (image or {}).get("id"),
            "publication": pub, "dropped": out.get("dropped") or []}
    if out.get("already"):
        if pub.get("status") == "scheduled":
            text = (f"{thing[0].upper() + thing[1:]} was already scheduled to {where} with these words, so I "
                    "didn't schedule it twice. It shows in Build, Social Media, where it can be "
                    "cancelled until it goes out.")
        else:
            text = (f"{thing[0].upper() + thing[1:]} already went to {where} with these words, so I didn't "
                    "post it twice. How each post went shows in Build, Social Media.")
        return {**base, "already": True, "result": text, "label": "Already sent, not posted twice"}
    if pub.get("status") == "scheduled" and at is not None:
        when = _say_time(at)
        return {**base, "already": False, "scheduled_at": pub.get("scheduled_at"),
                "result": (f"Scheduled {thing} for {when} on {where}, with {said}.{left} It is "
                           "waiting with the posting service, and you can cancel it in Build, "
                           "Social Media until it goes out. How each post goes shows there."),
                "label": f"Scheduled your {kind} for {when}"}
    return {**base, "already": False,
            "result": (f"Sent {thing} to {where} with {said}.{left} Each network takes a minute or so "
                       "to put it up; the link to each live post, or any network's error, shows in "
                       "Build, Social Media."),
            "label": f"Sent your {kind} to {nets}"}


def _from_core(e: HTTPException) -> Refusal:
    """image_posting's refusals are already plain words, written for the
    owner; a few are said in Chief's terms instead."""
    import social_publish_router as social
    detail = str(e.detail or "")
    if e.status_code == 403:
        return Refusal("Only the business owner can post for it, so nothing was posted.",
                       "Only the owner can post")
    if detail == social.REFUSED:
        return Refusal("The post wasn't accepted for posting, so nothing went out. Try again in a "
                       "minute.", NOT_POSTED, SOCIAL_NAV)
    if not detail or (e.status_code >= 500 and "nothing" not in detail.lower()):
        return Refusal("I couldn't post that just now, so nothing was posted. Try again in a "
                       "minute.", NOT_POSTED, SOCIAL_NAV)
    if "nothing" not in detail.lower():
        detail = detail.rstrip(".") + ". Nothing was posted."
    return Refusal(detail, NOT_POSTED, SOCIAL_NAV)


async def handle_post_image(client, biz, action) -> Dict[str, Any]:
    """Post a design, a photo or words to the connected accounts, now or at
    a time. See the module docstring for the action shape."""
    biz_id = str((biz or {}).get("id") or "")
    action = action or {}
    try:
        # ── The unattended gate (see the module docstring) ──
        # First, before anything is read: nothing recorded can cover an
        # unattended post, so there is nothing to look up.
        if action.get("_unattended"):
            raise Refusal(UNATTENDED, "Not posted: I post only when you ask", SOCIAL_NAV)

        user_id = _acting_user()
        await _require_owner(biz_id, user_id)
        at = _when(action.get("when"))
        await _require_posting(biz_id)
        rows = await asyncio.to_thread(_connections, biz_id)
        row = await asyncio.to_thread(_picture, biz_id, action)
        accounts = _pick_accounts(rows, action.get("platforms"))

        raw_caption = action.get("caption")
        caption = raw_caption.strip() if isinstance(raw_caption, str) else ""
        if row is None and not caption:
            raise Refusal("What should the post say? Tell me the words, or which design to post. "
                          "Nothing was posted.", "What should it say?")
        when_iso = at.isoformat() if at else None
        image_id = str(row["id"]) if row else None
        request_id = _request_id(biz_id, image_id, accounts, caption, when_iso)

        import image_posting
        try:
            out = await image_posting.post_image_for(
                biz_id, user_id, image_id, request_id=request_id, caption=caption,
                connection_ids=[str(a["id"]) for a in accounts], scheduled_at=when_iso)
        except HTTPException as e:
            raise _from_core(e)
        return _answer(out, row, caption, at)
    except Refusal as r:
        return _refused(r)
    except Exception as e:  # never a blank card, never a half-claim
        logger.exception(f"post_image failed for {biz_id[:8]}: {e}")
        return _refused(Refusal("I couldn't post that just now, so nothing was posted. "
                                "Try again in a minute.", NOT_POSTED, SOCIAL_NAV))
