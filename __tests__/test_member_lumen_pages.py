# __tests__/test_member_lumen_pages.py
#
# The member app's new look ("Lumen", member_lumen_ui / member_portal_lumen),
# behind MEMBER_LUMEN (member_lumen.py). Pins:
#   - off: no Lumen class, sheet or bar; the church's base still applies;
#   - on: the Lumen sheet is linked (a hashed, immutable file), the page is
#     white whatever the church's base, the top bar of a main tab carries the
#     logo and name, the message bubble (with the unread count), the bell and
#     the picture; a pushed page gets a plain back bar; the tab bar is
#     Home · Watch · Bible · Connect · Give with Messages not a tab;
#   - the bubble's count costs no read of its own (same reads as off);
#   - Home (Look 4.1, member_lumen_home; its own pins are
#     test_member_lumen_home.py): Up next features the next gathering with
#     I'm coming, carries check-in on the day, and Live wins;
#   - Connect (/my/connect) is built from today's readers, and goes to
#     Groups when the switch is off;
#   - the bell's dot and the "I'm new here" slot are hooks that default to
#     nothing; Youth keeps its own look.

import pathlib
import re
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import member_app_ui as ui
import member_lumen
import member_portal as mp
import member_portal_church as mpc
import test_church_threads as tct
from test_church_threads import fake  # noqa: F401  (the fixture)

TODAY = date.today()


def _occ(title, d, n=0, mine=None, eid="00000000-0000-4000-8000-000000000301"):
    return {"entry_id": eid, "module_id": "m", "title": title, "date": d.isoformat(),
            "date_label": f"{d.strftime('%A, %B')} {d.day}", "location": "Sanctuary", "capacity": None,
            "attending": n, "spots_left": None, "full": False, "occasion_noun": "event", "roles": [], "mine": mine}


@pytest.fixture
def church(fake, monkeypatch):  # noqa: F811
    """Ana at a made-up church whose base is black, with an accent colour.
    She picked Light for the new look (member_lumen_look), so these pages are
    its white page; test_member_lumen_dark covers Dark, Same as my phone and
    a member who hasn't chosen (the church's base)."""
    fake.person(tct.ANA, "Ana Rivera")
    for row in fake.t["contacts"]:
        if row["id"] == tct.ANA:
            row["metadata"] = {"member_look": "light"}
    biz = fake.biz[tct.BIZ]
    biz["name"] = "Grace Fellowship"
    biz["settings"]["member_portal"]["base"] = "black"
    biz["settings"]["brand_kit"] = {"accent": "#D6246E"}
    scene = {"occ": [_occ("Sunday Worship", TODAY + timedelta(days=4), n=40),
                     _occ("Prayer Night", TODAY + timedelta(days=6), eid="00000000-0000-4000-8000-000000000302")],
             "live": {}, "checkin": {"state": "off"}}
    monkeypatch.setattr(mpc, "upcoming_for", lambda b, me: [dict(o) for o in scene["occ"]])
    import member_portal_sermons as mps
    monkeypatch.setattr(mps, "load_library", lambda b: {"sermons": [], "series": []})
    import live_router as lr
    monkeypatch.setattr(lr, "current", lambda b: scene["live"])
    import church_checkin as cc
    monkeypatch.setattr(cc, "card", lambda b, me, now=None: scene["checkin"])
    import giving_router
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: False)
    import member_portal_classes as mcl
    monkeypatch.setattr(mcl, "tab_on", lambda b, me: False)
    # Home reads the church's clock (New York here): pinned to noon today.
    from datetime import datetime, time
    from zoneinfo import ZoneInfo
    import member_portal_lumen as mlp
    monkeypatch.setattr(mlp, "church_now", lambda b: datetime.combine(TODAY, time(12, 0), tzinfo=ZoneInfo("America/New_York")))
    monkeypatch.setenv("MEMBER_LUMEN", "on")
    return scene


def _client(fake, monkeypatch, space=""):  # noqa: F811
    return tct._app(fake, monkeypatch, tct.ANA, space)


def _body_class(html):
    return re.search(r"<body( class=\"([^\"]*)\")?>", html).group(2) or ""


def test_off_is_todays_look(church, fake, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    html = _client(fake, monkeypatch).get("/my").text
    assert "lm" not in _body_class(html).split()
    assert ui.sheet_url("lumen") not in html and ui.sheet_url("app") in html
    assert 'class="lm-' not in html and "/my/connect" not in html
    assert '<meta name="theme-color" content="#000000">' in html          # the church's black base
    assert 'href="/my/groups"' in html                                     # Connect is Groups today


def test_on_links_the_sheet_and_is_white(church, fake, monkeypatch):  # noqa: F811
    html = _client(fake, monkeypatch).get("/my").text
    assert _body_class(html).split()[:2] == ["lm", "lm-tab"]
    app_at, lumen_at = html.index(ui.sheet_url("app")), html.index(ui.sheet_url("lumen"))
    assert app_at < lumen_at                                              # laid over the app's sheet
    assert '<meta name="theme-color" content="#ffffff">' in html          # white: she chose Light
    assert "--mbt-bg:#ffffff" in html
    head = html[:html.index("</head>")]
    import member_lumen_motion
    assert member_lumen_motion.JS in head                                 # listening before the first reveal
    head = head.replace(member_lumen_motion.JS, "")
    assert "lm-ind" not in head and ".lm" not in head                     # CSS only in the file


def test_the_lumen_sheet_is_a_hashed_immutable_file():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(mp.router)
    r = TestClient(app, base_url=f"https://{tct.HOST}").get(ui.sheet_url("lumen"))
    assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert "body.lm" in r.text and "lm-ind" in r.text
    assert re.fullmatch(r"/my/lumen\.[0-9a-f]{12}\.css", ui.sheet_url("lumen"))
    import custom_domain_cache
    assert custom_domain_cache.SHARED_SHEET_RE.match(ui.sheet_url("lumen"))
    # Every rule is under body.lm: the file draws nothing on another page.
    # (The page moves hang off <html>: the direction member_lumen_motion's
    # script sets on a Lumen page only, and the cinema's page colour, which
    # asks for body.lm itself.)
    import member_lumen_ui as lm
    text = re.sub(r"/\*.*?\*/", "", lm.css(), flags=re.S)
    text = re.sub(r"@keyframes[^{]*\{(?:[^{}]*\{[^}]*\})*\s*\}", "", text)
    rules = re.findall(r"(?:^|\})\s*([^{}@]+)\{", re.sub(r"@media[^{]*\{|@supports[^{]*\{", "", text))
    for sel in rules:
        for one in sel.split(","):
            one = one.strip()
            if one and not one.startswith(("::view-transition", "html:active-view-transition", "html[data-vt=",
                                           "html:has(>body.lm")):
                assert one.startswith((".lm", "body.lm")), one


def test_the_sheet_leaves_headings_their_own_colour():
    """Today's pages under the new look keep their headings' colours: a
    title on a dark card (Give before online giving) stays white."""
    import member_lumen_ui as lm
    assert not re.search(r"\.lm\s+h[1-6]\s*[,{][^}]*?color", lm.css())


def test_the_top_bar_of_a_main_tab(church, fake, monkeypatch):  # noqa: F811
    html = _client(fake, monkeypatch).get("/my").text
    top = html[html.index('<header class="mb-top">'):html.index("</header>")]
    assert 'class="mb-brand lm-brand"' in top and "Grace Fellowship" in top
    order = [top.index(s) for s in ('href="/my/messages"', 'href="/my/notifications"', 'href="/my/me"')]
    assert order == sorted(order)                                          # bubble, bell, picture
    assert "lm-bdot" not in top                                            # the bell's dot waits for its list


def test_the_bubble_counts_unread_without_a_read_of_its_own(church, fake, monkeypatch):  # noqa: F811
    import member_portal_threads as mpt
    fake.note(contact_id=None, kind="announcements", title="Grace Fellowship", body="See you Sunday")
    c = _client(fake, monkeypatch)
    c.get("/my")                                                            # warm what's kept
    fake.gets.clear()
    on = c.get("/my").text
    reads_on = list(fake.gets)
    top = on[on.index('<header class="mb-top">'):on.index("</header>")]
    assert re.search(r'aria-label="Messages, (\d+) new"', top)
    assert 'class="lm-cnt"' in top
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    c.get("/my")
    fake.gets.clear()
    c.get("/my")
    reads_off = list(fake.gets)
    from collections import Counter
    extra = Counter(r.split("?")[0] for r in reads_on) - Counter(r.split("?")[0] for r in reads_off)
    assert not extra, extra


def test_the_tab_bar(church, fake, monkeypatch):  # noqa: F811
    html = _client(fake, monkeypatch).get("/my").text
    nav = html[html.index('<nav class="mb-nav lm-nav'):]
    nav = nav[:nav.index("</nav>")]
    labels = re.findall(r'<a class="mb-tab" href="([^"]+)"[^>]*>.*?<span>([^<]+)</span>', nav)
    assert labels == [("/my", "Home"), ("/my/sermons", "Watch"), ("/my/bible", "Bible"),
                      ("/my/connect", "Connect"), ("/my/give", "Give")]
    assert "Messages" not in nav
    assert 'style="--n:5;--i:0"' in nav and 'class="lm-ind"' in nav
    assert re.search(r'href="/my" aria-current="page"', nav)
    # The early loading and the cross-fade still find it.
    assert ui.EARLY_JS in html


def test_a_pushed_page_gets_a_back_bar(church, fake, monkeypatch):  # noqa: F811
    fake.biz[tct.BIZ]["settings"]["messaging"] = {"enabled": True}
    html = _client(fake, monkeypatch).get("/my/messages").text
    assert _body_class(html).split()[:2] == ["lm", "lm-push"]
    top = html[html.index('<header class="mb-top">'):html.index("</header>")]
    assert 'class="mb-back" href="/my" data-back' in top and "Back" in top
    assert "/my/notifications" not in top and "lm-brand" not in top
    assert "<em>Messages</em>" in html and 'aria-label="Connect"' not in html   # no Connect tabs
    nav = html[html.index('<nav class="mb-nav lm-nav'):]
    assert "aria-current" not in nav[:nav.index("</nav>")]                       # Messages sits over no tab


def _up(html):
    up = html[html.index('class="lm-up"'):]
    return up[:up.index("</section>")]


def test_home_leads_with_the_next_gathering(church, fake, monkeypatch):  # noqa: F811
    html = _client(fake, monkeypatch).get("/my").text
    up = _up(html)
    assert '<h3 class="lm-f4t" id="lm-f4-t">Sunday Worship</h3>' in up
    assert f'<p class="lm-f4k">This {(TODAY + timedelta(days=4)):%A}</p>' in up
    assert 'action="/my/rsvp"' in up and "I&#x27;m coming" in up
    assert "<b>40</b> going" in up
    assert "Coming up" in html and "Prayer Night" in html
    assert 'class="lm-page"' in html and "Verse of the day" in html          # the ivory verse card
    assert "How can we pray for you?" in html
    assert 'class="lm-ck"' not in html and 'action="/my/here"' not in html  # check-in is off


def test_home_on_the_day_says_today_and_shows_check_in(church, fake, monkeypatch):  # noqa: F811
    from datetime import datetime, timezone
    church["occ"][0] = _occ("Sunday Worship", TODAY, n=40)
    church["checkin"] = {"state": "open", "w": {"start": datetime.now(timezone.utc), "open": True, "day": TODAY},
                         "occasion": {"id": "o", "title": "Sunday Worship"}, "marks": {}, "settings": {},
                         "family": [{"id": tct.ANA, "name": "Ana Rivera", "me": True}]}
    html = _client(fake, monkeypatch).get("/my").text
    up = _up(html)
    assert '<p class="lm-f4k">Today · ' in up and "Sunday Worship" in up
    assert 'action="/my/here"' in up and 'name="where" value="in"' in up and 'name="where" value="online"' in up
    assert f'name="people" value="{tct.ANA}"' in up


def test_home_while_live(church, fake, monkeypatch):  # noqa: F811
    church["live"] = {"id": "l1", "title": "Sunday Worship"}
    html = _client(fake, monkeypatch).get("/my").text
    up = _up(html)
    assert "Live now" in up and '<a class="lm-btn sm" href="/my/live" aria-describedby="lm-f4-t">Join the room</a>' in up


def test_connect_is_the_people_hub(church, fake, monkeypatch):  # noqa: F811
    fake.add("groups", id=tct.GROUP, business_id=tct.BIZ, name="Young Adults", active=True, kind="small_group",
             meets="Thursdays, 7:00 PM", location="The Johnsons' home", join_mode="ask")
    fake.add("group_members", group_id=tct.GROUP, business_id=tct.BIZ, contact_id=tct.ANA, role="member")
    html = _client(fake, monkeypatch).get("/my/connect").text
    assert _body_class(html).split()[:2] == ["lm", "lm-tab"]
    # Look 5.1 (member_lumen_connect): the title and who it's about, your groups, prayer, More's Events row.
    assert '<h1 class="lm-ctt">Connect</h1>' in html and "Your people at " in html
    for s in ("Your groups", "Young Adults", "Prayer", "Ask for prayer", "Events"):
        assert s in html, s
    nav = html[html.index('<nav class="mb-nav lm-nav'):]
    assert 'href="/my/connect" aria-current="page"' in nav


def test_connect_without_the_new_look_is_groups(church, fake, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    r = _client(fake, monkeypatch).get("/my/connect", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my/groups"


def test_groups_is_pushed_from_connect(church, fake, monkeypatch):  # noqa: F811
    html = _client(fake, monkeypatch).get("/my/groups").text
    top = html[html.index('<header class="mb-top">'):html.index("</header>")]
    assert 'href="/my/connect"' in top and "Connect" in top
    assert "Find a <em>group</em>" in html


def test_the_hooks(church, fake, monkeypatch):  # noqa: F811
    monkeypatch.setattr(member_lumen, "bell_dot", lambda biz, me: True)
    monkeypatch.setattr(member_lumen, "new_here_card", lambda biz, me: '<div class="nh-card">New here</div>')
    c = _client(fake, monkeypatch)
    home = c.get("/my").text
    assert 'class="lm-bdot"' in home and "Alerts, something new" in home
    conn = c.get("/my/connect").text
    assert '<div class="lm-newslot"><div class="nh-card">New here</div></div>' in conn


def test_the_bell_is_asked_only_for_the_new_look(church, fake, monkeypatch):  # noqa: F811
    asked = []
    monkeypatch.setattr(member_lumen, "bell_dot", lambda biz, me: asked.append(me["id"]) or False)
    c = _client(fake, monkeypatch)
    c.get("/my")
    assert asked == [tct.ANA]
    monkeypatch.setenv("MEMBER_LUMEN", "off")
    c.get("/my")
    assert asked == [tct.ANA]


def test_the_hooks_default_to_nothing():
    assert member_lumen.bell_dot({"id": "b"}, {"id": "m"}) is False
    assert member_lumen.new_here_card({"id": "b"}, {"id": "m"}) == ""


def test_youth_keeps_its_own_look(church, fake, monkeypatch):  # noqa: F811
    html = _client(fake, monkeypatch, space="youth").get("/my").text
    assert "lm" not in _body_class(html).split() and ui.sheet_url("lumen") not in html


def test_base_of_is_white_only_on_a_lumen_page(church, fake, monkeypatch):  # noqa: F811
    biz = fake.business()
    assert ui.base_of(biz) == "black"                                       # no page being drawn
