"""THE REAL MATERIAL, PART TWO (2026-10-03, the hand-build plan, step 2b).

In the first live test the owner told the Coach "Next Chapter, six weeks,
$1,200; single 60-minute sessions, $150; Tuesday to Saturday, 9 to 6".
The dossier had nowhere to keep it, so the page said "there's no package
menu". And the Coach never asked for photos, though the business had none.
A hand-build gathers both: the offers go on the page as the owner said
them, and the photos get asked for.
"""
import discovery
import builder_v2
import design_coach as dc
import spec_author

_OFFERS = [{"name": "Next Chapter", "price": "$1,200", "duration": "six weeks"},
           {"name": "Single session", "price": "$150", "duration": "60 minutes"},
           {"name": "Discovery call", "price": "free", "duration": "20 minutes"}]


def _ctx(truth):
    return {"business": {"name": "Vertical Test Coach", "type": "coach"},
            "site": {"site_config": {"discovery_dossier": {"truth": truth}}}}


# ─── the dossier keeps them ──────────────────────────────────────────

def test_offers_and_hours_land_in_the_dossier():
    d = discovery.apply_practitioner_patch(discovery._empty_dossier(), {
        "truth": {"offers": _OFFERS, "hours": "Tuesday to Saturday, 9 to 6"}})
    assert [o["name"] for o in d["truth"]["offers"]] == ["Next Chapter", "Single session", "Discovery call"]
    assert d["truth"]["offers"][0] == {"source": "asked", "name": "Next Chapter",
                                       "price": "$1,200", "duration": "six weeks"}
    assert d["truth"]["hours"] == {"value": "Tuesday to Saturday, 9 to 6", "source": "asked"}


def test_a_later_answer_about_one_offer_keeps_the_others():
    d = discovery.apply_practitioner_patch(discovery._empty_dossier(), {"truth": {"offers": _OFFERS}})
    d = discovery.apply_practitioner_patch(d, {"truth": {"offers": [{"name": "single session", "price": "$175"}]}})
    by = {o["name"].lower(): o for o in d["truth"]["offers"]}
    assert len(by) == 3 and by["single session"]["price"] == "$175"
    assert by["next chapter"]["price"] == "$1,200"


def test_an_offer_without_a_name_is_dropped():
    d = discovery.apply_practitioner_patch(discovery._empty_dossier(), {
        "truth": {"offers": [{"price": "$99"}, "Workshop"]}})
    assert [o["name"] for o in d["truth"]["offers"]] == ["Workshop"]


# ─── the Coach saves and asks ────────────────────────────────────────

def test_the_coach_s_offer_and_hours_saves_reach_the_dossier(monkeypatch):
    seen = {}
    monkeypatch.setattr(discovery, "answer", lambda b, patch: seen.setdefault("patch", patch) or {})
    turn = dc.parse_turn('{"reply": "Got it.", "stage": "truth", "done": false, "saves": ['
                         '{"section": "truth", "field": "offers", "value": [{"name": "Next Chapter", "price": "$1,200"}]},'
                         '{"section": "truth", "field": "hours", "value": "Tuesday to Saturday, 9 to 6"}]}')
    assert dc.apply_saves("biz", turn["saves"]) == 2
    assert seen["patch"]["truth"]["offers"] == [{"name": "Next Chapter", "price": "$1,200"}]
    assert seen["patch"]["truth"]["hours"] == "Tuesday to Saturday, 9 to 6"


def test_the_coach_is_taught_to_save_offers_and_ask_the_truth_question():
    assert "offers (what they sell, a list of {name, price, duration, note}" in dc._SYSTEM
    assert "never a price or a length they did not say" in dc._SYSTEM
    assert "One TRUTH question" in dc.QUICK_SESSION and "when they are open" in dc.QUICK_SESSION


def test_the_server_asks_for_photos_once_when_there_are_none(monkeypatch):
    monkeypatch.setitem(dc._PHOTO_STATE, "biz", {"photos": 0, "asked": False})
    msgs = [{"role": "user", "content": "A small study above a bookstore."}]
    story_turn = {"reply": "What do people say walking out?", "stage": "story"}
    assert dc._should_ask_photos("biz", msgs, story_turn) is True
    # never on the brief, the done turn, or a turn already showing cards
    for t in ({"stage": "brief"}, {"stage": "story", "done": True},
              {"stage": "story", "gallery": {"kind": "looks"}}, {"stage": "story", "ask": "photos"}):
        assert dc._should_ask_photos("biz", msgs, dict(story_turn, **t)) is False
    # once per session
    monkeypatch.setitem(dc._PHOTO_STATE, "biz", {"photos": 0, "asked": True})
    assert dc._should_ask_photos("biz", msgs, story_turn) is False
    # a business with photos is never asked
    monkeypatch.setitem(dc._PHOTO_STATE, "biz", {"photos": 4, "asked": False})
    assert dc._should_ask_photos("biz", msgs, story_turn) is False


def test_the_photo_ask_is_remembered_for_the_session(monkeypatch):
    saved = {}
    monkeypatch.setattr(discovery, "get_dossier", lambda b: {"session": {"photos_asked": False}})
    monkeypatch.setattr(discovery, "save_dossier", lambda b, d: saved.update(d=d) or True)
    dc._persist_session("biz", [{"role": "user", "content": "hi"}],
                        {"reply": "Add a few photos?", "stage": "story", "ask": "photos"})
    assert saved["d"]["session"]["photos_asked"] is True
    monkeypatch.setattr(discovery, "get_dossier", lambda b: saved["d"])
    dc._persist_session("biz", [], {"reply": "Next.", "stage": "taste"})
    assert saved["d"]["session"]["photos_asked"] is True          # it stays asked


# ─── the builder and the Director use them ───────────────────────────

def test_the_builder_is_handed_the_offers_as_the_owner_said_them(monkeypatch):
    monkeypatch.setattr(builder_v2, "connected_systems_block", lambda b, c: "")
    data = builder_v2.assemble_real_data(_ctx({"offers": _OFFERS, "hours": {"value": "Tue to Sat, 9 to 6"}}), "biz")
    assert "WHAT THE OWNER SAID THEY OFFER" in data
    assert "- Next Chapter: $1,200, six weeks" in data
    assert "HOURS THE OWNER STATED: Tue to Sat, 9 to 6" in data
    # the price passes the truth law because it is in the data
    html = "<html><body><p>Next Chapter. Six weeks, $1,200.</p></body></html>"
    assert builder_v2.check_truth(html, data) == []


def test_a_missing_stated_offer_earns_a_repair_round():
    ctx = _ctx({"offers": _OFFERS})
    page = "<html><body><h2>Next Chapter</h2><p>Single session, $150.</p></body></html>"
    found = builder_v2.check_stated_offers(page, ctx)
    assert len(found) == 1 and "Discovery call" in found[0]
    assert builder_v2.check_stated_offers(page, _ctx({})) == []


def test_the_director_counts_stated_offers_under_the_coverage_law():
    assert "the offers the owner named in the design session count" in spec_author._SYSTEM
