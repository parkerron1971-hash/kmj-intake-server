"""THE LAYOUT LIBRARY (2026-10-03, the hand-build plan).

Seventeen layouts (twelve; bulletin and booking on 2026-10-04; launch,
poster and leader from the sites Kevin sent on 2026-10-05) and the
rubric that ranks them for a business from what it
actually has. The scenario tests are the hand-build check: each business
gets the layout a designer would pick by hand, for the reason a designer
would give.
"""
import re

import site_layouts as sl


def _ctx(btype, photos=0, offerings=0, story=None, stats=0, action="", idea="",
         store_items=0, testimonials=0, taste=None, slots=None, hours="",
         booking=False, durations=False, events=False):
    d = {"story": story or {}, "taste": taste or {},
         "identity": {"primary_action": {"value": action}} if action else {},
         "truth": {"proven_stats": [{"value": str(i)} for i in range(stats)],
                   **({"hours": {"value": hours}} if hours else {})}}
    cfg = {"discovery_dossier": d}
    if slots:
        cfg["slots"] = slots
    return {"business": {"type": btype},
            "gallery": [{"url": f"https://x/{i}.jpg"} for i in range(photos)],
            "offerings": [{"name": f"o{i}", **({"duration_min": 60} if durations else {})}
                          for i in range(offerings)],
            "booking": {"enabled": booking},
            "events_door": {"enabled": events},
            "testimonials": [{"q": "x"}] * testimonials,
            "store": {"enabled": store_items > 0, "items": [{}] * store_items},
            "concept": {"idea": idea},
            "site": {"site_config": cfg}}


_RICH_STORY = {k: {"value": "x", "source": "asked"}
               for k in ("proof", "voice", "origin", "atmosphere")}


def _top(ctx, n=1, recent=None):
    return [r["key"] for r in sl.rank(sl.signals(ctx, recent))[:n]]


# ─── the catalog ─────────────────────────────────────────────────────

def test_there_are_seventeen_complete_layouts():
    assert len(sl.LAYOUTS) == 17
    for k, L in sl.LAYOUTS.items():
        for field in ("name", "line", "best_for", "needs", "skeleton", "structure", "phone", "fit"):
            assert L.get(field), (k, field)
        assert callable(L["fit"])
    assert len({L["name"] for L in sl.LAYOUTS.values()}) == 17


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


def test_the_director_sees_the_ranking_and_every_layout():
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


# ─── the blueprint (2026-10-03, step 1b) ─────────────────────────────

def test_the_concept_sheet_reads_the_layout_line():
    import site_concept as sc
    sheet = sc.parse_sheet("=====\n0. THE CONCEPT\n=====\nINTENSITY: signature\n"
                           "LAYOUT: editorial — your story carries the site\n"
                           "IDEA: a used book\n=====\n1. OVERVIEW\n")
    assert sl.key_from_sheet(sheet) == "editorial"
    assert sheet["intensity"] == "signature"


def test_the_concept_law_puts_the_layout_on_every_sheet():
    import site_concept as sc
    assert "LAYOUT: one of the twelve layout keys" in sc.DIRECTOR_LAW
    assert "its LAYOUT line" in sc.DIRECTOR_LAW          # even a plain sheet
    assert "THE LAYOUT owns the page's structure" in sc.DIRECTOR_LAW


def test_the_director_law_replaces_the_one_skeleton():
    import spec_author
    s = spec_author._SYSTEM
    assert "THE LAYOUT LAW" in s
    assert "full-viewport hero (display headline" not in s   # the old fixed path is gone
    assert "unless the business genuinely has little on file" in s
    assert "in the layout's form" in s


def test_the_layout_block_rides_the_brief_before_the_section_plan():
    import spec_author
    user = spec_author.build_user_prompt("DOSSIER", [], concept="== THE CONCEPT ==",
                                         layout="== THE LAYOUT (decide) ==")
    assert user.index("THE CONCEPT") < user.index("== THE LAYOUT") < user.index("CURRENT SECTION PLAN")
    assert "== THE LAYOUT" not in spec_author.build_user_prompt("DOSSIER", [])


def test_the_director_is_handed_the_ranked_layouts(monkeypatch):
    import site_concept as sc
    import spec_author
    seen = {}
    monkeypatch.setattr(spec_author, "_call_llm",
                        lambda system, user, bid, image_urls=None, mark_urls=None:
                        seen.setdefault("user", user) and "0. THE CONCEPT\nINTENSITY: signature")
    monkeypatch.setattr(sc, "recent_concepts", lambda bid, limit=12: [])
    monkeypatch.setattr(sc, "recent_layouts", lambda bid, limit=6: ["editorial"])
    ctx = {"business": {"name": "Vertical Test Coach", "type": "coach"},
           "site": {"site_config": {"discovery_dossier": {
               "story": {k: {"value": "x", "source": "asked"}
                         for k in ("proof", "voice", "origin", "atmosphere")}}}}}
    spec_author.author_spec("biz-1", ctx, None, [])
    assert "== THE LAYOUT" in seen["user"] and "RANKED FOR THIS BUSINESS" in seen["user"]
    assert "ALL 17 LAYOUTS" in seen["user"]


def test_recent_layouts_come_from_other_businesses_blueprints(monkeypatch):
    import site_concept as sc
    import sb_clients
    rows = [{"business_id": "me", "spec": "INTENSITY: plain\nLAYOUT: grid — mine"},
            {"business_id": "b2", "spec": "INTENSITY: signature\nLAYOUT: showcase — photos\nIDEA: x"},
            {"business_id": "b3", "spec": "INTENSITY: plain\nLAYOUT: Long-scroll story — beats"},
            {"business_id": "b4", "spec": "INTENSITY: plain"}]
    monkeypatch.setattr(sc, "_recent_cache", {"at": None, "rows": []})
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: rows)
    assert sc.recent_layouts("me") == ["showcase", "story"]


# ─── the builder (2026-10-03, step 1b) ───────────────────────────────

_SPEC_SIDEBAR = ("=====\n0. THE CONCEPT\n=====\nINTENSITY: plain\n"
                 "LAYOUT: sidebar — a long menu is easier to move through from the side\n"
                 "STAYS PLAIN: everything\n=====\n1. OVERVIEW\n=====\nA menu.")


def test_the_builder_is_taught_to_build_the_layout():
    import builder_v2
    assert "18. THE LAYOUT" in builder_v2._SYSTEM


def test_the_layout_recipe_rides_the_build_message_only_when_chosen():
    import builder_v2
    user = builder_v2.build_user_prompt(_SPEC_SIDEBAR, "REAL DATA")
    assert "== THE LAYOUT: sidebar" in user and "STRUCTURE:" in user
    assert user.index("== THE LAYOUT") < user.index("== THE REAL DATA")
    plain = builder_v2.build_user_prompt("0. THE CONCEPT\nINTENSITY: plain", "REAL DATA")
    assert "== THE LAYOUT" not in plain
    # the surgical repair prompt is unchanged
    repair = builder_v2.build_user_prompt(_SPEC_SIDEBAR, "REAL DATA", violations=["x"], prior_doc="<html>")
    assert "== THE LAYOUT" not in repair


def test_a_layout_miss_reaches_the_eyes_as_a_measured_finding():
    import builder_v2
    miss = builder_v2.layout_findings(_SPEC_SIDEBAR, {"1440": {"layout_measured": True, "sidebar": False}})
    assert miss and "THE LAYOUT is Sidebar" in miss[0]
    assert builder_v2.layout_findings(_SPEC_SIDEBAR, {"1440": {"layout_measured": True, "sidebar": True}}) == []
    assert builder_v2.layout_findings("no sheet", {"1440": {"layout_measured": True}}) == []


def test_the_loop_s_render_tool_reports_layout_drift(monkeypatch):
    import builder_loop
    import builder_v2
    box = builder_loop.ToolBox({}, "biz", "REAL DATA", "https://x/submit",
                               screenshots=lambda html: [("1440px top", b"jpeg")])
    box.spec_text = _SPEC_SIDEBAR
    monkeypatch.setattr(builder_v2, "walk_measurements",
                        lambda html: {"1440": {"layout_measured": True, "sidebar": False}})
    found = box.measured_findings("<html></html>")
    assert any("THE LAYOUT is Sidebar" in f for f in found)


def test_the_loop_stays_quiet_when_nothing_was_measured(monkeypatch):
    import builder_loop
    import builder_v2
    box = builder_loop.ToolBox({}, "biz", "REAL DATA", "https://x/submit",
                               screenshots=lambda html: [("1440px top", b"jpeg")])
    box.spec_text = _SPEC_SIDEBAR
    monkeypatch.setattr(builder_v2, "walk_measurements", lambda html: None)
    assert box.measured_findings("<html></html>") == []


# ─── the two I built by hand (2026-10-04, the library grows) ──────────

def test_the_owner_s_stated_times_are_counted_once_each():
    sig = sl.signals(_ctx("church", hours="Sundays 9am and 11 a.m., Wednesdays 7pm; Sunday 9 AM"))
    assert sig["times"] == 3
    assert sig["gathering_trade"] and not sig["appointment_trade"]
    assert sl.signals(_ctx("church", hours="Tuesdays 18:30"))["times"] == 1


def test_a_church_that_said_its_times_leads_with_them():
    ctx = _ctx("church", photos=2, offerings=4, story=_RICH_STORY, stats=2,
               action="visit on Sunday", hours="Sundays 9am and 11am, Wednesdays 7pm", events=True)
    rows = sl.rank(sl.signals(ctx))
    assert rows[0]["key"] == "bulletin"
    assert "people come at set times, so the times come first" in rows[0]["why"]


def test_a_gym_leads_with_its_class_times():
    assert _top(_ctx("yoga studio", photos=3, offerings=5, hours="Mon-Fri 6am, 12pm, 6pm")) == ["bulletin"]


def test_a_business_nobody_visits_at_set_times_never_gets_a_bulletin():
    for btype in ("law firm", "coach", "candle shop", "hair salon"):
        rows = {r["key"]: r for r in sl.rank(sl.signals(_ctx(btype, offerings=4, hours="9am to 5pm")))}
        assert rows["bulletin"]["score"] < 0, btype


def test_a_salon_with_live_booking_gets_the_booking_desk():
    ctx = _ctx("hair salon", photos=3, offerings=5, action="book a chair", booking=True, durations=True)
    rows = sl.rank(sl.signals(ctx))
    assert rows[0]["key"] == "booking"
    assert "your booking page is live, so every service books in one tap" in rows[0]["why"]


def test_the_booking_desk_waits_for_booking_and_never_buries_great_work():
    # a barber with eight strong photos still leads with the work
    assert _top(_ctx("barber shop", photos=8, offerings=6, action="book a chair",
                     booking=True, durations=True)) == ["showcase"]
    # nobody books online: the booking desk stays off the list
    rows = {r["key"]: r for r in sl.rank(sl.signals(_ctx("consulting", offerings=3)))}
    assert rows["booking"]["score"] < 0
    assert "visitors do not book with you online" in rows["booking"]["against"]
    # they book, but booking is not on yet: it says so, and Chief can fix it
    off = {r["key"]: r for r in sl.rank(sl.signals(_ctx("nail salon", offerings=4, action="book")))}
    assert "booking is not switched on yet (Chief can set it up)" in off["booking"]["against"]


def test_the_new_layouts_normalize_from_the_director_s_words():
    assert sl.normalize("Booking desk: every service books in one tap") == "booking"
    assert sl.normalize("BULLETIN — the times come first") == "bulletin"
    assert sl.normalize("times first") == "bulletin"


def test_the_render_check_knows_the_new_shapes():
    m = lambda **kw: {"1440": {"layout_measured": True, **kw}}
    assert "weekly times are not near the top" in sl.render_findings("bulletin", m(times_top=0))[0]
    assert sl.render_findings("bulletin", m(times_top=3)) == []
    assert "only 1 links lead to booking" in sl.render_findings("booking", m(book_links=1))[0]
    assert sl.render_findings("booking", m(book_links=5)) == []
    assert "times_top" in sl.RENDER_JS and "book_links" in sl.RENDER_JS


def test_the_builder_reads_the_new_recipes():
    assert "times-strip object" in sl.builder_block("bulletin")
    block = sl.builder_block("booking")
    assert "hours-card object" in block and "dock object" in block


# ─── from the sites Kevin sent (2026-10-05) ───────────────────────────

def test_a_software_business_opens_on_the_launch_stage():
    ctx = _ctx("software", photos=3, offerings=3, story=_RICH_STORY, action="start a free trial")
    rows = sl.rank(sl.signals(ctx))
    assert rows[0]["key"] == "launch"
    assert "your business has a future feel, and this layout is built for it" in rows[0]["why"]


def test_a_future_feel_in_the_owner_s_taste_reaches_the_launch_layout():
    """Kevin: 'This layout is what I want to view when my business have
    future feel to it' - the feel, not only the trade."""
    plain = sl.signals(_ctx("consulting", photos=2, offerings=3))
    future = sl.signals(_ctx("consulting", photos=2, offerings=3,
                             taste={"feel_words": {"value": "futuristic, sleek, dark"}}))
    assert not plain["future"] and future["future"]
    assert sl.score("launch", future)[0] >= sl.score("launch", plain)[0] + 8


def test_a_church_with_a_loud_mission_and_real_photos_gets_the_poster():
    ctx = _ctx("church", photos=6, offerings=3, idea="Until all have heard: the mission as a street poster",
               action="plan your visit")
    rows = sl.rank(sl.signals(ctx))
    assert rows[0]["key"] == "poster"
    assert "a loud message and real photos to set into it" in rows[0]["why"]


def test_the_poster_needs_photos_and_never_shouts_at_calm_work():
    rows = {r["key"]: r for r in sl.rank(sl.signals(_ctx("church", photos=1, idea="Until all have heard")))}
    assert "it needs four or more real photos to set into the words" in rows["poster"]["against"]
    law = {r["key"]: r for r in sl.rank(sl.signals(_ctx("law firm", photos=6, idea="a bold promise")))}
    assert law["poster"]["score"] < 0


def test_a_personal_ministry_puts_the_person_out_front():
    ctx = _ctx("ministry", photos=3, offerings=2, story=_RICH_STORY, action="book Bishop for your event")
    rows = sl.rank(sl.signals(ctx))
    assert rows[0]["key"] == "leader"
    assert "you are the brand, so your name and face lead" in rows[0]["why"]


def test_a_church_is_bigger_than_one_person():
    rows = {r["key"]: r for r in sl.rank(sl.signals(_ctx("church", photos=4, story=_RICH_STORY)))}
    assert rows["leader"]["score"] < 0
    nobody = {r["key"]: r for r in sl.rank(sl.signals(_ctx("speaker", offerings=2)))}
    assert "it needs a strong portrait" in nobody["leader"]["against"]


def test_the_render_check_knows_the_three_new_shapes():
    m = lambda **kw: {"1440": {"layout_measured": True, **kw}}
    assert "light ground" in sl.render_findings("launch", m(ground_l=0.9, objects=["beam"]))[0]
    assert "nothing is lit" in sl.render_findings("launch", m(ground_l=0.1, objects=["faq"]))[0]
    assert sl.render_findings("launch", m(ground_l=0.1, objects=["beam", "device"])) == []
    assert "not a poster" in sl.render_findings("poster", m(h1_px=140, h1_imgs=0))[0]
    assert sl.render_findings("poster", m(h1_px=140, h1_imgs=2)) == []
    assert "does not lead the page" in sl.render_findings("leader", m(objects=["ticket"]))[0]
    assert sl.render_findings("leader", m(objects=["billboard"])) == []
    for key in ("ground_l", "h1_imgs", "objects"):
        assert key in sl.RENDER_JS


def test_the_builder_reads_the_three_new_recipes():
    assert "beam object" in sl.builder_block("launch") and "device object" in sl.builder_block("launch")
    assert "photo-words object" in sl.builder_block("poster") and "sign-off object" in sl.builder_block("poster")
    assert "billboard object" in sl.builder_block("leader")
    import site_objects
    for key in ("beam", "device", "photo-words", "sign-off", "billboard", "book-cover",
                "leader-spotlight", "word-rail", "two-doors", "flow-lines", "plan-cards"):
        assert key in site_objects.OBJECTS, f"a recipe names {key}, which must have a renderer"
