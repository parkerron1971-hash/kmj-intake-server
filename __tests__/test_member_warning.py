"""The member warning: "Pastor will never ask you for gift cards." Off by
default; the church's own words with its pastor's name; a Give-page line
only when the church turns it on; Chief offers it only on a turn about
scams at a church that hasn't sent one."""
import copy
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import member_warning as MW
import sb_clients

BIZ = "11111111-1111-4111-8111-111111111111"
OWNER = "aaaaaaaa-1111-4111-8111-111111111111"
VIEWER = "aaaaaaaa-2222-4222-8222-222222222222"


def church(**settings):
    return {"id": BIZ, "name": "First Light Church", "type": "church", "owner_id": OWNER,
            "stripe_account_id": "acct_123",
            "settings": {"giving": {"enabled": True, "funds": ["General"]}, **settings}}


@pytest.fixture(autouse=True)
def pastor(monkeypatch):
    import member_pastor
    monkeypatch.setattr(member_pastor, "who", lambda b: {"name": "James Carter", "title": "Senior Pastor"})


def test_off_by_default_and_no_give_line():
    b = church()
    s = MW.settings_of(b)
    assert s == {"on": False, "pastor": "", "give_line": False, "sent_at": None, "sent_by": "", "sent": []}
    assert MW.give_line_html(b) == ""
    # Turned on but the Give line not chosen: still nothing on the Give page.
    assert MW.give_line_html(church(member_warning={"on": True})) == ""


def test_the_words_are_filled_with_the_pastors_name():
    w = MW.words("Pastor James", "First Light Church")
    assert w["title"] == "Pastor James will never ask you for gift cards"
    assert "If someone does, it isn't Pastor James. Tell the office." in w["text"]
    assert "give only on our own Give page or in person" in w["news"]
    assert len(w["app_title"]) <= MW.APP_TITLE_MAX and len(w["app_body"]) <= MW.APP_BODY_MAX
    assert MW.pastor_of(church()) == "Pastor James"                      # the senior role's, suggested
    assert MW.pastor_of(church(member_warning={"pastor": "Pastor Kev"})) == "Pastor Kev"
    plain = MW.words("Our pastor", "First Light Church")
    assert "it isn't our pastor" in plain["text"]


def test_the_give_line_is_escaped_and_on_every_give_page(monkeypatch):
    import giving_router
    import giving_ways
    monkeypatch.setattr(giving_ways, "switched_on", lambda bid: True)
    monkeypatch.setattr(giving_router, "_schedule_wallet_domains", lambda biz: None)
    monkeypatch.setattr(giving_router, "ensure_business_site", lambda biz: ({"slug": "first-light"}, False))
    b = church(member_warning={"on": True, "give_line": True, "pastor": "Pastor <b>Jim</b>"})
    line = MW.give_line_html(b)
    assert "Pastor &lt;b&gt;Jim&lt;/b&gt; will never ask you to give by text, email or gift card." in line
    assert "<b>Jim" not in line
    page = giving_router.render_give_page(b, "https://x/give", "first-light", api_origin="https://api.example")
    embed = giving_router.render_give_embed(b, "first-light", api_origin="https://api.example")
    app = giving_router.render_give_page(b, "https://x/my/give", "first-light", api_origin="https://api.example",
                                         app={"head": "", "top": "<header>Give</header>", "name": "", "email": ""})
    for html in (page, embed, app):
        assert 'class="gv-safe"' in html
    off = church()
    assert 'class="gv-safe"' not in giving_router.render_give_page(off, "https://x/give", "first-light",
                                                                     api_origin="https://api.example")


# ─── The routes ───────────────────────────────────────────────────────

@pytest.fixture
def office(monkeypatch):
    import auth_supabase
    import business_access
    import business_settings
    state = SimpleNamespace(biz=church(), merges=[])

    def get(path, **kw):
        if path.startswith("/businesses?"):
            return [copy.deepcopy(state.biz)]
        return []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)

    def merge(bid, set=None, drop=(), under=()):
        state.merges.append(set)
        state.biz["settings"] = {**state.biz["settings"], **(set or {})}
        return copy.deepcopy(state.biz["settings"])
    monkeypatch.setattr(business_settings, "merge", merge)
    who = SimpleNamespace(id=OWNER, email="office@firstlight.org")
    monkeypatch.setattr(business_access, "_resolve_role", lambda b, u: {OWNER: "manager", VIEWER: "viewer"}.get(u))
    app = FastAPI()
    app.include_router(MW.router)
    app.dependency_overrides[auth_supabase.require_user_session] = lambda: SimpleNamespace(user=who, token="t")
    state.client, state.who = TestClient(app), who
    return state


def test_the_office_reads_and_saves_its_choice(office):
    got = office.client.get(f"/church/member-warning?business_id={BIZ}").json()
    assert got["on"] is False and got["suggested_pastor"] == "Pastor James"
    assert got["words"]["title"].startswith("Pastor James")
    r = office.client.put(f"/church/member-warning?business_id={BIZ}",
                          json={"on": True, "pastor": "Pastor Kev", "give_line": True})
    assert r.status_code == 200 and r.json()["pastor"] == "Pastor Kev" and r.json()["give_line"] is True
    assert r.json()["words"]["text"].startswith("Pastor Kev will never")
    r = office.client.put(f"/church/member-warning?business_id={BIZ}", json={"sent": ["news", "app", "bogus"]})
    assert r.json()["sent"] == ["app", "news"] and r.json()["sent_at"] and r.json()["sent_by"] == "office"
    assert office.client.put(f"/church/member-warning?business_id={BIZ}",
                             json={"pastor": "x" * 41}).status_code == 400
    assert office.client.put(f"/church/member-warning?business_id={BIZ}",
                             json={"pastor": "<script>"}).status_code == 400
    # A body that isn't an object changes nothing.
    n = len(office.merges)
    assert office.client.put(f"/church/member-warning?business_id={BIZ}", json=["on"]).status_code == 200
    assert office.merges[-1]["member_warning"]["pastor"] == "Pastor Kev" and len(office.merges) == n + 1


def test_a_viewer_and_a_business_that_isnt_a_church_get_nothing(office):
    office.who.id = VIEWER
    assert office.client.get(f"/church/member-warning?business_id={BIZ}").status_code == 404
    office.who.id = OWNER
    office.biz["type"] = "coach"
    assert office.client.get(f"/church/member-warning?business_id={BIZ}").status_code == 404


# ─── Chief ────────────────────────────────────────────────────────────

def test_chief_offers_it_only_on_a_turn_about_scams():
    b = church()
    assert MW.turn_line(b, OWNER, "How do I record Sunday's offering?") == ""
    line = MW.turn_line(b, OWNER, "Someone is texting our members pretending to be the pastor asking for gift cards")
    assert line.startswith("MEMBER WARNING") and '"type":"navigate"' in line and "Never say it was sent" in line
    assert MW.turn_line(church(member_warning={"sent_at": "2026-11-27T10:00:00Z"}), OWNER, "is this a scam?") == ""
    assert MW.turn_line({**b, "type": "coach"}, OWNER, "is this a scam?") == ""
    assert MW.turn_line(b, "", "is this a scam?") == ""
