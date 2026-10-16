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
"""
import httpx
import pytest

import brand_engine
import storage_links
from agents.slot_system import dalle_client

LOVE_CITY = "009e9a2c-3e81-4bfc-a92a-205a8806aa99"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 64

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
    assert "patch" not in business, "nothing is saved to the brand when storage refused"


def test_storage_out_of_reach_says_try_again(monkeypatch, env, business):
    _storage(monkeypatch, "down")
    res = brand_engine.upload_asset(LOVE_CITY, "primary", PNG, "logo.png", "image/png")
    assert res == {"ok": False, "error": storage_links.UPLOAD_UNREACHABLE}


def test_a_missing_service_key_is_named_not_attempted(monkeypatch, env, business):
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY")
    storage = _storage(monkeypatch)
    res = brand_engine.upload_asset(LOVE_CITY, "primary", PNG, "logo.png", "image/png")
    assert res == {"ok": False, "error": storage_links.UPLOAD_NOT_CONFIGURED}
    assert storage.posts == [], "an anon fallback would only earn the same refusal"


def test_the_checks_before_storage_speak_plainly(env, business):
    big = brand_engine.upload_asset(LOVE_CITY, "favicon", b"x" * (2 * 1024 * 1024),
                                    "icon.png", "image/png")
    assert big["error"].startswith("That file is over the 1 MB limit")
    pdf = brand_engine.upload_asset(LOVE_CITY, "primary", b"%PDF", "logo.pdf", "application/pdf")
    assert "isn't an image" in pdf["error"]
    bmp = brand_engine.upload_asset(LOVE_CITY, "primary", PNG, "logo.bmp", "image/bmp")
    assert bmp["error"].startswith(".bmp files can't be used here")


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
