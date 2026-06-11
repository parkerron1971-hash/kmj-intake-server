"""Arc 20 Phase B PR2 — Chief ops analyzer, Trust Track, vertical defaults,
metering-by-construction."""
from __future__ import annotations

import sys
import pathlib
from datetime import datetime, timezone, timedelta

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402

import rules_engine as re_  # noqa: E402
import rules_router as rr  # noqa: E402
import launch_access as la  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402


def _u(uid="owner1"):
    return type("U", (), {"id": uid})()


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    fb.rows("businesses").append({"id": "b1", "owner_id": "owner1", "name": "Biz",
                                  "settings": {}})
    return fb


def test_chief_analyzer_proposes_overdue_followups(fake):
    fb = fake
    due = (datetime.now(timezone.utc).date() - timedelta(days=10)).isoformat()
    fb.rows("invoices").append({"id": "i1", "business_id": "b1", "paid_at": None,
                                "status": "overdue", "due_date": due,
                                "invoice_number": "INV-3", "total": 450,
                                "contact_id": "c1",
                                "contacts": {"name": "Sam", "email": "sam@x.com"}})
    out = rr.analyze_ops("b1", _u())
    assert len(out["created"]) == 1
    p = out["created"][0]
    assert p["proposal_type"] == "propose_followup_email"
    assert p["source"] == "chief"
    assert "INV-3" in p["proposed"]["subject"]
    assert "nothing" in p["reasoning"].lower()              # trust narration
    # Idempotent: re-running doesn't duplicate the pending proposal.
    out2 = rr.analyze_ops("b1", _u())
    assert out2["created"] == []


def test_trust_track_graduation_math(fake):
    fb = fake
    # 18 approved + 2 rejected generic (90% over 20 → candidate).
    for i in range(18):
        fb.rows("chief_proposals").append({"business_id": "b1",
                                           "proposal_type": "propose_contact_tag",
                                           "status": "approved"})
    for i in range(2):
        fb.rows("chief_proposals").append({"business_id": "b1",
                                           "proposal_type": "propose_contact_tag",
                                           "status": "rejected"})
    # Bookkeeping proposals fold in too: 5 approved, 5 rejected (50%, no).
    for st in ("approved",) * 5 + ("rejected",) * 5:
        fb.rows("chief_bookkeeping_proposals").append({"business_id": "b1",
                                                       "proposal_type": "propose_categorize",
                                                       "status": st})
    # And a small sample below the floor (100% but only 3 resolved → no).
    for i in range(3):
        fb.rows("chief_proposals").append({"business_id": "b1",
                                           "proposal_type": "propose_task",
                                           "status": "approved"})
    out = rr.trust_track("b1", _u())
    cats = {c["proposal_type"]: c for c in out["categories"]}
    assert cats["propose_contact_tag"]["graduation_candidate"] is True
    assert cats["propose_contact_tag"]["approval_ratio"] == 0.9
    assert cats["propose_categorize"]["graduation_candidate"] is False
    assert cats["propose_task"]["graduation_candidate"] is False  # n too small


def test_regulated_vertical_autonomy_defaults(fake):
    fb = fake
    fb.rows("user_profiles").append({"user_id": "gf", "is_grandfathered": True})
    out = la.create_business(
        la.CreateBusinessBody(name="Hartwell Law", type="lawyer"), _u("gf"))
    auto = out["business"]["settings"]["autonomy"]
    assert auto["client_facing_autonomy"] == "disabled"
    assert auto["acknowledgment_required"] is True
    out2 = la.create_business(
        la.CreateBusinessBody(name="Stillpoint", type="therapist"), _u("gf"))
    assert out2["business"]["settings"]["autonomy"]["client_facing_autonomy"] == "disabled"
    out3 = la.create_business(
        la.CreateBusinessBody(name="Cuts", type="barber"), _u("gf"))
    assert "autonomy" not in (out3["business"]["settings"] or {})


def test_rules_make_zero_llm_calls(fake):
    """Part 7 metering-by-construction: a full rule execution writes NOTHING
    to api_usage — Tier 1 is free because it literally cannot spend."""
    fb = fake
    fb.rows("practitioner_rules").append({
        "id": "r1", "business_id": "b1", "name": "n", "rationale": "r",
        "enabled": True, "trigger_type": "contact_created", "trigger_config": {},
        "conditions": [], "version": 1,
        "actions": [{"verb": "apply_tag", "params": {"tag": "x"}},
                    {"verb": "create_task", "params": {"title": "t"}},
                    {"verb": "propose_contact_tag", "params": {"tag": "y"}}]})
    fb.rows("contacts").append({"id": "c1", "business_id": "b1", "tags": []})
    re_.on_event("b1", "contact_created", {"contact_id": "c1", "name": "X"})
    assert fb.rows("api_usage") == []
