"""
chief_inbound.py — Chief's side of "Needs a look" (inbound_hold).

    mark_real_person ......... {contact_id | name}: a held card is a real person.
                               What it held runs now (their follow-up, their
                               Welcome Path); this church remembers the sender.
    mark_not_a_guest ......... {contact_id | name}: closes their follow-ups,
                               takes them off the Welcome Path, marks them
                               inactive. Works on anyone, held or not (the
                               2026-11-26 card that was never held, too).
    undo_inbound_decision .... {decision_id}: put either back (action_inverse);
                               the person waits for a look again.

Class A: each one is undone by the third. Scam is never Chief's: it reaches
other churches (the shared list), so it is the office's own tap in Members.

Who may: someone signed in with a Manager seat or above at the business, the
Members roll's own gate (inbound_hold.MIN_ROLE). Never unattended.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote

from fastapi import HTTPException

VERBS = ("mark_real_person", "mark_not_a_guest", "undo_inbound_decision")
NAV = {"tab": "operate", "sub": "contacts"}


def _plain(v: Any) -> str:
    return " ".join(str(v or "").split())


def _fail(atype: str, msg: str) -> Dict[str, Any]:
    said = _plain(msg) or "That couldn't be done just now."
    said = said[:1].upper() + said[1:]
    return {"type": atype, "result": f"Failed: {said}", "label": said[:120], "failed": True, "nav": NAV}


def _turn_user() -> str:
    try:
        from chief_duties import _turn_user as tu
        return str(tu() or "")
    except Exception:  # noqa: BLE001
        return ""


def _who(biz_id: str, uid: str) -> Tuple[Optional[str], str]:
    """(their role here or None, a name for the record)."""
    import business_users_router as bur
    role = bur.role_of(biz_id, uid)
    name = ""
    try:
        import chief_church_schedule as ccs
        email = ccs._email(uid) or ""
        name = email.split("@")[0] if email else ""
    except Exception:  # noqa: BLE001
        name = ""
    return role, name


def _person(biz_id: str, action: Dict[str, Any]) -> Tuple[Optional[str], str]:
    """(contact id, '' ) or (None, why). By id, else by a name that names one person."""
    raw = action.get("contact_id")
    if raw:
        try:
            return str(uuid.UUID(str(raw))), ""
        except ValueError:
            return None, "that isn't one of the church's people."
    name = _plain(action.get("name") or action.get("person"))
    if not name:
        return None, "say who: their name, or the person from the list."
    import sb_clients
    safe = quote(name.replace("*", ""), safe="")
    rows = sb_clients.sb_get_as_service(f"/contacts?business_id=eq.{quote(biz_id, safe='')}&name=ilike.*{safe}*"
                                        "&select=id,name&limit=3")
    if not isinstance(rows, list):
        return None, "the people couldn't be read just now. Try again in a minute."
    exact = [r for r in rows if _plain(r.get("name")).lower() == name.lower()]
    pick = exact if len(exact) == 1 else rows
    if len(pick) != 1:
        return None, (f"I couldn't find {name}." if not pick else f"more than one person is called {name}; "
                      "say which one.")
    return str(pick[0]["id"]), ""


def _run(atype: str, biz: Any, action: Any) -> Dict[str, Any]:
    action = action if isinstance(action, dict) else {}
    try:
        if action.get("_unattended"):
            return _fail(atype, "only someone at the office can mark a card.")
        uid = _turn_user()
        if not uid:
            return _fail(atype, "marking a card is for someone signed in.")
        bid = str((biz or {}).get("id") or "")
        import business_users_router as bur
        import inbound_hold
        role, by_name = _who(bid, uid)
        if not role or bur._ROLE_RANK.get(role, 0) < bur._ROLE_RANK.get(inbound_hold.MIN_ROLE, 99):
            return _fail(atype, "marking a card needs a Manager seat or above at the church.")
        if atype == "undo_inbound_decision":
            out = inbound_hold.undo(bid, str(action.get("decision_id") or ""), by_user=uid)
            return {"type": atype, "result": out["said"], "label": out["said"][:120], "nav": NAV,
                    "decision_id": out["decision_id"], "contact_id": out["contact_id"]}
        cid, why = _person(bid, action)
        if not cid:
            return _fail(atype, why)
        verdict = inbound_hold.REAL if atype == "mark_real_person" else inbound_hold.NOT_A_GUEST
        out = inbound_hold.decide(bid, cid, verdict, by_user=uid, by_name=by_name, via="chief")
        if out.get("nudge"):
            try:
                import chief_agent
                chief_agent.nudge(bid, "contact_form_submitted")
            except Exception:  # noqa: BLE001
                pass
        return {"type": atype, "result": out["said"] + " Undo puts it back.", "label": out["said"][:120],
                "nav": NAV, "decision_id": out["decision_id"], "contact_id": cid, "name": out["name"]}
    except HTTPException as e:
        return _fail(atype, str(e.detail) if e.status_code != 404 else (str(e.detail) or "That isn't here."))
    except Exception as e:  # noqa: BLE001 — a failure is said, never a blank screen
        print(f"[chief_inbound] {atype} failed: {type(e).__name__}", flush=True)
        return _fail(atype, "that couldn't be done just now. Nothing changed. Try again in a minute.")


def _handler(atype: str):
    async def handle(client, biz, action) -> Dict[str, Any]:
        return await asyncio.to_thread(_run, atype, biz, action or {})
    handle.__name__ = f"handle_{atype}"
    handle.__qualname__ = handle.__name__
    return handle


HANDLERS = {verb: _handler(verb) for verb in VERBS}
PROGRESS = {
    "mark_real_person": "marking them a real person",
    "mark_not_a_guest": "marking them not a guest",
    "undo_inbound_decision": "putting that back",
}
