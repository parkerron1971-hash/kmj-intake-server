"""THE COACH READS THE ASK (2026-11-09, talking to Chief from the front end).

A test shop told Chief "nothing fancy, I just want people to find me and book".
Those words reached the blueprint at the very end and never the Coach, which then
asked again for services on file, never asked where the shop was, and said the
designer could pull photos off Instagram, which nothing can do.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest import mock

import build_readiness
import chief_site_design
import design_coach as dc
import discovery
import offering_profiles
import sb_clients
import site_composer
import site_layouts

FIND_AND_BOOK = "nothing fancy i just want people to be able to find me and book"


def _fresh(words=FIND_AND_BOOK, days=0):
    at = datetime.now(timezone.utc) - timedelta(days=days)
    return {"the_ask": {"words": words, "at": at.isoformat()}}


def _known(biz_type="barbershop", settings=None, offerings=(), dossier=None):
    biz = {"name": "Test Shop", "business_type": biz_type, "settings": settings or {}}

    def fake_get(path, *a, **k):
        if path.startswith("/businesses"):
            return [biz]
        if path.startswith("/offerings"):
            return list(offerings)
        return []

    with mock.patch.object(sb_clients, "sb_get_as_service", side_effect=fake_get), \
         mock.patch.object(offering_profiles, "business_state", return_value={}), \
         mock.patch.object(discovery, "get_dossier", return_value=dossier):
        return dc._known_context("b1")


# ── their words reach the Coach ──────────────────────────────────────

def test_what_they_asked_chief_is_at_the_top_of_what_the_coach_knows():
    known = _known(dossier=_fresh())
    assert FIND_AND_BOOK in known
    assert known.index("WHAT THEY ASKED CHIEF FOR") < known.index("PHOTOS ON FILE")


def test_a_month_old_ask_is_history():
    assert discovery.current_ask(_fresh(days=31)) == ""
    assert discovery.current_ask(_fresh(days=29)) == FIND_AND_BOOK
    assert discovery.current_ask({"the_ask": {"words": "x", "at": "whenever"}}) == ""
    assert discovery.current_ask(None) == ""


def test_opening_from_the_chat_saves_their_words_and_a_new_session_clears_them():
    store = {}

    def save(_id, d):
        store["d"] = d
        return True

    with mock.patch.object(discovery, "get_dossier", side_effect=lambda _id: store.get("d")), \
         mock.patch.object(discovery, "save_dossier", side_effect=save), \
         mock.patch.object(chief_site_design, "_hand_built_block", return_value=""):
        out = asyncio.run(chief_site_design.handle_start_design_session(
            None, {"id": "b1"}, {"brief_notes": FIND_AND_BOOK}))
        assert out["frontend_event"]["detail"]["brief_notes"] == FIND_AND_BOOK
        assert discovery.current_ask(store["d"]) == FIND_AND_BOOK
        asyncio.run(chief_site_design.handle_start_design_session(None, {"id": "b1"}, {}))
    assert discovery.current_ask(store["d"]) == ""


def test_a_save_that_fails_never_costs_them_the_session():
    with mock.patch.object(discovery, "save_ask", side_effect=RuntimeError("down")), \
         mock.patch.object(chief_site_design, "_hand_built_block", return_value=""):
        out = asyncio.run(chief_site_design.handle_start_design_session(
            None, {"id": "b1"}, {"brief_notes": FIND_AND_BOOK}))
    assert out["type"] == "start_design_session" and out["result"]


def test_the_ask_outlives_the_transcript_and_the_director_reads_it():
    dossier = {**_fresh(), "identity": {"one_liner": {"value": "fades"}}}
    with mock.patch.object(discovery, "get_dossier", return_value=dossier), \
         mock.patch.object(discovery, "save_dossier") as save:
        dc._persist_session("b1", [], {"reply": "hi"})
    assert discovery.current_ask(save.call_args[0][1]) == FIND_AND_BOOK
    digest = discovery.dossier_digest(dossier)
    assert digest.index("owners_ask") < digest.index("identity")


def test_an_old_ask_does_not_reach_the_director():
    assert "owners_ask" not in discovery.dossier_digest(
        {**_fresh(days=40), "identity": {"one_liner": {"value": "fades"}}})


# ── what is on file is not asked again ───────────────────────────────

def test_services_on_file_are_listed_so_they_are_not_asked_again():
    known = _known(offerings=[
        {"name": "Hair Cut", "current_price": 55, "duration_min": 45},
        {"name": "Haircut", "current_price": None, "duration_min": 30},
    ])
    assert "Hair Cut ($55, 45 min); Haircut (no price, 30 min)" in known
    assert "what people buy" not in known


def test_a_session_with_no_prices_asks_what_people_buy():
    assert "what people buy from them" in _known()
    assert "what people buy from them" in _known(offerings=[{"name": "Haircut"}])


def test_what_they_told_the_coach_counts_as_on_file():
    known = _known(dossier={"truth": {
        "offers": [{"name": "Fades", "price": "$35"}],
        "address": {"value": "12 Main St"},
        "hours": {"value": "tues thru sat 10 to 7"}}})
    assert "Fades ($35)" in known
    assert "12 Main St" in known and "tues thru sat 10 to 7" in known
    assert "STILL MISSING" not in known


# ── where they are ───────────────────────────────────────────────────

def test_a_barbershop_with_no_address_or_hours_is_told_those_are_missing():
    known = _known(offerings=[{"name": "Fade", "current_price": 35}])
    missing = known.split("STILL MISSING FOR THIS SITE")[1].split("\n")[0]
    assert "where they are" in missing and "days and times" in missing


def test_an_online_coach_is_not_asked_for_an_address():
    assert "where they are" not in _known(
        biz_type="business coach", offerings=[{"name": "Call", "current_price": 90}])


def test_an_online_trade_that_says_find_me_is_asked():
    assert "where they are" in _known(
        biz_type="business coach", offerings=[{"name": "Call", "current_price": 90}],
        dossier=_fresh("I want clients to be able to find us"))


def test_an_address_on_file_is_not_missing():
    known = _known(settings={"address": "9 Elm St"},
                   offerings=[{"name": "Fade", "current_price": 35}])
    assert "- Address: 9 Elm St" in known and "where they are" not in known


def test_the_door_rule():
    assert site_layouts.has_a_door("Barbershop")
    assert site_layouts.has_a_door("church")
    assert site_layouts.has_a_door("restaurant")
    assert not site_layouts.has_a_door("therapist")
    assert not site_layouts.has_a_door("software")
    assert not site_layouts.has_a_door("online store")
    assert not site_layouts.has_a_door("e-commerce shop")
    assert site_layouts.has_a_door("online store", "so people can find us")
    assert site_layouts.has_a_door("therapist", "people can't find me")
    assert not site_layouts.has_a_door("therapist", "I want to get found on google? no, just book")


def test_the_quick_session_asks_for_what_is_missing_not_a_fixed_list():
    assert "whatever STILL MISSING lists" in dc.QUICK_SESSION
    assert "Never ask for what ON FILE lists" in dc.QUICK_SESSION


def test_an_address_said_to_the_coach_is_saved_and_reaches_the_page():
    patched = discovery.apply_practitioner_patch(
        {}, {"truth": {"address": "12 Main St", "phone": {"value": "555-0100"}}})
    assert patched["truth"]["address"] == {"value": "12 Main St", "source": "asked"}
    assert patched["truth"]["phone"]["value"] == "555-0100"

    site = {"site_config": {"discovery_dossier": patched}}
    assert site_composer._told_coach(site, "address") == "12 Main St"
    assert site_composer._told_coach(site, "hours") == ""
    assert site_composer._told_coach(None, "address") == ""
    assert site_composer._told_coach({"site_config": "junk"}, "address") == ""


def test_the_save_goes_through_the_coachs_own_door():
    with mock.patch.object(discovery, "answer", return_value={}) as answer:
        assert dc.apply_saves("b1", [{"section": "truth", "field": "address",
                                      "value": "12 Main St"}]) == 1
    assert answer.call_args[0][1] == {"truth": {"address": "12 Main St"}}


def _card(contact, btype="barbershop", dossier=None):
    return build_readiness.spec_readiness({
        "business": {"type": btype},
        "contact": contact,
        "site": {"site_config": {"discovery_dossier": dossier or {}}},
    })["notes"]


def test_the_card_names_a_missing_address():
    assert any("No address on file" in n for n in _card({"address": ""}))
    assert not any("No address on file" in n for n in _card({"address": "9 Elm St"}))
    assert not any("No address on file" in n for n in _card({"address": ""}, btype="software"))
    assert any("No address on file" in n
               for n in _card({"address": ""}, btype="software", dossier=_fresh()))


def test_a_caller_with_no_contact_block_says_nothing_about_it():
    notes = build_readiness.spec_readiness({"business": {"type": "barbershop"}})["notes"]
    assert not any("No address on file" in n for n in notes)


# ── what nobody here can do ──────────────────────────────────────────

def test_the_coach_is_told_nobody_can_reach_their_accounts():
    assert "WHAT NOBODY HERE CAN DO" in dc._SYSTEM
    assert "Never say or imply" in dc._SYSTEM


def _say(*lines):
    return [{"role": "assistant" if i % 2 else "user", "content": t}
            for i, t in enumerate(lines)]


def test_naming_where_the_photos_live_is_noticed():
    assert dc._photos_elsewhere(_say("they're all on my instagram")) == ""  # no photo talk
    assert dc._photos_elsewhere(_say("my photos are on my Instagram")) == "Instagram"
    assert dc._photos_elsewhere(_say("hi", "Got any photos of your work?", "on IG mostly")) == "IG"
    assert dc._photos_elsewhere(_say("hi", "What should the page do?", "find me on instagram")) == ""
    assert dc._photos_elsewhere([]) == ""
    assert dc._photos_elsewhere(_say("my photos are on my Instagram", "sure")) == ""  # already answered


def test_the_upload_card_comes_back_when_they_name_the_place():
    dc._PHOTO_STATE["b1"] = {"photos": 0, "asked": True}
    try:
        turn = {"stage": "story"}
        assert dc._should_ask_photos("b1", _say("my pics are on my Insta"), turn)
        assert not dc._should_ask_photos("b1", _say("not now"), turn)
        dc._PHOTO_STATE["b1"] = {"photos": 3, "asked": False}
        assert not dc._should_ask_photos("b1", _say("my pics are on my Insta"), turn)
    finally:
        dc._PHOTO_STATE.pop("b1", None)


def test_the_phone_is_where_the_card_works_not_somewhere_else():
    dc._PHOTO_STATE["b1"] = {"photos": 0, "asked": True}
    try:
        with mock.patch.object(dc, "_known_context", return_value="BUSINESS: X"):
            lead = dc.build_turn_prompt("b1", _say("my pics are on my phone"), mode="quick")[0]["content"]
        assert "THEIR PHOTOS ARE ON THEIR PHONE" in lead
        assert "Never say you can't reach them" in lead
        assert "Nobody here can reach them there" not in lead
        assert dc._should_ask_photos("b1", _say("my pics are on my phone"), {"stage": "story"})
    finally:
        dc._PHOTO_STATE.pop("b1", None)


def test_the_facts_come_before_the_pictures():
    quick = dc.QUICK_SESSION
    assert quick.index("One TRUTH question") < quick.index("The LOOKS gallery")
    assert quick.count("One TRUTH question") == 1


def test_the_turn_is_told_it_cannot_reach_them():
    dc._PHOTO_STATE["b1"] = {"photos": 0, "asked": True}
    try:
        with mock.patch.object(dc, "_known_context", return_value="BUSINESS: X"):
            lead = dc.build_turn_prompt("b1", _say("my pics are on my Insta"), mode="quick")[0]["content"]
        assert "THEY JUST SAID THEIR PHOTOS ARE ON: Insta" in lead
        with mock.patch.object(dc, "_known_context", return_value="BUSINESS: X"):
            lead = dc.build_turn_prompt("b1", _say("mostly fades"), mode="quick")[0]["content"]
        assert "THEY JUST SAID" not in lead
    finally:
        dc._PHOTO_STATE.pop("b1", None)


def test_the_coach_is_taught_to_read_what_people_say():
    for phrase in ("READ THE ASK", '"nothing fancy"', "does not mean the Plain setting",
                   '"find me"', "Say it back"):
        assert phrase in dc._SYSTEM, phrase
