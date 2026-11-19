"""A database stand-in for the Payroll, the free version tests (not a test file).

FakeSB (test_i2_gl_sync) with what these doors lean on: uuid ids, `order`
and `limit` honoured, a patch that answers with the rows it changed, the two
new tables' unique keys (an upsert merges, an ignore-duplicates insert
answers []), and a table that can be "missing" (the migration not applied:
reads and writes answer None, as PostgREST's error does through sb_clients).

Every name and figure here is made up.
"""
from __future__ import annotations

import pathlib
import sys
import uuid
from datetime import date
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from test_i2_gl_sync import FakeSB, _parse  # noqa: E402

import payroll_calc  # noqa: E402

UNIQUE = {"payroll_deposits": ("business_id", "key"),
          "payroll_reminders_sent": ("business_id", "key", "audience")}


def uid() -> str:
    return str(uuid.uuid4())


CHURCH, OTHER, SHOP = uid(), uid(), uid()
OWNER, ADMIN, MANAGER, MEMBER, VIEWER, ACCOUNTANT, STRANGER, OTHER_OWNER, SHOP_OWNER, SHOP_VIEWER = (
    uid() for _ in range(10))


class PayrollFake(FakeSB):
    def __init__(self) -> None:
        super().__init__()
        self.missing: set = set()
        self.reads: List[str] = []
        self.err: Optional[Dict[str, Any]] = None

    @staticmethod
    def _table(path: str) -> str:
        return path.split("?", 1)[0].lstrip("/")

    @staticmethod
    def _param(path: str, name: str) -> Optional[str]:
        q = path.split("?", 1)[1] if "?" in path else ""
        for part in q.split("&"):
            if part.startswith(name + "="):
                return part.split("=", 1)[1]
        return None

    def get(self, path: str, redact: bool = False):  # noqa: D401 — sb_get_as_service's shape
        path = unquote(path)                     # PostgREST decodes each value; FakeSB doesn't
        self.reads.append(path)
        table = self._table(path)
        if table in self.missing:
            self.err = {"status": 404, "code": "PGRST205", "message": "missing"}
            return None
        self.err = None
        rows = super().get(path)
        order = self._param(path, "order")
        if order:
            for spec in reversed(order.split(",")):
                col, _, way = spec.partition(".")
                rows.sort(key=lambda r: (r.get(col) is None, str(r.get(col) or "")), reverse=(way == "desc"))
        limit = self._param(path, "limit")
        if limit and limit.isdigit():
            rows = rows[:int(limit)]
        return rows

    def post(self, path: str, body: Dict[str, Any], prefer: Optional[str] = "return=representation", **_kw):
        table = self._table(path)
        if table.startswith("rpc/"):
            return self.rpc(table[4:], body)
        if table in self.missing:
            self.err = {"status": 404, "code": "PGRST205", "message": "missing"}
            return None
        row = dict(body)
        row.setdefault("id", uid())
        keys = UNIQUE.get(table)
        if keys:
            same = [r for r in self.rows(table) if all(str(r.get(k)) == str(row.get(k)) for k in keys)]
            if same:
                if "ignore-duplicates" in (prefer or ""):
                    return []
                if "merge-duplicates" in (prefer or ""):
                    same[0].update({k: v for k, v in row.items() if k != "id"})
                    return [dict(same[0])]
                self.err = {"status": 409, "code": "23505", "message": "duplicate"}
                return None
        self.rows(table).append(row)
        return [dict(row)]

    def patch(self, path: str, body: Dict[str, Any], **_kw):
        table, cons = _parse(unquote(path))
        if table in self.missing:
            return None
        hit = self._match(table, cons)
        for r in hit:
            r.update(body)
        return [dict(r) for r in hit]

    def delete(self, path: str):
        if self._table(path) in self.missing:
            return False
        return super().delete(unquote(path))


def install(monkeypatch, db: PayrollFake) -> PayrollFake:
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", db.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", db.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", db.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", db.delete)
    monkeypatch.setattr(sb_clients, "last_error", lambda: db.err)
    import payroll_deposits
    payroll_deposits.forget_ready()
    import audit_log
    import event_spine
    monkeypatch.setattr(audit_log, "record", lambda *a, **k: True)
    monkeypatch.setattr(event_spine, "emit", lambda *a, **k: True)
    import member_asks
    monkeypatch.setattr(member_asks, "_OWNER_CACHE", {})
    monkeypatch.setattr(member_asks, "platform_church", lambda biz: False)
    import housing_allowance
    monkeypatch.setattr(housing_allowance, "switched_on", lambda biz: True)
    for k in ("CHURCH_MONEY_TICKS", "PAYROLL_STUB_EMAIL", "PAYROLL_REMINDERS", "SYMMETRY_API_KEY",
              "HOUSING_ALLOWANCE"):
        monkeypatch.delenv(k, raising=False)
    return db


def user(u: str) -> SimpleNamespace:
    return SimpleNamespace(id=u, email=f"{u[:6]}@example.test")


def seed(db: PayrollFake) -> PayrollFake:
    """Grace Harbor Church (made up): an owner, an Admin, a Manager, a Member,
    a Viewer and an outside accountant; another church; and a barbershop."""
    db.rows("businesses").extend([
        {"id": CHURCH, "name": "Grace Harbor Church", "type": "church", "owner_id": OWNER,
         "settings": {"brand_kit": {"colors": {"primary": "#0f766e"}}}},
        {"id": OTHER, "name": "Cedar Hill Fellowship", "type": "church", "owner_id": OTHER_OWNER, "settings": {}},
        {"id": SHOP, "name": "Corner Fade Barbers", "type": "barber", "owner_id": SHOP_OWNER, "settings": {}},
    ])
    for u, role in ((ADMIN, "admin"), (MANAGER, "manager"), (MEMBER, "member"), (VIEWER, "viewer")):
        db.rows("business_users").append({"id": uid(), "business_id": CHURCH, "user_id": u, "role": role,
                                          "status": "active", "invited_email": f"{role}@graceharbor.example"})
    db.rows("business_users").append({"id": uid(), "business_id": SHOP, "user_id": SHOP_VIEWER, "role": "viewer",
                                      "status": "active", "invited_email": "chair@cornerfade.example"})
    db.rows("business_collaborators").append({"id": uid(), "business_id": CHURCH, "user_id": ACCOUNTANT,
                                              "status": "active", "role": "accountant"})
    for t in ("employees", "employee_tax_profiles", "pay_runs", "pay_run_items", "payroll_deposits",
              "payroll_reminders_sent", "minister_housing_allowances", "minister_housing_entries",
              "contractors", "bills", "push_subscriptions", "church_money_holders"):
        db.rows(t)
    return db


PASTOR = uid()
STAFF = uid()
HOURLY = uid()


def people(db: PayrollFake, biz: str = CHURCH) -> None:
    db.rows("employees").extend([
        {"id": PASTOR, "business_id": biz, "first_name": "Marcus", "last_name": "Ellwood", "status": "active",
         "pay_type": "salary", "pay_rate": 72000.0, "pay_frequency": "monthly", "work_state": "OH",
         "minister": True, "minister_credential": "ordained", "housing_allowance_per_period": 2000.0,
         "email": "marcus@graceharbor.example", "direct_deposit_consented_at": "2026-01-02T00:00:00Z",
         "title": "Senior pastor"},
        {"id": STAFF, "business_id": biz, "first_name": "Dana", "last_name": "Reyes", "status": "active",
         "pay_type": "salary", "pay_rate": 52000.0, "pay_frequency": "biweekly", "work_state": "OH",
         "email": "dana@graceharbor.example"},
    ])
    db.rows("employee_tax_profiles").extend([
        {"employee_id": PASTOR, "business_id": biz, "ssn_last4": "5508", "ssn_encrypted": "gAAAA-SECRET-CIPHER",
         "address": {"line1": "12 Elm St", "city": "Dayton", "state": "OH", "zip": "45402"},
         "w4_signed_at": "2026-01-02T00:00:00Z"},
        {"employee_id": STAFF, "business_id": biz, "ssn_last4": "4321", "ssn_encrypted": "gAAAA-OTHER-CIPHER",
         "address": {}, "w4_signed_at": "2026-01-02T00:00:00Z"},
    ])


def run(db: PayrollFake, pay_date: str, status: str = "paid", biz: str = CHURCH, *,
        lines: Optional[List[Dict[str, Any]]] = None, period: Optional[tuple] = None) -> Dict[str, Any]:
    """A run with lines computed by payroll_calc (as the router would)."""
    pd = date.fromisoformat(pay_date)
    r = {"id": uid(), "business_id": biz, "status": status, "pay_date": pay_date,
         "period_start": (period or (f"{pd:%Y-%m}-01", pay_date))[0],
         "period_end": (period or (f"{pd:%Y-%m}-01", pay_date))[1], "totals": {}}
    db.rows("pay_runs").append(r)
    items = []
    for ln in lines or []:
        emp = next(e for e in db.rows("employees") if e["id"] == ln["employee_id"])
        calc = payroll_calc.compute_item(
            employee=emp, hours=ln.get("hours", 0), overtime_hours=ln.get("overtime_hours", 0),
            ytd_gross_before=ln.get("ytd", 0.0), year=pd.year, federal_withholding=ln.get("fit"),
            state_withholding=ln.get("sit"), housing_allowance=emp.get("housing_allowance_per_period"),
            church=True)
        item = {"id": uid(), "pay_run_id": r["id"], "business_id": biz, "employee_id": emp["id"], **calc,
                "calc_payload": {"pay": {"type": emp["pay_type"], "rate": float(emp["pay_rate"]),
                                         "frequency": emp["pay_frequency"]}},
                "created_at": f"{pay_date}T12:00:00Z"}
        db.rows("pay_run_items").append(item)
        items.append(item)
    r["totals"] = payroll_calc.run_totals(items)
    return r


def standard_lines(ytd_staff: float = 0.0) -> List[Dict[str, Any]]:
    """The pastor (minister, $6,000 a month, $2,000 of it housing, $500
    federal asked for, $100 state) and Dana ($2,000 a check, $150 federal,
    $40 state, FICA computed)."""
    return [{"employee_id": PASTOR, "fit": 500.0, "sit": 100.0},
            {"employee_id": STAFF, "fit": 150.0, "sit": 40.0, "ytd": ytd_staff}]


def designate(db: PayrollFake, amount: float = 24000.0, on: str = "2025-12-14", year: int = 2026) -> Dict[str, Any]:
    row = {"id": uid(), "business_id": CHURCH, "minister_name": "Pastor Marcus Ellwood", "tax_year": year,
           "designated_amount": amount, "designated_on": on, "employee_id": PASTOR, "contact_id": None,
           "board_decision_id": None, "fair_rental_value": None, "notes": "", "archived_at": None}
    db.rows("minister_housing_allowances").append(row)
    return row


def ticks(monkeypatch, holders: Dict[str, Dict[str, Any]], mode: str = "on", platform: Optional[str] = None):
    """The giving tick, as church_money_ticks.holder would answer it."""
    import church_money_ticks
    import member_asks
    monkeypatch.setenv("CHURCH_MONEY_TICKS", mode)
    if platform is not None:
        monkeypatch.setattr(member_asks, "platform_church", lambda biz: str(biz) == platform)
    monkeypatch.setattr(church_money_ticks, "holder",
                        lambda biz, u: (holders.get(str(u)) if church_money_ticks.open_for(biz) else None))


def tick(level: str, seat: str = "manager") -> Dict[str, Any]:
    return {"level": level, "can_work": level in ("work", "lead") and seat != "viewer", "who_gave": False,
            "bank": False, "seat_role": seat}
