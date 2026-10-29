"""The member app, round three (Kevin approved the "Member App, Round Three"
canvas, 2026-10-19): a colour family beside the church colour, each photo in
the look the church picked, default pictures instead of photos picked by
chance, a shorter top of Home and the Today card."""
from datetime import date

import member_app_photos as photos
import member_app_ui as ui
import member_portal as mp
import member_portal_church as mpc
import member_portal_reading as mpr
from public_form_theme import contrast

ME = {"id": "c1", "name": "Ana Rivers", "email": "ana@example.com"}


def _biz(primary="#C2125F", base="black", **portal):
    return {"id": "b1", "name": "Love City Church",
            "settings": {"brand_kit": {"colors": {"primary": primary}}, "member_portal": {"base": base, **portal}}}


# ─── the colour family ───────────────────────────────────────────────


def test_every_family_colour_reads_on_every_base_and_on_its_own_card():
    for base in ui.BASES:
        p = ui.palette(_biz(base=base), {})
        for slot in ui.FAMILY:
            assert contrast(p[f"{slot}_ink"], p["bg"]) >= 4.5, (base, slot)
            assert contrast(p[f"{slot}_ink"], p[f"{slot}_deep"]) >= 4.5, (base, slot)
            assert contrast(p[f"{slot}_on"], p[slot]) >= 4.5, (base, slot)
            assert contrast(p[f"{slot}_lit"], p[f"{slot}_night"]) >= 4.5, (base, slot)


def test_a_family_colour_near_the_churchs_own_steps_aside():
    blue = ui.palette(_biz("#2563EB"), {})
    assert blue["violet"] == blue["fill"] and blue["violet_ink"] == blue["accent"]      # Watch takes the church's blue
    assert blue["teal"] == ui.FAMILY["teal"]["fill"]                                    # the rest stay
    magenta = ui.palette(_biz(), {})
    assert {magenta[s] for s in ui.FAMILY} == {f["fill"] for f in ui.FAMILY.values()}


def test_a_church_can_keep_one_colour():
    p = ui.palette(_biz(colours="church"), {})
    assert all(p[s] == p["fill"] and p[f"{s}_ink"] == p["accent"] for s in ui.FAMILY)


def test_the_stylesheet_carries_the_family_and_each_tab_wears_its_colour():
    css = ui.css(_biz(), {})
    assert "--gold:#E3A92B" in css and "--teal-ink:" in css and ".mb-tab[aria-current][data-hue=violet]" in css
    bar = ui.nav("bible")
    assert 'href="/my/bible" aria-current="page" data-hue="gold"' in bar
    assert 'href="/my/sermons" data-hue="violet"' in bar and 'href="/my/groups" data-hue="teal"' in bar
    page = mp._shell(_biz(), None, "Bible", "<p>x</p>", tab="bible", who=ME)
    assert '<body class="pg-bible">' in page


# ─── photos: the church's choice, a photo named for it, else the default ─


POOL = ["/public/site-assets/lcc/service-wide.webp", "/public/site-assets/lcc/supper-house.webp",
        "/public/site-assets/lcc/worship-team.webp", "/public/site-assets/lcc/pantry-carry.webp"]


def test_the_churchs_own_choice_wins_with_its_look():
    biz = _biz(pictures={"event:supper-house": {"url": "https://cdn.example/supper.jpg", "look": "church"},
                         "event:prayer-night": {"url": ""}})
    assert photos.choose(biz, "event:supper-house", POOL, title="Supper House") == ("https://cdn.example/supper.jpg", "church")
    assert photos.choose(biz, "event:prayer-night", POOL, title="Prayer Night") == ("", "")    # it chose the default
    bad = _biz(pictures={"home": {"url": "javascript:alert(1)"}, "x": {"url": "https://a.example/p.jpg", "look": "neon"}})
    assert photos.assigned(bad, "home") is None
    assert photos.assigned(bad, "x") == {"url": "https://a.example/p.jpg", "look": "colour"}


def test_a_photo_named_for_the_thing_else_the_default_never_one_by_chance():
    biz = _biz()
    assert photos.choose(biz, "event:supper-house", POOL, title="Supper House")[0].endswith("supper-house.webp")
    assert photos.choose(biz, "event:sunday-worship", POOL, title="Sunday Worship")[0].endswith("worship-team.webp")
    assert photos.choose(biz, "event:men-s-breakfast", POOL, title="Men's Breakfast") == ("", "")
    used = {POOL[1]}
    assert photos.choose(biz, "event:x", POOL, title="Supper House", used=used) == ("", "")     # not twice on one screen


def test_this_week_wears_the_default_picture_when_nothing_fits():
    occ = [{"entry_id": "e1", "title": "Sunday Worship", "date": "2026-10-25"},
           {"entry_id": "e2", "title": "Men's Breakfast", "date": "2026-10-24"}]
    html = mpc.week_cards(occ, None, pool=POOL, biz=_biz())
    breakfast = html[html.index("Men&#x27;s Breakfast") - 1500:html.index("Men&#x27;s Breakfast")]
    assert 'class="mb-def h-coral' in breakfast and "worship-team.webp" in html
    assert 'class="h-coral" aria-labelledby="mb-week"' in html
    assert mpc.event_key("Sunday Worship!") == "event:sunday-worship"


def test_tiles_take_the_picture_the_church_chose_else_their_default():
    biz = _biz(pictures={"tile:prayer": {"url": "https://cdn.example/pray.jpg", "look": "bw"}})
    html = mpc.home_tiles(biz, None, [])
    prayer = html[html.index('href="/my/prayer"') - 40:html.index('href="/my/prayer"') + 260]
    assert 'class="mb-bt is-sq"' in prayer and 'mb-ph is-bw' in prayer and "pray.jpg" in prayer
    groups = html[html.index('href="/my/groups"') - 60:html.index('href="/my/groups"') + 200]
    assert "is-def" in groups and 'class="mb-def h-teal' in groups
    assert mpc.tile_kind("/my/events?x=1") == "events" and mpc.tile_kind("https://x.example") == "welcome"


def test_a_photo_shows_in_its_look():
    assert 'class="mb-ph is-church ' in ui.photo("https://a.example/p.jpg", look="church")
    assert 'class="mb-ph is-bw ' in ui.photo("https://a.example/p.jpg")
    assert 'class="mb-ph is-colour ' in ui.picture("https://a.example/p.jpg", "colour", "groups")
    assert 'mb-def h-violet is-night' in ui.picture("", "", "worship", night=True)


# ─── Home ────────────────────────────────────────────────────────────


def test_home_goes_greeting_next_quick_today_then_latest():
    occ = [{"entry_id": "e1", "title": "Midweek Service", "date": "2026-10-21", "date_label": "Wednesday",
            "attending": 24}]
    lib = {"series": [], "sermons": [{"id": "11111111-1111-1111-1111-111111111111", "series_id": None,
                                      "title": "Built to Last", "preached_on": "2026-10-18", "speaker": "",
                                      "scripture": "", "summary": "", "questions": "", "video_url": "",
                                      "audio_url": "", "published": True}]}
    plan = {"day": 21, "of": 31, "label": "Proverbs 21", "title": "Psalms and Proverbs in a month",
            "href": "/my/bible/proverbs/21"}
    page = mp.render_home(_biz(), None, me=ME, occasions=occ, groups=None, library=lib, give_url="",
                          reading=mpr.today_row(plan, set()))
    body = page[page.index("<body"):]
    order = [body.index(x) for x in ('class="mb-hero"', 'class="mb-quick"', 'class="mb-today"', 'id="mb-latest"')]
    assert order == sorted(order)
    assert 'class="h-coral" href="/my/events"' in body and 'class="h-violet" href="/my/live"' in body
    today = body[body.index('class="mb-today"'):body.index('id="mb-latest"')]
    assert "Verse of the day" in today and "Proverbs 21" in today and 'action="/my/reading"' in today


def test_todays_reading_row_ticks_and_shows_when_its_read():
    plan = {"day": 3, "of": 30, "label": "Matthew 7–9", "title": "The Gospels in 30 days", "href": "/my/bible/matthew/7"}
    open_ = mpr.today_row(plan, set())
    assert '<input type="hidden" name="day" value="3">' in open_ and 'class="mb-tick"' in open_
    done = mpr.today_row(plan, {3})
    assert 'mb-tick is-done' in done and "<form" not in done
    assert mpr.today_row(None, None) == ""


def test_without_a_plan_today_offers_where_they_left_off():
    page = mp.render_home(_biz(), None, me=ME, occasions=[], groups=None, library=None, give_url="",
                          where=("PRO", 4))
    today = page[page.index('class="mb-today"'):]
    assert "Keep reading Proverbs 4" in today and 'href="/my/bible/proverbs/4"' in today


def test_the_top_of_home_is_shorter():
    css = ui.css(_biz(), {})
    fam = css[css.index("/* Home: the next gathering, shorter"):]
    assert "min-height:236px" in fam and "aspect-ratio:auto" in fam
