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
  * A step USES WHAT THE EARLIER STEPS FOUND. Every completed step
    persists a trimmed `result_ref` into the row, and later steps
    resolve "@show_view.rows" against them through
    chief_of_staff's own resolver — the same syntax a same-turn chain
    uses, one implementation, no drift. Persisted rather than held in
    memory because a plan that pauses overnight must resume knowing
    what it learned yesterday.
  * A step may REPEAT OVER a list an earlier step returned:
    "for_each": "@show_view.rows" runs the step once per row,
    with {{item.contact_id}} filled in from that row. This is what
    turns "get my unpaid invoices collected" from a plan Chief could
    describe into one it can run — the proposer no longer has to know
    every contact id before the practitioner has said yes.
    Fan-out is deliberately narrow: class A only (cleanly undoable),
    never a bulk verb, capped at FANOUT_MAX, refused AT PROPOSAL TIME.
    A batch of sends stays what it already was — one bulk verb behind
    its own gate (bulk_approve), reviewed as one decision. Multiplying
    an irreversible step by data the practitioner has not seen is
    exactly the thing this engine must not invent.
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
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import action_registry

logger = logging.getLogger("chief")

MAX_STEPS = 12
# How many rows one for_each step may repeat over. A plan that quietly
# becomes 400 actions is not a plan, and the practitioner approved a
# STEP LIST — the size of what each step turns into has to stay legible.
FANOUT_MAX = 25
# Ceiling on one step's persisted result_ref. The row must stay small
# enough to ride _gather_context into every turn.
MAX_REF_CHARS = 20000
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


# ─── References: what a step may know about the steps before it ──────

_ITEM_RE = re.compile(r"\{\{item(?:\.([A-Za-z0-9_]+))?\}\}")


def _referenceable(result: Any) -> Dict[str, Any]:
    """The part of a step's result that LATER steps may reference.

    Persisted into the mission row, so a plan that pauses overnight can
    still resolve "@show_view.rows" when it resumes days later.
    Deliberately small: ids, counts, and the row lists a for_each
    iterates — never the whole handler payload, which carries rendered
    UI and can be enormous.
    """
    if not isinstance(result, dict):
        return {}
    out: Dict[str, Any] = {}
    for k, v in result.items():
        if k in ("frontend_event", "nav", "toast", "speak", "proposals"):
            continue
        if v is None or isinstance(v, (int, float, bool)):
            out[k] = v
        elif isinstance(v, str):
            if len(v) <= 300:
                out[k] = v
        elif isinstance(v, list):
            # One PAST the cap on purpose: _expand_step has to be able to
            # SEE that a list is too long. Trimming to exactly FANOUT_MAX
            # here would turn "26 overdue invoices" into 25 silent drafts
            # and a mission that reported success.
            rows: List[Any] = []
            for item in v[:FANOUT_MAX + 1]:
                if isinstance(item, dict):
                    rows.append({ik: iv for ik, iv in item.items()
                                 if isinstance(iv, (int, float, bool))
                                 or (isinstance(iv, str) and len(iv) <= 300)})
                elif isinstance(item, (str, int, float, bool)):
                    rows.append(item)
            out[k] = rows
    nav = result.get("nav")
    if isinstance(nav, dict):
        # _resolve_action_references falls back to nav.* — older handlers
        # stash ids there, so a reference to one must still resolve.
        out["nav"] = {k: v for k, v in nav.items()
                      if isinstance(v, (str, int, float, bool))}
    # Last guard: a result_ref that would bloat the row loses its lists
    # rather than the ids, which are the part a later step needs most.
    try:
        if len(json.dumps(out, default=str)) > MAX_REF_CHARS:
            out = {k: v for k, v in out.items() if not isinstance(v, list)}
            out["_trimmed"] = True
    except (TypeError, ValueError):
        out = {"type": result.get("type")}
    return out


def _prior_results(steps: List[Dict[str, Any]], upto: int) -> List[Dict[str, Any]]:
    """What the steps before `upto` returned, oldest first — read off the
    PERSISTED row, not from memory, so a resumed mission still knows what
    it found before it paused."""
    out: List[Dict[str, Any]] = []
    for s in steps[:upto]:
        ref = s.get("result_ref")
        if isinstance(ref, dict) and ref:
            out.append(ref)
    return out


def _resolve_ref(ref: str, prior: List[Dict[str, Any]]) -> Any:
    """Resolve one "@type.field" through chief_of_staff's OWN resolver.

    One implementation of the reference syntax: a mission step and a
    same-turn action chain can never disagree about what
    "@create_invoice.invoice_id" means. An unresolved reference comes
    back as the reference string itself — the caller checks for that.
    """
    probe = _cos()._resolve_action_references(
        {"type": "_mission_ref_probe", "value": ref}, prior)
    return probe.get("value")


def _fill_template(node: Any, item: Any) -> Any:
    """Substitute {{item}} / {{item.field}} through an action template.

    A placeholder that IS the whole string yields the raw value, so a
    number stays a number and a missing field stays None (which the
    handler's own validation then reports) rather than the text "None".
    """
    if isinstance(node, dict):
        return {k: _fill_template(v, item) for k, v in node.items()}
    if isinstance(node, list):
        return [_fill_template(v, item) for v in node]
    if not isinstance(node, str):
        return node
    whole = _ITEM_RE.fullmatch(node.strip())
    if whole:
        field = whole.group(1)
        if field is None:
            return item
        return item.get(field) if isinstance(item, dict) else None

    def _sub(m):
        field = m.group(1)
        v = item if field is None else (
            item.get(field) if isinstance(item, dict) else None)
        return "" if v is None else str(v)

    return _ITEM_RE.sub(_sub, node)


def _expand_step(step: Dict[str, Any],
                 prior: List[Dict[str, Any]]) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """(error, actions) for one step: one action normally, N for a
    for_each step. An empty list is NOT an error — it is zero actions,
    which the caller reports as zero work rather than as work done."""
    ref = step.get("for_each")
    if not ref:
        return None, [dict(step["action"])]
    rows = _resolve_ref(str(ref), prior)
    if rows is None or rows == ref:
        return (f"couldn't read {ref} — the earlier step didn't return it"), []
    if not isinstance(rows, list):
        return (f"{ref} isn't a list, so there's nothing to repeat over"), []
    if len(rows) > FANOUT_MAX:
        # "more than" rather than a count: the stored list is capped just
        # past FANOUT_MAX, so the exact number is not knowable here — and
        # a made-up count would be worse than an honest bound.
        return (f"{ref} has more than {FANOUT_MAX} rows, and one step repeats "
                f"at most {FANOUT_MAX} times — narrow the step that produced "
                f"it (a tighter filter) or split the plan"), []
    return None, [_fill_template(step["action"], row) for row in rows]


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

        # A repeated step is Chief multiplying one action by data the
        # practitioner has not seen yet. That is only safe while each
        # repetition is cleanly undoable, so the class is checked HERE,
        # at proposal time, and a plan that wants a batch of sends is
        # refused before a row exists rather than caught mid-run.
        for_each = s.get("for_each")
        if for_each is not None:
            if (not isinstance(for_each, str) or not for_each.startswith("@")
                    or "." not in for_each):
                return (f"step {i + 1}: for_each must point at an earlier step's "
                        f"list, like '@show_view.rows'"), []
            entry = action_registry.classification(verb) or {}
            if entry.get("bulk"):
                return (f"step {i + 1}: '{verb}' already acts on a whole set — "
                        f"repeating it is not what you want"), []
            if eff == action_registry.WRITE and entry.get("reversibility") != "A":
                return (f"step {i + 1}: '{verb}' is class "
                        f"{entry.get('reversibility')}, and a repeated step has to "
                        f"be cleanly undoable. Send a batch with a bulk verb so the "
                        f"practitioner approves it as one decision"), []

        out.append({
            "id": f"step-{i + 1}",
            "title": (s.get("title") or verb.replace("_", " ")).strip()[:120],
            "action": action,
            "for_each": for_each,
            "gate": _step_gate(action, bool(s.get("approval"))),
            "status": "pending",
            "result_label": "",
            "result_ref": None,
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


async def _pause_failed(client, mission: Dict[str, Any], step: Dict[str, Any],
                        i: int, detail: str) -> Dict[str, Any]:
    """Stop the plan and SAY WHY. Never a silent skip, never a claimed
    completion — the report names the step and what went wrong."""
    step["status"] = "failed"
    step["result_label"] = str(detail)[:200]
    mission["status"] = "paused"
    mission["current_step"] = i
    mission["report"] = (f"Paused at step {i + 1} ({step['title']}): "
                         f"{step['result_label'] or 'the action failed'}")
    await _save(client, mission)
    return mission


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

        # What the earlier steps found, off the persisted row — so a
        # mission resumed days later still resolves its own references.
        prior = _prior_results(steps, i)
        err, actions = _expand_step(step, prior)
        if err:
            return await _pause_failed(client, mission, step, i, err)

        if not actions:
            # A for_each over an empty list. Nothing to do is not a
            # failure — but it is never reported as work done either.
            step["status"] = "done"
            step["result_label"] = "nothing matched — 0 items"
            step["result_ref"] = {"type": step["action"].get("type"),
                                  "count": 0, "results": []}
            i += 1
            mission["current_step"] = i
            await _save(client, mission)
            continue

        taken = await cos._execute_actions(
            client, biz, actions,
            user_id=cos._TURN_USER_ID.get() or None,
            prior_results=prior)
        results = [r for r in (taken or []) if isinstance(r, dict)]
        failed = [r for r in results if cos._action_failed(r)]
        # A handler that returned nothing at all is a failure too — the
        # count has to match what we dispatched.
        dropped = len(actions) - len(results)
        fanned = bool(step.get("for_each"))

        if fanned:
            ok = [r for r in results if not cos._action_failed(r)]
            step["result_label"] = f"{len(ok)} of {len(actions)} done"
            step["result_ref"] = {
                "type": step["action"].get("type"),
                "count": len(ok),
                # Referenceable in turn: a later step can repeat over
                # what this one produced.
                "results": [_referenceable(r) for r in ok],
            }
        else:
            first = results[0] if results else None
            label = (first or {}).get("label") or (first or {}).get("result") or ""
            step["result_label"] = str(label)[:200]
            step["result_ref"] = _referenceable(first)

        if failed or dropped:
            detail = (f"{len(failed) + dropped} of {len(actions)} failed"
                      if fanned else
                      (step["result_label"] or "the action failed"))
            return await _pause_failed(client, mission, step, i, detail)

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
