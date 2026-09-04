"""
chief_assignments.py — Chief works an OUTCOME over days, not a message.

THE SHAPE (the "Chief to Eight" plan, phase one, 2026-09-04)
  "Fill Thursday." Said once, in chat. From then on the standing agent
  owns it: on a cadence, and whenever an event touches the business,
  it measures progress with a plain database read — no model call —
  and only THINKS when something changed or enough time has passed.
  When it thinks, it writes its reasoning BEFORE it acts (the autonomy
  spec's §2.2 rule, which chief_agent's event runs do not yet honour),
  then takes the next reversible step through the same tools and the
  same door a chat turn uses, files anything irreversible as a
  proposal, and leaves a one-line recap. It closes the assignment when
  the target is met, or at the deadline with a plain account.

  A mission (chief_missions) is a fixed list of steps the practitioner
  approved. An assignment has no list: it has a TARGET the code can
  measure, a DEADLINE, and a log of the moves Chief made toward it.
  The two are deliberately separate tables and separate verbs; a plan
  and a standing objective are different promises.

CHECK CHEAPLY, THINK RARELY — the cost rule
  A think is a model turn, about the cost of a chat turn. An assignment
  that thought every two minutes would cost more than the plan it runs
  on. So: progress is a query every CHECK_EVERY_MIN; the model is
  called at most every THINK_EVERY_HOURS in waking hours, at most
  MAX_THINKS_PER_DAY a day, and immediately when progress moved. Open
  assignments are capped per plan (feature_gates: 1 / 3 / 10).

WHAT IS REUSED, DELIBERATELY
  chief_tool_loop with surface="assignment", prompted=False — the
  reads, the reviewed class-A writes, and the propose_* tools. The
  policy engine sees an unattended surface; class C has no tool here.
  chief_agent.business_enabled — the SAME switch. Nobody's Chief works
  an assignment on its own unless the standing agent is on.
  chief_activity (source="system"), audit_log, agent_runs — the trace,
  in the same three places the event runs leave theirs.

STORAGE
  public.chief_assignments — service-role only (RLS on, no policies).
  Every write here goes through sb_clients.sb_*_as_service after the
  caller has checked the business and the actor; the chat handlers run
  inside a turn whose business was already resolved for the signed-in
  practitioner, and the HTTP door checks the owner itself.
  Fail-soft without the table: the tick logs the migration file name
  and does nothing; the chat verb says the feature is not set up yet.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("chief_assignments")

router = APIRouter(prefix="/agents/chief/assignments", tags=["chief-assignments"])

TABLE = "/chief_assignments"
MIGRATION = "APPLY-2026-09-04-chief-assignments.sql"
SURFACE = "assignment"

# What the code can measure without a model. Everything else is
# "manual": it closes at the deadline or on the practitioner's word.
TARGET_KINDS = (
    "sessions_scheduled",   # sessions on the calendar in [from, to]
    "sessions_completed",   # sessions marked completed in [from, to]
    "new_contacts",         # contacts created in [from, to]
    "revenue_collected",    # invoices paid in [from, to], summed
    "invoice_paid",         # one invoice, paid or not
    "manual",
)
_RANGE_KINDS = ("sessions_scheduled", "sessions_completed", "new_contacts", "revenue_collected")
_COUNT_KINDS = ("sessions_scheduled", "sessions_completed", "new_contacts")

OPEN_STATUSES = ("active",)
TERMINAL_STATUSES = ("completed", "expired", "stopped")

CHECK_EVERY_MIN = 30
THINK_EVERY_HOURS = 4
MAX_THINKS_PER_DAY = 6
MAX_PER_TICK = 25
MAX_MOVES_KEPT = 40
MAX_DAYS_OUT = 90
HARD_CAP_OPEN = 10
DEFAULT_OPEN_CAP = 3      # billing enforcement off, or no plan on record


def enabled() -> bool:
    return (os.environ.get("CHIEF_ASSIGNMENTS") or "on").strip().lower() != "off"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(s: Any) -> Optional[datetime]:
    if not isinstance(s, str) or not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_date(s: Any) -> Optional[date]:
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    if not isinstance(s, str) or not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


# ─── The business's clock ────────────────────────────────────────────

def _tz_for(business_id: str):
    """The business's own timezone (set_business_timezone stores it in
    the availability settings). UTC when unset or unreadable — a day
    boundary off by a few hours is a smaller wrong than a crash."""
    try:
        from zoneinfo import ZoneInfo
        import chief_offering_actions
        name = (chief_offering_actions._load_availability_settings(business_id) or {}).get("timezone")
        if name:
            return ZoneInfo(str(name))
    except Exception:
        pass
    return timezone.utc


def day_bounds(d_from: date, d_to: date, tz) -> Tuple[datetime, datetime]:
    """[start of d_from, end of d_to] in the business's day, as UTC."""
    start = datetime.combine(d_from, datetime.min.time(), tzinfo=tz)
    end = datetime.combine(d_to, datetime.max.time().replace(microsecond=0), tzinfo=tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


# ─── Targets ─────────────────────────────────────────────────────────

def normalize_target(raw: Any, *, today: Optional[date] = None) -> Tuple[Optional[str], Dict[str, Any]]:
    """(error, target). Fails closed: an unknown kind, a bad date, a
    non-positive number — refused at creation, never discovered on a
    tick three days later."""
    today = today or _now().date()
    if not isinstance(raw, dict):
        return "target must be an object with a kind", {}
    kind = str(raw.get("kind") or "").strip()
    if kind not in TARGET_KINDS:
        return f"unknown target kind {kind!r}; one of {', '.join(TARGET_KINDS)}", {}
    out: Dict[str, Any] = {"kind": kind}
    if kind in _RANGE_KINDS:
        d_from = _parse_date(raw.get("from")) or today
        d_to = _parse_date(raw.get("to")) or d_from
        if d_to < d_from:
            return "target 'to' is before 'from'", {}
        if (d_to - today).days > MAX_DAYS_OUT:
            return f"a target more than {MAX_DAYS_OUT} days out is a plan, not an assignment", {}
        out["from"], out["to"] = d_from.isoformat(), d_to.isoformat()
        if kind in _COUNT_KINDS:
            try:
                n = int(raw.get("count") or 0)
            except (TypeError, ValueError):
                n = 0
            if n <= 0:
                return "target needs a count above zero", {}
            out["count"] = n
        else:
            try:
                amt = float(raw.get("amount") or 0)
            except (TypeError, ValueError):
                amt = 0.0
            if amt <= 0:
                return "target needs an amount above zero", {}
            out["amount"] = round(amt, 2)
    elif kind == "invoice_paid":
        iid = str(raw.get("invoice_id") or "").strip()
        if not iid:
            return "invoice_paid needs invoice_id", {}
        out["invoice_id"] = iid
    return None, out


def default_deadline(target: Dict[str, Any], tz, *, today: Optional[date] = None) -> datetime:
    """End of the target's last day; a week out for the kinds with no
    day of their own."""
    today = today or _now().date()
    d_to = _parse_date(target.get("to"))
    if d_to:
        return day_bounds(d_to, d_to, tz)[1]
    return day_bounds(today + timedelta(days=7), today + timedelta(days=7), tz)[1]


def describe_target(target: Dict[str, Any]) -> str:
    kind = target.get("kind")
    span = ""
    if target.get("from"):
        span = (f" on {target['from']}" if target.get("to") in (None, target["from"])
                else f" between {target['from']} and {target['to']}")
    if kind == "sessions_scheduled":
        return f"{target.get('count')} session(s) on the calendar{span}"
    if kind == "sessions_completed":
        return f"{target.get('count')} session(s) completed{span}"
    if kind == "new_contacts":
        return f"{target.get('count')} new contact(s){span}"
    if kind == "revenue_collected":
        return f"${target.get('amount'):,.2f} collected{span}"
    if kind == "invoice_paid":
        return f"invoice {target.get('invoice_id')} paid"
    return "done when you say so"


def measure(business_id: str, target: Dict[str, Any], *, tz=None) -> Dict[str, Any]:
    """Progress from a plain read. Sync (service role); the tick wraps
    it in a thread. Never a model call, never a write.

    {"value", "target", "met", "label", "checked_at"} — value is None
    for a manual target, which is never met by measurement."""
    kind = target.get("kind")
    checked = _z(_now())
    bid = business_id
    if kind == "manual":
        return {"value": None, "target": None, "met": False,
                "label": "done when you say so", "checked_at": checked}
    if kind == "invoice_paid":
        rows = sb_clients.sb_get_as_service(
            f"/invoices?id=eq.{target.get('invoice_id')}&business_id=eq.{bid}"
            "&select=status,paid_at&limit=1") or []
        paid = bool(rows) and (rows[0].get("status") == "paid" or rows[0].get("paid_at"))
        return {"value": 1 if paid else 0, "target": 1, "met": paid,
                "label": "paid" if paid else "not paid yet", "checked_at": checked}

    tz = tz or _tz_for(bid)
    d_from = _parse_date(target.get("from")) or _now().date()
    d_to = _parse_date(target.get("to")) or d_from
    start, end = day_bounds(d_from, d_to, tz)
    lo, hi = _z(start), _z(end)
    if kind in ("sessions_scheduled", "sessions_completed"):
        rows = sb_clients.sb_get_as_service(
            f"/sessions?business_id=eq.{bid}&scheduled_for=gte.{lo}&scheduled_for=lte.{hi}"
            "&select=status&limit=1000") or []
        if kind == "sessions_completed":
            value = sum(1 for r in rows if r.get("status") == "completed")
            noun = "completed"
        else:
            value = sum(1 for r in rows if (r.get("status") or "scheduled") not in ("cancelled", "canceled", "no_show"))
            noun = "on the calendar"
        goal = int(target.get("count") or 0)
        return {"value": value, "target": goal, "met": value >= goal,
                "label": f"{value} of {goal} sessions {noun}", "checked_at": checked}
    if kind == "new_contacts":
        rows = sb_clients.sb_get_as_service(
            f"/contacts?business_id=eq.{bid}&created_at=gte.{lo}&created_at=lte.{hi}"
            "&select=id&limit=1000") or []
        value, goal = len(rows), int(target.get("count") or 0)
        return {"value": value, "target": goal, "met": value >= goal,
                "label": f"{value} of {goal} new contacts", "checked_at": checked}
    if kind == "revenue_collected":
        rows = sb_clients.sb_get_as_service(
            f"/invoices?business_id=eq.{bid}&status=eq.paid&paid_at=gte.{lo}&paid_at=lte.{hi}"
            "&select=total&limit=1000") or []
        value = 0.0
        for r in rows:
            try:
                value += float(r.get("total") or 0)
            except (TypeError, ValueError):
                pass
        goal = float(target.get("amount") or 0)
        return {"value": round(value, 2), "target": goal, "met": value >= goal,
                "label": f"${value:,.2f} of ${goal:,.2f} collected", "checked_at": checked}
    return {"value": None, "target": None, "met": False,
            "label": "unmeasurable", "checked_at": checked}


# ─── Rows ────────────────────────────────────────────────────────────

_SELECT = ("select=id,business_id,title,ask,target,deadline,status,progress,moves,report,"
           "origin,last_worked_at,next_check_at,thinks_day,thinks_today,created_at,updated_at")


def _table_missing(e: Exception) -> bool:
    return "chief_assignments" in str(e) or "42P01" in str(e) or "PGRST" in str(e)


def open_rows(business_id: str, limit: int = HARD_CAP_OPEN + 1) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"{TABLE}?business_id=eq.{business_id}&status=in.({','.join(OPEN_STATUSES)})"
        f"&order=created_at.asc&limit={limit}&{_SELECT}")
    return rows if isinstance(rows, list) else []


def recent_rows(business_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"{TABLE}?business_id=eq.{business_id}&order=updated_at.desc&limit={limit}&{_SELECT}")
    return rows if isinstance(rows, list) else []


def due_rows(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    now = now or _now()
    try:
        rows = sb_clients.sb_get_as_service(
            f"{TABLE}?status=eq.active&or=(next_check_at.is.null,next_check_at.lte.{_z(now)})"
            f"&order=next_check_at.asc.nullsfirst&limit={MAX_PER_TICK}&{_SELECT}")
    except Exception as e:
        logger.warning(f"[assignments] fetch failed (table missing? apply {MIGRATION}): {e}")
        return []
    return rows if isinstance(rows, list) else []


def save(row_id: str, patch: Dict[str, Any]) -> bool:
    patch = {**patch, "updated_at": _z(_now())}
    res = sb_clients.sb_patch_as_service(f"{TABLE}?id=eq.{row_id}", patch)
    return res is not None


def open_cap(biz: Dict[str, Any]) -> int:
    """How many assignments this business may have open at once. From
    the plan when billing is enforced; a sensible default otherwise."""
    try:
        import feature_gates
        if not feature_gates.enforcement_on():
            return DEFAULT_OPEN_CAP
        lim = feature_gates.limit_for(biz, "open_assignments")
        return min(int(lim), HARD_CAP_OPEN) if lim else HARD_CAP_OPEN
    except Exception:
        return DEFAULT_OPEN_CAP


def create(biz: Dict[str, Any], *, title: str, ask: str, target: Dict[str, Any],
           deadline: Optional[datetime], origin: str, created_by: Optional[str]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Validate, cap, insert. (error, row)."""
    bid = str(biz.get("id") or "")
    title = (title or "").strip()[:160]
    if not title:
        return "an assignment needs a title — the outcome in a few words", None
    err, target = normalize_target(target)
    if err:
        return err, None
    tz = _tz_for(bid)
    now = _now()
    if deadline is None:
        deadline = default_deadline(target, tz)
    if deadline <= now:
        return "the deadline is already past", None
    if (deadline - now).days > MAX_DAYS_OUT:
        return f"a deadline more than {MAX_DAYS_OUT} days out is a plan, not an assignment", None
    cap = open_cap(biz)
    try:
        already = open_rows(bid)
    except Exception as e:
        logger.warning(f"[assignments] open_rows failed: {e}")
        return "assignments are not set up on this server yet", None
    if len(already) >= cap:
        return (f"{cap} assignment{'s are' if cap != 1 else ' is'} already open on this plan — "
                f"finish or stop one first"), None
    for r in already:
        if (r.get("title") or "").strip().lower() == title.lower():
            return f"'{title}' is already open", None
    row = {
        "business_id": bid,
        "title": title,
        "ask": (ask or "").strip()[:1000],
        "target": target,
        "deadline": _z(deadline),
        "status": "active",
        "progress": None,
        "moves": [],
        "report": "",
        "origin": origin if origin in ("chat", "app", "agent") else "chat",
        "created_by": created_by,
        "next_check_at": _z(now),     # first look on the next tick
    }
    res = sb_clients.sb_post_as_service(TABLE, row)
    inserted = res[0] if isinstance(res, list) and res else (res if isinstance(res, dict) else None)
    if not inserted or not inserted.get("id"):
        return "the assignment could not be saved", None
    return None, inserted


def public_row(row: Dict[str, Any]) -> Dict[str, Any]:
    moves = row.get("moves") if isinstance(row.get("moves"), list) else []
    return {
        "id": row.get("id"), "title": row.get("title"), "ask": row.get("ask"),
        "target": row.get("target"), "target_label": describe_target(row.get("target") or {}),
        "deadline": row.get("deadline"), "status": row.get("status"),
        "progress": row.get("progress"), "report": row.get("report"),
        "origin": row.get("origin"), "last_worked_at": row.get("last_worked_at"),
        "created_at": row.get("created_at"), "updated_at": row.get("updated_at"),
        "moves": [{"at": m.get("at"), "reasoning": m.get("reasoning"),
                   "actions": m.get("actions") or [], "proposed": m.get("proposed") or [],
                   "recap": m.get("recap")} for m in moves[-8:]],
    }


# ─── The tick ────────────────────────────────────────────────────────

async def assignments_tick() -> None:
    """Leader-gated, every CHECK_EVERY_MIN / 2. Measures every due
    assignment; thinks on the few that earn it."""
    if not enabled():
        return
    rows = await asyncio.to_thread(due_rows)
    for row in rows:
        try:
            await check_one(row)
        except Exception as e:  # pragma: no cover
            logger.warning(f"[assignments] {str(row.get('id'))[:8]} crashed: {e}")


def touch(business_id: str) -> int:
    """An event just reached this business: have its open assignments
    looked at on the next tick rather than in half an hour. Sync,
    cheap, never raises. Returns the rows touched."""
    try:
        rows = sb_clients.sb_patch_as_service(
            f"{TABLE}?business_id=eq.{business_id}&status=eq.active",
            {"next_check_at": _z(_now())})
        return len(rows) if isinstance(rows, list) else 0
    except Exception:
        return 0


def _thinks_today(row: Dict[str, Any], today: date) -> int:
    return int(row.get("thinks_today") or 0) if str(row.get("thinks_day") or "") == today.isoformat() else 0


def should_think(row: Dict[str, Any], progress: Dict[str, Any], now: Optional[datetime] = None) -> Tuple[bool, str]:
    """(think?, why). Cheap first: the model is the expensive part."""
    now = now or _now()
    try:
        import notification_engine
        awake = notification_engine._within_waking_hours(now)
    except Exception:
        awake = True
    if not awake:
        return False, "outside waking hours"
    if _thinks_today(row, now.date()) >= MAX_THINKS_PER_DAY:
        return False, "thought enough for today"
    last = _parse_ts(row.get("last_worked_at"))
    if last is None:
        return True, "first look"
    before = row.get("progress") if isinstance(row.get("progress"), dict) else {}
    if before.get("value") != progress.get("value"):
        return True, "progress moved"
    if now - last >= timedelta(hours=THINK_EVERY_HOURS):
        return True, f"{THINK_EVERY_HOURS}h since the last look"
    return False, "nothing changed"


async def check_one(row: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """One assignment, one look. Returns what happened, for the log and
    the tests: {"did": measured|completed|expired|thought|skipped, ...}."""
    import chief_agent
    now = now or _now()
    rid = str(row.get("id"))
    bid = str(row.get("business_id") or "")
    biz = await asyncio.to_thread(chief_agent._business, bid)
    if not biz:
        await asyncio.to_thread(save, rid, {"next_check_at": _z(now + timedelta(minutes=CHECK_EVERY_MIN))})
        return {"did": "skipped", "why": "no business"}

    progress = await asyncio.to_thread(measure, bid, row.get("target") or {})
    next_check = _z(now + timedelta(minutes=CHECK_EVERY_MIN))

    if progress.get("met"):
        await finish(biz, row, "completed", progress)
        return {"did": "completed", "progress": progress}
    deadline = _parse_ts(row.get("deadline"))
    if deadline and deadline <= now:
        await finish(biz, row, "expired", progress)
        return {"did": "expired", "progress": progress}

    think, why = should_think(row, progress, now)
    if think:
        if not chief_agent.business_enabled(biz):
            think, why = False, "the standing agent is off"
    if think:
        import policy_engine
        if policy_engine.is_paused(biz):
            think, why = False, "automations paused"
    if think:
        import spend_guard
        if spend_guard.over_budget(bid):
            think, why = False, "over the daily spend cap"
    if not think:
        await asyncio.to_thread(save, rid, {"progress": progress, "next_check_at": next_check})
        return {"did": "measured", "why": why, "progress": progress}

    record = await work(biz, {**row, "progress": progress}, now=now)
    return {"did": "thought", "why": why, "progress": progress, "record": record}


async def finish(biz: Dict[str, Any], row: Dict[str, Any], status: str,
                 progress: Dict[str, Any]) -> None:
    """Close it and say so where the practitioner looks."""
    rid = str(row.get("id"))
    title = row.get("title") or "an assignment"
    label = progress.get("label") or ""
    if status == "completed":
        report = f"Done: {label}." if label else "Done."
        headline = f"Done: {title}"
    elif status == "expired":
        report = f"Ran out of time — {label}." if label else "Ran out of time."
        headline = f"Out of time: {title}"
    else:
        report = f"Stopped at {label}." if label else "Stopped."
        headline = f"Stopped: {title}"
    await asyncio.to_thread(save, rid, {"status": status, "progress": progress,
                                        "report": report, "next_check_at": None})
    await _announce(biz, row, headline, report, status)


async def _announce(biz: Dict[str, Any], row: Dict[str, Any], headline: str,
                    body: str, status: str) -> None:
    bid = str(biz.get("id") or row.get("business_id") or "")
    owner = biz.get("owner_id")
    try:
        sb_clients.sb_post_as_service("/chief_notifications", {
            "business_id": bid, "type": "reminder", "title": headline[:120],
            "body": body[:300], "priority": "normal",
        }, prefer="return=minimal")
    except Exception as e:
        logger.warning(f"[assignments] notification failed: {e}")
    try:
        sb_clients.sb_post_as_service("/chief_activity", {
            "user_id": owner, "business_id": bid, "source": "system",
            "action_type": f"assignment_{status}", "label": headline[:120],
            "summary": body[:240], "nav": None,
        }, prefer="return=minimal")
    except Exception as e:
        logger.warning(f"[assignments] activity row failed: {e}")
    if owner:
        try:
            import push_notifications
            await asyncio.to_thread(push_notifications.send_to_user, str(owner),
                                    title=headline[:80], body=body[:160], nav="home")
        except Exception as e:
            logger.warning(f"[assignments] push failed: {e}")


# ─── One think ───────────────────────────────────────────────────────

_PLAN_SYSTEM = """You are Chief, the chief of staff for {name}{kind}, working on an assignment the practitioner gave you. Nobody is talking to you now. Before you touch anything, write your plan for THIS look in two or three plain sentences: what the numbers say, what you will do next and why, and what you will leave alone (a move already made, a proposal still waiting on them). If nothing is worth doing right now, your whole answer is one sentence that begins with the word Nothing and says why. No lists, no markdown, no tool calls here — this is the note that goes on record before you act."""

_ACT_SYSTEM = """You are Chief, the chief of staff for {name}{kind}. Nobody is talking to you right now: you are working, on your own, on an assignment the practitioner gave you in so many words. They will read what you did the next time they open the app.

YOUR PLAN FOR THIS LOOK is below; follow it. Look before you act (the lookup tools), then do the next REVERSIBLE step toward the target with the tools that act: a task, a note, a waitlist or availability check, a follow-up you would have suggested, something remembered. One or two good moves beat five busy ones.

If the next step is a message to a client, an invoice, a charge, or a publish — PROPOSE it (propose_send_sms, propose_send_invoice, …): the exact words land in their Approval Queue and nothing happens until they approve. Never propose again what is already waiting on them. Never repeat a move in the log below. Do NOT try to send, charge or publish yourself; you have no tool for it on purpose.

WHAT YOU MUST NOT DO
- Never claim to have sent, charged, published or booked anything for a client.
- Never write anything that contradicts the practitioner's own records. Look first.

YOUR REPLY is the recap they will read: one or two short sentences, second person ("Thursday is at 3 of 6; I …"), naming what you did and what is waiting on them. No markdown, no headers, no [ACTION:] tags — tags do nothing here; tools are the only way to act."""


def _fmt_left(deadline: Optional[datetime], now: datetime) -> str:
    if not deadline:
        return "no deadline"
    left = deadline - now
    if left.total_seconds() <= 0:
        return "past due"
    if left.days >= 2:
        return f"{left.days} days left"
    hours = int(left.total_seconds() // 3600)
    return f"{hours} hour(s) left" if hours >= 1 else "under an hour left"


def _pending_proposals(moves: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The proposals this assignment has filed, with where they stand
    now — so the model neither re-proposes a text that is waiting nor
    forgets one that was dismissed."""
    ids = []
    for m in moves:
        for q in (m.get("proposed") or []):
            if q and q not in ids:
                ids.append(str(q))
    if not ids:
        return []
    try:
        rows = sb_clients.sb_get_as_service(
            f"/agent_queue?id=in.({','.join(ids[-20:])})&select=id,status,subject") or []
    except Exception:
        return []
    return [{"id": r.get("id"), "status": r.get("status"), "subject": r.get("subject")}
            for r in rows if isinstance(r, dict)]


def brief(row: Dict[str, Any], now: Optional[datetime] = None,
          pending: Optional[List[Dict[str, Any]]] = None) -> str:
    """The assignment as the model reads it. Third-party text (the ask,
    subjects) is defused: it is the model's INPUT."""
    now = now or _now()
    progress = row.get("progress") if isinstance(row.get("progress"), dict) else {}
    moves = row.get("moves") if isinstance(row.get("moves"), list) else []
    try:
        import untrusted_text
        clean = untrusted_text.defuse
    except Exception:  # pragma: no cover
        def clean(s):
            return s
    lines = [
        f"ASSIGNMENT: {clean(str(row.get('title') or ''))}",
        f"Asked for, in their words: {clean(str(row.get('ask') or '')[:400])}",
        f"Target: {describe_target(row.get('target') or {})}",
        f"Where it stands: {progress.get('label') or 'not measured yet'}",
        f"Deadline: {str(row.get('deadline') or '')[:16].replace('T', ' ')} ({_fmt_left(_parse_ts(row.get('deadline')), now)})",
        f"Now: {_z(now)[:16].replace('T', ' ')}",
    ]
    if moves:
        lines.append(f"Moves so far ({len(moves)}), latest last:")
        for m in moves[-6:]:
            acts = ", ".join(m.get("actions") or []) or "no actions"
            lines.append(f"- {str(m.get('at') or '')[:16].replace('T', ' ')}: "
                         f"{clean(str(m.get('reasoning') or '')[:160])} → {acts}")
    else:
        lines.append("Moves so far: none — this is the first look.")
    pending = pending if pending is not None else []
    waiting = [p for p in pending if p.get("status") in ("draft", "sent")]
    if waiting:
        lines.append("Waiting on the practitioner (do not propose these again):")
        for p in waiting[:8]:
            lines.append(f"- {clean(str(p.get('subject') or ''))[:120]}")
    dismissed = [p for p in pending if p.get("status") == "dismissed"]
    if dismissed:
        lines.append("They dismissed (do not repeat):")
        for p in dismissed[:5]:
            lines.append(f"- {clean(str(p.get('subject') or ''))[:120]}")
    return "\n".join(lines)


async def work(biz: Dict[str, Any], row: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """Reasoning first, on record; then the act turn; then the trace.
    Returns the move record."""
    import billing_context
    import chief_models
    import chief_of_staff as cos
    import chief_tool_loop as ctl

    now = now or _now()
    bid = str(biz.get("id") or row.get("business_id") or "")
    rid = str(row.get("id"))
    kind = f", a {biz.get('type')} business" if biz.get("type") else ""
    moves = list(row.get("moves") or []) if isinstance(row.get("moves"), list) else []
    pending = await asyncio.to_thread(_pending_proposals, moves)
    the_brief = brief(row, now, pending)
    import outcome_ledger
    digest = await outcome_ledger.digest_async(bid)
    if digest:
        the_brief += "\n\n" + "\n".join(digest)
    try:
        import feature_gates
        plan = feature_gates.plan_of(biz)
    except Exception:
        plan = None
    model = chief_models.model_for("chat", plan)

    try:
        cos._UNTRUSTED_TAINT.set(0)
    except Exception:
        pass
    started = now
    async with httpx.AsyncClient() as client:
        with billing_context.bill_to(bid):
            # 1. The plan, BEFORE anything is touched. No tools on this
            #    call: it cannot act, and it is cheap.
            ctl.reset_turn(writes_allowed=False, surface=SURFACE, prompted=False)
            raw_plan = await cos._call_claude(
                client, _PLAN_SYSTEM.format(name=biz.get("name") or "this business", kind=kind),
                [{"role": "user", "content": the_brief + "\n\nWrite your plan for this look."}],
                max_tokens=300, enable_web_search=False, business_id=bid, model=model)
            _, reasoning = cos._extract_actions_and_clean(raw_plan or "")
            reasoning = (reasoning or "").strip()[:800] or "No plan written."
            idle = reasoning.lower().startswith("nothing")

            # Written down before the act turn: a crash between the two
            # leaves the reasoning on record and no action unexplained.
            move = {"at": _z(now), "reasoning": reasoning, "actions": [], "proposed": [],
                    "recap": "", "idle": idle}
            await asyncio.to_thread(_append_move, rid, row, moves, move, now)

            taken: List[Dict[str, Any]] = []
            recap = ""
            tags = 0
            if not idle:
                ctl.reset_turn(writes_allowed=True, surface=SURFACE, prompted=False)
                tools = ctl.tool_definitions_for_turn(True)
                raw = await cos._call_claude(
                    client, _ACT_SYSTEM.format(name=biz.get("name") or "this business", kind=kind),
                    [{"role": "user", "content": the_brief + "\n\nYOUR PLAN FOR THIS LOOK:\n"
                      + reasoning + "\n\nLook, act where it helps, then write the recap."}],
                    max_tokens=chief_models.max_tokens_for("chat", default=900),
                    enable_web_search=False, business_id=bid, model=model,
                    read_tools=tools, tool_biz=biz)
                taken = ctl.writes_this_turn()
                tag_actions, recap = cos._extract_actions_and_clean(raw or "")
                tags = len(tag_actions)
                if tags:
                    logger.warning(f"[assignments] {bid[:8]} emitted {tags} [ACTION:] tag(s) — ignored")
            recap = (recap or "").strip() or (reasoning if idle else "I looked and nothing needed doing.")

        move["actions"] = [str(t.get("type")) for t in taken if isinstance(t, dict)]
        move["proposed"] = [str(t.get("queue_id")) for t in taken
                            if isinstance(t, dict) and t.get("queue_id")]
        move["recap"] = recap[:400]
        failed = [str(t.get("type")) for t in taken if isinstance(t, dict) and cos._action_failed(t)]
        record = {
            "business_id": bid, "assignment_id": rid, "title": row.get("title"),
            "reasoning": reasoning, "idle": idle,
            "actions": move["actions"], "proposed": move["proposed"], "failed": failed,
            "recap": recap[:600], "tags_ignored": tags,
            "duration_ms": int((_now() - started).total_seconds() * 1000),
        }
        await asyncio.to_thread(_finish_move, rid, row, moves, move, now)
        await _leave_trace(client, biz, taken, record)
    return record


def _append_move(rid: str, row: Dict[str, Any], moves: List[Dict[str, Any]],
                 move: Dict[str, Any], now: datetime) -> None:
    moves.append(move)
    del moves[:-MAX_MOVES_KEPT]
    today = now.date()
    save(rid, {"moves": moves, "last_worked_at": _z(now),
               "thinks_day": today.isoformat(), "thinks_today": _thinks_today(row, today) + 1,
               "progress": row.get("progress"),
               "next_check_at": _z(now + timedelta(minutes=CHECK_EVERY_MIN))})


def _finish_move(rid: str, row: Dict[str, Any], moves: List[Dict[str, Any]],
                 move: Dict[str, Any], now: datetime) -> None:
    if moves and moves[-1] is not move:
        moves[-1] = move
    save(rid, {"moves": moves})


async def _leave_trace(client, biz: Dict[str, Any], taken: List[Dict[str, Any]],
                       record: Dict[str, Any]) -> None:
    """Same three places the event runs leave theirs: the activity rail,
    the ledger, the run table. Best-effort, each independently."""
    import chief_of_staff as cos
    bid = record["business_id"]
    owner = biz.get("owner_id")
    title = record.get("title") or "an assignment"
    try:
        await cos._log_chief_activity(client, user_id=owner, business_id=bid,
                                      source="system", taken=taken)
    except Exception as e:
        logger.warning(f"[assignments] activity rows failed: {e}")
    if not record.get("idle"):
        try:
            await cos._sb(client, "POST", "/chief_activity", [{
                "user_id": owner, "business_id": bid, "source": "system",
                "action_type": "assignment_run",
                "label": f"Working on: {title}"[:120],
                "summary": record["recap"][:240], "nav": None,
            }])
        except Exception as e:
            logger.warning(f"[assignments] recap row failed: {e}")
    try:
        import audit_log
        await asyncio.to_thread(
            audit_log.record, bid, actor_type="chief", actor_id="agent",
            verb="assignment_run", ok=not record["failed"],
            error=(", ".join(record["failed"])[:500] or None),
            summary=record["reasoning"][:240],
            payload={"assignment_id": record["assignment_id"], "actions": record["actions"],
                     "proposed": record["proposed"], "idle": record["idle"],
                     "tags_ignored": record["tags_ignored"]},
            source="agent", authorized_by="agent:unattended")
    except Exception as e:
        logger.warning(f"[assignments] ledger row failed: {e}")
    try:
        await asyncio.to_thread(sb_clients.sb_post_as_service, "/agent_runs", {
            "business_id": bid, "surface": SURFACE, "tool": "assignment_run",
            "actor_email": "chief:agent", "allowed": True, "ok": not record["failed"],
            "duration_ms": record["duration_ms"],
            "error": (", ".join(record["failed"])[:300] or None),
            "arg_keys": sorted(set(record["actions"])),
            "detail": {"assignment_id": record["assignment_id"], "actions": record["actions"],
                       "proposed": record["proposed"], "idle": record["idle"],
                       "reasoning": record["reasoning"][:300],
                       "tags_ignored": record["tags_ignored"]},
        }, prefer="return=minimal")
    except Exception as e:
        logger.warning(f"[assignments] agent_runs row failed: {e}")
    try:
        import outcome_ledger
        await asyncio.to_thread(outcome_ledger.record_moves, bid, SURFACE, taken,
                                assignment_id=record.get("assignment_id"))
    except Exception as e:
        logger.warning(f"[assignments] outcome rows failed: {e}")


# ─── Chief's context ─────────────────────────────────────────────────

async def open_for_context(business_id: str) -> List[Dict[str, Any]]:
    """The open assignments, small, for _gather_context. Never raises."""
    try:
        rows = await asyncio.to_thread(open_rows, business_id, 5)
    except Exception:
        return []
    out = []
    for r in rows:
        p = r.get("progress") if isinstance(r.get("progress"), dict) else {}
        moves = r.get("moves") if isinstance(r.get("moves"), list) else []
        out.append({"id": r.get("id"), "title": r.get("title"),
                    "target": describe_target(r.get("target") or {}),
                    "progress": p.get("label") or "not measured yet",
                    "deadline": str(r.get("deadline") or "")[:10],
                    "moves": len(moves),
                    "last_worked_at": str(r.get("last_worked_at") or "")[:16].replace("T", " ")})
    return out


def context_lines(items: List[Dict[str, Any]]) -> List[str]:
    lines = []
    for a in items[:5]:
        line = f"  - {a.get('title')} — {a.get('progress')} (target: {a.get('target')}; due {a.get('deadline')})"
        line += (f"; Chief has made {a.get('moves')} move(s), last {a.get('last_worked_at')}"
                 if a.get("moves") else "; not worked yet")
        line += f" [id={a.get('id')}]"
        lines.append(line)
    return lines


# ─── Chat verbs ──────────────────────────────────────────────────────

def _fail(atype: str, msg: str) -> Dict[str, Any]:
    import chief_of_staff
    return chief_of_staff._fail(atype, msg)


async def handle_create_assignment(client, biz, action) -> Dict[str, Any]:
    """Class A: a row. Nothing runs now; the tick picks it up. Deleting
    (stop_assignment) undoes it completely."""
    deadline = None
    raw_dl = action.get("deadline")
    if raw_dl:
        deadline = _parse_ts(str(raw_dl))
        if deadline is None:
            d = _parse_date(str(raw_dl))
            if d:
                deadline = day_bounds(d, d, _tz_for(str(biz.get("id") or "")))[1]
        if deadline is None:
            return _fail("create_assignment", "deadline must be a date (YYYY-MM-DD)")
    if not isinstance(action.get("target"), dict):
        return _fail("create_assignment",
                     "target is required: {kind, from, to, count | amount} or {kind: 'manual'}")
    import chief_of_staff as cos
    err, row = await asyncio.to_thread(
        create, biz, title=str(action.get("title") or ""), ask=str(action.get("ask") or ""),
        target=action.get("target"), deadline=deadline, origin="chat",
        created_by=(cos._TURN_USER_ID.get() or None))
    if err:
        return _fail("create_assignment", err)
    on = False
    try:
        import chief_agent
        on = chief_agent.business_enabled(biz)
    except Exception:
        pass
    tail = ("" if on else
            " — turn on \"Chief works between conversations\" in Settings → Your Assistant, "
            "or I can only track it, not work it")
    return {
        "type": "create_assignment",
        "result": (f"taking on '{row['title']}': {describe_target(row['target'])}, "
                   f"by {str(row.get('deadline'))[:10]}{tail}"),
        "label": f"🎯 Assignment: {row['title']}",
        "assignment_id": row.get("id"),
        "title": row.get("title"),
        "target": row.get("target"),
        "deadline": row.get("deadline"),
        "agent_enabled": on,
        "speak": f"I'll work on {row['title']} until {str(row.get('deadline'))[:10]}.",
    }


async def handle_stop_assignment(client, biz, action) -> Dict[str, Any]:
    bid = str(biz.get("id") or "")
    rid = str(action.get("assignment_id") or "").strip()
    try:
        rows = await asyncio.to_thread(open_rows, bid)
    except Exception:
        return _fail("stop_assignment", "assignments are not set up on this server yet")
    if rid:
        rows = [r for r in rows if str(r.get("id")) == rid]
    elif action.get("title"):
        want = str(action.get("title")).strip().lower()
        rows = [r for r in rows if want in (r.get("title") or "").lower()] or rows
    if not rows:
        return _fail("stop_assignment", "no open assignment to stop")
    row = rows[-1]
    progress = row.get("progress") if isinstance(row.get("progress"), dict) else {}
    label = progress.get("label") or "not measured yet"
    ok = await asyncio.to_thread(save, str(row["id"]), {
        "status": "stopped", "report": f"Stopped by you at {label}.", "next_check_at": None})
    if not ok:
        return _fail("stop_assignment", "could not save — the assignment is still open")
    return {
        "type": "stop_assignment",
        "result": f"stopped '{row.get('title')}' at {label}",
        "label": f"⏹ Assignment stopped: {row.get('title')}",
        "assignment_id": row.get("id"),
    }


async def handle_assignment_status(client, biz, action) -> Dict[str, Any]:
    bid = str(biz.get("id") or "")
    try:
        rows = await asyncio.to_thread(recent_rows, bid, 10)
    except Exception:
        return _fail("assignment_status", "assignments are not set up on this server yet")
    open_ = [r for r in rows if r.get("status") in OPEN_STATUSES]
    items = [public_row(r) for r in rows]
    if not open_:
        return {"type": "assignment_status", "result": "no assignments open",
                "label": "🎯 Assignments: none open", "assignments": items,
                "signal": {"open": 0}}
    spoken = "; ".join(
        f"{r.get('title')}: {(r.get('progress') or {}).get('label') or 'not measured yet'}"
        for r in open_)
    return {
        "type": "assignment_status",
        "result": f"{len(open_)} open — {spoken}",
        "label": f"🎯 Assignments: {len(open_)} open",
        "assignments": items,
        "speak": spoken[:800],
        "signal": {"open": len(open_)},
    }


# ─── The HTTP door (the app's card) ──────────────────────────────────

def _require_owner(business_id: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,name,type,owner_id,settings,"
        "subscription_status,subscription_plan,comp_tier&limit=1") or []
    if not rows:
        raise HTTPException(status_code=404, detail="business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized for this business")
    return rows[0]


class _CreateBody(BaseModel):
    business_id: str
    title: str
    ask: str = ""
    target: Dict[str, Any]
    deadline: Optional[str] = None


class _StopBody(BaseModel):
    business_id: str
    assignment_id: str


@router.get("")
def list_assignments(business_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz = _require_owner(business_id, user)
    try:
        rows = recent_rows(business_id, 20)
    except Exception as e:
        logger.warning(f"[assignments] list failed: {e}")
        raise HTTPException(status_code=503, detail=f"assignments are not set up yet ({MIGRATION})")
    import chief_agent
    return {"ok": True,
            "assignments": [public_row(r) for r in rows],
            "open": sum(1 for r in rows if r.get("status") in OPEN_STATUSES),
            "cap": open_cap(biz),
            "agent_enabled": chief_agent.business_enabled(biz),
            "kinds": list(TARGET_KINDS)}


@router.post("")
def create_assignment(body: _CreateBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz = _require_owner(body.business_id, user)
    deadline = _parse_ts(body.deadline) if body.deadline else None
    if body.deadline and deadline is None:
        d = _parse_date(body.deadline)
        if d:
            deadline = day_bounds(d, d, _tz_for(body.business_id))[1]
        else:
            raise HTTPException(status_code=400, detail="deadline must be a date")
    err, row = create(biz, title=body.title, ask=body.ask, target=body.target,
                      deadline=deadline, origin="app", created_by=str(user.id))
    if err:
        raise HTTPException(status_code=400, detail=err)
    return {"ok": True, "assignment": public_row(row)}


@router.post("/stop")
def stop_assignment(body: _StopBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _require_owner(body.business_id, user)
    rows = [r for r in open_rows(body.business_id) if str(r.get("id")) == body.assignment_id]
    if not rows:
        raise HTTPException(status_code=404, detail="no open assignment with that id")
    row = rows[0]
    progress = row.get("progress") if isinstance(row.get("progress"), dict) else {}
    label = progress.get("label") or "not measured yet"
    if not save(body.assignment_id, {"status": "stopped", "report": f"Stopped by you at {label}.",
                                     "next_check_at": None}):
        raise HTTPException(status_code=502, detail="could not save")
    try:
        import audit_log
        audit_log.record(body.business_id, actor_type="user", actor_id=str(user.id),
                         verb="assignment_stop", ok=True, source="settings",
                         summary=f"Stopped assignment: {row.get('title')}")
    except Exception:
        pass
    return {"ok": True, "assignment": public_row({**row, "status": "stopped"})}
