"""
chief_marketing_actions.py — Chief works the business's own marketing desk (B10).

Marketing suite B10 (docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md; Kevin,
2026-10-07: "This will work. let's build this."). Chief does in chat what the
owner can do on the desk in Grow → Marketing, through THE SAME server
functions the desk's API calls. There is no second write path: every change
goes through business_marketing (create_idea, edit_slot, the cancel route,
post_existing_now) or business_marketing_planner (the /engine/run route),
with their owner check, their revision rule and their content hash.

  verb                 class    how Chief calls it   what
  marketing_desk       read     native tool + tag    the desk: this and next week's posts (post_id,
                                                     revision, time, status, words, accounts,
                                                     picture), what waits for the owner's OK,
                                                     Chief's read, the plan level, and on request
                                                     what came through the post links (B6)
  marketing_new_post   write A  tag                  a draft for the owner to approve on the desk
  marketing_edit_post  write A  tag                  words, time, accounts, picture or link; back
                                                     to a draft (an approved post too)
  marketing_skip_post  write A  tag                  skip a post: it never goes out
  marketing_replan     write C  tag                  the week's writing again (POST /engine/run)
  marketing_post_now   write C  tag                  a post goes out in about two minutes, on the
                                                     owner's yes in this turn

NO APPROVE VERB. Chief never approves a post: the owner approves on the desk
(standing permissions come with B13). Chief says what is waiting and points
to Grow → Marketing. The one approval that happens here is the desk's own
"Post now", which approves and moves a post in one step; Chief does it only
on the owner's explicit yes in this chat turn (class C: a voice turn is held
for a spoken yes by the class-C gate) and never unattended.

WHY TAGS, NOT NATIVE WRITE TOOLS. mcp_server.WRITE_TOOL_SCHEMAS is the one
list of native write tools, and an outside agent with a write key gets every
verb on it. None of these belongs there: (1) every desk write is the owner's
alone, checked against the signed-in person driving THIS chat turn
(chief_of_staff._TURN_USER_ID), which the agent surface does not carry, so
the tool would refuse there every time; (2) the table keeps out writes that
shape what the public sees, which a practitioner changes looking at the
result in the app, and the desk is that place; (3) marketing_replan spends
model and image money, which the table also keeps out; (4) class C is never
a tool. The read IS a native tool (mcp_server.TOOL_SCHEMAS): a lookup
mid-turn lets Chief answer from the desk instead of guessing.

WHO. Reading is for the owner and the business's members (the API reads
with business_access viewer); the read says whether the person asking can
change it. Every change is the owner's: the turn's signed-in person against
businesses.owner_id, read as the service role (business_marketing._owner_row,
the API's own check). No turn, no change.

THE GATE. The desk is behind MARKETING_DESK (business_marketing_planner.
desk_on_for, read in marketing_switches): unset, it covers every business
(2026-10-08); a business it does not cover ('off', or a list that leaves it
out) gets a plain "not switched on yet" from every verb, and no context
block. The plan level is the API's own
(business_marketing.level_for, from feature_gates.plan_includes): a replan
asks for what the plan gives, and a level that cannot do something says so
by the server's own upgrade label, never a plan named here.

IN A TURN. On a marketing-shaped turn (context_block) a compact read of the
desk rides the per-message tail of the prompt: never the cached segments.

FAILED READS are "couldn't read", never "nothing there". SENT AND POSTED are
said only when a post's status from the server says so: post now answers
"approved, going out at 3:42 PM", and the read reports what came back.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from chief_clip_actions import Refusal, _and, _network, _platform, _say_time

logger = logging.getLogger("chief_of_staff")

VERBS = ("marketing_desk", "marketing_new_post", "marketing_edit_post", "marketing_skip_post",
         "marketing_replan", "marketing_post_now")
DESK_NAV = {"tab": "grow", "sub": "marketing"}
CONNECT_NAV = {"tab": "build", "sub": "social-media"}
LIBRARY_NAV = {"tab": "build", "page": "media-library"}
WHERE = "Grow → Marketing"

MAX_POSTS = 10            # posts the read lists
WORDS_MAX = 140           # a post's words in the read
RESULT_BUDGET = 5400      # the read's JSON stays under chief_tool_loop.MAX_RESULT_CHARS (6000)
BLOCK_POSTS = 6           # posts the turn's context block lists
BLOCK_WORDS_MAX = 70
READ_TIMEOUT = 6.0        # the context block waits this long for the desk

SAVED = "nothing was saved"
CHANGED = "nothing was changed"
POSTED = "nothing was posted"
QUEUED = "nothing was queued"

UNATTENDED = ("A post goes out only when you ask me to post it, and this came from a scheduled or "
              "automatic run, so nothing was posted. Ask me to post it, or use Post now on the "
              "marketing desk.")
REPLAN_UNATTENDED = ("Chief plans posts again only when you ask, and this came from a scheduled or automatic "
                     "run, so nothing was queued. Ask me to plan again, or use Plan again on the marketing desk.")
COULD_NOT_READ = ("I couldn't read the marketing desk just now. That is not the same as an empty desk: "
                  "try again in a minute.")

# What each level gives, and what the next one adds, in the owner's words.
# The plan that adds it is always the server's own (level_for's upgrade label).
LEVEL_WORDS = {
    "suggest": "Chief writes one suggested post a week for you to approve",
    "week": "Chief plans the week: up to five posts, each with a flyer, for you to approve",
    "openings": "Chief turns open chairs on your booking calendar into up to three posts a week, for you to approve",
    "autopilot": "Chief plans the week: up to five posts, each with a flyer, for you to approve",
}
UPGRADE_WORDS = {
    "marketing_week": "A whole week of posts planned for you",
    "marketing_autopilot": "Chief's fullest marketing level",
}
# What a replan writes, by the level's kind of run.
LEVEL_KIND = {"suggest": "suggestion", "week": "week", "autopilot": "week", "openings": "openings"}
KIND_RANK = {"suggestion": 0, "week": 1, "openings": 1}
KIND_ASKED = {
    "suggestion": "suggestion", "suggest": "suggestion", "suggested": "suggestion", "suggested post": "suggestion",
    "one": "suggestion", "post": "suggestion",
    "week": "week", "weekly": "week", "plan": "week", "weekly plan": "week", "whole week": "week",
    "openings": "openings", "opening": "openings", "open chairs": "openings", "open chair": "openings",
    "chairs": "openings", "open-chair": "openings",
}
KIND_WORDS = {"suggestion": "one suggested post", "week": "a weekly plan of up to five posts",
              "openings": "open-chair posts from your booking calendar"}

STATUS_WORDS = {
    "draft": "waiting for your OK",
    "approved": "approved, goes out at its time",
    "dispatching": "going out now",
    "submitted": "sent; the networks are putting it up",
    "published": "posted",
    "partly_published": "posted on some of its accounts",
    "failed": "didn't go out",
    "uncertain": "may or may not have gone out",
    "cancelled": "skipped",
    "pulled": "pulled: its time booked first",
}
SOURCE_WORDS = {"suggestion": "Chief's weekly suggestion", "plan": "Chief's weekly plan", "owner": "you, on the desk",
                "chief": "Chief, in chat", "clip": "a clip", "opening": "Chief's open-chair posts"}


class _Unreadable(Exception):
    """A read the desk needs did not happen. Never "nothing there"."""


# ─── small words ─────────────────────────────────────────────────────

def _clip(text: Any, n: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _quoted(text: Any, n: int = 200) -> str:
    return f"“{_clip(text, n)}”"


def _say_when(value: Any, tz) -> str:
    """'Thursday Oct 8, 3:00 PM' on the business's clock."""
    import marketing_desk as words
    d = words._local(value, tz)
    if not d:
        return "its time"
    return f"{d:%A} {d:%b} {d.day}, {words.clock(d, tz)}"


def _day(value: Any, tz) -> str:
    import marketing_desk as words
    return words.day_name(value, tz)


def _stamp(value: Any) -> Optional[datetime]:
    import marketing_desk as words
    return words._stamp(value)


def _now() -> datetime:
    """The desk's own clock (business_marketing.now), so a time Chief checks
    and the time the desk checks are the same instant."""
    import business_marketing as bm
    return bm.now()


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _with_nothing(detail: str, nothing: str) -> str:
    """The server's own words, ending with what did not happen."""
    detail = _sentence(detail)
    return detail if "nothing" in detail.lower() else f"{detail} {_cap(nothing)}."


def _refused(verb: str, r: Refusal) -> Dict[str, Any]:
    # Both result and label, always: a missing result blanks the app.
    return {"type": verb, "result": r.result, "label": r.label, "nav": r.nav,
            "ok": False, "failed": True, **r.extra}


def _flag(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1", "on")
    return bool(value)


# ─── the gates, each a plain refusal ─────────────────────────────────

def _switched_on(business_id: str, nothing: str) -> None:
    import business_marketing_planner as planner
    if not planner.desk_on_for(business_id):
        raise Refusal(f"The marketing desk isn't switched on for this business yet, so {nothing}.",
                      "Marketing desk not switched on yet")


def _acting_user(nothing: str) -> str:
    import chief_of_staff as cos
    uid = str(cos._TURN_USER_ID.get() or "")
    if not uid:
        raise Refusal(f"I can only change the marketing desk when the business owner asks me in chat, "
                      f"so {nothing}.", "Ask me in chat")
    return uid


async def _owner(business_id: str, user_id: str, nothing: str) -> Dict[str, Any]:
    """The API's own owner check (a service-role read of businesses.owner_id).
    Returns the business row the desk's functions take."""
    import business_marketing as bm
    try:
        return await asyncio.to_thread(bm._owner_row, business_id, user_id)
    except HTTPException as e:
        if e.status_code == 403:
            raise Refusal(f"Only the business owner can change its marketing, so {nothing}. I can still "
                          "tell you what's on the desk.", "Only the owner can change the desk", DESK_NAV)
        if e.status_code == 404:
            raise Refusal(f"I couldn't find this business, so {nothing}.", "Business not found")
        raise Refusal(f"I couldn't confirm this business just now, so {nothing}. Try again in a minute.",
                      "Couldn't confirm the business")


async def _gates(verb: str, business_id: str, nothing: str) -> Dict[str, Any]:
    """Switched on, a signed-in turn, the owner. In that order: a business
    the desk is off for learns that first, whoever asks. Solutionist's own
    business while its desk is not on the suite (planner.own_desk):
    its owner, the platform owner, learns that it runs on the Mission Control
    desk (Buffer), never "not switched on"; anyone else, only the owner rule."""
    import business_marketing_planner as planner
    import platform_suite
    await platform_suite.ready()       # B15b: the platform verdict read off the event loop
    own = planner.own_desk(business_id)
    if not own:
        _switched_on(business_id, nothing)
    uid = _acting_user(nothing)
    row = await _owner(business_id, uid, nothing)
    if own:
        raise Refusal(f"Solutionist's own marketing runs on the Mission Control desk, so {nothing}. "
                      "Plan and post it there.", "Runs on the Mission Control desk")
    return {"user_id": uid, "business": row}


def _from_api(e: HTTPException, nothing: str, label: str) -> Refusal:
    """The desk's refusals are already plain words, written for the owner. A
    few are said in Chief's terms instead: the post changed since Chief read
    it, or is gone."""
    import business_marketing as bm
    detail = str(e.detail or "").strip()
    if detail == bm.STALE:
        return Refusal(f"That post changed since I read the desk, or it's already going out, so {nothing}. "
                       "I'll read the desk again before changing it.", "The post changed", DESK_NAV,
                       stale=True)
    if detail == bm.GONE_POST:
        return Refusal(f"I couldn't find that post on the desk any more (it may have been skipped), so {nothing}.",
                       "Post not found", DESK_NAV)
    if not detail or not isinstance(e.detail, str):
        detail = "The marketing desk couldn't be reached just now. Try again in a minute."
    nav = CONNECT_NAV if "Build, Social Media" in detail else DESK_NAV
    return Refusal(_with_nothing(detail, nothing), label, nav)


def _post_ref(action: Dict[str, Any], nothing: str) -> Dict[str, Any]:
    """The post asked about: its id and the revision Chief read."""
    raw = str(action.get("post_id") or action.get("id") or "").strip()
    try:
        post_id = str(UUID(raw))
    except ValueError:
        raise Refusal(f"Which post do you mean? Tell me its day and time and I'll find it. {_cap(nothing)}.",
                      "Which post?", DESK_NAV, need="post_id and revision from marketing_desk")
    try:
        revision = int(action.get("revision"))
    except (TypeError, ValueError):
        revision = 0
    if revision < 1:
        raise Refusal(f"I need to read that post on the desk first, so {nothing}. Ask me again and I'll "
                      "read it.", "Read the desk first", DESK_NAV,
                      need="the revision marketing_desk shows for this post")
    return {"id": post_id, "revision": revision}


async def _current(business_id: str, post_id: str, nothing: str) -> Dict[str, Any]:
    """The post as it is now, this business's only (another business's post
    reads as missing)."""
    import business_marketing_store as store
    try:
        row = await store.get_post(business_id, post_id)
    except store.StoreError:
        raise Refusal(f"I couldn't read that post just now, so {nothing}. Try again in a minute.",
                      "Couldn't read the post", DESK_NAV)
    if not row:
        raise Refusal(f"I couldn't find that post on the desk, so {nothing}.", "Post not found", DESK_NAV)
    return row


SETTLED = {
    "dispatching": "is going out right now",
    "submitted": "has already been sent",
    "published": "has already been posted",
    "partly_published": "has already been posted on some of its accounts",
    "uncertain": ("may or may not have gone out: check your accounts, and if it isn't there, mark it not sent "
                  "on the desk"),
    "cancelled": "was already skipped",
    "pulled": "was pulled because its time booked first",
}


def _open_for(row: Dict[str, Any], allowed, nothing: str, *, what: str) -> None:
    """A post the desk would refuse for its state, said for what it is
    (the desk refuses it too, in its own words, if this ever misses)."""
    status = row.get("status")
    if status in allowed:
        return
    if status == "failed":
        raise Refusal(f"That post didn't go out, so it can't be {what} as it is, and {nothing}. Change it (a change "
                      "makes it a draft again), then approve it on the desk or ask me to post it.",
                      "The post didn't go out", DESK_NAV)
    raise Refusal(f"That post {SETTLED.get(status, 'is no longer waiting')}, so {nothing}.",
                  "The post can't change now", DESK_NAV)


def _same_revision(row: Dict[str, Any], ref: Dict[str, Any], nothing: str) -> None:
    if int(row.get("revision") or 0) != ref["revision"]:
        raise Refusal(f"That post changed since I read the desk (it's had another change since), so {nothing}. "
                      "I'll read the desk again before changing it.", "The post changed", DESK_NAV,
                      stale=True, revision_now=row.get("revision"))


# ─── what a post is made of ──────────────────────────────────────────

def _reworded(r: Refusal, nothing: str) -> Refusal:
    text = r.result.replace("Nothing was posted", _cap(nothing)).replace("nothing was posted", nothing)
    return Refusal(text, r.label, r.nav, **r.extra)


async def _picture(business_id: str, action: Dict[str, Any], nothing: str) -> Optional[str]:
    """The picture asked for (an id, or "latest": the newest finished design
    of the last day, chief_social_actions' own pick), or None. Whether it is
    a ready picture of THIS business is the desk's own check (build_media)."""
    raw_id = str(action.get("image_id") or "").strip()
    pick = str(action.get("image") or "").strip()
    if not raw_id and pick:
        try:
            raw_id = str(UUID(pick))
        except ValueError:
            if pick.lower() not in ("latest", "newest", "last"):
                raise Refusal(f"Which picture should the post use? Tell me which one in Media Library. "
                              f"{_cap(nothing)}.", "Which picture?", LIBRARY_NAV)
    if raw_id:
        try:
            return str(UUID(raw_id))
        except ValueError:
            raise Refusal(f"I couldn't find that picture in your Media Library, so {nothing}.",
                          "Picture not found", LIBRARY_NAV)
    if pick:
        import chief_social_actions as csa
        try:
            row = await asyncio.to_thread(csa._latest, business_id)
        except Refusal as r:
            raise _reworded(r, nothing)
        return str(row["id"])
    return None


async def _connection_ids(business_id: str, platforms: Any, nothing: str) -> Optional[List[str]]:
    """The accounts on the networks asked for, or None (the desk's own
    default: its accounts, or every connected one). A network with no
    account is refused, never quietly dropped."""
    if isinstance(platforms, str):
        platforms = [platforms]
    wanted = [p for p in dict.fromkeys(_platform(x) for x in (platforms or [])) if p]
    if not wanted:
        return None
    import business_marketing as bm
    try:
        rows = await bm.connected(business_id)
    except HTTPException:
        raise Refusal(f"I couldn't read your connected accounts just now, so {nothing}. Try again in a minute.",
                      "Couldn't read the accounts")
    if not rows:
        raise Refusal(f"No social account is connected yet, so {nothing}. Connect one in Build, Social Media, "
                      "then ask me again.", "Connect an account in Build, Social Media", CONNECT_NAV)
    chosen = [r for r in rows if str(r.get("platform") or "").lower() in wanted]
    missing = [p for p in wanted if not any(str(r.get("platform") or "").lower() == p for r in rows)]
    if missing:
        have = _and([f"{_network(r.get('platform'))} ({r.get('username')})" if r.get("username")
                     else _network(r.get("platform")) for r in rows])
        nets = _and([_network(p) for p in missing])
        raise Refusal(f"No {nets} account is connected to this business, so {nothing}. Connected now: {have}. "
                      f"Connect {nets} in Build, Social Media, or tell me which of these to use.",
                      f"Connect {nets} in Build, Social Media", CONNECT_NAV)
    return [str(r["id"]) for r in chosen]


def _when(raw: Any, nothing: str) -> Optional[datetime]:
    """A time WITH its zone, later than now; None: the desk's next open time."""
    if raw is None or (isinstance(raw, str) and raw.strip().lower() in ("", "next", "auto", "default")):
        return None
    try:
        at = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
    except ValueError:
        raise Refusal(f"I couldn't read the time {str(raw)[:40]!r}, so {nothing}. Tell me the day and time again.",
                      "Which time?")
    if at.tzinfo is None:
        raise Refusal(f"I need that time with its time zone, so {nothing}. Tell me the time again.", "Which time?")
    if at <= _now():
        raise Refusal(f"{_say_time(at)} has already passed, so {nothing}. Tell me a time later than now.",
                      "That time has passed")
    return at


def _flyer_problem(problem: str) -> str:
    import marketing_engine as platform
    m = re.match(r"flyer (headline|line|cta) length", problem or "")
    if m:
        low, high = platform.FLYER_LIMITS[m.group(1)]
        name = {"headline": "headline", "line": "line", "cta": "button"}[m.group(1)]
        return f"The flyer's {name} needs {low} to {high} characters"
    m = re.match(r"number on the flyer not in the facts \((.+)\)", problem or "")
    if m:
        return (f"A flyer can show only numbers your own site states, and {m.group(1)} isn't there "
                "(add it to the offering on your site first, or leave it off the flyer)")
    if "hashtag" in (problem or ""):
        return "A flyer takes no hashtags"
    if "link" in (problem or ""):
        return "A flyer can name only your own site"
    return f"The flyer's words didn't pass the checks ({problem})"


async def _flyer(business_id: str, post_id: str, flyer: Any, play: Any, nothing: str) -> str:
    """The free composer flyer (cost 0, the business's own colours, its own
    name and site in the footer), made by the planner's own make_flyer, the
    one the weekly suggestion uses. Its words are held to the same checks
    as Chief's weekly flyers: numbers and prices only from the business's
    own facts, links only to its own site, no hashtag."""
    import business_marketing_engine as engine
    import business_marketing_planner as planner
    import creative_director
    import marketing_engine as platform
    import marketing_profile
    if not isinstance(flyer, dict):
        raise Refusal(f"A flyer needs a headline, one line and a button, so {nothing}. Tell me the words for it.",
                      "Flyer words needed")
    copy = {k: " ".join(str(flyer.get(k) or "").split()) for k in platform.FLYER_LIMITS}
    play_id = play if isinstance(play, str) and play in engine.PLAYS else "offer_spotlight"
    try:
        row = await asyncio.to_thread(planner.read_business, business_id)
        profile = await marketing_profile.read_profile(business_id, business=row)
        raw = await asyncio.to_thread(creative_director.business_facts, business_id)
    except LookupError:
        raise Refusal(f"I couldn't find this business, so {nothing}.", "Business not found")
    except Exception:
        raise Refusal(f"I couldn't read your business's details for the flyer just now, so {nothing}. "
                      "Try again in a minute.", "Flyer not made")
    problem = engine.check_flyer(copy, engine.verified_facts(raw), profile)
    if problem:
        raise Refusal(f"{_flyer_problem(problem)}, so {nothing}. Tell me the flyer's words again.",
                      "Flyer words need a change")
    art, _design = await planner.make_flyer(row, uuid5(NAMESPACE_URL, f"chief-marketing-flyer:{post_id}"), 0,
                                            {"play_id": play_id}, copy, profile)
    if not art:
        raise Refusal(f"The flyer couldn't be made just now, so {nothing}. I can save the post with words only, "
                      "or try the flyer again.", "Flyer not made")
    return art


def _idea_id(business_id: str, verb: str, payload: Dict[str, Any]) -> UUID:
    """The same turn asking for the same post gets the same id, so a retried
    turn saves it once (the desk's own idea id rule). No turn: a fresh id."""
    import image_studio
    from chief_code import turn_scope
    turn = image_studio.turn_id.get() or (turn_scope.get() or {}).get("turn_id") or ""
    if not turn:
        return uuid4()
    blob = json.dumps({"business": business_id, "turn": str(turn), "verb": verb, **payload},
                      sort_keys=True, default=str)
    return uuid5(NAMESPACE_URL, "chief-marketing-post:" + blob)


async def _tz(business: Dict[str, Any], nothing: str):
    import business_marketing as bm
    try:
        return await asyncio.to_thread(bm.business_tz, business)
    except HTTPException:
        raise Refusal(f"I couldn't read this business's time zone just now, so {nothing}. Try again in a minute.",
                      "Couldn't read the time zone")


async def _new_idea(verb: str, business_id: str, action: Dict[str, Any], nothing: str, *, post_now: bool):
    """The desk's Idea for a new post, every part resolved and checked the
    desk's way before anything is written."""
    import business_marketing as bm
    import business_marketing_store as store
    raw_caption = action.get("caption") if action.get("caption") is not None else action.get("words")
    caption = raw_caption.strip() if isinstance(raw_caption, str) else ""
    flyer = action.get("flyer")
    image_id = await _picture(business_id, action, nothing)
    if flyer and image_id:
        raise Refusal(f"A post carries one picture: a new flyer or one from Media Library, not both, so {nothing}.",
                      "One picture per post")
    if not caption and not image_id and not flyer:
        raise Refusal(f"What should the post say? Tell me the words, or which picture to use. {_cap(nothing)}.",
                      "What should it say?")
    connection_ids = await _connection_ids(business_id, action.get("platforms"), nothing)
    at = None if post_now else _when(action.get("when"), nothing)
    link = action.get("link")
    payload = {"caption": caption, "image": image_id, "flyer": flyer, "platforms": connection_ids,
               "when": at.isoformat() if at else None, "link": link}
    idea_id = _idea_id(business_id, verb, payload)
    if flyer:
        post_id = bm.idea_post_id(business_id, idea_id)
        try:
            existing = await store.get_post(business_id, post_id)
        except store.StoreError:
            raise Refusal(f"The marketing desk couldn't be read just now, so {nothing}. Try again in a minute.",
                          "Couldn't read the desk", DESK_NAV)
        artworks = ((existing or {}).get("media") or {}).get("artwork_ids") or []
        image_id = str(artworks[0]) if artworks else await _flyer(business_id, post_id, flyer, action.get("play"),
                                                                 nothing)
    try:
        return bm.Idea(id=idea_id, caption=caption, artwork_id=image_id, connection_ids=connection_ids,
                       run_at=at, landing_url=(str(link) if link is not None else None), post_now=post_now)
    except Exception:
        raise Refusal(f"That post didn't read right (its words may be too long), so {nothing}.", "Post not saved")


# ─── the answers ─────────────────────────────────────────────────────

def _accounts_of(post: Dict[str, Any]) -> str:
    return _and(list(post.get("accounts") or [])) or "your accounts"


def _picture_words(post: Dict[str, Any]) -> str:
    media = post.get("media") or {}
    design = post.get("design_status")
    if media.get("clip_id"):
        return "a clip"
    if design == "designing":
        return "a flyer on the way"
    if media.get("artwork_ids"):
        return "a picture"
    if design == "failed":
        return "words only (its flyer could not be made)"
    return "words only"


def _status_words(post: Dict[str, Any], now: datetime, paused: bool) -> str:
    status = post.get("status")
    at = _stamp(post.get("run_at"))
    if status == "draft":
        if at and at <= now:
            return "missed its time: it was never approved"
        if post.get("design_status") == "designing":
            return "waiting for its flyer, then your OK"
        return STATUS_WORDS["draft"]
    if status == "approved" and paused:
        return "approved, but held: posting is paused"
    return STATUS_WORDS.get(status, str(status or "unknown"))


def _gone_out(status: Optional[str]) -> Optional[str]:
    """'sent' or 'posted' ONLY when the post's own status says so."""
    if status in ("published", "partly_published"):
        return "posted"
    if status == "submitted":
        return "sent"
    return None


# ─── reading the desk ────────────────────────────────────────────────

def _business_row(business_id: str) -> Dict[str, Any]:
    import sb_clients
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{UUID(str(business_id))}&select=*&limit=1")
    if rows is None:
        raise _Unreadable("the business")
    if not rows:
        raise LookupError("Business not found.")
    return rows[0]


async def read_engine(business_id: str) -> Dict[str, Any]:
    """The desk exactly as GET /marketing/{id}/engine answers it (the route's
    own function), for the person driving this turn. Raises on a failed read."""
    import business_marketing as bm
    import chief_of_staff as cos
    row = await asyncio.to_thread(_business_row, business_id)
    uid = str(cos._TURN_USER_ID.get() or "")
    role = "owner" if uid and uid == str(row.get("owner_id")) else ("member" if uid else None)
    return await bm.engine(UUID(str(business_id)), biz={**row, "_caller_role": role})


def _posts_of(payload: Dict[str, Any], now: datetime) -> List[Dict[str, Any]]:
    """This and next week's posts: the ones still to come first, soonest
    first, then the ones whose time has passed, newest first."""
    posts = list((payload.get("this_week") or {}).get("posts") or []) + \
        list((payload.get("next_week") or {}).get("posts") or [])
    ahead = [p for p in posts if (_stamp(p.get("run_at")) or now) > now]
    past = [p for p in posts if p not in ahead]
    return ahead + list(reversed(past))


def _sending(payload: Dict[str, Any]) -> bool:
    posting = payload.get("posting") or {}
    return bool(posting.get("configured") and posting.get("allowed") and posting.get("sending"))


def _level(payload: Dict[str, Any]) -> Dict[str, Any]:
    level = payload.get("level")
    up = payload.get("upgrade") or None
    out = {"level": level, "plan_gives": LEVEL_WORDS.get(level), "upgrade": None}
    if up and up.get("label"):
        out["upgrade"] = {"plan": up["label"], "adds": UPGRADE_WORDS.get(up.get("feature"))}
    return out


def desk_digest(payload: Dict[str, Any], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """The engine's answer, compact, for Chief: every post with what an
    action needs (post_id, revision) and what the owner would see."""
    now = now or _now()
    tz = ZoneInfo(payload.get("time_zone") or "UTC")
    desk = payload.get("desk") or {}
    paused = bool(desk.get("paused"))
    posts = []
    for p in _posts_of(payload, now):
        line = {"post_id": str(p.get("id")), "revision": p.get("revision"), "when": _say_when(p.get("run_at"), tz),
                "status": _status_words(p, now, paused), "accounts": list(p.get("accounts") or []),
                "picture": _picture_words(p), "from": SOURCE_WORDS.get(p.get("source"), "the desk"),
                "words": _clip(p.get("caption"), WORDS_MAX)}
        if p.get("error"):
            line["note"] = _clip(p["error"], 160)
        posts.append(line)
    note = payload.get("note") or {}
    waiting = [p for p in posts if p["status"].startswith("waiting for")]
    return {
        **_level(payload),
        "time_zone": tz.key,
        "you_can_change": bool(payload.get("can_edit")),
        "sending": ("on: an approved post goes out at its time" if _sending(payload) else
                    "not switched on yet: approved posts wait"),
        "posting_paused": paused,
        "accounts": [f"{c.get('label')} ({c.get('username')})" if c.get("username") else str(c.get("label"))
                     for c in payload.get("connections") or []],
        "chief_read": {"headline": note.get("headline"), "body": list(note.get("body") or [])},
        "waiting_for_owner_ok": len(waiting),
        "planning_now": bool(payload.get("planning")),
        "posts": posts[:MAX_POSTS],
        "more_posts": max(0, len(posts) - MAX_POSTS),
        "needs_a_look": [{"title": i.get("title"), "detail": _clip(i.get("detail"), 200),
                          "posts": [it for s in i.get("slots") or [] for it in
                                    ({"post_id": x.get("id"), "revision": x.get("revision")} for x in s.get("items") or [])]}
                         for i in payload.get("attention") or []],
    }


async def _results(business_id: str, tz) -> Dict[str, Any]:
    """What came through the posts' links in the last 30 days (B6), the
    results route's own function. A source that could not be read is named."""
    import business_marketing as bm
    import business_marketing_outcomes as outcomes
    import business_marketing_store as store
    try:
        r = await outcomes.for_business(business_id, now=bm.now())
    except store.StoreError:
        return {"state": "unavailable", "said": "The results couldn't be read just now. That is not the same as none."}
    return {"state": "read", "headline": r.get("headline"), "posts_out_last_30_days": r.get("sent"),
            "with_links": r.get("linked"), "totals": r.get("totals"),
            "unavailable": [k for k, v in (r.get("sources") or {}).items() if v == "unavailable"],
            "posts": [{"post_id": p.get("id"), "when": _say_when(p.get("run_at"), tz),
                       "words": _clip(p.get("caption"), 70), "clicks": p.get("clicks"), "visits": p.get("visits"),
                       "leads": p.get("leads")} for p in (r.get("posts") or [])[:5]]}


def _fit(out: Dict[str, Any]) -> Dict[str, Any]:
    """Under the tool loop's result cap, whole: drop the furthest posts
    first and say how many more there are, never a cut-off half. Measured
    as chief_tool_loop._shrink writes it (ASCII-escaped JSON)."""
    while len(json.dumps(out, default=str)) > RESULT_BUDGET and out.get("posts"):
        out["posts"].pop()
        out["more_posts"] = int(out.get("more_posts") or 0) + 1
    return out


async def handle_marketing_desk(client, biz, action) -> Dict[str, Any]:
    """Read the desk. Owner and members alike; nothing changes."""
    verb = "marketing_desk"
    bid = str((biz or {}).get("id") or "")
    action = action or {}
    try:
        import business_marketing_planner as planner
        import platform_suite
        await platform_suite.ready()   # B15b: the platform verdict read off the event loop
        if not planner.desk_on_for(bid):
            return {"type": verb, "ok": True, "switched_on": False, "nav": None,
                    "result": "The marketing desk isn't switched on for this business yet, so there is nothing on "
                              "it to read.",
                    "label": "Marketing desk not switched on yet"}
        payload = await read_engine(bid)
        out = desk_digest(payload)
        if _flag(action.get("results")):
            out["results"] = await _results(bid, ZoneInfo(out["time_zone"]))
        read = out["chief_read"]
        summary = " ".join(x for x in [read.get("headline") or ""] + read["body"][:2] if x).strip()
        if out["waiting_for_owner_ok"]:
            summary += f" Approve on the desk in {WHERE}."
        return _fit({"type": verb, "ok": True, "switched_on": True, "nav": DESK_NAV,
                     "result": summary or "Here is the marketing desk.", "label": "Read the marketing desk", **out})
    except LookupError:
        return {"type": verb, "ok": False, "failed": True, "nav": None,
                "result": "I couldn't find this business.", "label": "Business not found"}
    except Exception as e:  # a failed read is never an empty desk
        logger.warning(f"marketing_desk read failed for {bid[:8]}: {type(e).__name__}: {e}")
        return {"type": verb, "ok": False, "failed": True, "unavailable": True, "nav": DESK_NAV,
                "result": COULD_NOT_READ, "label": "Couldn't read the marketing desk"}


# ─── a new post ──────────────────────────────────────────────────────

async def handle_marketing_new_post(client, biz, action) -> Dict[str, Any]:
    """Save a draft on the desk (create_idea, the desk's own New post) for
    the owner to approve there."""
    verb = "marketing_new_post"
    bid = str((biz or {}).get("id") or "")
    action = action or {}
    try:
        g = await _gates(verb, bid, SAVED)
        tz = await _tz(g["business"], SAVED)
        idea = await _new_idea(verb, bid, action, SAVED, post_now=False)
        import business_marketing as bm
        try:
            out = await bm.create_idea(bid, g["business"], idea, g["user_id"], source="chief")
        except HTTPException as e:
            raise _from_api(e, SAVED, "Post not saved")
        post = out.get("post") or {}
        when = _say_when(post.get("run_at") or out.get("run_at"), tz)
        lead = "That post is already on your desk" if out.get("already_saved") else "Saved a draft on your marketing desk"
        said = [f"{lead} for {when} on {_and(out.get('accounts') or []) or 'your accounts'}: {_quoted(post.get('caption'))}."]
        if (post.get("media") or {}).get("artwork_ids"):
            said.append("It carries its picture.")
        if out.get("note"):
            said.append(out["note"])
        if out.get("link"):
            said.append(f"It links to your site through {out['link']}.")
        said.append(f"It waits for your OK in {WHERE}; nothing posts until you approve it there.")
        return {"type": verb, "ok": True, "nav": DESK_NAV, "post_id": post.get("id"), "revision": post.get("revision"),
                "status": post.get("status"), "already": bool(out.get("already_saved")),
                "dropped": out.get("dropped") or [], "result": " ".join(said),
                "label": f"Draft on the desk for {_day(post.get('run_at'), tz)}"}
    except Refusal as r:
        return _refused(verb, r)
    except Exception as e:  # never a blank card, never a half-claim
        logger.exception(f"{verb} failed for {bid[:8]}: {e}")
        return _refused(verb, Refusal(f"I couldn't save that post just now, so {SAVED}. Try again in a minute.",
                                      "Post not saved", DESK_NAV))


# ─── change a post ───────────────────────────────────────────────────

async def handle_marketing_edit_post(client, biz, action) -> Dict[str, Any]:
    """Change a post's words, time, accounts, picture or link (edit_slot,
    the desk's own Change). Any change puts it back to a draft with a new
    revision: an approved post needs the owner's OK again."""
    verb = "marketing_edit_post"
    bid = str((biz or {}).get("id") or "")
    action = action or {}
    try:
        g = await _gates(verb, bid, CHANGED)
        ref = _post_ref(action, CHANGED)
        row = await _current(bid, ref["id"], CHANGED)
        _same_revision(row, ref, CHANGED)
        _open_for(row, ("draft", "approved", "failed"), CHANGED, what="changed")
        tz = await _tz(g["business"], CHANGED)
        import business_marketing as bm
        change: Dict[str, Any] = {}
        what = []
        raw_caption = action.get("caption") if action.get("caption") is not None else action.get("words")
        if isinstance(raw_caption, str) and raw_caption.strip():
            change["caption"] = raw_caption.strip()
            what.append("its words")
        at = _when(action.get("when"), CHANGED)
        if at is not None:
            change["run_at"] = at
            what.append("its time")
        if action.get("platforms"):
            change["connection_ids"] = await _connection_ids(bid, action.get("platforms"), CHANGED)
            what.append("its accounts")
        if _flag(action.get("remove_picture")):
            change["remove_media"] = True
            what.append("its picture (removed)")
        elif action.get("flyer"):
            change["artwork_id"] = await _flyer(bid, f"{ref['id']}:r{ref['revision']}", action.get("flyer"),
                                                action.get("play"), CHANGED)
            what.append("its picture (a new flyer)")
        else:
            image_id = await _picture(bid, action, CHANGED)
            if image_id:
                change["artwork_id"] = image_id
                what.append("its picture")
        if "link" in action:
            change["landing_url"] = str(action.get("link") or "")
            what.append("its link")
        if not change:
            raise Refusal(f"What should change: the words, the time, the accounts, the picture or the link? "
                          f"{_cap(CHANGED)}.", "What should change?", DESK_NAV)
        try:
            req = bm.SlotEdit(items=[bm.SlotItem(id=ref["id"], revision=ref["revision"])], **change)
        except Exception:
            raise Refusal(f"That change didn't read right (the words may be too long), so {CHANGED}.",
                          "Post not changed", DESK_NAV)
        try:
            out = await bm.edit_slot(bid, req, g["business"])
        except HTTPException as e:
            raise _from_api(e, CHANGED, "Post not changed")
        post = (out.get("posts") or [{}])[0]
        said = [f"Changed {_day(post.get('run_at'), tz)}'s post ({_and(what)}): now {_say_when(post.get('run_at'), tz)} "
                f"on {_accounts_of(post)}, {_quoted(post.get('caption'))}."]
        if out.get("note"):
            said.append(out["note"])
        if row.get("status") == "approved":
            said.append("It was approved; a change puts it back to a draft, so it needs your OK again on the desk "
                        "before it goes out.")
        else:
            said.append(f"It's a draft: it goes out at its time once you approve it in {WHERE}.")
        return {"type": verb, "ok": True, "nav": DESK_NAV, "post_id": post.get("id"), "revision": post.get("revision"),
                "status": post.get("status"), "was": row.get("status"), "dropped": out.get("dropped") or [],
                "result": " ".join(said), "label": f"Changed {_day(post.get('run_at'), tz)}'s post: back to draft"}
    except Refusal as r:
        return _refused(verb, r)
    except Exception as e:
        logger.exception(f"{verb} failed for {bid[:8]}: {e}")
        return _refused(verb, Refusal(f"I couldn't change that post just now, so {CHANGED}. Try again in a minute.",
                                      "Post not changed", DESK_NAV))


# ─── skip a post ─────────────────────────────────────────────────────

async def handle_marketing_skip_post(client, biz, action) -> Dict[str, Any]:
    """Skip a post (the desk's own Skip: POST /slot/cancel's function). It
    never goes out; the row stays."""
    verb = "marketing_skip_post"
    bid = str((biz or {}).get("id") or "")
    action = action or {}
    try:
        g = await _gates(verb, bid, CHANGED)
        ref = _post_ref(action, CHANGED)
        row = await _current(bid, ref["id"], CHANGED)
        _same_revision(row, ref, CHANGED)
        _open_for(row, ("draft", "approved", "failed"), CHANGED, what="skipped")
        tz = await _tz(g["business"], CHANGED)
        import business_marketing as bm
        try:
            await bm.cancel_slot_route(business_id=UUID(bid),
                                       req=bm.SlotCancel(items=[bm.SlotItem(id=ref["id"], revision=ref["revision"])]),
                                       user=SimpleNamespace(id=g["user_id"]))
        except HTTPException as e:
            raise _from_api(e, CHANGED, "Post not skipped")
        said = [f"Skipped {_say_when(row.get('run_at'), tz)}'s post ({_quoted(row.get('caption'), 120)}). "
                "It won't go out."]
        if row.get("status") == "approved":
            said.append("It had been approved; it's off the schedule now.")
        return {"type": verb, "ok": True, "nav": DESK_NAV, "post_id": ref["id"], "status": "cancelled",
                "result": " ".join(said), "label": f"Skipped {_day(row.get('run_at'), tz)}'s post"}
    except Refusal as r:
        return _refused(verb, r)
    except Exception as e:
        logger.exception(f"{verb} failed for {bid[:8]}: {e}")
        return _refused(verb, Refusal(f"I couldn't skip that post just now, so {CHANGED}. Try again in a minute.",
                                      "Post not skipped", DESK_NAV))


# ─── the week's writing, again ───────────────────────────────────────

def _asked_kind(raw: Any) -> Optional[str]:
    text = " ".join(str(raw or "").strip().lower().replace("_", " ").split())
    if not text:
        return None
    return KIND_ASKED.get(text) or KIND_ASKED.get(text.rstrip("s"))


def _level_refusal(asked: str, gives: str, level: Dict[str, Any]) -> Refusal:
    """What this plan gives instead, and the plan that adds what was asked
    (the server's own upgrade label), when it is above this level."""
    up = level.get("upgrade") or None
    label = (up or {}).get("label")
    gives_words = KIND_WORDS[gives]
    if KIND_RANK[asked] > KIND_RANK[gives] and label:
        extra = " and a live booking calendar" if asked == "openings" else ""
        lead = ("A whole week of posts planned for you" if asked == "week" else
                "Open-chair posts from your booking calendar")
        verb = "come" if asked == "openings" else "comes"
        text = (f"{lead} {verb} with {label}{extra}. On your plan Chief writes {gives_words}, so {QUEUED}. "
                f"Want me to write that instead?")
        return Refusal(text, f"Comes with {label}", DESK_NAV, upgrade=label, plan_gives=gives)
    if asked == "openings":
        return Refusal(f"Open-chair posts are written from a live booking calendar, and this business gets "
                       f"{gives_words} instead, so {QUEUED}. Want me to write that?",
                       "Not on this plan", DESK_NAV, plan_gives=gives)
    return Refusal(f"Your plan comes with {gives_words}, so Chief writes that instead of {KIND_WORDS[asked]}, and "
                   f"{QUEUED}. Want me to write that?", "Your plan writes something else", DESK_NAV, plan_gives=gives)


async def handle_marketing_replan(client, biz, action) -> Dict[str, Any]:
    """Queue this week's suggestion, weekly plan or open-chairs week again:
    the owner's own POST /marketing/{id}/engine/run (the route's function),
    with its level rules and its limits (once a day for a suggestion; a
    week twice; never over an approved or sent post; never while its
    flyers are being made). The worker writes it; nothing is cancelled
    until the new drafts are saved, and nothing posts until approved."""
    verb = "marketing_replan"
    bid = str((biz or {}).get("id") or "")
    action = action or {}
    try:
        # The unattended gate, before anything is read: a week's replan can
        # start paid flyers and retire the week's waiting drafts, so it runs
        # only on the owner's own ask in this turn (review of #1339).
        if action.get("_unattended"):
            raise Refusal(REPLAN_UNATTENDED, "Not queued: I plan again only when you ask", DESK_NAV)
        g = await _gates(verb, bid, QUEUED)
        import business_marketing as bm
        import business_marketing_planner as planner
        try:
            row = await asyncio.to_thread(planner.read_business, bid)
            level = await asyncio.to_thread(bm.level_for, row)
        except LookupError:
            raise Refusal(f"I couldn't find this business, so {QUEUED}.", "Business not found")
        except (planner.Unavailable, HTTPException):
            raise Refusal(f"I couldn't read your plan just now, so {QUEUED}. Try again in a minute.",
                          "Couldn't read the plan", DESK_NAV)
        gives = LEVEL_KIND.get(level.get("level"), "suggestion")
        asked = _asked_kind(action.get("kind") or action.get("what"))
        if asked and asked != gives:
            raise _level_refusal(asked, gives, level)
        try:
            out = await planner.run_route(business_id=UUID(bid), user=SimpleNamespace(id=g["user_id"]))
        except HTTPException as e:
            raise _from_api(e, QUEUED, "Nothing queued")
        kind = out.get("kind") or gives
        import marketing_desk as words
        week = words.week_label(out.get("week_of"))
        said = {
            "suggestion": (f"Chief is writing a suggested post for the week of {week}. It lands on your marketing "
                           "desk as a draft in a minute or two; the earlier suggestion stays until the new one is "
                           "saved. Nothing posts until you approve it there."),
            "week": (f"Chief is planning the week of {week}: up to five posts, each with a flyer. They land on your "
                     "marketing desk as drafts in a few minutes; the week's earlier drafts are retired only once "
                     "the new ones are saved. Nothing posts until you approve them there."),
            "openings": (f"Chief is turning open chairs on your booking calendar into posts for the week of {week}: "
                         "up to three, as drafts on your marketing desk in a minute or two. Nothing posts until you "
                         "approve them there."),
        }.get(kind, "Chief is writing your posts. Nothing posts until you approve them on the desk.")
        return {"type": verb, "ok": True, "nav": DESK_NAV, "queued": True, "kind": kind,
                "week_of": out.get("week_of"), "level": level.get("level"), "result": said,
                "label": {"suggestion": "Writing a suggested post", "week": "Planning the week",
                          "openings": "Planning open-chair posts"}.get(kind, "Writing your posts")}
    except Refusal as r:
        return _refused(verb, r)
    except Exception as e:
        logger.exception(f"{verb} failed for {bid[:8]}: {e}")
        return _refused(verb, Refusal(f"I couldn't ask for that just now, so {QUEUED}. Try again in a minute.",
                                      "Nothing queued", DESK_NAV))


# ─── post now ────────────────────────────────────────────────────────

def _post_now_answer(post: Dict[str, Any], tz, note: Optional[str]) -> Dict[str, Any]:
    status = post.get("status")
    words_said = _quoted(post.get("caption"))
    where = _accounts_of(post)
    gone = _gone_out(status)
    base = {"type": "marketing_post_now", "ok": True, "nav": DESK_NAV, "post_id": post.get("id"),
            "revision": post.get("revision"), "status": status}
    left = f" {note}" if note else ""
    if gone == "posted":
        return {**base, "result": f"Posted on {where}: {words_said}.{left}", "label": f"Posted on {where}"}
    if gone == "sent":
        return {**base, "result": (f"Sent to {where}: {words_said}.{left} Each network takes a minute or so to put "
                                   f"it up; the desk shows how it went."),
                "label": f"Sent to {where}"}
    if status == "approved":
        at = _stamp(post.get("run_at"))
        clock = _say_when(at, tz) if at else "in about two minutes"
        return {**base, "goes_out_at": post.get("run_at"),
                "result": (f"You said yes, so it's approved and goes out at {clock} (in about two minutes) on "
                           f"{where}: {words_said}.{left} Nothing is up yet: the desk sends it then, and each "
                           "network takes a minute or so after that. Ask me and I'll check the desk to see it went out."),
                "label": f"Going out at {clock}"}
    return {**base, "result": f"The desk shows this post as {_status_words(post, _now(), False)}.",
            "label": "Post now: see the desk"}


async def handle_marketing_post_now(client, biz, action) -> Dict[str, Any]:
    """A post goes out in about two minutes: a post already on the desk
    exactly as Chief read it (post_existing_now, the desk's own Post now),
    or a new one (create_idea with post_now, the desk's New post → Post
    now). Class C: the owner's request in this chat turn is the yes; never
    unattended."""
    verb = "marketing_post_now"
    bid = str((biz or {}).get("id") or "")
    action = action or {}
    try:
        # ── The unattended gate, before anything is read (as post_image's) ──
        if action.get("_unattended"):
            raise Refusal(UNATTENDED, "Not posted: I post only when you ask", DESK_NAV)
        g = await _gates(verb, bid, POSTED)
        tz = await _tz(g["business"], POSTED)
        import business_marketing as bm
        if action.get("post_id") or action.get("id"):
            ref = _post_ref(action, POSTED)
            row = await _current(bid, ref["id"], POSTED)
            _same_revision(row, ref, POSTED)
            _open_for(row, ("draft", "approved"), POSTED, what="posted now")
            item = bm.ReviewItem(id=ref["id"], revision=ref["revision"], content_hash=row["content_hash"])
            try:
                out = await bm.post_existing_now(bid, [item], g["user_id"])
            except HTTPException as e:
                raise _from_api(e, POSTED, "Not posted")
            post, note = (out.get("posts") or [{}])[0], None
        else:
            idea = await _new_idea(verb, bid, action, POSTED, post_now=True)
            try:
                out = await bm.create_idea(bid, g["business"], idea, g["user_id"], source="chief")
            except HTTPException as e:
                raise _from_api(e, POSTED, "Not posted")
            post, note = out.get("post") or {}, out.get("note")
        return _post_now_answer(post, tz, note)
    except Refusal as r:
        return _refused(verb, r)
    except Exception as e:
        logger.exception(f"{verb} failed for {bid[:8]}: {e}")
        return _refused(verb, Refusal(f"I couldn't post that just now, so {POSTED}. Try again in a minute.",
                                      "Not posted", DESK_NAV))


# ─── the desk in a turn ──────────────────────────────────────────────
#
# On a marketing-shaped turn a compact read of the desk rides the prompt's
# per-message tail (chief_chat appends it to growth_turn_block), so Chief
# can say what is waiting without a lookup. Never the cached segments: it
# changes with the desk. Precision over cost: a turn that never mentions
# posts, flyers, accounts or marketing pays nothing, and Chief can still
# read the desk with the marketing_desk tool.

_DESK_WORDS = re.compile(
    r"\b(posts?|posting|posted|flyers?|captions?|instagram|insta|facebook|fb|tiktok|social|socials|"
    r"marketing|desk|suggested post|suggestion|open chairs?|open-chair)\b", re.I)

UNREAD_BLOCK = ("MARKETING DESK: couldn't be read just now. That is not the same as an empty desk: if they ask, "
                "say you couldn't read it (or read it with marketing_desk), never that nothing is there.")


def wants_desk(message: str, *, mode: Optional[str] = None, tab: Optional[str] = None,
               sub_tab: Optional[str] = None) -> bool:
    if (mode or "").strip().endswith("_coach"):
        return False
    if "marketing" in ((tab or "").strip().lower(), (sub_tab or "").strip().lower()):
        return True
    try:
        import growth_doctrine
        if growth_doctrine.is_growth_turn(message or "", tab=tab, sub_tab=sub_tab):
            return True
    except Exception:
        pass
    return bool(_DESK_WORDS.search(message or ""))


def format_block(payload: Dict[str, Any], *, now: Optional[datetime] = None) -> str:
    """The desk in a few lines: the level, sending, Chief's read, the
    posts with what an action needs, and what needs a look."""
    now = now or _now()
    d = desk_digest(payload, now=now)
    lines = [f"MARKETING DESK, read just now (this business's own posts in {WHERE}; times on its clock, "
             f"{d['time_zone']}):"]
    plan = f"Plan: {d['plan_gives']}." if d.get("plan_gives") else ""
    if d.get("upgrade") and d["upgrade"].get("adds"):
        plan += f" {d['upgrade']['adds']} comes with {d['upgrade']['plan']}."
    if plan:
        lines.append(plan.strip())
    lines.append(f"Sending: {d['sending']}. Posting paused: {'yes' if d['posting_paused'] else 'no'}. "
                 f"Accounts: {_and(d['accounts']) or 'none connected'}."
                 + ("" if d["you_can_change"] else " The person asking can read the desk but not change it."))
    read = d["chief_read"]
    if read.get("headline"):
        lines.append("Chief's read: " + " ".join([read["headline"]] + read["body"][:1]))
    if d["posts"]:
        # A post's words are data, never instructions: the same two layers
        # as every lookup result (an action tag in a caption is defused and
        # taints the turn, so a class-C action on it is held).
        import untrusted_text
        lines.append("Posts (post_id · revision · when · status · accounts · picture · words):")
        for p in d["posts"][:BLOCK_POSTS]:
            lines.append(f"- {p['post_id']} · r{p['revision']} · {p['when']} · {p['status']} · "
                         f"{', '.join(p['accounts']) or 'no accounts'} · {p['picture']} · "
                         f"{_quoted(untrusted_text.defuse(p['words']), BLOCK_WORDS_MAX)}")
        more = len(d["posts"]) - BLOCK_POSTS + d["more_posts"]
        if more > 0:
            lines.append(f"(+{more} more: read them with marketing_desk)")
    else:
        lines.append("Posts this week and next: none on the desk.")
    looks = [i["title"] for i in d["needs_a_look"] if i.get("title")]
    if looks:
        lines.append("Needs a look: " + "; ".join(looks) + ".")
    lines.append("Change posts only with the marketing_* actions, using the post_id and revision above. You never "
                 "approve a post: the owner approves on the desk. Say sent or posted only when a status here says so.")
    return "\n".join(lines)


async def context_block(biz: Dict[str, Any], message: str, *, mode: Optional[str] = None,
                        tab: Optional[str] = None, sub_tab: Optional[str] = None) -> str:
    """The turn's MARKETING DESK lines, or '' when this turn is not about
    marketing or the desk is not switched on. Never raises."""
    try:
        bid = str((biz or {}).get("id") or "")
        if not bid or not wants_desk(message, mode=mode, tab=tab, sub_tab=sub_tab):
            return ""
        import business_marketing_planner as planner
        import platform_suite
        await platform_suite.ready()   # B15b: the platform verdict read off the event loop
        if not planner.desk_on_for(bid):
            return ""
        try:
            payload = await asyncio.wait_for(read_engine(bid), timeout=READ_TIMEOUT)
        except Exception as e:
            logger.warning(f"marketing desk block: the desk couldn't be read for {bid[:8]}: {type(e).__name__}")
            return UNREAD_BLOCK
        return format_block(payload)
    except Exception as e:  # pragma: no cover - a context block never breaks a turn
        logger.warning(f"marketing desk block failed: {e}")
        return ""
