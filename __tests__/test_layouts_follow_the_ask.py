"""THE LAYOUT FOLLOWS THE ASK (2026-11-09, talking to Chief as a test shop).

An owner asked for a site so "people can find me and book". The Coach recommended
the Long-scroll story, "your story has enough beats", on almost no story, and the
Booking desk wasn't offered, with booking live, because the ranking was never told.
"""
from datetime import datetime, timezone
from unittest import mock

import design_coach as dc
import discovery
import offering_profiles
import sb_clients
import site_concept
import site_layouts as sl

FIND_AND_BOOK = "i need a website for my shop. nothing fancy i just want people to be able to find me and book"


def _v(text):
    return {"value": text, "source": "asked"}


# what the real session on the test shop had saved by the time the cards showed
THIN = {
    "world": {"room": _v("just a barbershop")},
    "story": {"craft": _v("mostly fades"),
              "proof": _v("clients see the fade in the mirror, nod, and take a pic")},
    "signature": {"moment": _v("the fresh fade in the mirror"),
                  "sharpened": _v("The fresh fade in the mirror: the nod, the pic")},
}
RICH = {
    "story": {k: _v("a real answer with some words") for k in ("origin", "craft", "proof", "voice")},
    "world": {"room": _v("a narrow room with one window on the street")},
}


def _ask(words):
    return {"the_ask": {"words": words, "at": datetime.now(timezone.utc).isoformat()}}


def _ctx(btype="barbershop", dossier=None, booking=False, offerings=2):
    return {"business": {"type": btype}, "gallery": [],
            "offerings": [{"id": str(i), "duration_min": 30} for i in range(offerings)],
            "testimonials": [], "store": {"enabled": False, "items": []},
            "booking": {"enabled": booking},
            "site": {"site_config": {"discovery_dossier": dossier or {}}}}


def _rank(*a, **k):
    return sl.rank(sl.signals(_ctx(*a, **k)))


def test_a_thin_session_is_not_a_story():
    assert sl.signals(_ctx(dossier=THIN))["story_beats"] == 2
    assert sl.signals(_ctx(dossier=RICH))["story_beats"] == 5


def test_a_few_words_are_not_a_beat():
    assert sl._story_beats({"world": {"room": _v("just a barbershop")}}) == 0
    assert sl._story_beats({"identity": {"one_liner": _v("fades")}}) == 0
    assert sl._story_beats({"identity": {"one_liner": _v("fades for people in a hurry")}}) == 1


def test_the_coachs_rewriting_of_one_line_is_not_a_second_beat():
    assert sl._story_beats({"signature": THIN["signature"]}) == 1


def test_the_shop_that_asked_to_be_found_and_booked_gets_the_booking_desk():
    rows = _rank(dossier={**THIN, **_ask(FIND_AND_BOOK)}, booking=True)
    assert rows[0]["key"] == "booking"
    assert "you asked for people to be able to book" in sl.reason_line(rows[0]).lower()
    assert "story" not in [r["key"] for r in rows[:3]]


def test_the_booking_desk_says_so_even_before_booking_is_on():
    rows = _rank(dossier={**THIN, **_ask(FIND_AND_BOOK)}, booking=False)
    assert rows[0]["key"] == "booking"
    assert "visitors do not book with you online" not in rows[0]["against"]


def test_a_real_story_and_no_ask_can_still_earn_the_long_scroll():
    top = [r["key"] for r in _rank(btype="life coach", dossier=RICH)[:3]]
    assert "story" in top


def test_nothing_fancy_keeps_the_longest_page_off_the_shortlist():
    rows = _rank(btype="life coach", dossier={**RICH, **_ask("nothing fancy please")})
    story = next(r for r in rows if r["key"] == "story")
    assert "you asked to keep it simple, and this is the longest page there is" in story["against"]
    assert rows[0]["key"] != "story"


def test_the_owners_own_pick_still_leads():
    dossier = {**THIN, **_ask(FIND_AND_BOOK), "taste": {"layout": _v("story")}}
    assert _rank(dossier=dossier)[0]["key"] == "story"


def test_an_old_ask_does_not_steer_the_page():
    old = {"the_ask": {"words": FIND_AND_BOOK, "at": "2020-01-01T00:00:00+00:00"}}
    assert sl.signals(_ctx(dossier=old))["ask_book"] is False
    assert sl.signals(_ctx(dossier=old))["ask_simple"] is False


def test_the_words_set_the_main_action():
    for words, want in ((FIND_AND_BOOK, "book"), ("so people can make an appointment", "book"),
                        ("I sell dresses", "buy"), ("people can't find us", "visit"),
                        ("get me more clients", "call"), ("just a basic site", "")):
        assert sl.signals(_ctx(btype="studio", dossier=_ask(words)))["action"] == want, words


def test_what_they_saved_outranks_the_words():
    dossier = {**_ask(FIND_AND_BOOK), "identity": {"primary_action": _v("call me for a quote")}}
    assert sl.signals(_ctx(dossier=dossier))["action"] == "call"


def test_books_and_bookkeeping_are_not_booking():
    assert not sl.signals(_ctx(dossier=_ask("I do bookkeeping and my books are full")))["ask_book"]


def _ranked_through_the_coach(booking):
    biz = {"name": "Shop", "business_type": "barbershop", "settings": {}}

    def fake_get(path, *a, **k):
        if path.startswith("/businesses"):
            return [biz]
        if path.startswith("/offerings"):
            assert "duration_min" in path or "current_price" in path
            return [{"name": "Fade", "current_price": 35, "duration_min": 45},
                    {"name": "Lineup", "current_price": 20, "duration_min": 20}]
        return []

    state = {"store_url": "", "booking_enabled": booking,
             "booking_url": "https://x.example/book" if booking else ""}
    with mock.patch.object(sb_clients, "sb_get_as_service", side_effect=fake_get), \
         mock.patch.object(offering_profiles, "business_state", return_value=state), \
         mock.patch.object(site_concept, "recent_layouts", return_value=[]), \
         mock.patch.object(discovery, "get_dossier", return_value={**THIN, **_ask(FIND_AND_BOOK)}):
        return dc._known_context("b1")


def test_the_coach_tells_the_ranking_that_booking_is_live():
    known = _ranked_through_the_coach(booking=True)
    block = known.split("LAYOUTS THAT FIT THIS BUSINESS")[1]
    first = block.split("- page-")[1]
    assert first.startswith("booking:")
    assert "visitors do not book" not in block
