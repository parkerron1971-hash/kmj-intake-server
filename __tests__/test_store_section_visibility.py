"""Post-audit gap list (2026-08-13) — the shop section must not hide
itself without saying so.

site_modules/store.py counts an item toward the shop section only when it
carries an http image AND a price >= $5, and needs at least two such
items ("a one-test-product store destroys trust"). That bar is
deliberate and is NOT changed here.

What was wrong is that it was enforced silently at render time. A
practitioner could have priced, in-stock, Stripe-connected products, a
readiness chip reporting green, and a published site with no shop on it
and no explanation anywhere. The commonest cause is simply no photos.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import offering_profiles as op  # noqa: E402


def _prod(name="Thing", price=25.0, img="https://cdn.example/a.jpg",
          category="product"):
    return {"id": name, "name": name, "category": category,
            "current_price": price, "image_url": img}


READY_STATE = {
    "booking_enabled": True, "stripe_connected": True, "site_slug": "acme",
    "booking_url": "", "store_url": "https://acme.mysolutionist.app/store",
    "product_file_ids": set(),
}


# ─── the bar itself must not drift from the renderer ─────────────────


def test_readiness_mirrors_the_renderer_thresholds():
    """readiness reports a bar enforced in another module. If someone
    tunes the renderer, this fails until readiness follows — otherwise
    the explanation quietly starts lying."""
    from site_modules import store as store_module
    assert op.STORE_MIN_REAL_PRODUCTS == store_module._MIN_REAL_PRODUCTS
    assert op.STORE_MIN_REAL_PRICE == store_module._MIN_REAL_PRICE


# ─── store_section_status ────────────────────────────────────────────


def test_two_real_products_render_the_section():
    st = op.store_section_status([_prod("A"), _prod("B")])
    assert st["will_render"] is True
    assert st["reason"] == ""


def test_photoless_products_are_named_and_explained():
    """The exact silent case: priced, in stock, no photos, no shop."""
    st = op.store_section_status([_prod("A", img=""), _prod("B", img="")])
    assert st["will_render"] is False
    assert st["qualifying"] == 0
    assert set(st["missing_photo"]) == {"A", "B"}
    assert "photo" in st["reason"]
    assert "2 more would show it" in st["reason"]


def test_one_qualifying_product_still_hides_and_says_how_many_short():
    st = op.store_section_status([_prod("A"), _prod("B", img="")])
    assert st["will_render"] is False
    assert st["qualifying"] == 1
    assert "1 more would show it" in st["reason"]


def test_cheap_products_are_named_separately():
    st = op.store_section_status([_prod("A", price=1.0), _prod("B", price=2.0)])
    assert st["will_render"] is False
    assert set(st["below_min_price"]) == {"A", "B"}


def test_no_products_says_so_plainly():
    st = op.store_section_status([])
    assert st["will_render"] is False
    assert st["reason"] == "No products yet."


def test_services_are_not_counted_as_shop_items():
    st = op.store_section_status([
        {"id": "s", "name": "Session", "category": "service",
         "current_price": 90.0, "image_url": ""}])
    assert st["reason"] == "No products yet."


def test_malformed_price_does_not_crash_the_report():
    st = op.store_section_status([_prod("A", price="not-a-number")])
    assert st["will_render"] is False


# ─── per-offering signal ─────────────────────────────────────────────


def _codes(o):
    return {i["code"] for i in op.offering_readiness(o, READY_STATE)["issues"]}


def test_a_photoless_product_is_flagged():
    assert "no_image" in _codes(_prod("A", img=""))


def test_a_product_with_a_photo_is_not_flagged():
    assert "no_image" not in _codes(_prod("A"))


def test_a_non_http_image_does_not_count():
    """The renderer requires an http URL; a bare path silently fails it."""
    assert "no_image" in _codes(_prod("A", img="/uploads/a.jpg"))


def test_bookable_offerings_are_not_asked_for_a_photo():
    session = {"id": "s1", "name": "Session", "category": "service",
               "current_price": 90.0, "duration_min": 60, "image_url": ""}
    assert "no_image" not in _codes(session)


def test_readiness_query_selects_image_url():
    """The check is only as good as the row it is handed."""
    import inspect
    assert "image_url" in inspect.getsource(op.business_readiness)
