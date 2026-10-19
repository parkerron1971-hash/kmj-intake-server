"""The app's own pictures (member_app_pictures). Kevin, 2026-10-19: "only
the admin or key people like media etc can change those pictures. the only
thing people can change is there profile pictures and stuff related to
their account." """
import asyncio
import io

import pytest

import member_app_pictures as mapic
import member_photos as ph

ED = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
G1 = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


def _biz(**portal):
    return {"id": "11111111-1111-4111-8111-111111111111", "name": "Love City Church",
            "settings": {"member_portal": {"photo_editors": [ED], **portal}}}


def _jpeg(w=900, h=600):
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (w, h), (200, 40, 90)).save(out, "JPEG")
    return out.getvalue()


# ─── who may ─────────────────────────────────────────────────────────


def test_only_the_owner_in_a_preview_and_the_people_named_may_change_pictures():
    biz = _biz()
    assert mapic.may_edit({"preview": True, "claims": {"own": "u-owner"}, "me": {"id": OTHER}}, biz) == "owner:u-owner"
    assert mapic.may_edit({"me": {"id": ED}}, biz) == f"member:{ED}"
    assert mapic.may_edit({"me": {"id": OTHER}}, biz) is None            # any other member: their own photo only
    assert mapic.may_edit({"unavailable": True}, biz) is None
    assert mapic.may_edit(None, biz) is None
    # a sign-in shared by a household never carries the named person's right
    assert mapic.may_edit({"me": {"id": ED}, "people": [{"id": ED}, {"id": OTHER}]}, biz) is None
    assert mapic.may_edit({"me": {"id": ED}, "people": [{"id": ED}]}, biz) == f"member:{ED}"


def test_the_owners_list_is_checked():
    assert mapic.clean_editors([ED, ED.upper(), "x", 5, OTHER]) == [ED, OTHER]
    assert mapic.clean_editors("nope") is None
    many = [f"{i:08x}-aaaa-4aaa-8aaa-aaaaaaaaaaaa" for i in range(40)]
    assert len(mapic.clean_editors(many)) == mapic.EDITORS_MAX


# ─── the spots ───────────────────────────────────────────────────────


def test_every_spot_is_listed_events_by_name_once():
    occ = [{"title": "Sunday Worship"}, {"title": "Sunday Worship"}, {"title": "Supper House"}]
    keys = [s["key"] for s in mapic.spots(_biz(), occ, [{"id": G1, "name": "Young Adults"}])]
    assert keys[:7] == ["home", "signin", "give", "live", "watch", "groups", "youth"]
    assert "tile:ministries" in keys and "tile:love-city-online" in keys
    assert keys.count("event:sunday-worship") == 1 and "event:supper-house" in keys
    assert f"group:{G1}" in keys
    assert all(mapic.KEY_RE.fullmatch(k) for k in keys)


def test_what_a_spot_shows_now_and_why():
    pool = ["https://cdn.example/supper-house.jpg"]
    biz = _biz(pictures={"event:prayer-night": {"url": ""}, "home": {"url": "https://cdn.example/h.jpg", "look": "bw"}})
    spot = lambda key, label: {"key": key, "label": label}
    assert mapic.current(biz, None, pool, spot("home", "x")) == ("https://cdn.example/h.jpg", "bw", "chosen")
    assert mapic.current(biz, None, pool, spot("event:prayer-night", "Prayer Night")) == ("", "colour", "default")
    assert mapic.current(biz, None, pool, spot("event:supper-house", "Supper House"))[2] == "named"
    assert mapic.current(biz, None, pool, spot("event:mens-breakfast", "Men's Breakfast"))[2] == "default"


def test_the_list_and_the_editor():
    from starlette.requests import Request
    req = Request({"type": "http", "query_string": b"key=home", "headers": [], "path": "/my/pictures/spot"})
    me = {"id": ED, "name": "Dee"}
    page = mapic.render_list(_biz(), None, req, me, [{"title": "Supper House"}], [])
    assert "Home&#x27;s top photo" in page and 'href="/my/pictures/spot?key=event%3Asupper-house"' in page
    assert "Default picture" in page
    spot = mapic.find_spot(_biz(), "home", [], [])
    editor = mapic.render_spot(_biz(), None, req, me, spot)
    assert 'action="/my/pictures" enctype="multipart/form-data"' in editor and 'name="key" value="home"' in editor
    assert editor.count('name="look"') == 3 and 'value="default"' in editor and 'type="file" name="photo"' in editor
    assert mapic.find_spot(_biz(), "event:nothing-on", [], []) is None


# ─── an upload, and saving ───────────────────────────────────────────


def test_an_upload_is_upright_at_most_1600_and_webp():
    from PIL import Image
    webp = mapic.prepare(_jpeg(3000, 1200))
    with Image.open(io.BytesIO(webp)) as im:
        assert im.format == "WEBP" and max(im.size) == 1600 and im.size[0] > im.size[1]
    for bad in (b"", b"not a photo", _jpeg(120, 120)):
        with pytest.raises(ph.PhotoError):
            mapic.prepare(bad)


def test_saving_puts_the_picture_on_its_spot_and_an_upload_in_the_library(monkeypatch):
    import sb_clients
    written = []
    monkeypatch.setattr(sb_clients, "sb_get_as_service",
                        lambda path: [{"settings": {"brand_kit": {"x": 1}, "member_portal": {"base": "black"},
                                                    "media_library": {"gallery": [{"id": "g1", "sort_order": 4}]}}}])
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda path, body: written.append(body) or [{"id": "b"}])
    assert mapic.save_spot("b1", "home", "https://x.example/new.webp", "church", by="owner:u", uploaded=True, label="Home")
    s = written[-1]["settings"]
    assert s["brand_kit"] == {"x": 1} and s["member_portal"]["base"] == "black"        # nothing else touched
    assert s["member_portal"]["pictures"]["home"]["url"] == "https://x.example/new.webp"
    assert s["member_portal"]["pictures"]["home"]["look"] == "church"
    new = s["media_library"]["gallery"][-1]
    assert new["url"] == "https://x.example/new.webp" and new["show_on_website"] is False and new["sort_order"] == 5
    assert mapic.save_spot("b1", "tile:prayer", "", "neon", by="member:x")
    assert written[-1]["settings"]["member_portal"]["pictures"]["tile:prayer"] == {
        **written[-1]["settings"]["member_portal"]["pictures"]["tile:prayer"], "url": "", "look": "colour"}
    assert len(written[-1]["settings"]["media_library"]["gallery"]) == 1               # choosing isn't uploading


def test_a_failed_read_or_write_saves_nothing_and_says_so(monkeypatch):
    import sb_clients
    writes = []
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda path, body: writes.append(body) or [{"id": "b"}])
    for failed_read in (None, []):
        monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path, r=failed_read: r)
        assert mapic.save_spot("b1", "home", "", "colour", by="owner:u") is False
    assert writes == []                                                    # never a write from a failed read
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda path: [{"settings": {}}])
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", lambda path, body: None)
    assert mapic.save_spot("b1", "home", "", "colour", by="owner:u") is False


def test_the_owners_new_settings_are_checked(monkeypatch):
    from fastapi import HTTPException
    import member_portal as mp

    class U:
        id = "u-owner"
    for bad in ({"colours": "rainbow"}, {"photo_editors": "everyone"}):
        with pytest.raises(HTTPException) as e:
            mp.patch_member_portal_config("b1", bad, user=U())
        assert e.value.status_code == 400


# ─── the route ───────────────────────────────────────────────────────


def _req(fields, file=None):
    from starlette.requests import Request
    parts = b""
    for k, v in fields.items():
        parts += f"--X\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    if file is not None:
        parts += (b"--X\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"p.jpg\"\r\n"
                  b"Content-Type: image/jpeg\r\n\r\n" + file + b"\r\n")
    body = parts + b"--X--\r\n"

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    return Request({"type": "http", "method": "POST", "path": "/my/pictures", "query_string": b"",
                    "headers": [(b"content-type", b"multipart/form-data; boundary=X")]}, receive)


@pytest.fixture
def route(monkeypatch):
    import member_portal as mp
    import rate_limit
    state = {"sess": {"me": {"id": ED}}, "saved": [], "stored": []}

    async def church(request):
        return {"business": _biz(), "site": None}
    monkeypatch.setattr(mp, "_church_or_404", church)
    monkeypatch.setattr(mp, "_same_origin", lambda request: True)
    monkeypatch.setattr(mp, "_session_for", lambda request, c: state["sess"])
    monkeypatch.setattr(rate_limit, "allow_strict", lambda *a: True)
    monkeypatch.setattr(mapic, "library", lambda biz, site: ["https://cdn.example/a.jpg"])
    monkeypatch.setattr(mapic, "store", lambda b, w: state["stored"].append(len(w)) or "https://cdn.example/up.webp")
    monkeypatch.setattr(mapic, "save_spot", lambda b, key, url, look, **kw: state["saved"].append((key, url, look, kw["by"])) or True)
    return state


def _go(req):
    return asyncio.run(mapic.save_picture(req)).headers["location"]


def test_the_route_saves_a_pick_the_default_or_a_checked_upload(route, monkeypatch):
    async def ok(*a, **kw):
        return "ok"

    async def no(*a, **kw):
        return "no"

    async def down(*a, **kw):
        raise ph.ScreenUnavailable("x")
    assert _go(_req({"key": "home", "pick": "https://cdn.example/a.jpg", "look": "bw"})) == "/my/pictures?done=picture"
    assert route["saved"][-1] == ("home", "https://cdn.example/a.jpg", "bw", f"member:{ED}")
    assert _go(_req({"key": "event:supper-house", "pick": "default", "back": "/my?edit=pictures"})) == \
        "/my?edit=pictures&done=picture"
    assert route["saved"][-1][:2] == ("event:supper-house", "")
    assert _go(_req({"key": "home", "pick": "https://evil.example/x.jpg"})) == "/my/pictures?err=pick"    # not the church's
    monkeypatch.setattr(ph, "screen", ok)
    assert _go(_req({"key": "home", "look": "church"}, _jpeg())) == "/my/pictures?done=picture"
    assert route["saved"][-1][1] == "https://cdn.example/up.webp" and route["stored"]
    monkeypatch.setattr(ph, "screen", no)
    assert _go(_req({"key": "home"}, _jpeg())) == "/my/pictures?err=no"
    monkeypatch.setattr(ph, "screen", down)
    assert _go(_req({"key": "home"}, _jpeg())) == "/my/pictures?err=busy"
    assert _go(_req({"key": "home"}, b"not a photo")) == "/my/pictures?err=bad"
    assert _go(_req({"key": "../settings", "pick": "default"})) == "/my/pictures?err=error"
    assert _go(_req({"key": "home", "pick": "default", "back": "https://evil.example"})) == "/my/pictures?done=picture"


def test_anyone_else_is_turned_away_and_nothing_saves(route):
    route["sess"] = {"me": {"id": OTHER}}
    before = len(route["saved"])
    assert _go(_req({"key": "home", "pick": "default"})) == "/my"
    route["sess"] = None
    assert _go(_req({"key": "home", "pick": "default"})) == "/my"
    assert len(route["saved"]) == before
    route["sess"] = {"preview": True, "claims": {"own": "u-owner"}, "me": {"id": OTHER}}     # the owner, previewing
    assert _go(_req({"key": "home", "pick": "default"})) == "/my/pictures?done=picture"
    assert route["saved"][-1][3] == "owner:u-owner"


def test_the_pictures_route_is_mounted_before_the_catch_all():
    import kmj_intake_automation as app_mod
    routes = [(getattr(r, "path", ""), getattr(r, "methods", set()) or set()) for r in app_mod.app.routes]
    paths = [p for p, _ in routes]
    catch = next(i for i, p in enumerate(paths) if "{full_path" in p or p.endswith("{path:path}"))
    assert next(i for i, (p, m) in enumerate(routes) if p == "/my/pictures" and "POST" in m) < catch


# ─── every other screen's picture spot goes the same way ─────────────


ME = {"id": OTHER, "name": "Ana Rivers", "email": "ana@example.com"}
PIC = "https://cdn.example/chosen.jpg"


def _get(path="/my"):
    from starlette.requests import Request
    return Request({"type": "http", "query_string": b"", "headers": [], "path": path})


def test_give_watch_connect_live_and_youth_show_the_churchs_pick_else_their_default():
    import member_portal as mp
    import member_portal_church as mpc
    import member_portal_live as mpl
    import member_portal_sermons as mps
    import member_spaces as msp
    lead = [{"entry_id": "e1", "title": "Youth Night", "date": "2026-10-23", "attending": 3}]
    pages = {
        "give": lambda b: mp.render_give_off(b, None, ME),
        "watch": lambda b: mps.render_library(b, None, ME, {"sermons": [], "series": []}),
        "groups": lambda b: mpc.render_groups(b, None, _get("/my/groups"), {"mine": [], "open": []}, who=ME),
        "live": lambda b: mpl.render_live(b, None, _get("/my/live"), ME, {}),
        "youth": lambda b: msp.render_youth_home(b, None, me=ME, occasions=lead, groups=None, youth_posts=[]),
    }
    kinds = {"give": "h-brand", "watch": "h-violet", "groups": "h-teal", "live": "h-violet", "youth": "h-violet"}
    for key, page in pages.items():
        plain = page({"id": "b1", "name": "Love City Church", "settings": {}})
        assert f'class="mb-def {kinds[key]} is-night' in plain, key                       # no photos: its default
        chosen = page({"id": "b1", "name": "Love City Church",
                       "settings": {"member_portal": {"pictures": {key: {"url": PIC, "look": "church"}}}}})
        assert PIC in chosen and "mb-ph is-church" in chosen, key                          # the church's pick, its look


def test_the_owner_names_people_and_picks_the_colours(monkeypatch):
    import member_portal as mp
    payload = mp._config_payload({"id": "b1", "settings": {"member_portal": {"colours": "church"}}}, {"slug": "lcc"})
    assert payload["colours"] == "church" and payload["photo_editors"] == []
