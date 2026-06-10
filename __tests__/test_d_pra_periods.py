"""Category D PR-A — hard-lock, fiscal year, two-signature close, audit filters."""
from __future__ import annotations

import sys
import pathlib
from datetime import date

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import gl_engine as gl  # noqa: E402
import period_lock  # noqa: E402
import chief_bookkeeping as cb  # noqa: E402
import gl_reports_t4 as t4  # noqa: E402
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


# ─── Hard-lock ───────────────────────────────────────────────────────

def test_hard_lock_rejects_even_with_reason(fake):
    fb = fake
    fb.rows("businesses").append({"id": "b1", "owner_id": "o",
                                  "settings": {"period_lock_mode": "hard"}})
    fb.rows("accounting_periods").append({
        "id": "p1", "business_id": "b1", "period_type": "month",
        "period_start": "2026-05-01", "period_end": "2026-05-31", "status": "closed"})
    with pytest.raises(HTTPException) as e:
        period_lock.guard("b1", "2026-05-10", source_type="invoice", source_id="i1",
                          reason="totally valid reason", override_by="o")
    assert e.value.status_code == 403
    assert "Hard lock" in str(e.value.detail)
    assert fb.rows("period_edit_overrides") == []           # no override recorded


def test_soft_lock_still_allows_with_reason(fake):
    fb = fake
    fb.rows("businesses").append({"id": "b1", "owner_id": "o", "settings": {}})
    fb.rows("accounting_periods").append({
        "id": "p1", "business_id": "b1", "period_type": "month",
        "period_start": "2026-05-01", "period_end": "2026-05-31", "status": "closed"})
    period_lock.guard("b1", "2026-05-10", source_type="invoice", source_id="i1",
                      reason="fix amount", override_by="o")
    assert len(fb.rows("period_edit_overrides")) == 1
    # Open dates unaffected by hard mode.
    fb.rows("businesses")[0]["settings"] = {"period_lock_mode": "hard"}
    period_lock.guard("b1", "2026-06-10", source_type="invoice", source_id="i2",
                      reason=None, override_by="o")          # no closed period → no-op


# ─── Fiscal year ─────────────────────────────────────────────────────

def test_period_specs_fiscal_july():
    specs = gl._period_specs(2026, 7)
    year_rows = [x for x in specs if x[0] == "year"]
    assert year_rows[0][1] == date(2026, 7, 1)
    assert year_rows[0][2] == date(2027, 6, 30)
    q1 = [x for x in specs if x[0] == "quarter"][0]
    assert q1[1] == date(2026, 7, 1) and q1[2] == date(2026, 9, 30)
    months = [x for x in specs if x[0] == "month"]
    assert months[0][1] == date(2026, 7, 1)
    assert months[-1][1] == date(2027, 6, 1)
    # Calendar default unchanged.
    cal = gl._period_specs(2026)
    assert [x for x in cal if x[0] == "year"][0][1] == date(2026, 1, 1)


def test_generate_periods_uses_business_fiscal_setting(fake):
    fb = fake
    fb.rows("businesses").append({"id": "b1", "owner_id": "o",
                                  "settings": {"financial": {"fiscal_year_start_month": 7}}})
    out = gl.generate_periods("b1", 2026)
    assert out["fiscal_year_start_month"] == 7
    years = [r for r in fb.rows("accounting_periods") if r["period_type"] == "year"]
    assert years[0]["period_start"] == "2026-07-01"
    assert years[0]["period_end"] == "2027-06-30"
    # Idempotent re-run.
    out2 = gl.generate_periods("b1", 2026)
    assert out2["created"] == 0


# ─── Two-signature close ─────────────────────────────────────────────

def test_two_signature_second_signer_must_differ(fake):
    fb = fake
    fb.rows("businesses").append({"id": "b1", "owner_id": "o", "type": "consultant",
                                  "settings": {"period_close_two_signature": True}})
    fb.rows("accounting_periods").append({
        "id": "p1", "business_id": "b1", "period_type": "month",
        "period_start": "2026-05-01", "period_end": "2026-05-31", "status": "open"})
    row = cb._insert_proposal(
        "b1", "propose_period_close",
        proposed={"period_id": "p1", "initiated_by": "owner1",
                  "initiated_role": "owner", "requires_second_signature": True},
        confidence=1.0, reasoning="two-sig")
    # Initiator can't counter-sign their own request.
    with pytest.raises(HTTPException) as e:
        cb.approve_proposal("b1", row["id"], approved_by="owner1")
    assert e.value.status_code == 403
    # A different signer closes it; closed_via records the workflow.
    out = cb.approve_proposal("b1", row["id"], approved_by="accountant9")
    assert out["ok"]
    per = fb.rows("accounting_periods")[0]
    assert per["status"] == "closed"
    assert per["closed_via"] == "two_signature"
    assert per["closed_by"] == "accountant9"
    prop = fb.rows("chief_bookkeeping_proposals")[0]
    assert prop["status"] == "approved"                      # both ids on the row
    assert prop["proposed"]["initiated_by"] == "owner1"


# ─── Audit trail filters + snapshot diff ─────────────────────────────

def test_audit_trail_filters_and_change_line(fake):
    fb = fake
    fb.rows("period_edit_overrides").append({
        "id": "o1", "business_id": "b1", "source_type": "invoice", "source_id": "i1",
        "override_reason": "fix", "override_by_role": "owner",
        "override_at": "2026-06-08T12:00:00Z",
        "pre_change_snapshot": {"total": 400, "status": "sent"},
        "post_change_snapshot": {"total": 500, "status": "sent"}})
    fb.rows("period_edit_overrides").append({
        "id": "o2", "business_id": "b1", "source_type": "bill", "source_id": "x",
        "override_reason": "r", "override_by_role": "owner",
        "override_at": "2026-04-01T12:00:00Z",
        "pre_change_snapshot": None, "post_change_snapshot": None})
    out = t4.audit_trail("b1", source_type="invoice")
    assert out["count"] == 1
    assert "total: 400 → 500" in out["entries"][0]["change"]
    out2 = t4.audit_trail("b1", date_from="2026-06-01")
    assert out2["count"] == 1 and out2["entries"][0]["source_type"] == "invoice"
    out3 = t4.audit_trail("b1")
    assert out3["count"] == 2
