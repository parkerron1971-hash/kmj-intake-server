"""THE SOURCING DESK stage 2 — the bridge.

Two clusters.

The COMPOSER: preview and send must produce the identical letter from the
identical inputs, or the practitioner approved something that was never
sent. And a missing fact must drop its line rather than print a
placeholder — a vendor reading a template with the blanks showing knows
exactly how much attention the request deserves.

The SEND: this is one prompt away from being a cold-email tool, and the
thing being protected is a sending domain every practitioner shares. So
the fan-out cap, the de-duplication, the daily ceiling and the
already-asked guard are all tested as hard constraints, not preferences.
"""
from __future__ import annotations

import asyncio
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest
from fastapi import HTTPException

import rfq_engine as rq
import sourcing_router as sr


class _U:
    id = "owner"


BIZ = "biz1"
BIZ_ROW = {"id": BIZ, "owner_id": "owner", "name": "Kev's Barbershop"}


# ─── The composer ────────────────────────────────────────────────────

def test_quantity_tiers_ask_a_second_number_a_human_would_say():
    assert rq.quantity_tiers(200) == [200, 500]
    assert rq.quantity_tiers(1000) == [1000, 2500]
    assert rq.quantity_tiers(None) == []
    assert rq.quantity_tiers(0) == []


def test_the_letter_carries_real_numbers():
    out = rq.compose_rfq(
        biz={"name": "Kev's Barbershop"},
        supplier={"id": "abc123de", "name": "Northwind", "email": "o@n.com",
                  "contact_name": "Dana"},
        need="blank hoodies, screen-print ready", qty=200,
        offering={"name": "Shop Hoodie"}, sells=["Haircut", "Shop Hoodie"])
    body = out["body"]
    assert "Hello Dana," in body
    assert "Kev's Barbershop" in body
    assert "200 and 500 units" in body
    assert "Your minimum order" in body
    assert "Lead time" in body
    assert "200" in out["subject"]


def test_a_missing_fact_drops_its_line_rather_than_printing_a_blank():
    """No contact name, nothing sold on file, no quantity, no product."""
    out = rq.compose_rfq(
        biz={"name": "Kev's"}, supplier={"id": "x", "name": "Acme"},
        need="corrugated boxes")
    body = out["body"]
    assert "Hello Acme," in body
    assert "where we sell" not in body      # no "we sell []"
    assert "()" not in body
    assert "[" not in body and "]" not in body
    # With no quantity it still asks a useful question.
    assert "quantity your pricing starts at" in body


def test_greeting_falls_back_from_contact_to_company_to_plain():
    named = rq.compose_rfq(biz={"name": "K"}, need="hoodies",
                           supplier={"id": "1", "name": "Acme", "contact_name": "Dana"})
    company = rq.compose_rfq(biz={"name": "K"}, need="hoodies",
                             supplier={"id": "1", "name": "Acme"})
    nobody = rq.compose_rfq(biz={"name": "K"}, need="hoodies", supplier={"id": "1"})
    assert named["body"].startswith("Hello Dana,")
    assert company["body"].startswith("Hello Acme,")
    assert nobody["body"].startswith("Hello,")


def test_the_product_line_is_not_repeated_when_the_need_already_says_it():
    out = rq.compose_rfq(
        biz={"name": "K"}, supplier={"id": "1", "name": "A"},
        need="blank Shop Hoodie bodies", offering={"name": "Shop Hoodie"})
    assert out["body"].count("Shop Hoodie") == 1


# ─── Preview and send are the same letter ────────────────────────────

def _stub(monkeypatch, *, supplier, rfq_rows=None, offerings=None):
    rfq_rows = rfq_rows if rfq_rows is not None else []

    def _get(path):
        if path.startswith("/businesses"):
            return [BIZ_ROW]
        if path.startswith("/suppliers?id=in."):
            return [supplier]
        if path.startswith("/suppliers"):
            return [supplier]
        if path.startswith("/vendor_rfqs"):
            return rfq_rows
        if path.startswith("/offerings"):
            return offerings if offerings is not None else []
        return []

    monkeypatch.setattr(sr.sb_clients, "sb_get_as_service", _get)
    monkeypatch.setattr(sr.billing_limits, "require_units", lambda biz: None)


SUP = {"id": "sup1", "business_id": BIZ, "name": "Northwind",
       "email": "orders@northwind.com", "status": "candidate"}


def test_the_preview_is_the_email_not_an_impression_of_it(monkeypatch):
    """If preview and send could drift, the practitioner would be
    approving something that never goes out."""
    _stub(monkeypatch, supplier=SUP)
    sent = {}

    async def fake_send(**kw):
        sent.update(kw)
        return {"id": "e1"}

    import email_sender
    monkeypatch.setattr(email_sender, "send_via_resend", fake_send)
    monkeypatch.setattr(sr.sb_clients, "sb_post_as_service", lambda p, b, **kw: [b])
    monkeypatch.setattr(sr.sb_clients, "sb_patch_as_service", lambda p, b: b)

    body = sr.RfqBody(supplier_ids=["sup1"], need="blank hoodies", qty=200)
    pre = sr.preview_rfq(BIZ, body, user=_U())
    asyncio.run(sr.send_rfq(BIZ, body, user=_U()))

    assert pre["letters"][0]["subject"] == sent["subject"]
    assert pre["letters"][0]["body"] == sent["body"]


def test_preview_sends_nothing(monkeypatch):
    _stub(monkeypatch, supplier=SUP)

    async def boom(**kw):
        pytest.fail("preview sent an email")

    import email_sender
    monkeypatch.setattr(email_sender, "send_via_resend", boom)
    out = sr.preview_rfq(BIZ, sr.RfqBody(supplier_ids=["sup1"], need="hoodies"),
                         user=_U())
    assert out["ok"]


def test_preview_flags_a_vendor_with_no_address_while_it_can_be_fixed(monkeypatch):
    _stub(monkeypatch, supplier={**SUP, "email": None})
    out = sr.preview_rfq(BIZ, sr.RfqBody(supplier_ids=["sup1"], need="hoodies"),
                         user=_U())
    assert out["letters"][0]["blocked"] == "no_email"


# ─── The constraints that stop this being a blast tool ───────────────

def test_the_fan_out_is_capped(monkeypatch):
    _stub(monkeypatch, supplier=SUP)
    ids = [f"s{i}" for i in range(sr.RFQ_FAN_OUT_CAP + 1)]
    with pytest.raises(HTTPException) as e:
        sr.preview_rfq(BIZ, sr.RfqBody(supplier_ids=ids, need="hoodies"), user=_U())
    assert e.value.status_code == 400
    assert e.value.detail["error"] == "fan_out_cap"


def test_the_same_vendor_twice_in_one_request_is_one_email(monkeypatch):
    """A UI slip must not become two emails to the same inbox."""
    _stub(monkeypatch, supplier=SUP)
    calls = []

    async def fake_send(**kw):
        calls.append(kw["to_email"])
        return {}

    import email_sender
    monkeypatch.setattr(email_sender, "send_via_resend", fake_send)
    monkeypatch.setattr(sr.sb_clients, "sb_post_as_service", lambda p, b, **kw: [b])
    monkeypatch.setattr(sr.sb_clients, "sb_patch_as_service", lambda p, b: b)

    out = asyncio.run(sr.send_rfq(
        BIZ, sr.RfqBody(supplier_ids=["sup1", "sup1", "sup1"], need="hoodies"),
        user=_U()))
    assert len(calls) == 1
    assert out["sent_count"] == 1


def test_the_daily_ceiling_refuses_before_anything_is_sent(monkeypatch):
    _stub(monkeypatch, supplier=SUP,
          rfq_rows=[{"id": f"r{i}"} for i in range(sr.DAILY_RFQ_CAP)])

    async def boom(**kw):
        pytest.fail("sent past the daily cap")

    import email_sender
    monkeypatch.setattr(email_sender, "send_via_resend", boom)
    with pytest.raises(HTTPException) as e:
        asyncio.run(sr.send_rfq(BIZ, sr.RfqBody(supplier_ids=["sup1"],
                                                need="hoodies"), user=_U()))
    assert e.value.status_code == 429


def test_asking_the_same_vendor_the_same_week_is_refused_until_meant(monkeypatch):
    recent = [{"id": "r1", "need": "hoodies", "sent_at": "2026-08-20T00:00:00Z"}]
    _stub(monkeypatch, supplier=SUP, rfq_rows=recent)
    calls = []

    async def fake_send(**kw):
        calls.append(kw)
        return {}

    import email_sender
    monkeypatch.setattr(email_sender, "send_via_resend", fake_send)
    monkeypatch.setattr(sr.sb_clients, "sb_post_as_service", lambda p, b, **kw: [b])
    monkeypatch.setattr(sr.sb_clients, "sb_patch_as_service", lambda p, b: b)

    out = asyncio.run(sr.send_rfq(
        BIZ, sr.RfqBody(supplier_ids=["sup1"], need="hoodies"), user=_U()))
    assert out["sent_count"] == 0
    assert out["results"][0]["needs_force"] is True
    assert calls == []

    forced = asyncio.run(sr.send_rfq(
        BIZ, sr.RfqBody(supplier_ids=["sup1"], need="hoodies", force=True),
        user=_U()))
    assert forced["sent_count"] == 1


# ─── Partial failure is reported, not hidden ─────────────────────────

def test_a_vendor_with_no_address_is_skipped_and_named(monkeypatch):
    _stub(monkeypatch, supplier={**SUP, "email": ""})

    async def boom(**kw):
        pytest.fail("sent to an empty address")

    import email_sender
    monkeypatch.setattr(email_sender, "send_via_resend", boom)
    out = asyncio.run(sr.send_rfq(
        BIZ, sr.RfqBody(supplier_ids=["sup1"], need="hoodies"), user=_U()))
    assert out["sent_count"] == 0
    assert "no email" in out["results"][0]["reason"]


def test_one_bad_address_does_not_abort_the_batch(monkeypatch):
    """Being told 'the whole thing failed' is how a vendor gets asked
    twice."""
    sups = {
        "good": {"id": "good", "business_id": BIZ, "name": "Good",
                 "email": "a@good.com", "status": "candidate"},
        "bad": {"id": "bad", "business_id": BIZ, "name": "Bad",
                "email": "b@bad.com", "status": "candidate"},
    }

    def _get(path):
        if path.startswith("/businesses"):
            return [BIZ_ROW]
        if path.startswith("/vendor_rfqs"):
            return []
        if path.startswith("/offerings"):
            return []
        for k, v in sups.items():
            if f"id=eq.{k}" in path:
                return [v]
        return []

    monkeypatch.setattr(sr.sb_clients, "sb_get_as_service", _get)
    monkeypatch.setattr(sr.billing_limits, "require_units", lambda biz: None)
    monkeypatch.setattr(sr.sb_clients, "sb_post_as_service", lambda p, b, **kw: [b])
    monkeypatch.setattr(sr.sb_clients, "sb_patch_as_service", lambda p, b: b)

    async def fake_send(**kw):
        if kw["to_email"] == "b@bad.com":
            raise RuntimeError("bounced")
        return {}

    import email_sender
    monkeypatch.setattr(email_sender, "send_via_resend", fake_send)

    out = asyncio.run(sr.send_rfq(
        BIZ, sr.RfqBody(supplier_ids=["bad", "good"], need="hoodies"), user=_U()))
    by_name = {r["name"]: r for r in out["results"]}
    assert by_name["Good"]["sent"] is True
    assert by_name["Bad"]["sent"] is False
    assert out["sent_count"] == 1


def test_a_lost_receipt_still_reports_the_email_as_sent(monkeypatch):
    """The email is already gone. Reporting 'not sent' because the row
    failed to save is how a vendor gets asked twice."""
    _stub(monkeypatch, supplier=SUP)

    async def fake_send(**kw):
        return {}

    def _boom(p, b, **kw):
        raise RuntimeError("supabase is having a day")

    import email_sender
    monkeypatch.setattr(email_sender, "send_via_resend", fake_send)
    monkeypatch.setattr(sr.sb_clients, "sb_post_as_service", _boom)
    monkeypatch.setattr(sr.sb_clients, "sb_patch_as_service", lambda p, b: b)

    out = asyncio.run(sr.send_rfq(
        BIZ, sr.RfqBody(supplier_ids=["sup1"], need="hoodies"), user=_U()))
    assert out["sent_count"] == 1
    assert out["results"][0]["sent"] is True


# ─── Status moves one way ────────────────────────────────────────────

def test_a_candidate_becomes_contacted(monkeypatch):
    _stub(monkeypatch, supplier=SUP)
    patches = []

    async def fake_send(**kw):
        return {}

    import email_sender
    monkeypatch.setattr(email_sender, "send_via_resend", fake_send)
    monkeypatch.setattr(sr.sb_clients, "sb_post_as_service", lambda p, b, **kw: [b])
    monkeypatch.setattr(sr.sb_clients, "sb_patch_as_service",
                        lambda p, b: patches.append((p, b)))

    asyncio.run(sr.send_rfq(BIZ, sr.RfqBody(supplier_ids=["sup1"], need="hoodies"),
                            user=_U()))
    assert any(b.get("status") == "contacted" for _, b in patches)


def test_an_active_supplier_is_not_demoted_to_contacted(monkeypatch):
    """Asking an existing supplier for a fresh quote does not make them a
    prospect again."""
    _stub(monkeypatch, supplier={**SUP, "status": "active"})
    patches = []

    async def fake_send(**kw):
        return {}

    import email_sender
    monkeypatch.setattr(email_sender, "send_via_resend", fake_send)
    monkeypatch.setattr(sr.sb_clients, "sb_post_as_service", lambda p, b, **kw: [b])
    monkeypatch.setattr(sr.sb_clients, "sb_patch_as_service",
                        lambda p, b: patches.append((p, b)))

    asyncio.run(sr.send_rfq(BIZ, sr.RfqBody(supplier_ids=["sup1"], need="hoodies"),
                            user=_U()))
    assert not any(b.get("status") == "contacted" for _, b in patches)


def test_a_non_owner_cannot_send_from_the_business(monkeypatch):
    monkeypatch.setattr(sr.sb_clients, "sb_get_as_service",
                        lambda path: [{"id": BIZ, "owner_id": "somebody-else"}])

    class _Other:
        id = "intruder"

    with pytest.raises(HTTPException) as e:
        asyncio.run(sr.send_rfq(BIZ, sr.RfqBody(supplier_ids=["sup1"], need="hoodies"),
                                user=_Other()))
    assert e.value.status_code == 403
