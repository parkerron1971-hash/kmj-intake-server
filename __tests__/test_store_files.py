"""Digital delivery — hosted product files + validated downloads.

The contract under test:
  • upload is manager+ (member 403), cross-tenant offering ids read as
    404, and only sellable categories accept a file;
  • re-upload with a new filename deletes the old storage object;
  • the anon download validates the derived HMAC token, the order's
    paid state, and the offering's membership in the order before
    302-ing to a short-lived signed URL;
  • the receipt email carries a download link for digital items ONLY;
  • account deletion sweeps the product-files bucket.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

_here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(_here.parent))
sys.path.insert(0, str(_here))

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from test_i2_gl_sync import FakeSB  # noqa: E402

BIZ = "b1"
OTHER_BIZ = "b2"
OFF_DIGITAL = "off_digital"
OFF_PHYSICAL = "off_physical"
OFF_SERVICE = "off_service"
OFF_FOREIGN = "off_foreign"
ORDER = "ord1"


def _user(uid: str):
    return type("U", (), {"id": uid, "email": f"{uid}@x.com"})()


class _FakeUpload:
    def __init__(self, name="Guide.pdf", content=b"%PDF-fake",
                 content_type="application/pdf"):
        self.filename = name
        self.content_type = content_type
        self._chunks = [content]

    async def read(self, n=-1):
        return self._chunks.pop(0) if self._chunks else b""


class _FakeRequest:
    headers: dict = {}
    client = None


@pytest.fixture
def fake(monkeypatch):
    fb = FakeSB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", fb.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service",
                        lambda p, b, prefer="rep": fb.post(p, b, prefer))
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", fb.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", fb.delete)
    monkeypatch.setenv("CUSTOMER_TOKEN_SECRET", "test-secret")

    fb.rows("businesses").append({
        "id": BIZ, "owner_id": "owner1", "name": "Studio One",
        "settings": {}, "stripe_account_id": "acct_1"})
    fb.rows("businesses").append({
        "id": OTHER_BIZ, "owner_id": "owner2", "name": "Other",
        "settings": {}})
    fb.rows("business_users").append({
        "id": "seat_m", "business_id": BIZ, "user_id": "member1",
        "role": "member", "status": "active"})
    fb.rows("business_users").append({
        "id": "seat_g", "business_id": BIZ, "user_id": "manager1",
        "role": "manager", "status": "active"})
    fb.rows("offerings").append({
        "id": OFF_DIGITAL, "business_id": BIZ, "name": "The Guide",
        "category": "product", "is_active": True, "current_price": 29})
    fb.rows("offerings").append({
        "id": OFF_PHYSICAL, "business_id": BIZ, "name": "Mug",
        "category": "product", "is_active": True, "current_price": 15})
    fb.rows("offerings").append({
        "id": OFF_SERVICE, "business_id": BIZ, "name": "Coaching",
        "category": "session", "is_active": True, "current_price": 100})
    fb.rows("offerings").append({
        "id": OFF_FOREIGN, "business_id": OTHER_BIZ, "name": "Not yours",
        "category": "product", "is_active": True, "current_price": 5})
    return fb


@pytest.fixture
def storage(monkeypatch):
    """Mocked storage plumbing — records calls, never talks to Supabase."""
    import store_files
    calls = {"uploads": [], "deletes": [], "signs": []}
    monkeypatch.setattr(store_files, "storage_upload",
                        lambda path, blob, ct: calls["uploads"].append(
                            (path, len(blob), ct)) or True)
    monkeypatch.setattr(store_files, "storage_delete",
                        lambda path: calls["deletes"].append(path) or True)
    monkeypatch.setattr(
        store_files, "storage_signed_url",
        lambda path, ttl=300, download_as=None: calls["signs"].append(
            (path, download_as)) or f"https://sb.example/signed/{path}?exp=300")
    return calls


def _upload(uid, biz=BIZ, offering=OFF_DIGITAL, **kw):
    import store_files
    return asyncio.run(store_files.upload_product_file(
        biz, offering, file=_FakeUpload(**kw), user=_user(uid)))


# ─── Upload auth matrix + validation ─────────────────────────────────

def test_member_cannot_upload_manager_can(fake, storage):
    with pytest.raises(HTTPException) as e:
        _upload("member1")
    assert e.value.status_code == 403
    out = _upload("manager1")
    assert out["ok"] is True
    assert out["file"]["path"] == f"{BIZ}/{OFF_DIGITAL}/Guide.pdf"
    assert out["file"]["size_bytes"] == len(b"%PDF-fake")
    # Metadata landed in settings.store.product_files.
    biz = fake.rows("businesses")[0]
    assert biz["settings"]["store"]["product_files"][OFF_DIGITAL]["filename"] == "Guide.pdf"


def test_cross_tenant_offering_is_404(fake, storage):
    # owner1 IS an owner — but the offering belongs to another business.
    with pytest.raises(HTTPException) as e:
        _upload("owner1", offering=OFF_FOREIGN)
    assert e.value.status_code == 404
    # A stranger to the business gets 403 before the offering is even read.
    with pytest.raises(HTTPException) as e:
        _upload("owner2", offering=OFF_DIGITAL)
    assert e.value.status_code == 403


def test_non_sellable_category_refused(fake, storage):
    with pytest.raises(HTTPException) as e:
        _upload("owner1", offering=OFF_SERVICE)
    assert e.value.status_code == 400
    assert not storage["uploads"]


def test_reupload_new_name_deletes_old_object(fake, storage):
    _upload("owner1", name="v1.pdf")
    _upload("owner1", name="v2.pdf")
    assert storage["deletes"] == [f"{BIZ}/{OFF_DIGITAL}/v1.pdf"]
    files = fake.rows("businesses")[0]["settings"]["store"]["product_files"]
    assert files[OFF_DIGITAL]["path"] == f"{BIZ}/{OFF_DIGITAL}/v2.pdf"
    # Same name again = in-place upsert, nothing extra deleted.
    _upload("owner1", name="v2.pdf")
    assert storage["deletes"] == [f"{BIZ}/{OFF_DIGITAL}/v1.pdf"]


def test_detach_removes_object_and_metadata(fake, storage):
    import store_files
    _upload("owner1")
    out = store_files.delete_product_file(BIZ, OFF_DIGITAL, user=_user("owner1"))
    assert out["ok"] is True
    assert f"{BIZ}/{OFF_DIGITAL}/Guide.pdf" in storage["deletes"]
    assert fake.rows("businesses")[0]["settings"]["store"]["product_files"] == {}
    with pytest.raises(HTTPException) as e:
        store_files.delete_product_file(BIZ, OFF_DIGITAL, user=_user("owner1"))
    assert e.value.status_code == 404


def test_safe_filename():
    import store_files
    assert store_files.safe_filename("../../etc/passwd") == "passwd"
    assert store_files.safe_filename("My Course (final).zip") == "My_Course_final_.zip"
    assert store_files.safe_filename("") == "download"


# ─── Download: token, state, membership ──────────────────────────────

def _seed_order(fb, status="paid"):
    fb.rows("orders").append({
        "id": ORDER, "business_id": BIZ, "status": status,
        "paid_at": "2026-07-31T00:00:00Z" if status != "pending" else None,
        "total_cents": 2900, "customer_email": "buyer@x.com"})
    fb.rows("order_items").append({
        "id": "oi1", "order_id": ORDER, "offering_id": OFF_DIGITAL,
        "name_at_purchase": "The Guide", "unit_amount_cents": 2900,
        "quantity": 1})
    fb.rows("order_items").append({
        "id": "oi2", "order_id": ORDER, "offering_id": OFF_PHYSICAL,
        "name_at_purchase": "Mug", "unit_amount_cents": 1500,
        "quantity": 1})


def test_download_happy_path_302_signed(fake, storage):
    import store_files
    _upload("owner1")
    _seed_order(fake)
    token = store_files.order_download_token(ORDER)
    resp = store_files.public_download(ORDER, token, OFF_DIGITAL, _FakeRequest())
    assert resp.status_code == 302
    assert resp.headers["location"].startswith(
        f"https://sb.example/signed/{BIZ}/{OFF_DIGITAL}/Guide.pdf")
    assert storage["signs"] == [(f"{BIZ}/{OFF_DIGITAL}/Guide.pdf", "Guide.pdf")]


def test_download_wrong_token_404(fake, storage):
    import store_files
    _upload("owner1")
    _seed_order(fake)
    for bad in ("nope", store_files.order_download_token("other-order"), ""):
        with pytest.raises(HTTPException) as e:
            store_files.public_download(ORDER, bad, OFF_DIGITAL, _FakeRequest())
        assert e.value.status_code == 404


def test_download_unpaid_order_refused(fake, storage):
    import store_files
    _upload("owner1")
    _seed_order(fake, status="pending")
    token = store_files.order_download_token(ORDER)
    with pytest.raises(HTTPException) as e:
        store_files.public_download(ORDER, token, OFF_DIGITAL, _FakeRequest())
    assert e.value.status_code == 403
    assert not storage["signs"]


def test_download_offering_not_in_order_404(fake, storage):
    import store_files
    _upload("owner1")
    _seed_order(fake)
    token = store_files.order_download_token(ORDER)
    with pytest.raises(HTTPException) as e:
        store_files.public_download(ORDER, token, OFF_SERVICE, _FakeRequest())
    assert e.value.status_code == 404
    # In the order but no file attached → honest 404, no signing.
    with pytest.raises(HTTPException) as e:
        store_files.public_download(ORDER, token, OFF_PHYSICAL, _FakeRequest())
    assert e.value.status_code == 404
    assert not storage["signs"]


def test_fulfilled_order_still_downloads(fake, storage):
    import store_files
    _upload("owner1")
    _seed_order(fake, status="fulfilled")
    token = store_files.order_download_token(ORDER)
    resp = store_files.public_download(ORDER, token, OFF_DIGITAL, _FakeRequest())
    assert resp.status_code == 302


# ─── Receipt email: links for digital items only ─────────────────────

def test_receipt_email_links_digital_items_only(fake, storage, monkeypatch):
    import store_router
    _upload("owner1")
    _seed_order(fake)
    fake.rows("offerings")[1]["fulfillment_note"] = "Ships in 3 days"

    sent = {}

    async def _capture(**kw):
        sent.update(kw)
        return {"ok": True}

    import email_sender
    monkeypatch.setattr(email_sender, "send_via_resend", _capture)
    asyncio.run(store_router._send_receipt(ORDER))

    import store_files
    body = sent["body"]
    link = store_files.download_url(ORDER, OFF_DIGITAL)
    assert link and link in body                     # digital item → link
    assert f"/{OFF_PHYSICAL}" not in body            # physical item → no link
    assert "Ships in 3 days" in body                 # fulfillment_note kept
    assert sent["business_id"] == BIZ


def test_download_url_shape_and_stability(fake, monkeypatch):
    import store_files
    url1 = store_files.download_url(ORDER, OFF_DIGITAL)
    url2 = store_files.download_url(ORDER, OFF_DIGITAL)
    assert url1 == url2                              # stable — email links never rot
    assert url1.startswith("https://kmj-intake-server-production.up.railway.app"
                           "/public/store/download/")
    # No secret configured → no link rather than a broken one.
    monkeypatch.delenv("CUSTOMER_TOKEN_SECRET")
    assert store_files.download_url(ORDER, OFF_DIGITAL) is None


# ─── Thank-you page state + lifecycle sweep ──────────────────────────

def test_thank_you_states(fake, storage):
    import store_router
    _upload("owner1")
    _seed_order(fake, status="pending")
    site = {"business_id": BIZ}
    biz = fake.rows("businesses")[0]
    assert store_router._thank_you_digital(site, biz, ORDER) == {"digital_pending": True}
    fake.rows("orders")[0]["status"] = "paid"
    out = store_router._thank_you_digital(site, biz, ORDER)
    assert [d["name"] for d in out["downloads"]] == ["The Guide"]
    # Someone else's order id on this store's thank-you page → nothing.
    assert store_router._thank_you_digital({"business_id": OTHER_BIZ}, biz, ORDER) == {}


def test_product_files_bucket_is_swept_on_deletion():
    import account_lifecycle
    import store_files
    assert store_files.PRODUCT_BUCKET in account_lifecycle.STORAGE_BUCKETS


def test_order_download_event_is_cataloged():
    import event_spine
    assert "order_download" in event_spine.EVENT_CATALOG
