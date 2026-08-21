"""THE SOURCING DESK stage 0 — the vendor entity, and the cache contract.

The tests that matter here are the CACHE ones. offerings.supplier_name /
supplier_email still address every purchase order this app sends, and
suppliers_router is now the only thing that writes them. A missed sync
does not raise, does not log an error the practitioner sees, and does not
show up until a PO goes to the wrong address an hour later — so the sync
is asserted on every write path that can change who supplies a product.
"""
from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest
from fastapi import HTTPException

import sb_clients
import suppliers_router as sr


class _U:
    id = "owner"


BIZ = "biz1"
SUP = "sup1"
OFF = "off1"


def _install(monkeypatch, *, gets=None, patch_log=None, post_log=None,
             delete_log=None):
    """Route sb_* by path fragment. `gets` maps a substring to a result;
    the first matching fragment wins, so put the specific ones first."""
    gets = gets or []

    def _get(path):
        for frag, result in gets:
            if frag in path:
                return result(path) if callable(result) else result
        return []

    monkeypatch.setattr(sb_clients, "sb_get_as_service", _get)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service",
                        lambda p, b: (patch_log.append((p, b))
                                      if patch_log is not None else None))
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, **kw: (post_log.append((p, b))
                                            if post_log is not None else None)
                        or [{"id": "new1", **b}])
    monkeypatch.setattr(sb_clients, "sb_delete_as_service",
                        lambda p: (delete_log.append(p)
                                   if delete_log is not None else None) or True)


def _offerings_patch(patch_log):
    return [(p, b) for p, b in patch_log if p.startswith("/offerings")]


# ─── The cache contract ──────────────────────────────────────────────

def test_cache_points_at_the_primary_vendor(monkeypatch):
    patches = []
    _install(monkeypatch, patch_log=patches, gets=[
        ("/offering_suppliers?offering_id=eq.off1", [{"supplier_id": SUP}]),
        ("/suppliers?id=eq.sup1", [{"name": "Northwind", "email": "orders@northwind.com"}]),
    ])
    sr._sync_offering_cache(OFF)
    hits = _offerings_patch(patches)
    assert len(hits) == 1
    assert hits[0][1] == {"supplier_name": "Northwind",
                          "supplier_email": "orders@northwind.com"}


def test_no_primary_clears_the_cache_rather_than_leaving_a_stale_address(monkeypatch):
    """The honest answer to 'nobody supplies this' is empty, not the last
    vendor who did. A stale address is a purchase order to a stranger."""
    patches = []
    _install(monkeypatch, patch_log=patches, gets=[
        ("/offering_suppliers?offering_id=eq.off1", []),
    ])
    sr._sync_offering_cache(OFF)
    hits = _offerings_patch(patches)
    assert len(hits) == 1
    assert hits[0][1] == {"supplier_name": None, "supplier_email": None}


def test_cache_sync_never_fails_the_practitioners_save(monkeypatch):
    def _boom(path):
        raise RuntimeError("supabase is having a day")
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _boom)
    sr._sync_offering_cache(OFF)   # must not raise


def test_editing_a_vendors_address_repoints_every_product_it_supplies(monkeypatch):
    """The failure this catches: change the vendor's email, and the six
    products they supply keep mailing the old one."""
    patches = []
    _install(monkeypatch, patch_log=patches, gets=[
        ("/suppliers?id=eq.sup1&select=*", [{"id": SUP, "business_id": BIZ,
                                             "name": "Northwind",
                                             "email": "new@northwind.com",
                                             "source": "manual",
                                             "status": "active"}]),
        ("/businesses?id=eq.biz1", [{"id": BIZ, "owner_id": "owner"}]),
        ("/offering_suppliers?supplier_id=eq.sup1&is_primary=is.true",
         [{"offering_id": "offA"}, {"offering_id": "offB"}]),
        ("/offering_suppliers?offering_id=eq.", [{"supplier_id": SUP}]),
        ("/suppliers?id=eq.sup1&select=name,email",
         [{"name": "Northwind", "email": "new@northwind.com"}]),
    ])
    sr.update_supplier(SUP, sr.SupplierPatch(email="new@northwind.com"), user=_U())
    touched = {p for p, _ in _offerings_patch(patches)}
    assert any("offA" in p for p in touched)
    assert any("offB" in p for p in touched)


def test_a_note_edit_does_not_touch_the_products(monkeypatch):
    """The sync is not free — it walks every linked product. Only name and
    email can change where a PO goes, so only those trigger it."""
    patches = []
    _install(monkeypatch, patch_log=patches, gets=[
        ("/suppliers?id=eq.sup1&select=*", [{"id": SUP, "business_id": BIZ,
                                             "name": "Northwind",
                                             "source": "manual",
                                             "status": "active"}]),
        ("/businesses?id=eq.biz1", [{"id": BIZ, "owner_id": "owner"}]),
    ])
    sr.update_supplier(SUP, sr.SupplierPatch(notes="slow in December"), user=_U())
    assert _offerings_patch(patches) == []


# ─── One primary, enforced on the way in ─────────────────────────────

def test_linking_a_new_primary_demotes_the_incumbent_first(monkeypatch):
    """Order matters: the partial unique index rejects the INSERT if the
    old primary is still standing, so the demotion has to come first."""
    patches, posts = [], []
    _install(monkeypatch, patch_log=patches, post_log=posts, gets=[
        ("/suppliers?id=eq.sup1&select=*", [{"id": SUP, "business_id": BIZ}]),
        ("/businesses?id=eq.biz1", [{"id": BIZ, "owner_id": "owner"}]),
        ("/offerings?id=eq.off1", [{"id": OFF}]),
        ("/offering_suppliers?offering_id=eq.off1&supplier_id=eq.sup1", []),
        ("/offering_suppliers?id=eq.", [{"id": "new1", "offering_id": OFF,
                                         "business_id": BIZ}]),
        ("/offering_suppliers?offering_id=eq.off1", [{"supplier_id": SUP}]),
        ("/suppliers?id=eq.sup1&select=name,email",
         [{"name": "Northwind", "email": "orders@northwind.com"}]),
    ])
    sr.link_product(SUP, sr.LinkBody(offering_id=OFF), user=_U())

    demotions = [i for i, (p, b) in enumerate(patches)
                 if "is_primary=is.true" in p and b.get("is_primary") is False]
    assert demotions, "the incumbent primary was never demoted"
    assert posts, "the new link was never inserted"


def test_a_non_primary_link_leaves_the_incumbent_alone(monkeypatch):
    """A second quote on the same product must not silently steal 'who I
    order this from' from the vendor already holding it."""
    patches, posts = [], []
    _install(monkeypatch, patch_log=patches, post_log=posts, gets=[
        ("/suppliers?id=eq.sup1&select=*", [{"id": SUP, "business_id": BIZ}]),
        ("/businesses?id=eq.biz1", [{"id": BIZ, "owner_id": "owner"}]),
        ("/offerings?id=eq.off1", [{"id": OFF}]),
        ("/offering_suppliers?offering_id=eq.off1&supplier_id=eq.sup1", []),
        ("/offering_suppliers?id=eq.", [{"id": "new1", "offering_id": OFF,
                                         "business_id": BIZ}]),
        ("/offering_suppliers?offering_id=eq.off1", [{"supplier_id": "other"}]),
        ("/suppliers?id=eq.", [{"name": "Incumbent", "email": "a@b.com"}]),
    ])
    sr.link_product(SUP, sr.LinkBody(offering_id=OFF, is_primary=False), user=_U())
    demotions = [b for p, b in patches
                 if "is_primary=is.true" in p and b.get("is_primary") is False]
    assert not demotions


# ─── Deleting a vendor is never silent ───────────────────────────────

def test_deleting_a_vendor_with_products_needs_meaning_it(monkeypatch):
    _install(monkeypatch, gets=[
        ("/suppliers?id=eq.sup1&select=*", [{"id": SUP, "business_id": BIZ,
                                             "name": "Northwind"}]),
        ("/businesses?id=eq.biz1", [{"id": BIZ, "owner_id": "owner"}]),
        ("/offering_suppliers?supplier_id=eq.sup1",
         [{"offering_id": "offA", "is_primary": True}]),
    ])
    with pytest.raises(HTTPException) as e:
        sr.delete_supplier(SUP, force=False, user=_U())
    assert e.value.status_code == 409
    assert e.value.detail["product_count"] == 1


def test_forced_delete_repairs_the_cache_of_what_it_orphaned(monkeypatch):
    patches, deletes = [], []
    _install(monkeypatch, patch_log=patches, delete_log=deletes, gets=[
        ("/suppliers?id=eq.sup1&select=*", [{"id": SUP, "business_id": BIZ,
                                             "name": "Northwind"}]),
        ("/businesses?id=eq.biz1", [{"id": BIZ, "owner_id": "owner"}]),
        ("/offering_suppliers?supplier_id=eq.sup1",
         [{"offering_id": "offA", "is_primary": True}]),
        ("/offering_suppliers?offering_id=eq.offA", []),
    ])
    out = sr.delete_supplier(SUP, force=True, user=_U())
    assert out["products_unlinked"] == 1
    cleared = _offerings_patch(patches)
    assert cleared and cleared[0][1] == {"supplier_name": None,
                                         "supplier_email": None}


# ─── Validation ──────────────────────────────────────────────────────

def test_a_sourced_vendor_without_a_source_url_is_refused(monkeypatch):
    """The anti-hallucination rule at the wire, not in a prompt: a vendor
    we cannot point back at a real page is a vendor we invented."""
    _install(monkeypatch, gets=[
        ("/businesses?id=eq.biz1", [{"id": BIZ, "owner_id": "owner"}]),
    ])
    with pytest.raises(HTTPException) as e:
        sr.create_supplier(sr.SupplierBody(business_id=BIZ, name="Ghost Mfg",
                                           source="sourcing"), user=_U())
    assert e.value.status_code == 400
    assert "source_url" in str(e.value.detail)


def test_a_sourced_vendor_with_a_source_url_is_accepted(monkeypatch):
    posts = []
    _install(monkeypatch, post_log=posts, gets=[
        ("/businesses?id=eq.biz1", [{"id": BIZ, "owner_id": "owner"}]),
    ])
    out = sr.create_supplier(
        sr.SupplierBody(business_id=BIZ, name="Real Mfg", source="sourcing",
                        source_url="https://realmfg.com/wholesale"), user=_U())
    assert out["ok"]
    assert posts[0][1]["found_at"]


def test_bad_email_and_empty_name_are_refused(monkeypatch):
    _install(monkeypatch, gets=[
        ("/businesses?id=eq.biz1", [{"id": BIZ, "owner_id": "owner"}]),
    ])
    with pytest.raises(HTTPException) as e1:
        sr.create_supplier(sr.SupplierBody(business_id=BIZ, name="X",
                                           email="not-an-address"), user=_U())
    assert e1.value.status_code == 400
    with pytest.raises(HTTPException) as e2:
        sr.create_supplier(sr.SupplierBody(business_id=BIZ, name="   "), user=_U())
    assert e2.value.status_code == 400


def test_a_non_owner_cannot_write(monkeypatch):
    _install(monkeypatch, gets=[
        ("/businesses?id=eq.biz1", [{"id": BIZ, "owner_id": "somebody-else"}]),
    ])

    class _Other:
        id = "intruder"

    with pytest.raises(HTTPException) as e:
        sr.create_supplier(sr.SupplierBody(business_id=BIZ, name="X"), user=_Other())
    assert e.value.status_code == 403
