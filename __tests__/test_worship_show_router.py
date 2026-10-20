# __tests__/test_worship_show_router.py
#
# Sundays on screens over HTTP (worship_show_router.py). Pins:
#   * the switch: owner opens the signed-in routes to the platform owner
#     only; off closes screen links too
#   * seats: anyone with a seat reads a service; owner/admin/manager plan,
#     set screens and the look, and run the slides; a stranger gets 404
#   * a service's items are checked; one starts from a template; taking one
#     out archives it; the booth's show is its slides in the church's look
#   * a screen's link opens what that screen shows, never the booth's
#     notes; a new link retires the old one; a removed screen's link is dead;
#     only staff ever see a link
#   * the booth's slide reaches waiting screens at once, `rev` only goes up,
#     and the saved row brings a restarted server back to where Sunday was
#   * a failed read is a 503, never an empty list

import asyncio
import pathlib
import sys
import uuid as uuidlib
from urllib.parse import parse_qsl

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import sb_clients
import worship_show_router as wsr
from auth_supabase import AuthedUser, require_user

BIZ = "11111111-1111-4111-8111-111111111111"
OTHER_BIZ = "22222222-2222-4222-8222-222222222222"
OWNER_EMAIL = "kmjcreativesolution@gmail.com"
PEOPLE = {
    "owner": AuthedUser(id="u-owner", email=OWNER_EMAIL, role="authenticated"),
    "manager": AuthedUser(id="u-manager", email="pat@lovecity.org", role="authenticated"),
    "member": AuthedUser(id="u-member", email="jas@lovecity.org", role="authenticated"),
    "stranger": AuthedUser(id="u-stranger", email="who@else.org", role="authenticated"),
}
SEATS = {("u-owner", BIZ): "owner", ("u-manager", BIZ): "manager", ("u-member", BIZ): "member"}
SONG_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SONG = {"id": SONG_ID, "business_id": BIZ, "title": "It Is Well With My Soul", "song_key": "D", "authors": "", "ccli_number": None,
        "copyright": "", "public_domain": True, "lines_per_slide": 2, "archived_at": None,
        "sections": [{"id": "r", "kind": "refrain", "number": None, "label": "Refrain",
                      "lines": ["It is well with my soul,", "It is well, it is well with my soul."]}],
        "arrangements": [{"id": "main", "name": "Main", "order": ["r", "r"]}]}


class FakeDb:
    """sb_*_as_service over a few tables, with eq./is.null/in.() filters. Like
    sb_clients: None for a refused call AND for a successful minimal write."""

    KEYS = {"worship_settings": "business_id", "worship_live": "business_id"}

    def __init__(self):
        self.t = {"businesses": [{"id": BIZ, "name": "Love City Church",
                                  "settings": {"brand_kit": {"colors": {"primary": "#1c0b1f"}, "logo_url": "https://x.example/l.png"},
                                               "stripe_secret": "never-sent"}}],
                  "worship_songs": [dict(SONG)], "worship_services": [], "worship_screens": [],
                  "worship_settings": [], "worship_live": []}
        self.fail = set()

    @staticmethod
    def _split(path):
        table, _, q = path.lstrip("/").partition("?")
        return table, [(k, v) for k, v in parse_qsl(q, keep_blank_values=True)
                       if k not in ("select", "order", "limit", "on_conflict")]

    @staticmethod
    def _match(row, filters):
        for k, v in filters:
            if v == "is.null":
                if row.get(k) is not None:
                    return False
            elif v.startswith("eq."):
                if str(row.get(k)) != v[3:]:
                    return False
            elif v.startswith("in.("):
                if str(row.get(k)) not in v[4:-1].split(","):
                    return False
        return True

    def get(self, path, **_):
        table, f = self._split(path)
        if table in self.fail:
            return None
        return [dict(r) for r in self.t.get(table, []) if self._match(r, f)]

    def post(self, path, body, prefer=None, **_):
        table, _f = self._split(path)
        if table in self.fail:
            return None
        rows = body if isinstance(body, list) else [body]
        out = []
        key = self.KEYS.get(table)
        for b in rows:
            hit = next((r for r in self.t[table] if key and r.get(key) == b.get(key)), None)
            if hit is not None and "merge-duplicates" in (prefer or ""):
                hit.update(b)
                out.append(dict(hit))
                continue
            row = {"id": str(uuidlib.uuid4()), "archived_at": None, "created_at": "2026-10-19T00:00:00+00:00", **b}
            self.t[table].append(row)
            out.append(dict(row))
        return None if prefer == "return=minimal" else out

    def patch(self, path, body):
        table, f = self._split(path)
        if table in self.fail:
            return None
        hit = [r for r in self.t[table] if self._match(r, f)]
        for r in hit:
            r.update(body)
        return [dict(r) for r in hit]


@pytest.fixture
def api(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", db.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", db.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", db.patch)
    monkeypatch.setenv("PLATFORM_OWNER_EMAIL", OWNER_EMAIL)
    monkeypatch.delenv("WORSHIP_SONGS", raising=False)
    monkeypatch.setattr(wsr, "HUB", wsr.LiveHub())

    def fake_access(biz, user, min_role="viewer"):
        role = SEATS.get((user.id, biz))
        if not role:
            raise HTTPException(404, "Not Found")
        return role

    monkeypatch.setattr(wsr, "assert_access", fake_access)
    who = {"user": PEOPLE["owner"]}
    app = FastAPI()
    app.include_router(wsr.router)
    app.dependency_overrides[require_user] = lambda: who["user"]
    client = TestClient(app)

    def as_(name):
        who["user"] = PEOPLE[name]
        return client

    return db, as_, client


ITEMS = [
    {"id": "worship", "kind": "section", "title": "Worship"},
    {"id": "well", "kind": "song", "song_id": SONG_ID, "notes": "Hold the last refrain", "minutes": 5},
    {"id": "word", "kind": "scripture", "ref": "rom 8 28"},
]


def plan(as_, who="owner", **body):
    return as_(who).post("/worship/services", json={"business_id": BIZ, "title": "Sunday, Oct 25",
                                                    "starts_at": "2026-10-25T15:05:00Z", "items": ITEMS, **body})


def test_the_switch(api, monkeypatch):
    db, as_, _ = api
    assert as_("owner").get(f"/worship/services?business_id={BIZ}").status_code == 200
    assert as_("manager").get(f"/worship/services?business_id={BIZ}").status_code == 404
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    assert as_("manager").get(f"/worship/services?business_id={BIZ}").status_code == 200
    token = as_("owner").post("/worship/screens", json={"business_id": BIZ, "name": "Projector"}).json()["screen"]["token"]
    assert as_("member").get(f"/worship/screen/{token}").status_code == 200
    monkeypatch.setenv("WORSHIP_SONGS", "off")
    assert as_("owner").get(f"/worship/services?business_id={BIZ}").status_code == 404
    assert as_("owner").get(f"/worship/screen/{token}").status_code == 404


def test_seats_plan_and_read(api, monkeypatch):
    db, as_, _ = api
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    r = plan(as_, "manager")
    assert r.status_code == 200, r.text
    svc = r.json()["service"]
    assert (svc["item_count"], svc["minutes"]) == (2, 5.0)
    assert svc["items"][2]["ref"] == "Romans 8:28"          # how people type it, saved as a reference
    assert plan(as_, "member").status_code == 403
    assert as_("member").get(f"/worship/services/{svc['id']}?business_id={BIZ}").status_code == 200
    assert as_("stranger").get(f"/worship/services?business_id={BIZ}").status_code == 404
    assert as_("owner").get(f"/worship/services?business_id={OTHER_BIZ}").status_code == 404
    listed = as_("member").get(f"/worship/services?business_id={BIZ}").json()
    assert listed["can_write"] is False and [s["title"] for s in listed["services"]] == ["Sunday, Oct 25"]


def test_items_are_checked(api):
    db, as_, _ = api
    r = plan(as_, items=[{"id": "x", "kind": "scripture", "ref": "hezekiah 1"}])
    assert r.status_code == 400 and "isn't a passage" in r.json()["detail"]
    assert plan(as_, title="x" * 121).status_code == 400
    assert plan(as_, starts_at="next sunday").status_code == 400


def test_start_from_a_template_and_take_one_out(api):
    db, as_, _ = api
    tmpl = plan(as_, title="Sunday template", is_template=True).json()["service"]
    copy = as_("owner").post("/worship/services", json={"business_id": BIZ, "title": "Sunday, Nov 1", "from_id": tmpl["id"]})
    assert copy.status_code == 200 and [i["id"] for i in copy.json()["service"]["items"]] == ["worship", "well", "word"]
    sid = copy.json()["service"]["id"]
    saved = as_("owner").put(f"/worship/services/{sid}", json={"business_id": BIZ, "items": ITEMS[:2]})
    assert [i["id"] for i in saved.json()["service"]["items"]] == ["worship", "well"]
    assert as_("owner").delete(f"/worship/services/{sid}?business_id={BIZ}").json() == {"ok": True}
    assert as_("owner").get(f"/worship/services/{sid}?business_id={BIZ}").status_code == 404
    assert len(as_("owner").get(f"/worship/services?business_id={BIZ}").json()["services"]) == 1


def test_the_booth_gets_slides_in_the_look(api):
    db, as_, _ = api
    sid = plan(as_).json()["service"]["id"]
    show = as_("owner").get(f"/worship/services/{sid}/show?business_id={BIZ}").json()
    assert [i["id"] for i in show["items"]] == ["worship", "well", "word"]
    assert [s["lines"][0] for s in show["items"][1]["slides"]] == ["It is well with my soul,"] * 2
    assert show["items"][1]["notes"] == "Hold the last refrain"
    assert show["look"]["background"]["kind"] == "brand"
    assert show["church"] == {"name": "Love City Church",
                              "brand_kit": {"colors": {"primary": "#1c0b1f"}, "logo_url": "https://x.example/l.png"}}


def test_screens_and_their_links(api, monkeypatch):
    db, as_, _ = api
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    r = as_("manager").post("/worship/screens", json={"business_id": BIZ, "name": "LED wall", "role": "led",
                                                      "width": 2304, "height": 768, "led": {"across": 12, "down": 4, "px": 192}})
    assert r.status_code == 200, r.text
    screen = r.json()["screen"]
    assert len(screen["token"]) >= 32 and screen["led"] == {"across": 12, "down": 4, "px": 192}
    assert as_("member").post("/worship/screens", json={"business_id": BIZ, "name": "x"}).status_code == 403
    member_view = as_("member").get(f"/worship/screens?business_id={BIZ}").json()
    assert "token" not in member_view["screens"][0] and member_view["can_write"] is False
    assert as_("owner").post("/worship/screens", json={"business_id": BIZ, "name": "x", "role": "ceiling"}).status_code == 400
    assert as_("owner").post("/worship/screens", json={"business_id": BIZ, "name": "x", "width": 99}).status_code == 400

    info = as_("stranger").get(f"/worship/screen/{screen['token']}").json()
    assert info["screen"]["role"] == "led" and "token" not in info["screen"]
    assert info["church"]["name"] == "Love City Church" and "stripe_secret" not in str(info)

    fresh = as_("owner").post(f"/worship/screens/{screen['id']}/new-link", json={"business_id": BIZ}).json()["screen"]["token"]
    assert fresh != screen["token"]
    assert as_("owner").get(f"/worship/screen/{screen['token']}").status_code == 404
    assert as_("owner").get(f"/worship/screen/{fresh}").status_code == 200
    as_("owner").delete(f"/worship/screens/{screen['id']}?business_id={BIZ}")
    assert as_("owner").get(f"/worship/screen/{fresh}").status_code == 404
    assert as_("owner").get("/worship/screen/short").status_code == 404


def test_at_most_twenty_screens(api):
    db, as_, _ = api
    for k in range(20):
        assert as_("owner").post("/worship/screens", json={"business_id": BIZ, "name": f"TV {k}"}).status_code == 200
    r = as_("owner").post("/worship/screens", json={"business_id": BIZ, "name": "one more"})
    assert r.status_code == 400 and "at most 20" in r.json()["detail"]


def test_the_look(api, monkeypatch):
    db, as_, _ = api
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    assert as_("owner").get(f"/worship/look?business_id={BIZ}").json()["look"]["size"] == "std"
    r = as_("owner").put("/worship/look", json={"business_id": BIZ, "look": {"size": "big", "background": {"kind": "color", "color": "#1C0B1F"}}})
    assert r.status_code == 200 and r.json()["look"]["background"]["color"] == "#1C0B1F"
    r2 = as_("owner").put("/worship/look", json={"business_id": BIZ, "look": {"size": "small"}})
    assert r2.json()["look"]["size"] == "small" and len(db.t["worship_settings"]) == 1
    assert as_("owner").put("/worship/look", json={"business_id": BIZ, "look": {"size": "huge"}}).status_code == 400
    assert as_("member").put("/worship/look", json={"business_id": BIZ, "look": {}}).status_code == 403


def test_the_booth_runs_the_screens(api, monkeypatch):
    db, as_, _ = api
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    sid = plan(as_).json()["service"]["id"]
    token = as_("owner").post("/worship/screens", json={"business_id": BIZ, "name": "Projector"}).json()["screen"]["token"]
    # Before anything is live, a screen has nothing to show.
    assert as_("stranger").get(f"/worship/screen/{token}/show").json()["items"] == []

    r = as_("owner").post("/worship/live", json={"business_id": BIZ, "state": {"service_id": sid, "item_id": "well", "slide": 1}})
    assert r.status_code == 200 and r.json()["saved"] is True
    rev = r.json()["rev"]
    r2 = as_("owner").post("/worship/live", json={"business_id": BIZ, "state": {"service_id": sid, "item_id": "well", "slide": 0, "mode": "black"}})
    assert r2.json()["rev"] > rev
    live = as_("member").get(f"/worship/live?business_id={BIZ}").json()
    assert (live["state"]["mode"], live["state"]["slide"]) == ("black", 0)
    assert as_("member").post("/worship/live", json={"business_id": BIZ, "state": {"slide": 1}}).status_code == 403
    bad = as_("owner").post("/worship/live", json={"business_id": BIZ, "state": {"mode": "party"}})
    assert bad.status_code == 400

    show = as_("stranger").get(f"/worship/screen/{token}/show").json()
    assert [i["id"] for i in show["items"]] == ["worship", "well", "word"]
    assert all("notes" not in i for i in show["items"])          # a screen never gets the booth's notes

    # The row brings a restarted server back to where Sunday was.
    wsr.HUB = wsr.LiveHub()
    assert as_("member").get(f"/worship/live?business_id={BIZ}").json()["rev"] == r2.json()["rev"]


def test_a_waiting_screen_hears_the_next_slide_at_once():
    hub = wsr.LiveHub()

    async def run():
        waiting = asyncio.create_task(hub.wait(BIZ, 0, timeout=5))
        await asyncio.sleep(0.05)
        # Published from a worker thread, the way a plain handler runs.
        await asyncio.to_thread(hub.publish, BIZ, 7, {"slide": 2})
        return await asyncio.wait_for(waiting, 1)

    assert asyncio.run(run()) == (7, {"slide": 2})
    assert hub.publish(BIZ, 6, {"slide": 1}) is False           # rev only goes up
    assert hub.latest(BIZ) == (7, {"slide": 2})

    async def quiet():
        return await hub.wait(BIZ, 7, timeout=0.05)

    assert asyncio.run(quiet()) is None


def test_failed_reads_are_503(api):
    db, as_, _ = api
    db.fail.add("worship_services")
    assert as_("owner").get(f"/worship/services?business_id={BIZ}").status_code == 503
    db.fail = {"worship_screens"}
    assert as_("owner").get(f"/worship/screens?business_id={BIZ}").status_code == 503
    assert as_("owner").get("/worship/screen/" + "a" * 43).status_code == 503


def test_mounted_before_the_public_site_catch_all():
    src = (pathlib.Path(__file__).resolve().parent.parent / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert "include_router(worship_show_router)" in src
    assert src.index("include_router(worship_show_router)") < src.index("include_router(public_site_router)")


def test_a_real_screen_follows_the_booth_over_events(api, monkeypatch):
    """Over a real server: a screen's event stream gets where Sunday is on
    connect, then each slide the booth posts, in order."""
    import json as jsonlib
    import socket
    import threading
    import time

    import httpx
    import uvicorn

    db, as_, client = api
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    sid = plan(as_).json()["service"]["id"]
    token = as_("owner").post("/worship/screens", json={"business_id": BIZ, "name": "Projector"}).json()["screen"]["token"]
    as_("owner").post("/worship/live", json={"business_id": BIZ, "state": {"service_id": sid, "item_id": "well", "slide": 0}})

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(client.app, log_config=None, lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        base = f"http://127.0.0.1:{port}"
        got = []
        with httpx.stream("GET", f"{base}/worship/screen/{token}/events", timeout=10) as stream:
            assert stream.headers["content-type"].startswith("text/event-stream")
            lines = stream.iter_lines()
            # A 16 KB comment first, so Railway's edge flushes everything after it.
            first = next(lines)
            assert first.startswith(":") and len(first) >= wsr.PREAMBLE_BYTES
            for line in lines:
                if line.startswith("data: "):
                    got.append(jsonlib.loads(line[6:])["state"]["slide"])
                    if len(got) == 1:
                        # The booth presses Next on the same server.
                        httpx.post(f"{base}/worship/live", json={"business_id": BIZ, "state": {
                            "service_id": sid, "item_id": "well", "slide": 1}}, timeout=5)
                    if len(got) == 2:
                        break
        assert got == [0, 1]
    finally:
        server.should_exit = True
        thread.join(5)


def test_a_brand_kit_wins_and_a_church_without_one_uses_its_look(api, monkeypatch):
    db, as_, _ = api
    monkeypatch.setenv("WORSHIP_SONGS", "on")
    own = {"business_id": BIZ, "look": {"brand": {"primary": "#112233", "accent": "#C2125F", "logo_url": "https://x.example/own.png"}}}
    as_("owner").put("/worship/look", json=own)
    # Love City has a brand kit: it wins.
    assert as_("owner").get(f"/worship/look?business_id={BIZ}").json()["church"]["brand_kit"]["logo_url"] == "https://x.example/l.png"
    # A church on ChurchSavvy alone has none: its look's colors and logo draw the screens.
    db.t["businesses"][0]["settings"] = {}
    church = as_("owner").get(f"/worship/look?business_id={BIZ}").json()["church"]
    assert church["brand_kit"] == {"colors": {"primary": "#112233", "accent": "#C2125F"}, "logo_url": "https://x.example/own.png"}
