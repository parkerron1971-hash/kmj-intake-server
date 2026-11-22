"""The member app's icon and opening screen, the church's own (member_app_icon;
Kevin approved the Member page mock's "Icon & opening screen", 2026-11-22).
With nothing chosen, everything stays today's."""
import io

import pytest
from PIL import Image, ImageDraw

import member_app_icon as mic
import member_app_install as mai
import member_app_ui as ui

LOGO_URL = "https://x.supabase.co/storage/v1/object/public/business-assets/b1/logo.png"
PHOTO = "https://x.supabase.co/storage/v1/object/public/business-assets/b1/photo.jpg"


def _png(size=(1200, 400), colour=(255, 255, 255, 255), clear=True):
    im = Image.new("RGBA", size, (0, 0, 0, 0) if clear else (40, 40, 40, 255))
    ImageDraw.Draw(im).rectangle((100, 100, size[0] - 100, size[1] - 100), fill=colour)
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


def _biz(icon=None, **portal):
    mp = dict(portal)
    if icon is not None:
        mp["app_icon"] = icon
    return {"id": "b1", "name": "Cedar Street Church",
            "settings": {"brand_kit": {"logo_url": LOGO_URL, "colors": {"primary": "#c2185b"}}, "member_portal": mp}}


@pytest.fixture(autouse=True)
def pictures(monkeypatch):
    got = {LOGO_URL: _png(), PHOTO: _png((800, 600), (30, 90, 160, 255), clear=False)}
    monkeypatch.setattr(mic, "_kept", lambda url, bid, at, hour: got.get(url))
    for f in (mic._icon, mic._startup, mic._mark_png):
        f.cache_clear()
    mic._KEPT.clear()
    return got


def test_nothing_chosen_changes_nothing():
    biz = _biz()
    pal = ui.palette(biz, {})
    assert mic.choice(biz) is None and mic.icon_png(biz, pal, 512) is None
    assert mic.head_tags(biz, pal) == "" and mic.manifest_overrides(biz, pal) == {}
    assert mai.head_tags(biz) == (
        '<link rel="manifest" href="/my/manifest.webmanifest"><link rel="apple-touch-icon" href="/my/icon-180.png">'
        '<meta name="mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-capable" content="yes">'
        '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">'
        '<meta name="apple-mobile-web-app-title" content="Cedar Street">')
    m = mai.manifest(biz, None)
    assert m["icons"][1]["purpose"] == "any maskable" and "startup" not in str(m)
    assert mai.serve_asset(biz, None, "/my/startup-1170x2532.png").status_code == 404
    for bad in ({"source": "logo"}, {"source": "upload", "background": "black"},     # no upload saved
                {"source": "logo", "background": "photo"}, "logo"):                   # a photo with no photo
        assert mic.choice(_biz(bad)) is None


def test_the_logo_sits_in_the_safe_zone_on_its_background():
    biz = _biz({"source": "logo", "background": "black", "at": "t1"})
    png = mai.icon_png(biz, None, 512)
    im = Image.open(io.BytesIO(png)).convert("RGB")
    assert im.size == (512, 512) and im.getpixel((5, 5)) == (0, 0, 0)
    # every lit pixel is inside the middle circle of 80%
    lit = [(x, y) for y in range(0, 512, 4) for x in range(0, 512, 4) if sum(im.getpixel((x, y))) > 300]
    assert lit and all(((x - 256) ** 2 + (y - 256) ** 2) ** 0.5 <= 0.4 * 512 for x, y in lit)
    white = Image.open(io.BytesIO(mai.icon_png(_biz({"source": "logo", "background": "white", "at": "t1"}), None, 192)))
    assert white.convert("RGB").getpixel((96, 96))[0] < 60                           # a white logo turns dark on white
    colour = Image.open(io.BytesIO(mai.icon_png(_biz({"source": "logo", "background": "colour", "at": "t1"}), None, 192)))
    assert colour.convert("RGB").getpixel((3, 3)) == (0xC2, 0x18, 0x5B)                # the app's colour


def test_an_unreadable_logo_falls_back_to_the_initials(pictures):
    pictures[LOGO_URL] = b"<svg></svg>"
    png = mai.icon_png(_biz({"source": "logo", "background": "black", "at": "t2"}), None, 192)
    assert Image.open(io.BytesIO(png)).size == (192, 192)
    pictures.pop(LOGO_URL)                                         # storage didn't answer: a stand-in, not kept
    r = mai.serve_asset(_biz({"source": "logo", "background": "black", "at": "t2b"}), None, "/my/icon-192.png")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"


def test_an_uploaded_icon_and_a_photo_background(pictures):
    up = "https://x.supabase.co/storage/v1/object/public/business-assets/b1/icon.png"
    pictures[up] = _png((1024, 1024), (10, 200, 120, 255), clear=False)
    biz = _biz({"source": "upload", "background": "black", "at": "t3"}, app_icon_upload=up)
    im = Image.open(io.BytesIO(mai.icon_png(biz, None, 180))).convert("RGB")
    assert im.getpixel((90, 90)) == (10, 200, 120)
    biz = _biz({"source": "logo", "background": "photo", "photo": PHOTO, "ground": "#10325A", "at": "t4"})
    assert mic.manifest_overrides(biz, ui.palette(biz, {}))["background_color"] == "#10325a"


def test_the_opening_screens_and_the_page():
    biz = _biz({"source": "logo", "background": "colour", "at": "t5"}, app_short_name="  Cedar <St>  ")
    pal = ui.palette(biz, {})
    r = mai.serve_asset(biz, None, "/my/startup-1170x2532.png")
    assert r.status_code == 200 and r.headers["etag"] and "max-age" in r.headers["cache-control"]
    im = Image.open(io.BytesIO(r.body))
    assert im.size == (1170, 2532)
    assert mai.is_asset("/my/startup-1170x2532.png") and not mai.is_asset("/my/startup-10x10.png")
    assert mai.serve_asset(biz, None, "/my/startup-1171x2532.png") is None
    assert mai.serve_asset(biz, None, "/my/opening-mark.png").status_code == 200
    head = mai.head_tags(biz, {})
    v = mic.tag(biz, mic.choice(biz), pal)
    assert head.count('rel="apple-touch-startup-image"') == len(mic.DEVICES)
    assert f'href="/my/icon-180.png?v={v}"' in head and 'content="Cedar St"' in head
    assert "(display-mode: standalone)" in head and "sessionStorage" in head and "prefers-reduced-motion" in head
    assert "POWERED BY" in head and "Solutionist" in head
    m = mai.manifest(biz, None)
    assert m["short_name"] == "Cedar St" and m["background_color"] == pal["tint"]
    assert {i["purpose"] for i in m["icons"]} == {"any", "maskable"} and all(f"?v={v}" in i["src"] for i in m["icons"])


def test_the_name_under_the_icon_and_the_owners_choice_are_checked():
    assert mic.clean_short("  Love   City Church ") == "Love City Ch"
    assert mic.clean_short("<b>") == "b" and mic.clean_short("   ") is None and mic.clean_short(5) is None
    biz = _biz()
    assert mic.clean_choice({"source": "logo", "background": "black"}, biz, []) == \
        {"source": "logo", "background": "black", "photo": ""}
    assert mic.clean_choice({"source": "logo", "background": "photo", "photo": PHOTO}, biz, [PHOTO])["photo"] == PHOTO
    assert mic.clean_choice({"source": "logo", "background": "photo", "photo": "https://evil.example/x"}, biz, [PHOTO]) is None
    assert mic.clean_choice({"source": "upload", "background": "black"}, biz, []) is None          # nothing uploaded
    assert mic.clean_choice({"source": "logo", "background": "black"}, {"id": "b", "settings": {}}, []) is None   # no logo
    assert mic.clean_choice({"source": "logo", "background": "pink"}, biz, []) is None


# ─── the office ──────────────────────────────────────────────────────


def _settings(monkeypatch, start=None):
    from types import SimpleNamespace
    import member_portal as mp
    import member_app_pictures as mapic
    stored = {"settings": {"member_portal": {"enabled": True, "epoch": 7, **(start or {})},
                           "brand_kit": {"logo_url": LOGO_URL, "colors": {"primary": "#c2185b"}}}}

    def _owner(b, u):
        if str(u.id) != "u-owner":
            raise mp.HTTPException(403, "not authorized")
        return {"id": "b1", "type": "church", "name": "Cedar Street Church", "settings": dict(stored["settings"])}
    monkeypatch.setattr(mp, "_require_owner", _owner)
    import business_sites_helpers
    monkeypatch.setattr(business_sites_helpers, "ensure_business_site", lambda biz: ({"slug": "cedar", "site_config": {}}, False))
    monkeypatch.setattr(mp.sb_clients, "sb_get_as_service", lambda p: [{"settings": dict(stored["settings"])}])
    monkeypatch.setattr(mapic, "library", lambda biz, site: [PHOTO])

    def _patch(path, body):
        stored["settings"] = body["settings"]
        return [{"id": "b1"}]
    monkeypatch.setattr(mp.sb_clients, "sb_patch_as_service", _patch)
    return stored, SimpleNamespace(id="u-owner", email="pastor@example.test")


def test_the_owner_chooses_the_icon_its_background_and_the_name(monkeypatch):
    import member_portal as mp
    stored, owner = _settings(monkeypatch)
    out = mp.patch_member_portal_config("b1", {}, owner)
    assert out["app_icon"] is None and out["short_name_default"] == "Cedar Street" and out["icon_logo"] == LOGO_URL
    for bad in ({"app_icon": {"source": "logo", "background": "pink"}}, {"app_icon": {"source": "upload", "background": "black"}},
                {"app_icon": {"source": "logo", "background": "photo", "photo": "https://evil.example/x.jpg"}},
                {"app_icon": "logo"}, {"app_short_name": 5}):
        with pytest.raises(mp.HTTPException) as e:
            mp.patch_member_portal_config("b1", bad, owner)
        assert e.value.status_code == 400
    out = mp.patch_member_portal_config("b1", {"app_icon": {"source": "logo", "background": "photo", "photo": PHOTO},
                                               "app_short_name": " Cedar St "}, owner)
    saved = stored["settings"]["member_portal"]
    assert saved["app_icon"]["background"] == "photo" and saved["app_icon"]["ground"].startswith("#") and saved["app_icon"]["at"]
    assert saved["app_short_name"] == "Cedar St" and out["app_short_name"] == "Cedar St"
    assert out["app_icon"]["source"] == "logo"
    mp.patch_member_portal_config("b1", {"app_icon": None, "app_short_name": ""}, owner)
    assert "app_icon" not in stored["settings"]["member_portal"] and "app_short_name" not in stored["settings"]["member_portal"]
    with pytest.raises(mp.HTTPException) as e:
        mp.patch_member_portal_config("b1", {"app_icon": None}, type(owner)(id="someone", email=None))
    assert e.value.status_code == 403


def _upload_req(raw):
    from starlette.requests import Request
    body = (b"--X\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"i.png\"\r\nContent-Type: image/png\r\n\r\n"
            + raw + b"\r\n--X--\r\n")

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    return Request({"type": "http", "method": "POST", "path": "/member-portal/b1/app-icon", "query_string": b"",
                    "headers": [(b"content-type", b"multipart/form-data; boundary=X")]}, receive)


def test_an_uploaded_square_icon_is_checked_kept_and_can_be_chosen(monkeypatch):
    import asyncio
    import member_portal as mp
    import member_photos as ph
    import member_cache
    stored, owner = _settings(monkeypatch)
    monkeypatch.setattr(member_cache, "forget_church", lambda b: None)
    monkeypatch.setattr(mic, "store_icon", lambda b, png: "https://x.supabase.co/storage/v1/object/public/business-assets/b1/brand/icon.png")
    verdicts = ["ok"]

    async def screen(*a, **kw):
        return verdicts[0]
    monkeypatch.setattr(ph, "screen", screen)
    for bad in (_png((1024, 700), clear=False), _png((600, 600), clear=False), b"nope"):   # not square, too small, not a picture
        with pytest.raises(mp.HTTPException) as e:
            asyncio.run(mp.upload_app_icon("b1", _upload_req(bad), owner))
        assert e.value.status_code == 400
    verdicts[0] = "no"
    with pytest.raises(mp.HTTPException):
        asyncio.run(mp.upload_app_icon("b1", _upload_req(_png((1024, 1024), clear=False)), owner))
    assert "app_icon_upload" not in stored["settings"]["member_portal"]
    verdicts[0] = "ok"
    out = asyncio.run(mp.upload_app_icon("b1", _upload_req(_png((1030, 1024), clear=False)), owner))
    assert out["icon_upload"].endswith("/brand/icon.png") and stored["settings"]["member_portal"]["app_icon_upload"]
    out = mp.patch_member_portal_config("b1", {"app_icon": {"source": "upload", "background": "white"}}, owner)
    assert out["app_icon"]["source"] == "upload"
    with pytest.raises(mp.HTTPException) as e:
        asyncio.run(mp.upload_app_icon("b1", _upload_req(_png((1024, 1024), clear=False)), type(owner)(id="x", email=None)))
    assert e.value.status_code == 403


def test_a_new_upload_or_app_colour_is_a_new_address_and_a_failed_read_isnt_kept(pictures, monkeypatch):
    up = "https://x.supabase.co/storage/v1/object/public/business-assets/b1/icon.png"
    c = {"source": "logo", "background": "colour", "at": "t9"}
    a, b = _biz(c), _biz(c, app_icon_upload=up)
    pal = ui.palette(a, {})
    assert mic.tag(a, mic.choice(a), pal) != mic.tag(b, mic.choice(b), pal)              # a new upload
    teal = _biz(c, app_colour="#1f7a8c")
    assert mic.tag(a, mic.choice(a), pal) != mic.tag(teal, mic.choice(teal), ui.palette(teal, {}))   # a new app colour
    reads = []
    monkeypatch.setattr(mic, "_kept", lambda url, bid, at, hour: reads.append(url) or None)
    assert mic._bytes(LOGO_URL, "b1", "t9") is None and mic._bytes(LOGO_URL, "b1", "t9") is None
    assert len(reads) == 2                                                               # tried again


def test_the_icon_upload_is_rate_limited(monkeypatch):
    import asyncio
    import member_portal as mp
    import rate_limit
    stored, owner = _settings(monkeypatch)
    monkeypatch.setattr(rate_limit, "allow_strict", lambda *a: False)
    with pytest.raises(mp.HTTPException) as e:
        asyncio.run(mp.upload_app_icon("b1", _upload_req(_png((1024, 1024), clear=False)), owner))
    assert e.value.status_code == 429


def test_a_photo_background_that_cant_be_read_isnt_saved(monkeypatch, pictures):
    import member_portal as mp
    stored, owner = _settings(monkeypatch)
    pictures.pop(PHOTO)
    with pytest.raises(mp.HTTPException) as e:
        mp.patch_member_portal_config("b1", {"app_icon": {"source": "logo", "background": "photo", "photo": PHOTO}}, owner)
    assert e.value.status_code == 503 and "app_icon" not in stored["settings"]["member_portal"]
