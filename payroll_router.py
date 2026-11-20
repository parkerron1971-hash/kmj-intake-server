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

A minister (2026-10-31): `minister` and `housing_allowance_per_period` on
the employee, and a line's `housing_allowance`, are the OWNER's to set:
they change how the pay is taxed. Only a church may mark someone a
minister, and only with how they are one (`minister_credential`:
ordained, licensed or commissioned; the IRS's test for a minister):
a barbershop that ticked it would stop withholding Social Security and
owe it with penalties. A minister's line owes no Social Security, Medicare
or FUTA, and at a church no one's line owes FUTA (payroll_calc, `church=`).
When a run is marked paid, each
line's housing part is logged to that minister's housing allowance record
for the year (housing_allowance.py, source pay_run); the answer says what
was logged and what couldn't be.

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
  POST  /payroll/runs/{id}/log-housing          (owner; a paid run's housing parts, again)
  POST  /payroll/runs/{id}/cancel               (draft only)
  GET   /payroll/interest?biz=   POST /payroll/interest?biz=   (unchanged)

Payroll, the free version (2026-11-19, Kevin: "build the free version now").
The church pays from its own bank and sends its own deposits; Solutionist
prepares the numbers, the statements, the calendar, the reminders and the
year-end worksheets. The logic lives in its own modules; these are the doors:

  GET   /payroll/calendar?biz=&month=YYYY-MM    (payroll_calendar)
  POST  /payroll/deposits/mark-sent             (owner, Admin, or a Work tick; payroll_deposits)
  POST  /payroll/deposits/undo
  PUT   /payroll/settings                       (owner or Admin; businesses.settings.payroll)
  GET   /payroll/runs/{id}/stubs                (payroll_stubs; approved or paid runs)
  GET   /payroll/runs/{id}/items/{item}/stub    and .../stub.pdf
  POST  /payroll/runs/{id}/stubs/send           (owner or Admin; and on mark-paid, PAYROLL_STUB_EMAIL)
  GET   /payroll/forms/quarter?biz=&year=&q=    and /forms/quarter.pdf (payroll_forms; worksheets only)
  GET   /payroll/forms/year?biz=&year=          and /forms/year.pdf, /forms/year.csv
  A new run carries each person's typed withholding over (payroll_carry);
  the hourly reminders are payroll_reminders (PAYROLL_REMINDERS).

Every door asks the church wall first (church_money_gate.require_pay_records:
in a church the owner, an Admin or the accountant; with the giving tick on,
a login the owner gave giving at Work, to read as well as to change), then
today's seat ladder. Ids are shape-checked before they reach a PostgREST
path; a statement of another church's run is a 404.
"""
from __future__ import annotations

import logging
import math
import re
import threading
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
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


def _access(biz: str, user: AuthedUser, min_role: str = "viewer", tick_work: bool = False) -> Dict[str, Any]:
    """The business row when this person may open payroll at `min_role`.
    `tick_work`: a login the church wall let in by its giving tick (at Work,
    which require_pay_records already holds it to) stands in for min_role:
    the doors the contract opens to "owner, Admin, or a Work tick"."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,owner_id,settings,type&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    row = rows[0]
    # A church's or nonprofit's payroll, contractors and period closes are its
    # books: the money wall is asked first, as the ledger asks it (gl_router).
    # Any other business isn't asked here. Payroll shows pay and Social
    # Security numbers' last four, so a login let in only by its giving tick
    # must hold Work to READ as well as to change (Kevin, 2026-11-19).
    import church_money_gate
    passed = church_money_gate.require_pay_records(biz, user, row)
    if str(row.get("owner_id")) == str(user.id):
        return row
    if min_role == "owner":
        raise HTTPException(403, "owner only")
    if tick_work and passed.by in church_money_gate.TICKS:
        return row
    from business_users_router import require_role
    require_role(biz, str(user.id), min_role)
    return row


_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def _uuid(v: Any, what: str) -> str:
    """An id that goes into a PostgREST path: exactly a UUID (fullmatch, so
    no trailing newline, brace or fragment rides along), or a 400."""
    if not isinstance(v, str) or not _UUID_RE.fullmatch(v):
        raise HTTPException(400, f"That {what} id isn't valid.")
    return str(uuid.UUID(v))


def _scoped_run(run_id: str, user: AuthedUser, min_role: str = "viewer") -> Dict[str, Any]:
    """A run for a statement door: a run this person may not open (another
    church's, or one they can't see) is a 404, never a 403 that says it
    exists."""
    rid = _uuid(run_id, "pay run")
    try:
        return _run(rid, user, min_role)
    except HTTPException as e:
        if e.status_code == 403:
            raise HTTPException(404, "pay run not found")
        raise


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
    if not math.isfinite(f):                     # NaN and infinity are not money
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
    minister: Optional[bool] = None
    minister_credential: Optional[str] = None
    housing_allowance_per_period: Optional[float] = None


_MINISTER_KEYS = {"minister", "minister_credential", "housing_allowance_per_period"}
MINISTER_CREDENTIALS = payroll_calc.MINISTER_CREDENTIALS


def _is_church(biz_row: Optional[Dict[str, Any]]) -> bool:
    import church_follow_up
    return church_follow_up.is_church(biz_row or {})


def _church_of(biz: str) -> bool:
    """Whether the business paying is a church. A read that fails is a 503,
    never "not a church": the answer rewrites a saved line, and guessing no
    would put Social Security on a minister and drop their housing part."""
    rows = sb_clients.sb_get_as_service(f"/businesses?id=eq.{biz}&select=id,type&limit=1")
    if not isinstance(rows, list):
        raise HTTPException(503, "The business couldn't be read just now, so nothing was changed. Try again.")
    return bool(rows) and _is_church(rows[0])


def _minister_fields(biz_row: Dict[str, Any], user: AuthedUser, body: BaseModel,
                     current: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """A minister's tax status, how they're a minister, and housing part,
    when the body names them. The owner's alone: they decide how the pay
    is taxed. Only a church has ministers, and each says how they are one.
    Only a minister has a housing allowance; turning it off clears the
    housing part and the credential."""
    given = body.model_dump(exclude_unset=True)
    if not _MINISTER_KEYS & given.keys():
        return {}
    if str(biz_row.get("owner_id")) != str(user.id):
        raise HTTPException(403, "Only the owner sets a minister's tax status and housing allowance.")
    out: Dict[str, Any] = {}
    cur = current or {}
    minister = bool(cur.get("minister"))
    if "minister" in given:
        minister = bool(given["minister"])
        out["minister"] = minister
    if minister and not _is_church(biz_row):
        raise HTTPException(400, "Only a church can mark someone as a minister. The tax rules that take "
                                 "Social Security and Medicare off a minister's pay are for a church's ministers.")
    credential = cur.get("minister_credential")
    if "minister_credential" in given:
        credential = (given["minister_credential"] or "").strip().lower() or None
        if credential and credential not in MINISTER_CREDENTIALS:
            raise HTTPException(400, "minister_credential must be ordained, licensed or commissioned")
        out["minister_credential"] = credential
    if "housing_allowance_per_period" in given:
        out["housing_allowance_per_period"] = _money(given["housing_allowance_per_period"],
                                                     "housing_allowance_per_period")
    if minister:
        if credential not in MINISTER_CREDENTIALS:
            raise HTTPException(400, "Say how they're a minister: ordained, licensed or commissioned. Only a "
                                     "minister who is one of these, paid for ministry work, is taxed as one.")
        return out
    if out.get("housing_allowance_per_period"):
        raise HTTPException(400, "Only a minister has a housing allowance. Mark them as a minister first.")
    if cur.get("housing_allowance_per_period") or "housing_allowance_per_period" in out:
        out["housing_allowance_per_period"] = None
    if cur.get("minister_credential") or "minister_credential" in out:
        out["minister_credential"] = None
    return out


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
    biz_row = _access(body.business_id, user, "manager")
    fields = _employee_fields(body)
    fields.update(_minister_fields(biz_row, user, body))
    res = sb_clients.sb_post_as_service("/employees", {
        "business_id": body.business_id, "status": "active", **fields,
    })
    if res is None:
        raise HTTPException(503, "They weren't added: the save didn't go through. Try again.")
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
    minister: Optional[bool] = None
    minister_credential: Optional[str] = None
    housing_allowance_per_period: Optional[float] = None


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
    if _MINISTER_KEYS & body.model_fields_set:
        biz_row = _access(str(e["business_id"]), user, "manager")
        patch.update(_minister_fields(biz_row, user, body, e))
    if not patch:
        return {"ok": True, "employee": e}
    patch["updated_at"] = _now_iso()
    if sb_clients.sb_patch_as_service(f"/employees?id=eq.{employee_id}", patch) is None:
        raise HTTPException(503, "The change didn't save. Try again.")
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
    church = _church_of(biz)
    calc = payroll_calc.compute_item(
        employee=employee,
        hours=float(merged.get("hours") or 0),
        overtime_hours=float(merged.get("overtime_hours") or 0),
        ytd_gross_before=ytd, year=year,
        federal_withholding=merged.get("federal_withholding"),
        state_withholding=merged.get("state_withholding"),
        other_deductions=float(merged.get("other_deductions") or 0),
        employer_suta=merged.get("employer_suta"),
        housing_allowance=merged.get("housing_allowance"),
        church=church,
    )
    # No longer a minister: the line's housing part goes with the setting,
    # or it would still be totalled and logged as housing allowance paid.
    if not payroll_calc.is_minister(employee, church) and float(item.get("housing_allowance") or 0):
        calc["housing_allowance"] = 0.0
    return calc


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
    church = _is_church(_access(biz, user, "manager"))
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
    # Last time's typed withholding, where how they're paid hasn't changed
    # (payroll_carry). A read that fails carries nothing.
    import payroll_carry
    try:
        carry = payroll_carry.sources(biz, [by_id[it.employee_id] for it in wanted], exclude_run_id=run.get("id"))
    except Exception as e:  # noqa: BLE001 — the lines then need typing, as before
        logger.warning(f"[payroll] carry-over skipped biz={biz[:8]}: {type(e).__name__}")
        carry = {}
    items: List[Dict[str, Any]] = []
    for it in wanted:
        emp = by_id[it.employee_id]
        ytd = _ytd_gross_before(biz, emp["id"], year, run.get("id"))
        hours = _money(it.hours, "hours") or 0.0
        overtime = _money(it.overtime_hours, "overtime_hours") or 0.0
        # An hourly check carries last time's withholding only when its pay is
        # the same (payroll_carry.check); otherwise the note says why not.
        src, note = payroll_carry.check(carry.get(str(emp["id"])), emp,
                                        payroll_calc.gross_for(emp, hours, overtime))
        calc = payroll_calc.compute_item(
            employee=emp, hours=hours, overtime_hours=overtime,
            ytd_gross_before=ytd, year=year,
            federal_withholding=src.get("federal") if src else None,
            state_withholding=src.get("state") if src else None,
            housing_allowance=emp.get("housing_allowance_per_period"), church=church)
        r = sb_clients.sb_post_as_service("/pay_run_items", {
            "pay_run_id": run["id"], "business_id": biz, "employee_id": emp["id"], **calc,
            "calc_payload": payroll_carry.payload(emp, src, note=note),
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
    emps: Dict[str, Dict[str, Any]] = {}
    if items:
        # select=*: `minister` exists only once its migration is applied.
        emps = {e["id"]: e for e in sb_clients.sb_get_as_service(
            f"/employees?business_id=eq.{run['business_id']}&select=*&limit=1000") or []}
    for i in items:
        e = emps.get(i["employee_id"]) or {}
        i["employee_name"] = _name(e)
        i["minister"] = bool(e.get("minister"))
    totals = payroll_calc.run_totals(items)
    return {"ok": True, "run": {**run, "totals": totals}, "items": items,
            "housing_notes": _housing_notes(run, items, emps)}


# ─── A minister's housing allowance ─────────────────────────────────

def _name(e: Dict[str, Any]) -> str:
    return f"{e.get('first_name', '')} {e.get('last_name', '')}".strip()


def _words(s: Any) -> List[str]:
    return re.findall(r"[^\W\d_]+", str(s or "").lower())


def _housing_record(biz: str, year: int, employee: Dict[str, Any]):
    """The minister's housing allowance record for the year: the one linked
    to this employee, else the one unlinked record whose name holds theirs
    word for word ("Pastor Ana Cruz" for Ana Cruz; never "Susana Cruz-Lee").
    (record, "") or (None, why)."""
    rec, _kind, why = _housing_match(biz, year, employee)
    return rec, why


def _housing_match(biz: str, year: int, employee: Dict[str, Any]):
    """_housing_record's answer with what kind it is: (record, "found", ""),
    (None, "ambiguous", why) when more than one record could be theirs, or
    (None, "none", why). A failed read raises housing_allowance.Unavailable:
    it is never "none"."""
    import housing_allowance as ha
    rows = ha.list_allowances(biz, year)
    linked = [a for a in rows if str(a.get("employee_id") or "") == str(employee.get("id"))]
    if len(linked) == 1:
        return linked[0], "found", ""
    first, last = _words(employee.get("first_name")), _words(employee.get("last_name"))
    named = [a for a in rows if not a.get("employee_id") and first and last
             and set(first + last) <= set(_words(a["minister_name"]))]
    if len(named) == 1:
        return named[0], "found", ""
    who = _name(employee) or "this minister"
    if len(linked) + len(named) > 1:
        return None, "ambiguous", f"more than one {year} housing allowance could be {who}'s"
    return None, "none", f"no {year} housing allowance is recorded for {who}"


def _housing_notes(run: Dict[str, Any], items: List[Dict[str, Any]],
                   emps: Dict[str, Dict[str, Any]]) -> List[str]:
    """A line paying housing allowance with no designation on record: the
    board designates it before it's paid, or that part is taxable."""
    paying = [i for i in items if float(i.get("housing_allowance") or 0) > 0]
    if not paying:
        return []
    import housing_allowance as ha
    biz = str(run["business_id"])
    year = int(str(run["pay_date"])[:4])
    notes: List[str] = []
    for i in paying:
        try:
            if not ha.switched_on(biz):
                return []
            rec, why = _housing_record(biz, year, emps.get(i["employee_id"]) or {"id": i["employee_id"]})
        except Exception as e:  # a hint, never a failed run read
            logger.warning(f"[payroll] housing notes skipped: {e}")
            return []
        if not rec:
            notes.append(f"{why[0].upper()}{why[1:]}. The board designates it before it's paid; "
                         "without a designation, the housing part is taxable income.")
    return notes


def _log_housing(run: Dict[str, Any], user: AuthedUser) -> Dict[str, List[Dict[str, Any]]]:
    """Each line's housing part, logged to the minister's housing allowance
    record as paid (source pay_run, the line's id: a second try counts it
    once). Says what couldn't be logged and why. A failed read of the run's
    lines or its people raises housing_allowance.Unavailable: it is never
    "nothing to log"."""
    import housing_allowance as ha
    out: Dict[str, List[Dict[str, Any]]] = {"logged": [], "not_logged": []}
    lines = sb_clients.sb_get_as_service(
        f"/pay_run_items?pay_run_id=eq.{run['id']}&select=*&order=created_at.asc&limit=500")
    if lines is None:
        raise ha.Unavailable("pay_run_items")
    items = [i for i in lines if float(i.get("housing_allowance") or 0) > 0]
    if not items:
        return out
    biz = str(run["business_id"])
    people = sb_clients.sb_get_as_service(f"/employees?business_id=eq.{biz}&select=*&limit=1000")
    if people is None:
        raise ha.Unavailable("employees")
    emps = {e["id"]: e for e in people}
    year = int(str(run["pay_date"])[:4])
    on = ha.switched_on(biz)
    for i in items:
        emp = emps.get(i["employee_id"]) or {"id": i["employee_id"]}
        line = {"employee_id": i["employee_id"], "name": _name(emp),
                "amount": round(float(i["housing_allowance"]), 2)}
        if not on:
            out["not_logged"].append({**line, "reason": "the housing allowance records aren't switched on here"})
            continue
        try:
            rec, why = _housing_record(biz, year, emp)
            if not rec:
                out["not_logged"].append({**line, "reason": why})
                continue
            ha.add_entry(biz, str(user.id), rec["id"], {
                "kind": "paid", "amount": line["amount"], "entry_date": str(run["pay_date"])[:10],
                "source": "pay_run", "source_id": str(i["id"]),
                "note": f"Pay run, {str(run['pay_date'])[:10]}"})
            out["logged"].append(line)
        except HTTPException as e:
            if e.status_code == 409:            # already counted: a retry
                out["logged"].append(line)
            else:
                out["not_logged"].append({**line, "reason": str(e.detail)})
        except ha.Unavailable:
            out["not_logged"].append({**line, "reason": "the housing allowance records couldn't be read just now"})
    if out["logged"] or out["not_logged"]:
        logger.info(f"[payroll] housing run={str(run['id'])[:8]} logged={len(out['logged'])} "
                    f"not_logged={len(out['not_logged'])}")
    return out


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
    housing_allowance: Optional[float] = None     # a minister's line; the owner's to set


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
    housing = body.housing_allowance
    if housing is not None:
        biz_row = _access(str(run["business_id"]), user, "manager")
        if not payroll_calc.is_minister(emp_rows[0], _is_church(biz_row)):
            raise HTTPException(400, "Only a minister's pay has a housing allowance.")
        if str(biz_row.get("owner_id")) != str(user.id):
            raise HTTPException(403, "Only the owner sets the housing allowance part of a check.")
        overrides["housing_allowance"] = _money(housing, "housing_allowance")
    import payroll_carry
    before = item.get("calc_payload") if isinstance(item.get("calc_payload"), dict) else {}
    # A figure typed here is no longer carried; a carried hourly line whose
    # hours changed is a different check, so every carried figure this PATCH
    # doesn't type is cleared and the note says which (payroll_carry.after_patch).
    before, note, clear = payroll_carry.after_patch(before, item, emp_rows[0], overrides)
    for col in clear:
        overrides[col] = None
    calc = _recompute_item(run["business_id"], run, item, emp_rows[0], **overrides)
    if housing is not None and overrides["housing_allowance"] > calc["gross"]:
        raise HTTPException(400, f"The housing part can't be more than the check (${calc['gross']:,.2f}).")
    # How they're paid now rides the line (payroll_carry).
    calc["calc_payload"] = payroll_carry.payload(emp_rows[0], None, before, note=note)
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
    # Nobody is paid less than nothing: a line whose taxes and deductions are
    # more than its pay stops the run, naming the person.
    below = [i for i in items if i.get("net") is not None and float(i.get("net") or 0) < 0]
    if below:
        people = {e["id"]: e for e in sb_clients.sb_get_as_service(
            f"/employees?business_id=eq.{run['business_id']}&select=id,first_name,last_name&limit=1000") or []}
        names = [(_name(people.get(i["employee_id"]) or {}) or "Someone", float(i["net"])) for i in below]
        which = " and ".join(f"{n} (−${abs(v):,.2f})" for n, v in names)
        one = len(names) == 1
        raise HTTPException(409, {
            "error": "negative_net",
            "count": len(names),
            "people": [n for n, _ in names],
            "message": (f"Take-home pay would be below zero for {which}: the taxes and deductions are more than "
                        f"the pay. Fix {'that line' if one else 'those lines'} before approving."),
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
    try:
        housing = _log_housing(run, user)
    except Exception as e:  # the run is paid either way; log-housing can try again
        logger.warning(f"[payroll] housing log failed run={run_id[:8]}: {e}")
        housing = {"logged": [], "not_logged": [], "failed": True,
                   "reason": "the housing allowance couldn't be logged just now; the owner can try again"}
    return {"ok": True, "run": {**run, "status": "paid", "paid_at": when, "payout_rail": rail},
            "housing": housing, "stubs": _auto_stubs({**run, "status": "paid", "paid_at": when})}


def _background(fn) -> None:
    """Work after the answer, off the request (the repo's way:
    church_job_defs._later): a slow mail server never holds up mark-paid."""
    threading.Thread(target=fn, daemon=True).start()


def _auto_stubs(run: Dict[str, Any]) -> Dict[str, Any]:
    """A run marked paid emails each person their statement, behind
    PAYROLL_STUB_EMAIL (off | owner | on, default on), in the background:
    the answer says whether it was queued, never what went (Send stubs, and
    the run's statements, show that). A send that fails never fails the
    mark-paid."""
    import payroll_stubs
    biz = str(run["business_id"])
    if not payroll_stubs.auto_on(biz):
        return {"queued": False, "auto": False, "sent": None, "skipped": []}

    def go() -> None:
        try:
            rows = sb_clients.sb_get_as_service(
                f"/businesses?id=eq.{biz}&select=id,name,owner_id,settings,type&limit=1")
            if isinstance(rows, list) and rows:
                payroll_stubs.send(payroll_stubs.load(run, rows[0]), auto=True)
        except Exception as e:  # noqa: BLE001 — the run is paid either way; Send stubs can try again
            logger.warning(f"[payroll] statements not sent run={str(run.get('id'))[:8]}: {type(e).__name__}")
    try:
        _background(go)
    except Exception as e:  # noqa: BLE001 — couldn't start: Send stubs still works
        logger.warning(f"[payroll] statements not queued run={str(run.get('id'))[:8]}: {type(e).__name__}")
        return {"queued": False, "auto": True, "sent": None, "skipped": [], "failed": True}
    return {"queued": True, "auto": True, "sent": None, "skipped": []}


@router.post("/runs/{run_id}/log-housing")
def log_housing(run_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Log a paid run's housing parts again: after the designation was
    recorded, or a read failed. Each line counts once however often it runs."""
    run = _run(run_id, user, "owner")
    if run.get("status") != "paid":
        raise HTTPException(409, "Only a paid run's housing allowance is logged.")
    import housing_allowance as ha
    try:
        return {"ok": True, "housing": _log_housing(run, user)}
    except ha.Unavailable:
        raise HTTPException(503, "The pay run couldn't be read just now, so nothing was logged. Try again.")


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
# Payroll, the free version (2026-11-19): the calendar, deposits,
# settings, statements and worksheets. Thin doors; the logic is in
# payroll_calendar, payroll_deposits, payroll_stubs and payroll_forms.
# ═══════════════════════════════════════════════════════════════════

def _biz(biz: Any) -> str:
    return _uuid(biz, "business")


def _year(v: Optional[int]) -> int:
    y = date.today().year if v is None else v
    if not isinstance(y, int) or not 2000 <= y <= 2100:
        raise HTTPException(400, "year must be between 2000 and 2100")
    return y


def _unavailable() -> HTTPException:
    return HTTPException(503, "Payroll couldn't be read just now, so nothing is shown. Try again.")


def _file(data: bytes, media: str, name: str) -> Response:
    return Response(content=data, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


# ─── The calendar ───────────────────────────────────────────────────

@router.get("/calendar")
def payroll_calendar_month(biz: str, month: Optional[str] = None,
                           user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Every payday, approve-by day, tax deposit, form date and bank holiday
    in one month, with what's next and what comes after."""
    import payroll_calendar
    row = _owner(_biz(biz), user)
    try:
        return payroll_calendar.month_view(row, month)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except payroll_calendar.Unreadable:
        raise _unavailable()


# ─── Deposits marked sent ───────────────────────────────────────────

class MarkSentBody(BaseModel):
    business_id: str
    key: str
    amount: float
    sent_on: Optional[str] = None
    reference: Optional[str] = None


class DepositKeyBody(BaseModel):
    business_id: str
    key: str


def _deposit_key(key: str) -> Dict[str, Any]:
    import payroll_calendar
    parsed = payroll_calendar.parse_key((key or "").strip())
    if not parsed:
        raise HTTPException(400, "That isn't a deposit or form this calendar knows.")
    return parsed


@router.post("/deposits/mark-sent")
def mark_deposit_sent(body: MarkSentBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """The church sent this deposit (or filed this form) itself: the
    calendar says so and the reminders stop. A second call updates it."""
    import payroll_calendar
    import payroll_deposits
    biz = _biz(body.business_id)
    row = _access(biz, user, "admin", tick_work=True)
    key = body.key.strip()
    parsed = _deposit_key(key)
    amount = _money(body.amount, "amount", allow_none=False)
    if amount > 10_000_000:
        raise HTTPException(400, "amount is too large")
    sent_on = date.fromisoformat(_date(body.sent_on, "sent_on") or date.today().isoformat())
    if abs((sent_on - date.today()).days) > 400:
        raise HTTPException(400, "sent_on must be within a year of today")
    ref = re.sub(r"[\x00-\x1f\x7f<>]", " ", body.reference or "").strip()[:120] or None
    due = payroll_calendar.due_for(parsed, payroll_calendar.settings_of(row))
    try:
        saved = payroll_deposits.mark_sent(biz, key, parsed, amount=amount, sent_on=sent_on, reference=ref,
                                           due_on=due, by=str(user.id))
    except payroll_deposits.NotReady:
        raise HTTPException(503, payroll_deposits.NOT_READY)
    except payroll_deposits.SaveFailed:
        raise HTTPException(503, payroll_deposits.SAVE_503)
    _audit(biz, user, "payroll_deposit_marked", f"Marked {parsed['kind']} {parsed['period']} sent",
           target_type="payroll_deposit", target_id=key)
    return {"ok": True, "deposit": payroll_deposits.public(saved)}


@router.post("/deposits/undo")
def undo_deposit_sent(body: DepositKeyBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    import payroll_deposits
    biz = _biz(body.business_id)
    _access(biz, user, "admin", tick_work=True)
    key = body.key.strip()
    _deposit_key(key)
    try:
        payroll_deposits.undo(biz, key)
    except payroll_deposits.NotReady:
        raise HTTPException(503, payroll_deposits.NOT_READY)
    except payroll_deposits.SaveFailed:
        raise HTTPException(503, payroll_deposits.SAVE_503)
    _audit(biz, user, "payroll_deposit_unmarked", "Took back a deposit marked sent",
           target_type="payroll_deposit", target_id=key)
    return {"ok": True}


# ─── Settings ───────────────────────────────────────────────────────

class PayrollSettingsBody(BaseModel):
    business_id: str
    deposit_schedule: Optional[str] = None
    state_day: Optional[int] = None
    state_label: Optional[str] = None


@router.put("/settings")
def put_payroll_settings(body: PayrollSettingsBody, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """How often the church deposits, and its state's day. Written by the
    server into businesses.settings.payroll, these keys only."""
    import payroll_calendar
    biz = _biz(body.business_id)
    row = _access(biz, user, "admin")
    given = {k: getattr(body, k) for k in ("deposit_schedule", "state_day", "state_label")
             if k in body.model_fields_set}
    try:
        patch = payroll_calendar.settings_patch(given)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not patch:
        return {"ok": True, "settings": payroll_calendar.settings_of(row)}
    after = payroll_calendar.save_settings(biz, patch)
    if after is None:
        raise HTTPException(503, "The payroll settings didn't save. Try again.")
    _audit(biz, user, "payroll_settings_saved", "Changed the payroll deposit settings",
           payload={"keys": sorted(patch)})
    return {"ok": True, "settings": after}


# ─── Pay statements ─────────────────────────────────────────────────

def _stub_run(run_id: str, user: AuthedUser) -> Dict[str, Any]:
    import payroll_stubs
    run = _scoped_run(run_id, user)
    if run.get("status") == "draft":
        raise HTTPException(409, payroll_stubs.DRAFT_409)
    if run.get("status") not in payroll_stubs.STATUSES_WITH_STUBS:
        raise HTTPException(409, payroll_stubs.CANCELLED_409)
    return run


def _stub_ctx(run: Dict[str, Any], user: AuthedUser) -> Dict[str, Any]:
    import payroll_stubs
    row = _access(str(run["business_id"]), user)
    try:
        return payroll_stubs.load(run, row)
    except payroll_stubs.Unavailable:
        raise _unavailable()


def _one_item(ctx: Dict[str, Any], item_id: str) -> Dict[str, Any]:
    iid = _uuid(item_id, "line")
    item = next((i for i in ctx["items"] if str(i.get("id")) == iid), None)
    if not item:
        raise HTTPException(404, "That line isn't on this run.")
    return item


@router.get("/runs/{run_id}/stubs")
def run_stubs(run_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    import payroll_stubs
    ctx = _stub_ctx(_stub_run(run_id, user), user)
    return {"ok": True, "stubs": payroll_stubs.all_stubs(ctx)}


@router.get("/runs/{run_id}/items/{item_id}/stub")
def item_stub(run_id: str, item_id: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    import payroll_stubs
    ctx = _stub_ctx(_stub_run(run_id, user), user)
    return {"ok": True, "stub": payroll_stubs.build(ctx, _one_item(ctx, item_id))}


@router.get("/runs/{run_id}/items/{item_id}/stub.pdf")
def item_stub_pdf(run_id: str, item_id: str, user: AuthedUser = Depends(require_user)) -> Response:
    import payroll_stubs
    ctx = _stub_ctx(_stub_run(run_id, user), user)
    stub = payroll_stubs.build(ctx, _one_item(ctx, item_id))
    return _file(payroll_stubs.pdf(stub, ctx["biz"]), "application/pdf", payroll_stubs.filename(stub))


class SendStubsBody(BaseModel):
    item_ids: Optional[List[str]] = None


@router.post("/runs/{run_id}/stubs/send")
def send_run_stubs(run_id: str, body: Optional[SendStubsBody] = None,
                   user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Email each person (or the lines named) their statement, at the
    address on their own record, from the church."""
    import payroll_stubs
    run = _stub_run(run_id, user)
    _access(str(run["business_id"]), user, "admin")
    only = None
    if body is not None and body.item_ids is not None:
        if len(body.item_ids) > 500:
            raise HTTPException(400, "Too many lines at once.")
        only = [_uuid(i, "line") for i in body.item_ids]
    ctx = _stub_ctx(run, user)
    if only is not None:
        have = {str(i.get("id")) for i in ctx["items"]}
        if any(i not in have for i in only):
            raise HTTPException(404, "That line isn't on this run.")
    out = payroll_stubs.send(ctx, only=only)
    _audit(str(run["business_id"]), user, "pay_statements_sent",
           f"Emailed {out['sent']} pay statement(s) for the {run.get('pay_date')} run",
           target_type="pay_run", target_id=str(run["id"]))
    return {"ok": True, **out}


# ─── The worksheets ─────────────────────────────────────────────────

def _quarter(biz: str, year: Optional[int], q: int, user: AuthedUser):
    import payroll_forms
    row = _owner(_biz(biz), user)
    if not isinstance(q, int) or not 1 <= q <= 4:
        raise HTTPException(400, "q must be 1, 2, 3 or 4")
    try:
        return row, payroll_forms.quarter(row, _year(year), q)
    except payroll_forms.HousingUnreadable:
        raise HTTPException(503, payroll_forms.HOUSING_503)
    except payroll_forms.Unavailable:
        raise _unavailable()


def _year_data(biz: str, year: Optional[int], user: AuthedUser):
    import payroll_forms
    row = _owner(_biz(biz), user)
    try:
        return row, payroll_forms.year(row, _year(year))
    except payroll_forms.HousingUnreadable:
        raise HTTPException(503, payroll_forms.HOUSING_503)
    except payroll_forms.Unavailable:
        raise _unavailable()


@router.get("/forms/quarter")
def forms_quarter(biz: str, q: int = Query(...), year: Optional[int] = None,
                  user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    return _quarter(biz, year, q, user)[1]


@router.get("/forms/quarter.pdf")
def forms_quarter_pdf(biz: str, q: int = Query(...), year: Optional[int] = None,
                      user: AuthedUser = Depends(require_user)) -> Response:
    import payroll_forms
    row, data = _quarter(biz, year, q, user)
    return _file(payroll_forms.quarter_pdf(row, data), "application/pdf",
                 f"941-worksheet-{data['year']}-Q{data['q']}.pdf")


@router.get("/forms/year")
def forms_year(biz: str, year: Optional[int] = None, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    return _year_data(biz, year, user)[1]


@router.get("/forms/year.pdf")
def forms_year_pdf(biz: str, year: Optional[int] = None, user: AuthedUser = Depends(require_user)) -> Response:
    import payroll_forms
    row, data = _year_data(biz, year, user)
    return _file(payroll_forms.year_pdf(row, data), "application/pdf", f"year-end-worksheet-{data['year']}.pdf")


@router.get("/forms/year.csv")
def forms_year_csv(biz: str, year: Optional[int] = None, user: AuthedUser = Depends(require_user)) -> Response:
    import payroll_forms
    row, data = _year_data(biz, year, user)
    return _file(payroll_forms.year_csv(row, data).encode("utf-8"), "text/csv; charset=utf-8",
                 f"year-end-worksheet-{data['year']}.csv")


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
