"""Chief reports an invoice it created as created, and finds a module by name.

2026-09-18, Kevin, on a call: "2 actions didn't go through: create module
entry (I couldn't find that — double-check the details and try again.);
create invoice (name 'is_owner' is not defined)."

The invoice (INV-2026-014, $10, Jessica McCloud) WAS created, with a
payment link. handle_create_invoice inserted the row, then raised
NameError building its return value: `is_owner` had been deleted by the
2026-07-11 owner-gate change and one reference survived. Every invoice
Chief drafted since then was reported as a failure after being saved.

The module entry failed because handle_create_module_entry looked the
module up by id only, while the model (and the practitioner) name it.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import chief_of_staff as cos

_BIZ = {"id": "biz-1", "owner_id": "user-1", "name": "KMJ Creative Solutions",
        "type": "coach", "settings": {}}


def _sb_recorder(routes):
    calls = []

    async def fake_sb(client, method, path, body=None):
        calls.append((method, path, body))
        for (m, prefix), resp in routes.items():
            if method == m and path.startswith(prefix):
                return resp(body) if callable(resp) else resp
        return []

    return fake_sb, calls


def test_a_created_invoice_is_reported_as_created(monkeypatch):
    fake_sb, calls = _sb_recorder({
        ("GET", "/contacts"): [{"id": "c1", "name": "Jessica McCloud", "email": "j@x.com"}],
        ("GET", "/invoices"): [],
        ("POST", "/invoices"): lambda body: [{"id": "inv-1", **body}],
    })
    monkeypatch.setattr(cos, "_sb", fake_sb)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    res = asyncio.run(cos.handle_create_invoice(None, _BIZ, {
        "contact_id": "c1",
        "items": [{"description": "Flyer design", "quantity": 1, "unit_price": 10}],
    }))
    assert not cos._action_failed(res), res
    assert res["result"] == "drafted" and res["invoice_id"] == "inv-1"
    assert res["total"] == 10.0 and "Jessica McCloud" in res["label"]
    assert res["stripe_auto_generated"] is False
    assert any(m == "POST" and p.startswith("/invoices") for m, p, _ in calls)


def test_a_manual_pay_link_is_not_called_auto_generated(monkeypatch):
    biz = {**_BIZ, "settings": {"payments": {"stripe_link": "https://buy.stripe.com/manual"}}}
    fake_sb, _ = _sb_recorder({
        ("GET", "/contacts"): [{"id": "c1", "name": "Jessica McCloud"}],
        ("POST", "/invoices"): lambda body: [{"id": "inv-2", **body}],
    })
    monkeypatch.setattr(cos, "_sb", fake_sb)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    res = asyncio.run(cos.handle_create_invoice(None, biz, {
        "contact_id": "c1", "items": [{"description": "Flyer design", "unit_price": 10}]}))
    assert not cos._action_failed(res)
    assert res["stripe_payment_url"] == "https://buy.stripe.com/manual"
    assert res["stripe_auto_generated"] is False


def test_a_module_entry_finds_the_module_by_name(monkeypatch):
    module = {"id": "m1", "name": "Flyer Orders", "slug": "flyer-orders", "agent_config": {}}
    fake_sb, calls = _sb_recorder({
        ("GET", "/custom_modules?id=eq."): [],
        ("GET", "/custom_modules?name=ilike."): [module],
        ("GET", "/custom_modules?slug=eq."): [module],
        ("POST", "/module_entries"): lambda body: [{"id": "e1", **body}],
    })
    monkeypatch.setattr(cos, "_sb", fake_sb)
    for action in ({"module_name": "Flyer Orders", "data": {"title": "Jessica McCloud flyer"}},
                   {"module_id": "flyer-orders", "data": {"title": "Jessica McCloud flyer"}},
                   {"module_slug": "flyer-orders", "data": {"title": "Jessica McCloud flyer"}}):
        calls.clear()
        res = asyncio.run(cos.handle_create_module_entry(None, _BIZ, action))
        assert not cos._action_failed(res), (action, res)
        assert res["label"] == "Flyer Orders: Jessica McCloud flyer"
        posted = [b for m, p, b in calls if m == "POST" and p.startswith("/module_entries")]
        assert posted and posted[0]["module_id"] == "m1"


def test_a_missing_module_is_named_in_plain_words(monkeypatch):
    fake_sb, _ = _sb_recorder({})
    monkeypatch.setattr(cos, "_sb", fake_sb)
    res = asyncio.run(cos.handle_create_module_entry(None, _BIZ, {"module_name": "Invoices", "data": {}}))
    assert cos._action_failed(res)
    assert 'no module called "Invoices"' in res["result"]
    assert "which module" in res["result"]
    assert "double-check" not in res["result"]
