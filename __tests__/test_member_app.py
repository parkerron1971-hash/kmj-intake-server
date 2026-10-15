"""The member app ("Member App, Top Tier", 2026-10-15: a neutral base with
the church colour as the accent): the palette, Home, Watch, Me, and the bar."""
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
    assert "Kingdom &lt;Order&gt;" in art and 'class="mb-art-kick">Series<' in art


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
    assert "Sunday Worship" in card and "In 4 days" in card and "Serving: Greeter" in card
    assert "Tomorrow" in mpc.next_card(occ, today=date(2026, 10, 3))
    assert mpc.next_card(None) == "" and mpc.next_card([]) == ""




def test_coming_up_offers_only_what_i_havent_answered():
    occ = [_occ("e1", "Sunday Worship", {"status": "yes"}), _occ("e2", "Prayer night")]
    html = mpc.coming_up(occ)
    assert "Prayer night" in html and "Sunday Worship" not in html
    assert 'class="mp-go mb-soft"' in html                            # the one filled button is Give
    assert "answered everything" in mpc.coming_up([_occ("e1", "Sunday Worship", {"status": "yes"})])
    assert "couldn't load" in mpc.coming_up(None)


def test_home_leads_with_the_greeting_next_and_latest_message():
    page = mp.render_home(_biz("#0B2146"), None, me=ME, occasions=[_occ("e1", "Sunday Worship")],
                          groups={"mine": [], "open": []}, library=_lib(), give_url="/my/give")
    body = page[page.index("<body>"):]
    assert "Hi, <em>Ana.</em>" in body and 'data-first="Ana"' in body
    assert "God&#x27;s order for families" in body and "Kingdom Order · Pastor Ana · September 27, 2026" in body
    assert body.index('class="mb-hero"') < body.index('class="mb-quick"') < body.index('id="mb-latest"')
    empty = mp.render_home(_biz(), None, me=ME, occasions=[], groups=None, library=None, give_url="")
    empty = empty[empty.index("<body>"):]
    assert "Latest message" not in empty and "Welcome home" in empty     # the church itself leads


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




def test_a_failed_read_is_said_never_no_messages():
    page = mps.render_library(_biz(), None, ME, None)
    assert "couldn't load" in page and "No messages" not in page
    assert "Messages are on the way" in mps.render_library(_biz(), None, ME, {"sermons": [], "series": []})


def test_one_series_and_one_message():
    series = mps.render_library(_biz(), None, ME, _lib(), K)
    assert "Kingdom Order" in series and "How God orders a life." in series and "Deliverance" not in series
    msg = mps.render_sermon(_biz(), None, ME, _lib(), S1, "/give")
    assert 'class="mb-video"' in msg and "youtube-nocookie.com/embed/abc123" in msg
    assert 'referrerpolicy="strict-origin-when-cross-origin"' in msg
    assert f'data-share="/sermons/{S1}"' in msg and 'href="/give"' in msg
    assert "Talk it over this week" in msg and "Order is love." in msg
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
    assert "38 people are coming" in card and "Sunday, October 4 · Sanctuary" in card and "In 3 days" in card
    mine = mpc.next_card([{**_occ("e1", "Sunday Worship", {"status": "yes"}), "attending": 38}], today=date(2026, 10, 1))
    assert "You and 37 others are coming" in mine and "You&#x27;re coming" in mine and 'value="coming"' not in mine


def test_a_new_church_home_has_no_empty_blocks_and_always_something_to_read():
    page = mp.render_home(_biz(), None, me=ME, occasions=[], groups={"mine": [], "open": []},
                          library={"sermons": [], "series": []}, give_url="")
    body = page[page.index("<body>"):]
    assert "Verse of the day" in body and "Start with John 1" in body and "How can we pray for you?" in body
    assert "Nothing is on the calendar" not in body and "Latest message" not in body and "This week" not in body
    quick = body[body.index('class="mb-quick"'):]
    assert 'href="/my/prayer"' in quick and 'href="/my/live"' in quick     # tiles that lead somewhere




def test_empty_sermons_and_groups_get_a_designed_page_not_an_empty_list():
    s = mps.render_library(_biz(), None, ME, {"sermons": [], "series": []})
    assert "Messages are on the way" in s and 'href="/my/live"' in s and "Verse of the day" in s
    g = mpc.render_groups(_biz(), None, _req(), {"mine": [], "open": []}, who=ME)
    assert "Groups are coming" in g and "Find a group" not in g


def test_sign_in_leads_with_the_church_and_a_chat_drops_the_tab_bar():
    page = mp.render_signin(_biz(), None)
    assert 'class="si-first"' in page and "Welcome home." in page and 'class="mb-top"' not in page
    chat = mp._shell(_biz(), None, "Chat", "<p>x</p>", tab="me", who=ME, bar=False)
    assert 'aria-label="Main"' not in chat and 'class="mb-top"' in chat


def _req():
    from starlette.requests import Request
    return Request({"type": "http", "query_string": b"", "headers": [], "path": "/my/groups"})


def test_the_base_is_neutral_and_the_church_colour_is_the_accent():
    # Kevin, 2026-10-15: "colors being the church site should be an accent
    # and we have the primary pick black, white, or gray".
    for base, b in ui.BASES.items():
        for brand in ("#C8102E", "#2F8F5B", "#0B2146", "#C2125F"):
            biz = {"id": "b1", "settings": {"brand_kit": {"colors": {"primary": brand}}, "member_portal": {"base": base}}}
            p = ui.palette(biz, {})
            assert p["ground"] == b["bg"] and p["base"] == base           # the same neutral for every church
            assert contrast(p["text"], p["ground"]) >= 12
            assert contrast(p["muted"], p["ground"]) >= 4.5 and contrast(p["dim"], p["ground"]) >= 4.5
            assert contrast(p["accent"], p["ground"]) >= 4.5                # the church colour, readable
            assert abs(_hue(p["accent"]) - _hue(brand)) < 15 or abs(_hue(p["accent"]) - _hue(brand)) > 345
            assert contrast(p["on_fill"], p["fill"]) >= 4.5
    assert ui.palette(_biz("#C8102E"), {})["base"] == "black"              # the default, and Love City's pick
    odd = {"id": "b1", "settings": {"member_portal": {"base": "purple"}}}
    assert ui.base_of(odd) == "black"


def test_a_church_with_no_colour_gets_a_neutral_accent():
    p = ui.palette({"id": "b1", "settings": {}}, {"accent": "#555555"})
    assert ui.brand_colour({"id": "b1", "settings": {}}, {"accent": "#555555"}) is None
    r, g, b = (int(p["accent"][i:i + 2], 16) for i in (1, 3, 5))
    assert max(r, g, b) - min(r, g, b) < 12                               # gray, not a made-up colour


def test_this_week_shows_whats_on_and_never_names_other_members():
    occ = [_occ("e1", "Sunday Worship", {"status": "yes", "role": "greet"}, roles=ROLES),
           _occ("e2", "Picnic", {"status": "no"}), _occ("e3", "Prayer night")]
    groups = {"mine": [{"id": "g1", "name": "Tuesday Night Group", "kind": "Small group", "meets": "Tuesdays 7 pm",
                        "location": "", "leaders": ["Marcus"], "role": "member"},
                       {"id": "g2", "name": "Greeters", "kind": "Serving team", "meets": "Sundays",
                        "location": "", "leaders": ["Ana"], "role": "leader"}], "open": []}
    week = mpc.week_cards(occ, groups)
    assert "Sunday Worship" in week and "Serving: Greeter" in week and "Tuesday Night Group" in week
    assert "Led by Marcus" in week and "You lead" in week and "Prayer night" in week
    assert 'href="/my/events">Calendar<' in week                          # the section's "See all"
    assert mpc.week_cards([], {"mine": [], "open": []}) == ""


def test_watch_leads_with_live_then_the_latest_series_and_every_message():
    page = mps.render_library(_biz("#0B2146"), None, ME, _lib())
    assert f'href="/my/sermons?series={K}"' in page and "1 message" in page
    assert "All messages" in page and "Deliverance" in page and "Next live" in page
    assert 'href="/my/sermons" aria-current' in page                      # the Watch tab
    live = mps.render_library(_biz(), None, ME, _lib(), live={"id": "s1", "title": "Sunday <Worship>"})
    assert 'class="mb-livecard is-live"' in live and "Sunday &lt;Worship&gt;" in live


def test_give_is_a_tab_when_the_church_takes_gifts(monkeypatch):
    # Kevin, 2026-10-15: Give stays at the bottom like the design, gifts
    # in the app or not.
    import giving_router
    for active in (True, False):
        monkeypatch.setattr(giving_router, "giving_is_active", lambda b, a=active: a)
        page = mp._shell(_biz("#0B2146"), None, "Groups", "<p>x</p>", tab="groups", who=ME)
        nav = page[page.index('aria-label="Main"'):]
        assert 'href="/my/give"' in nav and "repeat(5,1fr)" in page
    assert 'href="/my/give"' not in mp.render_signin(_biz(), None)        # not before sign-in


def test_the_bar_is_home_watch_bible_give_connect_and_me_is_the_picture(monkeypatch):
    # The Subsplash app's five tabs, in plainer words (Kevin approved
    # "Member App, Top Tier", 2026-10-15). Live sits under Watch; Me is
    # the picture at the top.
    import giving_router
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: True)
    page = mp._shell(_biz(), None, "Live", "<p>x</p>", tab="live", who=ME)
    nav = page[page.index('aria-label="Main"'):]
    order = [nav.index(f'href="{h}"') for h in ("/my", "/my/sermons", "/my/bible", "/my/give", "/my/groups")]
    assert order == sorted(order) and 'href="/my/sermons" aria-current="page"' in nav and "/my/me" not in nav
    assert "/my/live" not in nav
    me = mp._shell(_biz(), None, "Me", "<p>x</p>", tab="me", who=ME)
    assert 'href="/my/me" aria-label="Me" aria-current="page">AR<' in me


def test_this_week_skips_the_gathering_home_leads_with():
    occ = [_occ("e1", "Sunday Worship"), _occ("e2", "Prayer night")]
    page = mp.render_home(_biz(), None, me=ME, occasions=occ, groups=None, library=None, give_url="")
    week = page[page.index('id="mb-week"'):]
    assert "Prayer night" in week and "Sunday Worship" not in week


def test_the_churchs_own_tiles_lead_home_and_are_checked():
    tiles = mpc.clean_tiles([
        {"title": "Fast & Prayer Live", "sub": "Weeknights 6 AM", "href": "/watch"},
        {"title": "City Store", "href": "https://lovecity.printify.me/", "photo": "https://cdn.example/s.jpg"},
        {"title": "", "href": "/x"}, {"title": "Bad", "href": "javascript:alert(1)"},
        {"title": "Also bad", "href": "//evil.example"}, "nope",
        {"title": "Odd photo", "href": "/", "photo": "javascript:x"}])
    assert [t["title"] for t in tiles] == ["Fast & Prayer Live", "City Store", "Odd photo"]
    assert tiles[2]["photo"] == "" and mpc.clean_tiles("x") is None
    biz = {**_biz(), "name": "Love City Church", "settings": {"member_portal": {"tiles": tiles}}}
    html = mpc.home_tiles(biz, None, [])
    assert "At Love City" in html and "Fast &amp; Prayer Live" in html
    assert 'href="https://lovecity.printify.me/" target="_blank" rel="noopener"' in html
    default = mpc.home_tiles(_biz(), None, [])
    assert 'href="/my/groups"' in default and 'href="/my/events"' in default and 'href="/my/prayer"' in default


def test_connect_puts_groups_and_messages_under_one_title(monkeypatch):
    import member_portal_messaging as mpm
    monkeypatch.setattr(mpm, "turned_on", lambda b: True)
    g = mpc.render_groups(_biz(), None, _req(), {"mine": [], "open": []}, who=ME)
    assert "<h1>Connect</h1>" in g and 'href="/my/groups" aria-current="page"' in g and 'href="/my/messages"' in g
    monkeypatch.setattr(mpm, "turned_on", lambda b: False)
    assert 'class="mb-seg"' not in mpc.render_groups(_biz(), None, _req(), {"mine": [], "open": []}, who=ME)


def test_a_page_back_link_moves_into_the_bar():
    page = mp._shell(_biz(), None, "Chapter", '<a class="mb-back" href="/my/bible?x=1&amp;y=2"><svg></svg>Bible</a><p>text</p>',
                     tab="bible", who=ME)
    top = page[page.index('class="mb-top"'):page.index("</header>")]
    assert 'href="/my/bible?x=1&amp;y=2"' in top and "Bible</a>" in top
    assert page.count('class="mb-back"') == 1


def test_before_online_giving_the_give_tab_says_how_to_give(tmp_path, monkeypatch):
    import member_app_photos as ph
    page = mp.render_give_off(_biz(), None, ME)
    assert "<h1>Give</h1>" in page and "In person" in page and 'href="/my/me#mp-giving"' in page
    assert 'href="/give"' not in page and "Sample" not in page              # no site page to send them to
    assert 'class="mb-tab" href="/my/give" aria-current="page"' in page
    (tmp_path / "grace" / "assets").mkdir(parents=True)
    (tmp_path / "grace" / "give.html").write_text("<p>give</p>")
    monkeypatch.setattr(ph, "SITES_DIR", tmp_path)
    ph._site_files.cache_clear()
    own = mp.render_give_off(_biz(), {"slug": "grace"}, ME)
    assert 'href="/give"' in own and "Give online" in own                  # the church's own give page
    preview = mp.render_give_off(_biz(), None, ME, preview=True)
    assert "Operate, Payments" in preview
