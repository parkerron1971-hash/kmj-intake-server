"""THE PAGE LAYOUTS IN THE COACH AND ON THE CARD (2026-10-03, step 1c).

The Coach shows the three layouts that fit the business as cards (gallery
kind "page"), with the reasons and the Recommended mark taken from the
rubric; the owner's tap is saved as taste.layout; the blueprint card
names the chosen layout and offers the best three to switch to; a pick on
the card is saved as the owner's own answer before the redraft.
"""
import json
import time

import blueprint_card
import design_coach as dc
import site_layouts as sl

_STORY = {k: {"value": "x", "source": "asked"} for k in ("proof", "voice", "origin", "atmosphere")}


def _turn(**over):
    base = {"reply": "Which of these feels like the stairs into your study?",
            "stage": "taste", "done": False}
    base.update(over)
    return json.dumps(base)


# ─── the pick ────────────────────────────────────────────────────────

def test_a_tapped_layout_card_is_saved_by_its_bare_key():
    for said, key in (("Editorial, that's the one.", "editorial"),
                      ("Long-scroll story — that's the one.", "story"),
                      ("page-sidebar", "sidebar"),
                      ("Full-screen", "fullscreen")):
        out = dc.parse_turn(_turn(saves=[{"section": "taste", "field": "layout", "value": said}]))
        assert out["saves"] == [{"section": "taste", "field": "layout", "value": key}], said


def test_an_unknown_layout_pick_is_dropped_not_guessed():
    out = dc.parse_turn(_turn(saves=[{"section": "taste", "field": "layout", "value": "a spaceship"}]))
    assert out["saves"] == []


# ─── the cards ───────────────────────────────────────────────────────

def test_the_page_gallery_keeps_real_layouts_only():
    out = dc.parse_turn(_turn(gallery={"kind": "page",
                                       "options": ["page-editorial", "page-story", "page-nope", "editorial"]}))
    assert out["gallery"]["kind"] == "page"
    assert out["gallery"]["options"] == ["page-editorial", "page-story"]


def test_the_cards_reasons_and_recommendation_come_from_the_rubric(monkeypatch):
    ctx = {"business": {"type": "coach"},
           "site": {"site_config": {"discovery_dossier": {"story": _STORY}}}}
    rows = sl.rank(sl.signals(ctx))
    monkeypatch.setitem(dc._LAYOUT_RANK, "biz", (time.monotonic(), rows))
    gallery = {"kind": "page", "options": ["page-story", "page-editorial", "page-statement"],
               "notes": {"page-story": "the model's own pitch"}}
    dc._finish_page_gallery(gallery, "biz")
    assert gallery["recommended"] == "page-editorial"            # the rubric's best of the three
    assert gallery["notes"]["page-editorial"] == sl.reason_line(rows[0])
    assert gallery["notes"]["page-story"] != "the model's own pitch"


def test_without_a_ranking_the_cards_are_left_as_written(monkeypatch):
    monkeypatch.setattr(dc, "_LAYOUT_RANK", {})
    gallery = {"kind": "page", "options": ["page-story"]}
    dc._finish_page_gallery(gallery, "nobody")
    assert "recommended" not in gallery


def test_the_coach_is_handed_the_layouts_that_fit(monkeypatch):
    import discovery
    import offering_profiles
    import sb_clients
    import site_concept

    def fake_get(path):
        if path.startswith("/businesses"):
            return [{"name": "Vertical Test Coach", "business_type": "coach", "settings": {}}]
        return []

    monkeypatch.setattr(sb_clients, "sb_get_as_service", fake_get)
    monkeypatch.setattr(discovery, "get_dossier", lambda b: {"story": _STORY})
    monkeypatch.setattr(offering_profiles, "business_state", lambda b: {})
    monkeypatch.setattr(site_concept, "recent_layouts", lambda b, limit=6: [])
    ctx = dc._known_context("biz-1")
    assert "LAYOUTS THAT FIT THIS BUSINESS" in ctx
    block = ctx[ctx.index("LAYOUTS THAT FIT THIS BUSINESS"):]
    assert block.split("\n")[1].startswith("- page-editorial: Editorial.")
    assert "biz-1" in dc._LAYOUT_RANK


def test_the_coach_offers_page_layouts_not_hero_shapes():
    s = dc._SYSTEM
    assert 'kind "page"' in s and "page-editorial" in s and "page-minimal" in s
    assert 'kind "layouts" (the hero' not in s
    assert "exactly 3 page layouts" in s
    assert 'layout (the page layout they tapped' in s


# ─── the blueprint card ──────────────────────────────────────────────

_SPEC = ("=====\n0. THE CONCEPT\n=====\nINTENSITY: signature\n"
         "LAYOUT: editorial - the owner's story carries this site with no photos on file\n"
         "IDEA: a used book\n=====\n1. OVERVIEW\n=====\nx")


def test_the_card_names_the_layout_with_the_director_s_reason():
    ctx = {"business": {"type": "coach"},
           "site": {"site_config": {"discovery_dossier": {"story": _STORY}}}}
    card = blueprint_card.summary({"text": _SPEC, "status": "draft"}, ctx, "biz")
    assert card["layout"]["key"] == "editorial" and card["layout"]["name"] == "Editorial"
    assert card["layout"]["reason"] == "The owner's story carries this site with no photos on file."
    opts = card["layout_options"]
    assert len(opts) == 3 and [o["key"] for o in opts][0] == "editorial"
    assert sum(1 for o in opts if o["recommended"]) == 1
    assert all(o["reason"].endswith(".") for o in opts)


def test_a_blueprint_without_a_layout_line_still_offers_the_options():
    ctx = {"business": {"type": "barber shop"},
           "gallery": [{"url": f"https://x/{i}.jpg"} for i in range(8)],
           "offerings": [{}] * 6}
    card = blueprint_card.summary({"text": "0. THE CONCEPT\nINTENSITY: signature"}, ctx, "biz")
    assert card["layout"] is None
    assert card["layout_options"][0]["key"] == "showcase"


# ─── the card's pick rides the redraft ───────────────────────────────

def test_a_layout_pick_on_the_card_is_saved_as_the_owner_s_answer(monkeypatch):
    import chief_jobs
    import discovery
    saved = {}
    monkeypatch.setattr(discovery, "get_dossier", lambda b: {"taste": {"look": {"value": "hearth", "source": "asked"}}})
    monkeypatch.setattr(discovery, "save_dossier", lambda b, d: saved.update(b=b, d=d) or True)
    assert chief_jobs.save_layout_pick("biz", "Long-scroll story") == "story"
    assert saved["d"]["taste"]["layout"] == {"value": "story", "source": "asked"}
    assert saved["d"]["taste"]["look"]["value"] == "hearth"           # nothing else touched
    # the rubric then leads with the owner's pick
    ctx = {"business": {"type": "coach"}, "site": {"site_config": {"discovery_dossier": saved["d"]}}}
    assert sl.rank(sl.signals(ctx))[0]["key"] == "story"


def test_an_unknown_layout_pick_saves_nothing(monkeypatch):
    import chief_jobs
    import discovery
    monkeypatch.setattr(discovery, "save_dossier", lambda b, d: (_ for _ in ()).throw(AssertionError("saved")))
    assert chief_jobs.save_layout_pick("biz", "a spaceship") is None
    assert chief_jobs.save_layout_pick("biz", None) is None


def test_the_quick_session_from_chief_shows_the_page_layouts():
    """A session opened from the chat is always quick; it used to say
    'No ... layouts or motion in a quick session', which would have kept
    the twelve page layouts from every Chief-opened session."""
    q = dc.QUICK_SESSION
    assert "The PAGE gallery" in q and 'kind "page"' in q
    assert "layouts or motion" not in q
    assert q.index("The LOOKS gallery") < q.index("The PAGE gallery") < q.index("The CONCEPT gallery")
