"""
chief_cases.py — the open-problem record: a problem Chief diagnosed, the
fix, a forecast, and an honest check on the day it said it would look
(Solutionist Intelligence, 2026-10-05).

THE GAP
  Chief diagnoses well in chat ("Tuesdays are empty because your booking
  page shows you open around the clock"), proposes a fix, and the
  conversation ends. Nothing remembered the problem, nothing said what the
  fix should change, and nobody found out whether it worked. The outcome
  ledger records whether the owner TOOK Chief's move (approved, replied,
  done); it cannot say whether the problem went away. Assignments and the
  business responsibilities measure a target Chief works toward; they are
  not a diagnosis and they make no forecast.

WHAT A CASE IS
  One row per problem: the symptom in the owner's words, the cause Chief
  found, the record it found it in, the fix, and a forecast the code can
  check. The forecast is a measure (an assignment target kind, sessions
  optionally limited to weekdays) over the window AFTER the fix, the number
  BEFORE (the same measure over the same length of time just before the
  window, read when the case opens), and the number Chief EXPECTS.

  The day after the window closes, a tick measures with a plain read (no
  model) and records what the records show and a verdict: met, partly
  (moved, short of the forecast), not_met, or unmeasured. The owner is told
  once where they look (a notification, an activity row, a push), and the
  next conversations carry the result so Chief can say it plainly.

WHAT IT IS NOT
  Not permission: opening a case sends, books and charges nothing; the fix
  still goes through the normal actions and approvals. Not a causal claim:
  the result is what the records show beside what was expected, never proof
  the fix did it. Not work between conversations: if the owner wants Chief
  to chase the number, that is start_business_responsibility, unchanged.

THE WORDS (2026-10-05, Kevin: "the wording pass for all the businesses")
  "Case", "forecast" and "the records show" are this file's words, never
  the owner's. Everything an owner reads says "keeping an eye on",
  "hoping for", "before" and "now", and counts in their trade's own word
  from vertical_terminology: a barber's appointments, a coach's sessions,
  a lawyer's consultations, a church's meetings and members, a
  contractor's visits. The word is stored on the case when it opens, so
  every later line (the check, the card, Chief's context) needs no lookup.

STORAGE
  public.chief_cases (APPLY-2026-10-05-chief-cases.sql), service-role only:
  RLS on, no policies. Every write goes through the backend after the
  business was resolved for the signed-in owner. Fail-soft without the
  table: the verbs say cases are not set up yet, the tick logs the file.
  Kill switch: CHIEF_CASES=off.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException

import chief_assignments as assignments
import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("chief_cases")

router = APIRouter(prefix="/agents/chief/cases", tags=["chief-cases"])

TABLE = "/chief_cases"
MIGRATION = "APPLY-2026-10-05-chief-cases.sql"

KINDS = ("sessions_scheduled", "sessions_completed", "new_contacts",
         "revenue_collected", "invoice_paid")
_SESSION_KINDS = ("sessions_scheduled", "sessions_completed")
DEFAULT_WINDOW_DAYS = 21          # "the next three weeks"
MIN_WINDOW_DAYS = 3
MAX_WINDOW_DAYS = 90
DEFAULT_INVOICE_CHECK_DAYS = 14
MAX_OPEN = 10
MAX_ATTEMPTS = 3                  # failed reads before a check is "unmeasured"
RESULT_DAYS = 7                   # a checked result stays in Chief's context this long
TEXT_MAX = 600
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

_SELECT = ("select=id,business_id,status,symptom,cause,evidence,fix,measure,baseline,"
           "expected,check_on,result,verdict,outcome,note,attempts,created_at,updated_at,"
           "checked_at,closed_at")


def enabled() -> bool:
    return (os.environ.get("CHIEF_CASES") or "on").strip().lower() != "off"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _today(tz) -> date:
    return _now().astimezone(tz).date()


def _text(v: Any, limit: int = TEXT_MAX) -> str:
    return " ".join(str(v or "").split())[:limit]


def _short_date(d: Any) -> str:
    """'Oct 27' — how a person says a check date."""
    dd = assignments._parse_date(d)
    return f"{dd:%b} {dd.day}" if dd else str(d or "")


# ─── The forecast ────────────────────────────────────────────────────

def _weekday_list(raw: Any) -> Tuple[Optional[str], List[int]]:
    """Monday=0. Accepts names ('tuesday', 'Tue') or numbers 0-6."""
    if raw in (None, "", []):
        return None, []
    items = raw if isinstance(raw, list) else [raw]
    out: List[int] = []
    for item in items:
        if isinstance(item, int) and not isinstance(item, bool) and 0 <= item <= 6:
            out.append(item)
            continue
        name = str(item or "").strip().lower()
        hit = [i for i, w in enumerate(WEEKDAYS) if name and w.startswith(name[:3])]
        if len(name) < 3 or not hit:
            return f"weekdays must be day names like 'tuesday', not {item!r}", []
        out.append(hit[0])
    return None, sorted(set(out))


def _day_names(days: List[int]) -> str:
    names = [WEEKDAYS[d].capitalize() + "s" for d in days]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def unit_for(business_type: Optional[str], kind: str) -> str:
    """The trade's own word for what a measure counts, lower case: what
    the app's screens already call it (vertical_terminology, the mirror
    of the studio's dictionary.ts). Sessions are the vertical's word for
    a sitting (a coach's sessions, a lawyer's consultations, a church's
    meetings, a contractor's visits), else appointments: Kevin's 8/18
    ruling that a barber says "appointment". New contacts are the people
    it serves (clients, members, donors, students)."""
    try:
        import vertical_terminology as vt
        terms = vt.terms_for(business_type)
        if kind in _SESSION_KINDS:
            word = terms.get("sessions") or terms.get("appointments") or "Appointments"
        elif kind == "new_contacts":
            word = vt.get_term(business_type, "customers")
        else:
            return ""
    except Exception:  # a lookup must never cost the case
        word = "appointments" if kind in _SESSION_KINDS else "clients"
    return str(word or "").strip().lower()


def _noun(measure: Dict[str, Any]) -> str:
    kind = measure.get("kind")
    days = measure.get("weekdays") or []
    on = f" on {_day_names(days)}" if days else ""
    unit = measure.get("unit")
    return {
        "sessions_scheduled": f"{unit or 'appointments'}{on}",
        "sessions_completed": f"finished {unit or 'appointments'}{on}",
        "new_contacts": f"new {unit or 'clients'}",
        "revenue_collected": "in payments",
        "invoice_paid": "invoice paid",
    }.get(kind, "")


def _amount(kind: str, value: Any) -> str:
    if value is None:
        return "not counted"
    if kind == "revenue_collected":
        v = float(value)
        return f"${v:,.0f}" if v == int(v) else f"${v:,.2f}"
    if kind == "invoice_paid":
        return "paid" if value else "not paid"
    return str(int(value))


def describe(measure: Dict[str, Any], value: Any) -> str:
    """'4 appointments on Tuesdays and Wednesdays', '$1,200 in payments'."""
    kind = measure.get("kind") or ""
    if kind == "invoice_paid":
        return "the invoice " + _amount(kind, value)
    return f"{_amount(kind, value)} {_noun(measure)}"


def _span_words(d_from: Any, d_to: Any) -> str:
    """'three weeks', 'week', '10 days': how long a window is, said aloud."""
    a, b = assignments._parse_date(d_from), assignments._parse_date(d_to)
    if not a or not b:
        return "few weeks"
    n = (b - a).days + 1
    weeks = {7: "week", 14: "two weeks", 21: "three weeks", 28: "four weeks"}
    return weeks.get(n, f"{n} days")


def _dates(d_from: Any, d_to: Any) -> str:
    return f"{_short_date(d_from)} to {_short_date(d_to)}"


def normalize(raw: Any, expected: Any, *, tz, check_on: Any = None,
              today: Optional[date] = None) -> Tuple[Optional[str], Dict[str, Any]]:
    """(error, plan). Fails closed at opening, never three weeks later.

    plan = {measure, expected, window: (from, to), before: (from, to) | None,
            check_on}"""
    today = today or _today(tz)
    if not isinstance(raw, dict):
        return "measure must say what to count: {kind, from, to}", {}
    kind = str(raw.get("kind") or "").strip()
    if kind not in KINDS:
        return f"measure.kind must be one of {', '.join(KINDS)}", {}
    measure: Dict[str, Any] = {"kind": kind}

    if kind == "invoice_paid":
        iid = str(raw.get("invoice_id") or "").strip()
        if not re.fullmatch(r"[0-9a-fA-F-]{32,36}", iid):
            return "an invoice_paid case needs the invoice's id from the records", {}
        measure["invoice_id"] = iid
        when = assignments._parse_date(check_on) or (today + timedelta(days=DEFAULT_INVOICE_CHECK_DAYS))
        if not (today < when <= today + timedelta(days=MAX_WINDOW_DAYS)):
            return f"check_on must be a date in the next {MAX_WINDOW_DAYS} days", {}
        return None, {"measure": measure, "expected": 1, "window": None, "before": None,
                      "check_on": when}

    err, days = _weekday_list(raw.get("weekdays"))
    if err:
        return err, {}
    if days and kind not in _SESSION_KINDS:
        return "weekdays only apply to sessions", {}
    if days:
        measure["weekdays"] = days

    d_from = assignments._parse_date(raw.get("from")) or today
    d_to = assignments._parse_date(raw.get("to")) or (d_from + timedelta(days=DEFAULT_WINDOW_DAYS - 1))
    span = (d_to - d_from).days + 1
    if d_from < today - timedelta(days=1):
        return "the window is the time AFTER the fix, so it starts today or later", {}
    if span < MIN_WINDOW_DAYS:
        return f"give the fix at least {MIN_WINDOW_DAYS} days to show", {}
    if (d_to - today).days > MAX_WINDOW_DAYS:
        return f"a check more than {MAX_WINDOW_DAYS} days out is too far to follow", {}

    try:
        exp = float(expected)
    except (TypeError, ValueError):
        return "expected must be the number you forecast for that window", {}
    if exp <= 0:
        return "expected must be above zero", {}
    if kind != "revenue_collected":
        if exp != int(exp):
            return "expected must be a whole number for this measure", {}
        exp = int(exp)
    else:
        exp = round(exp, 2)

    before = (d_from - timedelta(days=span), d_from - timedelta(days=1))
    return None, {"measure": measure, "expected": exp, "window": (d_from, d_to),
                  "before": before, "check_on": d_to + timedelta(days=1)}


def measure_value(business_id: str, measure: Dict[str, Any],
                  d_from: Optional[date], d_to: Optional[date], *, tz=None) -> Any:
    """What the records show. A plain read; raises RuntimeError when the
    read fails, so a failure never turns into a zero."""
    kind = measure.get("kind")
    tz = tz or assignments._tz_for(business_id)
    if kind == "invoice_paid":
        return assignments.measure(business_id, {"kind": kind,
                                                 "invoice_id": measure.get("invoice_id")})["value"]
    days = measure.get("weekdays") or []
    if days and kind in _SESSION_KINDS:
        start, end = assignments.day_bounds(d_from, d_to, tz)
        rows = sb_clients.sb_get_as_service(
            f"/sessions?business_id=eq.{business_id}&scheduled_for=gte.{_z(start)}"
            f"&scheduled_for=lte.{_z(end)}&select=status,scheduled_for&limit=1000")
        if not isinstance(rows, list):
            raise RuntimeError("the sessions could not be read")
        if len(rows) >= 1000:
            raise RuntimeError("too many sessions in the window to count exactly")
        n = 0
        for r in rows:
            when = assignments._parse_ts(r.get("scheduled_for"))
            if when is None or when.astimezone(tz).weekday() not in days:
                continue
            status = (r.get("status") or "scheduled")
            if kind == "sessions_completed":
                n += status == "completed"
            else:
                n += status not in ("cancelled", "canceled", "no_show")
        return n
    target = {"kind": kind, "from": d_from.isoformat(), "to": d_to.isoformat()}
    target["amount" if kind == "revenue_collected" else "count"] = 1
    return assignments.measure(business_id, target, tz=tz)["value"]


def verdict(expected: Any, before: Any, value: Any) -> str:
    """met | partly | not_met | unmeasured. 'partly' means the number moved
    the right way but fell short of the forecast."""
    if value is None:
        return "unmeasured"
    try:
        v, e = float(value), float(expected)
    except (TypeError, ValueError):
        return "unmeasured"
    if v >= e:
        return "met"
    try:
        if before is not None and v > float(before):
            return "partly"
    except (TypeError, ValueError):
        pass
    return "not_met"


# ─── Rows ────────────────────────────────────────────────────────────

def open_rows(business_id: str, limit: int = MAX_OPEN + 1) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"{TABLE}?business_id=eq.{business_id}&status=eq.open&{_SELECT}"
        f"&order=created_at.desc&limit={limit}")
    if not isinstance(rows, list):
        raise RuntimeError("cases could not be read")
    return rows


def recent_rows(business_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"{TABLE}?business_id=eq.{business_id}&{_SELECT}&order=updated_at.desc&limit={limit}")
    if not isinstance(rows, list):
        raise RuntimeError("cases could not be read")
    return rows


def due_rows(today: Optional[date] = None) -> List[Dict[str, Any]]:
    """Open cases whose check day may have come. This reads by the UTC
    date; check_one then waits until the business's own date reaches
    check_on, so a check never lands while the window's last day runs."""
    today = today or _now().date()
    rows = sb_clients.sb_get_as_service(
        f"{TABLE}?status=eq.open&check_on=lte.{today.isoformat()}&{_SELECT}"
        f"&order=check_on.asc&limit=50")
    if not isinstance(rows, list):
        # sb_clients logs the status; a missing table is the usual reason.
        logger.info(f"[cases] due read failed; if new, apply supabase/{MIGRATION}")
        return []
    return rows


def save(case_id: str, patch: Dict[str, Any]) -> bool:
    rows = sb_clients.sb_patch_as_service(
        f"{TABLE}?id=eq.{case_id}", {**patch, "updated_at": _z(_now())})
    return isinstance(rows, list) and len(rows) > 0


def public_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """The shape the app card and the context read. Plain words, the
    numbers that make the forecast, nothing else."""
    measure = row.get("measure") if isinstance(row.get("measure"), dict) else {}
    baseline = row.get("baseline") if isinstance(row.get("baseline"), dict) else {}
    result = row.get("result") if isinstance(row.get("result"), dict) else {}
    kind = measure.get("kind") or ""
    out = {
        "id": row.get("id"),
        "status": row.get("status"),
        "symptom": row.get("symptom") or "",
        "cause": row.get("cause") or "",
        "fix": row.get("fix") or "",
        "evidence": row.get("evidence") or "",
        "measure": measure,
        "check_on": str(row.get("check_on") or "")[:10],
        "verdict": row.get("verdict"),
        "outcome": row.get("outcome"),
        "opened_at": str(row.get("created_at") or "")[:10],
        "checked_at": str(row.get("checked_at") or "")[:10] or None,
    }
    if kind == "invoice_paid":
        out["before"] = "the invoice not paid"
        out["forecast"] = "the invoice paid"
    else:
        out["before"] = (f"{describe(measure, baseline.get('value'))} "
                         f"({_dates(baseline.get('from'), baseline.get('to'))})")
        out["forecast"] = (f"{describe(measure, row.get('expected'))} "
                           f"({_dates(baseline.get('window_from'), baseline.get('window_to'))})")
    if result:
        out["result"] = describe(measure, result.get("value")) if result.get("value") is not None \
            else "couldn't be counted"
    return out


def open_case(biz: Dict[str, Any], *, symptom: str, cause: str, fix: str,
              evidence: str, measure: Any, expected: Any, check_on: Any = None,
              origin: str = "chat", created_by: Optional[str] = None
              ) -> Tuple[Optional[str], Dict[str, Any]]:
    """(error, row). Sync. Validates, reads the number before, writes the
    row. Nothing else happens: no send, no work between conversations."""
    bid = str(biz.get("id") or "")
    symptom, cause, fix = _text(symptom), _text(cause), _text(fix)
    if not (symptom and cause and fix):
        return "to keep an eye on a problem I need the problem, what's causing it, and the fix", {}
    tz = assignments._tz_for(bid)
    err, plan = normalize(measure, expected, tz=tz, check_on=check_on)
    if err:
        return err, {}
    try:
        existing = open_rows(bid)
    except Exception:
        return "I can't keep track of that right now; nothing was saved", {}
    if len(existing) >= MAX_OPEN:
        return (f"I'm already keeping an eye on {MAX_OPEN} things; close one first "
                "(close_case) so each gets a proper check"), {}
    want = symptom.lower()
    for r in existing:
        if (r.get("symptom") or "").strip().lower() == want:
            return f"I'm already keeping an eye on that one [id={r.get('id')}]", {}

    m = plan["measure"]
    unit = unit_for(biz.get("type"), m["kind"])
    if unit:
        m = {**m, "unit": unit}
    baseline: Dict[str, Any] = {}
    try:
        if m["kind"] == "invoice_paid":
            paid = measure_value(bid, m, None, None, tz=tz)
            if paid:
                return "that invoice is already paid, so there is nothing to forecast", {}
            baseline = {"value": 0}
        else:
            b_from, b_to = plan["before"]
            w_from, w_to = plan["window"]
            before = measure_value(bid, m, b_from, b_to, tz=tz)
            if float(plan["expected"]) <= float(before):
                return (f"what you hope for has to beat the number now: {describe(m, before)} "
                        f"in the same stretch just before ({_dates(b_from, b_to)})"), {}
            baseline = {"value": before, "from": b_from.isoformat(), "to": b_to.isoformat(),
                        "window_from": w_from.isoformat(), "window_to": w_to.isoformat()}
    except RuntimeError as e:
        return f"I couldn't count where things stand now ({e}), so nothing was saved", {}
    except Exception:
        return "I couldn't count where things stand now, so nothing was saved", {}

    row = {
        "business_id": bid, "status": "open",
        "symptom": symptom, "cause": cause, "fix": fix, "evidence": _text(evidence),
        "measure": m, "baseline": baseline, "expected": plan["expected"],
        "check_on": plan["check_on"].isoformat(),
        "origin": origin, "created_by": created_by,
    }
    try:
        saved = sb_clients.sb_post_as_service(TABLE, row, prefer="return=representation")
    except Exception:
        saved = None
    if isinstance(saved, list) and saved:
        return None, saved[0]
    if isinstance(saved, dict) and saved.get("id"):
        return None, saved
    return "that couldn't be saved", {}


# ─── The check ───────────────────────────────────────────────────────

def _result_line(row: Dict[str, Any], value: Any, v: str) -> Tuple[str, str]:
    """(headline, body) for the owner, said the way they'd say it, in
    their trade's word. Observed, never credited: the numbers moved or they
    did not, and Chief never claims its fix did it."""
    measure = row.get("measure") if isinstance(row.get("measure"), dict) else {}
    baseline = row.get("baseline") if isinstance(row.get("baseline"), dict) else {}
    kind = measure.get("kind") or ""
    problem = _text(row.get("symptom"), 70)
    if v == "unmeasured":
        return (f"Couldn't check: {problem}",
                "I couldn't get to your numbers to check this one. Ask me and I'll look again.")
    if kind == "invoice_paid":
        if v == "met":
            return f"Paid: {problem}", "The invoice is paid."
        return (f"Still not paid: {problem}",
                "The invoice still isn't paid. Ask me and we'll try something else.")
    got = describe(measure, value)
    before = baseline.get("value")
    hoped = _amount(kind, row.get("expected"))
    if v == "met":
        return (f"It worked: {problem}",
                f"{got}, up from {_amount(kind, before)}. I was hoping for {hoped}.")
    if v == "partly":
        return (f"It helped: {problem}",
                f"{got}, up from {_amount(kind, before)}. I was hoping for {hoped}. "
                "Ask me and we'll try one more thing.")
    try:
        same = float(value) == float(before)
    except (TypeError, ValueError):
        same = False
    moved = "the same as before" if same else f"down from {_amount(kind, before)}"
    return (f"No change yet: {problem}",
            f"{got}, {moved}. I was hoping for {hoped}. Ask me and we'll try something else.")


async def check_one(row: Dict[str, Any]) -> Dict[str, Any]:
    """Measure one due case, record what happened, tell the owner once."""
    cid = str(row.get("id"))
    bid = str(row.get("business_id") or "")
    measure = row.get("measure") if isinstance(row.get("measure"), dict) else {}
    baseline = row.get("baseline") if isinstance(row.get("baseline"), dict) else {}
    tz = await asyncio.to_thread(assignments._tz_for, bid)
    # due_rows reads by the UTC date; the check day is the BUSINESS's day.
    # West of UTC the evening tick lands while the window's last day is
    # still running, so wait for the business's own date to arrive.
    local_today = _today(tz)
    check_on = assignments._parse_date(row.get("check_on"))
    if check_on and local_today < check_on:
        return {"id": cid, "verdict": None, "waiting": True}
    w_from = assignments._parse_date(baseline.get("window_from"))
    w_to = assignments._parse_date(baseline.get("window_to"))
    try:
        value = await asyncio.to_thread(measure_value, bid, measure, w_from, w_to, tz=tz)
    except Exception as e:
        attempts = int(row.get("attempts") or 0) + 1
        # Three failed reads, or three days past the check day whatever
        # the counter says (an attempts write can fail too): unmeasured.
        late = bool(check_on) and (local_today - check_on).days >= MAX_ATTEMPTS
        if attempts < MAX_ATTEMPTS and not late:
            if not await asyncio.to_thread(save, cid, {"attempts": attempts}):
                logger.warning(f"[cases] {cid[:8]} could not record failed attempt {attempts}")
            logger.info(f"[cases] {cid[:8]} check failed ({e}); retry {attempts}/{MAX_ATTEMPTS}")
            return {"id": cid, "verdict": None}
        value = None
    v = verdict(row.get("expected"), baseline.get("value"), value)
    now = _z(_now())
    saved = await asyncio.to_thread(save, cid, {
        "status": "checked", "verdict": v, "checked_at": now,
        "result": {"value": value, "checked_at": now},
        "attempts": int(row.get("attempts") or 0) + (1 if value is None else 0)})
    if not saved:
        # The row is still open. Telling the owner now would tell them
        # again on every tick until the write lands; the next tick retries.
        logger.warning(f"[cases] {cid[:8]} result not saved; owner not told yet")
        return {"id": cid, "verdict": None, "unsaved": v}
    head, body = _result_line(row, value, v)
    await _announce(bid, head, body, v)
    return {"id": cid, "verdict": v, "value": value}


async def _announce(business_id: str, headline: str, body: str, v: str) -> None:
    """Where the owner looks: the notification list, the activity rail,
    their phone. Each is best-effort; the row is the record."""
    owner = None
    try:
        rows = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{business_id}&select=owner_id&limit=1") or []
        owner = rows[0].get("owner_id") if rows else None
    except Exception:
        pass
    try:
        sb_clients.sb_post_as_service("/chief_notifications", {
            "business_id": business_id, "type": "reminder", "title": headline[:120],
            "body": body[:300], "priority": "normal",
        }, prefer="return=minimal")
    except Exception as e:
        logger.warning(f"[cases] notification failed: {e}")
    if owner:
        try:
            sb_clients.sb_post_as_service("/chief_activity", {
                "user_id": owner, "business_id": business_id, "source": "system",
                "action_type": f"case_{v}", "label": headline[:120],
                "summary": body[:240], "nav": None,
            }, prefer="return=minimal")
        except Exception as e:
            logger.warning(f"[cases] activity row failed: {e}")
        try:
            import push_notifications
            await asyncio.to_thread(push_notifications.send_to_user, str(owner),
                                    title=headline[:80], body=body[:160], nav="home")
        except Exception as e:
            logger.warning(f"[cases] push failed: {e}")


async def cases_tick() -> None:
    """Every six hours. A quiet tick is one indexed read."""
    if not enabled():
        return
    rows = await asyncio.to_thread(due_rows)
    for row in rows:
        try:
            await check_one(row)
        except Exception as e:  # pragma: no cover
            logger.warning(f"[cases] {str(row.get('id'))[:8]} crashed: {e}")


# ─── Chief's context ─────────────────────────────────────────────────

def _context_rows(business_id: str) -> List[Dict[str, Any]]:
    since = _z(_now() - timedelta(days=RESULT_DAYS))
    rows = sb_clients.sb_get_as_service(
        f"{TABLE}?business_id=eq.{business_id}"
        f"&or=(status.eq.open,and(status.eq.checked,checked_at.gte.{since}))"
        f"&{_SELECT}&order=updated_at.desc&limit=8")
    return rows if isinstance(rows, list) else []


async def open_for_context(business_id: str) -> List[Dict[str, Any]]:
    """Open cases and results from the last week, small, for
    _gather_context. Never raises."""
    try:
        rows = await asyncio.to_thread(_context_rows, business_id)
    except Exception:
        return []
    return [public_row(r) for r in rows]


_VERDICT_WORDS = {"met": "it worked", "partly": "it helped, short of what you hoped",
                  "not_met": "no change yet", "unmeasured": "couldn't check"}


def context_lines(items: List[Dict[str, Any]]) -> List[str]:
    """Chief reads these in the owner's words, so it says them back in the
    owner's words: no "case", "forecast" or "the records show"."""
    lines = []
    for c in items[:8]:
        line = f"  - {c.get('symptom')} — why: {c.get('cause')}; the fix: {c.get('fix')}"
        if c.get("status") == "open":
            line += (f". Before: {c.get('before')}. Hoping for: {c.get('forecast')}. "
                     f"Checking on {c.get('check_on')}.")
        else:
            line += (f". RESULT to tell them ({_VERDICT_WORDS.get(c.get('verdict'), 'checked')}, "
                     f"checked {c.get('checked_at')}): before {c.get('before')}; hoping for "
                     f"{c.get('forecast')}; now {c.get('result')}.")
        line += f" [id={c.get('id')}]"
        lines.append(line)
    return lines


# ─── Chat verbs ──────────────────────────────────────────────────────

def _fail(atype: str, msg: str) -> Dict[str, Any]:
    import chief_of_staff
    return chief_of_staff._fail(atype, msg)


async def handle_open_case(client, biz, action) -> Dict[str, Any]:
    """Class A: one row, read-only measurement. close_case undoes it."""
    import chief_of_staff as cos
    err, row = await asyncio.to_thread(
        open_case, biz,
        symptom=action.get("symptom"), cause=action.get("cause"), fix=action.get("fix"),
        evidence=action.get("evidence"), measure=action.get("measure"),
        expected=action.get("expected"), check_on=action.get("check_on"),
        origin="chat", created_by=(cos._TURN_USER_ID.get() or None))
    if err:
        return _fail("open_case", err)
    pub = public_row(row)
    when = _short_date(pub["check_on"])
    m = row.get("measure") if isinstance(row.get("measure"), dict) else {}
    b = row.get("baseline") if isinstance(row.get("baseline"), dict) else {}
    if m.get("kind") == "invoice_paid":
        said = f"I'll check on {when} whether it's paid."
    else:
        span = _span_words(b.get("window_from"), b.get("window_to"))
        said = (f"{describe(m, b.get('value'))} in the last {span}. I'm hoping for "
                f"{_amount(m.get('kind') or '', row.get('expected'))} in the next {span}, "
                f"and I'll check on {when}.")
    return {
        "type": "open_case",
        "result": f"keeping an eye on '{pub['symptom']}'. {said}",
        "label": f"👀 Keeping an eye on: {_text(pub['symptom'], 60)}",
        "case_id": row.get("id"),
        "case": pub,
        "speak": said,
        "for_chief": ("Tell the owner in one plain sentence, in their words: where it stands "
                      "now, what you're hoping for, and the day you'll check, the way `speak` "
                      "says it. Never call it a case or a forecast, and never say 'the records "
                      "show'. Keeping an eye on it sends, books and charges nothing; the fix "
                      "itself still needs its own action or approval."),
    }


async def handle_close_case(client, biz, action) -> Dict[str, Any]:
    bid = str(biz.get("id") or "")
    outcome = str(action.get("outcome") or "").strip().lower()
    if outcome not in ("solved", "dropped"):
        return _fail("close_case", "say whether the problem is solved or should be dropped")
    try:
        rows = await asyncio.to_thread(recent_rows, bid, 20)
    except Exception:
        return _fail("close_case", "cases are not available right now")
    rows = [r for r in rows if r.get("status") in ("open", "checked")]
    cid = str(action.get("case_id") or "").strip()
    if cid:
        rows = [r for r in rows if str(r.get("id")) == cid]
    if not rows:
        return _fail("close_case", "there's nothing open to close")
    if not cid and len(rows) > 1:
        # "The Tuesday thing is solved" must never close a different case.
        names = "; ".join(f"'{_text(r.get('symptom'), 60)}' [id={r.get('id')}]" for r in rows[:5])
        return _fail("close_case", f"I'm keeping an eye on more than one thing — ask which one, then pass its case_id: {names}")
    row = rows[0]
    ok = await asyncio.to_thread(save, str(row["id"]), {
        "status": "closed", "outcome": outcome, "note": _text(action.get("note")),
        "closed_at": _z(_now())})
    if not ok:
        return _fail("close_case", "that didn't save; it's still open")
    word = "fixed" if outcome == "solved" else "dropped"
    return {
        "type": "close_case",
        "result": f"marked '{row.get('symptom')}' as {word}; no longer keeping an eye on it",
        "label": (f"✅ Fixed: {_text(row.get('symptom'), 60)}" if outcome == "solved"
                  else f"Dropped: {_text(row.get('symptom'), 60)}"),
        "case_id": row.get("id"),
    }


# ─── The HTTP door (the app's card) ──────────────────────────────────

@router.get("")
def list_cases(business_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    assignments._require_owner(business_id, user)
    try:
        rows = recent_rows(business_id, 20)
    except Exception as e:
        logger.warning(f"[cases] list failed: {e}")
        raise HTTPException(status_code=503, detail=f"cases are not set up yet ({MIGRATION})")
    items = [public_row(r) for r in rows if r.get("status") in ("open", "checked")]
    return {"ok": True, "cases": items,
            "open": sum(1 for r in rows if r.get("status") == "open")}
