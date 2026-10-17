"""
test_brand_asset_upload.py — a logo upload has to reach storage.

THE DEFECT (2026-10-16, Love City Church, then every business): Brand
Studio answered every logo upload with "Storage upload failed". The
production log said why:

    brand_engine: storage upload brand/009e9a2c-…/primary-20261016114853.png:
    400 {"statusCode":"403","error":"Unauthorized",
         "message":"new row violates row-level security policy"}

brand_engine._storage_upload POSTed with the ANON key. The 2026-08-09
storage write lockdown left business-assets with one insert policy —
`authenticated` plus a business check — and anon fails it. The last
`brand/` object in that bucket is dated 2026-08-05; nothing has landed
since. contract_agent had the same fault and was fixed in the PDF
sweep (test_pdf_delivery.py); brand_engine and the site-image helper
in agents/slot_system/dalle_client.py were missed.

The fake below answers the way live storage does: the anon key gets the
exact refusal above, the service-role key gets 200. So these tests fail
on the old code for the real reason, not a mocked-up one.

SECOND ROUND (Codex review, same day): with the service role the bytes
and the route are the only gates left, so the upload now judges the file
by its bytes (a script-bearing SVG or a text file called logo.png is
refused before storage), and the route is tested whole — signed out,
strangers, seats and owners — with every permitted write landing under
the caller's own business.
"""
import io
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

import brand_engine
import brand_engine_router
import business_users_router
import sb_clients
import storage_links
from auth_supabase import require_user
from agents.slot_system import dalle_client

LOVE_CITY = "009e9a2c-3e81-4bfc-a92a-205a8806aa99"
OTHER_BIZ = "12773842-3cc6-41a7-9094-b8606e3f7549"


def _image(fmt: str, size=(64, 64), **save) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA" if fmt in ("PNG", "WEBP", "ICO") else "RGB", size,
              (200, 40, 90, 255)[: 4 if fmt in ("PNG", "WEBP", "ICO") else 3]).save(buf, fmt, **save)
    return buf.getvalue()


PNG = _image("PNG")
WEBP = _image("WEBP")
JPEG = _image("JPEG")
GIF = _image("GIF")
ICO = _image("ICO", size=(32, 32))
BMP = _image("BMP")
ACTIVE_SVG = (b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" '
              b'onload="alert(document.cookie)"><script>alert(1)</script></svg>')
TEXT_AS_PNG = b"<html><script>alert(1)</script></html>"

RLS_REFUSAL = ('{"statusCode":"403","error":"Unauthorized",'
               '"message":"new row violates row-level security policy"}')


class _Storage:
    """Stands in for httpx.Client against Supabase Storage."""

    def __init__(self, behaviour="live"):
        self.behaviour = behaviour
        self.posts = []

    def __call__(self, *a, **kw):  # httpx.Client(timeout=...) -> self
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, content=None, headers=None, **kw):
        self.posts.append({"url": url, "headers": dict(headers or {}), "bytes": content})
        if self.behaviour == "down":
            raise httpx.ConnectError("connection refused")
        if self.behaviour == "refuse":
            return httpx.Response(400, text=RLS_REFUSAL)
        # "live": what the bucket's policies actually do.
        bearer = (headers or {}).get("Authorization", "")
        if bearer == "Bearer service-key":
            return httpx.Response(200, json={"Key": url.split("/object/", 1)[1]})
        return httpx.Response(400, text=RLS_REFUSAL)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://sb.test")
    monkeypatch.setenv("SUPABASE_ANON", "anon-key")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")


@pytest.fixture
def business(monkeypatch):
    """A business row and a PATCH that records what it was asked to save."""
    saved = {}
    monkeypatch.setattr(brand_engine, "_safe_get_one",
                        lambda t, c, v: {"id": LOVE_CITY, "settings": {}})

    def patch(path, body):
        saved["path"], saved["body"] = path, body
        return [{"id": LOVE_CITY}]
    monkeypatch.setattr(brand_engine, "_sb_patch", patch)
    monkeypatch.setattr(brand_engine, "invalidate_bundle_cache", lambda b: None)
    return saved


def _storage(monkeypatch, behaviour="live"):
    fake = _Storage(behaviour)
    monkeypatch.setattr(brand_engine.httpx, "Client", fake)
    return fake


# ── The upload lands ────────────────────────────────────────────────

def test_a_logo_upload_reaches_storage(monkeypatch, env, business):
    storage = _storage(monkeypatch)
    res = brand_engine.upload_asset(LOVE_CITY, "primary", PNG, "logo.png", "image/png")

    assert res["ok"] is True, res
    assert res["url"].startswith(
        f"https://sb.test/storage/v1/object/public/business-assets/brand/{LOVE_CITY}/primary-")
    kit = business["body"]["settings"]["brand_kit"]
    assert kit["assets"]["primary"] == res["url"]
    assert kit["logo_url"] == res["url"], "primary mirrors to the legacy logo_url"
    assert len(storage.posts) == 1


def test_the_write_goes_out_as_the_service_role_not_anon(monkeypatch, env, business):
    storage = _storage(monkeypatch)
    brand_engine.upload_asset(LOVE_CITY, "primary", PNG, "logo.png", "image/png")
    sent = storage.posts[0]["headers"]
    assert sent["Authorization"] == "Bearer service-key"
    assert sent["apikey"] == "service-key"
    assert "anon-key" not in sent.values()


@pytest.mark.parametrize("variant", sorted(brand_engine.ASSET_VARIANTS))
def test_every_plate_uploads(monkeypatch, env, business, variant):
    _storage(monkeypatch)
    res = brand_engine.upload_asset(LOVE_CITY, variant, PNG, f"{variant}.png", "image/png")
    assert res["ok"] is True, res


def test_a_webp_logo_uploads(monkeypatch, env, business):
    _storage(monkeypatch)
    res = brand_engine.upload_asset(LOVE_CITY, "primary", WEBP, "logo.webp", "image/webp")
    assert res["ok"] is True, res
    assert res["url"].endswith(".webp")


# ── When it doesn't, the practitioner is told why in words ─────────

def test_a_refusal_reads_as_ours_not_theirs(monkeypatch, env, business):
    _storage(monkeypatch, "refuse")
    res = brand_engine.upload_asset(LOVE_CITY, "primary", PNG, "logo.png", "image/png")
    assert res["ok"] is False
    assert res["error"] == storage_links.UPLOAD_REFUSED
    assert "row-level" not in res["error"]
    assert res["error"] != "Storage upload failed"
    assert "path" not in business, "nothing is saved to the brand when storage refused"


def test_storage_out_of_reach_says_try_again(monkeypatch, env, business):
    _storage(monkeypatch, "down")
    res = brand_engine.upload_asset(LOVE_CITY, "primary", PNG, "logo.png", "image/png")
    assert res == {"ok": False, "code": "storage_unreachable",
                   "error": storage_links.UPLOAD_UNREACHABLE}


def test_a_missing_service_key_is_named_not_attempted(monkeypatch, env, business):
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY")
    storage = _storage(monkeypatch)
    res = brand_engine.upload_asset(LOVE_CITY, "primary", PNG, "logo.png", "image/png")
    assert res == {"ok": False, "code": "storage_not_configured",
                   "error": storage_links.UPLOAD_NOT_CONFIGURED}
    assert storage.posts == [], "an anon fallback would only earn the same refusal"


def test_the_checks_before_storage_speak_plainly(monkeypatch, env, business):
    storage = _storage(monkeypatch)
    big = brand_engine.upload_asset(LOVE_CITY, "favicon", b"x" * (2 * 1024 * 1024),
                                    "icon.png", "image/png")
    assert big["error"].startswith("That file is over the 1 MB limit")
    pdf = brand_engine.upload_asset(LOVE_CITY, "primary", b"%PDF-1.7", "logo.pdf", "application/pdf")
    assert pdf["error"] == brand_engine.ASSET_NOT_IMAGE
    bmp = brand_engine.upload_asset(LOVE_CITY, "primary", BMP, "logo.bmp", "image/bmp")
    assert bmp["error"] == brand_engine.ASSET_NOT_IMAGE
    empty = brand_engine.upload_asset(LOVE_CITY, "primary", b"", "logo.png", "image/png")
    assert empty["error"] == brand_engine.ASSET_EMPTY
    assert storage.posts == []


# ── The bytes decide, not the name or the declared type ─────────────

@pytest.mark.parametrize("data,mime,ext", [
    (PNG, "image/png", "png"), (JPEG, "image/jpeg", "jpg"), (WEBP, "image/webp", "webp"),
    (GIF, "image/gif", "gif"), (ICO, "image/x-icon", "ico"),
])
def test_a_real_picture_is_stored_as_what_it_is(monkeypatch, env, business, data, mime, ext):
    storage = _storage(monkeypatch)
    # Declared as something else entirely: the bytes win.
    res = brand_engine.upload_asset(LOVE_CITY, "primary", data, "whatever.txt", "text/plain")
    assert res["ok"] is True, res
    assert res["url"].endswith(f".{ext}")
    assert storage.posts[0]["headers"]["Content-Type"] == mime


def test_a_script_bearing_svg_is_refused_before_storage(monkeypatch, env, business):
    storage = _storage(monkeypatch)
    res = brand_engine.upload_asset(LOVE_CITY, "primary", ACTIVE_SVG, "logo.svg", "image/svg+xml")
    assert res == {"ok": False, "code": "svg_refused", "error": brand_engine.ASSET_SVG}
    assert storage.posts == []
    assert "path" not in business


@pytest.mark.parametrize("data", [
    TEXT_AS_PNG,                                   # a page called logo.png
    b"\x89PNG\r\n\x1a\n" + b"\x00" * 64,           # a PNG signature and nothing real
    PNG[:40],                                      # a truncated PNG
    b"\xff\xd8\xff" + b"<script>alert(1)</script>",
])
def test_non_picture_bytes_labelled_png_are_refused(monkeypatch, env, business, data):
    storage = _storage(monkeypatch)
    res = brand_engine.upload_asset(LOVE_CITY, "primary", data, "logo.png", "image/png")
    assert res["ok"] is False and res["code"] == "not_an_image", res
    assert storage.posts == []


def test_an_upload_lands_under_the_canonical_business_folder(monkeypatch, env, business):
    storage = _storage(monkeypatch)
    res = brand_engine.upload_asset(LOVE_CITY.upper(), "primary", PNG, "logo.png", "image/png")
    assert res["ok"] is True, res
    assert f"/business-assets/brand/{LOVE_CITY}/primary-" in storage.posts[0]["url"]
    assert business["path"] == f"/businesses?id=eq.{LOVE_CITY}"


@pytest.mark.parametrize("business_id", [f"{LOVE_CITY}/../{OTHER_BIZ}", "not-a-uuid", ""])
def test_a_business_id_that_is_not_a_plain_uuid_never_reaches_storage(monkeypatch, env, business,
                                                                      business_id):
    storage = _storage(monkeypatch)
    res = brand_engine.upload_asset(business_id, "primary", PNG, "logo.png", "image/png")
    assert res["ok"] is False and res["code"] == "no_business", res
    assert storage.posts == []


# ── storage_links.upload_refusal reads storage's own status ─────────

@pytest.mark.parametrize("status,body,expected", [
    (400, RLS_REFUSAL, storage_links.UPLOAD_REFUSED),          # the live 2026-10-16 answer
    (403, "", storage_links.UPLOAD_REFUSED),
    (400, '{"statusCode":"413","error":"Payload too large",'
          '"message":"The object exceeded the maximum allowed size"}', storage_links.UPLOAD_TOO_LARGE),
    (400, '{"statusCode":"415","error":"invalid_mime_type",'
          '"message":"mime type image/bmp is not supported"}', storage_links.UPLOAD_WRONG_TYPE),
    (500, "upstream timeout", storage_links.UPLOAD_UNREACHABLE),
    (502, "<html>bad gateway</html>", storage_links.UPLOAD_UNREACHABLE),
])
def test_upload_refusal(status, body, expected):
    assert storage_links.upload_refusal(status, body) == expected


# ── The site-image helper had the same fault ───────────────────────

def test_site_images_upload_as_the_service_role(monkeypatch, env):
    storage = _Storage()
    monkeypatch.setattr(dalle_client.httpx, "Client", storage)
    up = dalle_client._upload_site_image_debug(f"{LOVE_CITY}/drop_hero_1.png", PNG, "image/png")
    assert up["status"] == "ok", up
    assert storage.posts[0]["headers"]["Authorization"] == "Bearer service-key"


def test_a_site_image_refusal_reads_in_words(monkeypatch, env):
    monkeypatch.setattr(dalle_client.httpx, "Client", _Storage("refuse"))
    up = dalle_client._upload_site_image_debug(f"{LOVE_CITY}/drop_hero_1.png", PNG, "image/png")
    assert up["status"] == "http_error"
    assert dalle_client.upload_failure_words(up) == storage_links.UPLOAD_REFUSED


def test_site_images_without_a_service_key_say_so(monkeypatch, env):
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY")
    up = dalle_client._upload_site_image_debug(f"{LOVE_CITY}/x.png", PNG, "image/png")
    assert up == {"status": "no_supabase_env"}
    assert dalle_client.upload_failure_words(up) == storage_links.UPLOAD_NOT_CONFIGURED


# ── The route, whole: who may upload, and where it lands ────────────
#
# Codex (2026-10-16): the tests above call upload_asset directly and so
# skip authentication and the access check. These go through
# POST /brand/asset/upload with the real assert_access over a
# two-business fake database.

OWNER, ADMIN, MEMBER, VIEWER, STRANGER = "u-owner", "u-admin", "u-member", "u-viewer", "u-stranger"
SEATS = {OWNER: "owner", ADMIN: "admin", MEMBER: "member", VIEWER: "viewer"}


def _two_businesses(path, *a, **kw):
    if path.startswith("/businesses?id=eq."):
        biz = path.split("id=eq.", 1)[1].split("&", 1)[0]
        owner = {LOVE_CITY: OWNER, OTHER_BIZ: "u-other-owner"}.get(biz)
        return [{"id": biz, "owner_id": owner}] if owner else []
    return []


@pytest.fixture
def brand_route(monkeypatch, env, business):
    storage = _storage(monkeypatch)
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _two_businesses)
    monkeypatch.setattr(business_users_router, "role_of",
                        lambda biz, uid: SEATS.get(str(uid)) if biz == LOVE_CITY else None)
    bare = FastAPI()                       # the real sign-in check
    bare.include_router(brand_engine_router.router)
    app = FastAPI()
    app.include_router(brand_engine_router.router)
    who = {"id": OWNER}
    app.dependency_overrides[require_user] = (
        lambda: SimpleNamespace(id=who["id"], email=None, role="authenticated"))
    signed_in, signed_out = TestClient(app), TestClient(bare)

    def post(user, business_id=LOVE_CITY, data=PNG, variant="primary", name="logo.png",
             mime="image/png"):
        client = signed_out if user is None else signed_in
        who["id"] = user
        return client.post("/brand/asset/upload",
                           data={"business_id": business_id, "variant": variant},
                           files={"file": (name, data, mime)})
    post.storage = storage
    post.saved = business
    return post


def test_signed_out_is_refused_and_nothing_is_written(brand_route):
    r = brand_route(None)
    assert r.status_code == 401, r.text
    assert brand_route.storage.posts == []


@pytest.mark.parametrize("user", [STRANGER, VIEWER, MEMBER])
def test_anyone_below_admin_is_refused_and_nothing_is_written(brand_route, user):
    r = brand_route(user)
    assert r.status_code == 404, r.text          # same answer as "no such business"
    assert brand_route.storage.posts == []
    assert "path" not in brand_route.saved


@pytest.mark.parametrize("user", [OWNER, ADMIN])
def test_an_owner_or_admin_uploads_into_their_own_business(brand_route, user):
    r = brand_route(user)
    assert r.status_code == 200, r.text
    [post] = brand_route.storage.posts
    assert post["url"].startswith(
        f"https://sb.test/storage/v1/object/business-assets/brand/{LOVE_CITY}/primary-")
    assert brand_route.saved["path"] == f"/businesses?id=eq.{LOVE_CITY}"


@pytest.mark.parametrize("business_id", [OTHER_BIZ, f"{LOVE_CITY}/../{OTHER_BIZ}",
                                         f"{LOVE_CITY}&id=eq.{OTHER_BIZ}", "not-a-uuid"])
def test_an_admin_cannot_aim_the_upload_at_another_business(brand_route, business_id):
    r = brand_route(ADMIN, business_id=business_id)
    assert r.status_code == 404, r.text
    assert brand_route.storage.posts == []


def test_a_refused_file_comes_back_as_plain_words_with_a_code(brand_route):
    r = brand_route(OWNER, data=ACTIVE_SVG, name="logo.svg", mime="image/svg+xml")
    assert r.status_code == 400, r.text
    assert r.json() == {"detail": brand_engine.ASSET_SVG, "code": "svg_refused"}
    assert brand_route.storage.posts == []


def test_a_storage_refusal_through_the_route_is_ours_not_theirs(monkeypatch, brand_route):
    _storage(monkeypatch, "refuse")
    r = brand_route(OWNER)
    assert r.status_code == 502, r.text
    assert r.json() == {"detail": storage_links.UPLOAD_REFUSED, "code": "storage_refused"}


def test_an_oversized_file_is_refused_from_a_bounded_read(brand_route):
    r = brand_route(OWNER, variant="favicon", data=PNG + b"\x00" * (2 * 1024 * 1024))
    assert r.status_code == 400, r.text
    assert r.json()["code"] == "too_large"
    assert brand_route.storage.posts == []


# ── Pictures that don't decode (Codex re-check, 2026-10-16) ──────────
#
# img.verify() checks structure, not pixels, so a JPEG missing its last
# bytes was stored. Now a picture is stored only once it decodes, every
# frame of it, within a pixel budget.

def _noisy(fmt: str, size=(96, 96), frames=1) -> bytes:
    import os
    shots = [Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3))
             for _ in range(frames)]
    if fmt == "GIF":
        shots = [s.convert("P") for s in shots]
    buf = io.BytesIO()
    if frames > 1:
        shots[0].save(buf, fmt, save_all=True, append_images=shots[1:])
    else:
        shots[0].save(buf, fmt)
    return buf.getvalue()


NOISY_JPEG, NOISY_WEBP, NOISY_GIF = _noisy("JPEG"), _noisy("WEBP"), _noisy("GIF", frames=4)


def _png_claiming(width: int, height: int) -> bytes:
    """A real PNG whose header (with a valid CRC) claims width x height."""
    import struct
    import zlib
    png = bytearray(PNG)
    png[16:24] = struct.pack(">II", width, height)
    png[29:33] = struct.pack(">I", zlib.crc32(bytes(png[12:29])))
    return bytes(png)


@pytest.mark.parametrize("data,name,mime", [
    *[(NOISY_JPEG[:-cut], "logo.jpg", "image/jpeg") for cut in (2, 10, 30, 50)],
    (NOISY_WEBP[:-40], "logo.webp", "image/webp"),
    (NOISY_GIF[:-200], "logo.gif", "image/gif"),            # last frame cut short
    (_png_claiming(9000, 9000), "logo.png", "image/png"),   # 81 MP claimed, not decoded
], ids=["jpeg-2", "jpeg-10", "jpeg-30", "jpeg-50", "webp", "gif-frame", "png-81mp"])
def test_a_picture_that_does_not_decode_is_refused_and_nothing_is_written(
        brand_route, data, name, mime):
    r = brand_route(OWNER, data=data, name=name, mime=mime)
    assert r.status_code == 400, r.text
    assert r.json() == {"detail": brand_engine.ASSET_NOT_IMAGE, "code": "not_an_image"}
    assert brand_route.storage.posts == []
    assert "path" not in brand_route.saved


@pytest.mark.parametrize("data,ext", [(NOISY_JPEG, "jpg"), (NOISY_WEBP, "webp"),
                                      (NOISY_GIF, "gif")], ids=["jpeg", "webp", "gif-4-frames"])
def test_a_whole_picture_still_uploads(brand_route, data, ext):
    r = brand_route(OWNER, data=data)
    assert r.status_code == 200, r.text
    [post] = brand_route.storage.posts
    assert post["url"].endswith(f".{ext}")
