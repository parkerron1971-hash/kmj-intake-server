"""THE ORDERING LADDER — how much of a purchase can be handled for you.

Three clusters, and the first is the one that matters most.

THE SOFT-404. Four of the sixteen enterprise suppliers probed on
2026-08-21 answer a /.well-known path with HTTP 200 and an HTML app
shell — Grainger, Faire, Alibaba and 4imprint all do it. A detector that
trusted a status code would have declared four major suppliers
agent-ready on the strength of a React error page, and the badge that
follows tells a practitioner how much of an order Chief can handle. So
the parser is tested against the exact shapes that lie.

THE PO NUMBER. It used to be derived from the product and the date, so
two orders of the same product on the same day shared a number — the one
thing a PO number exists not to do, because it is how a supplier's
invoice finds the order it answers.

THE ACCOUNT NUMBER. Theirs, never ours. It is printed when present and
absent when not; a half-written "Account:" line is worse than no line.
"""
from __future__ import annotations

import json
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import agent_readiness as ar
import reorder_engine as re_


# ─── The soft-404 guard ──────────────────────────────────────────────

# Shapes taken from what real suppliers actually served on 2026-08-21.
HTML_SHAPES = [
    b'<!doctype html>\n<html lang="en">\n<head>\n\t<meta charset="UTF-8">',      # grainger
    b'<!DOCTYPE html><html lang="en"><head><meta charSet="utf-8"/>',             # faire
    b'\r\n\r\n<!DOCTYPE html>\r\n<html class="no-js" lang="en">\r\n<head>\r',    # 4imprint
    b'   <html><body>Not found</body></html>',
]


@pytest.mark.parametrize("body", HTML_SHAPES)
def test_an_html_page_served_with_200_is_not_a_manifest(body):
    """The exact failure that would have branded Grainger agent-ready."""
    ready, detail = ar.parse_manifest(body, "text/html")
    assert ready is False
    assert detail["reason"] == "html_not_json"


def test_json_that_is_not_a_manifest_is_rejected():
    ready, _ = ar.parse_manifest(b'{"hello":"world"}', "application/json")
    assert ready is False


def test_empty_and_garbage_are_rejected():
    assert ar.parse_manifest(b"", "")[0] is False
    assert ar.parse_manifest(b"not json at all", "application/json")[0] is False
    assert ar.parse_manifest(b'["a","b"]', "application/json")[0] is False


# ─── The live shape, and the documented variants ─────────────────────

LIVE = json.dumps({
    # Read off a production manifest, not a write-up: nested under `ucp`,
    # version inside. Both published descriptions had this wrong.
    "ucp": {
        "version": "2026-04-08",
        "supported_versions": ["2026-04-08"],
        "services": {"dev.ucp.shopping": {"version": "1", "rest": {}}},
        "capabilities": [],
        "payment_handlers": [],
    }
}).encode()


def test_the_real_world_manifest_is_recognised():
    ready, detail = ar.parse_manifest(LIVE, "application/json")
    assert ready is True
    assert detail["version"] == "2026-04-08"
    assert detail["shopping"] is True
    assert "dev.ucp.shopping" in detail["services"]


def test_the_flat_documented_variant_is_also_accepted():
    """One write-up described a top-level `ucp_version`. Hard-validating
    either single spelling would reject half of a real world."""
    flat = json.dumps({"ucp_version": "2026-01-12",
                       "services": {"dev.ucp.shopping": {}}}).encode()
    ready, detail = ar.parse_manifest(flat, "application/json")
    assert ready is True
    assert detail["shopping"] is True


@pytest.mark.parametrize("payload", [
    # ucp_version as the ONLY marker — no services, no capabilities. This
    # is what actually pins the documented-variant fallback; a payload
    # that also carries `services` would pass on that alone and prove
    # nothing about the version key.
    {"ucp_version": "2026-01-12"},
    {"ucp": {"ucp_version": "2026-01-12"}},
])
def test_the_version_key_alone_is_enough(payload):
    ready, _ = ar.parse_manifest(json.dumps(payload).encode(), "application/json")
    assert ready is True


def test_a_manifest_with_no_shopping_service_is_still_a_manifest():
    """Agent-ready and orderable are not the same claim."""
    other = json.dumps({"ucp": {"version": "1",
                                "services": {"dev.ucp.support": {}}}}).encode()
    ready, detail = ar.parse_manifest(other, "application/json")
    assert ready is True
    assert detail["shopping"] is False


# ─── Domain normalisation ────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("https://www.AnnieInc.com/wholesale?x=1", "annieinc.com"),
    ("orders@annieinc.com", "annieinc.com"),
    ("annieinc.com/", "annieinc.com"),
    ("  HTTP://AnnieInc.com  ", "annieinc.com"),
    ("", None),
    (None, None),
])
def test_domain_normalisation(raw, expected):
    assert ar.normalise_domain(raw) == expected


# ─── The PO number cannot collide ────────────────────────────────────

def test_the_po_number_comes_from_the_sequence(monkeypatch):
    seen = {}

    def _rpc(path, body, **kw):
        seen["path"] = path
        seen["biz"] = body.get("p_business_id")
        return "PO-2026-0042"

    monkeypatch.setattr(re_.sb_clients, "sb_post_as_service", _rpc)
    assert re_.next_po_number("biz1") == "PO-2026-0042"
    assert seen["path"] == "/rpc/next_po_number"
    assert seen["biz"] == "biz1"


def test_two_orders_of_one_product_on_one_day_get_different_numbers(monkeypatch):
    """The original bug, stated as a test: the old scheme derived the
    number from the product id and the date, so this pair collided."""
    counter = {"n": 0}

    def _rpc(path, body, **kw):
        counter["n"] += 1
        return f"PO-2026-{counter['n']:04d}"

    monkeypatch.setattr(re_.sb_clients, "sb_post_as_service", _rpc)
    offering = {"id": "same-product", "name": "Hoodie",
                "supplier_email": "o@x.com"}
    biz = {"id": "biz1", "name": "Kev's"}
    a = re_.compose_purchase_order(biz, offering, 25)
    b = re_.compose_purchase_order(biz, offering, 25)
    assert a["po_number"] != b["po_number"]


def test_a_counter_outage_still_produces_an_order(monkeypatch):
    """A slightly ugly number beats blocking somebody's stock order."""
    def _boom(path, body, **kw):
        raise RuntimeError("supabase is having a day")

    monkeypatch.setattr(re_.sb_clients, "sb_post_as_service", _boom)
    n = re_.next_po_number("biz1")
    assert n.startswith("PO-")
    assert len(n) > 6


# ─── The account number is theirs, and only printed when real ────────

def _po(supplier=None):
    return re_.compose_purchase_order(
        {"id": "b1", "name": "Kev's Barbershop"},
        {"id": "o1", "name": "Shop Hoodie", "sku": "HD-1",
         "supplier_name": "Annie International",
         "supplier_email": "orders@annieinc.com"},
        25, supplier=supplier, po_number="PO-2026-0007")


def test_the_account_number_is_printed_when_we_have_one():
    body = _po({"account_number": "ACCT-88213"})["body"]
    assert "Account: ACCT-88213" in body


def test_no_account_number_means_no_account_line():
    """An 'Account:' with nothing after it tells a supplier we don't know
    what we're doing."""
    for sup in (None, {}, {"account_number": ""}, {"account_number": "   "}):
        body = _po(sup)["body"]
        assert "Account:" not in body


def test_nothing_ever_invents_an_account_number():
    out = _po(None)
    assert out["account_number"] is None
    assert "ACCT" not in out["body"]


def test_the_po_still_addresses_the_vendor_without_an_entity():
    """The cache on the offering is enough to send; the entity only adds
    the account line."""
    out = _po(None)
    assert out["to_email"] == "orders@annieinc.com"
    assert out["to_name"] == "Annie International"
    assert "PO-2026-0007" in out["subject"]
