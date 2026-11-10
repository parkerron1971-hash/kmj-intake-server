"""AN OLD PICK MEETS A NEW ASK (2026-11-10, the live test on the test shop).

A day earlier the owner tapped the Long-scroll story when the old ranking
recommended it. Then they asked Chief for a site "so people can find me and
book, nothing fancy", and the saved pick kept leading: the Coach's summary said
"a long-scroll story" until the owner objected. A pick made before this ask now
goes back on the table once, against what fits the ask, and the owner chooses.
"""
from datetime import datetime, timedelta, timezone
from unittest import mock

import design_coach as dc
import discovery
import offering_profiles
import sb_clients
import site_concept
import site_layouts as sl

FIND_AND_BOOK = "i need a website for my shop. nothing fancy, i just want people to be able to find me and book"
NOW = datetime.now(timezone.utc)


def _at(delta):
    return (NOW + delta).isoformat()


def _dossier(pick_at=None, ask_at=None, pick="story", ask=FIND_AND_BOOK):
    leaf = {"value": pick, "source": "asked"}
    if pick_at:
        leaf["at"] = pick_at
    d = {"world": {"room": {"value": "just a barbershop", "source": "asked"}},
         "taste": {"layout": leaf}}
    if ask:
        d["the_ask"] = {"words": ask, "at": ask_at or _at(timedelta(0))}
    return d


# ─── telling an earlier pick apart ───────────────────────────────────

def test_a_pick_saved_before_picks_were_dated_counts_as_earlier():
    assert discovery.layout_picked_before_ask(_dossier()) == "story"
    assert sl.pick_before_ask(_dossier()) == "story"


def test_a_pick_from_yesterday_is_earlier_than_todays_ask():
    assert sl.pick_before_ask(_dossier(pick_at=_at(timedelta(days=-1)))) == "story"


def test_a_pick_made_after_the_ask_binds():
    assert sl.pick_before_ask(_dossier(pick_at=_at(timedelta(minutes=5)))) == ""


def test_no_ask_or_an_old_ask_leaves_the_pick_alone():
    assert sl.pick_before_ask(_dossier(ask="")) == ""
    assert sl.pick_before_ask(_dossier(ask_at=_at(timedelta(days=-40)))) == ""


def test_no_pick_is_nothing_to_offer():
    d = _dossier()
    d["taste"] = {}
    assert sl.pick_before_ask(d) == ""


def test_a_layout_pick_is_dated_when_it_is_saved_and_nothing_else_is():
    out = discovery.apply_practitioner_patch({}, {"taste": {
        "layout": {"value": "booking", "source": "asked"},
        "look": {"value": "neon", "source": "asked"}}})
    assert out["taste"]["layout"]["value"] == "booking"
    assert datetime.fromisoformat(out["taste"]["layout"]["at"]) >= NOW
    assert "at" not in out["taste"]["look"]
    # and a pick tapped now binds against the ask that brought them here
    out["the_ask"] = {"words": FIND_AND_BOOK, "at": _at(timedelta(minutes=-1))}
    assert sl.pick_before_ask(out) == ""


# ─── what the Coach sees ─────────────────────────────────────────────

def _known(dossier, booking=True):
    biz = {"name": "Shop", "business_type": "barbershop", "settings": {}}

    def fake_get(path, *a, **k):
        if path.startswith("/businesses"):
            return [biz]
        if path.startswith("/offerings"):
            return [{"name": "Fade", "current_price": 35, "duration_min": 45},
                    {"name": "Lineup", "current_price": 20, "duration_min": 20}]
        return []

    state = {"store_url": "", "booking_enabled": booking,
             "booking_url": "https://x.example/book" if booking else ""}
    with mock.patch.object(sb_clients, "sb_get_as_service", side_effect=fake_get), \
         mock.patch.object(offering_profiles, "business_state", return_value=state), \
         mock.patch.object(site_concept, "recent_layouts", return_value=[]), \
         mock.patch.object(discovery, "get_dossier", return_value=dossier):
        return dc._known_context("b1")


def test_the_coach_offers_what_fits_the_ask_against_the_old_pick():
    known = _known(_dossier(pick_at=_at(timedelta(days=-1))))
    block = known.split("LAYOUTS THAT FIT THIS BUSINESS")[1]
    assert block.split("- page-")[1].startswith("booking:")
    assert "A LAYOUT PICKED BEFORE THIS ASK" in block
    offer = block.split("A LAYOUT PICKED BEFORE THIS ASK")[1]
    assert "page-booking, page-story" in offer
    assert "never switch it for them" in offer
    assert "You picked it last time" in block


def test_the_cards_mark_the_new_fit_recommended():
    _known(_dossier(pick_at=_at(timedelta(days=-1))))
    gallery = {"kind": "page", "options": ["page-booking", "page-story", "page-minimal"]}
    dc._finish_page_gallery(gallery, "b1")
    assert gallery["recommended"] == "page-booking"
    assert gallery["notes"]["page-story"].startswith("You picked it last time")


def test_a_pick_made_this_session_leads_and_nothing_is_offered():
    known = _known(_dossier(pick_at=_at(timedelta(minutes=5))))
    block = known.split("LAYOUTS THAT FIT THIS BUSINESS")[1]
    assert block.split("- page-")[1].startswith("story:")
    assert "A LAYOUT PICKED BEFORE THIS ASK" not in known


def test_an_old_pick_that_still_fits_best_is_not_questioned():
    known = _known(_dossier(pick="booking", pick_at=_at(timedelta(days=-1))))
    assert "A LAYOUT PICKED BEFORE THIS ASK" not in known


def test_until_they_choose_the_build_keeps_their_pick():
    ctx = {"business": {"type": "barbershop"}, "offerings": [{"duration_min": 30}] * 2,
           "booking": {"enabled": True},
           "site": {"site_config": {"discovery_dossier": _dossier(pick_at=_at(timedelta(days=-1)))}}}
    assert "THE OWNER PICKED: story" in sl.director_block(sl.signals(ctx))
