"""THE LAYOUT LIBRARY (2026-10-03, the hand-build plan).

Twelve layouts and the rubric that ranks them for a business from what it
actually has. The scenario tests are the hand-build check: each business
gets the layout a designer would pick by hand, for the reason a designer
would give.
"""
import re

import site_layouts as sl


def _ctx(btype, photos=0, offerings=0, story=None, stats=0, action="", idea="",
         store_items=0, testimonials=0, taste=None, slots=None):
    d = {"story": story or {}, "taste": taste or {},
         "identity": {"primary_action": {"value": action}} if action else {},
         "truth": {"proven_stats": [{"value": str(i)} for i in range(stats)]}}
    cfg = {"discovery_dossier": d}
    if slots:
        cfg["slots"] = slots
    return {"business": {"type": btype},
            "gallery": [{"url": f"https://x/{i}.jpg"} for i in range(photos)],
            "offerings": [{"name": f"o{i}"} for i in range(offerings)],
            "testimonials": [{"q": "x"}] * testimonials,
            "store": {"enabled": store_items > 0, "items": [{}] * store_items},
            "concept": {"idea": idea},
            "site": {"site_config": cfg}}


_RICH_STORY = {k: {"value": "x", "source": "asked"}
               for k in ("proof", "voice", "origin", "atmosphere")}


def _top(ctx, n=1, recent=None):
    return [r["key"] for r in sl.rank(sl.signals(ctx, recent))[:n]]


# ─── the catalog ─────────────────────────────────────────────────────

def test_there_are_twelve_complete_layouts():
    assert len(sl.LAYOUTS) == 12
    for k, L in sl.LAYOUTS.items():
        for field in ("name", "line", "best_for", "needs", "skeleton", "structure", "phone", "fit"):
            assert L.get(field), (k, field)
        assert callable(L["fit"])
    assert len({L["name"] for L in sl.LAYOUTS.values()}) == 12


def test_every_layout_has_a_phone_plan_and_a_section_range():
    for k, L in sl.LAYOUTS.items():
        assert re.search(r"\d", L["skeleton"]), f"{k} skeleton names no section count"
        assert len(L["phone"]) > 20


def test_names_and_sentences_normalize_to_keys():
    assert sl.normalize("Editorial") == "editorial"
    assert sl.normalize("Long-scroll story — your story has beats") == "story"
    assert sl.normalize("full-screen") == "fullscreen"
    assert sl.normalize("BENTO: lots of facts") == "bento"
    assert sl.normalize("broken grid") == "asymmetric"
    assert sl.normalize("a spaceship") is None
    assert sl.normalize("") is None


# ─── the signals ─────────────────────────────────────────────────────

def test_photos_count_gallery_and_filled_slots_once_each():
    ctx = _ctx("coach", photos=2, slots={
        "hero": {"custom_url": "https://x/0.jpg"},          # same as a gallery photo
        "about": {"custom_url": "https://x/portrait.jpg"},
        "gone": {"custom_url": "https://x/old.jpg", "removed": True}})
    assert sl.signals(ctx)["photos"] == 3


def test_the_primary_action_reads_the_owner_s_words():
    assert sl.signals(_ctx("coach", action="book a free 20-minute discovery call"))["action"] == "call"
    assert sl.signals(_ctx("barber", action="book a chair"))["action"] == "book"
    assert sl.signals(_ctx("shop", action="shop the candles"))["action"] == "buy"


def test_calm_trades_are_recognized():
    assert sl.signals(_ctx("family law firm"))["calm_trade"] is True
    assert sl.signals(_ctx("licensed therapist"))["calm_trade"] is True
    assert sl.signals(_ctx("tattoo studio"))["calm_trade"] is False


def test_offers_the_owner_stated_count_toward_offerings():
    ctx = _ctx("coach")
    ctx["site"]["site_config"]["discovery_dossier"]["truth"]["offers"] = [
        {"name": "Next Chapter"}, {"name": "Single session"}, {"name": "Discovery call"}]
    assert sl.signals(ctx)["offerings"] == 3


# ─── the hand-build check: the layout a designer would pick ──────────

def test_a_coach_with_a_story_and_no_photos_gets_a_reading_layout():
    ctx = _ctx("coach", story=_RICH_STORY, stats=3, action="book a free discovery call",
               idea="The site is a used book from the shop downstairs, a pencil note in its margin")
    top3 = _top(ctx, 3)
    assert top3[0] == "editorial"
    assert set(top3) == {"editorial", "statement", "story"}
    for photo_layout in ("showcase", "fullscreen", "magazine", "asymmetric"):
        assert photo_layout not in top3


def test_a_barber_with_photos_leads_with_the_work():
    assert _top(_ctx("barber shop", photos=8, offerings=6, action="book a chair")) == ["showcase"]


def test_a_law_firm_stays_calm_and_never_breaks_the_grid():
    ctx = _ctx("law firm", photos=1, offerings=3, story={"origin": {"value": "x"}}, stats=2,
               action="schedule a consultation")
    top3 = _top(ctx, 3)
    assert top3[0] in ("split", "editorial")
    rows = {r["key"]: r for r in sl.rank(sl.signals(ctx))}
    assert rows["asymmetric"]["score"] < 0


def test_a_restaurant_opens_on_the_room():
    ctx = _ctx("restaurant", photos=5, offerings=4, story={"atmosphere": {"value": "x"}},
               action="reserve a table")
    assert _top(ctx) == ["fullscreen"]


def test_a_shop_with_products_gets_a_grid():
    assert _top(_ctx("candle shop", photos=4, offerings=2, action="shop the candles",
                     store_items=12)) == ["grid"]


def test_a_brand_new_business_with_nothing_on_file_stays_small():
    assert _top(_ctx("consulting")) [0] in ("statement", "minimal")


def test_a_church_with_many_ministries_reads_like_a_magazine():
    ctx = _ctx("church", photos=6, offerings=5, story=_RICH_STORY, stats=2, action="visit on Sunday")
    assert _top(ctx) == ["magazine"]


def test_no_photos_keeps_every_photo_layout_off_the_shortlist():
    for btype in ("hair salon", "restaurant", "photographer", "coach"):
        top3 = _top(_ctx(btype, offerings=3, story=_RICH_STORY), 3)
        assert not {"showcase", "fullscreen", "magazine", "asymmetric"} & set(top3), (btype, top3)


# ─── the owner, the Coach's older cards, variety ─────────────────────

def test_the_owner_s_pick_always_leads():
    ctx = _ctx("barber shop", photos=8, offerings=6, taste={"layout": {"value": "minimal"}})
    rows = sl.rank(sl.signals(ctx))
    assert rows[0]["key"] == "minimal" and rows[0]["picked"] is True
    assert sl.reason_line(rows[0]).startswith("You picked it")


def test_the_older_hero_shape_card_nudges_toward_its_layout():
    plain = sl.signals(_ctx("coach", story=_RICH_STORY))
    nudged = sl.signals(_ctx("coach", story=_RICH_STORY, taste={"hero_shape": {"value": "monument"}}))
    assert sl.score("statement", nudged)[0] == sl.score("statement", plain)[0] + 2


def test_a_layout_other_sites_just_used_loses_ground():
    ctx = _ctx("barber shop", photos=8, offerings=6)
    fresh = sl.score("showcase", sl.signals(ctx))[0]
    tired = sl.score("showcase", sl.signals(ctx, recent=["showcase", "showcase", "grid"]))[0]
    assert tired == fresh - 4


# ─── what the people and the models read ─────────────────────────────

def test_the_card_reason_is_one_plain_sentence():
    ctx = _ctx("coach", story=_RICH_STORY, action="book a call")
    line = sl.reason_line(sl.rank(sl.signals(ctx))[0])
    assert line.endswith(".") and line[0].isupper()
    assert "—" not in line and " - " not in line          # the dash law


def test_the_director_sees_the_ranking_and_all_twelve():
    block = sl.director_block(sl.signals(_ctx("coach", story=_RICH_STORY)))
    assert "THE LAYOUT" in block and "RANKED FOR THIS BUSINESS" in block
    for k in sl.LAYOUTS:
        assert f"- {k}:" in block


def test_the_director_is_told_to_use_the_owner_s_pick():
    block = sl.director_block(sl.signals(_ctx("coach", taste={"layout": {"value": "story"}})))
    assert "THE OWNER PICKED: story" in block


def test_the_builder_gets_the_chosen_layout_s_recipe():
    block = sl.builder_block("Sidebar — a long menu")
    assert "THE LAYOUT: sidebar" in block and "STRUCTURE:" in block and "PHONE:" in block
    assert sl.builder_block(None) == "" and sl.builder_block("nonsense") == ""


def test_the_concept_sheet_line_gives_key_and_reason():
    sheet = {"layout": "editorial — your story carries the site and there are no photos yet"}
    assert sl.key_from_sheet(sheet) == "editorial"
    assert sl.reason_from_sheet(sheet).startswith("your story carries the site")
    assert sl.key_from_sheet({}) is None
