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

@pytest.fixture(autouse=True)
def _pin_chat_price(monkeypatch):
    """These tests are about MECHANICS — thresholds firing once, drawdown
    order, weighted totals — and their expected numbers were written when
    a Chief turn cost 1 credit. It went to 8 on 2026-08-10, priced against
    measured cost.

    Pinning the dial keeps each assertion measuring the behaviour it
    names instead of re-encoding today's price list; a notification test
    should not change meaning because pricing moved. The price itself is
    covered by test_chat_repricing.py.
    """
    monkeypatch.setenv("PRICE_CHAT_PRICE", "1")




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
    """Prepaid semantics: allowance first, then credits — never postpaid
    overage. Past the allowance you draw down credits; with none left you
    stop ("out_of_units"), and a practitioner hard cap stops you at the
    allowance even when credits remain. Nothing bills as overage anymore,
    so the legacy postpaid fields must stay zeroed.

    The allowance is pinned to 300 via the dial rather than by generating
    3,000 rows: the shipped default moved to 3,000 on 2026-08-08, and
    what this test is about is the DRAW-DOWN ORDER, not the tank size.
    Setting it here also proves the override reaches usage_summary."""
    import usage_metering as um
    monkeypatch.setenv("CREDITS_STARTER_CREDITS", "300")
    fb = fake
    _biz(fb, "b1", plan="price_starter")
    now = datetime.now(timezone.utc)
    this_month = now.replace(day=2).isoformat()
    for i in range(305):                                         # past allowance
        fb.rows("api_usage").append({"id": f"u{i}", "business_id": "b1",
                                     "created_at": this_month, "endpoint": "/ai/proxy"})
    # Last month's usage doesn't count (auto-reset = computed window).
    fb.rows("api_usage").append({"id": "old", "business_id": "b1",
                                 "created_at": "2020-01-15T00:00:00Z",
                                 "endpoint": "/ai/proxy"})
    s0 = um.usage_summary("b1")
    assert s0["weighted_used"] == 305
    assert bl.chief_can_send("b1") is True                       # dormant

    # Enforcing, no credits banked: past the allowance is a full stop.
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    monkeypatch.setenv("STRIPE_PRICE_ID_STARTER", "price_starter")
    s1 = um.usage_summary("b1")
    assert s1["allotment"] == 300 and s1["overage_units"] == 5
    assert s1["credits_balance"] == 0 and s1["credits_burned_month"] == 0
    assert s1["blocked"] and s1["blocked_reason"] == "out_of_units"
    assert bl.chief_can_send("b1") is False
    # Postpaid is retired — these stay zeroed for older UI readers.
    assert s1["overage_cents"] == 0
    assert s1["overage_rate_cents"] is None and s1["cap_units"] is None

    # Bank a credit pack: the same usage now draws down instead of blocking.
    fb.rows("credit_ledger").append({"id": "c1", "business_id": "b1",
                                     "delta_units": 500, "kind": "purchase",
                                     "source": "pack:test"})
    s2 = um.usage_summary("b1")
    assert s2["credits_burned_month"] == 5                       # the 5 past 300
    assert s2["credits_balance"] == 495                          # 500 - 5
    assert not s2["blocked"] and bl.chief_can_send("b1") is True

    # Weighted: a full site build costs build_base(). Re-reading GROWS
    # the same month's burn row rather than stacking a second one.
    monkeypatch.setenv("PRICE_BUILD_BASE", "25")   # keep the arithmetic legible
    for i in range(8):
        fb.rows("api_usage").append({"id": f"b{i}", "business_id": "b1",
                                     "created_at": this_month,
                                     "endpoint": "/director/build"})
    s3 = um.usage_summary("b1")
    assert s3["weighted_used"] == 305 + 8 * 25                   # 505
    assert s3["credits_burned_month"] == 205                     # 505 - 300
    assert s3["credits_balance"] == 295                          # 500 - 205
    assert not s3["blocked"]                                     # credits remain

    # The practitioner's own hard cap stops at the allowance regardless.
    fb.rows("businesses")[0]["settings"] = {"usage_hard_cap": True}
    s4 = um.usage_summary("b1")
    assert s4["hard_cap"] and s4["blocked"]
    assert s4["blocked_reason"] == "hard_cap"
    assert bl.chief_can_send("b1") is False


def test_chief_llm_respects_cap_gracefully(fake, monkeypatch):
    """Practitioner hard cap: at/over allotment with usage_hard_cap set,
    AI interactions soft-block (Arc 19 rule).

    Allowance pinned to 300 via the dial — the behaviour under test is
    the soft-block, not the shipped tank size."""
    fb = fake
    monkeypatch.setenv("CREDITS_STARTER_CREDITS", "300")
    fb.rows("businesses").append({
        "id": "b1", "owner_id": "owner1", "is_active": True, "name": "b1",
        "subscription_status": "active", "subscription_plan": "price_starter",
        "settings": {"usage_hard_cap": True}})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("BILLING_ENFORCE", "on")
    monkeypatch.setenv("STRIPE_PRICE_ID_STARTER", "price_starter")
    now_iso = datetime.now(timezone.utc).replace(day=2).isoformat()
    for i in range(300):                                         # at allotment
        fb.rows("api_usage").append({"id": f"u{i}", "business_id": "b1",
                                     "created_at": now_iso, "endpoint": "/ai/proxy"})
    out = asyncio.run(chief_llm.ask_transaction("b1", "lawyer", "t1", None))
    assert out["llm"] == "capped" and "Upgrade" in out["answer"]
    out2 = asyncio.run(chief_llm.analyze_hard("b1", "lawyer"))
    assert out2["llm"] == "capped" and out2["created"] == []
    # Grandfathered owner: unlimited regardless.
    fb.rows("user_profiles").append({"user_id": "owner1", "is_grandfathered": True})
    import usage_metering as um
    assert um.can_interact("b1") is True


def test_seat_cap_and_invite_flow(fake, monkeypatch):
    fb = fake
    monkeypatch.setenv("STRIPE_PRICE_ID_PRACTICE", "price_practice")
    _biz(fb, "b1", plan="price_practice")
    # Invite (dormant enforcement, but seat math is real).
    out = asyncio.run(bu.invite("b1", bu.InviteBody(email="a@x.com", role="member"), _User()))
    assert out["ok"] and out["member"]["status"] == "invited"
    # The invite link must point at the app's real home (app_base_url),
    # not a hardcoded domain — https://app.solutionist.studio never
    # resolved, so every invite email shipped a dead link.
    from app_base import app_base_url
    assert out["accept_url"].startswith(f"{app_base_url()}/?team_invite=")
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


def test_build_marker_weights(fake, monkeypatch):
    """Weight-hole fix (2026-07-30) at the 2026-08-08 config prices: a
    shipped full build bills as ONE marker row (/composer/compose); the
    authoring calls inside it (canvas, canvas-review, builder-v2 + eyes,
    spec) are priced 0 so a build never bills per-LLM-call.

    Prices come from pricing_config rather than pinned literals — they
    are dials now, and a test hardcoding 25 would only have to be
    rewritten on the first tuning pass. What IS pinned is the shape:
    internals free, marker billable, chat is the unit."""
    import usage_metering as um
    import pricing_config as pc
    fb = fake
    _biz(fb, "b1", plan="price_starter")
    now_iso = datetime.now(timezone.utc).replace(day=2).isoformat()
    build_rows = ["/composer/compose", "/composer/canvas",
                  "/composer/canvas-review", "/composer/builder-v2",
                  "/composer/builder-v2-eyes", "/composer/spec",
                  "/composer/spec"]
    extra_rows = ["/composer/hero", "/ai/proxy", "/chief/backend"]
    for i, ep in enumerate(build_rows + extra_rows):
        fb.rows("api_usage").append({"id": f"w{i}", "business_id": "b1",
                                     "created_at": now_iso, "endpoint": ep})
    expected = (pc.build_base()      # marker row, no explicit units
                + 0 * 6              # build internals
                + pc.hero_regen()    # hero refresh
                + 1                  # /ai/proxy -> DEFAULT_WEIGHT
                + pc.chat_price())   # chat turn
    assert um.weighted_usage_this_month("b1") == expected
    assert um.weight_for("/composer/compose") == pc.build_base()
    assert um.weight_for("/composer/atelier") == pc.section_rewrite()
    assert um.weight_for("/director/build") == pc.build_base()  # legacy rows
    # Build internals must stay FREE — the marker carries the whole bill.
    for internal in ("/composer/canvas", "/composer/builder-v2",
                     "/composer/spec", "/composer/drl/dro", "/vision/grade"):
        assert um.weight_for(internal) == 0, internal


def test_row_units_override_the_endpoint_price(fake):
    """A row carrying explicit `units` is priced by that value, not by
    its endpoint — the mechanism that makes base+per-section, revamp,
    and in-build-vs-standalone atelier expressible at all.

    0 must be honoured (build internals are deliberately free), so the
    read path tests `is not None`, never truthiness."""
    import usage_metering as um
    import pricing_config as pc
    fb = fake
    _biz(fb, "b1", plan="price_starter")
    now_iso = datetime.now(timezone.utc).replace(day=2).isoformat()
    # A 5-section build, an in-build atelier fragment (free), and a
    # standalone Studio rewrite (charged) — all three would be mispriced
    # by an endpoint-only lookup.
    fb.rows("api_usage").extend([
        {"id": "u1", "business_id": "b1", "created_at": now_iso,
         "endpoint": "/composer/compose", "units": 1100},
        {"id": "u2", "business_id": "b1", "created_at": now_iso,
         "endpoint": "/composer/atelier", "units": 0},
        {"id": "u3", "business_id": "b1", "created_at": now_iso,
         "endpoint": "/composer/atelier", "units": pc.section_rewrite()},
    ])
    assert um.weighted_usage_this_month("b1") == 1100 + pc.section_rewrite()
    assert um.weight_for_row({"endpoint": "/composer/compose", "units": 0}) == 0
    # A NULL units column falls back to the endpoint table — every row
    # written before 2026-08-08.
    assert (um.weight_for_row({"endpoint": "/composer/hero", "units": None})
            == pc.hero_regen())
    # A malformed value must not crash the meter — fall back, don't raise.
    assert (um.weight_for_row({"endpoint": "/composer/hero", "units": "junk"})
            == pc.hero_regen())
