"""Phase I.2 — GL live sync (converge-to-desired) — against an in-memory
Supabase fake so the reverse+repost / delete / idempotency paths are exercised
end-to-end (read + write)."""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import gl_engine as gl


# ── tiny PostgREST-ish in-memory store ──────────────────────────────
def _num(x):
    try:
        return float(x)
    except Exception:
        return None


def _passes(row, col, op, target):
    if op == "__or__":
        return any(_passes(row, c2, o2, t2) for c2, o2, t2 in target)
    if op in ("is", "not.is"):
        # PostgREST `is` takes null/true/false. `not.is.true` matches false
        # AND null (the I.7 is_trust_account pattern relies on this).
        if target in ("true", "false"):
            res = row.get(col) is not None and bool(row.get(col)) is (target == "true")
        else:
            res = row.get(col) is None
        return res if op == "is" else (not res)
    val = row.get(col)
    if val is None:
        return op in ("neq",)  # missing ≠ a concrete target; matches neq only
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
        if col == "or":
            # or=(a.is.null,b.eq.x) — one top-level OR of simple conditions.
            inner = rest.strip("()")
            sub = []
            for piece in inner.split(","):
                if "." not in piece:
                    continue
                c2, r2 = piece.split(".", 1)
                if r2.startswith("not.is."):
                    sub.append((c2, "not.is", r2[7:]))
                elif r2.startswith("is."):
                    sub.append((c2, "is", r2[3:]))
                elif r2.startswith("in."):
                    sub.append((c2, "in", r2[3:]))
                elif "." in r2:
                    o2, t2 = r2.split(".", 1)
                    sub.append((c2, o2, t2))
            cons.append(("__or__", "__or__", sub))
            continue
        if rest.startswith("not.is."):
            cons.append((col, "not.is", rest[7:]))
        elif rest.startswith("is."):
            cons.append((col, "is", rest[3:]))
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

    def delete(self, path):
        table, cons = _parse(path)
        keep = [r for r in self.rows(table) if not all(_passes(r, c, o, tg) for c, o, tg in cons)]
        self.t[table] = keep
        return True


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    # business + one included depository account (cash snapshot 0 keeps opening simple)
    fb.rows("businesses").append({"id": "biz1", "type": "consultant", "owner_id": "owner"})
    return fb


def _enqueue(fb, table, sid, op="insert"):
    fb.rows("gl_sync_queue").append({"id": f"q{len(fb.rows('gl_sync_queue'))}",
                                     "business_id": "biz1", "source_table": table,
                                     "source_id": sid, "op": op, "processed_at": None,
                                     "enqueued_at": "2026-06-09T00:00:00Z"})


def _active(fb, source_type, source_id):
    return [r for r in fb.rows("journal_entries")
            if r["source_type"] == source_type and r["source_id"] == source_id and r["status"] == "active"]


def test_insert_update_delete_converges(fake):
    fb = fake
    # 1. New SENT invoice $400 → invoice_issue, AR 400.
    fb.rows("invoices").append({"id": "inv1", "total": 400, "status": "sent", "paid_at": None,
                                "sent_at": "2026-06-01T00:00:00Z", "created_at": "2026-06-01T00:00:00Z",
                                "due_date": "2026-06-20", "payment_method": None, "stripe_payment_url": "x",
                                "refund_amount_cents": None, "refunded_at": None})
    _enqueue(fb, "invoices", "inv1")
    gl.process_queue("biz1")
    assert len(_active(fb, "invoice_issue", "inv1")) == 1
    assert gl.gl_ar(gl.read_ledger("biz1")) == 400

    # 2. Edit total 400 → 500 → old issue reversed, new issue active, AR 500.
    fb.rows("invoices")[0]["total"] = 500
    _enqueue(fb, "invoices", "inv1", "update")
    gl.process_queue("biz1")
    assert len(_active(fb, "invoice_issue", "inv1")) == 1            # still one active
    assert gl.gl_ar(gl.read_ledger("biz1")) == 500
    # trial balance stays $0 (reversal cancels the stale entry).
    assert gl.trial_balance(gl.read_ledger("biz1"))["difference"] == 0.0

    # 3. Mark paid → invoice_payment added; AR back to 0, Clearing 500.
    fb.rows("invoices")[0].update({"status": "paid", "paid_at": "2026-06-10T00:00:00Z"})
    _enqueue(fb, "invoices", "inv1", "update")
    gl.process_queue("biz1")
    assert gl.gl_ar(gl.read_ledger("biz1")) == 0
    assert gl.gl_clearing(gl.read_ledger("biz1")) == 500

    # 4. Delete the invoice → everything reversed; AR + Clearing 0; TB still 0.
    fb.t["invoices"] = []
    _enqueue(fb, "invoices", "inv1", "delete")
    gl.process_queue("biz1")
    assert gl.gl_ar(gl.read_ledger("biz1")) == 0
    assert gl.gl_clearing(gl.read_ledger("biz1")) == 0
    assert gl.trial_balance(gl.read_ledger("biz1"))["difference"] == 0.0
    assert _active(fb, "invoice_issue", "inv1") == []


def test_idempotent_reprocess_no_change(fake):
    fb = fake
    fb.rows("business_expenses").append({"id": "e1", "amount": 120, "category": "operating",
                                         "subcategory": "rent", "vendor": "X", "date": "2026-06-05"})
    _enqueue(fb, "business_expenses", "e1")
    gl.process_queue("biz1")
    before = len(fb.rows("ledger_entries"))
    # Re-enqueue the SAME unchanged row → converge is a no-op (no new lines).
    _enqueue(fb, "business_expenses", "e1", "update")
    gl.process_queue("biz1")
    assert len(fb.rows("ledger_entries")) == before


def test_bill_draft_then_pending_creates_ap(fake):
    fb = fake
    fb.rows("bills").append({"id": "b1", "vendor_name": "Rent Co", "amount": 2000, "category": "operating",
                             "status": "draft", "due_date": "2026-07-01", "created_at": "2026-06-01T00:00:00Z",
                             "paid_at": None, "paid_amount": None})
    _enqueue(fb, "bills", "b1")
    gl.process_queue("biz1")
    assert gl.gl_ap(gl.read_ledger("biz1")) == 0                     # draft ≠ payable
    fb.rows("bills")[0]["status"] = "pending"
    _enqueue(fb, "bills", "b1", "update")
    gl.process_queue("biz1")
    assert gl.gl_ap(gl.read_ledger("biz1")) == 2000


def test_plaid_exclude_toggle_reverses(fake):
    fb = fake
    fb.rows("plaid_accounts").append({"account_id": "acc1", "business_id": "biz1", "type": "depository",
                                      "included_in_bookkeeping": True, "deleted_at": None, "last_balance": 0})
    fb.rows("plaid_transactions").append({"transaction_id": "t1", "business_id": "biz1", "amount": 250,
                                          "date": "2026-06-08", "business_category": "operating",
                                          "business_subcategory": "fuel", "plaid_category_primary": "TRANSPORTATION",
                                          "plaid_category_detail": None, "reconciled_to_payout_id": None,
                                          "pending": False, "excluded_from_books": False, "account_id": "acc1"})
    _enqueue(fb, "plaid_transactions", "t1")
    gl.process_queue("biz1")
    exp = [l for l in gl.read_ledger("biz1") if l["account_type"] == "expense"]
    assert sum(float(l["debit"]) for l in exp) == 250
    # Exclude it → expense reverses to net 0.
    fb.rows("plaid_transactions")[0]["excluded_from_books"] = True
    _enqueue(fb, "plaid_transactions", "t1", "update")
    gl.process_queue("biz1")
    exp = [l for l in gl.read_ledger("biz1") if l["account_type"] == "expense"]
    assert round(sum(float(l["debit"]) - float(l["credit"]) for l in exp), 2) == 0.0
