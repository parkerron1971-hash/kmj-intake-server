"""Tabs your members see (member_app_ui.church_tabs, 2026-10-27; Kevin:
"build it merge it", step 4 of the Church Menu Upgrade). The church office
picks which tabs the church's bar shows and in what order, the way a
Subsplash app's Manage tabs does. Home is always first, Give is always
there, five at most, only pages that exist, and nothing saved is today's
bar exactly."""
import re
from types import SimpleNamespace

import pytest

import member_app_ui as ui
import member_portal as mp

BIZ = "11111111-1111-1111-1111-111111111111"
ME = {"id": "c1", "name": "Ana Rivers", "email": "ana@example.com"}


def _biz(tabs=None, messaging=False, **portal):
    cfg = dict(portal)
    if tabs is not None:
        cfg["tabs"] = tabs
    settings = {"member_portal": cfg}
    if messaging:
        settings["messaging"] = {"enabled": True}
    return {"id": BIZ, "name": "Love City Church", "settings": settings}


def _bar(html):
    """[(href, label, current)] of the bar, in order."""
    nav = re.search(r'<nav class="mb-nav[^>]*>(.*?)</nav>', html, re.S).group(1)
    return [(m.group(1), m.group(3), bool(m.group(2)))
            for m in re.finditer(r'<a class="mb-tab" href="([^"]+)"( aria-current="page")?.*?<span>([^<]+)</span></a>', nav, re.S)]


# ─── nothing saved is today's bar ────────────────────────────────────


def test_nothing_saved_is_todays_bar_exactly():
    today = [("/my", "Home"), ("/my/sermons", "Watch"), ("/my/bible", "Bible"), ("/my/give", "Give"),
             ("/my/groups", "Connect")]
    for biz in (None, {}, _biz(), _biz(base="white"), _biz(tabs="not a bar"), _biz(tabs=7)):
        assert ui.church_tab_keys(biz) == ("home", "watch", "bible", "give", "connect")
        assert ui.church_tabs(biz) is ui.TABS
        for active in ("home", "watch", "sermons", "live", "bible", "give", "connect", "groups", "messages",
                       "events", "prayer", "news", "me", None):
            for lead in (False, True):
                assert ui.nav(active, lead=lead, biz=biz) == ui.nav(active, lead=lead)
        assert [(h, l) for h, l, _ in _bar(ui.nav("home", biz=biz))] == today
        assert "repeat(5,1fr)" in ui.nav("home", biz=biz)
    # Events, Prayer and News sit under Home, as they did.
    for page in ("events", "prayer", "news"):
        assert ui.nav(page, biz=_biz()) == ui.nav("home")
    # A leader's tab is still the sixth, last.
    led = _bar(ui.nav("home", lead=True, biz=_biz()))
    assert len(led) == 6 and led[-1][0] == "/my/lead"


def test_a_page_with_nothing_saved_looks_as_it_did():
    page = mp._shell(_biz(), None, "Coming up", "<p>x</p>", tab="events", who=ME, back=("/my", "Home"))
    assert 'class="mb-back" href="/my"' in page                      # its way back to Home
    assert ("/my", "Home", True) in _bar(page)


# ─── a saved bar ─────────────────────────────────────────────────────


def test_a_saved_order_renders_in_that_order():
    biz = _biz(["home", "events", "watch", "give", "bible"])
    bar = _bar(ui.nav("events", biz=biz))
    assert [(h, l) for h, l, _ in bar] == [("/my", "Home"), ("/my/events", "Events"), ("/my/sermons", "Watch"),
                                           ("/my/give", "Give"), ("/my/bible", "Bible")]
    assert [c for _, _, c in bar] == [False, True, False, False, False]   # Events lights itself, not Home
    assert 'data-hue="coral"' in ui.nav("events", biz=biz)
    # Connect left out: its pages light nothing, and nothing leads nowhere.
    assert not any(c for _, _, c in _bar(ui.nav("groups", biz=biz)))
    # A leader still gets Serve (or Lead) last.
    led = _bar(ui.nav("home", lead=True, biz=biz))
    assert len(led) == 6 and led[-1][0] == "/my/lead"


def test_home_first_and_give_kept_whatever_was_saved():
    assert ui.church_tab_keys(_biz(["watch", "home", "bible"])) == ("home", "watch", "bible", "give")
    assert ui.church_tab_keys(_biz([])) == ("home", "give")
    # Five at most, and Give is never the one dropped.
    assert ui.church_tab_keys(_biz(["watch", "bible", "events", "news", "prayer", "give"])) == (
        "home", "watch", "bible", "events", "give")
    assert ui.church_tab_keys(_biz(["give", "watch", "bible", "events", "news", "prayer"])) == (
        "home", "give", "watch", "bible", "events")
    assert len(_bar(ui.nav("home", biz=_biz(["watch", "bible", "events", "news", "prayer", "connect"])))) == 5


def test_unknown_keys_are_dropped():
    saved = ["home", "shop", "javascript:alert(1)", 3, None, {"key": "x"}, " Watch ", "watch", "lead", "chats"]
    assert ui.clean_tab_keys(saved) == ["home", "watch", "give"]
    assert ui.clean_tab_keys("home,watch") is None and ui.clean_tab_keys(None) is None
    html = ui.nav("home", biz=_biz(saved))
    assert "shop" not in html and "javascript" not in html and "/my/lead" not in html


def test_messages_waits_for_member_messaging():
    saved = ["home", "watch", "messages", "give"]
    assert [l for _, l, _ in _bar(ui.nav("home", biz=_biz(saved)))] == ["Home", "Watch", "Give"]
    on = _biz(saved, messaging=True)
    assert [l for _, l, _ in _bar(ui.nav("messages", biz=on))] == ["Home", "Watch", "Messages", "Give"]
    assert ("/my/messages", "Messages", True) in _bar(ui.nav("messages", biz=on))
    choices = {c["key"]: c for c in ui.tab_choices(_biz(saved))}
    assert not choices["messages"]["ready"] and choices["messages"]["waiting"]
    assert {c["key"]: c for c in ui.tab_choices(on)}["messages"]["ready"]


def test_a_page_the_church_made_a_tab_is_a_tab_page():
    biz = _biz(["home", "events", "news", "give", "messages"], messaging=True)
    page = mp._shell(biz, None, "Coming up", "<p>x</p>", tab="events", who=ME, back=("/my", "Home"))
    assert 'class="mb-back"' not in page                             # no way back to Home: it's a tab
    assert ("/my/events", "Events", True) in _bar(page)
    news = mp._shell(biz, None, "News", '<a class="mb-back" href="/my">Home</a><p>x</p>', tab="news", who=ME)
    assert 'class="mb-back"' not in news and ("/my/news", "News", True) in _bar(news)
    # Messages is in the bar, so the top has no second way to it.
    assert 'class="mb-chat-link mp-noprint" href="/my/messages"' not in page
    # A page that isn't a tab keeps its way back.
    prayer = mp._shell(biz, None, "Prayer", "<p>x</p>", tab="prayer", who=ME, back=("/my", "Home"))
    assert 'class="mb-back" href="/my"' in prayer


def test_youth_and_kids_keep_their_own_bars():
    biz = _biz(["home", "events", "give"])
    for space in ("youth", "kids"):
        for active in ("home", "events", "watch"):
            assert ui.nav(active, space=space, biz=biz) == ui.nav(active, space=space)


# ─── saving it (Settings → Member page) ──────────────────────────────


@pytest.fixture
def store(monkeypatch):
    stored = {"settings": {"member_portal": {"enabled": True, "epoch": 7, "base": "white"},
                           "giving": {"enabled": True}}, "patched": []}
    monkeypatch.setattr(mp, "_require_owner", lambda b, u: {**_biz(), "settings": dict(stored["settings"])})
    import business_sites_helpers
    monkeypatch.setattr(business_sites_helpers, "ensure_business_site",
                        lambda biz: ({"slug": "love-city", "site_config": {}}, False))
    monkeypatch.setattr(mp.sb_clients, "sb_get_as_service", lambda p: [{"settings": dict(stored["settings"])}])

    def _patch(path, body):
        stored["patched"].append(body)
        stored["settings"] = body["settings"]
        return [{"id": BIZ}]
    monkeypatch.setattr(mp.sb_clients, "sb_patch_as_service", _patch)
    return stored


def test_the_owner_saves_a_bar_and_gets_it_back(store):
    owner = SimpleNamespace(id="owner")
    out = mp.patch_member_portal_config(BIZ, {"tabs": ["home", "watch", "bible", "give", "events", "shop"]}, owner)
    assert out["tabs"] == ["home", "watch", "bible", "give", "events"]
    cfg = store["settings"]["member_portal"]
    assert cfg["tabs"] == ["home", "watch", "bible", "give", "events"]
    assert cfg["base"] == "white" and cfg["epoch"] == 7 and store["settings"]["giving"] == {"enabled": True}
    assert out["tab_limit"] == 5 and out["tabs_default"] == ["home", "watch", "bible", "give", "connect"]
    keys = [c["key"] for c in out["tab_choices"]]
    assert keys[:5] == ["home", "watch", "bible", "give", "connect"]
    assert {"events", "news", "prayer", "messages"} <= set(keys)
    locked = {c["key"]: c["locked"] for c in out["tab_choices"]}
    assert locked["home"] == "first" and locked["give"] == "always" and locked["watch"] == ""
    # Today's bar, or null, is kept as nothing saved.
    mp.patch_member_portal_config(BIZ, {"tabs": ["home", "watch", "bible", "give", "connect"]}, owner)
    assert "tabs" not in store["settings"]["member_portal"]
    mp.patch_member_portal_config(BIZ, {"tabs": ["home", "events", "give"]}, owner)
    out = mp.patch_member_portal_config(BIZ, {"tabs": None}, owner)
    assert "tabs" not in store["settings"]["member_portal"] and out["tabs"][-1] == "connect"


def test_a_bar_that_isnt_a_list_is_refused(store):
    owner = SimpleNamespace(id="owner")
    for bad in ("home,watch", {"home": 1}, 5):
        with pytest.raises(mp.HTTPException) as e:
            mp.patch_member_portal_config(BIZ, {"tabs": bad}, owner)
        assert e.value.status_code == 400
    assert not store["patched"]


def test_someone_who_isnt_the_owner_cant_save_a_bar(monkeypatch):
    monkeypatch.setattr(mp.sb_clients, "sb_get_as_service",
                        lambda p: [{"id": BIZ, "owner_id": "the-owner", "settings": {}, "type": "church"}])
    writes = []
    monkeypatch.setattr(mp.sb_clients, "sb_patch_as_service", lambda path, body: writes.append(body) or [{"id": BIZ}])
    with pytest.raises(mp.HTTPException) as e:
        mp.patch_member_portal_config(BIZ, {"tabs": ["home", "events", "give"]}, SimpleNamespace(id="someone-else"))
    assert e.value.status_code == 403 and not writes


def test_the_route_needs_a_signed_in_user():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(mp.router)
    r = TestClient(app).patch(f"/member-portal/{BIZ}", json={"tabs": ["home", "give"]})
    assert r.status_code in (401, 403)
