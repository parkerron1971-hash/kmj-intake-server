"""Chief sets up booking from what the owner told the Coach (2026-10-04).

Kevin: "what about booking? if someone wants to book, why haven't I seen
that?" The Design Coach heard the services, prices and hours; the blueprint
card said "add them as services"; nothing set booking up, so every button
on the page opened a note form. Pins: Chief sees whether booking is live and
what is missing, with the owner's own words to set it up from and the rule
to ask for any length they did not say; publish_booking_page puts the page
live only when it can take a booking; a live booking page turns the site's
book buttons into booking links on every render, without a rebuild.
"""
import asyncio
from unittest import mock

import action_registry
import build_readiness
import chief_of_staff
import chief_offering_actions as coa
import chief_prompt
import chief_site_design as csd
import site_composer as sc

DOSSIER = {"discovery_dossier": {"truth": {
    "offers": [{"name": "discovery call", "note": "where people usually start"},
               {"name": "six-week program", "price": "$1,200", "duration": "six weekly sessions"},
               {"name": "single session", "price": "$150"}],
    "hours": {"value": "Tuesday to Saturday, 9 to 6"}}}}
CALENDAR = [{"name": "Sessions", "archetype": "booking_calendar"}]


# ─── what Chief sees ────────────────────────────────────────────────

def test_chief_sees_booking_is_off_and_the_owners_own_words_to_set_it_up():
    lines = csd.booking_lines(DOSSIER, {}, CALENDAR, [])
    assert lines[0].startswith("  Booking: off (no service with a length in minutes; "
                               "the booking page is not published)")
    said = lines[1]
    assert "discovery call; six-week program ($1,200, six weekly sessions); single session ($150)" in said
    assert "hours: Tuesday to Saturday, 9 to 6" in said
    assert "never guess one" in said and "publish_booking_page" in said
    assert '"show_price_to_customer": false' in said


def test_chief_sees_live_booking_and_a_ready_but_unpublished_one():
    sessions = [{"name": "Discovery call", "category": "session", "duration_min": 30}]
    live = csd.booking_lines(DOSSIER, {"booking_page": {"published": True}}, CALENDAR, sessions)
    assert live == ["  Booking: live. The site's book and discovery-call buttons open the booking page."]
    ready = csd.booking_lines({}, {}, CALENDAR, sessions)
    assert ready[-1] == "  Everything booking needs is on file: offer publish_booking_page."
    none = csd.booking_lines({}, {}, [], [])
    assert "no booking calendar yet" in none[0] and len(none) == 1


def test_the_site_block_carries_the_booking_lines():
    site = {"slug": "x", "site_config": dict(DOSSIER)}
    lines = csd.site_design_lines(site, {}, modules=CALENDAR, offerings=[])
    assert any(line.startswith("  Booking: off") for line in lines)


# ─── the action ─────────────────────────────────────────────────────

def test_the_action_is_registered_dispatched_and_taught():
    assert "publish_booking_page" in action_registry.REGISTRY
    assert chief_of_staff.ACTION_HANDLERS["publish_booking_page"] is coa.handle_publish_booking_page
    assert '{{"type":"publish_booking_page"}}' in chief_prompt.__dict__.get("_PROMPT_SOURCE", "") or \
        "publish_booking_page" in open(chief_prompt.__file__, encoding="utf-8").read()


def test_a_page_that_cannot_take_a_booking_is_not_put_live():
    with mock.patch("booking_page_router.publish_blockers",
                    return_value=["Add at least one service with a length in minutes."]), \
            mock.patch.object(coa.sb_clients, "sb_patch_as_service") as patch:
        out = asyncio.run(coa.handle_publish_booking_page(None, {"id": "b1"}, {}))
    assert out.get("failed") is True
    assert "can't take a booking yet" in out["result"] and "length in minutes" in out["result"]
    patch.assert_not_called()


def test_a_ready_page_goes_live_and_the_site_refreshes():
    seen = {}
    with mock.patch("booking_page_router.publish_blockers", return_value=[]), \
            mock.patch.object(coa.sb_clients, "sb_get_as_service",
                              return_value=[{"id": "b1", "name": "VTC", "settings": {"x": 1}}]), \
            mock.patch.object(coa.sb_clients, "sb_patch_as_service",
                              side_effect=lambda path, body: seen.update(body=body)), \
            mock.patch("business_sites_helpers.ensure_business_site",
                       return_value=({"slug": "vtc"}, False)), \
            mock.patch("business_sites_helpers.booking_url_for_site",
                       return_value="https://vtc.mysolutionist.app/book"), \
            mock.patch.object(sc, "refresh_if_composed") as refresh:
        out = asyncio.run(coa.handle_publish_booking_page(None, {"id": "b1"}, {}))
    assert seen["body"]["settings"] == {"x": 1, "booking_page": {"published": True}}
    refresh.assert_called_once_with("b1")
    assert out["url"] == "https://vtc.mysolutionist.app/book" and "live" in out["result"]


def test_taking_the_page_down_needs_no_gate():
    with mock.patch("booking_page_router.publish_blockers") as gate, \
            mock.patch.object(coa.sb_clients, "sb_get_as_service",
                              return_value=[{"id": "b1", "settings": {"booking_page": {"published": True}}}]), \
            mock.patch.object(coa.sb_clients, "sb_patch_as_service"), \
            mock.patch("business_sites_helpers.ensure_business_site", return_value=({"slug": "v"}, False)), \
            mock.patch("business_sites_helpers.booking_url_for_site", return_value="u"), \
            mock.patch.object(sc, "refresh_if_composed"):
        out = asyncio.run(coa.handle_publish_booking_page(None, {"id": "b1"}, {"published": False}))
    gate.assert_not_called()
    assert "taken down" in out["result"]


# ─── the site's buttons ─────────────────────────────────────────────

PAGE = ('<nav><a class="btn" href="#contact">Start with a discovery call</a>'
        '<a href="#contact">Leave a note</a></nav>'
        '<a href="#contact" class="row"><span>Single session</span> $150</a>'
        '<a href="/#contact"><b>Book</b> a session</a><a href="#about">Our story</a>')


def test_book_worded_note_links_open_booking_and_nothing_else_moves():
    out = sc.rewire_booking_links(PAGE, "https://vtc.mysolutionist.app/book?x=1&y=2")
    assert out.count('data-sx-door="booking"') == 2
    assert 'href="https://vtc.mysolutionist.app/book?x=1&amp;y=2" data-sx-door="booking">Start with a discovery call' in out
    assert '<a href="#contact">Leave a note</a>' in out
    assert '<a href="#contact" class="row"><span>Single session</span> $150</a>' in out
    assert '<a href="#about">Our story</a>' in out
    assert sc.rewire_booking_links(out, "https://vtc.mysolutionist.app/book?x=1&y=2") == out
    assert sc.rewire_booking_links(PAGE, "") == PAGE


def test_the_buttons_follow_booking_on_every_render():
    with mock.patch("site_doors.live_doors", return_value=[]):
        assert sc.wire_booking_doors(PAGE, "b1") == PAGE
    booking = {"key": "booking", "name": "Booking", "path": "/book", "nav_label": "Book",
               "live": True}
    with mock.patch("site_doors.live_doors", return_value=[booking]):
        # root-relative, so the page stays right on whichever host serves it
        assert 'href="/book" data-sx-door="booking">Start with a discovery call'             in sc.wire_booking_doors(PAGE, "b1")


def test_the_blueprint_card_points_to_chief_for_booking():
    out = build_readiness.spec_readiness({"site": {"site_config": DOSSIER}, "offerings": []})
    note = next(n for n in out["notes"] if n.startswith("The page lists what you told the Coach"))
    assert "Visitors can't book yet: ask Chief to set up booking from what you told the Coach" in note
    assert "Add them as services" not in note
