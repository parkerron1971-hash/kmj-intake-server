# __tests__/test_product_lookup.py
#
# The public barcode databases + the replacement rubric.
#
# Two of these are REGRESSIONS for bugs found while building, and both
# are the same species: trusting the shape of somebody else's data.
#
#   • `brands` arrives as a list from some records. str() on a list is
#     "['Coca-Cola', 'x']", and splitting THAT on a comma writes
#     "['Coca-Cola'" — a bracket and a quote — into a practitioner's
#     catalog.
#   • The brand was appended only when it was not already `in` the name.
#     A plain substring test drops brand "A" because "a" is inside
#     "Cola", so a real brand silently vanished from the saved product.
#
# The replacement rubric gets the most attention here, because it is the
# one thing in this arc that ARCHIVES something. A false positive
# retires a product the practitioner still sells.

import asyncio

import inventory_scan as iscan
import product_lookup as pl


SRC = {"key": "test", "label": "Open Food Facts"}


def _norm(**product):
    return pl.normalize({"product": product}, SRC, "5449000000996")


# ─── normalize: other people's data ──────────────────────────────────


def test_a_clean_record_becomes_a_catalog_line():
    out = _norm(product_name="coca-cola", brands="Coca-Cola",
                quantity="330 ml", image_front_url="https://x/y.jpg")
    assert out["name"] == "Coca-Cola 330 ml"
    assert out["brand"] == "Coca-Cola"
    assert out["size"] == "330 ml"
    assert out["source"] == "Open Food Facts"
    assert out["barcode"] == "5449000000996"


def test_a_list_valued_brand_does_not_become_punctuation():
    # REGRESSION. Produced "['Coca-Cola'" as the brand.
    for brands in (["Coca-Cola", "x"], ("Coca-Cola",)):
        out = _norm(product_name="cola", brands=brands)
        assert out["brand"] == "Coca-Cola"
        assert "[" not in out["name"] and "'" not in out["name"]


def test_a_short_brand_is_not_swallowed_by_the_name():
    # REGRESSION. brand "A" is a substring of "Cola", so the old
    # `in` test dropped it and saved the product without its brand.
    assert _norm(product_name="cola", brands="A")["name"].startswith("A ")
    assert _norm(product_name="soap", brands="So")["name"] == "So Soap"


def test_a_brand_already_in_the_name_is_not_repeated():
    out = _norm(product_name="Coca-Cola Classic", brands="Coca-Cola")
    assert out["name"] == "Coca-Cola Classic"


def test_a_size_already_in_the_name_is_not_repeated():
    out = _norm(product_name="shampoo 16 oz", brands="Suave", quantity="16 oz")
    assert out["name"].lower().count("16 oz") == 1


def test_case_is_tidied_but_real_capitalisation_survives():
    assert _norm(product_name="BIG SHAMPOO")["name"] == "Big Shampoo"
    assert _norm(product_name="coca-cola")["name"] == "Coca-Cola"
    # Mixed case is somebody's actual brand styling — leave it alone.
    assert _norm(product_name="iPhone Case", brands="Apple")["name"] == "Apple iPhone Case"


def test_a_record_with_no_name_is_not_worth_showing():
    # A row with a barcode and nothing else costs the practitioner a
    # form they have to correct. Better to say we don't know.
    assert _norm(product_name="", brands="X") is None
    assert pl.normalize({"status": 0}, SRC, "1") is None
    assert pl.normalize({"product": "not a dict"}, SRC, "1") is None
    assert pl.normalize("garbage", SRC, "1") is None


def test_an_insecure_image_is_dropped():
    # These URLs end up on a practitioner's storefront.
    assert _norm(product_name="x", image_front_url="http://insecure/y.jpg")["image_url"] is None
    assert _norm(product_name="x", image_front_url="https://ok/y.jpg")["image_url"] == "https://ok/y.jpg"


def test_odd_field_types_never_raise():
    for weird in ({"x": 1}, 123, [], None, True):
        out = _norm(product_name="cola", brands=weird)
        assert out is not None and "[" not in (out["brand"] or "")


# ─── lookup: cache + concurrency ─────────────────────────────────────


def _reset_cache():
    pl._CACHE.clear()
    pl._CACHE_AT.clear()


def test_no_code_never_touches_the_network(monkeypatch):
    _reset_cache()
    monkeypatch.setattr(pl, "_ask", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not call out")))
    assert asyncio.run(pl.lookup("")) is None


def test_the_first_database_with_an_answer_wins(monkeypatch):
    _reset_cache()
    async def fake(client, source, code):
        return {"name": "Found", "source": source["label"]} \
            if source["key"] == "openbeautyfacts" else None
    monkeypatch.setattr(pl, "_ask", fake)
    out = asyncio.run(pl.lookup("123456789"))
    assert out and out["source"] == "Open Beauty Facts"


def test_a_miss_is_cached_so_the_next_scan_is_free(monkeypatch):
    # The miss is the COMMON case. Caching only hits would leave the
    # expensive path uncached and hammer a free shared service.
    _reset_cache()
    calls = []
    async def fake(client, source, code):
        calls.append(code)
        return None
    monkeypatch.setattr(pl, "_ask", fake)
    assert asyncio.run(pl.lookup("999")) is None
    n = len(calls)
    assert asyncio.run(pl.lookup("999")) is None
    assert len(calls) == n, "second lookup should have been served from cache"


def test_a_hit_is_cached_too(monkeypatch):
    _reset_cache()
    calls = []
    async def fake(client, source, code):
        calls.append(code)
        return {"name": "Thing", "source": "S"} if source["key"] == "openfoodfacts" else None
    monkeypatch.setattr(pl, "_ask", fake)
    assert asyncio.run(pl.lookup("111"))["name"] == "Thing"
    n = len(calls)
    assert asyncio.run(pl.lookup("111"))["name"] == "Thing"
    assert len(calls) == n


def test_one_database_exploding_does_not_lose_another_ones_answer(monkeypatch):
    _reset_cache()
    async def fake(client, source, code):
        if source["key"] == "openfoodfacts":
            raise RuntimeError("down")
        return {"name": "Found", "source": source["label"]} \
            if source["key"] == "openproductsfacts" else None
    monkeypatch.setattr(pl, "_ask", fake)
    out = asyncio.run(pl.lookup("222"))
    assert out and out["name"] == "Found"


def test_the_cache_is_bounded(monkeypatch):
    _reset_cache()
    for i in range(pl._CACHE_MAX + 50):
        pl._cache_put(str(i), None)
    assert len(pl._CACHE_AT) <= pl._CACHE_MAX


# ─── merge_known: database vs label ──────────────────────────────────


def test_the_database_wins_identity_and_the_label_wins_the_rest():
    label = {"not_a_product": False, "name": "POMAOE 4oz", "brand": None,
             "barcode": None, "sku": "LAY-4", "price": 21.5,
             "description": "", "category": "product"}
    known = {"name": "Layrite Superhold Pomade 4oz", "brand": "Layrite",
             "barcode": "857154004018", "image_url": "https://x/y.jpg",
             "description": "Hair", "source": "Open Beauty Facts"}
    out = iscan.merge_known(label, known)
    # A curated catalog entry beats a guess from a photo of a curved bottle.
    assert out["name"] == "Layrite Superhold Pomade 4oz"
    assert out["brand"] == "Layrite"
    assert out["image_url"] == "https://x/y.jpg"
    assert out["found_in"] == "Open Beauty Facts"
    # ...but only the database knows nothing about the printed price.
    assert out["price"] == 21.5
    assert out["sku"] == "LAY-4"


def test_merge_survives_either_side_missing():
    label = {"name": "Read off the label", "price": 3}
    assert iscan.merge_known(label, None) == label
    assert iscan.merge_known(None, None) is None
    only_db = iscan.merge_known(None, {"name": "From the database"})
    assert only_db["name"] == "From the database"
    assert only_db["not_a_product"] is False
    assert only_db["price"] is None and only_db["sku"] is None


def test_merge_does_not_mutate_the_label_read():
    label = {"name": "x", "price": 1}
    iscan.merge_known(label, {"name": "y", "brand": "b"})
    assert label == {"name": "x", "price": 1}


# ─── the replacement rubric ──────────────────────────────────────────

_SHELF = [
    {"id": "1", "name": "Layrite Superhold Pomade 4oz", "inventory_qty": 0},
    {"id": "2", "name": "Coconut Oil 8oz", "inventory_qty": 5},
    {"id": "3", "name": "Neck Duster", "inventory_qty": 2},
    {"id": "4", "name": "Suave Shampoo 16oz", "inventory_qty": 3},
    {"id": "5", "name": "Suave Conditioner 16oz", "inventory_qty": 4},
]


def test_brand_and_size_are_not_what_a_product_is():
    assert iscan.role_tokens("Layrite Superhold Pomade 4oz", "Layrite") == \
        ["superhold", "pomade"]
    # "4 oz" tokenizes to "4" and "oz"; the bare unit must go too, or
    # every 4 oz item shares a word with every other one.
    assert "oz" not in iscan.role_tokens("Firme Hold Pomade 4 oz", "Suavecito")


def test_a_switched_brand_finds_the_empty_slot_it_replaces():
    # The case this exists for: the shop changed pomade.
    out = iscan.replacement_candidates(
        {"name": "Firme Hold Pomade 4 oz", "brand": "Suavecito"}, _SHELF)
    assert len(out) == 1
    assert out[0]["offering"]["id"] == "1"
    assert out[0]["because"] == "pomade"        # it can say WHY
    assert out[0]["empty"] is True


def test_a_short_generic_word_is_not_a_role():
    # THE ALARM. Beard oil does not replace coconut oil, and this is the
    # one place in the arc that ARCHIVES something — a false positive
    # retires a product the practitioner still sells.
    assert iscan.replacement_candidates(
        {"name": "Beard Oil 2oz", "brand": "Honest Amish"}, _SHELF) == []


def test_something_unrelated_matches_nothing():
    assert iscan.replacement_candidates(
        {"name": "Clipper Guard Set", "brand": None}, _SHELF) == []


def test_a_product_never_offers_to_replace_itself():
    # Scanning what you already stock is a MATCH, not a replacement.
    # Getting this wrong archives the row that was just scanned.
    assert iscan.replacement_candidates(
        {"name": "Shampoo 16 oz", "brand": "Suave"}, _SHELF) == []
    assert iscan.replacement_candidates(
        {"name": "Superhold Pomade 4oz", "brand": "Layrite"}, _SHELF) == []


def test_a_shared_brand_alone_is_not_a_replacement():
    # THE THIRD ALARM, and the one that nearly shipped broken. When no
    # brand field comes back at all — the databases missed and the
    # label gave none — the brand is still sitting at the front of the
    # name with nothing to strip it. A body wash then looked like a
    # replacement for BOTH the shampoo and the conditioner, purely
    # because all three say "Suave".
    #
    # The rule: one shared word that LEADS both names is a maker, not a
    # job. (The earlier version of this test asserted on a case that
    # was already excluded for an unrelated reason, so it passed with
    # the guard removed — it was checking nothing.)
    out = iscan.replacement_candidates(
        {"name": "Suave Body Wash 12oz", "brand": None}, _SHELF)
    assert out == [], [c["offering"]["name"] for c in out]


def test_two_shared_words_survive_the_brand_guard():
    # The escape hatch: agreeing on more than one meaningful word is a
    # real signal whatever the first one happens to be.
    out = iscan.replacement_candidates(
        {"name": "Suave Kids Shampoo 12oz", "brand": None},
        [{"id": "9", "name": "Suave Kids Conditioner 16oz", "inventory_qty": 0}])
    assert len(out) == 1
    assert out[0]["shared"] == ["suave", "kids"]


def test_the_scanned_brand_is_stripped_from_the_shelf_name_too():
    out = iscan.replacement_candidates(
        {"name": "Dry Conditioner 16oz", "brand": "Suave"}, _SHELF)
    assert all(c["offering"]["id"] != "4" for c in out)


def test_an_empty_shelf_slot_ranks_above_a_full_one():
    shelf = [
        {"id": "full", "name": "Brand A Pomade", "inventory_qty": 9},
        {"id": "gone", "name": "Brand B Pomade", "inventory_qty": 0},
    ]
    out = iscan.replacement_candidates({"name": "Pomade Strong", "brand": "C"}, shelf)
    assert [c["offering"]["id"] for c in out][0] == "gone"


def test_candidates_are_capped():
    shelf = [{"id": str(i), "name": f"Brand{i} Pomade", "inventory_qty": 0}
             for i in range(10)]
    assert len(iscan.replacement_candidates({"name": "Pomade", "brand": "New"}, shelf)) <= 3


def test_a_nameless_scan_suggests_nothing():
    assert iscan.replacement_candidates({}, _SHELF) == []
    assert iscan.replacement_candidates({"name": "", "brand": ""}, _SHELF) == []


# ─── routes ──────────────────────────────────────────────────────────


def test_replacement_route_exists_and_is_authed():
    from auth_supabase import require_user
    paths = {}
    for r in iscan.router.routes:
        paths.setdefault(r.path, set()).update(getattr(r, "methods", set()))
    assert "POST" in paths.get(
        "/store/inventory/{business_id}/{offering_id}/replaces", set())
    for r in iscan.router.routes:
        deps = [d.call for d in r.dependant.dependencies]
        assert require_user in deps, f"{r.path} is missing require_user"


def test_a_product_cannot_replace_itself_at_the_wire():
    from fastapi import HTTPException
    try:
        iscan.predecessor_guard("same-id", "same-id")
    except HTTPException as e:
        assert e.status_code == 400
        return
    raise AssertionError("replacing itself must be refused")


def test_replacement_carries_shelf_logic_and_never_price():
    # Price must NOT inherit: a different product costs a different
    # amount, and an inherited price is how a wrong one reaches a
    # storefront. Asserted on the source because the write is remote.
    import inspect
    src = inspect.getsource(iscan.mark_replacement)
    assert '("reorder_at", "reorder_qty", "supplier_name", "supplier_email")' in src
    assert "current_price" not in src
    assert "reorder_pending_at" not in src.split('"""')[2]
