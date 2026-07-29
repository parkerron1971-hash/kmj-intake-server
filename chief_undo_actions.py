"""
chief_undo_actions.py — "undo that".

The verb that makes action_registry's class A mean something a practitioner
can press. Before this, restore_previous_site was the only real undo in the
system and everything else was reversible in principle only.

TWO VERBS
  undo_last  — reverse the most recent reversible action (a WRITE: it runs
               the inverse handler)
  what_undo  — what would undo do, without doing it (a READ)

The second exists because undo is frightening in proportion to how vague it
is. "I'll un-block Aug 3-7 — say go" is a different experience from a bare
"undo?", and it costs one extra turn to be certain.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import action_inverse

logger = logging.getLogger("chief_undo_actions")


def _fail(action_type: str, msg: str) -> Dict[str, Any]:
    return {"type": action_type, "result": f"failed: {msg}",
            "label": msg[:80], "nav": None}


async def _most_recent(client, biz) -> Optional[Dict[str, Any]]:
    """The newest still-undoable action inside the window."""
    from chief_of_staff import _sb
    cutoff = (datetime.now(timezone.utc)
              - timedelta(hours=action_inverse.UNDO_WINDOW_HOURS))
    # PostgREST timestamp class: the Z form. isoformat's +00:00 silently
    # returns empty in a query string.
    cutoff_z = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = await _sb(client, "GET",
        f"/chief_undo_log?business_id=eq.{biz['id']}&status=eq.undoable"
        f"&created_at=gte.{cutoff_z}&order=created_at.desc&limit=1&select=*")
    return rows[0] if rows else None


async def handle_what_undo(client, biz, action) -> Dict[str, Any]:
    """What WOULD undo do? Changes nothing."""
    row = await _most_recent(client, biz)
    if not row:
        return {"type": "what_undo",
                "result": (f"nothing to undo from the last "
                           f"{action_inverse.UNDO_WINDOW_HOURS} hours"),
                "label": "Nothing to undo", "nav": None}

    verb = row.get("action_type") or ""
    return {
        "type": "what_undo",
        "result": (f"the last thing I can take back is “{verb}” — undoing it "
                   f"would {action_inverse.describe(verb)}"),
        "label": f"Undo available: {verb}",
        "nav": None,
    }


async def handle_undo_last(client, biz, action) -> Dict[str, Any]:
    """Reverse the most recent reversible action."""
    from chief_of_staff import ACTION_HANDLERS, _sb, _action_failed

    row = await _most_recent(client, biz)
    if not row:
        return {"type": "undo_last",
                "result": (f"nothing to undo from the last "
                           f"{action_inverse.UNDO_WINDOW_HOURS} hours"),
                "label": "Nothing to undo", "nav": None}

    verb = row.get("action_type") or ""
    inverse = action_inverse.build_inverse(
        verb, row.get("action_json") or {}, row.get("result_json") or {})

    if not inverse:
        # Should be rare — the recorder only logs actions whose inverse
        # built cleanly at the time. Reaching here means something about
        # the payload changed shape since.
        return {"type": "undo_last",
                "result": f"can't undo “{verb}” — {action_inverse.why_not(verb)}",
                "label": f"Can't undo {verb}", "nav": None}

    handler = ACTION_HANDLERS.get(inverse.get("type"))
    if not handler:
        return _fail("undo_last",
                     f"no handler for the inverse '{inverse.get('type')}'")

    res = await handler(client, biz, inverse)

    if _action_failed(res):
        # Leave the row UNDOABLE. A failed undo that marks itself done is
        # how a practitioner ends up believing something was reversed when
        # it was not.
        return {"type": "undo_last",
                "result": (f"couldn't undo “{verb}” — {res.get('result')}. "
                           f"Nothing changed; you can try again."),
                "label": f"Undo failed: {verb}",
                "nav": res.get("nav")}

    await _sb(client, "PATCH", f"/chief_undo_log?id=eq.{row['id']}", {
        "status": "undone",
        "undone_at": datetime.now(timezone.utc).isoformat(),
        "undo_result": str(res.get("result"))[:240],
    })

    return {
        "type": "undo_last",
        "result": f"undone — {res.get('result')}",
        "label": f"↩ Undid {verb}",
        "nav": res.get("nav"),
    }
