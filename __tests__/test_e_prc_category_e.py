"""Category E PR-C — accrual basis, consolidation, FX scaffold, queue claims."""
from __future__ import annotations

import sys
import pathlib

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import gl_engine as gl  # noqa: E402
import gl_reports  # noqa: E402
import entity_groups_router as eg  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    return fb


def _u(uid="owner1"):
    return type("U", (), {"id": uid})()


def _biz(fb, bid, name, group=None):
    fb.rows("businesses").append({
        "id": bid, "owner_id": "owner1", "is_active": True, "name": name,
        "type": "consultant", "entity_group_id": group})


def _inv(fb, biz, iid, total, *, status="sent", paid=None):
    fb.rows("invoices").append({
        "id": iid, "business_id": biz, "total": total, "status": status,
        "sent_at": "2026-06-01T00:00:00Z", "created_at": "2026-06-01T00:00:00Z",
        "due_date": "2026-06-20", "paid_at": paid, "payment_method": "cash" if paid else None,
        "stripe_payment_url": None if paid else "x",
        "refund_amount_cents": None, "refunded_at": None, "category": None})


# ─── Accrual basis ───────────────────────────────────────────────────

def test_accrual_vs_cash_pl(fake):
    fb = fake
    _biz(fb, "b1", "Biz")
    _inv(fb, "b1", "i1", 400, status="sent")                 # issued, unpaid
    _inv(fb, "b1", "i2", 300, status="paid", paid="2026-06-10T00:00:00Z")
    fb.rows("bills").append({"id": "bl1", "business_id": "b1", "vendor_name": "V",
                             "amount": 120, "category": "operating", "subcategory": None,
                             "status": "unpaid", "due_date": "2026-06-25",
                             "created_at": "2026-06-05T00:00:00Z", "paid_at": None,
                             "paid_amount": None})
    gl.backfill("b1", "consultant")
    cash = gl_reports.gl_profit_and_loss("b1", "custom", None, "2026-06-01", "2026-06-30",
                                         basis="cash")
    acc = gl_reports.gl_profit_and_loss("b1", "custom", None, "2026-06-01", "2026-06-30",
                                        basis="accrual")
    # Cash: only the PAID invoice counts; unpaid bill excluded.
    assert cash["current"]["revenue"]["gross_revenue"] == 300.0
    assert cash["current"]["expenses"]["total"] == 0.0
    assert cash["basis"] == "cash"
    # Accrual: both ISSUED invoices + the unpaid bill count.
    assert acc["current"]["revenue"]["gross_revenue"] == 700.0
    assert acc["current"]["expenses"]["total"] == 120.0
    assert acc["current"]["net_income"] == 580.0
    assert acc["basis"] == "accrual"


# ─── Consolidation ───────────────────────────────────────────────────

def test_consolidated_pl_sums_members(fake):
    fb = fake
    fb.rows("entity_groups").append({"id": "g1", "owner_id": "owner1", "name": "KMJ Group"})
    _biz(fb, "b1", "Church", group="g1")
    _biz(fb, "b2", "Studio", group="g1")
    _biz(fb, "b3", "Outside")                                 # not in group
    _inv(fb, "b1", "i1", 500, status="paid", paid="2026-06-10T00:00:00Z")
    _inv(fb, "b2", "i2", 200, status="paid", paid="2026-06-11T00:00:00Z")
    gl.backfill("b1", "consultant")
    gl.backfill("b2", "consultant")
    out = eg.consolidated_pl("g1", period="custom", basis="accrual", user=_u())
    # period custom without dates defaults Jan1→today in period_bounds — fine.
    assert out["consolidated"]["gross_revenue"] == 700.0
    names = {c["name"] for c in out["columns"]}
    assert names == {"Church", "Studio"}
    assert out["eliminations"] == "none"                      # honesty in-band
    bs = eg.consolidated_balance_sheet("g1", user=_u())
    assert bs["consolidated"]["assets"] == bs["consolidated"]["liabilities"] + bs["consolidated"]["equity"]


def test_group_crud_and_ownership(fake):
    fb = fake
    _biz(fb, "b1", "Biz")
    out = eg.create_group(eg.GroupBody(name="Roll-up"), _u())
    gid = out["group"]["id"]
    eg.assign(gid, eg.AssignBody(business_id="b1"), _u())
    assert fb.rows("businesses")[0]["entity_group_id"] == gid
    with pytest.raises(HTTPException):
        eg.assign(gid, eg.AssignBody(business_id="b1"), _u("intruder"))
    eg.delete_group(gid, _u())
    assert fb.rows("businesses")[0]["entity_group_id"] is None
    assert fb.rows("entity_groups") == []


# ─── FX scaffold ─────────────────────────────────────────────────────

def test_fx_manual_upsert(fake):
    fb = fake
    eg.put_fx(eg.FxBody(base_currency="eur", rate=1.08, as_of_date="2026-06-10"), _u())
    assert fb.rows("fx_rates")[0]["base_currency"] == "EUR"
    eg.put_fx(eg.FxBody(base_currency="EUR", rate=1.09, as_of_date="2026-06-10"), _u())
    assert len(fb.rows("fx_rates")) == 1                      # upsert, not dup
    assert fb.rows("fx_rates")[0]["rate"] == 1.09
    with pytest.raises(HTTPException):
        eg.put_fx(eg.FxBody(base_currency="EURO", rate=1.0, as_of_date="2026-06-10"), _u())
    out = eg.list_fx(_u())
    assert out["rates"] and "USD-only" in out["note"]


# ─── Queue claim concurrency ─────────────────────────────────────────

def test_queue_claim_prevents_double_drain(fake):
    fb = fake
    _biz(fb, "b1", "Biz")
    fb.rows("business_expenses").append({"id": "e1", "business_id": "b1", "amount": 50,
                                         "category": "operating", "subcategory": None,
                                         "vendor": "V", "date": "2026-06-05"})
    fb.rows("gl_sync_queue").append({"id": "q1", "business_id": "b1",
                                     "source_table": "business_expenses", "source_id": "e1",
                                     "processed_at": None,
                                     "enqueued_at": "2026-06-10T00:00:00Z"})
    out1 = gl.process_queue("b1")
    assert out1["processed"] == 1
    q = fb.rows("gl_sync_queue")[0]
    assert q.get("claimed_by")                                # claim stamped
    assert q.get("processed_at")
    # Second drain: nothing left to claim.
    out2 = gl.process_queue("b1")
    assert out2["processed"] == 0
