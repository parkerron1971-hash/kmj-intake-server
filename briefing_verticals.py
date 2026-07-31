"""
briefing_verticals.py — the vertical-aware sections of the weekly briefing.

THE GAP THIS CLOSES (S12, second half)
  vertical_autopilot seeds a "briefing" job per vertical and labels it
  honestly — "Matter and deadline sweep" for the lawyer, "Practice review"
  for the therapist — but every one of those jobs ran the SAME generic
  agent. The lawyer's deadline sweep never read a deadline; the label was
  telling the truth about an agent that did not exist.

  This module makes the labels true. The briefing agent resolves the
  business's vertical INTERNALLY (vertical_registry.resolve on
  businesses.type) and adds sections built from real queries. Nothing is
  plumbed through the scheduler — the scheduler still says
  {"type": "run_agent", "agent": "briefing"} and nothing else, so the
  autopilot job definitions, the run_agent handler and the trust wall all
  stay exactly as audited.

EVERY NUMBER IS A QUERY RESULT
  Sections are computed BEFORE the LLM writes anything. Each section is a
  dict of precomputed lines + structured data; the LLM sees them as facts
  it may repeat but not derive from, and the deterministic markdown that
  lands in the stored briefing body is rendered here, not by the model.
  A briefing may be dull; it may never be wrong.

HONEST DEGRADATION
  A lawyer with no work_pipeline modules gets the generic briefing — not a
  "Matters" section full of zeros, and never a fabricated one. Every
  branch returns [] when its tables have nothing to say. service_provider
  and custom are DELIBERATELY generic (vertical_registry KNOWN_GAPS) and
  have no branch at all.

THE TWO ISOLATION WALLS
  * therapist — ADMIN ONLY, by the platform's HIPAA posture
    (vertical_registry.py, vertical_scope.py). The branch reads exactly
    two tables: /sessions (scheduling) and /invoices (billing). No
    contacts, no notes, no module entries, no "progress" language. The
    allowlist below (THERAPIST_ALLOWED_TABLES) is asserted by tests that
    record every query the branch makes — adding a read to the branch
    without adding it here fails the suite, and adding it here is a
    reviewable act. The briefing's ACTION phase is also suppressed for
    this vertical (outreach_restricted) — drafting re-engagement email to
    therapy clients on a timer is exactly what the autopilot job's
    "Admin only — never client outreach" promise forbids.
  * ministry / nonprofit — the branch reads contacts (counts only) and
    event_roster modules. It NEVER touches restricted_module_entries:
    giving lives behind restricted_modules.py's audited, owner-only
    endpoints, and a briefing query there would rightly be flagged in the
    access log. Attendance-ish proxies come from non-restricted data only.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("briefing_verticals")

# ─── tuning ──────────────────────────────────────────────────────────
DEADLINE_WINDOW_DAYS = 14      # "approaching" horizon for date_field items
DEADLINE_URGENT_DAYS = 7       # the sharper inner window, called out separately
STALE_DAYS = 21                # no movement (updated_at) in this long = stale
ESTIMATE_FOLLOWUP_DAYS = 7     # an estimate untouched this long needs a call
BALANCE_EXPIRY_DAYS = 30       # briefing surfaces a WIDER window than the
                               # sweep's 7-day warning — see note below
ROSTER_WINDOW_DAYS = 14        # upcoming occasions worth staffing now
MAX_NAMED = 5                  # named items per line before "and N more"
MAX_MODULES = 20
MAX_ENTRIES = 200

# The therapist branch may read THESE TABLES AND NO OTHERS. Scheduling and
# billing only — the tables any front desk already sees. Tests assert every
# query the branch issues resolves to this set.
THERAPIST_ALLOWED_TABLES = frozenset({"sessions", "invoices"})

# Ministry/nonprofit isolation: the giving table the community branch must
# never name. Tests assert on this constant AND on recorded queries.
RESTRICTED_TABLE = "restricted_module_entries"

# NOTE ON THE BALANCE SWEEP (PR #349): balance_sweep.py ALERTS — it writes
# chief_notifications at hit-zero / 1-left and for grants expiring within 7
# days, deduped by ledger row. This module SUMMARIZES — it renders text into
# the briefing body and writes NO notifications, so the two can never nag
# twice about the same grant. The briefing's 30-day expiry window is wider
# than the sweep's 7-day one on purpose: "expiring this month" is planning
# information, not an alarm.


# ─── small helpers ───────────────────────────────────────────────────

def _z(dt: datetime) -> str:
    """PostgREST timestamp class: the Z form, ALWAYS — isoformat's +00:00
    silently returns empty result sets in query strings (#196)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_day(v: Any) -> Optional[date]:
    """A date out of whatever a module entry holds — '2026-08-04',
    an ISO datetime, or junk (None)."""
    if not v or not isinstance(v, str):
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        pass
    try:
        return date.fromisoformat(v[:10])
    except (ValueError, TypeError):
        return None


def _days_since(iso_str: Optional[str]) -> Optional[int]:
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return (_now() - dt).days
    except (ValueError, TypeError):
        return None


def _fmt_day(d: date) -> str:
    return f"{d.strftime('%b')} {d.day}"


def _named(items: List[str]) -> str:
    """'A, B, C and 2 more' — bounded so a section never floods."""
    if len(items) <= MAX_NAMED:
        return ", ".join(items)
    return ", ".join(items[:MAX_NAMED]) + f" and {len(items) - MAX_NAMED} more"


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _section(key: str, heading: str, lines: List[str],
             tables: List[str], data: Dict[str, Any]) -> Dict[str, Any]:
    return {"key": key, "heading": heading, "lines": lines,
            "tables": tables, "data": data}


# ─── work_pipeline reading (G03 — matter trackers ARE pipelines) ─────

# Mirrors the frontend defaults (work_pipeline/types.ts DEFAULT_FIELDS /
# DEFAULT_STAGES) — an unconfigured module still reads honestly.
_DEFAULT_STAGE_IDS_DONE = {"done"}
_PIPELINE_DEFAULTS = {"stage_field": "stage", "title_field": "title",
                      "contact_field": "contact_id", "date_field": "due_date",
                      "value_field": "value"}


def _pipeline_params(raw: Any) -> Dict[str, Any]:
    p = raw if isinstance(raw, dict) else {}
    out = {k: (p.get(k) or v) for k, v in _PIPELINE_DEFAULTS.items()}
    stages = p.get("stages") if isinstance(p.get("stages"), list) else []
    stage_meta = [s for s in stages
                  if isinstance(s, dict) and s.get("id") and s.get("label")]
    out["stages"] = stage_meta
    out["done_ids"] = ({s["id"] for s in stage_meta if s.get("done")}
                       if stage_meta else set(_DEFAULT_STAGE_IDS_DONE))
    out["stage_labels"] = {s["id"]: s["label"] for s in stage_meta}
    return out


async def _pipeline_modules(sb, client, biz_id: str) -> List[Dict[str, Any]]:
    return await sb(client, "GET",
        f"/custom_modules?business_id=eq.{biz_id}&archetype=eq.work_pipeline"
        f"&is_active=eq.true&select=id,name,slug,archetype_params"
        f"&limit={MAX_MODULES}") or []


async def _module_entries(sb, client, module_id: str) -> List[Dict[str, Any]]:
    return await sb(client, "GET",
        f"/module_entries?module_id=eq.{module_id}&status=eq.active"
        f"&select=id,data,created_at,updated_at&limit={MAX_ENTRIES}") or []


async def _scan_pipelines(sb, client, biz_id: str) -> List[Dict[str, Any]]:
    """One summary dict per work_pipeline module: open items by stage,
    date_field items approaching / past due, stale items, open value.
    Every number is a count over real entries."""
    out: List[Dict[str, Any]] = []
    today = _now().date()
    for mod in await _pipeline_modules(sb, client, biz_id):
        params = _pipeline_params(mod.get("archetype_params"))
        entries = await _module_entries(sb, client, mod["id"])

        by_stage: Dict[str, int] = {}
        deadlines: List[Dict[str, Any]] = []
        overdue: List[Dict[str, Any]] = []
        stale: List[Dict[str, Any]] = []
        estimates_waiting: List[Dict[str, Any]] = []
        open_count = 0
        open_value = 0.0

        for e in entries:
            data = e.get("data") or {}
            stage = str(data.get(params["stage_field"]) or "") or "unstaged"
            if stage in params["done_ids"]:
                continue  # finished work is not briefing material
            open_count += 1
            label = params["stage_labels"].get(stage, stage)
            by_stage[label] = by_stage.get(label, 0) + 1
            open_value += _num(data.get(params["value_field"]))

            title = str(data.get(params["title_field"]) or "(untitled)")
            d = _parse_day(data.get(params["date_field"]))
            if d is not None:
                days = (d - today).days
                if days < 0:
                    overdue.append({"title": title, "date": d.isoformat(),
                                    "days_over": -days})
                elif days <= DEADLINE_WINDOW_DAYS:
                    deadlines.append({"title": title, "date": d.isoformat(),
                                      "days": days})

            idle = _days_since(e.get("updated_at") or e.get("created_at"))
            if idle is not None and idle >= STALE_DAYS:
                stale.append({"title": title, "days_idle": idle})
            if (re.search(r"estimate|quote|bid", f"{stage} {label}", re.I)
                    and idle is not None and idle >= ESTIMATE_FOLLOWUP_DAYS):
                estimates_waiting.append({"title": title, "days_idle": idle})

        deadlines.sort(key=lambda x: x["days"])
        overdue.sort(key=lambda x: -x["days_over"])
        stale.sort(key=lambda x: -x["days_idle"])
        out.append({
            "module": mod.get("name") or mod.get("slug") or "pipeline",
            "open_count": open_count, "by_stage": by_stage,
            "open_value": round(open_value, 2),
            "deadlines": deadlines,
            "deadlines_7d": sum(1 for d in deadlines
                                if d["days"] <= DEADLINE_URGENT_DAYS),
            "overdue": overdue, "stale": stale,
            "estimates_waiting": estimates_waiting,
        })
    return out


def _deadline_lines(scan: Dict[str, Any], noun: str) -> List[str]:
    lines: List[str] = []
    dl, od = scan["deadlines"], scan["overdue"]
    if dl:
        named = _named([f"{d['title']} ({_fmt_day(date.fromisoformat(d['date']))})"
                        for d in dl])
        urgent = (f" — {scan['deadlines_7d']} within 7 days"
                  if scan["deadlines_7d"] else "")
        lines.append(f"{len(dl)} deadline{'s' if len(dl) != 1 else ''} in the "
                     f"next {DEADLINE_WINDOW_DAYS} days{urgent}: {named}")
    if od:
        named = _named([f"{d['title']} ({d['days_over']}d over)" for d in od])
        lines.append(f"{len(od)} past due: {named}")
    if scan["stale"]:
        named = _named([f"{s['title']} ({s['days_idle']}d)"
                        for s in scan["stale"]])
        lines.append(f"{len(scan['stale'])} {noun}{'s' if len(scan['stale']) != 1 else ''} "
                     f"with no movement in {STALE_DAYS}+ days: {named}")
    return lines


def _stage_line(scan: Dict[str, Any], noun: str) -> Optional[str]:
    if not scan["open_count"]:
        return None
    parts = [f"{n} {label}" for label, n in
             sorted(scan["by_stage"].items(), key=lambda kv: -kv[1])]
    value = (f" (${scan['open_value']:,.0f} open value)"
             if scan["open_value"] > 0 else "")
    return (f"{scan['open_count']} open {noun}"
            f"{'s' if scan['open_count'] != 1 else ''} in "
            f"{scan['module']}{value}: {', '.join(parts)}")


# ─── shared money reads (service layer, not reimplemented) ───────────

def _unbilled_section(biz_id: str) -> Optional[Dict[str, Any]]:
    """billable_time's own unbilled_summary — the same numbers Chief's
    unbilled_time verb reports."""
    import billable_time
    s = billable_time.unbilled_summary(biz_id)
    if not s.get("entries"):
        return None
    line = (f"{s['entries']} unbilled time entr"
            f"{'y' if s['entries'] == 1 else 'ies'} totalling {s['hours']}")
    if s.get("amount"):
        line += f" (${s['amount']:,.2f} at recorded rates)"
    if s.get("unpriced_entries"):
        line += f"; {s['unpriced_entries']} without a rate set"
    return _section("unbilled_time", "Unbilled time", [line],
                    ["time_entries"], s)


async def _retainer_section(sb, client, biz_id: str,
                            heading: str) -> Optional[Dict[str, Any]]:
    """Positive retainer balances from the customer_balances VIEW (the
    derived ledger view — there is no stored total to drift), lowest
    first so the ones running out lead."""
    rows = await sb(client, "GET",
        f"/customer_balances?business_id=eq.{biz_id}&kind=eq.retainer"
        f"&select=contact_id,unit,balance&limit=100") or []
    positive = [r for r in rows if _num(r.get("balance")) > 0]
    if not positive:
        return None
    names = await _contact_names(sb, client, biz_id,
                                 [str(r.get("contact_id")) for r in positive])
    positive.sort(key=lambda r: _num(r.get("balance")))
    described = []
    for r in positive:
        bal = _num(r.get("balance"))
        unit = str(r.get("unit") or "")
        amt = f"${bal:,.2f}" if unit == "money" else f"{bal:g} {unit}{'s' if bal != 1 else ''}"
        described.append(f"{names.get(str(r.get('contact_id')), 'A client')}: {amt}")
    line = (f"{len(positive)} client{'s' if len(positive) != 1 else ''} "
            f"holding retainer balance — lowest first: {_named(described)}")
    return _section("retainers", heading, [line],
                    ["customer_balances", "contacts"],
                    {"count": len(positive),
                     "balances": [{"contact_id": r.get("contact_id"),
                                   "unit": r.get("unit"),
                                   "balance": _num(r.get("balance"))}
                                  for r in positive]})


async def _contact_names(sb, client, biz_id: str,
                         ids: List[str]) -> Dict[str, str]:
    ids = [i for i in dict.fromkeys(ids) if i and i != "None"][:50]
    if not ids:
        return {}
    rows = await sb(client, "GET",
        f"/contacts?business_id=eq.{biz_id}&id=in.({','.join(ids)})"
        f"&select=id,name&limit=50") or []
    return {str(r["id"]): r.get("name") or "A contact" for r in rows}


def _expiring_balances_section(grants: List[Dict[str, Any]],
                               names: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """Grants lapsing within 30 days — the rows come from
    customer_balances.expiring_soon (the service layer shipped with the
    ledger; read, not reimplemented). Summary only: the sweep owns
    notifications (see module docstring)."""
    if not grants:
        return None
    described = []
    for g in grants[:MAX_NAMED + 3]:
        who = names.get(str(g.get("contact_id")), "A client")
        unit = str(g.get("unit") or "")
        delta = _num(g.get("delta"))
        amt = f"${delta:,.2f}" if unit == "money" else f"{delta:g} {unit}{'s' if delta != 1 else ''}"
        when = str(g.get("expires_at") or "")[:10]
        described.append(f"{who}: {g.get('kind', '').replace('_', ' ')} of {amt} lapses {when}")
    line = (f"{len(grants)} prepaid grant{'s' if len(grants) != 1 else ''} "
            f"expiring within {BALANCE_EXPIRY_DAYS} days: {_named(described)}")
    return _section("expiring_balances", "Balances expiring soon", [line],
                    ["customer_ledger"],
                    {"count": len(grants),
                     "grants": [{"contact_id": g.get("contact_id"),
                                 "kind": g.get("kind"), "unit": g.get("unit"),
                                 "delta": _num(g.get("delta")),
                                 "expires_at": g.get("expires_at")}
                                for g in grants]})


# ─── the branches ────────────────────────────────────────────────────

async def _lawyer(sb, client, biz: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Matters + deadlines + trust/retainer balances + unbilled time —
    the autopilot label 'Matter and deadline sweep' made true."""
    biz_id = biz["id"]
    sections: List[Dict[str, Any]] = []
    for scan in await _scan_pipelines(sb, client, biz_id):
        lines = _deadline_lines(scan, "matter")
        stage = _stage_line(scan, "matter")
        if stage:
            lines.insert(0, stage)
        if lines:
            sections.append(_section(
                "matters", f"Matters & deadlines — {scan['module']}", lines,
                ["custom_modules", "module_entries"], scan))
    ret = await _retainer_section(sb, client, biz_id, "Trust & retainer balances")
    if ret:
        sections.append(ret)
    ub = _unbilled_section(biz_id)
    if ub:
        sections.append(ub)
    return sections


async def _consultant(sb, client, biz: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Engagement review: stale engagements, milestone dates, retainers
    running down, unbilled time."""
    biz_id = biz["id"]
    sections: List[Dict[str, Any]] = []
    for scan in await _scan_pipelines(sb, client, biz_id):
        lines = _deadline_lines(scan, "engagement")
        stage = _stage_line(scan, "engagement")
        if stage:
            lines.insert(0, stage)
        if lines:
            sections.append(_section(
                "engagements", f"Engagements — {scan['module']}", lines,
                ["custom_modules", "module_entries"], scan))
    ret = await _retainer_section(sb, client, biz_id, "Retainer balances")
    if ret:
        sections.append(ret)
    ub = _unbilled_section(biz_id)
    if ub:
        sections.append(ub)
    return sections


async def _creative(sb, client, biz: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Project review: live projects by stage, due dates approaching,
    projects that have stalled."""
    sections: List[Dict[str, Any]] = []
    for scan in await _scan_pipelines(sb, client, biz["id"]):
        lines = _deadline_lines(scan, "project")
        stage = _stage_line(scan, "project")
        if stage:
            lines.insert(0, stage)
        if lines:
            sections.append(_section(
                "projects", f"Projects — {scan['module']}", lines,
                ["custom_modules", "module_entries"], scan))
    return sections


async def _therapist(sb, client, biz: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Practice review — ADMIN ONLY, by law (vertical_registry HIPAA
    posture, vertical_scope). Reads /sessions and /invoices and NOTHING
    else — see THERAPIST_ALLOWED_TABLES and the tests that record every
    query this branch makes. Schedule density, cancellations, upcoming
    session count, unpaid invoices. No clinical content, no session
    notes, no client-progress language — ever."""
    biz_id = biz["id"]
    now = _now()
    week_ago, two_weeks_ago = now - timedelta(days=7), now - timedelta(days=14)
    week_ahead = now + timedelta(days=7)

    this_week = await sb(client, "GET",
        f"/sessions?business_id=eq.{biz_id}"
        f"&scheduled_for=gte.{_z(week_ago)}&scheduled_for=lt.{_z(now)}"
        f"&select=id,status&limit=500") or []
    last_week = await sb(client, "GET",
        f"/sessions?business_id=eq.{biz_id}"
        f"&scheduled_for=gte.{_z(two_weeks_ago)}&scheduled_for=lt.{_z(week_ago)}"
        f"&select=id,status&limit=500") or []
    upcoming = await sb(client, "GET",
        f"/sessions?business_id=eq.{biz_id}&status=eq.scheduled"
        f"&scheduled_for=gte.{_z(now)}&scheduled_for=lte.{_z(week_ahead)}"
        f"&select=id&limit=500") or []
    unpaid = await sb(client, "GET",
        f"/invoices?business_id=eq.{biz_id}&status=in.(sent,viewed)"
        f"&select=id,total,due_date&limit=200") or []

    cancelled = sum(1 for s in this_week if s.get("status") == "cancelled")
    today = now.date()
    overdue = [i for i in unpaid
               if (_parse_day(i.get("due_date")) or today) < today]
    unpaid_total = round(sum(_num(i.get("total")) for i in unpaid), 2)

    if not this_week and not last_week and not upcoming and not unpaid:
        return []  # a practice with no schedule and no billing: stay generic

    lines = [
        f"Schedule density: {len(this_week)} session"
        f"{'s' if len(this_week) != 1 else ''} this week vs "
        f"{len(last_week)} last week"
        + (f" ({cancelled} cancelled this week)" if cancelled else ""),
        f"{len(upcoming)} session{'s' if len(upcoming) != 1 else ''} "
        f"on the book for the next 7 days",
    ]
    if unpaid:
        line = (f"{len(unpaid)} unpaid invoice"
                f"{'s' if len(unpaid) != 1 else ''} outstanding "
                f"(${unpaid_total:,.2f})")
        if overdue:
            line += f", {len(overdue)} past due"
        lines.append(line)
    lines.append("This practice review reads scheduling and billing only "
                 "(sessions, invoices) — never clinical content.")
    return [_section("practice_review", "Practice review (admin only)", lines,
                     sorted(THERAPIST_ALLOWED_TABLES),
                     {"sessions_this_week": len(this_week),
                      "sessions_last_week": len(last_week),
                      "cancelled_this_week": cancelled,
                      "sessions_upcoming_7d": len(upcoming),
                      "unpaid_invoices": len(unpaid),
                      "unpaid_total": unpaid_total,
                      "unpaid_overdue": len(overdue)})]


async def _packages(sb, client, biz: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Coach / fitness / course_creator / financial_educator — nurture
    verticals whose briefings run when the practitioner asks. Package
    balances outstanding + grants expiring within 30 days (the sweep
    alerts at hit-zero and 7-day expiry; this summarizes the month)."""
    import customer_balances as cb
    biz_id = biz["id"]
    sections: List[Dict[str, Any]] = []

    rows = await sb(client, "GET",
        f"/customer_balances?business_id=eq.{biz_id}&kind=eq.package"
        f"&select=contact_id,unit,balance&limit=100") or []
    positive = [r for r in rows if _num(r.get("balance")) > 0]
    grants = cb.expiring_soon(biz_id, within_days=BALANCE_EXPIRY_DAYS) or []
    names = await _contact_names(
        sb, client, biz_id,
        [str(r.get("contact_id")) for r in positive]
        + [str(g.get("contact_id")) for g in grants])
    if positive:
        positive.sort(key=lambda r: _num(r.get("balance")))
        low = [r for r in positive
               if _num(r.get("balance")) <= 1 and r.get("unit") == "session"]
        described = []
        for r in positive[:MAX_NAMED + 3]:
            bal = _num(r.get("balance"))
            unit = str(r.get("unit") or "")
            amt = f"${bal:,.2f}" if unit == "money" else f"{bal:g} {unit}{'s' if bal != 1 else ''}"
            described.append(f"{names.get(str(r.get('contact_id')), 'A client')}: {amt} left")
        lines = [f"{len(positive)} client{'s' if len(positive) != 1 else ''} "
                 f"holding package balance — lowest first: {_named(described)}"]
        if low:
            lines.append(f"{len(low)} down to their last session — "
                         f"renewal conversations worth having")
        sections.append(_section(
            "package_balances", "Package balances", lines,
            ["customer_balances", "contacts"],
            {"count": len(positive), "low_count": len(low),
             "balances": [{"contact_id": r.get("contact_id"),
                           "unit": r.get("unit"),
                           "balance": _num(r.get("balance"))}
                          for r in positive]}))

    exp = _expiring_balances_section(grants, names)
    if exp:
        sections.append(exp)
    return sections


async def _community(sb, client, biz: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Ministry / nonprofit — attendance-ish proxies from NON-RESTRICTED
    data only: contact growth + event_roster occasions with unfilled
    roles. Giving is behind restricted_modules.py (audited, owner-only)
    and is deliberately never read here — see RESTRICTED_TABLE."""
    biz_id = biz["id"]
    now = _now()
    sections: List[Dict[str, Any]] = []

    week_ago, two_weeks_ago = now - timedelta(days=7), now - timedelta(days=14)
    recent = await sb(client, "GET",
        f"/contacts?business_id=eq.{biz_id}&created_at=gte.{_z(week_ago)}"
        f"&select=id&limit=200") or []
    prior = await sb(client, "GET",
        f"/contacts?business_id=eq.{biz_id}&created_at=gte.{_z(two_weeks_ago)}"
        f"&created_at=lt.{_z(week_ago)}&select=id&limit=200") or []
    if recent or prior:
        sections.append(_section(
            "community_growth", "Community growth",
            [f"{len(recent)} new "
             f"{'person' if len(recent) == 1 else 'people'} added this week "
             f"vs {len(prior)} the week before"],
            ["contacts"],
            {"new_this_week": len(recent), "new_prior_week": len(prior)}))

    # event_roster occasions in the next 14 days with roles still unfilled.
    roster_mods = await sb(client, "GET",
        f"/custom_modules?business_id=eq.{biz_id}&archetype=eq.event_roster"
        f"&is_active=eq.true&select=id,name,slug,archetype_params"
        f"&limit={MAX_MODULES}") or []
    today = now.date()
    gaps: List[str] = []
    gap_data: List[Dict[str, Any]] = []
    for mod in roster_mods:
        p = mod.get("archetype_params") or {}
        title_f = p.get("title_field") or "title"
        date_f = p.get("date_field") or "date"
        signups_f = p.get("signups_field") or "signups"
        roles = [r for r in (p.get("roles") or [])
                 if isinstance(r, dict) and r.get("id")]
        if not roles:
            continue  # headcount-only RSVP modules have no roles to fill
        for e in await _module_entries(sb, client, mod["id"]):
            data = e.get("data") or {}
            d = _parse_day(data.get(date_f))
            if d is None or d < today or (d - today).days > ROSTER_WINDOW_DAYS:
                continue
            signups = data.get(signups_f)
            signups = signups if isinstance(signups, list) else []
            unfilled = []
            for role in roles:
                needed = max(1, int(role.get("needed") or 1))
                filled = sum(
                    1 for s in signups
                    if isinstance(s, dict) and s.get("role") == role["id"]
                    and (s.get("status") or "yes") == "yes")
                if filled < needed:
                    unfilled.append(f"{role.get('label') or role['id']} "
                                    f"needs {needed - filled} more")
            if unfilled:
                title = str(data.get(title_f) or "(untitled)")
                gaps.append(f"{title} ({_fmt_day(d)}): {'; '.join(unfilled)}")
                gap_data.append({"title": title, "date": d.isoformat(),
                                 "unfilled": unfilled})
    if gaps:
        sections.append(_section(
            "roster_gaps", "Upcoming events needing volunteers",
            [f"{len(gaps)} occasion{'s' if len(gaps) != 1 else ''} in the "
             f"next {ROSTER_WINDOW_DAYS} days with unfilled roles:"] + gaps[:8],
            ["custom_modules", "module_entries"],
            {"count": len(gaps), "occasions": gap_data}))
    return sections


async def _jobs(sb, client, biz: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Contractor / personal_services — nurture stays their primary
    autopilot; when a briefing IS run, it reads the job board: jobs by
    stage, dates approaching, and estimates sitting unanswered (the
    trade's classic leak — quoted work nobody called back about)."""
    sections: List[Dict[str, Any]] = []
    for scan in await _scan_pipelines(sb, client, biz["id"]):
        lines = []
        stage = _stage_line(scan, "job")
        if stage:
            lines.append(stage)
        lines += _deadline_lines(scan, "job")
        if scan["estimates_waiting"]:
            named = _named([f"{x['title']} ({x['days_idle']}d)"
                            for x in scan["estimates_waiting"]])
            n = len(scan["estimates_waiting"])
            lines.append(f"{n} estimate{'s' if n != 1 else ''} outstanding "
                         f"{ESTIMATE_FOLLOWUP_DAYS}+ days without follow-up: "
                         f"{named}")
        if lines:
            sections.append(_section(
                "jobs", f"Jobs — {scan['module']}", lines,
                ["custom_modules", "module_entries"], scan))
    return sections


_BRANCHES = {
    "lawyer": _lawyer,
    "consultant": _consultant,
    "creative": _creative,
    "therapist": _therapist,
    "coach": _packages,
    "fitness_wellness": _packages,
    "course_creator": _packages,
    "financial_educator": _packages,
    "ministry": _community,
    "nonprofit": _community,
    "contractor": _jobs,
    "personal_services": _jobs,
    # service_provider + custom: deliberately generic (vertical_registry
    # KNOWN_GAPS) — no branch, no fabricated sections.
}


def resolve_vertical(business_type: Optional[str]) -> str:
    try:
        import vertical_registry
        return vertical_registry.resolve(business_type)
    except Exception:
        return "custom"


def outreach_restricted(business_type: Optional[str]) -> bool:
    """True when the briefing's action phase must NOT draft client
    outreach. Therapist is admin-only by the same ruling that keeps its
    autopilot on the briefing instead of nurture — drafting check-ins to
    therapy clients on a timer breaks the 'never client outreach'
    promise the practitioner was shown."""
    return resolve_vertical(business_type) == "therapist"


async def gather(sb, client, biz: Dict[str, Any]) -> Dict[str, Any]:
    """The vertical block for one business's briefing. Never raises —
    a failed vertical read degrades to the generic briefing, it does not
    take the whole briefing down."""
    vertical = resolve_vertical(biz.get("type"))
    branch = _BRANCHES.get(vertical)
    if branch is None:
        return {"vertical": vertical, "sections": [], "tables_read": []}
    try:
        sections = [s for s in await branch(sb, client, biz) if s]
    except Exception as e:
        logger.warning(f"[briefing_verticals] {vertical} branch failed "
                       f"for {biz.get('id')}: {e}")
        sections = []
    tables = sorted({t for s in sections for t in s.get("tables", [])})
    return {"vertical": vertical, "sections": sections, "tables_read": tables}


# ─── rendering ───────────────────────────────────────────────────────

def format_for_ai(vstats: Optional[Dict[str, Any]]) -> str:
    """The block appended to the briefing prompt's data payload. The
    numbers here are query results; the prompt instructs the model to
    repeat them exactly and never derive new ones."""
    if not vstats or not vstats.get("sections"):
        return ""
    lines = [f"VERTICAL SECTIONS ({vstats['vertical']}) — precomputed from "
             "real queries. Repeat these numbers EXACTLY if you reference "
             "them; never compute, extrapolate or invent numbers:"]
    for s in vstats["sections"]:
        lines.append(f"[{s['heading']}]")
        lines += [f"  - {ln}" for ln in s["lines"]]
    return "\n".join(lines)


def format_markdown(vstats: Optional[Dict[str, Any]]) -> str:
    """The deterministic markdown appended to the stored briefing body —
    same pattern as the actions section: the letter is the model's, the
    numbers are ours. Returns '' when there is nothing to show."""
    if not vstats or not vstats.get("sections"):
        return ""
    blocks: List[str] = []
    for s in vstats["sections"]:
        blocks.append(f"## {s['heading']}")
        blocks += [f"- {ln}" for ln in s["lines"]]
        blocks.append("")
    return "\n".join(blocks).rstrip()
