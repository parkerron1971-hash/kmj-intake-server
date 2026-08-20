# __tests__/test_inventory_scan.py
#
# SCAN THE SHELF, rung one. Pins the three things that can silently
# corrupt inventory if they drift:
#
#   1. clean_barcode — a junk code stored once is a permanent key that
#      matches the wrong product forever.
#   2. parse_product — the model's reply is untrusted text; a "price"
#      of "call for pricing" must not become a number on a store page.
#   3. best_match — the duplicate guard. Matching too eagerly writes
#      stock onto the wrong row (silent); matching too shyly proposes a
#      new product (visible, cancellable). The floor must stay where a
#      genuinely different product does NOT match.

import inventory_scan as iscan


# ─── clean_barcode ───────────────────────────────────────────────────


def test_clean_barcode_accepts_real_codes():
    assert iscan.clean_barcode("857154004018") == "857154004018"     # UPC-A
    assert iscan.clean_barcode("5901234123457") == "5901234123457"   # EAN-13
    assert iscan.clean_barcode(" abc-123456 ") == "ABC-123456"       # CODE-128


def test_clean_barcode_rejects_junk():
    # A misread must be None, never a stored string that can never match.
    assert iscan.clean_barcode(None) is None
    assert iscan.clean_barcode("") is None
    assert iscan.clean_barcode("   ") is None
    assert iscan.clean_barcode("12345") is None            # too short
    assert iscan.clean_barcode("857154 004018") is None    # whitespace
    assert iscan.clean_barcode("not a barcode!") is None   # punctuation
    assert iscan.clean_barcode("1" * 49) is None           # absurdly long


# ─── parse_product ───────────────────────────────────────────────────


def test_parse_product_clean_json():
    out = iscan.parse_product(
        '{"name": "Layrite Superhold Pomade 4oz", "brand": "Layrite", '
        '"barcode": "857154004018", "sku": "LAY-SH-4", "price": 21.5, '
        '"description": "Strong hold, water soluble", "category": "product"}')
    assert out["not_a_product"] is False
    assert out["name"] == "Layrite Superhold Pomade 4oz"
    assert out["brand"] == "Layrite"
    assert out["barcode"] == "857154004018"
    assert out["sku"] == "LAY-SH-4"
    assert out["price"] == 21.5


def test_parse_product_survives_fences_and_prose():
    out = iscan.parse_product(
        'Sure! Here you go:\n```json\n{"name": "Beard Oil 2oz", '
        '"brand": null, "barcode": "not visible", "sku": null, '
        '"price": "call for pricing", "description": "beard oil", '
        '"category": "course"}\n```\nHope that helps!')
    assert out["name"] == "Beard Oil 2oz"
    assert out["brand"] is None
    assert out["barcode"] is None      # unreadable -> None, never garbage
    assert out["price"] is None        # non-numeric -> None, never 0
    # Category is FIXED. A boxed DVD must not land in 'course', where
    # store checkout treats it as a non-shippable good.
    assert out["category"] == "product"


def test_parse_product_rejects_non_products_and_junk():
    assert iscan.parse_product('{"not_a_product": true}')["not_a_product"] is True
    assert iscan.parse_product("I can't help with that")["not_a_product"] is True
    assert iscan.parse_product("")["not_a_product"] is True
    assert iscan.parse_product("{broken json")["not_a_product"] is True
    # A reply with no name is not a usable proposal.
    assert iscan.parse_product('{"name": "", "price": 4}')["not_a_product"] is True


def test_parse_product_drops_nonsense_price():
    assert iscan.parse_product('{"name": "Wax", "price": 0}')["price"] is None
    assert iscan.parse_product('{"name": "Wax", "price": -3}')["price"] is None


# ─── best_match — the duplicate guard ────────────────────────────────


_SHELF = [
    {"id": "1", "name": "Layrite Superhold Pomade 4oz", "sku": "LAY-SH-4",
     "category": "product", "inventory_qty": 12},
    {"id": "2", "name": "Beard Oil 2oz", "sku": "BO-2",
     "category": "product", "inventory_qty": 3},
    {"id": "3", "name": "Neck Duster", "sku": None,
     "category": "product", "inventory_qty": None},
]


def test_best_match_finds_the_same_product():
    hit = iscan.best_match(
        {"name": "Layrite Superhold Pomade 4oz", "brand": "Layrite"}, _SHELF)
    assert hit and hit["offering"]["id"] == "1"
    assert hit["score"] >= 0.9


def test_best_match_survives_word_order_and_brand_prefix():
    # The label says the brand; the catalog row may not, or vice versa.
    hit = iscan.best_match({"name": "Superhold Pomade", "brand": "Layrite"}, _SHELF)
    assert hit and hit["offering"]["id"] == "1"


def test_best_match_uses_a_printed_sku():
    hit = iscan.best_match({"name": "unreadable label", "sku": "bo-2"}, _SHELF)
    assert hit and hit["offering"]["id"] == "2"


def test_best_match_refuses_a_different_product():
    # THE ALARM. If this ever returns a hit, the scanner writes stock
    # onto the wrong row and nobody sees it happen.
    assert iscan.best_match({"name": "Shampoo 16oz", "brand": "Suave"}, _SHELF) is None
    assert iscan.best_match({"name": "Clipper Guard Set"}, _SHELF) is None


def test_best_match_on_an_empty_catalog_is_new():
    assert iscan.best_match({"name": "Layrite Superhold Pomade 4oz"}, []) is None


def test_name_score_is_bounded_and_handles_blanks():
    assert iscan.name_score(None, "x") == 0.0
    assert iscan.name_score("", "") == 0.0
    assert iscan.name_score("Beard Oil", "Beard Oil") == 1.0
    assert 0.0 <= iscan.name_score("a b c", "x y z") <= 1.0


# ─── shape + routes ──────────────────────────────────────────────────


def test_shape_reports_untracked_honestly():
    s = iscan._shape(_SHELF[2])
    assert s["inventory_qty"] is None and s["tracked"] is False
    s2 = iscan._shape(_SHELF[0])
    assert s2["inventory_qty"] == 12 and s2["tracked"] is True


def test_routes_exist_and_are_authed():
    from auth_supabase import require_user

    paths = {}
    for r in iscan.router.routes:
        paths.setdefault(r.path, set()).update(getattr(r, "methods", set()))
    assert "POST" in paths.get("/store/inventory/{business_id}/scan", set())
    assert "POST" in paths.get(
        "/store/inventory/{business_id}/{offering_id}/barcode", set())

    for r in iscan.router.routes:
        deps = [d.call for d in r.dependant.dependencies]
        assert require_user in deps, f"{r.path} is missing require_user"


def test_offerings_router_passes_barcode_through():
    import offerings_router as orr
    assert "barcode" in orr.OfferingCreateBody.model_fields
    assert "barcode" in orr.OfferingPatchBody.model_fields
    # ONE normalizer. Two would mean a code saved through the catalog
    # form can never be found by the scanner.
    assert orr._clean_barcode(" 857154004018 ") == "857154004018"
    assert orr._clean_barcode("nope!") is None
