"""
payroll_router.py — Pay your team.

Two eras live here.

  1. Interest capture (7/31): a card whose button RECORDS demand for
     "payroll with taxes handled for you" (the embedded-vendor route) and
     tells Kevin. Still live — it is the demand signal for Route B.

  2. The data layer (9/05, Route D): employees, their W-4 tax profile,
     and pay runs. Solutionist prepares the numbers; the employer pays
     from their own bank and makes their own tax deposits. Nothing here
     moves money or files anything. The payout rail (Plaid Transfer /
     Stripe Treasury) plugs in later behind `payout_rail` + `rail_ref`.

Roles (seat-access ladder, same as contractors): any seat reads; adding
or editing people and drafting runs is manager+; approving or marking a
run paid is admin; the tax profile (SSN) is the OWNER's act alone.

  GET   /payroll/summary?biz=
  GET   /payroll/employees?biz=
  POST  /payroll/employees
  PATCH /payroll/employees/{id}
  PUT   /payroll/employees/{id}/tax-profile     (owner; encrypts the SSN)
  GET   /payroll/employees/{id}/tax-profile     (last4 only)
  POST  /payroll/employees/{id}/consent         (direct-deposit consent stamp)
  POST  /payroll/employees/{id}/new-hire-reported
  GET   /payroll/runs?biz=
  POST  /payroll/runs                           (draft with one item per active employee)
  GET   /payroll/runs/{id}
  PATCH /payroll/runs/{id}/items/{item_id}      (hours / withholding / deductions → recompute)
  POST  /payroll/runs/{id}/approve              (admin; every item complete)
  POST  /payroll/runs/{id}/mark-paid            (admin; "I paid this from my bank")
  POST  /payroll/runs/{id}/cancel               (draft only)
  GET   /payroll/interest?biz=   POST /payroll/interest?biz=   (unchanged)
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import payroll_calc
import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("payroll_router")

router = APIRouter(prefix="/payroll", tags=["payroll"])

_PAY_TYPES = ("hourly", "salary")
_FREQS = tuple(payroll_calc.PERIODS_PER_YEAR)
_STATUSES = ("active", "terminated")
_FILING = ("single", "married_joint", "head_of_household")
_STATE_RE = re.compile(r"^[A-Z]{2}$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _access(biz: str, user: AuthedUser, min_role: str = "viewer") -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,owner_id,settings&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    row = rows[0]
    if str(row.get("owner_id")) == str(user.id):
        return row
    if min_role == "owner":
        raise HTTPException(403, "owner only")
    from business_users_router import require_role
    require_role(biz, str(user.id), min_role)
    return row


def _owner(biz: str, user: AuthedUser) -> Dict[str, Any]:
    return _access(biz, user, "viewer")


def _employee(employee_id: str, user: AuthedUser, min_role: str = "viewer") -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/employees?id=eq.{employee_id}&select=*&limit=1") or []
    if not rows:
        raise HTTPException(404, "employee not found")
    _access(str(rows[0]["business_id"]), user, min_role)
    return rows[0]


def _run(run_id: str, user: AuthedUser, min_role: str = "viewer") -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/pay_runs?id=eq.{run_id}&select=*&limit=1") or []
    if not rows:
        raise HTTPException(404, "pay run not found")
    _access(str(rows[0]["business_id"]), user, min_role)
    return rows[0]


def _state(code: Optional[str]) -> Optional[str]:
    c = (code or "").strip().upper()
    if not c:
        return None
    if not _STATE_RE.match(c):
        raise HTTPException(400, "state must be a 2-letter code")
    return c


def _date(s: Optional[str], field: str, required: bool = False) -> Optional[str]:
    v = (s or "").strip()
    if not v:
        if required:
            raise HTTPException(400, f"{field} is required (YYYY-MM-DD)")
        return None
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError:
        raise HTTPException(400, f"{field} must be YYYY-MM-DD")


def _money(v: Optional[float], field: str, allow_none: bool = True) -> Optional[float]:
    if v is None:
        if allow_none:
            return None
        raise HTTPException(400, f"{field} is required")
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{field} must be a number")
    if f < 0:
        raise HTTPException(400, f"{field} cannot be negative")
    return f


def _audit(biz: str, user: AuthedUser, verb: str, summary: str,
           target_type: Optional[str] = None, target_id: Optional[str] = None,
           payload: Optional[Dict[str, Any]] = None) -> None:
    try:
        import audit_log
        audit_log.record(biz, actor_type="user", actor_id=str(user.id), verb=verb,
                         summary=summary, target_type=target_type, target_id=target_id,
                         payload=payload, source="desktop")
    except Exception as e:  # never let the ledger break the write
        logger.warning(f"[payroll] audit {verb} failed: {e}")


# ═══════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════

@router.get("/summary")
def summary(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    emps = sb_clients.sb_get_as_service(
        f"/employees?business_id=eq.{biz}&select=id,status,direct_deposit_consented_at&limit=1000") or []
    runs = sb_clients.sb_get_as_service(
        f"/pay_runs?business_id=eq.{biz}&select=id,status,pay_date&order=pay_date.desc&limit=200") or []
    profiles = sb_clients.sb_get_as_service(
        f"/employee_tax_profiles?business_id=eq.{biz}&select=employee_id,w4_signed_at&limit=1000") or []
    signed = {p["employee_id"] for p in profiles if p.get("w4_signed_at")}
    active = [e for e in emps if e.get("status") == "active"]
    paid = sorted([r for r in runs if r.get("status") == "paid"],
                  key=lambda r: str(r.get("pay_date") or ""), reverse=True)
    return {
        "ok": True,
        "employees_active": len(active),
        "employees_missing_w4": sum(1 for e in active if e["id"] not in signed),
        "runs_draft": sum(1 for r in runs if r.get("status") == "draft"),
        "runs_approved": sum(1 for r in runs if r.get("status") == "approved"),
        "last_paid_date": paid[0]["pay_date"] if paid else None,
        "calculator": payroll_calc.active_calculator().name,
    }


# ═══════════════════════════════════════════════════════════════════
# Employees
# ═══════════════════════════════════════════════════════════════════

@router.get("/employees")
def list_employees(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    rows = sb_clients.sb_get_as_service(
        f"/employees?business_id=eq.{biz}&order=created_at.desc&select=*&limit=1000") or []
    profiles = sb_clients.sb_get_as_service(
        f"/employee_tax_profiles?business_id=eq.{biz}"
        f"&select=employee_id,ssn_last4,w4_signed_at&limit=1000") or []
    by_emp = {p["employee_id"]: p for p in profiles}
    out = []
    for r in rows:
        p = by_emp.get(r["id"]) or {}
        out.append({**r,
                    "has_ssn": bool(p.get("ssn_last4")),
                    "ssn_last4": p.get("ssn_last4"),
                    "w4_signed_at": p.get("w4_signed_at")})
    return {"ok": True, "employees": out}


class EmployeeBody(BaseModel):
    business_id: str
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    hire_date: Optional[str] = None
    pay_type: str = "hourly"
    pay_rate: float = 0.0
    pay_frequency: str = "biweekly"
    work_state: Optional[str] = None
    residence_state: Optional[str] = None
    notes: Optional[str] = None


def _employee_fields(body: EmployeeBody) -> Dict[str, Any]:
    if not (body.first_name or "").strip() or not (body.last_name or "").strip():
        raise HTTPException(400, "first and last name are required")
    if body.pay_type not in _PAY_TYPES:
        raise HTTPException(400, f"pay_type must be one of {_PAY_TYPES}")
    if body.pay_frequency not in _FREQS:
        raise HTTPException(400, f"pay_frequency must be one of {_FREQS}")
    return {
        "first_name": body.first_name.strip()[:80],
        "last_name": body.last_name.strip()[:80],
        "email": (body.email or "").strip().lower()[:200] or None,
        "phone": (body.phone or "").strip()[:40] or None,
        "hire_date": _date(body.hire_date, "hire_date"),
        "pay_type": body.pay_type,
        "pay_rate": _money(body.pay_rate, "pay_rate", allow_none=False),
        "pay_frequency": body.pay_frequency,
        "work_state": _state(body.work_state),
        "residence_state": _state(body.residence_state),
        "notes": (body.notes or "").strip()[:2000] or None,
    }


@router.post("/employees")
def create_employee(body: EmployeeBody,
                    user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _access(body.business_id, user, "manager")
    fields = _employee_fields(body)
    res = sb_clients.sb_post_as_service("/employees", {
        "business_id": body.business_id, "status": "active", **fields,
    })
    row = (res or [{}])[0]
    _audit(body.business_id, user, "employee_added",
           f"Added {fields['first_name']} {fields['last_name']} to the team",
           target_type="employee", target_id=row.get("id"))
    logger.info(f"[payroll] employee added biz={body.business_id[:8]}")
    return {"ok": True, "employee": row}


class EmployeePatch(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    hire_date: Optional[str] = None
    termination_date: Optional[str] = None
    status: Optional[str] = None
    pay_type: Optional[str] = None
    pay_rate: Optional[float] = None
    pay_frequency: Optional[str] = None
    work_state: Optional[str] = None
    residence_state: Optional[str] = None
    notes: Optional[str] = None


@router.patch("/employees/{employee_id}")
def update_employee(employee_id: str, body: EmployeePatch,
                    user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    e = _employee(employee_id, user, "manager")
    patch: Dict[str, Any] = {}
    if body.first_name is not None:
        if not body.first_name.strip():
            raise HTTPException(400, "first_name cannot be blank")
        patch["first_name"] = body.first_name.strip()[:80]
    if body.last_name is not None:
        if not body.last_name.strip():
            raise HTTPException(400, "last_name cannot be blank")
        patch["last_name"] = body.last_name.strip()[:80]
    if body.email is not None:
        patch["email"] = body.email.strip().lower()[:200] or None
    if body.phone is not None:
        patch["phone"] = body.phone.strip()[:40] or None
    if body.hire_date is not None:
        patch["hire_date"] = _date(body.hire_date, "hire_date")
    if body.termination_date is not None:
        patch["termination_date"] = _date(body.termination_date, "termination_date")
    if body.status is not None:
        if body.status not in _STATUSES:
            raise HTTPException(400, f"status must be one of {_STATUSES}")
        patch["status"] = body.status
        if body.status == "terminated" and not (body.termination_date or e.get("termination_date")):
            patch["termination_date"] = date.today().isoformat()
        if body.status == "active":
            patch["termination_date"] = None
    if body.pay_type is not None:
        if body.pay_type not in _PAY_TYPES:
            raise HTTPException(400, f"pay_type must be one of {_PAY_TYPES}")
        patch["pay_type"] = body.pay_type
    if body.pay_rate is not None:
        patch["pay_rate"] = _money(body.pay_rate, "pay_rate", allow_none=False)
    if body.pay_frequency is not None:
        if body.pay_frequency not in _FREQS:
            raise HTTPException(400, f"pay_frequency must be one of {_FREQS}")
        patch["pay_frequency"] = body.pay_frequency
    if body.work_state is not None:
        patch["work_state"] = _state(body.work_state)
    if body.residence_state is not None:
        patch["residence_state"] = _state(body.residence_state)
    if body.notes is not None:
        patch["notes"] = body.notes.strip()[:2000] or None
    if not patch:
        return {"ok": True, "employee": e}
    patch["updated_at"] = _now_iso()
    sb_clients.sb_patch_as_service(f"/employees?id=eq.{employee_id}", patch)
    return {"ok": True, "employee": {**e, **patch}}


# ─── Tax profile (W-4) ──────────────────────────────────────────────

class TaxProfileBody(BaseModel):
    ssn: Optional[str] = None
    address_line1: str = ""
    address_line2: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    filing_status: str = "single"
    multiple_jobs: bool = False
    dependents_amount: float = 0.0
    other_income: float = 0.0
    deductions: float = 0.0
    extra_withholding: float = 0.0
    exempt: bool = False
    state_form: Dict[str, Any] = {}
    signed: bool = False


@router.put("/employees/{employee_id}/tax-profile")
def put_tax_profile(employee_id: str, body: TaxProfileBody,
                    user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """The W-4. Stays with the employer — never sent to the IRS or the
    state. SSN entry is the OWNER's act alone, same rule as contractor
    TINs, and there is no read path for the full number here."""
    import tin_crypto

    e = _employee(employee_id, user, min_role="owner")
    if body.filing_status not in _FILING:
        raise HTTPException(400, f"filing_status must be one of {_FILING}")
    if len(str(body.state_form)) > 4000:
        raise HTTPException(400, "state_form is too large")

    existing = sb_clients.sb_get_as_service(
        f"/employee_tax_profiles?employee_id=eq.{employee_id}&select=employee_id,ssn_last4,w4_signed_at&limit=1") or []
    prior = existing[0] if existing else {}

    row: Dict[str, Any] = {
        "employee_id": employee_id,
        "business_id": e["business_id"],
        "address": {
            "line1": body.address_line1.strip()[:120],
            "line2": body.address_line2.strip()[:120],
            "city": body.city.strip()[:80],
            "state": _state(body.state) or "",
            "zip": body.zip.strip()[:20],
        },
        "federal": {
            "filing_status": body.filing_status,
            "multiple_jobs": bool(body.multiple_jobs),
            "dependents_amount": _money(body.dependents_amount, "dependents_amount") or 0.0,
            "other_income": _money(body.other_income, "other_income") or 0.0,
            "deductions": _money(body.deductions, "deductions") or 0.0,
            "extra_withholding": _money(body.extra_withholding, "extra_withholding") or 0.0,
            "exempt": bool(body.exempt),
        },
        "state": dict(body.state_form or {}),
        "w4_version": "2020",
        "updated_at": _now_iso(),
    }
    if body.signed:
        row["w4_signed_at"] = prior.get("w4_signed_at") or _now_iso()
    if (body.ssn or "").strip():
        ciphertext, last4 = tin_crypto.encrypt_tin(body.ssn)
        row["ssn_encrypted"] = ciphertext
        row["ssn_last4"] = last4
    elif not prior.get("ssn_last4"):
        raise HTTPException(400, "ssn is required (none on file yet)")

    if prior:
        sb_clients.sb_patch_as_service(f"/employee_tax_profiles?employee_id=eq.{employee_id}", row)
    else:
        sb_clients.sb_post_as_service("/employee_tax_profiles", row)

    _audit(e["business_id"], user, "employee_tax_profile_saved",
           f"Saved W-4 for {e.get('first_name')} {e.get('last_name')}",
           target_type="employee", target_id=employee_id,
           payload={"ssn_updated": bool((body.ssn or "").strip()), "signed": bool(body.signed)})
    logger.info(f"[payroll] tax profile saved employee={employee_id[:8]} "
                f"ssn_updated={bool((body.ssn or '').strip())}")
    return {"ok": True, "ssn_last4": row.get("ssn_last4") or prior.get("ssn_last4"),
            "w4_signed_at": row.get("w4_signed_at") or prior.get("w4_signed_at")}


@router.get("/employees/{employee_id}/tax-profile")
def get_tax_profile(employee_id: str,
                    user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Everything except the SSN — last4 only. The ciphertext never
    leaves the service role."""
    e = _employee(employee_id, user, min_role="owner")
    rows = sb_clients.sb_get_as_service(
        f"/employee_tax_profiles?employee_id=eq.{employee_id}"
        f"&select=employee_id,ssn_last4,address,federal,state,w4_version,w4_signed_at,updated_at&limit=1") or []
    p = rows[0] if rows else {}
    return {
        "ok": True,
        "employee_id": employee_id,
        "name": f"{e.get('first_name', '')} {e.get('last_name', '')}".strip(),
        "has_ssn": bool(p.get("ssn_last4")),
        "ssn_last4": p.get("ssn_last4"),
        "address": p.get("address") or {},
        "federal": p.get("federal") or {},
        "state": p.get("state") or {},
        "w4_version": p.get("w4_version"),
        "w4_signed_at": p.get("w4_signed_at"),
    }


@router.post("/employees/{employee_id}/consent")
def record_consent(employee_id: str,
                   user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Stamp direct-deposit consent. The account itself is never stored
    here — the payout rail collects it from the employee."""
    e = _employee(employee_id, user, "manager")
    when = e.get("direct_deposit_consented_at") or _now_iso()
    sb_clients.sb_patch_as_service(
        f"/employees?id=eq.{employee_id}",
        {"direct_deposit_consented_at": when, "updated_at": _now_iso()})
    return {"ok": True, "direct_deposit_consented_at": when}


@router.post("/employees/{employee_id}/new-hire-reported")
def new_hire_reported(employee_id: str,
                      user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """The owner filed the state new-hire report (due within 20 days of
    the first day of work). We record that it happened."""
    e = _employee(employee_id, user, "manager")
    when = e.get("new_hire_reported_at") or _now_iso()
    sb_clients.sb_patch_as_service(
        f"/employees?id=eq.{employee_id}",
        {"new_hire_reported_at": when, "updated_at": _now_iso()})
    return {"ok": True, "new_hire_reported_at": when}


# ═══════════════════════════════════════════════════════════════════
# Pay runs
# ═══════════════════════════════════════════════════════════════════

def _ytd_gross_before(biz: str, employee_id: str, year: int,
                      exclude_run_id: Optional[str]) -> float:
    """Wages already on approved/paid runs this calendar year — the base
    the Social Security cap and additional Medicare are measured against."""
    items = sb_clients.sb_get_as_service(
        f"/pay_run_items?employee_id=eq.{employee_id}&select=gross,pay_run_id&limit=1000") or []
    if not items:
        return 0.0
    runs = sb_clients.sb_get_as_service(
        f"/pay_runs?business_id=eq.{biz}&select=id,status,pay_date&limit=1000") or []
    ok_runs = {r["id"] for r in runs
               if r.get("status") in ("approved", "paid")
               and str(r.get("pay_date") or "")[:4] == str(year)
               and r["id"] != exclude_run_id}
    return float(sum(float(i.get("gross") or 0) for i in items if i.get("pay_run_id") in ok_runs))


def _items_of(run_id: str) -> List[Dict[str, Any]]:
    return sb_clients.sb_get_as_service(
        f"/pay_run_items?pay_run_id=eq.{run_id}&select=*&order=created_at.asc&limit=500") or []


def _recompute_item(biz: str, run: Dict[str, Any], item: Dict[str, Any],
                    employee: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    year = int(str(run["pay_date"])[:4])
    ytd = _ytd_gross_before(biz, employee["id"], year, run["id"])
    merged = {**item, **overrides}
    return payroll_calc.compute_item(
        employee=employee,
        hours=float(merged.get("hours") or 0),
        overtime_hours=float(merged.get("overtime_hours") or 0),
        ytd_gross_before=ytd, year=year,
        federal_withholding=merged.get("federal_withholding"),
        state_withholding=merged.get("state_withholding"),
        other_deductions=float(merged.get("other_deductions") or 0),
        employer_suta=merged.get("employer_suta"),
    )


@router.get("/runs")
def list_runs(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    rows = sb_clients.sb_get_as_service(
        f"/pay_runs?business_id=eq.{biz}&order=pay_date.desc&select=*&limit=200") or []
    return {"ok": True, "runs": rows}


class RunItemInput(BaseModel):
    employee_id: str
    hours: float = 0.0
    overtime_hours: float = 0.0


class RunBody(BaseModel):
    business_id: str
    period_start: str
    period_end: str
    pay_date: str
    items: Optional[List[RunItemInput]] = None   # None → every active employee


@router.post("/runs")
def create_run(body: RunBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz = body.business_id
    _access(biz, user, "manager")
    ps = _date(body.period_start, "period_start", required=True)
    pe = _date(body.period_end, "period_end", required=True)
    pd = _date(body.pay_date, "pay_date", required=True)
    if ps > pe:
        raise HTTPException(400, "period_start must be on or before period_end")

    employees = sb_clients.sb_get_as_service(
        f"/employees?business_id=eq.{biz}&status=eq.active&select=*&limit=1000") or []
    by_id = {e["id"]: e for e in employees}
    if not employees:
        raise HTTPException(409, "Add at least one active employee before drafting a pay run.")

    wanted: List[RunItemInput]
    if body.items is None:
        wanted = [RunItemInput(employee_id=e["id"]) for e in employees]
    else:
        wanted = body.items
        for it in wanted:
            if it.employee_id not in by_id:
                raise HTTPException(400, f"employee {it.employee_id} is not an active employee here")
    if not wanted:
        raise HTTPException(400, "a pay run needs at least one employee")

    res = sb_clients.sb_post_as_service("/pay_runs", {
        "business_id": biz, "period_start": ps, "period_end": pe, "pay_date": pd,
        "status": "draft", "calc_source": payroll_calc.active_calculator().name,
        "totals": {},
    })
    run = (res or [{}])[0]
    year = int(pd[:4])
    items: List[Dict[str, Any]] = []
    for it in wanted:
        emp = by_id[it.employee_id]
        ytd = _ytd_gross_before(biz, emp["id"], year, run.get("id"))
        calc = payroll_calc.compute_item(
            employee=emp, hours=_money(it.hours, "hours") or 0.0,
            overtime_hours=_money(it.overtime_hours, "overtime_hours") or 0.0,
            ytd_gross_before=ytd, year=year)
        r = sb_clients.sb_post_as_service("/pay_run_items", {
            "pay_run_id": run["id"], "business_id": biz, "employee_id": emp["id"], **calc,
        })
        items.append((r or [{}])[0])

    totals = payroll_calc.run_totals(items)
    sb_clients.sb_patch_as_service(f"/pay_runs?id=eq.{run['id']}", {"totals": totals})
    _audit(biz, user, "pay_run_created",
           f"Drafted a pay run for {len(items)} people, pay date {pd}",
           target_type="pay_run", target_id=run.get("id"))
    logger.info(f"[payroll] run drafted biz={biz[:8]} items={len(items)}")
    return {"ok": True, "run": {**run, "totals": totals}, "items": items}


def _run_detail(run: Dict[str, Any]) -> Dict[str, Any]:
    items = _items_of(run["id"])
    names: Dict[str, str] = {}
    if items:
        emps = sb_clients.sb_get_as_service(
            f"/employees?business_id=eq.{run['business_id']}&select=id,first_name,last_name,pay_type,pay_rate&limit=1000") or []
        for e in emps:
            names[e["id"]] = f"{e.get('first_name', '')} {e.get('last_name', '')}".strip()
    for i in items:
        i["employee_name"] = names.get(i["employee_id"], "")
    totals = payroll_calc.run_totals(items)
    return {"ok": True, "run": {**run, "totals": totals}, "items": items}


@router.get("/runs/{run_id}")
def get_run(run_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    return _run_detail(_run(run_id, user))


class ItemPatch(BaseModel):
    hours: Optional[float] = None
    overtime_hours: Optional[float] = None
    federal_withholding: Optional[float] = None
    state_withholding: Optional[float] = None
    other_deductions: Optional[float] = None
    employer_suta: Optional[float] = None


@router.patch("/runs/{run_id}/items/{item_id}")
def update_item(run_id: str, item_id: str, body: ItemPatch,
                user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    run = _run(run_id, user, "manager")
    if run.get("status") != "draft":
        raise HTTPException(409, "Only a draft run can be edited.")
    rows = sb_clients.sb_get_as_service(
        f"/pay_run_items?id=eq.{item_id}&pay_run_id=eq.{run_id}&select=*&limit=1") or []
    if not rows:
        raise HTTPException(404, "line not found on this run")
    item = rows[0]
    emp_rows = sb_clients.sb_get_as_service(
        f"/employees?id=eq.{item['employee_id']}&select=*&limit=1") or []
    if not emp_rows:
        raise HTTPException(404, "employee not found")

    overrides: Dict[str, Any] = {}
    for k in ("hours", "overtime_hours", "federal_withholding", "state_withholding",
              "other_deductions", "employer_suta"):
        v = getattr(body, k)
        if v is not None:
            overrides[k] = _money(v, k)
    calc = _recompute_item(run["business_id"], run, item, emp_rows[0], **overrides)
    calc["updated_at"] = _now_iso()
    sb_clients.sb_patch_as_service(f"/pay_run_items?id=eq.{item_id}", calc)
    items = _items_of(run_id)
    totals = payroll_calc.run_totals(items)
    sb_clients.sb_patch_as_service(f"/pay_runs?id=eq.{run_id}", {"totals": totals, "updated_at": _now_iso()})
    return {"ok": True, "item": {**item, **calc}, "totals": totals}


@router.post("/runs/{run_id}/approve")
def approve_run(run_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Approval freezes the numbers. It moves NO money: the owner pays
    from their own bank and deposits through EFTPS + the state portal,
    or a payout rail picks the approved run up later."""
    run = _run(run_id, user, "admin")
    if run.get("status") != "draft":
        raise HTTPException(409, f"Run is {run.get('status')}, not a draft.")
    items = _items_of(run_id)
    if not items:
        raise HTTPException(409, "This run has no lines.")
    missing = [i for i in items if (i.get("calc_status") or "") == "needs_calculation"]
    if missing:
        raise HTTPException(409, {
            "error": "needs_calculation",
            "count": len(missing),
            "message": (f"{len(missing)} line(s) still need federal and state withholding. "
                        "Enter them from your tax engine before approving."),
        })
    totals = payroll_calc.run_totals(items)
    when = _now_iso()
    sb_clients.sb_patch_as_service(f"/pay_runs?id=eq.{run_id}", {
        "status": "approved", "approved_at": when, "approved_by": str(user.id),
        "totals": totals, "updated_at": when,
    })
    biz = run["business_id"]
    from event_spine import emit
    emit("pay_run_approved", biz, {
        "pay_run_id": run_id, "pay_date": run.get("pay_date"),
        "employees": totals["employees"], "net": totals["net"],
        "federal_941": totals["deposits"]["federal_941"],
    }, source="payroll")
    _audit(biz, user, "pay_run_approved",
           f"Approved pay for {totals['employees']} people, pay date {run.get('pay_date')}",
           target_type="pay_run", target_id=run_id,
           payload={"net": totals["net"], "federal_941": totals["deposits"]["federal_941"]})
    logger.info(f"[payroll] run approved biz={biz[:8]} run={run_id[:8]}")
    return {"ok": True, "run": {**run, "status": "approved", "approved_at": when, "totals": totals}}


@router.post("/runs/{run_id}/mark-paid")
def mark_paid(run_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """The owner paid the team from their own bank. Records it; the
    bookkeeping side reads pay_run_paid off the spine."""
    run = _run(run_id, user, "admin")
    if run.get("status") != "approved":
        raise HTTPException(409, "Approve the run first, then mark it paid.")
    when = _now_iso()
    rail = run.get("payout_rail") or "manual"
    sb_clients.sb_patch_as_service(f"/pay_runs?id=eq.{run_id}", {
        "status": "paid", "paid_at": when, "updated_at": when, "payout_rail": rail,
    })
    biz = run["business_id"]
    totals = run.get("totals") or payroll_calc.run_totals(_items_of(run_id))
    from event_spine import emit
    emit("pay_run_paid", biz, {
        "pay_run_id": run_id, "pay_date": run.get("pay_date"),
        "net": totals.get("net"), "rail": rail,
    }, source="payroll")
    _audit(biz, user, "pay_run_paid",
           f"Marked pay run for {run.get('pay_date')} as paid",
           target_type="pay_run", target_id=run_id)
    return {"ok": True, "run": {**run, "status": "paid", "paid_at": when, "payout_rail": rail}}


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    run = _run(run_id, user, "manager")
    if run.get("status") != "draft":
        raise HTTPException(409, "Only a draft run can be cancelled.")
    when = _now_iso()
    sb_clients.sb_patch_as_service(f"/pay_runs?id=eq.{run_id}",
                                   {"status": "cancelled", "updated_at": when})
    return {"ok": True, "run": {**run, "status": "cancelled"}}


# ═══════════════════════════════════════════════════════════════════
# Interest capture (7/31) — unchanged
# ═══════════════════════════════════════════════════════════════════

@router.get("/interest")
def get_interest(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    rows = sb_clients.sb_get_as_service(
        f"/payroll_interest?business_id=eq.{biz}&select=id,requested_at&limit=1") or []
    return {"ok": True, "requested": bool(rows),
            "requested_at": rows[0]["requested_at"] if rows else None}


@router.post("/interest")
async def record_interest(biz: str,
                          user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    b = _owner(biz, user)
    existing = sb_clients.sb_get_as_service(
        f"/payroll_interest?business_id=eq.{biz}&select=id&limit=1") or []
    if existing:
        return {"ok": True, "requested": True, "already": True}

    sb_clients.sb_post_as_service("/payroll_interest", {
        "business_id": biz,
        "requested_by": str(user.id),
    }, prefer=None)

    # Kevin hears about real demand where he reads mail: the platform
    # inbox. Best-effort — the interest row is the record.
    try:
        from email_sender import send_via_resend
        count_rows = sb_clients.sb_get_as_service(
            "/payroll_interest?select=id&limit=1000") or []
        await send_via_resend(
            to_email="admin@mysolutionist.app",
            to_name="Kevin",
            from_email="noreply@mysolutionist.app",
            from_name="The Solutionist System",
            subject=f"Payroll interest: {b.get('name') or biz[:8]} "
                    f"({len(count_rows)} total)",
            body=(f"{b.get('name') or 'A business'} asked for payroll with taxes handled.\n\n"
                  f"Total businesses on the waitlist: {len(count_rows)}.\n"
                  f"The embedded-vendor ruling: open the vendor calls when demand "
                  f"justifies the per-customer cost — this is the demand signal."),
            reply_to=None,
        )
    except Exception as e:
        logger.warning(f"[payroll] interest email failed (row recorded): {e}")

    import audit_log
    audit_log.record(biz, actor_type="user", actor_id=str(user.id),
                     verb="payroll_interest", summary="Asked for payroll with taxes handled (waitlist)",
                     source="desktop")
    logger.info(f"[payroll] interest recorded biz={biz[:8]}")
    return {"ok": True, "requested": True, "already": False}
