"""THE KIT'S CHURCH LAYOUTS (2026-11-10): Bulletin, Magazine, Leader, Poster.

Kevin: "do all but start on these ones." Pins the facts rules these layouts add
(gatherings checked against the data, a leader's photo must be them) and that
every layout assembles whole: nav links reach real sections, ministries and
events show when the data has them, nothing is shown twice.
"""
import re

import site_kit as kit
import site_kit_church as church

PHOTOS = [{"url": f"https://example.org/p{i}.jpg", "alt": alt} for i, alt in enumerate([
    "The whole church family together", "The worship team singing", "The pastor preaching",
    "A community day outside", "Hands on the keyboard", "Volunteers giving away food",
    "A graduate celebrated", "A full Sunday service", "Praying with a neighbor"])]

FX = {
    "business": {"id": "b-church", "name": "Cedar Hollow Church", "type": "church"},
    "owner_brief": "We are a family church. Everyone is welcome.",
    "contact": {"address": "12 Cedar Rd, Hollow, MI", "hours": "Sundays 10:30am; Wednesdays 7pm, Bible study"},
    "gallery": PHOTOS,
    "testimonials": [],
    "offerings": [],
    "ministries": [{"name": "Kids church", "when": "Sundays 10:30am", "who": "Ages 4 to 11",
                    "description": "Songs, a story and snacks while parents worship."},
                   {"name": "Food pantry", "when": "Saturdays 9am", "description": "Groceries for anyone who needs them."}],
    "events": [{"title": "Harvest dinner", "date": "Nov 22", "time": "5pm", "place": "Fellowship hall"}],
    "discovery_dossier": {"identity": {"team": [{"name": "Dana Reyes", "role": "Senior pastor"}]}},
}

WORDS = {
    "tokens": {"bg": "#f4f1ec", "text": "#1d1a17", "deep": "#2b2320", "accent": "#a13d2f",
               "second": "#e9e4dc", "muted": "#ece8e1", "display_upper": True, "radius": 18, "pill": True},
    "gatherings": [{"day": 0, "time": "10:30", "label": "Sunday worship"},
                   {"day": 3, "time": "19:00", "label": "Bible study"},
                   {"day": 0, "time": "09:00", "label": "Early service"}],       # not in the data
    "hero": {"lines": ["Come as", "you are"], "inset_photos": [PHOTOS[0]["url"]], "portrait": PHOTOS[0]["url"]},
    "leaders": {"head": "Our pastors", "head_script": "pastors", "photo": PHOTOS[0]["url"]},
    "story": {"paragraphs": ["We are a family church."], "polaroids": [{"url": PHOTOS[3]["url"], "caption": "Community day"}]},
    "ceremony": {"line": "Everyone is welcome", "accent_word": "welcome"},
    "visit": {"steps": ["Come Sunday at 10:30am.", "Find us at 12 Cedar Rd."]},
    "nav": [{"label": "Pastors", "target": "pastors"}, {"label": "Photos", "target": "people"},
            {"label": "Board", "target": "board"}],
}


def _page(layout):
    return kit.assemble(FX, dict(WORDS), None, layout)


def test_a_gathering_must_be_stated_in_the_data():
    rows = kit.clean_gatherings(WORDS["gatherings"], kit.fact_records(FX))
    assert [(g["day"], g["time"]) for g in rows] == [(0, "10:30"), (3, "19:00")]
    assert rows[0]["time_label"] == "10:30am"


def test_a_gathering_label_the_data_does_not_hold_is_dropped():
    rows = kit.clean_gatherings([{"day": 0, "time": "10:30", "label": "Healing crusade"}], kit.fact_records(FX))
    assert rows[0]["label"] == "Gathering"


def test_a_leaders_photo_must_show_them():
    assert church.shows_leader("The pastor preaching", [{"name": "Dana Reyes"}])
    assert church.shows_leader("Dana at the door", [{"name": "Dana Reyes"}])
    assert not church.shows_leader("The whole church family together", [{"name": "Dana Reyes"}])


def test_the_leaders_block_drops_a_photo_that_is_not_them_and_never_doubles_a_word():
    html = _page("poster")
    block = html[html.index('id="leaders"'):html.index("</section>", html.index('id="leaders"'))]
    assert PHOTOS[0]["url"] not in block
    assert block.lower().count("pastors") == 1


def test_the_leader_hero_finds_the_photo_that_shows_the_leader():
    html = _page("leader")
    hero = html[html.index('id="top"'):html.index("</section>", html.index('id="top"'))]
    assert PHOTOS[2]["url"] in hero and PHOTOS[0]["url"] not in hero


def test_every_layout_assembles_whole():
    for layout in church.LAYOUTS:
        html = _page(layout)
        assert html.startswith("<!doctype html>"), layout
        ids = set(re.findall(r'id="([a-z]+)"', html))
        for target in re.findall(r'href="#([a-z]+)"', html):
            assert target in ids, (layout, target)                     # no link points at nothing
        assert html.count('data-sx-object="hours-card"') <= 1, layout
        assert 'data-sx-object="sign-off"' in html, layout


def test_ministries_and_events_show_when_the_data_has_them():
    for layout in ("bulletin", "magazine"):
        html = _page(layout)
        assert "Kids church" in html and "Food pantry" in html, layout
        assert "Harvest dinner" in html, layout


def test_the_album_fills_its_rows():
    html = _page("poster")
    m = re.search(r'k-album-grid n(\d+)', html)
    assert m and int(m.group(1)) in (3, 6, 9)


def test_the_magazine_rail_lists_the_page_s_own_sections():
    html = _page("magazine")
    rail = html[html.index('class="k-rail"'):html.index("</aside>")]
    assert rail.count("<li>") >= 4


def test_labels_read_whatever_colour_the_words_chose():
    t = kit.tokens(WORDS["tokens"])
    assert kit.contrast(t["second"], t["bg"]) >= 4.5
    assert kit.contrast(t["muted"], t["bg"]) >= 4.5


def test_the_layout_comes_from_the_blueprint():
    assert kit.kit_layout("0. THE CONCEPT\nLAYOUT: poster - the owner asked for poster-size type") == "poster"
    assert kit.kit_layout("LAYOUT: booking. People come to this page") == "booking"
    assert kit.kit_layout("LAYOUT: bento - many facts") == ""                # not in the kit yet


def test_the_words_sheet_offers_this_layouts_sections_as_nav_targets():
    nav = kit.shape_for("bulletin")["nav"][0]["target"]
    assert "times" in nav and "board" not in nav
