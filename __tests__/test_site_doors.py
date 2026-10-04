"""The site's doors (2026-10-04).

Kevin: "what about events as well? all the things that are needed that
chief can connect to the site?" site_doors.py is the one place that knows
every working public page a site can link to. Pins: each door's live rule
is its owning router's (and the shop is no longer always ON), Chief sees
every door with what it needs and who opens it, the builder is told every
live door, and a builder page links each live door, including one opened
after the build, as a link shaped like its own nav links.
"""
import time
from unittest import mock

import builder_v2 as v2
import chief_site_design as csd
import site_doors as sd

BIZ = {"id": "b1", "name": "Grace", "type": "church", "stripe_account_id": "acct_1",
       "settings": {}}


def _facts(**over):
    f = {"business": dict(BIZ), "site": {"slug": "grace"}, "archetypes": [],
         "offerings": [], "sermons": [], "courses": []}
    f.update(over)
    return f


def _door(doors, key):
    return next(d for d in doors if d["key"] == key)


# ─── the rules ──────────────────────────────────────────────────────

def test_booking_is_live_only_when_published_with_a_calendar():
    f = _facts(archetypes=["booking_calendar"],
               offerings=[{"category": "session", "duration_min": 30}])
    off = _door(sd.doors_from_facts(f), "booking")
    assert off["live"] is False and off["missing"] == ["the booking page published"]
    f["business"]["settings"] = {"booking_page": {"published": True}}
    on = _door(sd.doors_from_facts(f), "booking")
    assert on["live"] is True and on["url"] == "https://grace.mysolutionist.app/book"


def test_the_shop_needs_something_to_sell_and_a_way_to_take_the_card():
    """The old builder check asked a helper that always answers, so every
    page with an address was told STORE: ON."""
    nothing = _door(sd.doors_from_facts(_facts()), "store")
    assert nothing["live"] is False and "an item with a price" in nothing["missing"]
    with mock.patch("payments_core.can_charge", return_value=True):
        selling = _door(sd.doors_from_facts(_facts(offerings=[
            {"category": "product", "current_price": 25}])), "store")
    assert selling["live"] is True


def test_events_giving_courses_sermons_news_and_members_use_their_own_rules():
    s = {"events_public": {"enabled": True}, "giving": {"enabled": True},
         "member_portal": {"enabled": True},
         "website_content": {"news": [{"title": "Fall picnic", "body": "Join us", "slug": "fall"}]}}
    f = _facts(business=dict(BIZ, settings=s), archetypes=["event_roster"],
               sermons=[{"published": True}], courses=[{"status": "published"}])
    with mock.patch("vertical_scope.client_surface_allowed", return_value=True):
        doors = {d["key"]: d for d in sd.doors_from_facts(f)}
    for key in ("events", "giving", "courses", "sermons", "members"):
        assert doors[key]["live"] is True, key
    # a non-church never has giving or the member app near
    shop = _facts(business=dict(BIZ, type="consultant", settings=s))
    doors = {d["key"]: d for d in sd.doors_from_facts(shop)}
    assert doors["giving"]["live"] is False and doors["giving"]["near"] is False


def test_a_rule_that_fails_reads_as_closed():
    with mock.patch("events_rsvp_router.events_settings", side_effect=RuntimeError("x")):
        events = _door(sd.doors_from_facts(_facts()), "events")
    assert events["live"] is False


def test_the_doors_live_on_the_sites_own_domain():
    f = _facts(site={"slug": "grace", "custom_domain": "gracechurch.org"})
    assert _door(sd.doors_from_facts(f), "sermons")["url"] == "https://gracechurch.org/sermons"


# ─── what Chief sees ────────────────────────────────────────────────

def test_chief_sees_the_live_doors_and_the_ones_close_to_opening():
    doors = [
        {"key": "booking", "name": "Booking", "path": "/book", "live": True, "near": True},
        {"key": "events", "name": "Events", "path": "/events", "live": True, "near": True},
        {"key": "giving", "name": "Giving", "path": "/give", "live": False, "near": True,
         "missing": ["card payments connected"], "chief_can_open": False,
         "opens_with": "the owner turns giving on in its settings"},
        {"key": "store", "name": "Shop", "path": "/store", "live": False, "near": False,
         "missing": ["an item with a price"], "chief_can_open": True, "opens_with": "x"},
    ]
    lines = csd.doors_lines(doors)
    assert lines[0].startswith("  Also live on the site: Events (/events).")
    assert lines[1] == ("  Giving: off (needs card payments connected). The owner opens it: "
                        "the owner turns giving on in its settings. Offer it once when it comes up.")
    assert len(lines) == 2, "booking has its own line; a door with nothing on file stays quiet"


# ─── what the builder is told ───────────────────────────────────────

def test_the_builder_is_told_every_live_door():
    doors = sd.doors_from_facts(_facts(
        business=dict(BIZ, settings={"giving": {"enabled": True}}),
        sermons=[{"published": True}]))
    with mock.patch("site_doors.site_doors", return_value=doors):
        block = v2.connected_systems_block("b1", {})
    assert "- GIVING: ON — a Give link" in block and "https://grace.mysolutionist.app/give" in block
    assert "- SERMONS: ON" in block and "- STORE: OFF" in block
    missing = v2.check_connected("<html><body>nothing</body></html>", block)
    assert {m.split(" is ON")[0].split(": ")[-1] for m in missing} == {"GIVING", "SERMONS"}


# ─── how a page reaches them ────────────────────────────────────────

NAV_PAGE = ('<header><a class="brand" href="/">Grace</a>'
            '<nav class="top"><a class="nav-link" href="#about">About</a>'
            '<a class="nav-link" href="#visit">Visit</a>'
            '<a class="btn btn-primary" href="#contact">Plan a visit</a></nav></header>'
            '<nav class="sheet"><ul><li class="it"><a href="#about">About</a></li>'
            '<li class="it"><a href="#visit">Visit</a></li></ul></nav>'
            '<nav class="icons"><a class="logo" href="/"><img src="x.png" alt=""></a></nav>')
EVENTS = {"key": "events", "name": "Events", "path": "/events", "nav_label": "Events", "live": True}
GIVE = {"key": "giving", "name": "Giving", "path": "/give", "nav_label": "Give", "live": True}


def test_a_live_door_gains_a_link_shaped_like_each_navs_own():
    out = sd.add_door_links(NAV_PAGE, [EVENTS])
    assert ('<a class="nav-link" href="#visit">Visit</a>'
            '<a href="/events" class="nav-link" data-sx-door="events">Events</a>'
            '<a class="btn btn-primary"') in out
    assert ('<li class="it"><a href="#visit">Visit</a></li>'
            '<li class="it"><a href="/events" data-sx-door="events">Events</a></li></ul>') in out
    assert '<nav class="icons"><a class="logo" href="/"><img src="x.png" alt=""></a></nav>' in out
    assert sd.add_door_links(out, [EVENTS]) == out


def test_a_door_the_page_already_links_is_left_alone():
    linked = NAV_PAGE.replace('href="#visit"', 'href="https://grace.org/give"', 1)
    assert 'data-sx-door="giving"' not in sd.add_door_links(linked, [GIVE])
    closed = dict(GIVE, live=False)
    assert sd.add_door_links(NAV_PAGE, [closed]) == NAV_PAGE


def test_wire_html_does_booking_and_every_other_door():
    page = NAV_PAGE.replace("Plan a visit", "Book a visit")
    booking = {"key": "booking", "name": "Booking", "path": "/book", "nav_label": "Book", "live": True}
    out = sd.wire_html(page, [booking, EVENTS])
    assert 'href="/book" data-sx-door="booking">Book a visit' in out
    assert out.count('data-sx-door="events"') == 2
    assert out.count('data-sx-door="booking"') == 1, "booking already linked: no extra nav link"


def test_only_builder_pages_are_wired():
    assert sd.is_builder_page('<p data-override-target="v2/hero/title">Hi</p>')
    assert not sd.is_builder_page("<p>hand-built</p>")


def test_the_serve_time_check_is_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(sd, "live_doors", lambda b: calls.append(b) or [EVENTS])
    sd._LIVE_CACHE.clear()
    assert sd.live_doors_cached("b1") == [EVENTS] and sd.live_doors_cached("b1") == [EVENTS]
    assert calls == ["b1"]
    monkeypatch.setattr(sd, "DOORS_TTL_S", 0)
    time.sleep(0.01)
    sd.live_doors_cached("b1")
    assert calls == ["b1", "b1"]


def test_a_visitor_gets_the_doors_on_a_builder_page_and_not_on_a_hand_built_one(monkeypatch):
    import asyncio
    import public_site as ps

    async def _no_rows(client, path):
        return []
    monkeypatch.setattr(ps, "_sb", _no_rows)
    monkeypatch.setattr(ps, "_inject_brand_meta", lambda html, biz_id: html)
    monkeypatch.setattr(ps, "_optimize_images", lambda html: html)
    monkeypatch.setattr(sd, "live_doors_cached", lambda b: [EVENTS])
    page = '<p data-override-target="v2/hero/title">Grace</p>' + NAV_PAGE
    served = asyncio.run(ps._augment_html(None, "b1", "grace", page))
    assert 'data-sx-door="events"' in served
    hand = asyncio.run(ps._augment_html(None, "b1", "grace", NAV_PAGE))
    assert 'data-sx-door' not in hand
    manual = asyncio.run(ps._augment_html(None, "b1", "grace", page, manual=True))
    assert 'data-sx-door="events"' not in manual


def test_chiefs_site_block_carries_the_doors():
    """Through the real PRACTITIONER SITE block, not the helper alone."""
    import chief_of_staff
    ctx = {"site": {"slug": "grace", "site_config": {}},
           "business": {"settings": {}}, "modules": [], "offerings": [],
           "site_doors": [{"key": "events", "name": "Events", "path": "/events",
                           "live": True, "near": True}]}
    block = chief_of_staff._format_site_info(ctx)
    assert "Also live on the site: Events (/events)." in block
