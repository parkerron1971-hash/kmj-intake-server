"""
outcome_ledger.py — what happened after Chief made a move.

THE GAP (the "Chief to Eight" plan, phase three, 2026-09-04)
  The standing agent and the assignments engine leave a full trace of
  what Chief DID — activity rows, the audit ledger, agent_runs — and
  nothing about what came of it. A task Chief set that nobody touched,
  a text it proposed that was dismissed three times running, a reminder
  that got the invoice paid: none of it was recorded as an outcome, so
  none of it could teach the next move. The bookkeeping engine had its
  own small version (chief_learning_signals, corrections only) that
  nothing else read.

WHAT THIS IS
  One row per move in public.chief_moves, written at trace time by the
  agent and the assignments engine, with the ids the move produced (a
  queue id, a task id, a contact). A reconciler, every six hours, asks
  plain questions of the data — no model — and fills in the outcome:

    a proposal   → approved | dismissed | expired      (agent_queue)
                 → replied, when the contact wrote back within three
                   days of an approval                  (events)
    a task       → completed | ignored                  (tasks)
    an assignment's moves → met | missed | stopped      (chief_assignments)
    anything else Chief did (a note, a log, a memory) is "done" the
    moment it is made — there is no signal to wait for.
    pending past NO_SIGNAL_DAYS → no_signal.

  From those rows, three things:
    digest_lines()  — five lines for the prompts: what lands with this
                      practitioner, so the next move is shaped by the
                      last thirty days rather than by nothing.
    retired_verbs() — the hard rule that needs no model: a proposal
                      verb whose last RETIRE_AFTER outcomes were all
                      dismissed or expired is retired for
                      RETIRE_WINDOW_DAYS. The tool loop refuses it;
                      the practitioner is told once.
    stats()         — per-verb tallies for the app and the weekly
                      report (phase four).

  Service-role only, RLS on, no policies. Fail-soft without the table:
  recording and reading return nothing; the tick logs the migration.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("outcome_ledger")

router = APIRouter(prefix="/agents/chief/outcomes", tags=["chief-outcomes"])

TABLE = "/chief_moves"
MIGRATION = "APPLY-2026-09-04-chief-moves.sql"

PENDING = "pending"
DONE = "done"
TERMINAL = ("done", "approved", "dismissed", "expired", "replied", "completed", "ignored",
            "met", "missed", "stopped", "no_signal")
NEGATIVE = ("dismissed", "expired")

RETIRE_AFTER = 3
RETIRE_WINDOW_DAYS = 14
NO_SIGNAL_DAYS = 7
REPLY_WINDOW_DAYS = 3
DIGEST_DAYS = 30
MAX_PER_SWEEP = 500

_SELECT = ("select=id,business_id,surface,verb,assignment_id,queue_id,target_type,target_id,"
           "contact_id,outcome,outcome_at,made_at")


def enabled() -> bool:
    return (os.environ.get("OUTCOME_LEDGER") or "on").strip().lower() != "off"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _ts(s: Any) -> Optional[datetime]:
    if not isinstance(s, str) or not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _configured() -> bool:
    return bool(os.environ.get("SUPABASE_URL"))


# ─── Recording ────────────────────────────────────────────────────────

def _target_of(t: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    for key, kind in (("task_id", "task"), ("invoice_id", "invoice"), ("session_id", "session"),
                      ("contact_id", "contact"), ("note_id", "note")):
        v = t.get(key)
        if v:
            return kind, str(v)
    nav = t.get("nav") if isinstance(t.get("nav"), dict) else {}
    if nav.get("contact_id"):
        return "contact", str(nav["contact_id"])
    return None, None


def rows_for(business_id: str, surface: str, taken: List[Dict[str, Any]], *,
             assignment_id: Optional[str] = None, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """The ledger rows one run produces. Pure; the tests read this."""
    import chief_of_staff as cos
    now = now or _now()
    out: List[Dict[str, Any]] = []
    for t in taken:
        if not isinstance(t, dict) or not t.get("type"):
            continue
        if t.get("type") == "navigate" or cos._action_failed(t):
            continue
        qid = str(t.get("queue_id") or "") or None
        kind, tid = _target_of(t)
        waits = bool(qid) or kind == "task" or bool(assignment_id)
        out.append({
            "business_id": business_id,
            "surface": surface,
            "verb": str(t.get("type")),
            "assignment_id": assignment_id,
            "queue_id": qid,
            "target_type": kind,
            "target_id": tid,
            "contact_id": str(t.get("contact_id") or (kind == "contact" and tid) or "") or None,
            "outcome": PENDING if waits else DONE,
            "outcome_at": None if waits else _z(now),
            "made_at": _z(now),
        })
    return out


def record_moves(business_id: str, surface: str, taken: List[Dict[str, Any]], *,
                 assignment_id: Optional[str] = None) -> int:
    """Sync, best-effort, never raises. Returns rows written."""
    if not enabled():
        return 0
    rows = rows_for(business_id, surface, taken, assignment_id=assignment_id)
    if not rows:
        return 0
    try:
        res = sb_clients.sb_post_as_service(TABLE, rows, prefer="return=minimal")  # type: ignore[arg-type]
        if res is None:
            logger.info(f"[outcomes] write refused (table missing? apply {MIGRATION})")
            return 0
        return len(rows)
    except Exception as e:
        logger.warning(f"[outcomes] record failed: {e}")
        return 0


# ─── Reconciling ─────────────────────────────────────────────────────

def _chunks(ids: List[str], n: int = 80):
    for i in range(0, len(ids), n):
        yield ids[i:i + n]


def _fetch_by_id(path: str, ids: List[str], select: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for part in _chunks(sorted(set(i for i in ids if i))):
        rows = sb_clients.sb_get_as_service(f"{path}?id=in.({','.join(part)})&select={select}") or []
        for r in rows:
            if isinstance(r, dict) and r.get("id"):
                out[str(r["id"])] = r
    return out


def _set_outcome(move_id: str, outcome: str, now: datetime) -> bool:
    res = sb_clients.sb_patch_as_service(
        f"{TABLE}?id=eq.{move_id}", {"outcome": outcome, "outcome_at": _z(now)})
    return res is not None


def resolve_pending(now: Optional[datetime] = None) -> Dict[str, int]:
    """Plain questions of the data. Returns a tally by outcome."""
    now = now or _now()
    try:
        moves = sb_clients.sb_get_as_service(
            f"{TABLE}?outcome=eq.{PENDING}&order=made_at.asc&limit={MAX_PER_SWEEP}&{_SELECT}")
    except Exception as e:
        logger.warning(f"[outcomes] fetch failed (apply {MIGRATION}): {e}")
        return {}
    if not isinstance(moves, list) or not moves:
        moves = []
    tally: Dict[str, int] = {}

    queue = _fetch_by_id("/agent_queue", [m.get("queue_id") for m in moves if m.get("queue_id")],
                         "id,status,reviewed_at,sent_at")
    tasks = _fetch_by_id("/tasks", [m.get("target_id") for m in moves if m.get("target_type") == "task"],
                         "id,status,due_date,completed_at")
    assignments = _fetch_by_id("/chief_assignments",
                               [m.get("assignment_id") for m in moves if m.get("assignment_id")],
                               "id,status")
    for m in moves:
        made = _ts(m.get("made_at")) or now
        age = now - made
        outcome: Optional[str] = None
        if m.get("queue_id"):
            q = queue.get(str(m["queue_id"]))
            st = (q or {}).get("status")
            if st in ("approved", "sent"):
                outcome = "approved"
            elif st == "dismissed":
                outcome = "dismissed"
            elif st == "expired":
                outcome = "expired"
            elif q is None or age > timedelta(days=NO_SIGNAL_DAYS):
                outcome = "no_signal"
        elif m.get("target_type") == "task":
            t = tasks.get(str(m.get("target_id")))
            if t is None:
                outcome = "no_signal" if age > timedelta(days=1) else None
            elif t.get("status") == "done" or t.get("completed_at"):
                outcome = "completed"
            else:
                due = _ts((str(t.get("due_date")) + "T23:59:59+00:00") if t.get("due_date") else None)
                if (due and due < now - timedelta(days=1)) or age > timedelta(days=NO_SIGNAL_DAYS):
                    outcome = "ignored"
        elif m.get("assignment_id"):
            a = assignments.get(str(m["assignment_id"]))
            st = (a or {}).get("status")
            if st == "completed":
                outcome = "met"
            elif st == "expired":
                outcome = "missed"
            elif st == "stopped":
                outcome = "stopped"
            elif a is None or age > timedelta(days=DIGEST_DAYS):
                outcome = "no_signal"
        if outcome:
            if _set_outcome(str(m["id"]), outcome, now):
                tally[outcome] = tally.get(outcome, 0) + 1

    # Second-order: did the person write back after an approved message?
    since = _z(now - timedelta(days=REPLY_WINDOW_DAYS))
    approved = sb_clients.sb_get_as_service(
        f"{TABLE}?outcome=eq.approved&contact_id=not.is.null&outcome_at=gte.{since}"
        f"&limit={MAX_PER_SWEEP}&{_SELECT}") or []
    for m in approved if isinstance(approved, list) else []:
        after = m.get("outcome_at") or m.get("made_at")
        ev = sb_clients.sb_get_as_service(
            f"/events?business_id=eq.{m.get('business_id')}&contact_id=eq.{m.get('contact_id')}"
            f"&event_type=in.(sms_received,email_replied)&created_at=gte.{after}&select=id&limit=1") or []
        if ev and _set_outcome(str(m["id"]), "replied", now):
            tally["replied"] = tally.get("replied", 0) + 1
    return tally


# ─── Reading back ─────────────────────────────────────────────────────

def recent_moves(business_id: str, days: int = DIGEST_DAYS, limit: int = 400) -> List[Dict[str, Any]]:
    since = _z(_now() - timedelta(days=days))
    rows = sb_clients.sb_get_as_service(
        f"{TABLE}?business_id=eq.{business_id}&made_at=gte.{since}"
        f"&order=made_at.desc&limit={limit}&{_SELECT}")
    return rows if isinstance(rows, list) else []


def stats(moves: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Per-verb tallies, from rows already in hand."""
    per: Dict[str, Dict[str, int]] = {}
    for m in moves:
        v = str(m.get("verb") or "?")
        c = per.setdefault(v, {})
        o = str(m.get("outcome") or PENDING)
        c[o] = c.get(o, 0) + 1
        c["total"] = c.get("total", 0) + 1
    return per


def retired_verbs(moves: List[Dict[str, Any]], now: Optional[datetime] = None) -> List[str]:
    """Verbs whose last RETIRE_AFTER proposal outcomes, inside the
    window, were all dismissed or expired. Pending ones do not count
    either way; an approval anywhere in the last three ends it."""
    now = now or _now()
    since = now - timedelta(days=RETIRE_WINDOW_DAYS)
    by_verb: Dict[str, List[str]] = {}
    for m in sorted(moves, key=lambda r: str(r.get("made_at") or ""), reverse=True):
        if not m.get("queue_id"):
            continue
        made = _ts(m.get("made_at"))
        if made and made < since:
            continue
        o = str(m.get("outcome") or PENDING)
        if o in (PENDING, "no_signal"):
            continue
        lst = by_verb.setdefault(str(m.get("verb")), [])
        if len(lst) < RETIRE_AFTER:
            lst.append(o)
    return sorted(v for v, lst in by_verb.items()
                  if len(lst) >= RETIRE_AFTER and all(o in NEGATIVE for o in lst))


def retired_for(business_id: str) -> List[str]:
    """The live answer, for the tool loop. Never raises; empty without
    a configured database."""
    if not enabled() or not _configured():
        return []
    try:
        return retired_verbs(recent_moves(business_id, RETIRE_WINDOW_DAYS))
    except Exception:
        return []


_WORDS = {
    "send_sms": "texts", "send_invoice": "invoice sends", "mark_invoice_paid": "payments recorded",
    "generate_payment_link": "payment links", "publish_to_site": "site posts",
    "draft_email": "emails", "create_task": "tasks",
}


def _plural(verb: str) -> str:
    verb = verb[8:] if verb.startswith("propose_") else verb
    return _WORDS.get(verb, verb.replace("_", " ") + "s")


def digest_lines(moves: List[Dict[str, Any]], now: Optional[datetime] = None) -> List[str]:
    """At most six lines. Proposals first, then tasks, then assignments,
    then the retired list. Empty when there is nothing to say."""
    if not moves:
        return []
    per = stats(moves)
    retired = set(retired_verbs(moves, now))
    lines: List[str] = []
    proposal_verbs = sorted(v for v in per if any(m.get("queue_id") for m in moves if m.get("verb") == v))
    for v in proposal_verbs:
        c = per[v]
        parts = []
        if c.get("approved", 0) + c.get("replied", 0):
            parts.append(f"{c.get('approved', 0) + c.get('replied', 0)} approved")
        if c.get("dismissed"):
            parts.append(f"{c['dismissed']} dismissed")
        if c.get("expired"):
            parts.append(f"{c['expired']} expired unapproved")
        if c.get("replied"):
            parts.append(f"{c['replied']} got a reply")
        if not parts:
            continue
        line = f"  - {_plural(v)} you proposed: " + ", ".join(parts)
        if v in retired:
            line += " — RETIRED for two weeks: do not propose this"
        lines.append(line)
    t = per.get("create_task")
    if t and (t.get("completed") or t.get("ignored")):
        lines.append(f"  - tasks you set: {t.get('completed', 0)} completed, {t.get('ignored', 0)} ignored past due"
                     + (f", {t.get('pending', 0)} open" if t.get("pending") else ""))
    met = sum(1 for m in moves if m.get("outcome") == "met")
    missed = sum(1 for m in moves if m.get("outcome") == "missed")
    if met or missed:
        # moves, not assignments — but the ratio reads the same way
        lines.append(f"  - assignment moves: {met} toward outcomes that were met, {missed} toward ones that ran out of time")
    if not lines:
        return []
    return [f"WHAT LANDS WITH THIS PRACTITIONER (last {DIGEST_DAYS} days, from what came of your moves):"] + lines[:5]


def digest_for(business_id: str) -> List[str]:
    """Prompt lines, live. Never raises; empty without a database."""
    if not enabled() or not _configured():
        return []
    try:
        return digest_lines(recent_moves(business_id))
    except Exception:
        return []


async def digest_async(business_id: str) -> List[str]:
    return await asyncio.to_thread(digest_for, business_id)


# ─── The tick ─────────────────────────────────────────────────────────

async def outcomes_tick(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Every six hours, leader-gated: fill in outcomes, then tell each
    practitioner about a newly retired verb, once."""
    if not enabled():
        return {"skipped": "off"}
    now = now or _now()
    tally = await asyncio.to_thread(resolve_pending, now)
    told = await asyncio.to_thread(_announce_retirements, now)
    return {"resolved": tally, "retired_told": told}


def _announce_retirements(now: datetime) -> List[str]:
    """One notification per (business, verb) per window."""
    since = _z(now - timedelta(days=RETIRE_WINDOW_DAYS))
    rows = sb_clients.sb_get_as_service(
        f"{TABLE}?queue_id=not.is.null&outcome=in.({','.join(NEGATIVE)})&made_at=gte.{since}"
        f"&select=business_id&limit=2000") or []
    if not isinstance(rows, list):
        return []
    told: List[str] = []
    for bid in sorted({str(r.get("business_id")) for r in rows if r.get("business_id")}):
        try:
            retired = retired_verbs(recent_moves(bid, RETIRE_WINDOW_DAYS), now)
        except Exception:
            continue
        for verb in retired:
            key = f"retired:{verb}"
            dup = sb_clients.sb_get_as_service(
                f"/chief_notifications?business_id=eq.{bid}&action_payload->>dedup_key=eq.{key}"
                f"&created_at=gte.{since}&select=id&limit=1")
            if dup:
                continue
            noun = _plural(verb)
            try:
                sb_clients.sb_post_as_service("/chief_notifications", {
                    "business_id": bid, "type": "reminder", "priority": "normal",
                    "title": f"I've stopped proposing {noun}",
                    "body": (f"You dismissed the last {RETIRE_AFTER} {noun} I proposed, so I will not "
                             f"propose another for two weeks. Say the word in chat if you want them back."),
                    "action_payload": {"dedup_key": key},
                }, prefer="return=minimal")
                told.append(f"{bid[:8]}:{verb}")
            except Exception as e:
                logger.warning(f"[outcomes] retirement notice failed: {e}")
    return told


# ─── The door ─────────────────────────────────────────────────────────

def _require_owner(business_id: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(status_code=404, detail="business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(status_code=403, detail="not authorized for this business")
    return rows[0]


@router.get("")
def outcomes(business_id: str, days: int = DIGEST_DAYS,
             user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _require_owner(business_id, user)
    days = max(1, min(int(days or DIGEST_DAYS), 90))
    try:
        moves = recent_moves(business_id, days)
    except Exception as e:
        logger.warning(f"[outcomes] read failed: {e}")
        raise HTTPException(status_code=503, detail=f"outcomes are not set up yet ({MIGRATION})")
    return {"ok": True, "days": days, "moves": len(moves),
            "by_verb": stats(moves), "retired": retired_verbs(moves),
            "digest": digest_lines(moves)[1:],
            "recent": [{k: m.get(k) for k in ("verb", "surface", "outcome", "made_at", "outcome_at", "assignment_id")}
                       for m in moves[:50]]}
