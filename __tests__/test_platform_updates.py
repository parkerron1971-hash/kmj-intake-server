"""What's New from the database (platform_updates.py): who an update is for,
how the card ranks, a church's own words, seen-state per login, and the
Mission Control queue with its wording warnings."""
import copy
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import platform_updates as PU
import sb_clients

BIZ = "11111111-1111-4111-8111-111111111111"
OWNER = "aaaaaaaa-1111-4111-8111-111111111111"
SEAT = "aaaaaaaa-2222-4222-8222-222222222222"
TODAY = "2026-11-27"


def up(id_, date="2026-11-20", **kw):
    row = {"id": id_, "date": date, "status": "published", "area": "Operate", "page": None, "kinds": [],
           "areas": [], "roles": [], "weight": "normal", "group_key": None, "title": f"Title {id_}",
           "line": f"Line {id_}", "body": f"Body {id_}", "church_title": None, "church_line": None,
           "church_body": None, "tour": []}
    row.update(kw)
    return row


def viewer(**kw):
    base = dict(kind="coach", church=False, role="owner", areas=None, joined="2026-08-01")
    base.update(kw)
    return PU.Viewer(**base)


# ─── Who an update is for ────────────────────────────────────────────────

def test_kinds_roles_areas_and_the_day_they_joined():
    church_only = up("2026-11-20-a", kinds=["ministry"])
    owner_only = up("2026-11-20-b", roles=["owner"])
    giving = up("2026-11-20-c", areas=["giving_money"])
    old = up("2026-07-01-d", date="2026-07-01")
    coach = viewer()
    assert not PU.shown_to(church_only, coach)
    assert PU.shown_to(church_only, viewer(kind="ministry", church=True))
    assert PU.shown_to(owner_only, coach)
    assert not PU.shown_to(owner_only, viewer(role="admin"))       # an admin seat isn't told about the bill
    assert PU.shown_to(giving, coach)                               # areas only narrow a church office login
    office = viewer(kind="ministry", church=True, role="manager", areas=["people_care"])
    assert not PU.shown_to(giving, office)
    assert PU.shown_to(giving, viewer(kind="ministry", church=True, role="manager", areas=["giving_money"]))
    assert not PU.shown_to(old, coach)                              # dated before they joined
    assert not PU.shown_to(up("2026-08-01-e", date="2026-08-01"), coach)   # the day itself too


def test_drafts_and_archived_never_show_and_a_group_shows_once():
    rows = [up("2026-11-27-phone-3", date="2026-11-27", group_key="chief-phone"),
            up("2026-11-26-phone-2", date="2026-11-26", group_key="chief-phone"),
            up("2026-11-25-draft", date="2026-11-25", status="draft"),
            up("2026-11-24-gone", date="2026-11-24", status="archived"),
            up("2026-11-23-other", date="2026-11-23")]
    got = [e["id"] for e in PU.for_viewer(rows, viewer())]
    assert got == ["2026-11-27-phone-3", "2026-11-23-other"]


def test_the_card_ranks_for_this_login_and_skips_what_they_saw():
    rows = [up("2026-11-27-everyone", date="2026-11-27"),
            up("2026-11-26-small", date="2026-11-26", weight="small"),
            up("2026-11-20-for-churches", kinds=["ministry"], page="operate:contacts"),
            up("2026-11-21-big", date="2026-11-21", weight="big", page="operate:news"),
            up("2026-11-22-used", date="2026-11-22", page="operate:serving"),
            up("2026-10-01-too-old", date="2026-10-01", kinds=["ministry"], weight="big")]
    pastor = viewer(kind="ministry", church=True, pages=["operate:serving"])
    ids = [e["id"] for e in PU.card(rows, pastor, TODAY)]
    assert ids == ["2026-11-20-for-churches", "2026-11-21-big", "2026-11-22-used"]
    pastor.seen = {"2026-11-20-for-churches"}
    ids = [e["id"] for e in PU.card(rows, pastor, TODAY)]
    assert ids == ["2026-11-21-big", "2026-11-22-used", "2026-11-27-everyone"]
    # Nothing from before the last 30 days is ever on the card.
    assert "2026-10-01-too-old" not in [e["id"] for e in PU.card(rows, viewer(kind="ministry", church=True), TODAY)]


def test_a_church_reads_its_own_words_and_a_business_never_does():
    e = up("2026-11-27-chief-phone", title="Chief on your phone", line="Between jobs, ask Chief.",
           church_line="At the hospital or between visits, ask Chief.",
           tour=[{"text": "Ask looks things up.", "church_text": "Ask finds who's been missing."}])
    church = PU.shape(e, viewer(kind="ministry", church=True), TODAY)
    biz = PU.shape(e, viewer(), TODAY)
    assert church["line"].startswith("At the hospital") and church["title"] == "Chief on your phone"
    assert biz["line"] == "Between jobs, ask Chief."
    assert church["tour"] == [{"text": "Ask finds who's been missing."}]
    assert biz["tour"] == [{"text": "Ask looks things up."}]
    assert church["new"] is True and church["seen"] is False


def test_why_it_was_picked_is_plain():
    v = viewer(kind="ministry", church=True, pages=["operate:news"])
    assert PU._why(up("2026-11-20-a", roles=["owner"]), v) == "For the account owner"
    assert PU._why(up("2026-11-20-b", page="operate:news"), v) == "On a page you use"
    assert PU._why(up("2026-11-20-c", page="operate:contacts"), v) == "Where you work lately"
    assert PU._why(up("2026-11-20-d", kinds=["ministry"]), v) == "Made for churches"
    assert PU._why(up("2026-11-20-e", kinds=["coach"]), viewer()) == "Made for businesses like yours"
    assert PU._why(up("2026-11-20-f", page="build:settings"), v) == "New for everyone"


# ─── The routes ──────────────────────────────────────────────────────────

@pytest.fixture
def app(monkeypatch):
    import auth_supabase
    import business_access
    st = SimpleNamespace(rows=[up("2026-11-27-everyone", date="2026-11-27"),
                               up("2026-11-26-churches", date="2026-11-26", kinds=["ministry"],
                                  church_line="For the church office."),
                               up("2026-11-25-owner", date="2026-11-25", roles=["owner"]),
                               up("2026-11-01-older", date="2026-11-01"),
                               up("2026-11-20-draft", status="draft")],
                         seen=set(), posts=[], patches=[], biz={"id": BIZ, "name": "Grace Street", "type": "church",
                                                                "owner_id": OWNER, "created_at": "2026-08-10T00:00:00Z"},
                         seen_fails=False, seat_fails=False)

    def get(path, **kw):
        if path.startswith("/businesses?"):
            return [copy.deepcopy(st.biz)]
        if path.startswith("/business_users?"):
            return None if st.seat_fails else [{"accepted_at": "2026-11-02T00:00:00Z"}]
        if path.startswith("/platform_updates?id=eq."):
            uid = path.split("id=eq.")[1].split("&")[0]
            return [copy.deepcopy(r) for r in st.rows if r["id"] == uid]
        if path.startswith("/platform_updates?"):
            return [copy.deepcopy(r) for r in st.rows if "status=eq.draft" not in path or r["status"] == "draft"]
        return []

    def get_all(path, **kw):
        if path.startswith("/platform_updates?"):
            return [copy.deepcopy(r) for r in st.rows if r["status"] == "published"]
        if path.startswith("/platform_update_seen?"):
            if st.seen_fails:
                raise sb_clients.PartialRead("first page failed")
            return [{"update_id": i} for i in sorted(st.seen)]
        return []

    def post(path, body, prefer=None, **kw):
        st.posts.append((path, body))
        if path.startswith("/platform_update_seen"):
            for r in body:
                st.seen.add(r["update_id"])
            return []
        return [dict(body)]

    def patch(path, body, **kw):
        st.patches.append((path, body))
        uid = path.split("id=eq.")[1]
        for r in st.rows:
            if r["id"] == uid:
                r.update(body)
                return [copy.deepcopy(r)]
        return []

    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    monkeypatch.setattr(sb_clients, "sb_get_all_as_service", get_all)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", patch)
    monkeypatch.setattr(sb_clients, "sb_count_as_service", lambda path: 1)
    monkeypatch.setattr(PU, "_today", lambda: TODAY)
    monkeypatch.setattr(business_access, "_resolve_role",
                        lambda b, u: {OWNER: "owner", SEAT: "admin"}.get(u))
    PU.forget_cache()
    who = SimpleNamespace(id=OWNER, email="pastor@gracestreet.org")
    a = FastAPI()
    a.include_router(PU.router)
    a.dependency_overrides[auth_supabase.require_user_session] = lambda: SimpleNamespace(user=who, token="t")
    a.dependency_overrides[auth_supabase.require_user] = lambda: who
    st.client, st.who = TestClient(a), who
    yield st
    PU.forget_cache()


def test_for_me_gives_the_card_and_the_list_in_church_words(app):
    got = app.client.get(f"/updates/for-me?business_id={BIZ}&pages=operate:news,bad page").json()
    assert got["church"] is True
    ids = [e["id"] for e in got["updates"]]
    assert ids == ["2026-11-27-everyone", "2026-11-26-churches", "2026-11-25-owner", "2026-11-01-older"]
    assert got["card"][0]["id"] == "2026-11-26-churches" and got["card"][0]["line"] == "For the church office."
    assert len(got["card"]) == 3 and got["unseen"] == 4


def test_seen_follows_the_login_and_only_counts_what_they_may_see(app):
    r = app.client.post(f"/updates/seen?business_id={BIZ}",
                        json={"ids": ["2026-11-26-churches", "2026-11-20-draft", "nope"], "how": "card"})
    assert r.status_code == 200 and r.json()["saved"] == 1
    assert app.seen == {"2026-11-26-churches"}
    got = app.client.get(f"/updates/for-me?business_id={BIZ}").json()
    assert "2026-11-26-churches" not in [e["id"] for e in got["card"]]
    assert next(e for e in got["updates"] if e["id"] == "2026-11-26-churches")["seen"] is True
    assert got["unseen"] == 3
    assert app.client.post(f"/updates/seen?business_id={BIZ}", json={"ids": [], "how": "card"}).status_code == 400
    assert app.client.post(f"/updates/seen?business_id={BIZ}", json={"ids": ["x"], "how": "shout"}).status_code == 400


def test_an_admin_seat_sees_from_the_day_it_joined_and_no_owner_news(app):
    app.who.id = SEAT
    got = app.client.get(f"/updates/for-me?business_id={BIZ}").json()
    assert [e["id"] for e in got["updates"]] == ["2026-11-27-everyone", "2026-11-26-churches"]


def test_reads_that_fail_never_widen_what_a_seat_sees(app, monkeypatch):
    import church_areas
    app.who.id = SEAT
    # The seat's own row can't be read: its day is today, so nothing older shows.
    app.seat_fails = True
    assert app.client.get(f"/updates/for-me?business_id={BIZ}").json()["updates"] == []
    app.seat_fails = False
    # Its areas can't be read while the switch is on: an update for an area is
    # hidden, one for everyone still shows.
    app.rows.append(up("2026-11-24-giving", date="2026-11-24", areas=["giving_money"]))
    PU.forget_cache()
    monkeypatch.setattr(church_areas, "my_areas", lambda b, u, r: None)
    monkeypatch.setattr(church_areas, "mode", lambda: "on")
    ids = [e["id"] for e in app.client.get(f"/updates/for-me?business_id={BIZ}").json()["updates"]]
    assert "2026-11-24-giving" not in ids and "2026-11-27-everyone" in ids
    # With the switch off, None is the whole church, as before.
    monkeypatch.setattr(church_areas, "mode", lambda: "off")
    ids = [e["id"] for e in app.client.get(f"/updates/for-me?business_id={BIZ}").json()["updates"]]
    assert "2026-11-24-giving" in ids


def test_seen_that_cannot_be_read_shows_nothing_as_new(app):
    app.seen_fails = True
    got = app.client.get(f"/updates/for-me?business_id={BIZ}").json()
    assert got["card"] == [] and got["unseen"] == 0 and got["updates"]


def test_the_list_pages_by_date_and_id(app):
    first = app.client.get(f"/updates/for-me?business_id={BIZ}&limit=2").json()
    assert [e["id"] for e in first["updates"]] == ["2026-11-27-everyone", "2026-11-26-churches"]
    assert first["more"] is True and first["next"] == "2026-11-26|2026-11-26-churches"
    rest = app.client.get(f"/updates/for-me?business_id={BIZ}&limit=2&before={first['next']}").json()
    assert [e["id"] for e in rest["updates"]] == ["2026-11-25-owner", "2026-11-01-older"] and rest["more"] is False


def test_a_stranger_gets_nothing(app):
    app.who.id = "bbbbbbbb-1111-4111-8111-111111111111"
    assert app.client.get(f"/updates/for-me?business_id={BIZ}").status_code == 404


# ─── Mission Control ─────────────────────────────────────────────────────

def test_only_the_platform_owner_reaches_the_queue(app):
    assert app.client.get("/platform/updates").status_code == 403
    import lead_admin
    app.who.email = lead_admin.PLATFORM_OWNER_EMAIL
    got = app.client.get("/platform/updates?status=draft").json()
    assert [r["id"] for r in got["rows"]] == ["2026-11-20-draft"] and "warnings" in got["rows"][0]


def test_create_edit_and_publish(app):
    import lead_admin
    app.who.email = lead_admin.PLATFORM_OWNER_EMAIL
    r = app.client.post("/platform/updates", json={"title": "Every page fits a laptop", "line": "More room.",
                                                   "date": "2026-11-26", "area": "Everywhere"})
    assert r.status_code == 200
    row = r.json()["row"]
    assert row["id"] == "2026-11-26-every-page-fits-a-laptop" and row["status"] == "draft" and row["source"] == "editor"
    app.rows.append({**up(row["id"], status="draft"), **row})
    assert app.client.post("/platform/updates", json={"title": "Every page fits a laptop",
                                                      "date": "2026-11-26"}).status_code == 409
    r = app.client.patch(f"/platform/updates/{row['id']}", json={"status": "published", "weight": "big"})
    assert r.status_code == 200 and r.json()["row"]["published_at"]
    for bad in ({"page": "Not A Page"}, {"weight": "huge"}, {"roles": ["boss"]}, {"kinds": ["Has Space"]},
                {"title": ""}, {"line": "x" * 301}, {"tour": [{"nope": 1}]}, {"date": "tomorrow"}):
        assert app.client.patch(f"/platform/updates/{row['id']}", json=bad).status_code == 400, bad
    assert app.client.patch("/platform/updates/2026-01-01-missing", json={"title": "x"}).status_code == 404


def test_the_editor_is_warned_about_words_that_cross_over():
    w = PU.warnings(up("2026-11-27-x", line="If a customer calls while you're between jobs, ask Chief."))
    assert any("Churches will read" in s and "customer" in s for s in w)
    w = PU.warnings(up("2026-11-27-y", line="Your members get a note."))
    assert any("Businesses will read" in s and "members" in s for s in w)
    # Set for churches only, church words are fine; with church words, the business line is fine for churches.
    assert not [s for s in PU.warnings(up("2026-11-27-z", kinds=["ministry"], line="Your members get a note."))
                if "read" in s]
    assert not [s for s in PU.warnings(up("2026-11-27-w", line="Ask Chief between jobs.",
                                          church_line="Ask Chief between visits.")) if "read" in s]
    w = PU.warnings(up("2026-11-27-v", line="", weight="big"))
    assert any("No one-line" in s for s in w) and any("nowhere to go" in s for s in w)


def test_news_drafts_queue(app):
    import lead_admin
    app.who.email = lead_admin.PLATFORM_OWNER_EMAIL
    assert app.client.post("/platform/news-drafts", json={"body": "no headline"}).status_code == 400
    r = app.client.post("/platform/news-drafts", json={"headline": "Chief on your phone", "audience": "church",
                                                       "church_body": "At the hospital…"})
    assert r.status_code == 200 and r.json()["row"]["audience"] == "church"
    assert app.client.post("/platform/news-drafts", json={"headline": "x", "audience": "martians"}).status_code == 400
