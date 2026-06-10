"""Phase E v1.1 — business caps, Chief metering, multi-seat (gate-ready)."""
from __future__ import annotations

import asyncio
import sys
import pathlib
from datetime import datetime, timezone

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import billing_limits as bl  # noqa: E402
import business_users_router as bu  # noqa: E402
import chief_llm  # noqa: E402
from test_i2_gl_sync import FakeSB  # noqa: E402


class _User:
    id = "owner1"


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    for k in ("BILLING_ENFORCE", "STRIPE_PRICE_ID_STARTER", "STRIPE_PRICE_ID_PRACTICE"):
        monkeypatch.delenv(k, raising=False)
    return fb


def _biz(fb, bid, *, plan=None, status="active", owner="owner1"):
    fb.rows("businesses").append({
        "id": bid, "owner_id": owner, "is_active": True, "name": bid,
        "subscription_status": status if plan else None,
        "subscription_plan": plan})


def test_business_cap_dormant_then_enforced(fake, monkeypatch):
    fb = fake
    _biz(fb, "b1", plan="price_starter")
    out = bl.can_create_business("owner1")
    assert out["allowed"] is True and out["limit"] is None      # dormant
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    monkeypatch.setenv("STRIPE_PRICE_ID_STARTER", "price_starter")
    out = bl.can_create_business("owner1")
    assert out["limit"] == 1 and out["count"] == 1
    assert out["allowed"] is False                              # starter cap hit
    monkeypatch.setenv("STRIPE_PRICE_ID_PRACTICE", "price_practice")
    _biz(fb, "b2", plan="price_practice")                       # best plan wins
    out = bl.can_create_business("owner1")
    assert out["limit"] == 3 and out["count"] == 2 and out["allowed"] is True


def test_chief_metering_month_window_and_cap(fake, monkeypatch):
    fb = fake
    _biz(fb, "b1", plan="price_starter")
    now = datetime.now(timezone.utc)
    this_month = now.replace(day=2).isoformat()
    for i in range(50):
        fb.rows("api_usage").append({"id": f"u{i}", "business_id": "b1",
                                     "created_at": this_month})
    # Last month's usage doesn't count (auto-reset = computed window).
    fb.rows("api_usage").append({"id": "old", "business_id": "b1",
                                 "created_at": "2020-01-15T00:00:00Z"})
    u = bl.chief_usage("b1")
    assert u["used"] == 50 and u["limit"] is None               # dormant
    assert bl.chief_can_send("b1") is True
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    monkeypatch.setenv("STRIPE_PRICE_ID_STARTER", "price_starter")
    u = bl.chief_usage("b1")
    assert u["limit"] == 50 and u["remaining"] == 0
    assert bl.chief_can_send("b1") is False                     # cap reached


def test_chief_llm_respects_cap_gracefully(fake, monkeypatch):
    fb = fake
    _biz(fb, "b1", plan="price_starter")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    monkeypatch.setenv("STRIPE_PRICE_ID_STARTER", "price_starter")
    now_iso = datetime.now(timezone.utc).replace(day=2).isoformat()
    for i in range(50):
        fb.rows("api_usage").append({"id": f"u{i}", "business_id": "b1",
                                     "created_at": now_iso})
    out = asyncio.run(chief_llm.ask_transaction("b1", "lawyer", "t1", None))
    assert out["llm"] == "capped" and "Upgrade" in out["answer"]
    out2 = asyncio.run(chief_llm.analyze_hard("b1", "lawyer"))
    assert out2["llm"] == "capped" and out2["created"] == []


def test_seat_cap_and_invite_flow(fake, monkeypatch):
    fb = fake
    monkeypatch.setenv("STRIPE_PRICE_ID_PRACTICE", "price_practice")
    _biz(fb, "b1", plan="price_practice")
    # Invite (dormant enforcement, but seat math is real).
    out = asyncio.run(bu.invite("b1", bu.InviteBody(email="a@x.com", role="member"), _User()))
    assert out["ok"] and out["member"]["status"] == "invited"
    assert out["accept_url"].startswith("https://app.solutionist.studio/?team_invite=")
    assert bl.seat_count("b1") == 2                             # owner + 1 invite
    # Duplicate invite rejected.
    with pytest.raises(HTTPException) as e:
        asyncio.run(bu.invite("b1", bu.InviteBody(email="a@x.com"), _User()))
    assert e.value.status_code == 409
    # Accept binds the user + activates.
    token = out["member"].get("token")
    fb.rows("business_users")[0]["token"] = token or "tok1"
    acc = bu.accept(bu.AcceptBody(token=token or "tok1"),
                    type("U", (), {"id": "member9"})())
    assert acc["ok"] and acc["business_id"] == "b1"
    assert fb.rows("business_users")[0]["status"] == "active"
    # Enforced practice cap = 5 seats: fill to 5, 6th invite → 402.
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    for i in range(3):
        asyncio.run(bu.invite("b1", bu.InviteBody(email=f"m{i}@x.com"), _User()))
    assert bl.seat_count("b1") == 5
    with pytest.raises(HTTPException) as e:
        asyncio.run(bu.invite("b1", bu.InviteBody(email="six@x.com"), _User()))
    assert e.value.status_code == 402
    # Revoke frees the seat.
    rid = fb.rows("business_users")[1]["id"]
    bu.revoke(rid, "b1", _User())
    assert bl.can_add_seat("b1")["allowed"] is True


def test_invite_requires_owner_and_valid_role(fake):
    fb = fake
    _biz(fb, "b1")
    with pytest.raises(HTTPException) as e:
        asyncio.run(bu.invite("b1", bu.InviteBody(email="a@x.com"),
                              type("U", (), {"id": "intruder"})()))
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        asyncio.run(bu.invite("b1", bu.InviteBody(email="a@x.com", role="owner"), _User()))
    assert e.value.status_code == 400
