"""chief_move_in.py — Chief reads a church's move and fills an item in.

Kevin, 2026-11-11, the day the Move-in room was built (church_move_in.py):
"should this be a process that chief does … the strategy coach is who helps
them on board with no problem", then "you can allow chief to fill items as
well". The room stays the record; Chief is the guide who knows where the
move stands and types what it is told.

A pastor says "We meet Sundays at 9 and 11, the nursery is birth to two,
and Dana leads the women's group on Tuesdays." Chief saves that into Your
Sunday details as a DRAFT, says what it saved, and the pastor opens Move-in,
reads it over and presses Hand in.

    move_in_status ...... the eleven things, where each stands, what each
                          still needs, what's next, and each item's lines
                          by key so a fill names real ones. A mid-turn read
    fill_move_in ........ {item, answers}: saves the lines given into one
                          item, through the room's own cleaning and write
                          (church_move_in.clean_answers, _write). A line
                          given replaces that line (a list line is the
                          whole list); lines not given stay. An unknown
                          line changes nothing and says so. Never hands in
    undo_move_in_fill ... {item, answers}: the item's lines as they were
                          before the last fill (undo_last's inverse)

What Chief can't do here, on purpose: hand an item in (a person presses
it), add a file, or set up giving (Stripe wants the owner). It says so and
opens the page.

Who: whoever the room lets in (church_move_in._access: the owner, admins,
the office; a Viewer reads and can't fill), by the signed-in person's id.
Switched with the room (CHURCH_MOVE_IN). Action tags only, never native
write tools: they need the signed-in person (registry chief_only).
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

import church_move_in as mi

NAV = {"tab": "operate", "sub": "move-in"}
CLOSED = "The Move-in room isn't open for this church."

TOOL = {
    "name": "move_in_status",
    "description": (
        "A new church's move: the eleven things it hands in (giving setup, its people, the move owner, the tools "
        "it uses today, monthly givers, this year's giving, office logins, safety officers, Sunday details, its "
        "look, the room), where each stands (not started, started, handed in, checked, needs a change, waiting "
        "on Stripe), what each still needs, what's next, and each item's lines by key. Use it before saying "
        "what's left or done on the move, and before fill_move_in so the item and its lines are real."),
    "input_schema": {"type": "object", "properties": {}},
}


# ─── Small things ─────────────────────────────────────────────────────

def _fail(atype: str, msg: str) -> Dict[str, Any]:
    return {"type": atype, "result": f"Failed: {msg}", "label": msg[:80], "failed": True, "nav": NAV}


def _norm(v: Any) -> str:
    return " ".join(str(v or "").split()).casefold()


def _turn_user() -> str:
    from chief_of_staff import _TURN_USER_ID
    return str(_TURN_USER_ID.get() or "")


def _open(atype: str, business_id: str, write: bool = False) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """(a refusal or None, the room's own `me`). The person talking must be
    signed in and let into the room; to fill, a login that may hand in."""
    uid = _turn_user()
    if not uid:
        return _fail(atype, "the move is read and filled in only by someone signed in to the church's office."), {}
    try:
        me = mi._access(business_id, SimpleNamespace(id=uid, email=""))
    except HTTPException as e:
        if e.status_code == 404:
            return _fail(atype, CLOSED), {}
        return _fail(atype, str(e.detail)), {}
    if write and me["role"] not in mi.WRITERS:
        return _fail(atype, "this login reads the move. An admin can let it hand things in."), {}
    return None, me


def find_item(raw: Any) -> Optional[Dict[str, Any]]:
    """An item from its key or its title ("Sunday details", "your look")."""
    w = _norm(raw)
    if not w:
        return None
    for k in (w, w.replace(" ", "_").replace("-", "_")):
        if k in mi.ITEM:
            return mi.ITEM[k]
    bare = w.removeprefix("your ").removeprefix("the ")
    hits = [i for i in mi.ITEMS if _norm(i["title"]) == w or bare in _norm(i["title"])]
    return hits[0] if len(hits) == 1 else None


def _typed() -> str:
    return "; ".join(f"{i['title']} ({i['key']})" for i in mi.ITEMS if i.get("fields"))


def _lines_of(item: Dict[str, Any]) -> str:
    """An item's lines by key, so a fill names real ones."""
    out = []
    for f in item.get("fields") or []:
        if f["type"] == "rows":
            out.append(f"{f['key']} = list of {{{', '.join(c['key'] for c in f['columns'])}}}, {f['max']} at most")
        else:
            out.append(f"{f['key']} ({f['label']}{', a number' if f['type'] == 'number' else ''})")
    return "; ".join(out)


def _said(item: Dict[str, Any], answers: Dict[str, Any]) -> str:
    """What an item holds, in words."""
    parts = []
    for f in item.get("fields") or []:
        v = (answers or {}).get(f["key"])
        if v in (None, "", []):
            continue
        if f["type"] == "rows":
            rows = [" · ".join(str(r[c["key"]]) for c in f["columns"] if r.get(c["key"])) for r in v]
            parts.append(f"{f['label']}: " + "; ".join(rows))
        else:
            parts.append(f"{f['label']}: {v}")
    return ". ".join(parts)


def _live_words(shown: Dict[str, Any]) -> str:
    live = shown.get("live") or {}
    if shown["key"] == "giving":
        if live.get("ready"):
            return "Stripe has approved the church; a gift can be given."
        if live.get("connected"):
            return "The Stripe account is started; Stripe hasn't approved the church yet."
        return "Stripe isn't started; only the account owner can set it up."
    n = live.get("on_file")
    return f"{n:,} people on file." if isinstance(n, int) else ""


def _next(items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    open_ = [i for i in items if i["state"] not in ("handed_in", "checked", "done", "waiting")]
    return (next((i for i in open_ if i["state"] == "needs"), None)
            or next((i for i in open_ if i["urgent"]), None) or (open_[0] if open_ else None))


# ─── move_in_status ───────────────────────────────────────────────────

def status_sync(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    atype = "move_in_status"
    try:
        refused, me = _open(atype, business_id)
        if refused:
            return refused
        room = mi._room(me["biz"])
    except HTTPException as e:
        return _fail(atype, str(e.detail))
    p = room["progress"]
    lines = [f"{room['church']['name']}'s move: {p['settled']} of {p['total']} are in "
             "(handed in, checked, or done)."]
    for n, shown in enumerate(room["items"], start=1):
        item = mi.ITEM[shown["key"]]
        bits = [f"{n}. {shown['title']} ({shown['key']}): {shown['state_words']}."]
        if shown["state"] == "needs" and shown.get("note"):
            bits.append(f"We asked for a change: {shown['note']}")
        live = _live_words(shown)
        if live:
            bits.append(live)
        said = _said(item, shown["answers"])
        if said:
            bits.append(f"Has: {said}.")
        files = (shown.get("files") or {}).get("list") or []
        if files:
            bits.append(f"Files: {', '.join(str(f['name']) for f in files[:12])}.")
        missing = (shown.get("hand_in") or {}).get("missing")
        if missing and shown["state"] not in ("handed_in", "checked"):
            bits.append(f"Before it can be handed in: {missing}")
        if item.get("fields"):
            bits.append(f"Lines: {_lines_of(item)}.")
        if item.get("files"):
            bits.append("Takes files, which they add on the page.")
        lines.append(" ".join(bits))
    nxt = _next(room["items"])
    lines.append(f"Next: {nxt['title']}." if nxt else "Everything is in. We look each one over and mark it checked.")
    left = p["total"] - p["settled"]
    return {"type": atype, "result": "\n".join(lines), "label": f"The move · {p['settled']} of {p['total']} in",
            "nav": NAV, "settled": p["settled"], "total": p["total"], "next": nxt["key"] if nxt else None,
            "note_for_chief": (
                "Say where the move stands from this, by each item's name, and what's next"
                + (f" ({left} still to do)" if left else "") + ". To save what they tell you, fill_move_in with "
                "the item's key and its lines by key. It saves a draft: they open Move-in, read it over and press "
                "Hand in themselves. You can't hand in, add a file, or set up giving; say so and open the page.")}


async def handle_move_in_status(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(status_sync, str((biz or {}).get("id") or ""), action or {})


# ─── fill_move_in ─────────────────────────────────────────────────────

def _save(atype: str, business_id: str, action: Dict[str, Any], *, whole: bool) -> Dict[str, Any]:
    """Write an item's lines. `whole` puts the given lines in place of all
    of them (the undo); otherwise a line given replaces that line only."""
    if action.get("_unattended"):
        return _fail(atype, "an item is filled in only when someone at the church says what goes in it.")
    try:
        refused, me = _open(atype, business_id, write=True)
        if refused:
            return refused
        item = find_item(action.get("item"))
        if not item or not item.get("fields"):
            if item and item["key"] == "giving":
                return _fail(atype, "giving is set up with Stripe by the account owner, on the page. "
                                    "There's nothing to type.")
            if item:
                return _fail(atype, f"“{item['title']}” takes files, which they add on the Move-in page. "
                                    "There's nothing to type.")
            return _fail(atype, f"there's no move-in item called “{str(action.get('item') or '').strip()}”. "
                                f"The ones with lines to fill in: {_typed()}.")
        given = action.get("answers")
        if not isinstance(given, dict) or (not given and not whole):
            return _fail(atype, f"say what goes in “{item['title']}”: {_lines_of(item)}.")
        known = {f["key"] for f in item["fields"]}
        strange = sorted(k for k in given if k not in known)
        if strange:
            return _fail(atype, f"“{item['title']}” has no line called {', '.join(strange)}. Nothing changed. "
                                f"Its lines: {_lines_of(item)}.")
        biz_id = str(me["biz"]["id"])
        had = mi._rows_of(biz_id).get(item["key"])
        before = dict((had or {}).get("answers") or {})
        try:
            after = mi.clean_answers(item, given if whole else {**before, **given})
        except HTTPException as e:
            if e.status_code == 400:
                return _fail(atype, f"{e.detail} Nothing changed.")
            raise
        if after == before:
            return {"type": atype, "result": f"“{item['title']}” already says that. Nothing changed.",
                    "label": f"{item['title']} · no change", "nav": NAV, "item": item["key"], "changed": False}
        was_in = (had or {}).get("state") in ("handed_in", "checked")
        mi._write(biz_id, item["key"], had, {"answers": after, "updated_by": me["uid"], **mi._reopened(had)})
        room = mi._room(me["biz"])
    except HTTPException as e:
        return _fail(atype, str(e.detail))
    shown = next(i for i in room["items"] if i["key"] == item["key"])
    missing = (shown.get("hand_in") or {}).get("missing")
    said = _said(item, after) or "nothing"
    head = (f"Put “{item['title']}” back the way it was. It now holds: {said}." if whole
            else f"Saved a draft of “{item['title']}”. It now holds: {said}.")
    tail = [head, "It is not handed in."]
    if was_in:
        tail.append("It had been handed in, and this change took it back, so it needs handing in again.")
    tail.append(f"Before it can be handed in: {missing}" if missing
                else "It's ready: they open Move-in, read it over and press Hand in.")
    return {"type": atype, "result": " ".join(tail), "label": f"{item['title']} · draft saved", "nav": NAV,
            "item": item["key"], "before": before, "changed": True, "ready": not missing}


def fill_sync(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    return _save("fill_move_in", business_id, action, whole=False)


def undo_sync(business_id: str, action: Dict[str, Any]) -> Dict[str, Any]:
    return _save("undo_move_in_fill", business_id, action, whole=True)


async def handle_fill_move_in(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(fill_sync, str((biz or {}).get("id") or ""), action or {})


async def handle_undo_move_in_fill(client, biz, action) -> Dict[str, Any]:
    return await asyncio.to_thread(undo_sync, str((biz or {}).get("id") or ""), action or {})
