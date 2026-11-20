"""payroll_calendar.py — Pay staff's deposit calendar (Payroll, the free version, 2026-11-19).

Kevin, 2026-11-19: "build the free version now". The church pays its people
from its own bank and sends its own tax deposits; Solutionist prepares the
numbers and says WHEN each thing is due. Nothing here moves money or files
anything. This module is the "when": every payday, approve-by day, federal
and state deposit, form due date and bank holiday, worked out from the pay
runs, and the payroll settings those dates depend on.

    THE DATES ...... pure functions, each citing where its rule comes from:
                     bank days (Federal Reserve holidays), IRS days (legal
                     holidays in the District of Columbia), the monthly and
                     semiweekly deposit rules, Form 941 and the January forms
    THE SETTINGS ... businesses.settings.payroll {deposit_schedule, state_day,
                     state_label}, written by the server alone through
                     business_settings.merge (never a client's settings blob)
    THE CALENDAR ... month_view(): GET /payroll/calendar's answer. The events
                     themselves come from build_events(), which the reminders
                     (payroll_reminders.py) read too, so a reminder and the
                     calendar can never disagree about a date

Status words: "open" (still to do), "sent" (a deposit or form marked sent,
payroll_deposits.py), "done" (a paid run's payday, an approved run's
approve-by), null (projected, or a holiday).
"""
from __future__ import annotations

import calendar as _cal
import re
from datetime import date, timedelta
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Tuple

MONTHLY, SEMIWEEKLY = "monthly", "semiweekly"
SCHEDULES = (MONTHLY, SEMIWEEKLY)
SETTINGS_KEY = "payroll"
DEFAULT_SETTINGS = {"deposit_schedule": MONTHLY, "state_day": None, "state_label": None}

MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
QUARTER_WORDS = {1: "January to March", 2: "April to June", 3: "July to September", 4: "October to December"}

KINDS = ("holiday", "payday", "approve", "deposit_federal", "deposit_state", "forms")
_KIND_ORDER = {k: i for i, k in enumerate(KINDS)}
# What a reminder, `next` and `later` look at: things someone has to do.
TO_DO = ("approve", "deposit_federal", "deposit_state", "forms")

APPROVE_BANK_DAYS = 2        # a bank's direct deposit file wants two business days
PROJECT_MONTHS = 3           # projected paydays never reach further than this past today
LATER_DAYS = 92              # `later` looks this far past the month
LATER_MAX = 6
NEXT_DAYS = 400              # `next` looks this far ahead (a January form from February)

# fullmatch only: "$" would let a trailing newline by.
KEY_RE = re.compile(r"(federal:[0-9]{4}-[0-9]{2}(?:-[0-9]{2})?|state:[0-9]{4}-[0-9]{2}|forms:941:[0-9]{4}Q[1-4]"
                    r"|forms:w2:[0-9]{4})")


# ─── Words ────────────────────────────────────────────────────────────

def money(x: Optional[float]) -> str:
    return "" if x is None else f"${float(x):,.2f}"


def short_day(d: date) -> str:
    """"Dec 15"."""
    return f"{MONTHS[d.month - 1][:3]} {d.day}"


def day_words(d: date) -> str:
    """"Tue, Dec 15"."""
    return f"{DAYS[d.weekday()][:3]}, {short_day(d)}"


def long_day(d: date) -> str:
    """"Monday, November 30, 2026"."""
    return f"{DAYS[d.weekday()]}, {MONTHS[d.month - 1]} {d.day}, {d.year}"


def _r(x: float) -> float:
    return round(float(x or 0) + 1e-9, 2)


# ─── Holidays ─────────────────────────────────────────────────────────

def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year, month, _cal.monthrange(year, month)[1])
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _federal_holidays(year: int) -> List[Tuple[date, str]]:
    """The eleven federal holidays on their calendar dates (5 U.S.C.
    6103(a)); the Federal Reserve closes for the same eleven."""
    return [
        (date(year, 1, 1), "New Year’s Day"),
        (_nth_weekday(year, 1, 0, 3), "Martin Luther King Jr. Day"),
        (_nth_weekday(year, 2, 0, 3), "Washington’s Birthday"),
        (_last_weekday(year, 5, 0), "Memorial Day"),
        (date(year, 6, 19), "Juneteenth"),
        (date(year, 7, 4), "Independence Day"),
        (_nth_weekday(year, 9, 0, 1), "Labor Day"),
        (_nth_weekday(year, 10, 0, 2), "Columbus Day"),
        (date(year, 11, 11), "Veterans Day"),
        (_nth_weekday(year, 11, 3, 4), "Thanksgiving"),
        (date(year, 12, 25), "Christmas"),
    ]


@lru_cache(maxsize=64)
def bank_holidays(year: int) -> Dict[date, str]:
    """The days the banks are closed for a holiday: the Federal Reserve's
    holiday schedule (federalreserve.gov/aboutthefed/k8.htm). A holiday on a
    Sunday is observed the Monday after. On a Saturday the Reserve Banks are
    OPEN the Friday before, so it closes nothing a weekend doesn't already
    (shown on its own Saturday)."""
    out: Dict[date, str] = {}
    for d, name in _federal_holidays(year):
        if d.weekday() == 6:
            out[d + timedelta(days=1)] = f"{name} (observed)"
        else:
            out[d] = name
    return out


@lru_cache(maxsize=64)
def irs_holidays(year: int) -> Dict[date, str]:
    """The legal holidays that move a federal tax deposit or a return's due
    date: "any legal holiday in the District of Columbia" (IRS Publication
    15 (Circular E), "Legal holidays"; IRC 7503). That is the federal
    holidays, DC Emancipation Day (April 16) and Inauguration Day (January 20
    after a presidential election). One on a Saturday is observed the Friday
    before and one on a Sunday the Monday after (D.C. Code 28-2701, 5 U.S.C.
    6103(b)), so a Saturday New Year's Day is a holiday on December 31 of the
    year before: hence the three years read here. Inauguration Day has no
    Friday: on a Sunday it moves to the Monday (5 U.S.C. 6103(c))."""
    out: Dict[date, str] = {}
    for y in (year - 1, year, year + 1):
        for d, name in _federal_holidays(y) + [(date(y, 4, 16), "DC Emancipation Day")]:
            if d.weekday() == 5:
                d -= timedelta(days=1)
            elif d.weekday() == 6:
                d += timedelta(days=1)
            if d.year == year:
                out.setdefault(d, name)
        if y % 4 == 1:                                    # 2029, 2033: the January after the election
            inaug = date(y, 1, 20)
            if inaug.weekday() == 6:
                inaug += timedelta(days=1)
            if inaug.weekday() < 5 and inaug.year == year:
                out.setdefault(inaug, "Inauguration Day")
    return out


def is_bank_day(d: date) -> bool:
    return d.weekday() < 5 and d not in bank_holidays(d.year)


def is_irs_day(d: date) -> bool:
    """A business day for a federal deposit: not a Saturday, Sunday or legal
    holiday (Publication 15, "Deposits on business days only")."""
    return d.weekday() < 5 and d not in irs_holidays(d.year)


def roll(d: date) -> date:
    """A due date on a weekend or legal holiday moves to the next business
    day (Publication 15, "Deposits on business days only"; for Form 941, its
    instructions, "If any due date for filing falls on a Saturday, Sunday, or
    legal holiday, you may file your return on the next business day"; for
    W-2/W-3 and 1099-NEC, the General Instructions for Forms W-2 and W-3 and
    the Instructions for Forms 1099-MISC and 1099-NEC say the same)."""
    while not is_irs_day(d):
        d += timedelta(days=1)
    return d


def approve_by(payday: date) -> date:
    """Two bank business days before payday (weekends and Federal Reserve
    holidays skipped), so a bank's direct deposit has time to settle."""
    d, n = payday, 0
    while n < APPROVE_BANK_DAYS:
        d -= timedelta(days=1)
        if is_bank_day(d):
            n += 1
    return d


def previous_bank_day(d: date) -> date:
    while not is_bank_day(d):
        d -= timedelta(days=1)
    return d


def _next_month(year: int, month: int) -> Tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def add_months(d: date, n: int) -> date:
    y, m = d.year, d.month
    for _ in range(n):
        y, m = _next_month(y, m)
    return date(y, m, min(d.day, _cal.monthrange(y, m)[1]))


# ─── The deposit and filing rules ─────────────────────────────────────

def monthly_due(year: int, month: int) -> date:
    """A monthly schedule depositor deposits the taxes on payments made in a
    month by the 15th of the following month (IRS Publication 15, "Monthly
    Deposit Schedule"), moved past a weekend or legal holiday."""
    y, m = _next_month(year, month)
    return roll(date(y, m, 15))


def semiweekly_period_end(pay_date: date) -> date:
    """The last day of the semiweekly period a payday falls in: Wednesday to
    Friday, or Saturday to Tuesday (Publication 15, "Semiweekly Deposit
    Schedule")."""
    wd = pay_date.weekday()
    if wd in (2, 3, 4):
        return pay_date + timedelta(days=4 - wd)          # the Friday
    return pay_date + timedelta(days=(1 - wd) % 7)       # the Tuesday


def semiweekly_due(pay_date: date) -> date:
    """A semiweekly schedule depositor deposits taxes on payments made
    Wednesday, Thursday or Friday by the following Wednesday, and on
    Saturday, Sunday, Monday or Tuesday by the following Friday (Publication
    15, "Semiweekly Deposit Schedule"). Publication 15 also gives "at least 3
    business days following the close of the semiweekly period", one more
    for each legal holiday among those three weekdays: so the due date is
    the third business day after the period closes. Without a holiday that
    is exactly the Wednesday or the Friday; with one (payday Friday, Monday
    a holiday) it is the Thursday, as Publication 15's own example says."""
    d, n = semiweekly_period_end(pay_date), 0
    while n < 3:
        d += timedelta(days=1)
        if is_irs_day(d):
            n += 1
    return d


def roll_bank(d: date) -> date:
    """The next bank business day on or after `d` (weekends and Federal
    Reserve holidays skipped)."""
    while not is_bank_day(d):
        d += timedelta(days=1)
    return d


def state_due(year: int, month: int, day: int) -> date:
    """The state's withholding deposit: the day of the following month the
    church set (its state publishes it), moved past a weekend or a BANK
    holiday (the Federal Reserve's). A state's deadlines don't follow the
    District of Columbia's holidays, so DC Emancipation Day or a Friday
    "observed" holiday the banks stay open on doesn't move them."""
    y, m = _next_month(year, month)
    return roll_bank(date(y, m, day))


def eftps_by(due: date) -> date:
    """The day an EFTPS payment must be submitted for a deposit due on
    `due`: by 8 p.m. Eastern the calendar day before (IRS Publication 15,
    "How To Deposit": "you must submit the deposit by 8 p.m. Eastern time
    the day before the date the deposit is due")."""
    return due - timedelta(days=1)


def eftps_words(due: date) -> str:
    """"Submit it on EFTPS by 8 p.m. Eastern on Mon, Dec 14.\""""
    return f"Submit it on EFTPS by 8 p.m. Eastern on {day_words(eftps_by(due))}."


def quarter_of(d: date) -> int:
    return (d.month - 1) // 3 + 1


def form_941_raw(year: int, q: int) -> date:
    """Form 941 is due the last day of the month after the quarter: April 30,
    July 31, October 31 and January 31 (Instructions for Form 941, "When
    Must You File?")."""
    y, m = _next_month(year, q * 3)
    return date(y, m, _cal.monthrange(y, m)[1])


def form_941_due(year: int, q: int) -> date:
    return roll(form_941_raw(year, q))


def year_end_raw(year: int) -> date:
    """W-2s to each employee, W-2s and the W-3 to the Social Security
    Administration, and 1099-NEC to each contractor and the IRS: all by
    January 31 (General Instructions for Forms W-2 and W-3, "When to file";
    Instructions for Forms 1099-MISC and 1099-NEC, "Due dates")."""
    return date(year + 1, 1, 31)


def year_end_due(year: int) -> date:
    return roll(year_end_raw(year))


def rolled_words(raw: date, due: date, it: str = "it’s") -> str:
    """"January 31 is a Sunday, so they’re due Monday, Feb 1.", or "" when it
    didn't move."""
    if raw == due:
        return ""
    why = "a holiday" if raw.weekday() < 5 else f"a {DAYS[raw.weekday()]}"
    return f"{MONTHS[raw.month - 1]} {raw.day} is {why}, so {it} due {DAYS[due.weekday()]}, {short_day(due)}."


# ─── Keys ─────────────────────────────────────────────────────────────

def federal_key(schedule: str, pay_date: date) -> str:
    return f"federal:{pay_date.isoformat()}" if schedule == SEMIWEEKLY else f"federal:{pay_date:%Y-%m}"


def state_key(year: int, month: int) -> str:
    return f"state:{year:04d}-{month:02d}"


def forms_941_key(year: int, q: int) -> str:
    return f"forms:941:{year}Q{q}"


def forms_w2_key(year: int) -> str:
    return f"forms:w2:{year}"


def parse_key(key: Any) -> Optional[Dict[str, Any]]:
    """{kind, period, ...} for a deposit or forms key, or None when it isn't
    one (the shape, and a real date)."""
    k = key if isinstance(key, str) else ""
    if not KEY_RE.fullmatch(k):
        return None
    try:
        if k.startswith("federal:"):
            rest = k[8:]
            if len(rest) == 10:
                d = date.fromisoformat(rest)
                return {"kind": "federal", "period": rest, "pay_date": d, "schedule": SEMIWEEKLY}
            y, m = int(rest[:4]), int(rest[5:7])
            date(y, m, 1)
            return {"kind": "federal", "period": rest, "year": y, "month": m, "schedule": MONTHLY}
        if k.startswith("state:"):
            y, m = int(k[6:10]), int(k[11:13])
            date(y, m, 1)
            return {"kind": "state", "period": k[6:], "year": y, "month": m}
        if k.startswith("forms:941:"):
            y, q = int(k[10:14]), int(k[15])
            return {"kind": "forms", "period": f"{y}Q{q}", "year": y, "q": q, "form": "941"}
        y = int(k[9:13])
        return {"kind": "forms", "period": str(y), "year": y, "form": "w2"}
    except ValueError:
        return None


def due_for(parsed: Dict[str, Any], settings: Dict[str, Any]) -> Optional[date]:
    """The due date a parsed key names (a state key needs the state's day)."""
    if parsed["kind"] == "federal":
        if parsed["schedule"] == SEMIWEEKLY:
            return semiweekly_due(parsed["pay_date"])
        return monthly_due(parsed["year"], parsed["month"])
    if parsed["kind"] == "state":
        day = settings.get("state_day")
        return state_due(parsed["year"], parsed["month"], int(day)) if day else None
    if parsed.get("form") == "941":
        return form_941_due(parsed["year"], parsed["q"])
    return year_end_due(parsed["year"])


# ─── Settings ─────────────────────────────────────────────────────────

def settings_of(biz_row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    raw = ((biz_row or {}).get("settings") or {})
    raw = raw.get(SETTINGS_KEY) if isinstance(raw, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULT_SETTINGS)
    if raw.get("deposit_schedule") in SCHEDULES:
        out["deposit_schedule"] = raw["deposit_schedule"]
    day = raw.get("state_day")
    if isinstance(day, int) and not isinstance(day, bool) and 1 <= day <= 28:
        out["state_day"] = day
    label = raw.get("state_label")
    if isinstance(label, str) and label.strip():
        out["state_label"] = clean_label(label)
    return out


_CTRL = re.compile(r"[\x00-\x1f\x7f<>]")


def clean_label(v: Any) -> str:
    return re.sub(r"\s+", " ", _CTRL.sub(" ", str(v or ""))).strip()[:60]


def settings_patch(given: Dict[str, Any]) -> Dict[str, Any]:
    """The keys a PUT may write, checked. ValueError names what's wrong."""
    out: Dict[str, Any] = {}
    if "deposit_schedule" in given:
        if given["deposit_schedule"] not in SCHEDULES:
            raise ValueError("deposit_schedule must be monthly or semiweekly")
        out["deposit_schedule"] = given["deposit_schedule"]
    if "state_day" in given:
        day = given["state_day"]
        if day is not None and (isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= 28):
            raise ValueError("state_day must be a day of the month from 1 to 28")
        out["state_day"] = day
    if "state_label" in given:
        label = clean_label(given["state_label"]) if given["state_label"] is not None else ""
        out["state_label"] = label or None
    return out


def save_settings(business_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Write the payroll settings as the server, touching only these keys.
    The settings after it, or None when it didn't save."""
    import business_settings
    after = business_settings.merge(business_id, set=patch, under=[SETTINGS_KEY])
    if after is None:
        return None
    return settings_of({"settings": after})


# ─── Projected paydays ────────────────────────────────────────────────

def _next_payday(d: date, freq: str, anchor: date) -> date:
    if freq == "weekly":
        return d + timedelta(days=7)
    if freq == "semimonthly":
        end = _cal.monthrange(d.year, d.month)[1]
        if d.day < 15:
            return date(d.year, d.month, 15)
        if d.day < end:
            return date(d.year, d.month, end)
        y, m = _next_month(d.year, d.month)
        return date(y, m, 15)
    if freq == "monthly":
        y, m = _next_month(d.year, d.month)
        last = _cal.monthrange(y, m)[1]
        month_end = anchor.day == _cal.monthrange(anchor.year, anchor.month)[1]
        return date(y, m, last if month_end else min(anchor.day, last))
    return d + timedelta(days=14)                      # biweekly, and anything unknown


def projected_paydays(latest: Optional[date], frequencies: Iterable[str], until: date,
                      taken: Iterable[date] = ()) -> List[date]:
    """The paydays after the latest run, on each active person's pay
    frequency, up to `until`, moved back off a weekend or bank holiday the
    way a payroll is, never on a day a real run already has. A guess, and
    every one says so ("projected")."""
    if latest is None:
        return []
    have = set(taken)
    out = set()
    for freq in sorted(set(f for f in frequencies if f)):
        d = latest
        for _ in range(600):                           # weekly for over ten years; then it stops
            d = _next_payday(d, freq, latest)
            if d > until:
                break
            shown = previous_bank_day(d)
            if shown > latest and shown not in have:
                out.add(shown)
    return sorted(out)


# ─── The events ───────────────────────────────────────────────────────

def _day(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


def _deposits_of(run: Dict[str, Any]) -> Dict[str, float]:
    t = run.get("totals") if isinstance(run.get("totals"), dict) else {}
    dep = t.get("deposits") if isinstance(t.get("deposits"), dict) else {}
    return {"federal": _r(dep.get("federal_941") or 0), "state": _r(dep.get("state_withholding") or 0),
            "net": _r(t.get("net") or 0), "employees": int(t.get("employees") or 0)}


def _ev(kind: str, on: date, title: str, sub: str, *, amount: Optional[float] = None, run_id: Any = None,
        key: Optional[str] = None, status: Optional[str] = None) -> Dict[str, Any]:
    return {"date": on, "kind": kind, "title": title, "sub": sub,
            "amount": None if amount is None else _r(amount), "run_id": str(run_id) if run_id else None,
            "deposit_key": key, "status": status}


def _people(n: int) -> str:
    return "1 person" if n == 1 else f"{n} people"


def build_events(*, runs: List[Dict[str, Any]], settings: Dict[str, Any], marked: Dict[str, Any],
                 frequencies: Iterable[str], latest: Optional[date], start: date, end: date, today: date,
                 church: bool = True) -> List[Dict[str, Any]]:
    """Every calendar event dated start..end. `runs`: the business's
    non-cancelled runs (id, status, pay_date, totals), wide enough to cover
    the deposits and forms that fall in the range. `marked`: deposit key →
    its payroll_deposits row (a key there is "sent"). `latest`: the latest
    non-cancelled run's pay date, the projection's starting point."""
    schedule = settings.get("deposit_schedule") or MONTHLY
    state_day = settings.get("state_day")
    state_label = settings.get("state_label") or "State withholding"
    real: List[Tuple[date, Dict[str, Any]]] = []
    for r in runs:
        pd = _day(r.get("pay_date"))
        if pd and r.get("status") in ("draft", "approved", "paid"):
            real.append((pd, r))
    real.sort(key=lambda x: (x[0], str(x[1].get("id"))))
    until = add_months(today, PROJECT_MONTHS)
    # A guess about what's ahead: a payday before today with no run is one
    # that didn't happen, never a projection.
    projected = [d for d in projected_paydays(latest, frequencies, min(until, end + timedelta(days=45)),
                                              taken=[pd for pd, _ in real]) if d >= today]
    out: List[Dict[str, Any]] = []

    # Paydays and approve-by days.
    for pd, r in real:
        status = r.get("status")
        d = _deposits_of(r)
        final = status in ("approved", "paid")
        sub = (f"{money(d['net'])} to {_people(d['employees'])}" if final and d["employees"]
               else _people(d["employees"]) if d["employees"] else "")
        out.append(_ev("payday", pd, "Payday", sub, amount=d["net"] if final else None, run_id=r.get("id"),
                       status="done" if status == "paid" else "open"))
        out.append(_ev("approve", approve_by(pd), f"Approve the {short_day(pd)} run",
                       "two bank days before payday, in time for direct deposit", run_id=r.get("id"),
                       status="done" if final else "open"))
    for pd in projected:
        out.append(_ev("payday", pd, "Payday", "projected"))
        out.append(_ev("approve", approve_by(pd), f"Approve the {short_day(pd)} run", "projected"))

    # Federal deposits: income tax withheld and both halves of Social
    # Security and Medicare, from the approved and paid runs each covers
    # (payroll_calc.run_totals' federal_941).
    groups: Dict[str, Dict[str, Any]] = {}
    for pd, r in real:
        g = groups.setdefault(federal_key(schedule, pd), {"pd": pd, "runs": [], "projected": False})
        g["runs"].append(r)
    for pd in projected:
        groups.setdefault(federal_key(schedule, pd), {"pd": pd, "runs": [], "projected": True})
    for key, g in groups.items():
        pd = g["pd"]
        due = semiweekly_due(pd) if schedule == SEMIWEEKLY else monthly_due(pd.year, pd.month)
        final = [r for r in g["runs"] if r.get("status") in ("approved", "paid")]
        amount = _r(sum(_deposits_of(r)["federal"] for r in final)) if final else None
        for_words = (f"for the {short_day(pd)} payday" if schedule == SEMIWEEKLY else f"for {MONTHS[pd.month - 1]}")
        status = "sent" if key in marked else ("open" if g["runs"] else None)
        about = for_words + ("" if g["runs"] else ", projected")
        ev = _ev("deposit_federal", due, "IRS deposit", f"{about}. {eftps_words(due)}", amount=amount, key=key,
                 status=status)
        ev["_for"] = about                         # the reminders' own words; never in the answer
        out.append(ev)

    # State withholding: only once the church has set its state's day.
    if state_day:
        months: Dict[Tuple[int, int], Dict[str, Any]] = {}
        for pd, r in real:
            months.setdefault((pd.year, pd.month), {"runs": []})["runs"].append(r)
        for pd in projected:
            months.setdefault((pd.year, pd.month), {"runs": []})
        for (y, m), g in months.items():
            key = state_key(y, m)
            final = [r for r in g["runs"] if r.get("status") in ("approved", "paid")]
            amount = _r(sum(_deposits_of(r)["state"] for r in final)) if final else None
            status = "sent" if key in marked else ("open" if g["runs"] else None)
            out.append(_ev("deposit_state", state_due(y, m, int(state_day)), state_label,
                           f"for {MONTHS[m - 1]}" + ("" if g["runs"] else ", projected"),
                           amount=amount, key=key, status=status))

    # Forms: each quarter's 941 and each year's W-2s, W-3 and 1099-NEC.
    quarters: Dict[Tuple[int, int], bool] = {}
    years: Dict[int, bool] = {}
    for pd, _r_ in real:
        quarters[(pd.year, quarter_of(pd))] = True
        years[pd.year] = True
    for pd in projected:
        quarters.setdefault((pd.year, quarter_of(pd)), False)
        years.setdefault(pd.year, False)
    for (y, q), has_real in quarters.items():
        key = forms_941_key(y, q)
        raw, due = form_941_raw(y, q), form_941_due(y, q)
        sub = f"for {QUARTER_WORDS[q]}" + ("" if has_real else ", projected")
        moved = rolled_words(raw, due)
        out.append(_ev("forms", due, "Form 941", f"{sub}. {moved}" if moved else sub, key=key,
                       status="sent" if key in marked else ("open" if has_real else None)))
    for y, has_real in years.items():
        key = forms_w2_key(y)
        raw, due = year_end_raw(y), year_end_due(y)
        sub = (f"for {y}: W-2s to each person, W-2s and the W-3 to Social Security, 1099-NEC to "
               f"contractors and the IRS" + ("" if has_real else ", projected"))
        moved = rolled_words(raw, due, "they’re")
        out.append(_ev("forms", due, "W-2s, W-3 and 1099-NEC", f"{sub}. {moved}" if moved else sub, key=key,
                       status="sent" if key in marked else ("open" if has_real else None)))

    # Bank holidays.
    for y in range(start.year, end.year + 1):
        for d, name in bank_holidays(y).items():
            out.append(_ev("holiday", d, name, "banks closed"))

    keep = [e for e in out if start <= e["date"] <= end]
    keep.sort(key=lambda e: (e["date"], _KIND_ORDER[e["kind"]], e["title"]))
    return keep


def public(e: Dict[str, Any]) -> Dict[str, Any]:
    return {k: e[k] for k in ("kind", "title", "sub", "amount", "run_id", "deposit_key", "status")}


# ─── The month's view ─────────────────────────────────────────────────

class Unreadable(Exception):
    """A read the calendar needs failed: never shown as an empty month."""


def parse_month(v: Optional[str], today: date) -> date:
    """The first day of a "YYYY-MM" month (this month when not given).
    ValueError when it isn't one."""
    s = (v or "").strip()
    if not s:
        return date(today.year, today.month, 1)
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", s):
        raise ValueError("month must be YYYY-MM")
    y, m = int(s[:4]), int(s[5:])
    if not (2000 <= y <= 2100 and 1 <= m <= 12):
        raise ValueError("month must be YYYY-MM")
    return date(y, m, 1)


def load(biz: str, lo: date, hi: date) -> Dict[str, Any]:
    """The rows the calendar reads, as the server: the non-cancelled runs
    dated lo..hi, the latest run, the active people's pay frequencies and the
    deposits marked sent. Unreadable when a read fails."""
    import sb_clients
    import payroll_deposits
    from urllib.parse import quote
    b = quote(str(biz), safe="")
    try:
        runs = sb_clients.sb_get_all_as_service(
            f"/pay_runs?business_id=eq.{b}&status=neq.cancelled&pay_date=gte.{lo.isoformat()}"
            f"&pay_date=lte.{hi.isoformat()}&select=id,status,pay_date,totals", strict=True)
    except sb_clients.PartialRead:
        raise Unreadable("pay_runs")
    latest_rows = sb_clients.sb_get_as_service(
        f"/pay_runs?business_id=eq.{b}&status=neq.cancelled&select=id,pay_date&order=pay_date.desc&limit=1")
    people = sb_clients.sb_get_as_service(
        f"/employees?business_id=eq.{b}&status=eq.active&select=id,pay_frequency&limit=1000")
    if not isinstance(latest_rows, list) or not isinstance(people, list):
        raise Unreadable("pay_runs/employees")
    marked, ready = payroll_deposits.marked(biz)
    if marked is None:
        raise Unreadable("payroll_deposits")
    return {"runs": runs or [], "latest": _day(latest_rows[0].get("pay_date")) if latest_rows else None,
            "frequencies": [p.get("pay_frequency") for p in people], "marked": marked, "deposits_ready": ready}


def window(start: date, end: date) -> Tuple[date, date]:
    """The runs that can put an event in start..end: from January 1 of the
    year before (a January's W-2s cover the whole year before) to 45 days
    past the end (an approve-by day falls before its payday)."""
    return date(start.year - 1, 1, 1), end + timedelta(days=45)


def month_view(biz_row: Dict[str, Any], month: Optional[str], today: Optional[date] = None) -> Dict[str, Any]:
    """GET /payroll/calendar's answer for one business."""
    import church_follow_up
    today = today or date.today()
    first = parse_month(month, today)
    last = date(first.year, first.month, _cal.monthrange(first.year, first.month)[1])
    settings = settings_of(biz_row)
    horizon = max(last + timedelta(days=LATER_DAYS), today + timedelta(days=NEXT_DAYS))
    begin = min(first, today)
    lo, hi = window(begin, horizon)
    rows = load(str(biz_row["id"]), lo, hi)
    church = church_follow_up.is_church(biz_row)
    events = build_events(runs=rows["runs"], settings=settings, marked=rows["marked"],
                          frequencies=rows["frequencies"], latest=rows["latest"], start=begin, end=horizon,
                          today=today, church=church)
    days: Dict[date, List[Dict[str, Any]]] = {}
    for e in events:
        if first <= e["date"] <= last:
            days.setdefault(e["date"], []).append(public(e))
    nxt = next((e for e in events if e["date"] >= today and e["status"] == "open" and e["kind"] in TO_DO), None)
    later_events = [e for e in events if last < e["date"] <= last + timedelta(days=LATER_DAYS)
                    and e["kind"] in ("deposit_federal", "deposit_state", "forms") and e["status"] != "sent"]
    later: List[Dict[str, Any]] = [{"date": e["date"].isoformat(), "title": e["title"], "sub": e["sub"]}
                                   for e in later_events[:LATER_MAX]]
    if not settings.get("state_day") and rows["runs"]:
        later.append({"date": None, "title": "Set your state’s due date",
                      "sub": "Your state’s withholding deposit day isn’t set yet. Set it once in the payroll "
                             "settings and it shows here every month."})
    return {
        "ok": True,
        "month": f"{first:%Y-%m}",
        "settings": settings,
        "days": [{"date": d.isoformat(), "events": evs} for d, evs in sorted(days.items())],
        "next": ({"kind": nxt["kind"], "title": nxt["title"], "date": nxt["date"].isoformat(),
                  "amount": nxt["amount"], "deposit_key": nxt["deposit_key"]} if nxt else None),
        "later": later,
        "deposits_ready": rows["deposits_ready"],
    }
