"""
payroll_calc.py — Pay your team — the pay-run math (data layer, 2026-09-05).

The rails rule: build the brain, rent the plumbing. Payroll math splits
cleanly into two kinds, and this module is honest about which is which.

  COMPUTED HERE (statutory: one rate and one wage base per year, no
  bracket tables):
    * gross — hours × rate (overtime at 1.5×) for hourly staff, or the
      annual salary divided by the number of pay periods
    * Social Security — 6.2% employee + 6.2% employer, up to the wage base
    * Medicare — 1.45% employee + 1.45% employer, plus the 0.9% additional
      employee tax on wages over $200,000 in the year
    * FUTA — employer 0.6% on the first $7,000 (assumes the full state
      credit; the 6.0% gross rate applies only in credit-reduction states)

  NOT COMPUTED HERE (tables that change every January, across 50 states
  and thousands of localities):
    * federal income tax withholding
    * state income tax withholding
    * state unemployment (an employer-specific rate the state assigns)

  Those come from a tax engine through the Calculator seam below, or the
  owner types them from the engine's answer. Until one of those fills
  them, the item stays `needs_calculation` and the run cannot be approved.

Rail-agnostic: nothing in this module moves money or knows a bank account.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import HTTPException

# ─── Statutory constants ────────────────────────────────────────────
# One number per year. When January comes, add the year — never edit the
# past, a prior year's run must recompute the same way it did then.
SOCIAL_SECURITY_RATE = 0.062
SOCIAL_SECURITY_WAGE_BASE: Dict[int, float] = {
    2024: 168_600.0,
    2025: 176_100.0,
    2026: 184_500.0,
}
MEDICARE_RATE = 0.0145
ADDITIONAL_MEDICARE_RATE = 0.009
ADDITIONAL_MEDICARE_THRESHOLD = 200_000.0
FUTA_RATE = 0.006          # 6.0% gross less the 5.4% state credit
FUTA_WAGE_BASE = 7_000.0
OVERTIME_MULTIPLIER = 1.5

PERIODS_PER_YEAR: Dict[str, int] = {
    "weekly": 52,
    "biweekly": 26,
    "semimonthly": 24,
    "monthly": 12,
}


def _r(x: float) -> float:
    """Money rounding — half-up to the cent, the way a pay stub does it."""
    return float(f"{x + 1e-9:.2f}") if x >= 0 else -float(f"{-x + 1e-9:.2f}")


def ss_wage_base(year: int) -> float:
    """The wage base for a year; a future year falls back to the latest
    known one so a January run never crashes, and logs nothing — the
    approve path surfaces it as a review note instead."""
    if year in SOCIAL_SECURITY_WAGE_BASE:
        return SOCIAL_SECURITY_WAGE_BASE[year]
    return SOCIAL_SECURITY_WAGE_BASE[max(SOCIAL_SECURITY_WAGE_BASE)]


# ─── Gross ──────────────────────────────────────────────────────────

def gross_for(employee: Dict[str, Any], hours: float, overtime_hours: float = 0.0) -> float:
    """Hourly: hours × rate + overtime × rate × 1.5. Salary: annual / periods,
    hours ignored (kept on the item for the record)."""
    rate = float(employee.get("pay_rate") or 0)
    if (employee.get("pay_type") or "hourly") == "salary":
        periods = PERIODS_PER_YEAR.get(employee.get("pay_frequency") or "biweekly", 26)
        return _r(rate / periods)
    return _r(max(0.0, float(hours or 0)) * rate
              + max(0.0, float(overtime_hours or 0)) * rate * OVERTIME_MULTIPLIER)


# ─── Statutory taxes ────────────────────────────────────────────────

def statutory(gross: float, ytd_gross_before: float, year: int) -> Dict[str, float]:
    """FICA + FUTA for one check, given wages already paid this year.
    Wage bases are applied against YTD so the cap lands mid-year the way
    the IRS expects, not per check."""
    gross = max(0.0, float(gross or 0))
    ytd = max(0.0, float(ytd_gross_before or 0))

    base = ss_wage_base(year)
    ss_taxable = max(0.0, min(gross, base - ytd))
    ss = _r(ss_taxable * SOCIAL_SECURITY_RATE)

    medicare = _r(gross * MEDICARE_RATE)
    over_before = max(0.0, ytd - ADDITIONAL_MEDICARE_THRESHOLD)
    over_after = max(0.0, ytd + gross - ADDITIONAL_MEDICARE_THRESHOLD)
    additional = _r((over_after - over_before) * ADDITIONAL_MEDICARE_RATE)

    futa_taxable = max(0.0, min(gross, FUTA_WAGE_BASE - ytd))
    futa = _r(futa_taxable * FUTA_RATE)

    return {
        "social_security_employee": ss,
        "medicare_employee": _r(medicare + additional),
        "employer_social_security": ss,
        "employer_medicare": medicare,
        "employer_futa": futa,
    }


# ─── The calculator seam ────────────────────────────────────────────

class Calculator:
    """One interface, two implementations. `withholding` answers the two
    numbers this module refuses to compute — or None to say "not mine"."""
    name = "manual"

    def configured(self) -> bool:
        return True

    def withholding(self, *, gross: float, employee: Dict[str, Any],
                    profile: Dict[str, Any], pay_frequency: str,
                    ytd_gross_before: float, year: int) -> Optional[Dict[str, float]]:
        return None


class ManualCalculator(Calculator):
    """The owner types federal and state withholding from their own tax
    engine or table. Nothing is guessed."""
    name = "manual"


class SymmetryCalculator(Calculator):
    """Symmetry Tax Engine adapter. Present so the seam exists and the
    router can name it; the HTTP call lands when SYMMETRY_API_KEY does.
    Until then it is honest: 501, never a fabricated number."""
    name = "symmetry"

    def configured(self) -> bool:
        return bool((os.environ.get("SYMMETRY_API_KEY") or "").strip())

    def withholding(self, **kwargs) -> Optional[Dict[str, float]]:
        raise HTTPException(
            501, "The tax engine is not connected yet. Enter federal and state "
                 "withholding by hand, or connect Symmetry in Settings.")


def active_calculator() -> Calculator:
    sym = SymmetryCalculator()
    return sym if sym.configured() else ManualCalculator()


# ─── One line item ──────────────────────────────────────────────────

def compute_item(*, employee: Dict[str, Any], hours: float, overtime_hours: float,
                 ytd_gross_before: float, year: int,
                 federal_withholding: Optional[float] = None,
                 state_withholding: Optional[float] = None,
                 other_deductions: float = 0.0,
                 employer_suta: Optional[float] = None) -> Dict[str, Any]:
    """Everything a pay_run_items row needs from the numbers we own.
    FIT/SIT pass through untouched (None = still needed)."""
    gross = gross_for(employee, hours, overtime_hours)
    tax = statutory(gross, ytd_gross_before, year)
    fit = None if federal_withholding is None else _r(float(federal_withholding))
    sit = None if state_withholding is None else _r(float(state_withholding))
    other = _r(max(0.0, float(other_deductions or 0)))

    complete = fit is not None and sit is not None
    net = None
    if complete:
        net = _r(gross - (fit or 0) - (sit or 0)
                 - tax["social_security_employee"] - tax["medicare_employee"] - other)

    return {
        "hours": _r(float(hours or 0)),
        "overtime_hours": _r(float(overtime_hours or 0)),
        "gross": gross,
        "federal_withholding": fit,
        "state_withholding": sit,
        "social_security_employee": tax["social_security_employee"],
        "medicare_employee": tax["medicare_employee"],
        "other_deductions": other,
        "net": net,
        "employer_social_security": tax["employer_social_security"],
        "employer_medicare": tax["employer_medicare"],
        "employer_futa": tax["employer_futa"],
        "employer_suta": None if employer_suta is None else _r(float(employer_suta)),
        "calc_status": "manual" if complete else "needs_calculation",
    }


# ─── Run totals + the deposit summary ───────────────────────────────

def run_totals(items: list[Dict[str, Any]]) -> Dict[str, Any]:
    """What the owner pays out and what they must deposit, from the items.

    federal_941 = the trust-fund deposit: income tax withheld + BOTH halves
    of Social Security and Medicare. It goes through EFTPS in the
    employer's own name. FUTA is deposited separately (quarterly once it
    passes $500). State withholding goes to the state's portal.
    """
    def s(key: str) -> float:
        return _r(sum(float(i.get(key) or 0) for i in items))

    fit, sit = s("federal_withholding"), s("state_withholding")
    ss_e, ss_r = s("social_security_employee"), s("employer_social_security")
    med_e, med_r = s("medicare_employee"), s("employer_medicare")
    gross, net = s("gross"), s("net")
    futa, suta = s("employer_futa"), s("employer_suta")
    incomplete = sum(1 for i in items if (i.get("calc_status") or "") == "needs_calculation")

    return {
        "employees": len(items),
        "gross": gross,
        "net": net,
        "federal_withholding": fit,
        "state_withholding": sit,
        "social_security_employee": ss_e,
        "medicare_employee": med_e,
        "employer_social_security": ss_r,
        "employer_medicare": med_r,
        "employer_futa": futa,
        "employer_suta": suta,
        "employer_cost": _r(gross + ss_r + med_r + futa + suta),
        "deposits": {
            "federal_941": _r(fit + ss_e + ss_r + med_e + med_r),
            "federal_940_futa": futa,
            "state_withholding": sit,
            "state_unemployment": suta,
        },
        "needs_calculation": incomplete,
    }
