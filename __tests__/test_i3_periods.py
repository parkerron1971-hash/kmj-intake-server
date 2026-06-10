"""Phase I.3 (PR1) — period closing — against an in-memory Supabase fake.
Verifies the annual closing journal entry balances + zeros P&L into Retained
Earnings, idempotency, and reopen-reverses."""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import gl_engine as gl


# ── compact PostgREST-ish in-memory store ───────────────────────────
def _num(x):
    try:
        return float(x)
    except Exception:
        return None


def _passes(row, col, op, target):
    if op in ("is", "not.is"):
        isnull = row.get(col) is None
        return isnull if op == "is" else (not isnull)
    val = row.get(col)
    if val is None:
        return op == "neq"
    if op == "in":
        return str(val) in target.strip("()").split(",")
    if op == "not.in":
        return str(val) not in target.strip("()").split(",")
    if target in ("true", "false"):
        return (bool(val) is (target == "true")) if op == "eq" else (bool(val) is not (target == "true"))
    nv, nt = _num(val), _num(target)
    if nv is not None and nt is not None:
        return {"eq": nv == nt, "neq": nv != nt, "gte": nv >= nt, "lte": nv <= nt, "lt": nv < nt, "gt": nv > nt}.get(op, True)
    sv, st = str(val), str(target)
    return {"eq": sv == st, "neq": sv != st, "gte": sv >= st, "lte": sv <= st, "lt": sv < st, "gt": sv > st}.get(op, True)


def _parse(path):
    table = path.split("?", 1)[0].lstrip("/")
    q = path.split("?", 1)[1] if "?" in path else ""
    cons = []
    for part in q.split("&"):
        if "=" not in part:
            continue
        col, rest = part.split("=", 1)
        if col in ("select", "limit", "order", "on_conflict"):
            continue
        if rest.startswith("not.is."):
            cons.append((col, "not.is", None))
        elif rest.startswith("is."):
            cons.append((col, "is", None))
        elif rest.startswith("not.in."):
            cons.append((col, "not.in", rest[7:]))
        elif rest.startswith("in."):
            cons.append((col, "in", rest[3:]))
        elif "." in rest:
            op, tgt = rest.split(".", 1)
            cons.append((col, op, tgt))
    return table, cons


class FakeSB:
    def __init__(self):
        self.t = {}
        self.n = 0

    def rows(self, table):
        return self.t.setdefault(table, [])

    def _match(self, table, cons):
        return [r for r in self.rows(table) if all(_passes(r, c, o, tg) for c, o, tg in cons)]

    def get(self, path):
        table, cons = _parse(path)
        return [dict(r) for r in self._match(table, cons)]

    def post(self, path, body, prefer="rep"):
        table = path.split("?", 1)[0].lstrip("/")
        row = dict(body)
        if "id" not in row:
            self.n += 1
            row["id"] = f"{table[:3]}_{self.n}"
        self.rows(table).append(row)
        return [dict(row)]

    def patch(self, path, body):
        table, cons = _parse(path)
        for r in self._match(table, cons):
            r.update(body)
        return []


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    fb.rows("businesses").append({"id": "biz1", "type": "consultant", "owner_id": "owner"})
    return fb


def _seed_pnl(fb):
    """Year-period + BALANCED 2026 P&L: revenue 1000 (Dr AR / Cr Rev) and
    expense 300 (Dr Expense / Cr Cash). Net income 700."""
    fb.rows("accounting_periods").append({
        "id": "yr2026", "business_id": "biz1", "period_type": "year",
        "period_start": "2026-01-01", "period_end": "2026-12-31", "status": "open"})
    seed = [("1100", 1000, 0, "asset"), ("4000", 0, 1000, "income"),     # invoice issue
            ("5000", 300, 0, "expense"), ("1000", 0, 300, "asset")]      # expense paid
    for i, (code, deb, cred, typ) in enumerate(seed):
        fb.rows("ledger_entries").append({
            "id": f"l_{i}", "business_id": "biz1", "journal_entry_id": "je0",
            "account_code": code, "account_type": typ, "source_type": "seed",
            "debit": deb, "credit": cred, "entry_date": "2026-06-01"})


def _bal(fb, code, normal):
    s = sum(float(l["debit"]) - float(l["credit"]) for l in fb.rows("ledger_entries")
            if l["account_code"] == code)
    return round(s if normal == "debit" else -s, 2)


def test_generate_periods_idempotent(fake):
    out = gl.generate_periods("biz1", 2026)
    assert out["created"] == 17                     # 12 months + 4 quarters + 1 year
    again = gl.generate_periods("biz1", 2026)
    assert again["created"] == 0


def test_annual_close_posts_balanced_closing_entry(fake):
    _seed_pnl(fake)
    out = gl.close_period("biz1", "yr2026", closed_by="owner", closed_via="owner")
    assert out["closed"] is True and out["closing_journal_entry_id"]
    # Revenue + Expense zeroed; net (1000-300=700) rolled into Retained Earnings.
    assert _bal(fake, "4000", "credit") == 0
    assert _bal(fake, "5000", "debit") == 0
    assert _bal(fake, "3900", "credit") == 700
    # Trial balance balanced (closing entry is balanced by construction).
    deb = sum(float(l["debit"]) for l in fake.rows("ledger_entries"))
    cred = sum(float(l["credit"]) for l in fake.rows("ledger_entries"))
    assert round(deb - cred, 2) == 0.0
    # Period flipped to closed.
    p = fake.rows("accounting_periods")[0]
    assert p["status"] == "closed" and p["closed_via"] == "owner"


def test_close_is_idempotent(fake):
    _seed_pnl(fake)
    gl.close_period("biz1", "yr2026", closed_by="owner")
    n_before = len(fake.rows("journal_entries"))
    out = gl.close_period("biz1", "yr2026", closed_by="owner")
    assert out.get("already") == "closed"
    assert len(fake.rows("journal_entries")) == n_before   # no second closing entry


def test_monthly_close_no_journal_entry(fake):
    fake.rows("accounting_periods").append({
        "id": "m6", "business_id": "biz1", "period_type": "month",
        "period_start": "2026-06-01", "period_end": "2026-06-30", "status": "open"})
    out = gl.close_period("biz1", "m6", closed_by="owner")
    assert out["closed"] is True and out["closing_journal_entry_id"] is None
    assert fake.rows("journal_entries") == []              # status flip only


def test_reopen_reverses_closing_entry(fake):
    _seed_pnl(fake)
    gl.close_period("biz1", "yr2026", closed_by="owner")
    assert _bal(fake, "3900", "credit") == 700
    gl.reopen_period("biz1", "yr2026", reopened_by="owner", reason="found a missing expense")
    # Reversal cancels the closing entry → Retained Earnings back to 0, P&L restored.
    assert _bal(fake, "3900", "credit") == 0
    assert _bal(fake, "4000", "credit") == 1000
    p = fake.rows("accounting_periods")[0]
    assert p["status"] == "reopened" and p["reopened_reason"] == "found a missing expense"
