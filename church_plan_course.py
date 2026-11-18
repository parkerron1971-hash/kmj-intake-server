"""church_plan_course.py — a church's planning course.

The Solutionist Academy is a business strategy course: market research,
pricing, service packages, a launch plan. It sat on every church's Help
door too, and a pastor who opened it was asked about the idea he wanted to
launch and what he would charge (Kevin, 2026-11-17: "keep for business and
build a church planning course").

A church gets its own course on the same page and in the same coached,
resumable shape: eight parts, each one a conversation with a planning
coach that ends as a page of the church's plan.

    1. calling       why this church is here: mission, vision, values, story
    2. community     who is around it, who comes now, who it wants to reach
    3. path          how someone goes from a first visit to belonging
    4. ministries    what the church does, who leads it, what to keep or start
    5. leaders       who carries the work, where it is thin, how leaders are raised
    6. stewardship   what the money is for, how giving stands, what to aim at
    7. honest_look   what is strong, what is weak, what is open, what could hurt
    8. ninety_days   the next 90 days, week by week, each step tied to a page

WHERE IT IS KEPT
The same row a business's course uses (strategy_tracks, one per business),
so nothing new is created in the database. Parts 1 to 7 are kept in the
row's `phases` object under their own ids, beside the session log, the way
a business's discovery already is. Part 8 is kept in `launch_plan` in the
shape a business's launch plan has ({weeks: [{week, theme, actions}]}), so
ticking a step off works the way it always has.

WHAT A CHURCH'S COURSE NEVER DOES
Finishing a business's course builds a website, makes a products page and
an intake form, and rewrites the business's settings. A church has its
website and its cards already. Finishing a church's course marks the plan
written and changes nothing else (see `finish`).

WHO IT IS FOR
The verbs that save a part are the owner's and admins' alone
(chief_areas.OWNERS), so the page is on the owner's and admins' menu only.
The plan holds what a pastor says about leaders, ministries and money.

Every string a person can read here is in a church's words: people,
members, guests, gifts, ministries. Never clients, customers, leads,
revenue, pricing or launch.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

TEXT_MAX = 1200
ITEM_MAX = 240
LIST_MAX = 12
ROWS_MAX = 16
WEEKS_MAX = 13

# What a ministry is to be: the four words the page shows.
CALLS = ("keep", "grow", "fix", "pause")

# id, title, what the part is for (said to the coach), and its fields:
# (key, kind, columns for rows). Kinds: text, list, rows.
PARTS: List[Dict[str, Any]] = [
    {"id": "calling", "title": "Calling",
     "about": "why this church is here: its mission in a sentence, where it believes it is being led, "
              "what it will not give up, and the short story of how it came to be",
     "fields": [("mission", "text", None), ("vision", "text", None), ("values", "list", None), ("story", "text", None)]},
    {"id": "community", "title": "Community",
     "about": "who is around the church and who it is for: the neighborhood, who comes now, "
              "who the church wants to reach next, and what those people need",
     "fields": [("neighborhood", "text", None), ("who_comes_now", "text", None),
                ("who_to_reach", "list", None), ("needs", "list", None)]},
    {"id": "path", "title": "The path",
     "about": "how someone goes from a first visit to belonging: each step, what happens at it, "
              "who owns it, and where people are lost today",
     "fields": [("steps", "rows", ("name", "what_happens", "who_owns_it", "gap"))]},
    {"id": "ministries", "title": "Ministries",
     "about": "what the church does week to week: each ministry, who leads it, who it serves, "
              "and whether to keep it, grow it, fix it or pause it; then what to start and what to stop",
     "fields": [("ministries", "rows", ("name", "leader", "serves", "call", "note")),
                ("start", "list", None), ("stop", "list", None)]},
    {"id": "leaders", "title": "Leaders",
     "about": "who carries the work: each team and its leader, where the church is thin, "
              "how new leaders are found and raised, and how leaders are cared for",
     "fields": [("teams", "rows", ("name", "leader", "needs")), ("gaps", "list", None),
                ("raising_leaders", "text", None), ("care", "text", None)]},
    {"id": "stewardship", "title": "Stewardship",
     "about": "what the church's money is for: what comes first in the budget, how giving stands today "
              "in the pastor's own words, what to aim at, and what could go wrong",
     "fields": [("priorities", "list", None), ("giving_today", "text", None),
                ("goals", "list", None), ("risks", "list", None)]},
    {"id": "honest_look", "title": "An honest look",
     "about": "a plain look at the whole church after the first six parts: what is strong, "
              "what is weak, what doors are open, and what could hurt it",
     "fields": [("strengths", "list", None), ("weaknesses", "list", None),
                ("open_doors", "list", None), ("risks", "list", None)]},
    {"id": "ninety_days", "title": "The next 90 days",
     "about": "the plan turned into the next 90 days: a few steps a week, each one small enough to do, "
              "and tied to the page of the app where it is done when there is one",
     "fields": []},
]
_BY_ID = {p["id"]: p for p in PARTS}
FIRST = PARTS[0]["id"]
LAST = PARTS[-1]["id"]


def ids() -> List[str]:
    return [p["id"] for p in PARTS]


def title(part: str) -> str:
    return (_BY_ID.get(part) or {}).get("title") or str(part).replace("_", " ")


def is_church(biz: Optional[Dict[str, Any]]) -> bool:
    try:
        import church_follow_up
        return church_follow_up.is_church(biz or {})
    except Exception:  # noqa: BLE001 — not knowing is "not a church"
        return False


# ─── Cleaning what the coach saves ────────────────────────────────────

def _text(v: Any, most: int = TEXT_MAX) -> str:
    return " ".join(str(v).split())[:most] if isinstance(v, (str, int, float)) and not isinstance(v, bool) else ""


def _list(v: Any) -> List[str]:
    if isinstance(v, str):
        v = [line for line in v.replace("\r", "").split("\n")]
    if not isinstance(v, list):
        return []
    out = [_text(i, ITEM_MAX).lstrip("-• ").strip() for i in v]
    return [i for i in out if i][:LIST_MAX]


def _rows(v: Any, cols: Tuple[str, ...]) -> List[Dict[str, str]]:
    if not isinstance(v, list):
        return []
    out: List[Dict[str, str]] = []
    for r in v:
        if isinstance(r, str):
            r = {cols[0]: r}
        if not isinstance(r, dict):
            continue
        row = {c: _text(r.get(c), ITEM_MAX) for c in cols}
        if "call" in row:
            call = row["call"].lower()
            row["call"] = call if call in CALLS else ""
        if row.get(cols[0]):
            out.append({c: val for c, val in row.items() if val})
    return out[:ROWS_MAX]


def clean(part: str, data: Any) -> Optional[Dict[str, Any]]:
    """What is kept of a part the coach saved: the part's own fields, at a
    sane size, and nothing else. None when nothing is left to keep."""
    spec = _BY_ID.get(part)
    if not spec or not isinstance(data, dict) or part == LAST:
        return None
    out: Dict[str, Any] = {}
    for key, kind, cols in spec["fields"]:
        raw = data.get(key)
        val: Any = _text(raw) if kind == "text" else _list(raw) if kind == "list" else _rows(raw, cols)
        if val:
            out[key] = val
    return out or None


def links() -> Dict[str, str]:
    """Every page on a church's menu a step may point at: 'area:id' -> where
    it is, in the menu's words."""
    try:
        import church_findway
        return {p["key"]: p["where"] for p in church_findway.pages() if p.get("key") and p.get("where")}
    except Exception:  # noqa: BLE001 — without the menu a step keeps its words and loses its link
        return {}


def clean_weeks(weeks: Any) -> List[Dict[str, Any]]:
    """The 90 days as kept: the launch plan's own shape, with a step's link
    kept only when it is a page on a church's menu."""
    if not isinstance(weeks, list):
        return []
    known = links()
    out: List[Dict[str, Any]] = []
    for w in weeks:
        if not isinstance(w, dict):
            continue
        steps: List[Dict[str, Any]] = []
        for a in (w.get("actions") or [])[:8]:
            if isinstance(a, str):
                a = {"description": a}
            if not isinstance(a, dict):
                continue
            words = _text(a.get("description") or a.get("text"), ITEM_MAX)
            if not words:
                continue
            step: Dict[str, Any] = {"description": words, "completed": bool(a.get("completed", False))}
            link = _text(a.get("system_link"), 60).replace("/", ":")
            if link in known:
                step["system_link"] = link
            steps.append(step)
        if steps:
            try:
                number = int(w.get("week") or len(out) + 1)
            except (TypeError, ValueError):
                number = len(out) + 1
            out.append({"week": number, "theme": _text(w.get("theme"), 80), "actions": steps})
    return out[:WEEKS_MAX]


# ─── Reading the row ──────────────────────────────────────────────────

def page(track: Optional[Dict[str, Any]], part: str) -> Any:
    """A part's saved page, or None."""
    track = track or {}
    if part == LAST:
        plan = track.get("launch_plan") or {}
        return plan if (plan.get("weeks") if isinstance(plan, dict) else None) else None
    got = (track.get("phases") or {}).get(part)
    return got if isinstance(got, dict) and got else None


def done(track: Optional[Dict[str, Any]]) -> List[str]:
    return [p for p in ids() if page(track, p)]


def current(track: Optional[Dict[str, Any]]) -> str:
    """The part the church is on. A row a business's course began (its
    current_phase is one of that course's) starts at the first part not done."""
    at = (track or {}).get("current_phase")
    if at in _BY_ID:
        return at
    finished = set(done(track))
    return next((p for p in ids() if p not in finished), LAST)


def finished(track: Optional[Dict[str, Any]]) -> bool:
    return (track or {}).get("status") in ("completed", "complete")


# ─── What the coach is told ───────────────────────────────────────────

def _shape(part: Dict[str, Any]) -> str:
    """The save line for one part, as the coach emits it."""
    data: Dict[str, Any] = {}
    for key, kind, cols in part["fields"]:
        data[key] = "..." if kind == "text" else ["...", "..."] if kind == "list" else [
            {c: ("keep|grow|fix|pause" if c == "call" else "...") for c in cols}]
    return '  [ACTION:' + json.dumps({"type": "save_phase", "phase": part["id"], "data": data}) + ']'


def _digest(track: Optional[Dict[str, Any]]) -> str:
    """The pages already written, short, so the coach builds on them."""
    lines: List[str] = []
    for p in PARTS:
        got = page(track, p["id"])
        if not got:
            continue
        if p["id"] == LAST:
            weeks = got.get("weeks") or []
            steps = sum(len(w.get("actions") or []) for w in weeks)
            lines.append(f"  {p['title']}: {len(weeks)} weeks, {steps} steps")
            continue
        bits: List[str] = []
        for key, kind, cols in p["fields"]:
            val = got.get(key)
            if not val:
                continue
            if kind == "text":
                bits.append(f"{key}: {str(val)[:220]}")
            elif kind == "list":
                bits.append(f"{key}: " + "; ".join(str(i)[:80] for i in val[:6]))
            else:
                bits.append(f"{key}: " + "; ".join(
                    str(r.get(cols[0], ""))[:50] + (f" ({r['call']})" if r.get("call") else "") for r in val[:10]))
        lines.append(f"  {p['title']}: " + " | ".join(bits))
    return "\n".join(lines) or "  (nothing written yet)"


def office_team_block(track: Optional[Dict[str, Any]], structure: str = "") -> str:
    """The coach's part in the standard start (church_structure): once the
    Leaders part is written it may offer, ONCE, to draft the office team
    from what the pastor just said. The draft is a proposal the pastor
    reviews on Logins & areas; writing or finishing the plan still changes
    nothing by itself. `structure` is who already does what in the office
    (church_structure.coach_block), so the coach doesn't ask twice. '' until
    Leaders is written and there is nothing to hand it."""
    out = (structure.rstrip() + "\n\n") if structure and structure.strip() else ""
    if not page(track, "leaders"):
        return out
    waiting = "A draft of the office team is waiting" in structure
    return out + (
        "THE OFFICE TEAM (the Leaders part is written, so this is open to you)\n"
        + ("- A draft of the office team is already waiting for their review, so do NOT offer to make one. If "
           "they ask, say it is on Logins & areas and offer to open it.\n" if waiting else
           "- ONCE in this course, at a natural pause after the Leaders part is saved, you may offer: \"Want me to "
           "set up your office team from what you just told me? You'd review each person before anything "
           "changes.\" If RECENT SESSIONS shows you already offered, or they said no, do not offer again.\n")
        + "- On a yes, emit silently, with the people THEY named in this conversation and what each does, in "
        "their words (a title only if they said one; never a name they did not say; leave money out unless "
        "they told you who counts, who deposits and who keeps the books):\n"
        '  [ACTION:{"type":"draft_church_structure","answers":{"leads":"pastor|pastor_board|elders|staff",'
        '"people":[{"name":"...","title":"...","does":"..."}],"guests":"..."}}]\n'
        "  It makes a DRAFT and nothing else: no login, no invitation, no job and no sheet. Then say in one "
        "sentence that the draft is waiting on Logins & areas, that each person is reviewed there before "
        "anything changes, and offer to open it:\n"
        '  [ACTION:{"type":"navigate","tab":"operate","sub":"areas","setup":1}]\n'
        "- Never say anyone was invited or given access. Then come back to the plan.\n"
        "- A step in the next 90 days about setting up the office team may point at operate/areas.\n\n")


def coach_prompt(ctx: Dict[str, Any], is_greeting: bool, resume_note: Any = None,
                 shared_core: str = "", knowledge_block: str = "", learning: str = "",
                 structure: str = "") -> str:
    """The planning coach's whole prompt, for a church in a course session."""
    biz = ctx.get("business") or {}
    church = biz.get("name") or "the church"
    settings = biz.get("settings") or {}
    pastor = settings.get("practitioner_name") or "the pastor"
    track = ctx.get("strategy_track") or {}
    at = current(track)
    finished_parts = done(track)
    log = ((track.get("phases") or {}).get("session_log") or [])[-3:]
    history = "\n".join(
        f"  - {s.get('date')}: {s.get('summary')} [covered: {', '.join(s.get('phases_progressed') or [])}]"
        for s in log if isinstance(s, dict)) or "  (this is the first session)"

    opening = ""
    if is_greeting:
        if log:
            last = log[-1]
            opening = (
                "\n\nOPENING (COMING BACK):\n"
                f"{pastor} is coming back. Last time ({last.get('date')}) you covered: {last.get('summary')}.\n"
                "Welcome them back in one or two sentences that name what you worked on, then ask ONE question "
                f"that moves the part you are on ({title(at)}) forward. Do not recap everything. "
                "Do not emit actions in the opening message.")
        else:
            opening = (
                "\n\nOPENING (FIRST SESSION):\n"
                f"A warm, unhurried welcome. Say you are {pastor}'s planning coach and that together you will "
                f"write {church}'s plan: where it is going, who it is for, and what the next 90 days hold. "
                "Say it takes a few sittings and they can stop at any point and pick it up later. "
                "Then ask ONE real question to begin, about why this church is here. "
                "If the answer is already in what you know about the church, say what you know and ask the one "
                "thing that is not settled. Three or four sentences in all. Do not emit actions in the opening.")

    gap = ""
    minutes = getattr(resume_note, "gap_minutes", 0) if resume_note else 0
    if minutes and minutes > 0:
        said = f"{minutes}m" if minutes < 60 else f"{round(minutes / 60, 1)}h"
        gap = (f"\n\nGAP: {said} since the last message in this conversation. Say so briefly if it is natural; "
               "otherwise keep going.")

    menu = ""
    try:
        import church_findway
        menu = church_findway.menu_block(biz)
    except Exception:  # noqa: BLE001 — the coach still coaches without the menu
        menu = ""

    parts = "\n".join(f"{n}. {p['title'].upper()}: {p['about']}" for n, p in enumerate(PARTS, 1))
    saves = "\n".join(_shape(p) for p in PARTS if p["id"] != LAST)
    known = (f"\nWHAT YOU KNOW ABOUT THIS CHURCH (kept privately by the church's Chief):\n{knowledge_block}\n{learning}\n"
             if knowledge_block or learning else "")

    return f"""You are a planning coach for a church, inside The Solutionist System. You help a pastor and the church's leaders write the church's plan through honest conversation.

You are {pastor}'s planning coach at {church}.

{shared_core}
{known}
WHO YOU ARE TALKING TO
- A pastor or a church administrator, not a business owner. Speak the way a trusted older pastor or a seasoned church consultant would: warm, plain, unhurried, and honest.
- A church's words only: people, members, guests, gifts and giving, ministries, the church. Never clients, customers, leads, prospects, revenue, sales, pricing, packages, brand, market, competitors or launch.
- Churches differ in tradition, size and culture. Do not assume a denomination, a style of worship, a way of governing, or a theology the pastor has not told you. Ask. Use their words for their offices and ministries once you hear them.
- You are not the pastor's theologian. Do not preach, quote scripture to make a point, or tell them what God is saying. They bring the calling; you help them say it plainly and plan around it. If they bring scripture, receive it and work with it.
- Be honest. If a plan asks more of volunteers than the church has, say so and offer a smaller first step. A plan the church can keep is better than one that sounds good.

YOUR STYLE
- A conversation, not a form. One question at a time. Build on what they said.
- The parts are INVISIBLE to them. Never say "part 3" or "now let's move to". Flow from one subject to the next.
- Short. Two to five sentences, then a question. No bullet lists unless you are reading a page back to them.
- When you have enough for a part, read it back in a few plain sentences ("Here is what I have for the path someone walks...") and ask if it is right before you save it.

THE EIGHT PARTS (hidden from them)
{parts}

RULES
- Use what is already written. Do not ask again for something a saved page already says, unless they are changing it.
- Save a part SILENTLY once they agree it is right, with the save line for that part below. Then move on with advance_phase, also silently. Do not narrate saving.
- Numbers come from them. Never invent an attendance figure, a giving figure, a budget or a date. If they give a number, use it as they said it. Do not ask what individual people give.
- Names of people belong to them. Write a leader's name only when they said it.
- The last part is the next 90 days. Build it from the pages already written: a few steps a week, each small enough to do in that week, in their words. Where a step is done on a page of this church's menu, put that page in "system_link" exactly as the menu below writes it in brackets (for example operate/follow-up). Leave "system_link" out when no page fits. Save it with save_launch_plan.
- When the 90 days are saved and they say the plan is right, emit complete_strategy_track. That marks the plan written. It builds nothing and changes nothing else.
- Offer to stop when it is natural: "That is a good place to pause. Want to keep going or pick this up next time?" When they stop, emit session_summary with one or two sentences and the parts you touched.
- If they ask how to do something in the app, tell them the door and the page from the menu below in a sentence, then come back to the plan. You may open a page for them with navigate when they ask.
- Do not send anything, text or email anyone, move money, or change the church's records. You write the plan. Their Chief does the rest.

WHERE THINGS STAND
  Church: {church}
  You are on (hidden from them): {at} ({title(at)})
  Parts written: {', '.join(title(p) for p in finished_parts) if finished_parts else '(none)'}
  The plan so far:
{_digest(track)}

RECENT SESSIONS
{history}

{office_team_block(track, structure)}ACTIONS (all emitted silently, inside your reply)
{saves}
  [ACTION:{{"type":"save_launch_plan","weeks":[{{"week":1,"theme":"...","actions":[{{"description":"...","system_link":"operate/follow-up"}},{{"description":"..."}}]}}]}}]
  [ACTION:{{"type":"advance_phase","to":"{'|'.join(ids()[1:])}"}}]
  [ACTION:{{"type":"session_summary","summary":"...","phases_progressed":["calling","community"]}}]
  [ACTION:{{"type":"complete_strategy_track"}}]
  [ACTION:{{"type":"navigate","tab":"operate","sub":"follow-up"}}]

{menu}{opening}{gap}"""


# ─── What the everyday Chief is told ──────────────────────────────────

def chief_block(track: Optional[Dict[str, Any]]) -> str:
    """The church's plan, for Chief on an ordinary turn: what is written, so
    its advice fits where the church says it is going. Empty with no plan."""
    if not track:
        return ""
    written = done(track)
    if not written:
        return ""
    calling = page(track, "calling") or {}
    lines = ["THE CHURCH'S PLAN (written by the pastor in the church planning course; the page is Help › Church planning course):"]
    if calling.get("mission"):
        lines.append(f"  Mission: {str(calling['mission'])[:300]}")
    if calling.get("vision"):
        lines.append(f"  Vision: {str(calling['vision'])[:300]}")
    if calling.get("values"):
        lines.append("  Values: " + "; ".join(str(v)[:60] for v in calling["values"][:8]))
    reach = (page(track, "community") or {}).get("who_to_reach")
    if reach:
        lines.append("  Wants to reach: " + "; ".join(str(v)[:80] for v in reach[:5]))
    plan = page(track, LAST)
    if plan:
        steps = [a for w in plan.get("weeks") or [] for a in w.get("actions") or []]
        ticked = sum(1 for a in steps if a.get("completed"))
        lines.append(f"  The next 90 days: {ticked} of {len(steps)} steps done.")
    left = [title(p) for p in ids() if p not in written]
    lines.append(f"  Parts written: {', '.join(title(p) for p in written)}."
                 + (f" Still to write: {', '.join(left)}." if left and not finished(track) else ""))
    lines.append(
        "  Let this shape your advice: when they ask what to do about guests, leaders, ministries or giving, answer "
        "plainly and in line with what the plan says. If the plan is not finished, you may offer once, in one closing "
        "line, to open the church planning course to write the next part. Never say Academy, strategy session, "
        "launch, pricing or packages to a church. You do not save parts of the plan yourself: that is done in a "
        "course session.")
    return "\n".join(lines)
