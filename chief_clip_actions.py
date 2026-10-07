"""
chief_clip_actions.py — Chief posts an approved clip, with its cover.

Kevin, 2026-10-06: "let Chief post clips". One verb, post_clip:

  [ACTION:{"type":"post_clip","clip_name":"Separate Them",
           "platforms":["instagram","tiktok"],      # optional; default every connected account
           "caption":"Sunday, 10am. Come as you are.",  # optional; default the clip's caption, else its title
           "when":"2026-10-08T09:00:00-04:00",      # optional ISO with a zone; null = now
           "covers":"auto"}]                         # "auto" (newest ready cover of each shape) | "none"

  clip_id may stand in for clip_name.

THE POST ITSELF is clip_posting.post_clip_for, the same function the Post tap
in Video Clips calls: owner only, the clip approved as it is now, the cover per
network, the JPEG cover, the signed video link, the shared door
(social_publish_router.send_post), the 24-hour duplicate guard. Nothing about
the post is decided twice. This module only turns Chief's words into that
call and its answer into plain words, and refuses early, in Chief's words,
where the practitioner can do something about it.

CLASS C. A post is public and cannot be recalled once it is out (a scheduled
one can be cancelled until then). action_registry says so; the class-C gate in
_execute_actions treats the practitioner's request as the approval, holds a
voice turn for a spoken yes, and counts it against the turn's cap.

THE UNATTENDED GATE mirrors publish_post's (chief_grow_actions): the
`_unattended` mark set by chief_scheduler and by the door on every run nobody
asked for in this turn, never read from a payload. publish_post holds such a
run unless a human approval recorded on the post still covers its words and
its Page (post_approval.refusal). A clip post has no such record: the clip's
approval in Video Clips covers the clip and its own caption, never the
accounts, the time or words Chief writes. So under the same rule every
unattended clip post is held, and Chief never posts a clip on its own
initiative. A later time needs no scheduler: `when` hands the time to the
posting service with the post, where it can be cancelled in Video Clips.

THE ACTING USER is the signed-in person driving this chat turn
(chief_of_staff._TURN_USER_ID, bound from the verified JWT in chief_chat).
No turn, no post. post_clip_for checks them against businesses.owner_id with
the service role, like the endpoint.

NEVER TWICE. The post's request id is derived from the turn (image_studio's
turn id: the chat request's own id, so a retried request is the same turn),
the clip, the accounts, the caption, the time and the cover choice. The same
turn asking twice returns the first post; the day's duplicate guard in
clip_posting is the second line.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import HTTPException

logger = logging.getLogger("chief_of_staff")

VERB = "post_clip"
CLIPS_NAV = {"tab": "grow", "sub": "video-clips"}
CONNECT_NAV = {"tab": "build", "sub": "social-media"}
MAX_ACCOUNTS = 10          # the Post tap's own limit (clip_posting.ClipPost)
CLIP_SCAN = 200            # clips read when resolving one by name

# What a practitioner calls a network → the name the connection carries.
ALIASES = {
    "ig": "instagram", "insta": "instagram", "instagram reels": "instagram", "reels": "instagram",
    "fb": "facebook", "facebook reels": "facebook", "meta": "facebook",
    "tik tok": "tiktok", "tt": "tiktok",
    "yt": "youtube", "youtube shorts": "youtube", "shorts": "youtube", "you tube": "youtube",
    "twitter": "x", "x/twitter": "x", "twitter/x": "x",
    "linked in": "linkedin", "threads app": "threads",
}

UNATTENDED = ("A clip goes out only when you ask me to post it, and this came from a "
              "scheduled or automatic run, so nothing was posted. Ask me to post it "
              "(I can set the time), or post it from Video Clips.")


class Refusal(Exception):
    """A plain-words reason nothing was posted."""

    def __init__(self, result: str, label: str, nav: Optional[Dict[str, Any]] = None, **extra: Any):
        super().__init__(result)
        self.result, self.label, self.nav, self.extra = result, label, nav, extra


def _refused(r: Refusal) -> Dict[str, Any]:
    # Both result and label, always: a missing result blanks the app.
    return {"type": VERB, "result": r.result, "label": r.label, "nav": r.nav,
            "ok": False, "failed": True, **r.extra}


def _quoted(name: str) -> str:
    return f"“{(name or 'your clip').strip()}”"


def _network(platform: str) -> str:
    import social_publish_router as social
    return social.post_for_me_label(platform or "")


def _and(items: List[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _made(row: Dict[str, Any]) -> str:
    raw = str(row.get("created_at") or "")
    try:
        at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return f"made {at:%b} {at.day}"
    except ValueError:
        return ""


def _say_time(at: datetime) -> str:
    """Thursday Oct 8, 9:00 AM, in the zone the time was given in. No
    %-d / %-I: Windows strftime has neither."""
    hour = at.hour % 12 or 12
    return f"{at:%A} {at:%b} {at.day}, {hour}:{at:%M} {'AM' if at.hour < 12 else 'PM'}"


# ─── the gates, each a plain refusal ─────────────────────────────────

def _acting_user() -> str:
    import chief_of_staff as cos
    uid = str(cos._TURN_USER_ID.get() or "")
    if not uid:
        raise Refusal("I can only post a clip when the business owner asks me in chat, "
                      "so nothing was posted.", "Ask me in chat to post a clip")
    return uid


async def _require_owner(business_id: str, user_id: str) -> None:
    import clip_posting
    try:
        await asyncio.to_thread(clip_posting._require_owner, business_id, SimpleNamespace(id=user_id))
    except HTTPException as e:
        if e.status_code == 403:
            raise Refusal("Only the business owner can post its clips, so nothing was posted.",
                          "Only the owner can post clips")
        raise Refusal("I couldn't confirm this business just now, so nothing was posted. "
                      "Try again in a minute.", "Clip not posted")


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
                      "Tell me the day and time again.", "Clip not posted")
    if at.tzinfo is None:
        raise Refusal("I need that time with its time zone, so nothing was posted yet. "
                      "Tell me the time again.", "Clip not posted")
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
                      "Try again in a minute.", "Clip not posted")
    if not rows:
        raise Refusal("No social account is connected yet, so nothing was posted. Connect an "
                      "account in Build, Social Media, then ask me again.",
                      "Connect an account in Build, Social Media", CONNECT_NAV)
    return rows


def _platform(name: Any) -> str:
    p = " ".join(str(name or "").strip().lower().split())
    return ALIASES.get(p, p.replace(" ", ""))


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
                      "accounts you have.", f"Connect {nets} in Build, Social Media", CONNECT_NAV)
    if len(chosen) > MAX_ACCOUNTS:
        raise Refusal(f"That is {len(chosen)} accounts at once; I can post a clip to "
                      f"{MAX_ACCOUNTS} at a time, so nothing was posted. Tell me which networks.",
                      "Tell me which networks")
    return chosen


_CLIP_COLUMNS = "id,business_id,kind,name,status,source_id,sha256,configuration,approval,created_at,source_removed_at"


def _clip(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """The clip asked for: by id, or by name among this business's ready
    clips (exact, then part of the name, newest first)."""
    import media_library
    raw_id = str(action.get("clip_id") or "").strip()
    name = str(action.get("clip_name") or action.get("name") or "").strip().strip("\"'“”").strip()
    try:
        if raw_id:
            try:
                clip_id = str(UUID(raw_id))
            except ValueError:
                raise Refusal("I couldn't find that clip in Video Clips, so nothing was posted. "
                              "Tell me its name.", "Clip not found", CLIPS_NAV)
            rows = media_library.read(f"/media_assets?id=eq.{clip_id}&business_id=eq.{business_id}"
                                      f"&kind=eq.clip&select={_CLIP_COLUMNS}&limit=1")
            if not rows:
                raise Refusal("I couldn't find that clip in Video Clips, so nothing was posted. "
                              "Tell me its name.", "Clip not found", CLIPS_NAV)
            row = rows[0]
        elif name:
            rows = media_library.read(f"/media_assets?business_id=eq.{business_id}&kind=eq.clip"
                                      f"&status=eq.ready&select={_CLIP_COLUMNS}"
                                      f"&order=created_at.desc&limit={CLIP_SCAN}")
            wanted = name.lower()
            exact = [r for r in rows if (r.get("name") or "").strip().lower() == wanted]
            found = exact or [r for r in rows if wanted in (r.get("name") or "").strip().lower()]
            if not found:
                raise Refusal(f"I couldn't find a finished clip called {_quoted(name)} in Video "
                              "Clips, so nothing was posted. Tell me the clip's name as it shows "
                              "there.", "Clip not found", CLIPS_NAV)
            if len(found) > 1:
                some = found[:5]
                listed = "; ".join(f"{_quoted(r.get('name'))}" + (f" ({_made(r)})" if _made(r) else "")
                                   for r in some)
                more = f" and {len(found) - 5} more" if len(found) > 5 else ""
                raise Refusal(f"More than one clip matches {_quoted(name)}: {listed}{more}. Which "
                              "one should I post? Nothing was posted.", "Which clip?", CLIPS_NAV,
                              clips=[{"clip_id": r.get("id"), "name": r.get("name"),
                                      "created_at": r.get("created_at")} for r in some])
            row = found[0]
        else:
            raise Refusal("Which clip should I post? Tell me its name as it shows in Video "
                          "Clips. Nothing was posted.", "Which clip?", CLIPS_NAV)
    except HTTPException:
        raise Refusal("I couldn't read your clips just now, so nothing was posted. "
                      "Try again in a minute.", "Clip not posted")
    if row.get("status") != "ready":
        raise Refusal(f"{_quoted(row.get('name'))} is still being made. I can post it once it is "
                      "ready. Nothing was posted.", "Clip not ready yet", CLIPS_NAV)
    if row.get("source_removed_at"):
        raise Refusal(f"{_quoted(row.get('name'))} is no longer stored, so I can't post it. "
                      "Nothing was posted.", "Clip no longer stored", CLIPS_NAV)
    return row


def _require_approved(row: Dict[str, Any]) -> None:
    """Chief cannot approve a clip; the owner does, in Video Clips."""
    import clip_posting
    problem = clip_posting.approval_problem(row)
    name = _quoted(row.get("name"))
    if problem == "unapproved":
        raise Refusal(f"{name} hasn't been approved yet, so nothing was posted. Approve it in "
                      "Video Clips first (open it and finish Ready to post), then ask me again. "
                      "I can't approve a clip for you.", "Approve it in Video Clips first", CLIPS_NAV)
    if problem == "changed":
        raise Refusal(f"{name} changed after it was approved, so nothing was posted. Check it and "
                      "approve it again in Video Clips first, then ask me again.",
                      "Approve it again in Video Clips first", CLIPS_NAV)


def _request_id(business_id: str, clip_id: str, accounts: List[Dict[str, Any]], caption: str,
                when: Optional[str], covers: str) -> UUID:
    """The same turn asking for the same post gets the same id, so a retried
    turn never posts twice. No turn (a test harness, a future caller): a fresh
    id, and clip_posting's same-post-today check still stands."""
    import image_studio
    from chief_code import turn_scope
    turn = image_studio.turn_id.get() or (turn_scope.get() or {}).get("turn_id") or ""
    if not turn:
        return uuid4()
    blob = json.dumps({"business": business_id, "turn": str(turn), "clip": clip_id,
                       "accounts": sorted(str(a["id"]) for a in accounts),
                       "caption": caption, "when": when, "covers": covers}, sort_keys=True)
    return uuid5(NAMESPACE_URL, "chief-post-clip:" + blob)


# ─── the answer, in plain words ──────────────────────────────────────

def _cover_words(used: Dict[str, Any], covers: str) -> str:
    """Which cover went where, from what clip_posting actually used."""
    used = used or {}
    if covers == "none":
        return "no cover, as you asked"
    by_shape: Dict[str, List[str]] = {"story": [], "wide": [], "": []}
    for platform, v in used.items():
        by_shape[(v or {}).get("shape") or ""].append(_network(platform))
    if not by_shape["story"] and not by_shape["wide"]:
        return "no cover (it has no finished cover yet), so each network shows a frame from the video"
    if not by_shape["wide"] and not by_shape[""]:
        return "its story cover as the thumbnail"
    parts = []
    if by_shape["story"]:
        parts.append(f"its story cover on {_and(by_shape['story'])}")
    if by_shape["wide"]:
        parts.append(f"its widescreen cover on {_and(by_shape['wide'])}")
    if by_shape[""]:
        parts.append(f"no cover on {_and(by_shape[''])}")
    return _and(parts)


def _answer(out: Dict[str, Any], row: Dict[str, Any], caption: str, at: Optional[datetime],
            covers: str) -> Dict[str, Any]:
    pub = out.get("publication") or {}
    targets = pub.get("targets") or []
    nets = _and(list(dict.fromkeys(_network(t.get("platform")) for t in targets)))
    where = _and([f"{_network(t.get('platform'))} ({t.get('username')})" if t.get("username")
                  else _network(t.get("platform")) for t in targets])
    name = _quoted(row.get("name"))
    shown = caption if len(caption) <= 280 else caption[:280] + "…"
    said = "the caption " + _quoted(shown) if caption else "no caption"
    cover = _cover_words(out.get("covers") or {}, covers)
    base = {"type": VERB, "ok": True, "nav": CLIPS_NAV, "clip_id": row.get("id"),
            "publication": pub, "covers": out.get("covers") or {}}
    if out.get("already"):
        if pub.get("status") == "scheduled":
            text = (f"{name} was already scheduled to {where} with this caption, so I didn't "
                    "schedule it twice. It shows in Video Clips under the clip, where it can be "
                    "cancelled until it goes out.")
        else:
            text = (f"{name} already went to {where} with this caption, so I didn't post it "
                    "twice. How each post went shows in Video Clips under the clip.")
        return {**base, "already": True, "result": text, "label": "Already sent, not posted twice"}
    if pub.get("status") == "scheduled" and at is not None:
        when = _say_time(at)
        return {**base, "already": False, "scheduled_at": pub.get("scheduled_at"),
                "result": (f"Scheduled {name} for {when} on {where}, with {said} and {cover}. "
                           "It is waiting with the posting service, and you can cancel it in "
                           "Video Clips until it goes out. How each post goes shows there."),
                "label": f"Scheduled your clip for {when}"}
    return {**base, "already": False,
            "result": (f"Sent {name} to {where} with {said} and {cover}. Each network takes a minute "
                       "or so to put it up; the link to each live post, or any network's error, "
                       "shows in Video Clips under the clip."),
            "label": f"Sent your clip to {nets}"}


def _from_core(e: HTTPException, row: Dict[str, Any]) -> Refusal:
    """clip_posting's refusals are already plain words, written for the
    owner; a few are said in Chief's terms instead."""
    import social_publish_router as social
    detail = str(e.detail or "")
    name = _quoted(row.get("name"))
    if e.status_code == 409 and "since you opened it" in detail:
        return Refusal(f"{name} changed while I was getting it ready, so nothing was posted. Check "
                       "it in Video Clips and ask me again.", "Clip not posted", CLIPS_NAV)
    if e.status_code == 409 and "approve" in detail.lower():
        return Refusal(f"{name} changed after it was approved, so nothing was posted. Check it and "
                       "approve it again in Video Clips first, then ask me again.",
                       "Approve it again in Video Clips first", CLIPS_NAV)
    if e.status_code == 403:
        return Refusal("Only the business owner can post its clips, so nothing was posted.",
                       "Only the owner can post clips")
    if detail == social.REFUSED:
        return Refusal(f"{name} wasn't accepted for posting, so nothing went out. Try again in a "
                       "minute.", "Clip not posted", CLIPS_NAV)
    if not detail or (e.status_code >= 500 and "nothing" not in detail.lower()):
        return Refusal("I couldn't post the clip just now, so nothing was posted. Try again in a "
                       "minute.", "Clip not posted", CLIPS_NAV)
    if "nothing" not in detail.lower():
        detail = detail.rstrip(".") + ". Nothing was posted."
    return Refusal(detail, "Clip not posted", CLIPS_NAV)


async def handle_post_clip(client, biz, action) -> Dict[str, Any]:
    """Post an approved clip, with its cover, to the connected accounts, now
    or at a time. See the module docstring for the action shape."""
    biz_id = str((biz or {}).get("id") or "")
    action = action or {}
    try:
        # ── The unattended gate (see the module docstring) ──
        # First, before anything is read: no recorded approval can cover an
        # unattended clip post, so there is nothing to look up.
        if action.get("_unattended"):
            raise Refusal(UNATTENDED, "Clip not posted: I post clips only when you ask", CLIPS_NAV)

        user_id = _acting_user()
        await _require_owner(biz_id, user_id)
        at = _when(action.get("when"))
        await _require_posting(biz_id)
        rows = await asyncio.to_thread(_connections, biz_id)
        row = await asyncio.to_thread(_clip, biz_id, action)
        _require_approved(row)
        accounts = _pick_accounts(rows, action.get("platforms"))

        import clip_posting
        raw_caption = action.get("caption")
        given = raw_caption.strip() if isinstance(raw_caption, str) and raw_caption.strip() else None
        caption = given if given is not None else clip_posting.default_caption(row)
        covers = "none" if str(action.get("covers") or "auto").strip().lower() in ("none", "no", "false", "off") else "auto"
        when_iso = at.isoformat() if at else None
        request_id = _request_id(biz_id, str(row["id"]), accounts, caption, when_iso, covers)

        import media_library
        try:
            out = await clip_posting.post_clip_for(
                biz_id, user_id, str(row["id"]), request_id=request_id,
                fingerprint=media_library.fingerprint(row), caption=given,
                connection_ids=[str(a["id"]) for a in accounts], scheduled_at=when_iso,
                covers=({} if covers == "none" else None))
        except HTTPException as e:
            raise _from_core(e, row)
        return _answer(out, row, caption.strip(), at, covers)
    except Refusal as r:
        return _refused(r)
    except Exception as e:  # never a blank card, never a half-claim
        logger.exception(f"post_clip failed for {biz_id[:8]}: {e}")
        return _refused(Refusal("I couldn't post the clip just now, so nothing was posted. "
                                "Try again in a minute.", "Clip not posted", CLIPS_NAV))
