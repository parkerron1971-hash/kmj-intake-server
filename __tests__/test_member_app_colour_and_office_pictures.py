"""Settings → Member page: App colour and Pictures (Kevin approved the mock,
2026-11-22: "this is a good build").

App colour: settings.member_portal.app_colour, read first by
member_app_ui.brand_colour, so it changes the member app and nothing else;
unset, nothing changes for anyone.

Pictures: member_pictures_office, the office's way into the same store the
app's edit mode saves to (member_app_pictures.put)."""
import asyncio
import io
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import member_app_pictures as mapic
import member_app_ui as ui
import member_pictures_office as mpo
import member_portal as mp

BIZ = "11111111-1111-4111-8111-111111111111"
ED = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
KIT = {"brand_kit": {"colors": {"primary": "#1f6feb", "secondary": "#e3a92b"}}}


def _biz(portal=None, **settings):
    return {"id": BIZ, "name": "Love City Church", "type": "church", "owner_id": "u-owner",
            "settings": {**KIT, "member_portal": {"photo_editors": [ED], **(portal or {})}, **settings}}


# ─── App colour ──────────────────────────────────────────────────────


def test_the_apps_own_colour_comes_first_and_only_in_the_app():
    plain, own = _biz(), _biz({"app_colour": "#D6336C"})
    assert ui.brand_colour(plain, {}) == "#1f6feb"                       # unset: the brand's, as before
    assert ui.brand_colour(own, {}) == "#d6336c"                         # set: the app's own, first
    assert ui.brand_colour(own, {"accent": "#0a7d5a"}) == "#d6336c"      # before the theme's accent too
    assert ui.brand_colour(own, {}, app=False) == "#1f6feb"              # not the app: the brand's
    assert ui.palette(own, {})["tint"] == "#d6336c"
    assert ui.palette(plain, {}) == ui.palette(_biz({"app_colour": ""}), {})
    for junk in ("#777777", "#fafafa", "#050505", "red", 7, None):          # grey, near white/black, not a colour
        assert ui.app_colour(_biz({"app_colour": junk})) is None
        assert ui.brand_colour(_biz({"app_colour": junk}), {}) == "#1f6feb"
    assert ui.brand_colours(plain, {"accent": "#1F6FEB"}) == ["#1F6FEB", "#e3a92b"]   # each once


def test_the_highlight_is_the_new_looks_gold_and_only_when_chosen(monkeypatch):
    import member_lumen
    plain, hi = _biz(), _biz({"app_highlight": "#2FB6A6"})
    assert ui.app_highlight(hi) == "#2fb6a6" and ui.app_highlight(plain) is None
    assert ui.app_highlight(_biz({"app_highlight": "#888888"})) is None              # grey: the app's gold
    monkeypatch.setattr(member_lumen, "page", lambda: False)
    assert ui.palette(hi, {}) == ui.palette(plain, {})                                # today's look: unchanged
    monkeypatch.setattr(member_lumen, "page", lambda: True)
    base = ui.palette(plain, {})
    assert base["gold"] == ui.FAMILY["gold"]["fill"]                                  # unset: the gold, as before
    pal = ui.palette(hi, {})
    assert pal["gold"] == "#2fb6a6" and pal["gold_lit"] != base["gold_lit"]
    assert ui.contrast(pal["gold_ink"], pal["bg"]) >= 4.5                            # on white: a deeper shade
    assert ui.contrast(pal["gold_lit"], "#000000") >= 4.5                            # reads on black
    assert {k: v for k, v in pal.items() if not k.startswith("gold")} ==         {k: v for k, v in base.items() if not k.startswith("gold")}                   # nothing else moves
    assert ui.palette(hi, {}, "youth") == ui.palette(plain, {}, "youth")
    # The golds written into the new look's sheets follow it too, and only when it's chosen.
    assert ui.highlight_css(plain, "church", True) == "" and ui.highlight_css(hi, "church", False) == ""
    assert ui.highlight_css(hi, "youth", True) == ""
    extra = ui.highlight_css(hi, "church", True)
    assert ".lm-page .lbl" in extra and ".lm-pl-streak" in extra and ".lm-pl-dots i.now" in extra
    assert "body.lm.lm-dark:has(.lm-read)" in extra and "body.lm.lm-auto:has(.lm-read)" in extra
    assert "#FFE1A6" not in extra and "#8A5A00" not in extra


def test_brand_studio_the_website_and_flyers_keep_the_brand():
    import inspect
    import church_move_ready
    import church_move_setup
    import devotional_daily
    for mod in (church_move_ready, church_move_setup, devotional_daily):
        src = inspect.getsource(mod)
        assert src.count("brand_colour(") == src.count("app=False)") > 0, mod.__name__


def _settings(monkeypatch, owner="u-owner"):
    stored = {"settings": {"member_portal": {"enabled": True, "epoch": 7}, **KIT}}

    def _owner(b, u):
        if str(u.id) != owner:
            raise HTTPException(403, "not authorized")
        return {"id": BIZ, "type": "church", "settings": dict(stored["settings"])}
    monkeypatch.setattr(mp, "_require_owner", _owner)
    import business_sites_helpers
    monkeypatch.setattr(business_sites_helpers, "ensure_business_site",
                        lambda biz: ({"slug": "lcc", "site_config": {}}, False))
    monkeypatch.setattr(mp.sb_clients, "sb_get_as_service", lambda p: [{"settings": dict(stored["settings"])}])
    writes = []

    def _patch(path, body):
        writes.append(body)
        stored["settings"] = body["settings"]
        return [{"id": BIZ}]
    monkeypatch.setattr(mp.sb_clients, "sb_patch_as_service", _patch)
    return stored, writes


def test_the_owner_gives_the_app_its_own_colour_and_takes_it_back(monkeypatch):
    stored, writes = _settings(monkeypatch)
    user = SimpleNamespace(id="u-owner", email="pastor@example.test")
    for bad in ({"app_colour": "pink"}, {"app_colour": "#12345"}, {"app_colour": "#808080"}, {"app_colour": 5}):
        with pytest.raises(HTTPException) as e:
            mp.patch_member_portal_config(BIZ, bad, user)
        assert e.value.status_code == 400
    assert not writes
    out = mp.patch_member_portal_config(BIZ, {"app_colour": "#D6336C"}, user)
    assert stored["settings"]["member_portal"] == {"enabled": True, "epoch": 7, "app_colour": "#d6336c"}
    assert stored["settings"]["brand_kit"] == KIT["brand_kit"]                 # Brand Studio's colours untouched
    assert out["app_colour"] == "#d6336c" and out["brand_colour"] == "#1f6feb"
    assert out["brand_colours"] == ["#1f6feb", "#e3a92b"]
    out = mp.patch_member_portal_config(BIZ, {"app_colour": ""}, user)        # Back to my brand colour
    assert "app_colour" not in stored["settings"]["member_portal"] and out["app_colour"] is None
    mp.patch_member_portal_config(BIZ, {"app_colour": "#d6336c"}, user)
    mp.patch_member_portal_config(BIZ, {"app_colour": None}, user)
    assert "app_colour" not in stored["settings"]["member_portal"]
    out = mp.patch_member_portal_config(BIZ, {"app_highlight": "#2FB6A6"}, user)       # the highlight, beside it
    assert stored["settings"]["member_portal"]["app_highlight"] == "#2fb6a6" and out["app_highlight"] == "#2fb6a6"
    assert out["highlight_default"] == "#E3A92B"
    for bad in ({"app_highlight": "gold"}, {"app_highlight": "#ffffff"}):
        with pytest.raises(HTTPException):
            mp.patch_member_portal_config(BIZ, bad, user)
    mp.patch_member_portal_config(BIZ, {"app_highlight": ""}, user)                    # Use the app's gold
    assert "app_highlight" not in stored["settings"]["member_portal"]
    with pytest.raises(HTTPException) as e:
        mp.patch_member_portal_config(BIZ, {"app_colour": "#d6336c"}, SimpleNamespace(id="someone", email=None))
    assert e.value.status_code == 403


def test_the_page_says_what_the_app_wears():
    payload = mp._config_payload({"id": BIZ, "settings": {**KIT, "member_portal": {"app_colour": "#0a7d5a"}}},
                                 {"slug": "lcc"})
    assert (payload["app_colour"], payload["brand_colour"]) == ("#0a7d5a", "#1f6feb")
    payload = mp._config_payload({"id": BIZ, "settings": {}}, {"slug": "lcc"})
    assert payload["app_colour"] is None


# ─── Pictures from the office: who may ──────────────────────────────


@pytest.fixture
def office(monkeypatch):
    import business_access
    state = {"biz": _biz(), "seat": None, "contacts": [{"id": ED, "email": "Media@Example.test"}]}

    def get(path):
        if path.startswith("/businesses"):
            return [state["biz"]]
        if path.startswith("/contacts"):
            return state["contacts"]
        return []
    monkeypatch.setattr(mpo.sb_clients, "sb_get_as_service", get)

    def access(business_id, user, min_role="viewer"):
        if not state["seat"]:
            raise HTTPException(404, "business not found")
        return state["seat"]
    monkeypatch.setattr(business_access, "assert_access", access)
    return state


def test_the_owner_and_the_named_people_with_an_office_login_may(office):
    owner = SimpleNamespace(id="u-owner", email="pastor@example.test")
    media = SimpleNamespace(id="u-media", email="media@example.test")
    stranger = SimpleNamespace(id="u-x", email="x@example.test")
    assert mpo._who(BIZ, owner)[1] == "owner:u-owner"
    with pytest.raises(HTTPException) as e:                       # no login on this church: the stranger's 404
        mpo._who(BIZ, media)
    assert e.value.status_code == 404
    office["seat"] = "member"
    assert mpo._who(BIZ, media)[1] == f"member:{ED}"              # a login, and named (by the email on record)
    with pytest.raises(HTTPException) as e:                       # a login, not named
        mpo._who(BIZ, stranger)
    assert e.value.status_code == 403
    office["contacts"] = None                                    # the records didn't load: try again, not "no"
    with pytest.raises(HTTPException) as e:
        mpo._who(BIZ, media)
    assert e.value.status_code == 503
    office["contacts"] = [{"id": ED, "email": "Media@Example.test"}]
    office["biz"] = _biz({"photo_editors": []})
    with pytest.raises(HTTPException) as e:
        mpo._who(BIZ, media)
    assert e.value.status_code == 403
    office["biz"] = {**_biz(), "type": "salon"}                   # not a church: no member app
    with pytest.raises(HTTPException) as e:
        mpo._who(BIZ, owner)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        mpo._who("../x", owner)
    assert e.value.status_code == 404


# ─── Pictures from the office: what's where ─────────────────────────


def test_every_spot_with_what_it_shows_its_look_and_where_it_came_from(monkeypatch):
    import member_app_photos as photos
    monkeypatch.setattr(photos, "photos", lambda biz, site, limit=None: ["https://cdn.example/site-1.jpg"])
    monkeypatch.setattr(photos, "series_art", lambda site, title: "/public/site-assets/lcc/series-to-the-future.webp"
                        if title == "To the Future" else "")
    import member_yt_pictures as myp
    monkeypatch.setattr(myp, "sign", lambda name: "sig")
    biz = _biz({"pictures": {"home": {"url": "https://cdn.example/site-1.jpg", "look": "church"},
                             "give": {"url": "https://cdn.example/up.webp", "look": "bw"},
                             "live": {"url": ""}}})
    lib = {"sermons": [{"id": "s1", "title": "Pressing On", "video_url": "https://youtu.be/AAAAAAAAAAA", "series_id": None},
                       {"id": "s2", "title": "Week 2", "video_url": "https://youtu.be/BBBBBBBBBBB", "series_id": "x1"}],
           "series": [{"id": "x1", "title": "To the Future"}, {"id": "x2", "title": "Unused"}]}
    out = mpo.listing(biz, None, [], [{"id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd", "name": "Ministers Alliance"}], [], lib)
    by = {s["key"]: s for s in out["spots"]}
    assert (by["home"]["look"], by["home"]["source"]) == ("church", "Your website photo")
    assert (by["give"]["look"], by["give"]["source"]) == ("bw", "Your photo")
    assert by["live"]["url"] == "" and by["live"]["source"] == "No picture: your colour shows"
    assert by["group:dddddddd-dddd-4ddd-8ddd-dddddddddddd"]["group"] == "Groups"
    assert [s["pick"] for s in out["stills"]] == ["yt:AAAAAAAAAAA", "yt:BBBBBBBBBBB"]
    auto = {a["key"]: a for a in out["automatic"]}
    assert auto["message"]["source"] == "Its YouTube still, automatic" and auto["message"]["url"].startswith("/my/yt/")
    assert auto["series:x1"]["url"].endswith("series-to-the-future.webp") and "series:x2" not in auto
    assert [lk["key"] for lk in out["looks"]] == ["colour", "bw", "church"]


# ─── Pictures from the office: saving, through the app's own save ───


def _form(fields, file=None):
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
    return Request({"type": "http", "method": "POST", "path": f"/member-portal/{BIZ}/pictures", "query_string": b"",
                    "headers": [(b"content-type", b"multipart/form-data; boundary=X")]}, receive)


def _jpeg(w=1600, h=900):
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (w, h), (200, 40, 90)).save(out, "JPEG")
    return out.getvalue()


@pytest.fixture
def saving(monkeypatch):
    import member_cache
    import member_photos as ph
    import rate_limit
    state = {"saved": [], "stored": [], "screened": 0, "who": "owner:u-owner"}
    monkeypatch.setattr(mpo, "_who", lambda b, u: (_biz(), state["who"]))
    monkeypatch.setattr(mpo, "_site", lambda biz: None)
    monkeypatch.setattr(rate_limit, "allow_strict", lambda *a: True)
    monkeypatch.setattr(member_cache, "forget_church", lambda b: None)
    monkeypatch.setattr(mapic, "library", lambda biz, site: ["https://cdn.example/a.jpg"])
    monkeypatch.setattr(mapic, "store", lambda b, w: state["stored"].append(len(w)) or "https://cdn.example/up.webp")
    monkeypatch.setattr(mapic, "save_spot",
                        lambda b, key, url, look, **kw: state["saved"].append((key, url, look, kw["by"], kw["uploaded"])) or True)

    async def ok(*a, **kw):
        state["screened"] += 1
        return "ok"
    monkeypatch.setattr(ph, "screen", ok)
    return state


def _post(fields, file=None):
    return asyncio.run(mpo.save_picture(BIZ, _form(fields, file), SimpleNamespace(id="u-owner", email=None)))


def test_the_office_saves_a_pick_an_upload_or_a_message_still(saving, monkeypatch):
    assert _post({"key": "home", "pick": "https://cdn.example/a.jpg", "look": "bw"})["ok"]
    assert saving["saved"][-1] == ("home", "https://cdn.example/a.jpg", "bw", "owner:u-owner", False)
    assert _post({"key": "tile:prayer", "look": "church"}, _jpeg())["ok"]               # an upload: checked, kept
    assert saving["saved"][-1][1:] == ("https://cdn.example/up.webp", "church", "owner:u-owner", True)
    assert saving["screened"] == 1
    import member_portal_sermons as mps
    import member_yt_pictures as myp
    monkeypatch.setattr(mps, "load_library", lambda b: {"sermons": [{"video_url": "https://youtu.be/AAAAAAAAAAA"}]})
    monkeypatch.setattr(myp, "get", lambda vid, wide: _jpeg(1280, 720) if (vid, wide) == ("AAAAAAAAAAA", True) else None)
    assert _post({"key": "home", "pick": "yt:AAAAAAAAAAA", "look": "colour"})["ok"]     # one of the church's own
    assert saving["saved"][-1][1] == "https://cdn.example/up.webp" and saving["screened"] == 1
    for bad, code in (({"key": "home", "pick": "yt:CCCCCCCCCCC"}, 400),                 # not one of theirs
                      ({"key": "home", "pick": "https://evil.example/x.jpg"}, 400),     # not the church's photo
                      ({"key": "../settings", "pick": "default"}, 400)):
        with pytest.raises(HTTPException) as e:
            _post(bad)
        assert e.value.status_code == code
    with pytest.raises(HTTPException) as e:
        _post({"key": "home"}, b"not a photo")
    assert e.value.status_code == 400 and "JPG, PNG or WebP" in e.value.detail
    saving["who"] = f"member:{ED}"
    out = asyncio.run(mpo.remove_picture(BIZ, {"key": "event:supper-house"}, SimpleNamespace(id="u", email=None)))
    assert out["ok"] and saving["saved"][-1][:2] == ("event:supper-house", "") and saving["saved"][-1][3] == f"member:{ED}"


def test_a_picture_the_check_turns_down_or_cant_check_saves_nothing(saving, monkeypatch):
    import member_photos as ph

    async def no(*a, **kw):
        return "no"

    async def down(*a, **kw):
        raise ph.ScreenUnavailable("x")
    for screen, code in ((no, 400), (down, 503)):
        monkeypatch.setattr(ph, "screen", screen)
        with pytest.raises(HTTPException) as e:
            _post({"key": "home"}, _jpeg())
        assert e.value.status_code == code
    assert not saving["saved"]


def test_the_office_routes_are_mounted_before_the_catch_all():
    import kmj_intake_automation as app_mod
    routes = [(getattr(r, "path", ""), getattr(r, "methods", set()) or set()) for r in app_mod.app.routes]
    paths = [p for p, _ in routes]
    catch = next(i for i, p in enumerate(paths) if "{full_path" in p or p.endswith("{path:path}"))
    for path, method in (("/member-portal/{business_id}/pictures", "GET"), ("/member-portal/{business_id}/pictures", "POST"),
                         ("/member-portal/{business_id}/pictures/remove", "POST")):
        assert next(i for i, (p, m) in enumerate(routes) if p == path and method in m) < catch
