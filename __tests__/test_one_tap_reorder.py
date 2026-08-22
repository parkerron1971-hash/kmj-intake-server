"""ONE TAP — and the three things that must all be true before it is offered.

The low-stock alert can now carry send_purchase_order instead of
draft_purchase_order, so a single tap places the order. The tap is the
approval, exactly as the action registry describes it — nothing here
sends unattended, and this is not the outbox change that would allow
that.

Which makes the question "when is the button allowed to appear", and
these are the three answers:

  1. the OWNER granted it, on that specific vendor
  2. there is an address to send to
  3. a reorder QUANTITY is on file

The third is the one that looks like bureaucracy and is not. The tap is
the approval, so the notification has to be able to say exactly what it
will order. "Tap to send an order" without a number asks somebody to
approve something unstated — and the send would fail anyway, because
_po_qty returns None and the verb refuses.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import reorder_engine as re_  # noqa: E402
import suppliers_router as sr  # noqa: E402
import sb_clients  # noqa: E402

BIZ = "b1"
OFF = "off_tee"
SUP = "sup1"


# ─── one_tap_vendor: the permission is read, never assumed ───────────

def _stub(monkeypatch, *, links, supplier_rows):
    def _get(path):
        if path.startswith("/offering_suppliers"):
            return links
        if path.startswith("/suppliers"):
            return supplier_rows
        return []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _get)


def test_a_granted_vendor_is_returned(monkeypatch):
    _stub(monkeypatch, links=[{"supplier_id": SUP}],
          supplier_rows=[{"id": SUP, "name": "Acme", "email": "o@acme.com"}])
    got = re_.one_tap_vendor(BIZ, OFF)
    assert got and got["name"] == "Acme"


def test_a_vendor_without_the_grant_is_not_returned(monkeypatch):
    """The query filters on chief_can_reorder — a vendor that has not been
    granted it simply does not come back."""
    seen = {}

    def _get(path):
        if path.startswith("/offering_suppliers"):
            return [{"supplier_id": SUP}]
        seen["path"] = path
        return []      # the filter matched nothing

    monkeypatch.setattr(sb_clients, "sb_get_as_service", _get)
    assert re_.one_tap_vendor(BIZ, OFF) is None
    assert "chief_can_reorder=is.true" in seen["path"], seen["path"]


def test_a_product_with_no_primary_vendor_gets_nothing(monkeypatch):
    _stub(monkeypatch, links=[], supplier_rows=[])
    assert re_.one_tap_vendor(BIZ, OFF) is None


def test_a_lookup_failure_falls_back_rather_than_assuming_permission(monkeypatch):
    """The safe direction is always "draft it". Never the other way."""
    def _boom(path):
        raise RuntimeError("supabase is having a day")
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _boom)
    assert re_.one_tap_vendor(BIZ, OFF) is None


# ─── The sweep: which payload the notification carries ───────────────

def _run_sweep(monkeypatch, *, offering, one_tap):
    """Drive the sweep with a single tripped offering and capture the
    alert it would raise."""
    captured = {}

    async def fake_alert(client, bid, **kw):
        captured.update(kw)
        captured["business_id"] = bid
        return {"id": "n1"}

    async def fake_active(client):
        return [BIZ]

    import notification_engine as ne
    monkeypatch.setattr(ne, "create_urgent_alert", fake_alert)
    monkeypatch.setattr(ne, "_all_active_business_ids", fake_active)
    monkeypatch.setattr(ne, "_within_waking_hours", lambda now: True)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [offering])
    monkeypatch.setattr(re_, "one_tap_vendor", lambda b, o: one_tap)
    monkeypatch.setattr(re_, "tripped", lambda rows: [offering])

    asyncio.run(re_.low_stock_reorder_sweep())
    return captured


READY = {"id": OFF, "business_id": BIZ, "name": "Blueprint Tee",
         "inventory_qty": 3, "reorder_at": 5, "reorder_qty": 25,
         "supplier_name": "Acme", "supplier_email": "orders@acme.com"}


def test_a_granted_vendor_gets_a_SEND_payload(monkeypatch):
    cap = _run_sweep(monkeypatch, offering=READY,
                     one_tap={"id": SUP, "name": "Acme", "email": "o@acme.com"})
    payload = cap["action_payload"]
    assert payload["type"] == "send_purchase_order"
    assert payload["offering_id"] == OFF
    # The quantity travels WITH the payload, so the tap cannot resolve to
    # a different number than the one the practitioner was shown.
    assert payload["qty"] == 25


def test_the_notification_says_exactly_what_the_tap_will_order(monkeypatch):
    """The tap IS the approval, so what it does has to be legible before
    it happens, not after."""
    cap = _run_sweep(monkeypatch, offering=READY,
                     one_tap={"id": SUP, "name": "Acme", "email": "o@acme.com"})
    body = cap["body"]
    assert "25" in body
    assert "Blueprint Tee" in body
    assert "Acme" in body
    assert "25" in cap["suggested_action"] and "Acme" in cap["suggested_action"]


def test_without_the_grant_it_still_only_DRAFTS(monkeypatch):
    cap = _run_sweep(monkeypatch, offering=READY, one_tap=None)
    assert cap["action_payload"]["type"] == "draft_purchase_order"
    assert "nothing sends without your say-so" in cap["body"]


def test_no_reorder_quantity_means_no_one_tap_send(monkeypatch):
    """Not bureaucracy: the notification could not state what it would
    order, and the send would refuse anyway for want of a quantity."""
    no_qty = {**READY, "reorder_qty": None}
    called = {"n": 0}

    def _spy(b, o):
        called["n"] += 1
        return {"id": SUP, "name": "Acme"}

    monkeypatch.setattr(re_, "one_tap_vendor", _spy)
    cap = _run_sweep(monkeypatch, offering=no_qty,
                     one_tap={"id": SUP, "name": "Acme"})
    assert cap["action_payload"]["type"] == "draft_purchase_order"


def test_no_supplier_email_means_no_one_tap_send(monkeypatch):
    no_email = {**READY, "supplier_email": ""}
    cap = _run_sweep(monkeypatch, offering=no_email,
                     one_tap={"id": SUP, "name": "Acme"})
    assert cap["action_payload"]["type"] == "draft_purchase_order"


# ─── The router guard ────────────────────────────────────────────────

def _sup_stub(monkeypatch, supplier, patches):
    def _get(path):
        if path.startswith("/businesses"):
            return [{"id": BIZ, "owner_id": "owner"}]
        if path.startswith("/suppliers"):
            return [supplier]
        return []
    monkeypatch.setattr(sr.sb_clients, "sb_get_as_service", _get)
    monkeypatch.setattr(sr.sb_clients, "sb_patch_as_service",
                        lambda p, b: patches.append((p, b)))


class _U:
    id = "owner"


BASE_SUP = {"id": SUP, "business_id": BIZ, "name": "Acme",
            "email": "orders@acme.com", "source": "manual", "status": "active"}


def test_it_cannot_be_turned_on_without_an_address(monkeypatch):
    """A button that fails the moment somebody taps it is worse than a
    button that never appears."""
    _sup_stub(monkeypatch, {**BASE_SUP, "email": None}, [])
    with pytest.raises(HTTPException) as e:
        sr.update_supplier(SUP, sr.SupplierPatch(chief_can_reorder=True), user=_U())
    assert e.value.status_code == 400
    assert e.value.detail["error"] == "no_email"


def test_it_can_be_turned_on_when_there_is_an_address(monkeypatch):
    patches = []
    _sup_stub(monkeypatch, BASE_SUP, patches)
    sr.update_supplier(SUP, sr.SupplierPatch(chief_can_reorder=True), user=_U())
    assert any(b.get("chief_can_reorder") is True for _, b in patches)


def test_turning_it_OFF_never_needs_an_address(monkeypatch):
    """Revoking must always be possible, whatever state the vendor is in."""
    patches = []
    _sup_stub(monkeypatch, {**BASE_SUP, "email": None}, patches)
    sr.update_supplier(SUP, sr.SupplierPatch(chief_can_reorder=False), user=_U())
    assert any(b.get("chief_can_reorder") is False for _, b in patches)


def test_clearing_the_address_revokes_the_one_tap_send(monkeypatch):
    """Otherwise the grant stays armed with nowhere to fire."""
    patches = []
    _sup_stub(monkeypatch, {**BASE_SUP, "chief_can_reorder": True}, patches)
    sr.update_supplier(SUP, sr.SupplierPatch(clear=["email"]), user=_U())
    body = patches[0][1]
    assert body["email"] is None
    assert body["chief_can_reorder"] is False


def test_a_false_grant_is_not_swallowed_as_None(monkeypatch):
    """The bool goes through untouched — running it past the string
    cleaner would turn a deliberate "no" into "unset"."""
    patches = []
    _sup_stub(monkeypatch, {**BASE_SUP, "chief_can_reorder": True}, patches)
    sr.update_supplier(SUP, sr.SupplierPatch(chief_can_reorder=False), user=_U())
    assert patches[0][1]["chief_can_reorder"] is False


def test_only_the_owner_can_grant_it(monkeypatch):
    monkeypatch.setattr(sr.sb_clients, "sb_get_as_service",
                        lambda path: ([{"id": SUP, "business_id": BIZ}]
                                      if path.startswith("/suppliers")
                                      else [{"id": BIZ, "owner_id": "somebody-else"}]))

    class _Other:
        id = "intruder"

    with pytest.raises(HTTPException) as e:
        sr.update_supplier(SUP, sr.SupplierPatch(chief_can_reorder=True), user=_Other())
    assert e.value.status_code == 403
