"""church_findway.py — Chief knows where everything is on a church's menu.

Kevin, 2026-11-16, after loading his first church: "major navigation issues
such as where everything is." The app answers "where is" and "how do I" in
three places that must agree: its search, its Help Center and Chief. The
first two read the map of a church's app in the frontend
(src/core/components/church/findway). This is Chief's copy.

A pastor in his first week needs to pay a deacon back for paint. In the
app that is a check request: Office, Money out, Check requests. Before
this, Chief's directions listed the business rooms only, so he was told
about invoices. Now Chief has the church's menu door by door, and when the
question matches one of the Help Center's answers, that answer is handed to
it for the turn with the page to open.

    church_findway.json ... the frontend's export
                            (scripts/export-church-map.mjs there): the
                            doors, each page's name, tab and sub, who sees
                            it, the words people type for it, and its card
                            (what you do there, the "how do I" answers).
                            NEVER edit it by hand: change the frontend and
                            export again
    menu_block() .......... the whole church's menu, for the per-business
                            part of the prompt (the same for every login
                            of a church, so it caches). Each page carries
                            who sees it; the THIS LOGIN block (chief_areas)
                            already says which areas a login has
    turn_block() .......... for this message only: the answers and pages it
                            matches, cut to what the login's areas show.
                            Nothing when nothing matches, so a turn that
                            isn't a "where" or a "how" pays nothing
    the matcher ........... the frontend's (findway/churchMap.ts
                            matchAnswers), line for line, so Chief and the
                            Help Center pick the same answer

Switched by CHIEF_FINDWAY: on (the default) | off.
"""
from __future__ import annotations

import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("church_findway")

_FILE = Path(__file__).with_name("church_findway.json")

# Pages the map has a card for that today's menu does not list: the
# marketing desk is open for every business, and it took their place
# (Posts opens Marketing; Video studio and Video Clips are tabs of Create).
NOT_ON_THE_MENU = {"grow:content", "grow:video-studio", "grow:video-clips"}

# An area's short name, for the tag after a page.
AREA_TAG = {
    "worship_media": "sunday", "kids_youth": "kids", "people_care": "people", "groups_classes": "groups",
    "office": "office", "website_outreach": "media", "messages_safety": "safety",
}


def mode() -> str:
    m = (os.environ.get("CHIEF_FINDWAY") or "on").strip().lower()
    return m if m in ("off", "on") else "on"


@lru_cache(maxsize=1)
def _map() -> Dict[str, Any]:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — no map means today's Chief, never a failed turn
        logger.warning("church findway: the map could not be read")
        return {"doors": []}


def pages() -> List[Dict[str, Any]]:
    """Every page on the menu, each with its door and its place:
    {key, tab, sub, name, sees, what, words, answers, door, where}."""
    return _pages()


@lru_cache(maxsize=1)
def _pages() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for door in _map().get("doors") or []:
        for group in door.get("groups") or []:
            for page in group.get("pages") or []:
                if page.get("key") in NOT_ON_THE_MENU:
                    continue
                where = [door.get("label") or ""] + ([group["caption"]] if group.get("caption") else [])
                out.append({**page, "door": door.get("label") or "", "where": " › ".join(where + [page.get("name") or ""])})
    return out


def _is_church(biz: Optional[Dict[str, Any]]) -> bool:
    try:
        import church_follow_up
        return bool(biz) and church_follow_up.is_church(biz or {})
    except Exception:  # noqa: BLE001
        return False


# ─── Who sees a page ──────────────────────────────────────────────────

def shown_to(page: Dict[str, Any], scope: Optional[Dict[str, Any]]) -> bool:
    """Whether a login kept to its areas (chief_areas.scope_for) has the
    page. No scope is the whole church: the owner, an admin. Money pages
    are never a lane's (the menu's own rule, churchStructure MONEY)."""
    if scope is None:
        return True
    sees = page.get("sees")
    if sees == "every":
        return True
    if sees == "money" or not isinstance(sees, list):
        return False
    mine = scope.get("areas") or []
    return any(a in mine for a in sees)


def _tag(page: Dict[str, Any]) -> str:
    sees = page.get("sees")
    if sees == "every":
        return ""
    if sees == "money":
        return " [money]"
    if not sees:
        return " [owner]"
    return " [" + ", ".join(AREA_TAG.get(a, a) for a in sees) + "]"


def _path(page: Dict[str, Any]) -> str:
    """How navigate opens it: operate and grow pages by sub, build pages
    by page."""
    if page.get("sub") == "@roster":
        return "a module page: open it by its module id"
    return f"{page.get('tab')}/{page.get('sub')}"


def place_of(biz: Optional[Dict[str, Any]], tab: Optional[str], leaf: Optional[str]) -> Optional[str]:
    """Where a page sits on a church's menu, in the menu's words: "Office ›
    Money out › Check requests". None for a business that isn't a church,
    a page the map does not have, or the switch off. handle_navigate labels
    what it opened with this, and Chief repeats the label."""
    if mode() == "off" or not _is_church(biz):
        return None
    tab = (tab or "").lower().strip()
    if tab == "home":
        return "Home"
    for page in _pages():
        if page.get("tab") == tab and page.get("sub") == leaf:
            return page["where"]
    return None


# ─── The menu, for the per-business part of the prompt ────────────────

def menu_block(biz: Optional[Dict[str, Any]]) -> str:
    """The church's menu, door by door. Empty for a business that isn't a
    church, or with the switch off. The same text for every login of a
    church: who sees a page is said by its tag."""
    if mode() == "off" or not _is_church(biz):
        return ""
    return _menu_text()


@lru_cache(maxsize=1)
def _menu_text() -> str:
    lines: List[str] = []
    for door in _map().get("doors") or []:
        parts: List[str] = []
        for group in door.get("groups") or []:
            shown = [p for p in group.get("pages") or [] if p.get("key") not in NOT_ON_THE_MENU]
            if not shown:
                continue
            row = "; ".join(f"{p['name']} ({_path(p)}){_tag(p)}" for p in shown)
            parts.append((group["caption"] + ": " if group.get("caption") else "") + row)
        if parts:
            lead = "Home (home); " if door.get("id") == "home" else ""
            lines.append(f"  {door.get('label')} — {lead}" + " | ".join(parts))
    if not lines:
        return ""
    return (
        "THIS CHURCH'S MENU — a church does not see Operate, Grow and Build. Its menu is eleven doors down the side: "
        "Home, Sunday, People, Giving, Messages, Office, Media, Reach, Web, then Settings and Help at the foot. Each "
        "door lists its pages, some under a small heading. This is every page, as Name (tab/sub):\n"
        + "\n".join(lines) + "\n"
        "  How to use it: when someone asks where something is or how to do something, say the door, the heading if "
        "there is one, and the page by the names above (\"That is a check request. It is in Office, under Money out, "
        "Check requests.\"), then offer to take them there and open it with navigate (tab and sub as written; a "
        "build page goes in \"page\"). These names replace the business names in the destination map and SURFACE "
        "NAMES above: a church has no Contacts, Lead Flow, Today, Invoices or Services & Products on its menu. Their "
        "people are Members, Bills are what the church sends, Gifts is where giving is recorded, and money going "
        "out (paying someone back, a ministry's budget) is Check requests in Office, never Giving. In an email or a "
        "text you write TO the person who was sent one (a reminder, a thank-you), call it a bill, never an invoice: "
        "that is the word on what they received. A tag says who "
        "has the page: [money] is the owner, admins and the treasurer only; [owner] the owner and admins; any other "
        "tag names the areas whose logins have it; no tag is every login. For a login kept to a lane, never point "
        "to a page its areas do not have: say who handles it. The Help Center (operate/help-center) has the "
        "written answers; when a HELP CENTER ANSWERS block is in this turn, use it. When you open a page, the action "
        "comes back saying where it is (\"Opened Office › Money out › Check requests\"): say the place in those "
        "words, door first, and never as Operate, Grow or Build.\n"
    )


# ─── Matching what was asked (the frontend's matcher, line for line) ──

_STOP = {
    "a", "an", "the", "to", "of", "in", "on", "for", "at", "by", "with", "and", "or", "my", "our", "i", "we", "me",
    "us", "is", "are", "it", "do", "does", "can", "how", "where", "what", "who", "when", "which", "this", "that",
    "there", "need", "want", "would", "like", "should", "please", "get", "go", "find", "some", "someone",
    "something", "up", "out", "from", "into", "so", "be", "have", "has", "did", "was", "were", "will", "am", "work",
}


def _stem(w: str) -> str:
    if w == "paid":
        return "pay"
    if w == "gave":
        return "give"
    if w == "sent":
        return "send"
    if len(w) > 5 and w.endswith("ing"):
        return w[:-3]
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith("ed"):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def key_words(text: str) -> List[str]:
    words = re.split(r"[^a-z0-9]+", re.sub(r"[’']", "", (text or "").lower()))
    stems = [_stem(w) for w in words if w and w not in _STOP]
    return [w for w in stems if w not in _STOP]


def _fit(asked: List[str], phrase: List[str]) -> float:
    if not asked or not phrase:
        return 0.0
    last = len(asked) - 1
    for i, w in enumerate(asked):
        hit = w in phrase or (i == last and len(w) >= 3 and any(p.startswith(w) for p in phrase))
        if not hit:
            return 0.0
    exact = 1.0 if asked[last] in phrase else 0.9
    return exact * (0.7 + 0.3 * (len(asked) / max(len(asked), len(phrase))))


def match_answers(message: str, scope: Optional[Dict[str, Any]] = None, limit: int = 2) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """(answer, page) for the answers a message asks for, best first, cut
    to the pages the login's areas show."""
    asked = key_words(message)
    if not asked or len((message or "").strip()) < 2:
        return []
    pool: List[Tuple[Dict[str, Any], Dict[str, Any]]] = [
        (a, p) for p in _pages() if shown_to(p, scope) for a in p.get("answers") or []]
    scored: List[Tuple[float, int, Tuple[Dict[str, Any], Dict[str, Any]]]] = []
    last = len(asked) - 1
    for i, (a, p) in enumerate(pool):
        s = _fit(asked, key_words(a.get("q") or "")) * 4
        for w in a.get("words") or []:
            s = max(s, _fit(asked, key_words(w)) * 2.6)
        if not s:
            wide = key_words(" ".join([a.get("q") or "", *(a.get("words") or []), p.get("name") or "", *(p.get("words") or [])]))
            if all(w in wide or (k == last and len(w) >= 3 and any(x.startswith(w) for x in wide)) for k, w in enumerate(asked)):
                s = 1.0
        if s:
            scored.append((s, i, (a, p)))
    if not scored and len(asked) >= 3:
        # Nothing holds every word, which is usual when the question carries
        # a name ("pay Deacon Ray back"). An answer that holds at least two
        # of its words, and half of them, one of them in the task itself, is
        # still worth offering: most words first, then most in the task.
        for i, (a, p) in enumerate(pool):
            task = key_words(a.get("q") or "")
            own = key_words(" ".join([a.get("q") or "", *(a.get("words") or []), p.get("name") or "", *(p.get("words") or [])]))
            hits = sum(1 for w in asked if w in own)
            in_task = sum(1 for w in asked if w in task)
            if hits >= 2 and hits * 2 >= len(asked) and in_task:
                scored.append((hits / len(asked) + in_task / 100, i, (a, p)))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [row for _, _, row in scored[:limit]]


def _plain(text: str) -> str:
    """Lower case, letters and numbers only, a space at each end, so
    " follow up board " is found in " what is the follow up board for "."""
    return " " + " ".join(re.findall(r"[a-z0-9]+", (text or "").lower().replace("’", "").replace("'", ""))) + " "


def match_pages(message: str, scope: Optional[Dict[str, Any]] = None, limit: int = 3) -> List[Dict[str, Any]]:
    """The pages a message names: by the menu's name for them, or a word
    of two letters or more people type for them said whole."""
    text = _plain(message)
    out: List[Tuple[int, int, Dict[str, Any]]] = []
    for i, p in enumerate(_pages()):
        if not shown_to(p, scope):
            continue
        name = _plain(p.get("name") or "")
        s = 2 if len(name) > 2 and name in text else 0
        if not s:
            # One of its words said whole: a phrase, or a single word long
            # enough not to be everyday speech ("give", "text", "help").
            for w in p.get("words") or []:
                if (" " in w or len(w) >= 7) and _plain(w) in text:
                    s = 1
                    break
        if s:
            out.append((s, i, p))
    out.sort(key=lambda x: (-x[0], x[1]))
    return [p for _, _, p in out[:limit]]


# ─── This turn ────────────────────────────────────────────────────────

# A message that asks where something is or how to do it. A question about
# the church's own numbers ("what did we take in last Sunday") is not one,
# and neither is an order ("text the deacons"): the menu block covers
# opening a page by name.
_ASKS = re.compile(
    r"\b(where|how (do|can|would|should|to)\b|can'?t find|cannot find|can not find|looking for|take me to|"
    r"which (page|door|tab)|what (page|door|tab)|is there (a|any) (way|page|place)|what is .{0,40} for\b|"
    r"what does .{0,40} do\b|walk me through|show me how|how does)", re.I)


def turn_block(biz: Optional[Dict[str, Any]], message: str, scope: Optional[Dict[str, Any]] = None) -> str:
    """The Help Center's answers and the pages this message matches, for
    the turn's tail. Empty unless the business is a church, the switch is
    on, and the message reads like a "where" or a "how"."""
    if mode() == "off" or not message or not _is_church(biz) or not _ASKS.search(message):
        return ""
    try:
        answers = match_answers(message, scope, 2)
        # A page is named only when no answer was: an answer already says its page.
        named = [] if answers else match_pages(message, scope, 2)
    except Exception:  # noqa: BLE001 — a failed match adds nothing
        logger.warning("church findway: matching failed")
        return ""
    if not answers and not named:
        return ""
    lines = ["HELP CENTER ANSWERS — written from the pages themselves, the same words the app's Help Center shows. "
             "If one fits what they asked, give it in your own words, keep the button and tab names as written, say "
             "the place, and offer to take them there. If none fits, do not force it."]
    for a, p in answers:
        opens = ("open with navigate build/settings" if a.get("settings")
                 else f"open with navigate {_path(p)}")
        lines.append(f"  • {a.get('q')} — {p['where']} ({opens}): {a.get('a')}")
    for p in named:
        lines.append(f"  • The page {p['where']} ({_path(p)}): {p.get('what')}")
    return "\n".join(lines) + "\n"
