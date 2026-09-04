"""
chief_week.py — Chief's week: what it did, what landed, what is waiting.

THE POINT (the "Chief to Eight" plan, phase four, 2026-09-04)
  An eight nobody can see is a six on the sales call. Every Monday,
  for each business whose Chief works between conversations, one
  report: how many moves it made on its own, what came of them
  (outcome_ledger), where the assignments stand (chief_assignments),
  what is waiting on a tap (agent_queue), and the minutes the
  practitioner did not have to spend — counted from the ledger, not
  guessed. It lands as a notification and a push, and the app's Home
  card reads the same numbers live any day of the week, with a Listen
  button.

  Nothing here calls a model. The sentences are assembled from counts,
  so the report is the same kind of true as the ledger it reads.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("chief_week")

router = APIRouter(prefix="/agents/chief/week", tags=["chief-week"])

DAYS = 7

# Minutes a practitioner would have spent doing the move by hand. Flat,
# conservative, and the same for everyone — the number is for a
# feeling of scale, and it is labelled "about".
MINUTES_BY_VERB = {
    "create_note": 2, "log_activity": 2, "save_note": 2, "remember": 1,
    "update_contact": 2, "update_contact_status": 1, "create_task": 3,
    "create_contact": 4, "draft_email": 8, "schedule_session": 4,
}
MINUTES_PROPOSAL = 6      # drafting the exact words of a text / invoice send
MINUTES_DEFAULT = 2

_VERB_WORDS = {
    "send_sms": "texts", "send_invoice": "invoice sends", "mark_invoice_paid": "payments recorded",
    "generate_payment_link": "payment links", "publish_to_site": "site posts",
    "draft_email": "emails", "create_task": "tasks", "create_note": "notes",
    "log_activity": "activity entries", "remember": "things remembered",
    "update_contact": "contact updates", "create_contact": "new contacts",
}


def enabled() -> bool:
    return (os.environ.get("CHIEF_WEEK") or "on").strip().lower() != "off"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _words(verb: str) -> str:
    return _VERB_WORDS.get(verb, verb.replace("_", " ") + "s")


def _n(n: int, one: str, many: Optional[str] = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


# ─── The report ───────────────────────────────────────────────────────

def _waiting(business_id: str) -> int:
    rows = sb_clients.sb_get_as_service(
        f"/agent_queue?business_id=eq.{business_id}&status=eq.draft&channel=eq.action"
        "&select=id&limit=50") or []
    return len(rows) if isinstance(rows, list) else 0


def compose(moves: List[Dict[str, Any]], assignments: List[Dict[str, Any]],
            waiting: int, *, days: int = DAYS, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Pure: the report from rows already in hand. The tests read this."""
    now = now or _now()
    since = now - timedelta(days=days)

    def _in_week(ts: Any) -> bool:
        if not isinstance(ts, str):
            return False
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return False
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)) >= since

    week = [m for m in moves if _in_week(m.get("made_at"))]
    proposals = [m for m in week if m.get("queue_id")]
    tasks = [m for m in week if m.get("target_type") == "task"]
    other = [m for m in week if not m.get("queue_id") and m.get("target_type") != "task"]

    p_out = {"filed": len(proposals)}
    for m in proposals:
        o = str(m.get("outcome") or "pending")
        p_out[o] = p_out.get(o, 0) + 1
    p_sent = p_out.get("approved", 0) + p_out.get("replied", 0)
    t_out = {"set": len(tasks), "completed": sum(1 for m in tasks if m.get("outcome") == "completed"),
             "ignored": sum(1 for m in tasks if m.get("outcome") == "ignored")}
    by_verb: Dict[str, int] = {}
    for m in other:
        v = str(m.get("verb") or "?")
        by_verb[v] = by_verb.get(v, 0) + 1

    minutes = 0
    for m in week:
        if m.get("queue_id"):
            minutes += MINUTES_PROPOSAL
        else:
            minutes += MINUTES_BY_VERB.get(str(m.get("verb") or ""), MINUTES_DEFAULT)

    done = [a for a in assignments if a.get("status") == "completed" and _in_week(a.get("updated_at"))]
    missed = [a for a in assignments if a.get("status") == "expired" and _in_week(a.get("updated_at"))]
    open_ = [a for a in assignments if a.get("status") == "active"]

    lines: List[str] = []
    if week:
        parts = []
        if proposals:
            p = f"drafted {_n(len(proposals), 'message or send', 'messages and sends')} for you"
            tail = []
            if p_sent:
                tail.append(f"{p_sent} you sent")
            if p_out.get("replied"):
                tail.append(f"{p_out['replied']} got a reply")
            if p_out.get("dismissed"):
                tail.append(f"{p_out['dismissed']} you dismissed")
            if p_out.get("expired"):
                tail.append(f"{p_out['expired']} expired unapproved")
            if tail:
                p += " (" + ", ".join(tail) + ")"
            parts.append(p)
        if tasks:
            t = f"set {_n(len(tasks), 'task')}"
            if t_out["completed"] or t_out["ignored"]:
                t += f" ({t_out['completed']} done" + (f", {t_out['ignored']} slipped past due" if t_out["ignored"] else "") + ")"
            parts.append(t)
        top = sorted(by_verb.items(), key=lambda kv: -kv[1])[:2]
        for v, c in top:
            parts.append(f"left {c} {_words(v)}" if v in ("create_note", "log_activity") else f"made {c} {_words(v)}")
        lines.append(f"This week Chief made {_n(len(week), 'move')} on its own: " + ", ".join(parts) + ".")
    else:
        lines.append("This week Chief made no moves on its own.")
    for a in done:
        lines.append(f"Done: {a.get('title')} — {((a.get('progress') or {}).get('label') or 'target met')}.")
    for a in missed:
        lines.append(f"Out of time: {a.get('title')} — {((a.get('progress') or {}).get('label') or 'target not met')}.")
    for a in open_[:3]:
        lines.append(f"Still working: {a.get('title')} — {((a.get('progress') or {}).get('label') or 'not measured yet')}.")
    if waiting:
        lines.append(f"{_n(waiting, 'thing is', 'things are')} waiting on your tap in the Approval Queue.")
    if minutes:
        lines.append(f"About {minutes} minutes you did not have to spend.")

    return {
        "days": days,
        "since": _z(since),
        "moves": len(week),
        "proposals": p_out,
        "tasks": t_out,
        "by_verb": by_verb,
        "assignments": {"done": [a.get("title") for a in done],
                        "out_of_time": [a.get("title") for a in missed],
                        "open": [{"title": a.get("title"),
                                  "progress": (a.get("progress") or {}).get("label")} for a in open_]},
        "waiting": waiting,
        "minutes_saved": minutes,
        "lines": lines,
        "spoken": " ".join(lines),
        "empty": not week and not done and not missed and not open_,
    }


def build(business_id: str, days: int = DAYS, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Sync, service role. Never raises past a missing table — the
    pieces degrade to empty."""
    import chief_assignments
    import outcome_ledger
    try:
        moves = outcome_ledger.recent_moves(business_id, days)
    except Exception:
        moves = []
    try:
        assignments = chief_assignments.recent_rows(business_id, 20)
    except Exception:
        assignments = []
    try:
        waiting = _waiting(business_id)
    except Exception:
        waiting = 0
    return compose(moves, assignments, waiting, days=days, now=now)


# ─── Monday ──────────────────────────────────────────────────────────

def _week_key(now: datetime) -> str:
    y, w, _ = now.isocalendar()
    return f"chief_week:{y}-W{w:02d}"


def _already_sent(business_id: str, key: str) -> bool:
    rows = sb_clients.sb_get_as_service(
        f"/chief_notifications?business_id=eq.{business_id}"
        f"&action_payload->>dedup_key=eq.{key}&select=id&limit=1")
    return bool(rows)


def deliver(biz: Dict[str, Any], report: Dict[str, Any], now: datetime) -> bool:
    """One notification, one activity row, one push. Returns whether
    anything was sent (an empty week sends nothing)."""
    bid = str(biz.get("id") or "")
    if report.get("empty"):
        return False
    key = _week_key(now)
    if _already_sent(bid, key):
        return False
    title = f"Chief's week: {report['moves']} move{'s' if report['moves'] != 1 else ''}" + (
        f", {report['waiting']} waiting on you" if report.get("waiting") else "")
    body = report["spoken"][:300]
    try:
        sb_clients.sb_post_as_service("/chief_notifications", {
            "business_id": bid, "type": "reminder", "priority": "normal",
            "title": title[:120], "body": body,
            "suggested_action": "Read the week",
            "action_payload": {"type": "navigate", "tab": "home", "dedup_key": key},
        }, prefer="return=minimal")
    except Exception as e:
        logger.warning(f"[week] notification failed: {e}")
        return False
    try:
        sb_clients.sb_post_as_service("/chief_activity", {
            "user_id": biz.get("owner_id"), "business_id": bid, "source": "system",
            "action_type": "chief_week", "label": title[:120],
            "summary": report["lines"][0][:240] if report.get("lines") else None, "nav": None,
        }, prefer="return=minimal")
    except Exception as e:
        logger.warning(f"[week] activity row failed: {e}")
    if biz.get("owner_id"):
        try:
            import push_notifications
            push_notifications.send_to_user(str(biz["owner_id"]), title=title[:80],
                                            body=body[:160], nav="home", tag="chief-week")
        except Exception as e:
            logger.warning(f"[week] push failed: {e}")
    return True


def _candidates() -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        "/businesses?is_active=eq.true&select=id,owner_id,settings&limit=500") or []
    return [r for r in rows if isinstance(r, dict)]


async def weekly_tick(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Monday, after the morning brief. Every active business whose
    standing agent is on, or that has anything in the ledger."""
    if not enabled():
        return {"skipped": "off"}
    now = now or _now()
    import chief_agent
    sent, looked = 0, 0
    for biz in await asyncio.to_thread(_candidates):
        try:
            report = await asyncio.to_thread(build, str(biz["id"]), DAYS, now)
            if not chief_agent.business_enabled(biz) and report.get("empty"):
                continue
            looked += 1
            if await asyncio.to_thread(deliver, biz, report, now):
                sent += 1
        except Exception as e:  # pragma: no cover
            logger.warning(f"[week] {str(biz.get('id'))[:8]} failed: {e}")
    return {"looked": looked, "sent": sent}


# ─── The door ─────────────────────────────────────────────────────────

def _require_access(business_id: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(status_code=404, detail="business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized for this business")
    return rows[0]


@router.get("")
def week(business_id: str, days: int = DAYS, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _require_access(business_id, user)
    days = max(1, min(int(days or DAYS), 30))
    return {"ok": True, "report": build(business_id, days)}
