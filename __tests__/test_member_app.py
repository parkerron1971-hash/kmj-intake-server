"""The member app (Broadcast look, tinted to each church's brand,
2026-09-30): the palette, Home, Sermons, Me, and the bar."""
import colorsys
from datetime import date

import member_app_ui as ui
import member_portal as mp
import member_portal_church as mpc
import member_portal_sermons as mps
from public_form_theme import contrast, luminance

ME = {"id": "c1", "name": "Ana Rivers", "email": "ana@example.com"}
S1 = "11111111-1111-1111-1111-111111111111"
S2 = "22222222-2222-2222-2222-222222222222"
K = "33333333-3333-3333-3333-333333333333"


def _biz(primary=None, accent=None):
    kit = {}
    if primary:
        kit["colors"] = {"primary": primary}
    if accent:
        kit["accent"] = accent
    return {"id": "b1", "name": "First Light", "settings": {"brand_kit": kit}}


def _hue(hex_):
    r, g, b = (int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hls(r, g, b)[0] * 360


def _pal(primary=None, accent=None):
    return ui.palette(_biz(primary, accent), {"accent": accent or "#334155"})


def _lib():
    return {"series": [{"id": K, "title": "Kingdom Order", "description": "How God orders a life."}],
            "sermons": [
                {"id": S1, "series_id": K, "title": "God's order for families", "preached_on": "2026-09-27",
                 "speaker": "Pastor Ana", "scripture": "1 Corinthians 11:3", "summary": "Order is love.",
                 "questions": "Where is order missing?", "video_url": "https://youtu.be/abc123", "audio_url": "",
                 "published": True},
                {"id": S2, "series_id": None, "title": "Deliverance", "preached_on": "2026-09-13",
                 "speaker": "", "scripture": "Luke 11:20", "summary": "", "questions": "", "video_url": "",
                 "audio_url": "", "published": True},
            ]}


# ─── the palette: dark, tinted to the church's own brand ─────────────


def test_the_ground_carries_each_brands_own_hue():
    red, green, navy = _pal("#C8102E"), _pal("#2F8F5B"), _pal("#0B2146")
    assert abs(_hue(red["ground"]) - _hue("#C8102E")) < 12 or abs(_hue(red["ground"]) - _hue("#C8102E")) > 348
    assert abs(_hue(green["ground"]) - _hue("#2F8F5B")) < 12
    assert abs(_hue(navy["ground"]) - _hue("#0B2146")) < 12
    assert red["ground"] != green["ground"] != navy["ground"]        # not the same blue for everyone
    for p in (red, green, navy, _pal()):
        assert luminance(p["ground"]) < 0.02                         # still a dark app
        assert contrast(p["text"], p["ground"]) >= 12
        assert contrast(p["muted"], p["ground"]) >= 4.5
        assert contrast(p["dim"], p["ground"]) >= 3


def test_a_church_with_no_colour_gets_a_warm_neutral():
    p = ui.palette({"id": "b1", "settings": {}}, {"accent": "#555555"})
    assert ui.brand_colour({"id": "b1", "settings": {}}, {"accent": "#555555"}) is None
    r, g, b = (int(p["ground"][i:i + 2], 16) for i in (1, 3, 5))
    assert r >= b                                                    # warm, not blue


def test_a_dark_accent_is_lightened_in_its_own_hue_not_replaced():
    p = _pal("#0B2146", "#0B2146")
    assert contrast(p["accent"], p["ground"]) >= 4.5
    assert abs(_hue(p["accent"]) - _hue("#0B2146")) < 15              # still the church's navy family
    assert contrast(p["on_accent"], p["accent"]) >= 4.5
    bright = _pal("#0B2146", "#F4AE3D")
    assert bright["accent"].lower() == "#f4ae3d"                     # a readable accent is used as-is


def test_poster_colours_are_stable_per_series():
    p = _pal("#0B2146", "#F4AE3D")
    assert ui.poster_colours(K, p) == ui.poster_colours(K, p)
    art = ui.poster(K, p, "Kingdom <Order>", "Series")
    assert "Kingdom &lt;Order&gt;" in art and 'class="mb-art-ghost" aria-hidden="true">K<' in art


def test_the_bar_marks_the_current_tab_and_sign_in_has_none():
    page = mp._shell(_biz("#0B2146"), None, "Home", "<p>x</p>", tab="home", who=ME)
    assert 'href="/my" aria-current="page"' in page and 'aria-label="Main"' in page
    assert 'href="/my/me" aria-label="Me">AR<' in page and 'class="mb-mark"' in page
    assert 'aria-label="Main"' not in mp.render_signin(_biz(), None)


# ─── Home ────────────────────────────────────────────────────────────


def _occ(eid, title, mine=None, day="2026-10-04", roles=None):
    return {"entry_id": eid, "title": title, "date": day, "date_label": "Sunday, October 4", "location": "Sanctuary",
            "capacity": None, "full": False, "roles": roles or [], "mine": mine}


ROLES = [{"id": "greet", "label": "Greeter", "needed": 2, "filled": 1, "full": False}]


def test_the_next_card_says_how_soon_and_my_answer():
    occ = [_occ("e1", "Sunday Worship", {"status": "yes", "role": "greet"}, roles=ROLES)]
    card = mpc.next_card(occ, today=date(2026, 9, 30))
    assert "Sunday Worship" in card and "in 4 days" in card and "Serving: Greeter" in card
    assert "Tomorrow" in mpc.next_card(occ, today=date(2026, 10, 3))
    assert mpc.next_card(None) == "" and mpc.next_card([]) == ""


def test_your_week_is_mine_and_never_names_other_members():
    occ = [_occ("e1", "Sunday Worship", {"status": "yes", "role": "greet"}, roles=ROLES),
           _occ("e2", "Picnic", {"status": "no"}), _occ("e3", "Prayer night")]
    groups = {"mine": [{"id": "g1", "name": "Tuesday Night Group", "kind": "Small group", "meets": "Tuesdays 7 pm",
                        "location": "", "leaders": ["Marcus"], "role": "member"},
                       {"id": "g2", "name": "Greeters", "kind": "Serving team", "meets": "Sundays",
                        "location": "", "leaders": ["Ana"], "role": "leader"}], "open": []}
    week = mpc.week_cards(occ, groups)
    assert "Sunday Worship" in week and "Serving: Greeter" in week and "Tuesday Night Group" in week
    assert "Led by Marcus" in week and "You lead" in week
    assert "Picnic" not in week and "Prayer night" not in week
    assert mpc.week_cards([], {"mine": [], "open": []}) == ""


def test_coming_up_offers_only_what_i_havent_answered():
    occ = [_occ("e1", "Sunday Worship", {"status": "yes"}), _occ("e2", "Prayer night")]
    html = mpc.coming_up(occ)
    assert "Prayer night" in html and "Sunday Worship" not in html
    assert 'class="mp-go mb-soft"' in html                            # the one filled button is Give
    assert "answered everything" in mpc.coming_up([_occ("e1", "Sunday Worship", {"status": "yes"})])
    assert "couldn't load" in mpc.coming_up(None)


def test_home_leads_with_the_greeting_next_and_latest_message():
    page = mp.render_home(_biz("#0B2146"), None, me=ME, occasions=[_occ("e1", "Sunday Worship")],
                          groups={"mine": [], "open": []}, library=_lib(), give_url="/give")
    body = page[page.index("<body>"):]
    assert "Hi, Ana" in body and 'data-first="Ana"' in body
    assert 'class="mb-main" href="/give"' in body
    assert "God&#x27;s order for families" in body and "Pastor Ana · 1 Corinthians 11:3" in body
    assert body.index('class="mb-next"') < body.index('class="mb-quick"') < body.index('id="mb-latest"')
    empty = mp.render_home(_biz(), None, me=ME, occasions=[], groups=None, library=None, give_url="")
    empty = empty[empty.index("<body>"):]
    assert "Latest message" not in empty and 'href="/give"' not in empty and 'class="mb-main"' not in empty


# ─── Me ──────────────────────────────────────────────────────────────


def test_me_shows_the_year_month_by_month_with_give_and_statement():
    gifts = [{"date": "2026-03-01", "fund": "Tithes", "amount": 40.0, "refunded": False, "method": "card"},
             {"date": "2026-03-08", "fund": "Tithes", "amount": 60.0, "refunded": False, "method": "card"}]
    page = mp.render_me(_biz("#0B2146"), None, me=ME, people=[ME], year=2025, gifts=gifts, give_url="/give",
                        this_year=2026)
    assert "$100.00" in page and "See each gift (2)" in page and "/my/statement?year=2025" in page
    bars = page[page.index('class="mb-bars"'):page.index('class="mb-months"')]
    assert bars.count("<i") == 12 and bars.count("mb-on") == 1       # a past year lights its biggest month
    assert 'style="height:100%"' in bars
    failed = mp.render_me(_biz(), None, me=ME, people=[ME], year=2026, gifts=None, give_url="", this_year=2026)
    assert "couldn't load" in failed and "$0" not in failed


# ─── Sermons ─────────────────────────────────────────────────────────


def test_the_shelf_shows_series_posters_and_loose_messages():
    page = mps.render_library(_biz("#0B2146"), None, ME, _lib())
    assert f'href="/my/sermons?series={K}"' in page and "1 message · Now" in page
    assert "More messages" in page and "Deliverance" in page and "mb-tall" in page
    assert 'href="/my/sermons" aria-current' in page


def test_a_failed_read_is_said_never_no_messages():
    page = mps.render_library(_biz(), None, ME, None)
    assert "couldn't load" in page and "No messages" not in page
    assert "No messages are posted yet" in mps.render_library(_biz(), None, ME, {"sermons": [], "series": []})


def test_one_series_and_one_message():
    series = mps.render_library(_biz(), None, ME, _lib(), K)
    assert "Kingdom Order" in series and "How God orders a life." in series and "Deliverance" not in series
    msg = mps.render_sermon(_biz(), None, ME, _lib(), S1, "/give")
    assert 'class="mb-video"' in msg and "youtube-nocookie.com/embed/abc123" in msg
    assert 'referrerpolicy="strict-origin-when-cross-origin"' in msg
    assert f'data-share="/sermons/{S1}"' in msg and 'href="/give"' in msg
    assert "For your group this week" in msg and "Order is love." in msg
    assert mps.render_sermon(_biz(), None, ME, _lib(), "44444444-4444-4444-4444-444444444444") is None
    bare = mps.render_sermon(_biz(), None, ME, _lib(), S2)
    assert "isn't posted yet" in bare and 'class="mb-art' in bare and 'href="/give"' not in bare


def test_only_published_messages_are_loaded(monkeypatch):
    rows = {"sermons": [dict(_lib()["sermons"][0]), {**_lib()["sermons"][1], "published": False}], "series": []}
    monkeypatch.setattr(mps.sb_clients, "sb_get_as_service",
                        lambda p: rows["sermons"] if p.startswith("/sermons") else rows["series"])
    lib = mps.load_library("b1")
    assert [s["id"] for s in lib["sermons"]] == [S1]
    monkeypatch.setattr(mps.sb_clients, "sb_get_as_service", lambda p: None)
    assert mps.load_library("b1") is None


def test_give_is_one_tap_from_every_signed_in_screen(monkeypatch):
    import giving_router
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: True)
    page = mp._shell(_biz("#0B2146"), None, "Groups", "<p>x</p>", tab="groups", who=ME)
    assert 'class="mb-give mp-noprint" href="/my/give" aria-label="Give"' in page
    assert 'aria-label="Give"' not in mp.render_signin(_biz(), None)     # not before sign-in
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: False)
    assert 'aria-label="Give"' not in mp._shell(_biz(), None, "Groups", "<p>x</p>", tab="groups", who=ME)


def test_the_bar_is_home_sermons_bible_groups_live_and_me_is_the_picture():
    # Kevin, 10/02: the Bible took a tab; Live moved to the end; Me is the
    # profile picture at the top.
    page = mp._shell(_biz(), None, "Live", "<p>x</p>", tab="live", who=ME)
    nav = page[page.index('aria-label="Main"'):]
    order = [nav.index(f'href="{h}"') for h in ("/my", "/my/sermons", "/my/bible", "/my/groups", "/my/live")]
    assert order == sorted(order) and 'href="/my/live" aria-current="page"' in nav and "/my/me" not in nav
    me = mp._shell(_biz(), None, "Me", "<p>x</p>", tab="me", who=ME)
    assert 'href="/my/me" aria-label="Me" aria-current="page">AR<' in me


# ─── the phone design (Kevin approved "Member App, Next Level", 2026-10-14) ──


def test_buttons_carry_white_text_in_the_churchs_own_hue_and_gold_stays_light():
    red = _pal("#C8102E", "#C8102E")
    assert red["on_fill"] == "#FFFFFF" and contrast("#FFFFFF", red["fill"]) >= 4.5
    assert contrast(red["fill"], red["ground"]) >= 3                  # the button still stands off the ground
    gold = _pal("#0B2146", "#F4AE3D")
    assert gold["fill"] == gold["accent"] and contrast(gold["on_fill"], gold["fill"]) >= 4.5


def test_the_stylesheet_fills_every_token():
    css = ui.css(_biz("#0B2146"), {"accent": "#F4AE3D"})
    assert "$" not in css and "--mb-fill:" in css and ".mb-nav{position:fixed" in css


def test_photos_are_the_churchs_own_and_never_logos_or_series_art(tmp_path, monkeypatch):
    import member_app_photos as ph
    d = tmp_path / "grace" / "assets"
    d.mkdir(parents=True)
    for name, size in (("service-wide.webp", 40000), ("logo.webp", 40000), ("series-hope.webp", 40000),
                       ("family.webp", 40000), ("tiny.webp", 500)):
        (d / name).write_bytes(b"x" * size)
    monkeypatch.setattr(ph, "SITES_DIR", tmp_path)
    ph._site_files.cache_clear()
    biz = {"settings": {"media_library": {"gallery": [
        {"url": "https://cdn.example/a.jpg", "sort_order": 2},
        {"url": "https://cdn.example/hidden.jpg", "show_on_website": False},
        {"url": "http://insecure.example/b.jpg"}]}}}
    pool = ph.photos(biz, {"slug": "grace"})
    assert pool == ["https://cdn.example/a.jpg", "/public/site-assets/grace/family.webp",
                    "/public/site-assets/grace/service-wide.webp"]
    assert ph.hero(pool).endswith("service-wide.webp") and ph.welcome(pool).endswith("family.webp")
    assert ph.pick(pool, "k1") == ph.pick(pool, "k1")                  # stable
    assert ph.pick(pool, "k1", set(pool[:2])) == pool[2]               # never twice on one screen
    assert ph.photos({}, {"slug": "../etc"}) == [] and ph.photos({}, None) == []


def test_the_verse_of_the_day_is_real_scripture_and_changes_daily():
    import member_portal_bible as mpb
    a, b = mpb.verse_of_day("kjv", date(2026, 10, 14)), mpb.verse_of_day("kjv", date(2026, 10, 15))
    assert a and b and a["label"] != b["label"] and a["href"].startswith("/my/bible/")
    card = mpb.verse_card("web", date(2026, 10, 14))
    assert "Verse of the day" in card and "WEB" in card and "Read the chapter" in card


def test_the_next_card_offers_im_coming_and_counts_without_names():
    occ = [{**_occ("e1", "Sunday Worship"), "attending": 38}]
    card = mpc.next_card(occ, today=date(2026, 10, 1))
    assert 'action="/my/rsvp"' in card and 'value="coming"' in card and "I'm coming" in card
    assert "38 people are coming" in card and "Sunday, October 4" in card
    mine = mpc.next_card([{**_occ("e1", "Sunday Worship", {"status": "yes"}), "attending": 38}], today=date(2026, 10, 1))
    assert "You and 37 others are coming" in mine and "You&#x27;re coming" in mine and 'value="coming"' not in mine


def test_a_new_church_home_has_no_empty_blocks_and_always_something_to_read():
    page = mp.render_home(_biz(), None, me=ME, occasions=[], groups={"mine": [], "open": []},
                          library={"sermons": [], "series": []}, give_url="")
    body = page[page.index("<body>"):]
    assert "Verse of the day" in body and "Start with John 1" in body and "How can we pray for you?" in body
    assert "Nothing is on the calendar" not in body and "Coming up" not in body and "Latest message" not in body
    assert 'href="/my/bible"><span>' in body and 'href="/my/live"><span>' in body   # tiles that lead somewhere


def test_home_skips_the_next_occasion_in_coming_up():
    occ = [_occ("e1", "Sunday Worship"), _occ("e2", "Prayer night")]
    page = mp.render_home(_biz(), None, me=ME, occasions=occ, groups=None, library=None, give_url="")
    coming = page[page.index('id="mp-coming"'):]
    assert "Prayer night" in coming and "Sunday Worship" not in coming


def test_empty_sermons_and_groups_get_a_designed_page_not_an_empty_list():
    s = mps.render_library(_biz(), None, ME, {"sermons": [], "series": []})
    assert "Messages are on the way" in s and 'href="/my/live"' in s and "Verse of the day" in s
    g = mpc.render_groups(_biz(), None, _req(), {"mine": [], "open": []}, who=ME)
    assert "Groups are coming" in g and "Find a group" not in g


def test_sign_in_leads_with_the_church_and_a_chat_drops_the_tab_bar():
    page = mp.render_signin(_biz(), None)
    assert 'class="mb-si"' in page and "Welcome<br>home." in page and 'class="mb-top"' not in page
    chat = mp._shell(_biz(), None, "Chat", "<p>x</p>", tab="me", who=ME, bar=False)
    assert 'aria-label="Main"' not in chat and 'class="mb-top"' in chat


def _req():
    from starlette.requests import Request
    return Request({"type": "http", "query_string": b"", "headers": [], "path": "/my/groups"})
