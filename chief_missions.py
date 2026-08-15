"""
chief_missions.py — Chief executes plans, not just moves.

The Jarvis arc, step 3 (Kevin, 8/14: "anything that is requested in the
system, I want Chief to be able to do with no problem" — and 8/15:
"let's continue with the missions upgrade").

A mission is a persistent multi-step plan: proposed as a draft the
practitioner can read, started on their word, executed step by step, and
REMEMBERED across turns — so "get my unpaid invoices collected" becomes
list → draft reminders → (your approval) → send → schedule follow-ups →
report back, instead of one move and amnesia.

The trust story, which is the design:

  * Steps DISPATCH THROUGH chief_of_staff._execute_actions — the same
    door every chat-emitted action walks through. The Class-C trust
    gate, the per-turn class-C cap, the fail-closed registry check and
    the ledger all apply to mission steps automatically, because the
    mission engine never touches a handler directly.
  * On top of that, any class-C step (irreversible: sends, deletes,
    money) PAUSES the mission as awaiting_approval before it runs. The
    practitioner advances it with a word; advance_mission is itself
    class-C, so the approval flows through the chat loop's own gate.
    Class-A/B steps run without a pause — the practitioner approved
    the plan that contains exactly these steps when they started it.
  * Verbs a mission may contain = ACTION_HANDLERS minus the mission
    verbs themselves (no recursion) minus pure window dressing
    (set_chat_window / navigate / close_view). Reads are welcome —
    a step can look before the next step leaps.
  * A failed step pauses the mission and says so. It never silently
    skips, and it never claims the plan finished (empty states that
    lie, mission edition).

Storage: one row in chief_missions, steps as JSONB, written through the
context-bound _sb (the practitioner's own JWT in a chat turn; RLS is
the authority). Every write is verified — _sb returns None on a refused
write, and a mission engine that reports progress it failed to save
would be the wholesale-replace bug wearing a cape.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import action_registry

logger = logging.getLogger("chief")

MAX_STEPS = 12
# How many missions may be in flight (non-terminal) per business — a
# planner that queues 40 plans is noise wearing ambition.
MAX_OPEN_MISSIONS = 5

_FORBIDDEN_VERBS = {
    # No recursion — a plan may not plan.
    "propose_mission", "start_mission", "advance_mission",
    "abandon_mission", "mission_status",
    # Window dressing — meaningless as plan steps.
    "set_chat_window", "navigate", "close_view",
}

_TERMINAL = ("completed", "abandoned")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cos():
    import chief_of_staff
    return chief_of_staff


def _fail(atype: str, msg: str) -> Dict[str, Any]:
    return _cos()._fail(atype, msg)


def _step_gate(action: Dict[str, Any], explicit: bool) -> bool:
    """Does this step pause for the practitioner? Class-C always does —
    irreversibility is not a thing to be breezy about inside a plan that
    runs while they are not looking. A proposer can also flag any step."""
    verb = (action.get("type") or "").strip()
    if explicit:
        return True
    return action_registry.reversibility(verb) == "C"


def validate_steps(raw_steps: Any) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """Normalize the proposed steps; return (error, steps). Every verb
    must exist, be permitted, and carry its gate flag resolved here so
    the executor never re-decides policy mid-run."""
    if not isinstance(raw_steps, list) or not raw_steps:
        return "a mission needs at least one step", []
    if len(raw_steps) > MAX_STEPS:
        return f"missions cap at {MAX_STEPS} steps — split the plan", []
    cos = _cos()
    out: List[Dict[str, Any]] = []
    for i, s in enumerate(raw_steps):
        if not isinstance(s, dict):
            return f"step {i + 1} is not an object", []
        action = s.get("action")
        if not isinstance(action, dict) or not action.get("type"):
            return f"step {i + 1} has no action", []
        verb = str(action["type"]).strip()
        if verb in _FORBIDDEN_VERBS:
            return f"step {i + 1}: '{verb}' is not allowed inside a mission", []
        if verb not in cos.ACTION_HANDLERS:
            return f"step {i + 1}: unknown action '{verb}'", []
        eff = action_registry.effect(verb)
        if eff is None:
            # Fail closed — an unregistered verb has no classification
            # and therefore no place in a semi-autonomous plan.
            return f"step {i + 1}: '{verb}' is not classified — refused", []
        out.append({
            "id": f"step-{i + 1}",
            "title": (s.get("title") or verb.replace("_", " ")).strip()[:120],
            "action": action,
            "gate": _step_gate(action, bool(s.get("approval"))),
            "status": "pending",
            "result_label": "",
        })
    return None, out


async def _save(client, mission: Dict[str, Any]) -> bool:
    """Write the mission row back and VERIFY the write landed."""
    cos = _cos()
    mission["updated_at"] = _now()
    body = {k: mission[k] for k in
            ("status", "steps", "current_step", "report", "updated_at")}
    rows = await cos._sb(client, "PATCH",
                         f"/chief_missions?id=eq.{mission['id']}", body)
    if rows is None:
        logger.warning(f"[missions] save REFUSED for {mission['id']}")
        return False
    return True


def _progress(mission: Dict[str, Any]) -> str:
    steps = mission.get("steps") or []
    done = sum(1 for s in steps if s.get("status") == "done")
    return f"{done}/{len(steps)}"


def _speak(mission: Dict[str, Any]) -> str:
    steps = mission.get("steps") or []
    lines = []
    for s in steps:
        mark = {"done": "done", "failed": "FAILED", "awaiting": "WAITING ON YOU",
                "pending": "pending", "skipped": "skipped"}.get(s.get("status"), "?")
        lines.append(f"{s.get('title')}: {mark}"
                     + (f" ({s.get('result_label')})" if s.get("result_label") else ""))
    return "; ".join(lines[:12])


async def _run_until_gate(client, biz: Dict[str, Any],
                          mission: Dict[str, Any]) -> Dict[str, Any]:
    """Execute pending steps in order until a gate, a failure, or the
    end. Mutates + saves the mission; returns it."""
    cos = _cos()
    steps: List[Dict[str, Any]] = mission["steps"]
    i = mission.get("current_step") or 0
    while i < len(steps):
        step = steps[i]
        if step["status"] in ("done", "skipped"):
            i += 1
            continue
        if step["status"] == "pending" and step.get("gate"):
            step["status"] = "awaiting"
            mission["status"] = "awaiting_approval"
            mission["current_step"] = i
            await _save(client, mission)
            return mission
        # awaiting steps reach here only via advance (gate lifted).
        taken = await cos._execute_actions(
            client, biz, [dict(step["action"])],
            user_id=cos._TURN_USER_ID.get() or None)
        result = taken[0] if taken else None
        label = (result or {}).get("label") or (result or {}).get("result") or ""
        step["result_label"] = str(label)[:200]
        if result is None or cos._action_failed(result):
            step["status"] = "failed"
            mission["status"] = "paused"
            mission["current_step"] = i
            mission["report"] = (f"Paused at step {i + 1} ({step['title']}): "
                                 f"{step['result_label'] or 'the action failed'}")
            await _save(client, mission)
            return mission
        step["status"] = "done"
        i += 1
        mission["current_step"] = i
        # Save after every step: a deploy restart mid-mission must not
        # forget which sends already happened.
        await _save(client, mission)
    mission["status"] = "completed"
    mission["report"] = f"Completed: {_progress(mission)} steps done."
    await _save(client, mission)
    return mission


async def _load(client, biz_id: str, mission_id: Optional[str],
                statuses: Tuple[str, ...]) -> Optional[Dict[str, Any]]:
    cos = _cos()
    q = f"/chief_missions?business_id=eq.{biz_id}"
    if mission_id:
        q += f"&id=eq.{mission_id}"
    else:
        q += "&status=in.(" + ",".join(statuses) + ")"
    q += "&order=updated_at.desc&limit=1"
    rows = await cos._sb(client, "GET", q) or []
    return rows[0] if rows else None


# ─── Handlers ─────────────────────────────────────────────────────────

async def handle_propose_mission(client, biz, action) -> Dict[str, Any]:
    """Draft a plan. Executes NOTHING — the row is the proposal, and
    start_mission is the practitioner's yes."""
    cos = _cos()
    biz_id = biz["id"]
    title = (action.get("title") or "").strip()
    if not title:
        return _fail("propose_mission", "title is required")
    err, steps = validate_steps(action.get("steps"))
    if err:
        return _fail("propose_mission", err)

    open_rows = await cos._sb(
        client, "GET",
        f"/chief_missions?business_id=eq.{biz_id}"
        f"&status=in.(draft,active,awaiting_approval,paused)"
        f"&select=id&limit={MAX_OPEN_MISSIONS + 1}") or []
    if len(open_rows) > MAX_OPEN_MISSIONS - 1:
        return _fail("propose_mission",
                     f"{MAX_OPEN_MISSIONS} missions are already open — "
                     f"finish or abandon one first")

    row = {
        "business_id": biz_id,
        "title": title[:200],
        "goal": (action.get("goal") or "").strip()[:1000],
        "status": "draft",
        "steps": steps,
        "current_step": 0,
    }
    inserted = await cos._sb(client, "POST", "/chief_missions", row)
    if not inserted:
        return _fail("propose_mission", "the mission could not be saved")
    mission = inserted[0] if isinstance(inserted, list) else inserted
    gates = sum(1 for s in steps if s.get("gate"))
    return {
        "type": "propose_mission",
        "result": (f"drafted '{title}' with {len(steps)} steps"
                   + (f", {gates} needing your approval" if gates else "")
                   + " — say the word and I start"),
        "label": f"🎯 Mission drafted: {title} ({len(steps)} steps)",
        "mission_id": mission.get("id"),
        "title": title,
        "steps": [{"title": s["title"], "gate": s["gate"]} for s in steps],
        "speak": "; ".join(
            f"{i + 1}. {s['title']}" + (" [needs your OK]" if s["gate"] else "")
            for i, s in enumerate(steps)),
    }


async def handle_start_mission(client, biz, action) -> Dict[str, Any]:
    """The practitioner's yes. Runs the plan up to the first gate."""
    mission = await _load(client, biz["id"], action.get("mission_id"), ("draft",))
    if not mission:
        return _fail("start_mission", "no draft mission to start — propose one first")
    mission["status"] = "active"
    mission = await _run_until_gate(client, biz, mission)
    return _mission_state_payload("start_mission", mission)


async def handle_advance_mission(client, biz, action) -> Dict[str, Any]:
    """Lift the current gate and keep going. This verb is class-C, so
    the chat loop's own trust gate stands in front of it — the approval
    the paused step was waiting for IS this call."""
    mission = await _load(client, biz["id"], action.get("mission_id"),
                          ("awaiting_approval", "paused"))
    if not mission:
        return _fail("advance_mission", "no mission is waiting on you")
    steps = mission["steps"]
    i = mission.get("current_step") or 0
    if i < len(steps) and steps[i]["status"] in ("awaiting", "failed"):
        # Lifting the gate / retrying the failure both mean: run it now.
        steps[i]["status"] = "approved"
        steps[i]["gate"] = False
    mission["status"] = "active"
    mission = await _run_until_gate(client, biz, mission)
    return _mission_state_payload("advance_mission", mission)


async def handle_abandon_mission(client, biz, action) -> Dict[str, Any]:
    mission = await _load(client, biz["id"], action.get("mission_id"),
                          ("draft", "active", "awaiting_approval", "paused"))
    if not mission:
        return _fail("abandon_mission", "no open mission to abandon")
    mission["status"] = "abandoned"
    mission["report"] = f"Abandoned at {_progress(mission)}."
    if not await _save(client, mission):
        return _fail("abandon_mission", "could not save — the mission is still open")
    return {
        "type": "abandon_mission",
        "result": f"abandoned '{mission['title']}' at {_progress(mission)}",
        "label": f"🗑 Mission abandoned: {mission['title']}",
        "mission_id": mission["id"],
    }


async def handle_mission_status(client, biz, action) -> Dict[str, Any]:
    """Read: every non-terminal mission, with per-step truth."""
    cos = _cos()
    rows = await cos._sb(
        client, "GET",
        f"/chief_missions?business_id=eq.{biz['id']}"
        f"&status=in.(draft,active,awaiting_approval,paused)"
        f"&order=updated_at.desc&limit={MAX_OPEN_MISSIONS}")
    if rows is None:
        return _fail("mission_status", "couldn't load missions just now")
    if not rows:
        return {
            "type": "mission_status",
            "result": "no missions in flight",
            "label": "🎯 Missions: none open",
            "missions": [],
            "signal": {"open": 0, "awaiting": 0},
        }
    awaiting = sum(1 for m in rows if m.get("status") == "awaiting_approval")
    return {
        "type": "mission_status",
        "result": f"{len(rows)} open, {awaiting} waiting on the practitioner",
        "label": f"🎯 Missions: {len(rows)} open"
                 + (f" · {awaiting} waiting on you" if awaiting else ""),
        "missions": [{
            "id": m["id"], "title": m["title"], "status": m["status"],
            "progress": _progress(m),
            "steps": [{"title": s.get("title"), "status": s.get("status"),
                       "result_label": s.get("result_label")}
                      for s in (m.get("steps") or [])],
        } for m in rows],
        "speak": " | ".join(
            f"{m['title']} [{m['status']}] {_progress(m)}: {_speak(m)}"
            for m in rows)[:1500],
        "signal": {"open": len(rows), "awaiting": awaiting},
    }


def _mission_state_payload(atype: str, mission: Dict[str, Any]) -> Dict[str, Any]:
    status = mission["status"]
    steps = mission["steps"]
    i = mission.get("current_step") or 0
    if status == "completed":
        result = f"'{mission['title']}' completed — {_progress(mission)} steps done"
        label = f"🎯 Mission complete: {mission['title']}"
    elif status == "awaiting_approval":
        step = steps[i]
        result = (f"ran up to step {i + 1} and stopped for you: "
                  f"'{step['title']}' needs your OK — say \"go ahead\" to continue")
        label = f"⏸ Mission waiting on you: {step['title']}"
    elif status == "paused":
        result = mission.get("report") or "paused on a failed step"
        label = f"⚠️ Mission paused: {mission['title']}"
    else:
        result = f"'{mission['title']}' is {status} at {_progress(mission)}"
        label = f"🎯 Mission {status}: {mission['title']}"
    return {
        "type": atype,
        "result": result,
        "label": label,
        "mission_id": mission["id"],
        "status": status,
        "progress": _progress(mission),
        "steps": [{"title": s.get("title"), "status": s.get("status"),
                   "result_label": s.get("result_label")} for s in steps],
        "speak": _speak(mission),
    }
