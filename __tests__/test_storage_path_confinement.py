"""
test_storage_path_confinement.py — a service-role write stays inside the
caller's own business folder.

THE DEFECT (Codex review of #1464, 2026-10-16): #1464 moved the
site_images writer to the service role, which bypasses storage's
per-business policy, but the storage key was still glued together from
request strings. /slots/_diag/dalle checks that the caller is an admin
of business A, then hands the caller's own `slot_name` to
download_and_rehost, which built

    f"{business_id}/{slot_name}_{ts}_{quality}.png"

A slot_name of "../<B>/existing.png#" makes that
"<A>/../<B>/existing.png#_1760000000_standard.png", and httpx normalises
the request target to /storage/v1/object/site_images/<B>/existing.png.
With x-upsert on, that replaces business B's file. Nothing about B was
ever checked.

The fix: a key is built only from the canonical business UUID and a
plain file name (storage_links.business_object_key), the writers refuse
any other key before they send anything, generation refuses an unsafe
slot name before it spends, and the diagnostic takes only slot names the
server defines.

The fake network below records the request target httpx would really
send (httpx.URL(...).raw_path), so a traversal shows up as the victim's
path, exactly as it would on the wire.
"""
import io
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

import brand_engine
import business_users_router
import sb_clients
import storage_links
from agents.slot_system import dalle_client
from agents.slot_system import router as slot_router

A = "009e9a2c-3e81-4bfc-a92a-205a8806aa99"   # the caller's business
B = "12773842-3cc6-41a7-9094-b8606e3f7549"   # someone else's
OWNER_A, ADMIN_A, OWNER_B = "user-owner-a", "user-admin-a", "user-owner-b"
ROLES = {(A, OWNER_A): "owner", (A, ADMIN_A): "admin", (B, OWNER_B): "owner"}


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (40, 90, 200)).save(buf, "PNG")
    return buf.getvalue()


PNG = _png()


class _Net:
    """httpx.Client stand-in: OpenAI answers with a temporary image URL,
    the download returns a PNG, and storage records the request target
    httpx would actually put on the wire."""

    def __init__(self):
        self.writes = []
        self.openai_calls = 0

    def __call__(self, *a, **kw):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, content=None, headers=None, **kw):
        if url == dalle_client.OPENAI_IMAGES_ENDPOINT:
            self.openai_calls += 1
            return httpx.Response(200, json={"data": [
                {"url": "https://images.test/tmp.png", "revised_prompt": "p"}]})
        self.writes.append(httpx.URL(url).raw_path.decode())
        return httpx.Response(200, json={"Key": "ok"})

    def get(self, url, **kw):
        return httpx.Response(200, content=PNG)


@pytest.fixture
def net(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://sb.test")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    fake = _Net()
    monkeypatch.setattr(dalle_client.httpx, "Client", fake)
    monkeypatch.setattr(dalle_client, "can_dalle_generate", lambda b, c: (True, 0.0))
    monkeypatch.setattr(dalle_client, "_log_dalle_spend", lambda **kw: None)
    return fake


def _businesses(path, *a, **kw):
    # Like Postgres: a uuid compares case-blind and comes back lowercase.
    if path.startswith("/businesses?id=eq."):
        biz = path.split("id=eq.", 1)[1].split("&", 1)[0].lower()
        owner = {A: OWNER_A, B: OWNER_B}.get(biz)
        return [{"id": biz, "owner_id": owner}] if owner else []
    return []


@pytest.fixture
def diag(monkeypatch, net):
    """POST /slots/_diag/dalle as a signed-in user, with real access checks
    over a two-business fake database."""
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _businesses)
    monkeypatch.setattr(business_users_router, "role_of",
                        lambda biz, uid: ROLES.get((biz, str(uid))))
    monkeypatch.setattr(slot_router, "can_dalle_generate", lambda b, c: (True, 0.0))
    monkeypatch.setattr(slot_router, "get_site_dalle_spend_today", lambda b: 0.0)
    persisted = []
    monkeypatch.setattr(slot_router.slot_storage, "set_slot_default",
                        lambda **kw: persisted.append(kw) or True)
    app = FastAPI()
    app.include_router(slot_router.router)
    who = {"id": ADMIN_A}
    app.dependency_overrides[sb_clients.authed_request] = (
        lambda: SimpleNamespace(user=SimpleNamespace(id=who["id"])))
    client = TestClient(app)

    def post(slot_name, business_id=A, user=ADMIN_A):
        who["id"] = user
        return client.post("/slots/_diag/dalle", json={
            "business_id": business_id, "slot_name": slot_name, "quality": "standard"})
    post.net = net
    post.persisted = persisted
    return post


# ── The reproduced attack: A's admin aims the diagnostic at B ────────

TRAVERSALS = [
    f"../{B}/existing.png#",                 # the one Codex reproduced
    f"../{B}/existing.png?",
    f"hero_main/../../{B}/existing.png#",
    f"..%2F{B}%2Fexisting.png#",             # encoded separators
    f"%2e%2e/{B}/existing.png#",             # encoded dots
    f"..\\{B}\\existing.png#",               # backslashes
    "hero_main#",
    "hero_main/extra",
    "",
]


@pytest.mark.parametrize("slot_name", TRAVERSALS)
def test_an_admin_of_one_business_cannot_write_into_another(diag, slot_name):
    r = diag(slot_name)
    assert r.status_code == 400, r.text
    assert diag.net.writes == [], f"storage was written: {diag.net.writes}"
    assert diag.net.openai_calls == 0, "refused before anything was paid for"
    assert diag.persisted == []


def test_a_real_slot_writes_only_under_the_callers_business(diag):
    r = diag("hero_main")
    assert r.status_code == 200, r.text
    assert len(diag.net.writes) == 1
    assert diag.net.writes[0].startswith(f"/storage/v1/object/site_images/{A}/hero_main_")


def test_the_folder_is_the_canonical_id_however_the_request_spelled_it(diag):
    r = diag("hero_main", business_id=A.upper())
    assert r.status_code == 200, r.text
    assert diag.net.writes[0].startswith(f"/storage/v1/object/site_images/{A}/")


@pytest.mark.parametrize("business_id", [f"{A}/../{B}", f"{A}/x", "not-a-uuid", ""])
def test_a_business_id_that_is_not_a_plain_uuid_is_not_found(diag, business_id):
    r = diag("hero_main", business_id=business_id)
    assert r.status_code == 404, r.text
    assert diag.net.writes == []


def test_a_stranger_to_the_business_is_refused_before_anything_runs(diag):
    r = diag("hero_main", business_id=B, user=ADMIN_A)
    assert r.status_code == 404, r.text
    assert diag.net.writes == [] and diag.net.openai_calls == 0


# ── The writers themselves refuse a key outside one business folder ──

UNSAFE_KEYS = [
    f"{A}/../{B}/existing.png",
    f"{A}/x.png#_1_hd.png",
    f"{A}/x.png?v=1",
    f"../{B}/x.png",
    f"{A}/sub/x.png",
    f"{A}/..%2F{B}.png",
    f"{A}/.png",
    f"{A}/x.svg",
    f"{A}/x.html",
    f"{A.upper()}/x.png",
    "not-a-uuid/x.png",
    f"brand/{A}/x.png",
    A,
]


@pytest.mark.parametrize("path", UNSAFE_KEYS)
def test_the_site_image_writer_refuses_a_key_outside_one_business(net, path):
    up = dalle_client._upload_site_image_debug(path, PNG, "image/png")
    assert up["status"] == "unsafe_path", up
    assert net.writes == []
    assert dalle_client.upload_failure_words(up) == storage_links.UPLOAD_UNSAFE_PATH


def test_rehost_refuses_an_unsafe_slot_name_before_it_writes(net):
    got = dalle_client.download_and_rehost(
        "https://images.test/tmp.png", A, f"../{B}/existing.png#")
    assert got is None
    assert net.writes == []


@pytest.mark.parametrize("generate", ["generate_dalle_image", "generate_dalle_image_debug"])
def test_generation_refuses_an_unsafe_slot_name_before_it_spends(net, generate):
    out = getattr(dalle_client, generate)("a calm photo", A, f"../{B}/existing.png#")
    assert not out or out.get("status") == "unsafe_slot_name", out
    assert net.openai_calls == 0
    assert net.writes == []


@pytest.mark.parametrize("path", [f"brand/{A}/../{B}/primary.png", f"brand/{A}/p.png#",
                                  f"{A}/primary.png", f"brand/not-a-uuid/p.png",
                                  f"brand/{A}/p.svg"])
def test_the_brand_writer_refuses_a_key_outside_one_business(monkeypatch, net, path):
    monkeypatch.setattr(brand_engine.httpx, "Client", net)
    url, reason = brand_engine._storage_upload(path, PNG, "image/png")
    assert url is None
    assert reason == storage_links.UPLOAD_UNSAFE_PATH
    assert net.writes == []


# ── The key builder ──────────────────────────────────────────────────

def test_business_object_key_builds_only_from_trusted_parts():
    assert storage_links.business_object_key(A.upper(), "hero_main_1_hd.png") == \
        f"{A}/hero_main_1_hd.png"
    assert storage_links.business_object_key(A, "primary-1.png", prefix="brand/") == \
        f"brand/{A}/primary-1.png"
    for biz, name in [(f"{A}/../{B}", "x.png"), (A, "../x.png"), (A, "x.png#"),
                      (A, "a/b.png"), (A, "x"), ("", "x.png"), (A, "x.svg"),
                      (A, "x.png\n"), (A + "/x", "x.png")]:
        with pytest.raises(ValueError):
            storage_links.business_object_key(biz, name)


# ── The other two upload routes, whole ───────────────────────────────
#
# Studio drop (POST /composer/drop/upload: owner or a member seat) and
# slot upload (POST /slots/{business_id}/{slot}/upload: admin). Real
# access checks over the two-business fake; every refusal writes
# nothing, every permitted write lands under the caller's business.

MEMBER_A, VIEWER_A, STRANGER = "user-member-a", "user-viewer-a", "user-stranger"
SEATS_A = {OWNER_A: "owner", ADMIN_A: "admin", MEMBER_A: "member", VIEWER_A: "viewer"}


def _photo(size=(256, 256)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (30, 120, 60)).save(buf, "JPEG")
    return buf.getvalue()


PHOTO = _photo()


def _routes(monkeypatch, net, include):
    monkeypatch.setattr(sb_clients, "sb_get_as_service", _businesses)
    monkeypatch.setattr(business_users_router, "role_of",
                        lambda biz, uid: SEATS_A.get(str(uid)) if biz.lower() == A
                        else ROLES.get((biz.lower(), str(uid))))
    bare, app = FastAPI(), FastAPI()
    include(bare)
    include(app)
    who = {"id": OWNER_A}
    app.dependency_overrides[sb_clients.authed_request] = (
        lambda: SimpleNamespace(user=SimpleNamespace(id=who["id"]), jwt="test-jwt"))
    signed_in, signed_out = TestClient(app), TestClient(bare)

    def client(user):
        who["id"] = user
        return signed_out if user is None else signed_in
    return client


@pytest.fixture
def drop(monkeypatch, net):
    import site_composer
    monkeypatch.setattr(site_composer, "drop_fill",
                        lambda body, session: {"ok": True, "slot": body.slot,
                                               "business_id": body.business_id})
    client = _routes(monkeypatch, net, lambda app: app.include_router(site_composer.router))

    def post(user, business_id=A, data=PHOTO, mime="image/jpeg", slot="hero"):
        return client(user).post("/composer/drop/upload",
                                 data={"business_id": business_id, "slot": slot},
                                 files={"file": ("photo.jpg", data, mime)})
    post.net = net
    return post


@pytest.fixture
def slot_upload(monkeypatch, net):
    monkeypatch.setattr(slot_router.slot_storage, "set_slot_custom", lambda **kw: True)
    monkeypatch.setattr(slot_router, "_refresh_composed", lambda b: None)
    monkeypatch.setattr(slot_router, "_slot_record_for_response", lambda b, s: {})
    client = _routes(monkeypatch, net, lambda app: app.include_router(slot_router.router))

    def post(user, business_id=A, slot="hero_main", data=PHOTO, mime="image/jpeg"):
        return client(user).post(f"/slots/{business_id}/{slot}/upload",
                                 files={"file": ("photo.jpg", data, mime)})
    post.net = net
    return post


def test_drop_signed_out_writes_nothing(drop):
    assert drop(None).status_code == 401
    assert drop.net.writes == []


@pytest.mark.parametrize("user", [STRANGER, VIEWER_A, OWNER_B])
def test_drop_refuses_anyone_without_a_member_seat(drop, user):
    r = drop(user)
    assert r.status_code in (403, 404), r.text
    assert drop.net.writes == []


@pytest.mark.parametrize("user", [OWNER_A, ADMIN_A, MEMBER_A])
def test_drop_writes_only_under_the_callers_business(drop, user):
    r = drop(user, slot=f"../{B}/existing")
    assert r.status_code == 200, r.text
    [target] = drop.net.writes
    assert target.startswith(f"/storage/v1/object/site_images/{A}/drop____{B}_existing_")
    assert target.endswith(".jpg")


@pytest.mark.parametrize("business_id", [f"{A}/../{B}", "not-a-uuid", A + "&id=eq." + B])
def test_drop_cannot_be_aimed_at_another_business(drop, business_id):
    r = drop(OWNER_A, business_id=business_id)
    assert r.status_code == 404, r.text
    assert drop.net.writes == []


@pytest.mark.parametrize("data", [b"<svg onload='alert(1)'></svg>", b"not a photo",
                                  b"\xff\xd8\xff<script>alert(1)</script>", b""])
def test_drop_refuses_bytes_that_are_not_a_photo(drop, data):
    r = drop(OWNER_A, data=data)
    assert r.status_code == 400, r.text
    assert drop.net.writes == []


def test_drop_stores_what_the_bytes_are_not_what_the_browser_said(drop):
    png = io.BytesIO()
    Image.new("RGB", (256, 256)).save(png, "PNG")
    r = drop(OWNER_A, data=png.getvalue(), mime="image/jpeg")
    assert r.status_code == 200, r.text
    assert drop.net.writes[0].endswith(".png")


def test_slot_upload_signed_out_writes_nothing(slot_upload):
    assert slot_upload(None).status_code == 401
    assert slot_upload.net.writes == []


@pytest.mark.parametrize("user", [STRANGER, VIEWER_A, MEMBER_A, OWNER_B])
def test_slot_upload_refuses_anyone_below_admin(slot_upload, user):
    r = slot_upload(user)
    assert r.status_code == 404, r.text
    assert slot_upload.net.writes == []


@pytest.mark.parametrize("user", [OWNER_A, ADMIN_A])
def test_slot_upload_writes_only_under_the_callers_business(slot_upload, user):
    r = slot_upload(user, business_id=A.upper())
    assert r.status_code == 200, r.text
    [target] = slot_upload.net.writes
    assert target.startswith(f"/storage/v1/object/site_images/{A}/custom_hero_main_")


def test_slot_upload_takes_only_defined_slots(slot_upload):
    r = slot_upload(OWNER_A, slot="not_a_slot")
    assert r.status_code == 404, r.text
    assert slot_upload.net.writes == []


# ── Pictures that don't decode (Codex re-check, 2026-10-16) ──────────
#
# img.verify() checks a file's structure, not its pixels: a JPEG missing
# its last bytes passed it and was stored. AVIF was taken on its
# signature alone whenever this Pillow couldn't decode AVIF, so
# `ftypavif` followed by anything was stored as image/avif. A picture is
# now stored only after it decodes, within a pixel budget.

def _noisy_jpeg(size=(128, 128)) -> bytes:
    import os
    buf = io.BytesIO()
    Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3)).save(buf, "JPEG")
    return buf.getvalue()


def _png_claiming(width: int, height: int) -> bytes:
    """A real 8x8 PNG whose header (with a valid CRC) claims width x height."""
    import struct
    import zlib
    png = bytearray(PNG)
    png[16:24] = struct.pack(">II", width, height)
    png[29:33] = struct.pack(">I", zlib.crc32(bytes(png[12:29])))
    return bytes(png)


def _avif():
    try:
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), (200, 10, 10)).save(buf, "AVIF")
        return buf.getvalue()
    except Exception:  # noqa: BLE001 — this Pillow can't write AVIF
        return None


NOISY_JPEG = _noisy_jpeg()
FAKE_AVIF = b"\x00\x00\x00\x18ftypavif" + b"not an image"
REAL_AVIF = _avif()
needs_avif = pytest.mark.skipif(REAL_AVIF is None, reason="this Pillow can't write AVIF")


@pytest.mark.parametrize("cut", [2, 10, 30, 50])
def test_drop_refuses_a_truncated_jpeg(drop, cut):
    r = drop(OWNER_A, data=NOISY_JPEG[:-cut])
    assert r.status_code == 400, r.text
    assert drop.net.writes == []


@pytest.mark.parametrize("decoder", [False, True], ids=["no-avif-decoder", "avif-decoder"])
def test_drop_refuses_a_malformed_avif(drop, monkeypatch, decoder):
    import upload_images
    monkeypatch.setattr(upload_images, "_pillow_reads_avif", lambda: decoder)
    r = drop(OWNER_A, data=FAKE_AVIF, mime="image/avif")
    assert r.status_code == 400, r.text
    assert drop.net.writes == []


def test_drop_refuses_an_avif_this_server_cannot_decode_and_says_so(drop, monkeypatch):
    import upload_images
    monkeypatch.setattr(upload_images, "_pillow_reads_avif", lambda: False)
    r = drop(OWNER_A, data=REAL_AVIF or FAKE_AVIF, mime="image/avif")
    assert r.status_code == 400, r.text
    assert "AVIF" in r.json()["detail"] and "JPG" in r.json()["detail"]
    assert drop.net.writes == []


@needs_avif
def test_drop_stores_an_avif_that_decodes(drop):
    r = drop(OWNER_A, data=REAL_AVIF, mime="image/avif")
    assert r.status_code == 200, r.text
    [target] = drop.net.writes
    assert target.endswith(".avif")


@needs_avif
def test_drop_refuses_a_truncated_avif(drop):
    r = drop(OWNER_A, data=REAL_AVIF[:-30], mime="image/avif")
    assert r.status_code == 400, r.text
    assert drop.net.writes == []


def test_drop_refuses_a_picture_too_big_to_decode_safely(drop):
    # 81 megapixels from a few hundred bytes: refused before any pixel is decoded.
    r = drop(OWNER_A, data=_png_claiming(9000, 9000), mime="image/png")
    assert r.status_code == 400, r.text
    assert drop.net.writes == []


def test_drop_still_stores_a_whole_jpeg(drop):
    r = drop(OWNER_A, data=NOISY_JPEG)
    assert r.status_code == 200, r.text
    assert drop.net.writes[0].endswith(".jpg")


def _ultra_hdr_like() -> bytes:
    """A JPEG with a multi-picture block and a second picture after it,
    the way an Android Ultra HDR photo carries its gain map. Pillow
    opens it as MPO."""
    import os
    buf = io.BytesIO()
    Image.frombytes("RGB", (96, 96), os.urandom(96 * 96 * 3)).save(
        buf, "MPO", save_all=True, append_images=[Image.new("L", (48, 48), 128)])
    return buf.getvalue()


ULTRA_HDR = _ultra_hdr_like()


def test_drop_stores_a_multi_picture_phone_jpeg_as_a_jpeg(drop):
    r = drop(OWNER_A, data=ULTRA_HDR)
    assert r.status_code == 200, r.text
    assert drop.net.writes[0].endswith(".jpg")


def test_drop_refuses_a_multi_picture_jpeg_cut_short(drop):
    r = drop(OWNER_A, data=ULTRA_HDR[:-30])
    assert r.status_code == 400, r.text
    assert drop.net.writes == []
