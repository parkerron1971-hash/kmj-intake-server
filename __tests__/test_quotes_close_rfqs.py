"""THE SOURCING DESK stage 3 — a quote coming back closes the RFQ.

An RFQ stuck at 'sent' forever is the follow-through failure in
miniature: the app asked somebody a question on the practitioner's behalf
and then had no idea whether it was ever answered. When a price gets
written down against that vendor, the answer plainly arrived.

The subtle half is the TRANSITION. Editing a price that was already there
is a correction, not a reply, and treating it as one would keep
re-closing loops that were closed weeks ago — and, worse, mark an RFQ
'replied' on the day someone tidied up a number.
"""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest

import sb_clients
import suppliers_router as sr


class _U:
    id = "owner"


BIZ = "biz1"
SUP = "sup1"
OFF = "off1"
LINK = "link1"


def _install(monkeypatch, *, link, rfq_rows, existing=None, patches=None,
             posts=None):
    def _get(path):
        if path.startswith("/businesses"):
            return [{"id": BIZ, "owner_id": "owner"}]
        if path.startswith("/vendor_rfqs"):
            return rfq_rows
        if path.startswith("/offering_suppliers?id=eq."):
            return [link]
        if "supplier_id=eq.sup1&select=id,unit_cost" in path:
            return existing if existing is not None else []
        if path.startswith("/offering_suppliers?offering_id=eq."):
            return []
        if path.startswith("/suppliers?id=eq.sup1&select=*"):
            return [{"id": SUP, "business_id": BIZ, "name": "Northwind"}]
        if path.startswith("/suppliers"):
            return [{"id": SUP, "business_id": BIZ, "name": "Northwind",
                     "email": "o@n.com"}]
        if path.startswith("/offerings"):
            return [{"id": OFF}]
        return []

    monkeypatch.setattr(sb_clients, "sb_get_as_service", _get)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda p, b: (patches.append((p, b))
                                      if patches is not None else None))
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, **kw: (posts.append((p, b))
                                            if posts is not None else None)
                        or [{"id": LINK, **b}])
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", lambda p: True)


def _rfq_patches(patches):
    return [(p, b) for p, b in patches if p.startswith("/vendor_rfqs")]


BASE_LINK = {"id": LINK, "business_id": BIZ, "offering_id": OFF,
             "supplier_id": SUP, "unit_cost": None, "is_primary": True}


def test_the_first_price_closes_the_open_request(monkeypatch):
    patches = []
    _install(monkeypatch, link=BASE_LINK, rfq_rows=[{"id": "r1"}], patches=patches)
    sr.update_link(LINK, sr.LinkPatch(unit_cost=12.5), user=_U())
    closed = _rfq_patches(patches)
    assert closed, "a quote came back and the request stayed open"
    assert closed[0][1]["status"] == "replied"
    assert closed[0][1]["replied_at"]


def test_correcting_a_price_that_was_already_there_is_not_a_reply(monkeypatch):
    """Otherwise tidying up a number would mark an RFQ answered."""
    patches = []
    _install(monkeypatch, link={**BASE_LINK, "unit_cost": 12.5},
             rfq_rows=[{"id": "r1"}], patches=patches)
    sr.update_link(LINK, sr.LinkPatch(unit_cost=11.0), user=_U())
    assert _rfq_patches(patches) == []


def test_a_change_that_is_not_a_price_closes_nothing(monkeypatch):
    patches = []
    _install(monkeypatch, link=BASE_LINK, rfq_rows=[{"id": "r1"}], patches=patches)
    sr.update_link(LINK, sr.LinkPatch(moq=24), user=_U())
    assert _rfq_patches(patches) == []


def test_only_SENT_requests_move(monkeypatch):
    """A closed RFQ stays closed, and a draft was never asked."""
    patches = []
    _install(monkeypatch, link=BASE_LINK, rfq_rows=[], patches=patches)
    sr.update_link(LINK, sr.LinkPatch(unit_cost=9.0), user=_U())
    assert _rfq_patches(patches) == []
    # The query itself is what enforces this — assert it asks for 'sent'.
    seen = {}
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path: (seen.setdefault("p", path)
                                      if "vendor_rfqs" in path else None) or [])
    sr._close_rfq_for(BIZ, SUP)
    assert "status=eq.sent" in seen["p"]


def test_logging_a_quote_for_a_brand_new_link_closes_it_too(monkeypatch):
    """The common shape: a vendor who was asked but did not yet supply
    the product comes back with a price."""
    patches, posts = [], []
    _install(monkeypatch, link=BASE_LINK, rfq_rows=[{"id": "r1"}],
             existing=[], patches=patches, posts=posts)
    sr.link_product(SUP, sr.LinkBody(offering_id=OFF, unit_cost=14.0), user=_U())
    assert _rfq_patches(patches), "a new quote left the request open"


def test_relogging_against_a_link_that_already_had_a_price_is_not_a_reply(monkeypatch):
    patches, posts = [], []
    _install(monkeypatch, link={**BASE_LINK, "unit_cost": 14.0},
             rfq_rows=[{"id": "r1"}],
             existing=[{"id": LINK, "unit_cost": 14.0}],
             patches=patches, posts=posts)
    sr.link_product(SUP, sr.LinkBody(offering_id=OFF, unit_cost=13.0), user=_U())
    assert _rfq_patches(patches) == []


def test_a_failure_to_close_never_loses_the_quote(monkeypatch):
    """The price is the thing the practitioner was actually saving."""
    patches = []
    _install(monkeypatch, link=BASE_LINK, rfq_rows=[{"id": "r1"}], patches=patches)

    def _boom(path):
        if "vendor_rfqs" in path:
            raise RuntimeError("supabase is having a day")
        return [BASE_LINK] if "offering_suppliers?id=eq." in path else [
            {"id": BIZ, "owner_id": "owner"}]

    monkeypatch.setattr(sb_clients, "sb_get_as_service", _boom)
    out = sr.update_link(LINK, sr.LinkPatch(unit_cost=12.5), user=_U())
    assert out["ok"]
