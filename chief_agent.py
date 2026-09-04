"""
chief_agent.py — Chief wakes on events, not only on a message.

THE SHAPE (docs/extensibility_and_autonomy.md §2.2, first slice, 2026-09-04)
  A per-business agent that runs on a leader-gated tick, takes the
  events that arrived since it last looked, and — inside the SAME loop,
  the same tools and the same door a chat turn uses — does the
  reversible bookkeeping Chief would have done if asked, then leaves a
  recap where the practitioner sees it next time they open the app.

  A new booking arrives → the agent logs the activity on the contact,
  puts a note on the record, sets the task it would have offered, and
  tells the practitioner in one line. Anything that needs their hand — a
  send, a charge, a decision — it names in a notification. It does not
  do those things, and cannot: class C has no tool on this surface.

WHAT IS REUSED, DELIBERATELY
  chief_tool_loop — the read tools and the 55 reviewed write tools,
  run with surface="agent", prompted=False so the policy engine treats
  every write as unattended (a paused business pauses its agent; a
  regulated practice's client-facing switch holds; bulk is refused).
  _execute_actions — the door: reference resolution, the gate, the
  policy engine, the undo log, _authorized_by.
  events — the spine event_spine.emit() already writes. One new column,
  agent_handled_at, is the cursor. Stamped BEFORE the model call, so a
  crash loses one run and never double-handles a booking.
  chief_activity (source="system") — WhileYouWereAway renders it.
  audit_log + agent_runs — the ledger and the run record.

WHAT IT DELIBERATELY DOES NOT TOUCH
  sms_received and email_replied. notification_engine already alerts
  on those and unanswered_lead_sweep already chases them; an agent that
  proposed "reply to this lead" on top of the alert the practitioner is
  reading would be the double-handling the survey warned about. The
  event allow-list starts narrow and grows one type at a time.

OPT-IN, THREE SWITCHES
  CHIEF_AGENT=off (platform), settings.automations_paused (business,
  already honoured by the policy engine), settings.autonomy.agent_enabled
  (business; default OFF — nobody's Chief acts on its own until they
  turn it on). Plus spend_guard, the per-turn write budget, and a cap on
  businesses per tick.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("chief_agent")

router = APIRouter(prefix="/agents/chief/agent", tags=["chief-agent"])

# Events the agent may act on. Narrow on purpose; see the header.
AGENT_EVENT_TYPES = (
    "booking_created",
    "contact_form_submitted",
    "invoice_paid_auto",
    "payment_received",
    "contract_signed",
    "order_paid",
    "concierge_lead_captured",
)
# THE FAST LANE (2026-09-04). A lead is worth most in its first minutes
# — lead_response.py exists because first-response time decides whether
# an enquiry becomes a customer — and a booking confirmation that lands
# ten minutes after the booking reads as an afterthought. These event
# types wake the agent within a minute of arriving (event_spine.emit
# calls nudge()); everything else waits for the sweep, which itself
# runs every two minutes now. Payments and contracts are bookkeeping;
# nobody is waiting on the other end of them.
FAST_EVENT_TYPES = frozenset({
    "booking_created",
    "contact_form_submitted",
    "concierge_lead_captured",
})
NUDGE_DELAY_S = 20   # let the writer finish its own row (contact, session) first

# Events older than this are never picked up: an agent enabled today
# must not walk back through last month.
LOOKBACK_HOURS = 24
MAX_EVENTS_PER_RUN = 12
MAX_BUSINESSES_PER_TICK = 10


def enabled() -> bool:
    return (os.environ.get("CHIEF_AGENT") or "on").strip().lower() != "off"


def business_enabled(biz: Dict[str, Any]) -> bool:
    settings = (biz or {}).get("settings") if isinstance((biz or {}).get("settings"), dict) else {}
    autonomy = settings.get("autonomy") if isinstance(settings.get("autonomy"), dict) else {}
    return autonomy.get("agent_enabled") is True


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _z(dt: datetime) -> str:
    # '+00:00' reads as a space in a PostgREST query string.
    return dt.isoformat().replace("+00:00", "Z")


# ─── The tick ─────────────────────────────────────────────────────────

def unhandled_events() -> List[Dict[str, Any]]:
    since = _z(_now() - timedelta(hours=LOOKBACK_HOURS))
    types = ",".join(AGENT_EVENT_TYPES)
    try:
        rows = sb_clients.sb_get_as_service(
            f"/events?agent_handled_at=is.null&event_type=in.({types})"
            f"&created_at=gte.{since}&order=created_at.asc&limit=200"
            "&select=id,business_id,contact_id,event_type,data,source,created_at") or []
    except Exception as e:
        logger.warning(f"[agent] event fetch failed (column missing? apply "
                       f"APPLY-2026-09-04-events-agent-cursor.sql): {e}")
        return []
    return rows if isinstance(rows, list) else []


def group_by_business(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        bid = str(r.get("business_id") or "")
        if bid:
            out.setdefault(bid, []).append(r)
    return out


def stamp_handled(event_ids: List[str]) -> List[str]:
    """Idempotence. Stamped BEFORE anything is planned: a crash costs one
    run, never a second booking note.

    Returns the ids this call actually stamped. The PATCH only touches
    rows still unstamped, and PostgREST returns the rows it touched, so
    when a nudge on one replica and the sweep on another read the same
    unhandled row, exactly one of them gets it back here and the other
    gets an empty list — and acts on nothing."""
    if not event_ids:
        return []
    ids = ",".join(str(i) for i in event_ids)
    rows = sb_clients.sb_patch_as_service(
        f"/events?id=in.({ids})&agent_handled_at=is.null",
        {"agent_handled_at": _z(_now())})
    if isinstance(rows, list):
        return [str(r.get("id")) for r in rows if r.get("id")]
    return list(event_ids)   # a helper that returned nothing: assume ours, as before


def _business(business_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}"
        "&select=id,name,type,settings,owner_id,voice_profile,subscription_status,"
        "subscription_plan,comp_tier&limit=1") or []
    return rows[0] if rows else None


async def agent_tick() -> None:
    """Leader-gated, every 2 minutes — the sweep behind the fast lane."""
    if not enabled():
        return
    rows = await asyncio.to_thread(unhandled_events)
    if not rows:
        return
    by_biz = group_by_business(rows)
    for bid, events in list(by_biz.items())[:MAX_BUSINESSES_PER_TICK]:
        try:
            await handle_business(bid, events[:MAX_EVENTS_PER_RUN])
        except Exception as e:  # pragma: no cover
            logger.warning(f"[agent] business {bid[:8]} crashed: {e}")


async def handle_business(business_id: str, events: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """One business, one run. Returns the run record, or None when it
    did not run (and why is logged)."""
    biz = await asyncio.to_thread(_business, business_id)
    if not biz:
        return None
    ids = [str(e.get("id")) for e in events if e.get("id")]

    if not business_enabled(biz):
        # Not opted in: retire the events so the queue never grows, and
        # say nothing — this business's Chief acts only when asked.
        await asyncio.to_thread(stamp_handled, ids)
        return None

    import policy_engine
    if policy_engine.is_paused(biz):
        # Paused is temporary. Leave the events for the next tick; the
        # 24-hour window retires them if the pause outlives it.
        logger.info(f"[agent] {business_id[:8]} paused — leaving {len(ids)} event(s)")
        return None

    import spend_guard
    if spend_guard.over_budget(business_id):
        logger.info(f"[agent] {business_id[:8]} over budget — leaving events")
        return None

    stamped = await asyncio.to_thread(stamp_handled, ids)
    if stamped is None:   # a helper that says nothing (older contract, test doubles): assume ours
        stamped = ids
    mine = set(str(i) for i in stamped)
    events = [e for e in events if str(e.get("id")) in mine]
    if not events:
        return None   # another replica got there first
    return await run(biz, events)


# ─── The fast lane ──────────────────────────────────────────────────────

_pending_nudges: Dict[str, "asyncio.Task[None]"] = {}


def nudge(business_id: Optional[str], event_type: str) -> bool:
    """Called by event_spine.emit for every event. For a fast-lane type,
    schedule a run for that business in NUDGE_DELAY_S, debounced per
    business, on the running loop. Where there is no running loop (a
    worker thread, a script) this is a no-op and the sweep picks the
    event up within two minutes. Never raises. Returns whether a run
    was scheduled."""
    if not business_id or event_type not in FAST_EVENT_TYPES or not enabled():
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    bid = str(business_id)
    existing = _pending_nudges.get(bid)
    if existing and not existing.done():
        return False   # one already on its way; it will see this event too
    try:
        _pending_nudges[bid] = loop.create_task(_run_soon(bid))
        return True
    except Exception as e:  # pragma: no cover
        logger.warning(f"[agent] nudge for {bid[:8]} failed: {e}")
        return False


async def _run_soon(business_id: str) -> None:
    try:
        await asyncio.sleep(NUDGE_DELAY_S)
        rows = await asyncio.to_thread(unhandled_events)
        events = [r for r in rows if str(r.get("business_id")) == business_id]
        if events:
            await handle_business(business_id, events[:MAX_EVENTS_PER_RUN])
    except Exception as e:  # pragma: no cover
        logger.warning(f"[agent] fast-lane run for {business_id[:8]} failed: {e}")
    finally:
        _pending_nudges.pop(business_id, None)


# ─── One run ──────────────────────────────────────────────────────────

_SYSTEM = """You are Chief, the chief of staff for {name}{kind}. Nobody is talking to you right now: you are acting on your own, between conversations, because something happened in the business. The practitioner will read what you did the next time they open the app.

WHAT YOU MAY DO
- Use the lookup tools to understand the situation (the contact, their history, what is on the calendar).
- Use the tools that act to do the reversible bookkeeping you would have done if asked: log the activity on the contact, put a note on their record, create the task you would have offered, keep their status current, put the session on the calendar if it is not there, remember what matters.
- If something needs the practitioner's hand — a message to a client, a charge, a decision — call notify_practitioner with a one-line title that says what and why. Do NOT try to do it yourself; you have no tool for it on purpose.
- Do the minimum that is genuinely useful. Three good actions beat six busy ones. If an event needs nothing, do nothing and say so.

WHAT YOU MUST NOT DO
- Never claim to have sent, charged, published or booked anything for a client. You cannot, and saying so would be a lie the practitioner acts on.
- Never write anything that contradicts the practitioner's own records. Look first.

YOUR REPLY is the recap they will read: two or three short sentences, second person ("You have a new booking from…; I logged it and…"), naming what happened and what you did. No markdown, no headers, no [ACTION:] tags — tags do nothing here, tools are the only way to act.
"""


def _event_lines(events: List[Dict[str, Any]]) -> str:
    lines = []
    for e in events:
        data = e.get("data") if isinstance(e.get("data"), dict) else {}
        # The event's own fields, compact. Third-party text (a form
        # answer, a note) is neutralised by the tool loop's defuser on
        # any lookup; here it is the model's INPUT, so it is defused too.
        try:
            import untrusted_text
            blob = untrusted_text.defuse(json.dumps(data, default=str)[:600])
        except Exception:
            blob = json.dumps(data, default=str)[:600]
        when = str(e.get("created_at") or "")[:16].replace("T", " ")
        cid = f" contact_id={e.get('contact_id')}" if e.get("contact_id") else ""
        lines.append(f"- {when} {e.get('event_type')}{cid}: {blob}")
    return "\n".join(lines)


async def run(biz: Dict[str, Any], events: List[Dict[str, Any]]) -> Dict[str, Any]:
    import billing_context
    import chief_models
    import chief_of_staff as cos
    import chief_tool_loop as ctl

    business_id = str(biz["id"])
    kind = f", a {biz.get('type')} business" if biz.get("type") else ""
    system = _SYSTEM.format(name=biz.get("name") or "this business", kind=kind)
    user = ("New since you last looked:\n" + _event_lines(events)
            + "\n\nLook, act where it helps, then write the recap.")
    # _event_lines ran the defuser; its taint (if any) belongs to this
    # run and is read by the gate. It is reset at the top of the NEXT run.

    try:
        import feature_gates
        plan = feature_gates.plan_of(biz)
    except Exception:
        plan = None

    # Every run starts clean. The taint counter is a contextvar on the
    # tick's task; without this, a suspicious form answer in business
    # A's events would still be "tainting" business B's run a moment
    # later. Within ONE run the taint from _event_lines is kept on
    # purpose — it is about exactly this input.
    try:
        cos._UNTRUSTED_TAINT.set(0)
    except Exception:
        pass
    ctl.reset_turn(writes_allowed=True, surface="agent", prompted=False)
    tools = ctl.tool_definitions_for_turn(True)
    started = _now()
    async with httpx.AsyncClient() as client:
        with billing_context.bill_to(business_id):
            raw = await cos._call_claude(
                client, system, [{"role": "user", "content": user}],
                max_tokens=chief_models.max_tokens_for("chat", default=900),
                enable_web_search=False, business_id=business_id,
                model=chief_models.model_for("chat", plan),
                read_tools=tools, tool_biz=biz)
        taken = ctl.writes_this_turn()
        # Tags do nothing on this surface. If the model emitted any, they
        # are stripped from the recap and COUNTED, never executed — the
        # count is the signal that the prompt above is not landing.
        tag_actions, recap = cos._extract_actions_and_clean(raw or "")
        recap = (recap or "").strip() or "I looked at what came in and nothing needed doing."
        if tag_actions:
            logger.warning(f"[agent] {business_id[:8]} emitted {len(tag_actions)} "
                           f"[ACTION:] tag(s) on the agent surface — ignored")

        record = {
            "business_id": business_id,
            "events": [str(e.get("event_type")) for e in events],
            "actions": [str(t.get("type")) for t in taken if isinstance(t, dict)],
            "failed": [str(t.get("type")) for t in taken
                       if isinstance(t, dict) and cos._action_failed(t)],
            "recap": recap[:600],
            "tags_ignored": len(tag_actions),
            "duration_ms": int((_now() - started).total_seconds() * 1000),
        }
        await _leave_trace(client, biz, taken, record)
    return record


async def _leave_trace(client, biz: Dict[str, Any], taken: List[Dict[str, Any]],
                       record: Dict[str, Any]) -> None:
    """The recap where they will see it, plus the ledger. Best-effort,
    each piece independently — a failed row must not hide the others."""
    import chief_of_staff as cos
    business_id = record["business_id"]
    owner = biz.get("owner_id")

    # 1. What it did, one activity row per action — the same writer a
    #    chat turn uses, tagged system so WhileYouWereAway shows it.
    try:
        await cos._log_chief_activity(client, user_id=owner, business_id=business_id,
                                      source="system", taken=taken)
    except Exception as e:
        logger.warning(f"[agent] activity rows failed: {e}")

    # 2. The recap itself, as one row the rail leads with.
    try:
        await cos._sb(client, "POST", "/chief_activity", [{
            "user_id": owner, "business_id": business_id, "source": "system",
            "action_type": "agent_run",
            "label": f"While you were away — {len(record['events'])} thing(s) came in",
            "summary": record["recap"][:240], "nav": None,
        }])
    except Exception as e:
        logger.warning(f"[agent] recap row failed: {e}")

    # 3. The ledger: one row for the run, pre-action reasoning in the
    #    payload as the recap (the model writes it after acting, but it
    #    is the only account of WHY, and it is on record).
    try:
        import audit_log
        await asyncio.to_thread(
            audit_log.record, business_id, actor_type="chief", actor_id="agent",
            verb="agent_run", ok=not record["failed"],
            error=(", ".join(record["failed"])[:500] or None),
            summary=record["recap"][:240],
            payload={"events": record["events"], "actions": record["actions"],
                     "tags_ignored": record["tags_ignored"]},
            source="agent", authorized_by="agent:unattended")
    except Exception as e:
        logger.warning(f"[agent] ledger row failed: {e}")

    # 4. The run record, in the table built for agent runs.
    try:
        await asyncio.to_thread(sb_clients.sb_post_as_service, "/agent_runs", {
            "business_id": business_id, "surface": "agent", "tool": "agent_run",
            "actor_email": "chief:agent", "allowed": True, "ok": not record["failed"],
            "duration_ms": record["duration_ms"],
            "error": (", ".join(record["failed"])[:300] or None),
            "arg_keys": sorted(set(record["events"])),
            "detail": {"actions": record["actions"], "tags_ignored": record["tags_ignored"]},
        }, prefer="return=minimal")
    except Exception as e:
        logger.warning(f"[agent] agent_runs row failed: {e}")


# ─── The switch ───────────────────────────────────────────────────────

class _EnableBody(BaseModel):
    business_id: str
    enabled: bool


def _require_owner(business_id: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,owner_id,settings&limit=1") or []
    if not rows:
        raise HTTPException(status_code=404, detail="business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized for this business")
    return rows[0]


@router.get("")
def agent_status(business_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz = _require_owner(business_id, user)
    return {"ok": True, "enabled": business_enabled(biz), "platform_enabled": enabled(),
            "events": list(AGENT_EVENT_TYPES)}


@router.post("/enable")
def agent_enable(body: _EnableBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """The per-business switch. Owner only. Writes settings.autonomy.
    agent_enabled and nothing else in settings — the merge is shallow on
    purpose so a stale client cannot clobber a neighbouring key."""
    biz = _require_owner(body.business_id, user)
    settings = biz.get("settings") if isinstance(biz.get("settings"), dict) else {}
    autonomy = dict(settings.get("autonomy") or {}) if isinstance(settings.get("autonomy"), dict) else {}
    autonomy["agent_enabled"] = bool(body.enabled)
    autonomy["agent_enabled_at" if body.enabled else "agent_disabled_at"] = _z(_now())
    sb_clients.sb_patch_as_service(
        f"/businesses?id=eq.{body.business_id}",
        {"settings": {**settings, "autonomy": autonomy}})
    try:
        import audit_log
        audit_log.record(body.business_id, actor_type="user", actor_id=str(user.id),
                         verb="agent_enable" if body.enabled else "agent_disable",
                         ok=True, source="settings",
                         summary="Chief may act on its own between conversations"
                         if body.enabled else "Chief acts only when asked")
    except Exception:
        pass
    return {"ok": True, "enabled": bool(body.enabled)}
