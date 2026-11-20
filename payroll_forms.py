"""payroll_forms.py — the quarter's and the year's worksheets (Payroll, the free version, 2026-11-19).

Solutionist fills in every number from the pay runs; the church or its
accountant files. NOTHING here files anything, and nothing here draws an
official IRS or Social Security form or anything shaped like one (the rule
at the top of irs_forms.py: a facsimile is a step toward manufacturing
official paper). The PDFs and the CSV are worksheets: plain tables of the
numbers, each saying "For you or your accountant to file. Solutionist
doesn't file." W-2s and the W-3 are filed free on SSA Business Services
Online; the 941 through IRS e-file or by mail; 1099-NEC through IRS IRIS.

THE RULES ENCODED HERE (each cited where it is used):
  * Form 941 line 2 is wages, tips and other compensation: the W-2 Box 1
    figure, so a minister's housing allowance is left out (IRC 107; IRS
    Publication 517) and a minister's other pay is in
  * lines 5a and 5c are Social Security and Medicare wages; a minister's
    pay is neither (IRC 3121(b)(8)), so ministers are left out of both
    (Instructions for Form 941, lines 5a and 5c); 12.4% and 2.9% are both
    halves (6.2% and 1.45% each side, IRS Publication 15, "Social security
    and Medicare taxes"); Social Security wages stop at the year's wage
    base (payroll_calc.ss_wage_base)
  * line 5d: Additional Medicare Tax withholding, 0.9% of a person's wages
    over $200,000 in the year (Publication 15, "Additional Medicare Tax
    withholding")
  * W-2 Box 1 leaves out the housing allowance, which shows in Box 14
    (Publication 517, "Members of the Clergy"); a minister's Boxes 3 to 6
    are blank (General Instructions for Forms W-2 and W-3, "Clergy and
    religious workers"); only housing the board designated IN ADVANCE is
    left out (Treas. Reg. 1.107-1(b)): housing paid before the vote, past the
    year's designated amount, or with no designation at all is wages in Box
    1 and on 941 line 2, and Box 14 shows only what is left out
  * a church owes no FUTA (IRC 3306(c)(8)), so there is no Form 940 here
  * 1099-NEC: each contractor paid $2,000 or more for payments made in 2026
    and later, $600 before (Instructions for Forms 1099-MISC and 1099-NEC,
    2026)

Logs carry ids and counts only: never a name or an amount.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import payroll_calc
import payroll_calendar as pcal
import sb_clients

logger = logging.getLogger("payroll_forms")

SS_RATE_BOTH = 0.124          # 6.2% employee + 6.2% employer (Publication 15)
MEDICARE_RATE_BOTH = 0.029    # 1.45% + 1.45%
ADDITIONAL_RATE = payroll_calc.ADDITIONAL_MEDICARE_RATE
ADDITIONAL_OVER = payroll_calc.ADDITIONAL_MEDICARE_THRESHOLD
FILE_IT = "For you or your accountant to file. Solutionist doesn’t file."
NOT_A_FORM = ("WORKSHEET ONLY. This is not a W-2, a W-3, a Form 941, a 1099 or any other IRS or Social Security "
              "form.")
WHERE_TO_FILE = [
    "W-2s and the W-3: free on Social Security’s Business Services Online (ssa.gov/bso).",
    "Form 941: through IRS e-file, or by mail to the address in the Form 941 instructions.",
    "1099-NEC: through the IRS Information Returns Intake System, IRIS (irs.gov/iris).",
]


class Unavailable(Exception):
    """A read the worksheet needs failed: never shown as a worksheet of zeros."""


HOUSING_503 = "The housing allowance records couldn't be read. Try again shortly."


class HousingUnreadable(Unavailable):
    """The housing allowance records couldn't be read: never shown as "not
    designated" (that would move the housing into Box 1 with a confident,
    wrong number). The doors answer 503 with HOUSING_503."""


def nec_threshold(year: int) -> float:
    """The 1099-NEC line: $2,000 for payments made in 2026 and later, $600
    before (Instructions for Forms 1099-MISC and 1099-NEC, 2026). One shared
    helper, form_1099.nec_threshold, so every 1099 surface says the same."""
    import form_1099
    return form_1099.nec_threshold(year)


HOUSING_RULE = "Treas. Reg. 1.107-1(b)"


def _r(x: Any) -> float:
    try:
        return payroll_calc._r(float(x or 0))
    except (TypeError, ValueError):
        return 0.0


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _day(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


def _name(e: Dict[str, Any]) -> str:
    return f"{e.get('first_name') or ''} {e.get('last_name') or ''}".strip() or "Someone"


# ─── What a worksheet reads ───────────────────────────────────────────

def load(biz_row: Dict[str, Any], year: int, statuses: Tuple[str, ...]) -> Dict[str, Any]:
    """The year's runs, the lines on runs in `statuses`, the people, their
    tax profiles (never the SSN's ciphertext) and the deposits marked sent."""
    import church_follow_up
    import payroll_deposits
    biz = str(biz_row["id"])
    b = _q(biz)
    try:
        runs = sb_clients.sb_get_all_as_service(
            f"/pay_runs?business_id=eq.{b}&status=neq.cancelled&pay_date=gte.{year}-01-01"
            f"&pay_date=lte.{year}-12-31&select=id,status,pay_date,period_start,period_end,totals", strict=True) or []
    except sb_clients.PartialRead:
        raise Unavailable("pay_runs")
    counted = {str(r["id"]): r for r in runs if r.get("status") in statuses}
    items: List[Dict[str, Any]] = []
    ids = sorted(counted)
    for n in range(0, len(ids), 60):
        chunk = ",".join(_q(i) for i in ids[n:n + 60])
        try:
            items += sb_clients.sb_get_all_as_service(
                f"/pay_run_items?business_id=eq.{b}&pay_run_id=in.({chunk})&select=*", strict=True) or []
        except sb_clients.PartialRead:
            raise Unavailable("pay_run_items")
    emps = sb_clients.sb_get_as_service(f"/employees?business_id=eq.{b}&select=*&limit=1000")
    profiles = sb_clients.sb_get_as_service(
        f"/employee_tax_profiles?business_id=eq.{b}&select=employee_id,ssn_last4,address,w4_signed_at&limit=1000")
    latest = sb_clients.sb_get_as_service(
        f"/pay_runs?business_id=eq.{b}&status=neq.cancelled&select=id,pay_date&order=pay_date.desc&limit=1")
    if not isinstance(emps, list) or not isinstance(profiles, list) or not isinstance(latest, list):
        raise Unavailable("employees")
    marked, ready = payroll_deposits.marked(biz)
    if marked is None:
        raise Unavailable("payroll_deposits")
    for i in items:
        run = counted.get(str(i.get("pay_run_id"))) or {}
        i["_pay_date"] = str(run.get("pay_date") or "")[:10]
        i["_status"] = run.get("status")
    items.sort(key=lambda i: (i["_pay_date"], str(i.get("created_at") or ""), str(i.get("id"))))
    return {"biz": biz_row, "year": year, "runs": runs, "items": items,
            "emps": {str(e["id"]): e for e in emps}, "profiles": {str(p["employee_id"]): p for p in profiles},
            "church": church_follow_up.is_church(biz_row), "marked": marked, "deposits_ready": ready,
            "latest": _day(latest[0].get("pay_date")) if latest else None,
            "frequencies": [e.get("pay_frequency") for e in emps if e.get("status") == "active"],
            "settings": pcal.settings_of(biz_row), "housing": {}}


def _housing_record(ctx: Dict[str, Any], emp: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    """(the minister's housing allowance record for the year, or None; and
    which it is): "found"; "none" (no record: nothing designated in
    advance); "ambiguous" (more than one record could be theirs: can't
    tell); "off" (the records aren't switched on for this church: can't
    tell). A read that FAILS raises HousingUnreadable: it is never "none"."""
    eid = str(emp.get("id"))
    if eid in ctx["housing"]:
        return ctx["housing"][eid]
    import housing_allowance as ha
    import payroll_router
    biz = str(ctx["biz"]["id"])
    try:
        on = ha.switched_on(biz)
        if not on:
            out: Tuple[Optional[Dict[str, Any]], str] = (None, "off")
        else:
            rec, kind, _why = payroll_router._housing_match(biz, ctx["year"], emp)
            out = (rec, kind)
    except Exception as e:  # noqa: BLE001 — never a confident wrong number: the door says try again
        logger.warning("[payroll] housing records unread biz=%s: %s", biz[:8], type(e).__name__)
        raise HousingUnreadable("minister_housing_allowances")
    ctx["housing"][eid] = out
    return out


# ─── One person's year, line by line ──────────────────────────────────

def _exempt(item: Dict[str, Any]) -> bool:
    """A line taxed as a minister's: pay but no Medicare, either half.
    Medicare has no wage base, so any other line with pay carries some
    (payroll_calc.statutory); this reads how the line WAS taxed, so a
    person who became a minister mid-year is counted right on both sides."""
    gross = _r(item.get("gross"))
    # A check so small its Medicare rounds to nothing isn't a minister's.
    return (gross > 0 and _r(gross * payroll_calc.MEDICARE_RATE) > 0
            and not _r(item.get("medicare_employee")) and not _r(item.get("employer_medicare")))


def person_lines(ctx: Dict[str, Any], emp: Dict[str, Any], items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Each of a person's lines (in pay-date order) with the figures the
    forms need: Box 1 wages, Social Security and Medicare wages (the wage
    base and the $200,000 line measured across the year), the housing part
    left out, and the line's tax liability for the 941's months.

    The housing part is left out of Box 1 only as far as the board
    designated it IN ADVANCE (Treas. Reg. 1.107-1(b); IRS Publication 517):
    housing paid before the vote, housing past the year's designated amount
    (counted in pay-date order), and all of it when no designation is on
    file are wages. With the housing allowance records not switched on for
    the church, or more than one record that could be theirs, nothing can be
    checked, so the housing is left out as before and the worksheet says so.
    A read that fails raises HousingUnreadable (the door's 503)."""
    base = payroll_calc.ss_wage_base(ctx["year"])
    minister = payroll_calc.is_minister(emp, ctx["church"])
    rec, state = None, "none"
    if minister or any(_r(i.get("housing_allowance")) for i in items):
        rec, state = _housing_record(ctx, emp)
    unchecked_why = state if state in ("off", "ambiguous") else None
    voted = _day(rec.get("designated_on")) if rec else None
    cap = None if not rec or rec.get("designated_amount") in (None, "") else _r(rec.get("designated_amount"))
    fica_before = 0.0
    out = []
    for i in items:
        pd = _day(i.get("_pay_date"))
        gross, housing = _r(i.get("gross")), min(_r(i.get("housing_allowance")), _r(i.get("gross")))
        exempt = _exempt(i)
        early = over = undesignated = 0.0
        excluded = 0.0
        if housing and (exempt or minister):
            if unchecked_why:
                excluded = housing                    # can't be checked here: left out, and said so
            elif rec is None:
                undesignated = housing                # nothing designated in advance: wages
            elif voted and pd and pd < voted:
                early = housing                       # paid before the board's vote: wages
            elif cap is None:
                excluded = housing
            else:
                excluded = _r(min(housing, cap))      # up to what the board designated for the year
                cap = _r(cap - excluded)
                over = _r(housing - excluded)         # past it: wages
        if exempt:
            ss_w = med_w = add_w = 0.0
        else:
            ss_w = _r(max(0.0, min(gross, base - fica_before)))
            med_w = gross
            add_w = _r(max(0.0, fica_before + gross - ADDITIONAL_OVER) - max(0.0, fica_before - ADDITIONAL_OVER))
            fica_before += gross
        liability = _r(_r(i.get("federal_withholding")) + _r(i.get("social_security_employee"))
                       + _r(i.get("employer_social_security")) + _r(i.get("medicare_employee"))
                       + _r(i.get("employer_medicare")))
        out.append({"pay_date": pd, "item": i, "box1": _r(gross - excluded), "housing_excluded": excluded,
                    "housing_early": early, "housing_over": over, "housing_undesignated": undesignated,
                    "housing_unchecked": excluded if unchecked_why else 0.0, "housing_unchecked_why": unchecked_why,
                    "fit": _r(i.get("federal_withholding")),
                    "sit": _r(i.get("state_withholding")), "exempt": exempt, "ss_wages": ss_w, "med_wages": med_w,
                    "add_wages": add_w, "ss_tax": _r(i.get("social_security_employee")),
                    "med_tax": _r(i.get("medicare_employee")), "liability": liability, "gross": gross})
    return out


def _by_person(ctx: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for i in ctx["items"]:
        out.setdefault(str(i.get("employee_id")), []).append(i)
    return {eid: person_lines(ctx, ctx["emps"].get(eid) or {"id": eid}, its) for eid, its in out.items()}


def _projection(ctx: Dict[str, Any], until: date, today: date) -> List[date]:
    stop = min(until, pcal.add_months(today, pcal.PROJECT_MONTHS))
    taken = [_day(r.get("pay_date")) for r in ctx["runs"]]
    return [d for d in pcal.projected_paydays(ctx["latest"], ctx["frequencies"], stop, [t for t in taken if t])
            if d >= today]


def _sent_in(marked: Dict[str, Dict[str, Any]], first: date, last: date) -> List[Dict[str, Any]]:
    """The federal deposits marked sent whose period falls first..last."""
    out = []
    for key, row in sorted(marked.items()):
        p = pcal.parse_key(key)
        if not p or p["kind"] != "federal":
            continue
        on = p["pay_date"] if p["schedule"] == pcal.SEMIWEEKLY else date(p["year"], p["month"], 1)
        if first <= on <= last:
            out.append({"key": key, "period": p["period"], "amount": _r(row.get("amount")),
                        "sent_on": row.get("sent_on")})
    return out


# ─── The quarter: Form 941's numbers ──────────────────────────────────

def quarter(biz_row: Dict[str, Any], year: int, q: int, today: Optional[date] = None) -> Dict[str, Any]:
    """GET /payroll/forms/quarter's answer. Paid runs only; the year's lines
    before the quarter are read so the wage base and the $200,000 line land
    where they really did."""
    today = today or date.today()
    ctx = load(biz_row, year, ("paid",))
    first = date(year, 3 * q - 2, 1)
    last = pcal.form_941_raw(year, q).replace(day=1) - timedelta(days=1)

    def inside(v: Any) -> bool:
        d = _day(v)
        return bool(d and first <= d <= last)

    lines = [ln for lns in _by_person(ctx).values() for ln in lns if inside(ln["pay_date"])]
    l2 = _r(sum(ln["box1"] for ln in lines))
    l3 = _r(sum(ln["fit"] for ln in lines))
    a_w = _r(sum(ln["ss_wages"] for ln in lines))
    c_w = _r(sum(ln["med_wages"] for ln in lines))
    d_w = _r(sum(ln["add_wages"] for ln in lines))
    a_t, c_t, d_t = _r(a_w * SS_RATE_BOTH), _r(c_w * MEDICARE_RATE_BOTH), _r(d_w * ADDITIONAL_RATE)
    l6 = _r(l3 + a_t + c_t + d_t)
    months = [0.0, 0.0, 0.0]
    for ln in lines:
        months[ln["pay_date"].month - first.month] = _r(months[ln["pay_date"].month - first.month] + ln["liability"])
    total = _r(sum(months))
    real = [r for r in ctx["runs"] if inside(r.get("pay_date"))]
    paid_runs = [r for r in real if r.get("status") == "paid"]
    ahead = [d for d in _projection(ctx, last, today) if first <= d <= last]
    expected = (len(real) + len(ahead)) if (real or ahead) else None
    sent = _sent_in(ctx["marked"], first, last)
    notes = []
    if abs(_r(total - l6)) > 1.0:
        notes.append(f"What was withheld and owed differs from the rates by {pcal.money(abs(_r(total - l6)))}. "
                     "Ask your accountant before filing.")
    if any(ln["exempt"] for ln in lines):
        notes.append("Ministers aren’t in lines 5a and 5c: their pay isn’t Social Security or Medicare wages.")
    moved = _r(sum(ln["housing_early"] + ln["housing_over"] + ln["housing_undesignated"] for ln in lines))
    if moved:
        why = [w for w, k in (("paid before the board’s vote", "housing_early"),
                              ("more than the board designated for the year", "housing_over"),
                              ("not designated in advance", "housing_undesignated"))
               if any(ln[k] for ln in lines)]
        notes.append(f"{pcal.money(moved)} of housing paid this quarter is counted as wages on line 2: it was "
                     f"{' or '.join(why)} ({HOUSING_RULE}).")
    unchecked = _r(sum(ln["housing_unchecked"] for ln in lines))
    if unchecked:
        whys = {ln["housing_unchecked_why"] for ln in lines if ln["housing_unchecked"]}
        reasons = [w for w, k in (("the housing allowance records aren’t switched on here", "off"),
                                  ("more than one housing allowance record could be the minister’s", "ambiguous"))
                   if k in whys]
        notes.append(f"{pcal.money(unchecked)} of housing paid this quarter is left out of line 2 without being "
                     f"checked: {' and '.join(reasons)}. If the board didn’t designate it in advance, it is wages "
                     f"({HOUSING_RULE}).")
    due = pcal.form_941_due(year, q)
    return {
        "ok": True, "year": year, "q": q, "due": due.isoformat(),
        "runs_in": len(paid_runs), "runs_expected": expected,
        "lines": {"2": l2, "3": l3, "5a_wages": a_w, "5a_tax": a_t, "5c_wages": c_w, "5c_tax": c_t,
                  "5d_wages": d_w, "5d_tax": d_t, "6": l6, "7": _r(total - l6), "12": total},
        "months": months,
        "deposited": _r(sum(s["amount"] for s in sent)),
        "deposits": sent,
        "schedule": ctx["settings"]["deposit_schedule"],
        "quarter_words": pcal.QUARTER_WORDS[q],
        "notes": notes,
        "deposits_ready": ctx["deposits_ready"],
        "file_it": FILE_IT,
    }


# ─── The year: W-2s, the W-3, 1099-NEC ────────────────────────────────

def _address_ok(p: Dict[str, Any]) -> bool:
    a = p.get("address") if isinstance(p.get("address"), dict) else {}
    return all(str(a.get(k) or "").strip() for k in ("line1", "city", "state", "zip"))


def _contractors(biz: str, year: int) -> List[Dict[str, Any]]:
    """Each contractor the church files a 1099-NEC for, chosen exactly as
    the 1099 drafts choose them (reports_router.drafts_1099): from the 1099
    summary (paid 1099-eligible bills), at or above the year's line, and not
    Stripe-managed (Stripe Tax Reporting files those). With whether a W-9 is
    on file (its last four)."""
    import reports_router
    try:
        summary = reports_router._summary_1099(biz, year)
    except sb_clients.PartialRead:
        raise Unavailable("bills")
    rows = [r for r in summary.get("rows") or [] if not r.get("stripe_managed") and r.get("reaches_threshold")]
    ids = sorted({str(r["contractor_id"]) for r in rows if r.get("contractor_id")})
    w9: Dict[str, bool] = {}
    if ids:
        got = sb_clients.sb_get_as_service(
            f"/contractors?business_id=eq.{_q(biz)}&id=in.({','.join(_q(i) for i in ids)})"
            f"&select=id,tin_last4&limit=500")
        if not isinstance(got, list):
            raise Unavailable("contractors")
        w9 = {str(c["id"]): bool(c.get("tin_last4")) for c in got}
    return [{"name": r.get("name") or "—", "amount": _r(r.get("total_paid")),
             "w9": bool(r.get("contractor_id") and w9.get(str(r["contractor_id"])))} for r in rows]


def _names(people: List[str]) -> str:
    if len(people) <= 1:
        return people[0] if people else ""
    return ", ".join(people[:-1]) + " and " + people[-1]


def year(biz_row: Dict[str, Any], yr: int, today: Optional[date] = None) -> Dict[str, Any]:
    """GET /payroll/forms/year's answer."""
    today = today or date.today()
    ctx = load(biz_row, yr, ("paid", "approved"))
    unpaid = [r for r in ctx["runs"] if r.get("status") in ("draft", "approved")]
    ahead = _projection(ctx, date(yr, 12, 31), today) if date(yr, 12, 31) >= today else []
    # While the year still has runs to pay, the figures include the approved
    # runs and say so; once it doesn't, paid runs alone.
    projected = bool(unpaid or ahead)
    if not projected:
        ctx["items"] = [i for i in ctx["items"] if i.get("_status") == "paid"]
    per = _by_person(ctx)
    w2 = []
    w3 = {"1": 0.0, "2": 0.0, "3": 0.0, "4": 0.0, "5": 0.0, "6": 0.0}
    need: Dict[str, List[str]] = {"w4s": [], "addresses": [], "ssns": [], "housing": [], "housing_ambiguous": []}
    housing_on = True
    ministers = 0
    for eid, lns in sorted(per.items(), key=lambda kv: _name(ctx["emps"].get(kv[0]) or {}).lower()):
        emp = ctx["emps"].get(eid) or {"id": eid}
        prof = ctx["profiles"].get(eid) or {}
        who = _name(emp)
        minister = payroll_calc.is_minister(emp, ctx["church"])
        fica = [ln for ln in lns if not ln["exempt"]]
        b1, b2 = _r(sum(ln["box1"] for ln in lns)), _r(sum(ln["fit"] for ln in lns))
        housing = _r(sum(ln["housing_excluded"] for ln in lns))
        early = _r(sum(ln["housing_early"] for ln in lns))
        over = _r(sum(ln["housing_over"] for ln in lns))
        undesignated = _r(sum(ln["housing_undesignated"] for ln in lns))
        unchecked = _r(sum(ln["housing_unchecked"] for ln in lns))
        sit = _r(sum(ln["sit"] for ln in lns))
        boxes: Dict[str, Any] = {
            "1": b1, "2": b2,
            "3": _r(sum(ln["ss_wages"] for ln in fica)) if fica else None,
            "4": _r(sum(ln["ss_tax"] for ln in fica)) if fica else None,
            "5": _r(sum(ln["med_wages"] for ln in fica)) if fica else None,
            "6": _r(sum(ln["med_tax"] for ln in fica)) if fica else None,
            "14": [{"label": "Housing", "amount": housing}] if housing else [],
            "16": b1 if (sit or emp.get("work_state")) else None,
            "17": sit if (sit or emp.get("work_state")) else None,
        }
        missing: List[str] = []
        notes: List[str] = []
        if not prof.get("w4_signed_at"):
            missing.append("a W-4")
            need["w4s"].append(who)
        if not _address_ok(prof):
            missing.append("a mailing address")
            need["addresses"].append(who)
        if not prof.get("ssn_last4"):
            missing.append("a Social Security number")
            need["ssns"].append(who)
        if minister or housing or early or over or undesignated or unchecked:
            ministers += 1
            rec, state = _housing_record(ctx, emp)
            housing_on = housing_on and state != "off"
            if state == "none":
                missing.append(f"the board’s {yr} housing designation")
                need["housing"].append(who)
            elif state == "ambiguous":
                missing.append(f"one clear {yr} housing designation (more than one record could be theirs)")
                need["housing_ambiguous"].append(who)
            if over:
                notes.append(f"{pcal.money(over)} of housing is more than the board designated for {yr} "
                             f"({pcal.money(_r(rec.get('designated_amount')))}), so it is wages in Box 1, not "
                             f"housing allowance ({HOUSING_RULE}).")
        if early:
            notes.append(f"{pcal.money(early)} of housing was paid before the board’s vote, so it is wages in "
                         f"Box 1, not housing allowance ({HOUSING_RULE}).")
        if undesignated:
            notes.append(f"No housing allowance was designated in advance for {yr}, so the {pcal.money(undesignated)} "
                         f"of housing paid is wages in Box 1 ({HOUSING_RULE}). If the board did designate it, record "
                         f"the designation and this changes.")
        if unchecked:
            whys = {ln["housing_unchecked_why"] for ln in lns if ln["housing_unchecked"]}
            if "ambiguous" in whys:
                notes.append(f"More than one {yr} housing allowance record could be {who}’s, so the "
                             f"{pcal.money(unchecked)} of housing is left out of Box 1 as if the board designated it "
                             f"in advance: it couldn’t tell which record is theirs. Link the right record to them on "
                             f"Bookkeeping, Housing, and it is checked.")
            else:
                notes.append(f"Housing allowance records aren’t switched on here, so the {pcal.money(unchecked)} of "
                             f"housing is left out of Box 1 as if the board designated it in advance. If it didn’t, "
                             f"it is wages.")
        for k in ("1", "2"):
            w3[k] = _r(w3[k] + boxes[k])
        for k in ("3", "4", "5", "6"):
            w3[k] = _r(w3[k] + (boxes[k] or 0))
        w2.append({"employee": {"id": eid, "name": who,
                                "title": (str(emp.get("title")).strip() or None) if emp.get("title") else None,
                                "minister": minister},
                   "boxes": boxes, "missing": missing, "notes": notes})
    contractors = _contractors(str(biz_row["id"]), yr)
    line = nec_threshold(yr)
    past_unpaid = [r for r in ctx["runs"] if r.get("status") in ("draft", "approved")
                   and (_day(r.get("pay_date")) or today) <= today]
    n = len(w2)

    def ready_line(key: str, ok: bool, yes: str, no: str, fix: Optional[str]) -> Dict[str, Any]:
        return {"key": key, "ok": ok, "line": yes if ok else no, "fix": None if ok else fix}

    no_w9 = [c["name"] for c in contractors if not c["w9"]]
    readiness = [
        ready_line("runs_paid", not past_unpaid,
                   f"Every {yr} pay run so far is marked paid" if ctx["runs"] else f"No {yr} pay runs yet",
                   f"{len(past_unpaid)} {yr} pay run{'s' if len(past_unpaid) != 1 else ''} dated on or before "
                   f"today {'aren’t' if len(past_unpaid) != 1 else 'isn’t'} marked paid yet",
                   "Mark each one paid on Pay staff once the money has gone out."),
        ready_line("w4s", not need["w4s"],
                   "W-4 on file" if n == 1 else "W-4s on file for both people" if n == 2
                   else f"W-4s on file for all {n} people",
                   f"{_names(need['w4s'])} {'has' if len(need['w4s']) == 1 else 'have'} no W-4 on file",
                   "Add the W-4 on their page in Pay staff."),
        ready_line("addresses", not need["addresses"], "Every W-2 has a mailing address",
                   f"{_names(need['addresses'])} {'has' if len(need['addresses']) == 1 else 'have'} no mailing "
                   f"address, and the W-2 needs one",
                   "Ask for it and add it with their W-4."),
        ready_line("ssns", not need["ssns"], "Every W-2 has a Social Security number",
                   f"{_names(need['ssns'])} {'has' if len(need['ssns']) == 1 else 'have'} no Social Security "
                   f"number on file", "The owner adds it with their W-4."),
        ready_line("w9s", not no_w9,
                   (f"W-9s on file for {'both' if len(contractors) == 2 else 'all ' + str(len(contractors))} "
                    f"contractors" if len(contractors) > 1 else "W-9 on file for the contractor" if contractors
                    else f"No contractor reached the {pcal.money(line)[:-3]} line in {yr}"),
                   f"{_names(no_w9)} {'has' if len(no_w9) == 1 else 'have'} no W-9 on file",
                   "Add their W-9 on Contractors before the 1099-NEC."),
    ]
    if not ministers:
        readiness.append(ready_line("housing_designation", True,
                                    "No minister’s pay this year, so no housing designation is needed", "", None))
    elif not housing_on:
        readiness.append({"key": "housing_designation", "ok": False,
                          "line": f"Housing allowance records aren’t switched on for this church: keep the board’s "
                                  f"written {yr} designation with the payroll records", "fix": None})
    else:
        gaps, fixes = [], []
        if need["housing"]:
            gaps.append(f"No {yr} housing allowance designation is on file for {_names(need['housing'])}")
            fixes.append("Record the board’s designation on Bookkeeping, Housing.")
        if need["housing_ambiguous"]:
            gaps.append(f"More than one {yr} housing allowance record could be "
                        f"{_names(need['housing_ambiguous'])}’s")
            fixes.append("Link the right record to each minister on Bookkeeping, Housing.")
        readiness.append(ready_line("housing_designation", not gaps,
                                    f"The board’s housing allowance for {yr} is on file", "; ".join(gaps),
                                    " ".join(fixes)))
    due = pcal.year_end_due(yr)
    return {
        "ok": True, "year": yr, "due": due.isoformat(), "projected": projected,
        "note": (f"Shown as they’ll be once the approved runs are paid. Final when every {yr} run is marked paid."
                 if projected else None),
        "w2": w2, "w3": w3, "contractors": contractors, "readiness": readiness,
        "nec_threshold": line,
        "file_it": FILE_IT,
    }


# ─── The CSV ──────────────────────────────────────────────────────────

def _cell(v: Any) -> Any:
    """A spreadsheet never runs a cell as a formula."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def year_csv(biz_row: Dict[str, Any], data: Dict[str, Any]) -> str:
    out = io.StringIO()
    w = csv.writer(out)

    def row(*cells: Any) -> None:
        w.writerow([_cell(c) for c in cells])

    yr = data["year"]
    row(f"Year-end payroll worksheet, {yr}", str(biz_row.get("name") or ""))
    row(NOT_A_FORM)
    row(FILE_IT)
    if data.get("note"):
        row(data["note"])
    row()
    row("W-2 figures, one row a person")
    row("Person", "Title", "Minister", "Box 1 wages", "Box 2 federal income tax", "Box 3 Social Security wages",
        "Box 4 Social Security tax", "Box 5 Medicare wages", "Box 6 Medicare tax", "Box 14 housing",
        "Box 16 state wages", "Box 17 state income tax", "Still needed", "Notes")

    def num(v: Any) -> Any:
        return "" if v is None else f"{float(v):.2f}"

    for p in data["w2"]:
        b = p["boxes"]
        housing = sum(x["amount"] for x in b["14"]) if b["14"] else None
        row(p["employee"]["name"], p["employee"]["title"] or "", "yes" if p["employee"]["minister"] else "no",
            num(b["1"]), num(b["2"]), num(b["3"]), num(b["4"]), num(b["5"]), num(b["6"]), num(housing),
            num(b["16"]), num(b["17"]), "; ".join(p["missing"]), " ".join(p.get("notes") or []))
    w3 = data["w3"]
    row("W-3 totals", "", "", num(w3["1"]), num(w3["2"]), num(w3["3"]), num(w3["4"]), num(w3["5"]), num(w3["6"]))
    row()
    row(f"1099-NEC: contractors paid {pcal.money(data['nec_threshold'])} or more in {yr}")
    row("Contractor", f"Paid in {yr}", "W-9 on file")
    for c in data["contractors"]:
        row(c["name"], num(c["amount"]), "yes" if c["w9"] else "no")
    row()
    row("Ready to file")
    for r in data["readiness"]:
        row("ok" if r["ok"] else "needs a look", r["line"], r["fix"] or "")
    row()
    row(f"Due {pcal.long_day(_day(data['due']))}: W-2s to each person, W-2s and the W-3 to Social Security, "
        f"1099-NEC to contractors and the IRS")
    for line in WHERE_TO_FILE:
        row(line)
    return out.getvalue()


# ─── The PDFs (plain tables) ──────────────────────────────────────────

def _doc(title: str):
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=46, rightMargin=46, topMargin=46, bottomMargin=46,
                            title=title, author="Solutionist", creator="Solutionist")
    return buf, doc


def _styles():
    from reportlab.lib.colors import HexColor
    from reportlab.lib.styles import ParagraphStyle
    ink, muted = HexColor("#17171a"), HexColor("#5a5a64")
    return {
        "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=ink),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=11.5, leading=15, textColor=ink,
                             spaceBefore=12, spaceAfter=4),
        "p": ParagraphStyle("p", fontName="Helvetica", fontSize=9, leading=12, textColor=ink),
        "muted": ParagraphStyle("muted", fontName="Helvetica", fontSize=8.5, leading=11, textColor=muted),
        "notice": ParagraphStyle("notice", fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=ink,
                                 backColor=HexColor("#f4f4f5"), borderPadding=(7, 8, 7, 8), spaceBefore=8,
                                 spaceAfter=10),
        "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8.5, leading=10.5, textColor=ink),
    }


def _esc(s: Any) -> str:
    from xml.sax.saxutils import escape
    return escape(str(s if s is not None else ""))


def _table(rows: List[List[Any]], widths: List[float], *, header: bool = True, total: bool = False,
           text_cols: int = 1):
    """A plain table: the first `text_cols` columns read left, the figures right."""
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import Table, TableStyle
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [("FONT", (0, 0), (-1, -1), "Helvetica", 8.5), ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
             ("ALIGN", (text_cols, 0), (-1, -1), "RIGHT"),
             ("LINEBELOW", (0, 0), (-1, -1), 0.4, HexColor("#e4e4e7")),
             ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
    if header:
        style += [("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8), ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#5a5a64")),
                  ("LINEBELOW", (0, 0), (-1, 0), 1.0, HexColor("#17171a"))]
    if total:
        style += [("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 8.5),
                  ("LINEABOVE", (0, -1), (-1, -1), 1.0, HexColor("#17171a"))]
    t.setStyle(TableStyle(style))
    return t


def _m(v: Any) -> str:
    return "blank" if v is None else pcal.money(v)


def quarter_pdf(biz_row: Dict[str, Any], data: Dict[str, Any]) -> bytes:
    from reportlab.platypus import Paragraph, Spacer
    s = _styles()
    words = pcal.QUARTER_WORDS[data["q"]]
    title = f"941 worksheet, {words} {data['year']}"
    buf, doc = _doc(title)
    due = _day(data["due"])
    sched = "monthly" if data["schedule"] == pcal.MONTHLY else "semiweekly"
    L = data["lines"]
    story = [
        Paragraph(_esc(f"Form 941 worksheet: {words} {data['year']}"), s["h1"]),
        Paragraph(_esc(str(biz_row.get("name") or "")), s["muted"]),
        Paragraph(_esc(f"{NOT_A_FORM} {FILE_IT}"), s["notice"]),
        Paragraph(_esc(f"You deposit {sched}. The return is due {pcal.long_day(due)}. "
                       f"{data['runs_in']} paid run{'s' if data['runs_in'] != 1 else ''} counted"
                       + (f" of {data['runs_expected']} expected." if data["runs_expected"] else ".")), s["p"]),
        Paragraph("The numbers, by the return’s line", s["h2"]),
    ]
    rows = [["Line", "What it is", "Amount"],
            ["2", "Wages, not counting a minister’s housing allowance", pcal.money(L["2"])],
            ["3", "Federal income tax withheld", pcal.money(L["3"])],
            ["5a", f"Social Security wages, staff only: {pcal.money(L['5a_wages'])} × 12.4%", pcal.money(L["5a_tax"])],
            ["5c", f"Medicare wages, staff only: {pcal.money(L['5c_wages'])} × 2.9%", pcal.money(L["5c_tax"])],
            ["5d", f"Wages over $200,000 for Additional Medicare: {pcal.money(L['5d_wages'])} × 0.9%",
             pcal.money(L["5d_tax"])],
            ["6", "Total taxes before adjustments", pcal.money(L["6"])],
            ["7", "Rounding: fractions of cents", pcal.money(L["7"])],
            ["12", "Total taxes after adjustments", pcal.money(L["12"])]]
    story.append(_table(rows, [40, 330, 150], total=True, text_cols=2))
    story.append(Paragraph("Tax owed each month (for the monthly schedule)", s["h2"]))
    first = 3 * data["q"] - 2
    mrows = [["Month", "Owed"]] + [[pcal.MONTHS[first - 1 + n], pcal.money(v)] for n, v in enumerate(data["months"])]
    mrows.append(["Total", pcal.money(sum(data["months"]))])
    story.append(_table(mrows, [370, 150], total=True))
    story.append(Paragraph("Deposited", s["h2"]))
    drows = [["Deposit", "Sent", "Amount"]] + [[d["period"], str(d.get("sent_on") or ""), pcal.money(d["amount"])]
                                               for d in data["deposits"]]
    drows.append(["Deposited so far", "", pcal.money(data["deposited"])])
    story.append(_table(drows, [220, 150, 150], total=True, text_cols=2))
    for n in data.get("notes") or []:
        story += [Spacer(1, 6), Paragraph(_esc(n), s["p"])]
    story += [Paragraph("Where it’s filed", s["h2"])] + [Paragraph(_esc(x), s["p"]) for x in WHERE_TO_FILE[1:2]]
    story += [Spacer(1, 10), Paragraph("Prepared with Solutionist from the pay runs marked paid.", s["muted"])]
    doc.build(story)
    return buf.getvalue()


def year_pdf(biz_row: Dict[str, Any], data: Dict[str, Any]) -> bytes:
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.platypus import Paragraph, Spacer
    s = _styles()
    yr = data["year"]
    title = f"Year-end payroll worksheet, {yr}"
    buf, doc = _doc(title)
    doc.pagesize = landscape(letter)
    due = _day(data["due"])
    story = [Paragraph(_esc(title), s["h1"]), Paragraph(_esc(str(biz_row.get("name") or "")), s["muted"]),
             Paragraph(_esc(f"{NOT_A_FORM} {FILE_IT}"), s["notice"])]
    if data.get("note"):
        story.append(Paragraph(_esc(data["note"]), s["p"]))
    story.append(Paragraph(_esc(f"Due {pcal.long_day(due)}: W-2s to each person, W-2s and the W-3 to Social "
                                f"Security, 1099-NEC to contractors and the IRS."), s["p"]))
    story.append(Paragraph("Ready to file", s["h2"]))
    for r in data["readiness"]:
        mark = "Done" if r["ok"] else "Needs a look"
        story.append(Paragraph(_esc(f"{mark}: {r['line']}" + (f". {r['fix']}" if r["fix"] else "")), s["p"]))
    story.append(Paragraph("W-2 figures, one row a person", s["h2"]))
    head = ["Person", "Wages\n(1)", "Federal tax\n(2)", "SS wages\n(3)", "SS tax\n(4)", "Medicare\nwages (5)",
            "Medicare\ntax (6)", "Housing\n(14)", "State wages\n(16)", "State tax\n(17)"]
    rows: List[List[Any]] = [head]
    for p in data["w2"]:
        b = p["boxes"]
        housing = sum(x["amount"] for x in b["14"]) if b["14"] else None
        who = p["employee"]["name"] + (" (minister)" if p["employee"]["minister"] else "")
        extra = ([f"Still needed: {'; '.join(p['missing'])}"] if p["missing"] else []) + list(p.get("notes") or [])
        cell = Paragraph(_esc(who) + "".join(f"<br/><font size=7 color='#5a5a64'>{_esc(x)}</font>" for x in extra),
                         s["cell"])
        rows.append([cell, _m(b["1"]), _m(b["2"]), _m(b["3"]), _m(b["4"]), _m(b["5"]), _m(b["6"]),
                     _m(housing) if housing else "none", _m(b["16"]), _m(b["17"])])
    w3 = data["w3"]
    rows.append(["W-3 totals", _m(w3["1"]), _m(w3["2"]), _m(w3["3"]), _m(w3["4"]), _m(w3["5"]), _m(w3["6"]),
                 "", "", ""])
    story.append(_table(rows, [154, 64, 62, 64, 58, 64, 58, 58, 64, 54], total=True))
    story.append(Paragraph(_esc(f"1099-NEC: contractors paid {pcal.money(data['nec_threshold'])} or more in {yr}"),
                           s["h2"]))
    crows = [["Contractor", f"Paid in {yr}", "W-9 on file"]] + [
        [c["name"], pcal.money(c["amount"]), "yes" if c["w9"] else "no"] for c in data["contractors"]]
    if len(crows) == 1:
        crows.append(["None this year", "", ""])
    story.append(_table(crows, [400, 150, 150]))
    story += [Paragraph("Where they’re filed", s["h2"])] + [Paragraph(_esc(x), s["p"]) for x in WHERE_TO_FILE]
    story += [Spacer(1, 10), Paragraph("Prepared with Solutionist from the pay runs.", s["muted"])]
    doc.build(story)
    return buf.getvalue()
