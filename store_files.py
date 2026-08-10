"""
store_files.py — hosted digital product delivery (Gumroad-style).

Upgrades the store from "paste a Drive link in fulfillment_note" to:
the practitioner uploads the file INTO the platform, the buyer gets an
instant, validated download link on the receipt email + thank-you page.

Storage: private Supabase bucket `product-files`, object path
`{business_id}/{offering_id}/{filename}`. NO public access — every
download mints a short-lived (300s) signed URL per request via the
service role. The buyer-facing link is STABLE (email links must not
rot); only the storage URL is ephemeral.

"PRIVATE" IS A REQUIREMENT OF THIS MODULE, NOT A DESCRIPTION OF IT.
Audited 2026-08-10: the bucket was public=true. An anonymous GET of
/object/public/product-files/<path> returned 200 with the file body and
no credentials of any kind — which makes the signed URL below, its 300s
expiry, the rate limit, and the HMAC purchase token in front of it all
decorative. Anyone with a path could take a paid file without buying
it.

Nothing had leaked only because the bucket was still empty; it would
have fired the first time a practitioner sold a digital product. Closed
via scripts/close_product_files_bucket.sh, which proves the change by
fetching the same object anonymously before and after.

A test now asserts the bucket flag, so the sentence above is checked
rather than believed. That is the actual lesson: this docstring has
claimed "NO public access" since the day it was written, and the
storage layer never agreed with it.

File METADATA lives in businesses.settings.store.product_files =
{offering_id: {path, filename, size_bytes, content_type, uploaded_at}}
— the settings.superbill.service_codes precedent; no SQL migration.

Download auth: the orders table has no spare secret column, so the
per-order token is DERIVED, not stored — HMAC-SHA256 over the order id
with the same CUSTOMER_TOKEN_SECRET that customer_token.py already
signs customer widget links with. Deterministic → stable forever (no
expiry: a bought file's link must not rot), stateless → zero schema
change, validated by recompute + constant-time compare. The order id
itself is a gen_random_uuid() the buyer received via the Stripe
redirect, so link = two independent unguessables.

Lifecycle: `product-files` is in account_lifecycle.STORAGE_BUCKETS, so
account/business deletion sweeps the objects; the metadata rides in
businesses.settings which the export already includes.

Endpoints:
  POST   /store/products/{biz}/{offering}/file   (manager+, multipart, ≤200MB)
  DELETE /store/products/{biz}/{offering}/file   (manager+)
  GET    /store/products/{biz}/files             (viewer+, metadata map)
  GET    /public/store/download/{order}/{token}/{offering}
         (anon, rate-limited, 302 → 300s signed URL)
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("store_files")

router = APIRouter(tags=["store-files"])

PRODUCT_BUCKET = "product-files"
MAX_FILE_BYTES = 200 * 1024 * 1024  # 200 MB
SIGNED_URL_TTL_SECONDS = 300
_READ_CHUNK = 1024 * 1024

_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _storage_base() -> str:
    return (os.environ.get("SUPABASE_URL") or "").rstrip("/")


def _service_headers() -> Dict[str, str]:
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def safe_filename(name: str) -> str:
    """Strip any path parts, collapse unsafe chars, cap length. Never
    returns an empty string (falls back to 'download')."""
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = _FILENAME_SAFE.sub("_", base).strip("._") or "download"
    if len(base) > 140:
        stem, dot, ext = base.rpartition(".")
        base = (stem[:120] + (("." + ext[:16]) if dot else "")) if stem else base[:140]
    return base


# ─── Storage plumbing (service role; bucket is PRIVATE) ───────────────

def _ensure_bucket(client: httpx.Client) -> None:
    """Create the private bucket if it doesn't exist. Existing buckets
    are never mutated (409/400 'already exists' is success)."""
    r = client.post(f"{_storage_base()}/storage/v1/bucket",
                    headers={**_service_headers(),
                             "Content-Type": "application/json"},
                    json={"id": PRODUCT_BUCKET, "name": PRODUCT_BUCKET,
                          "public": False})
    if r.status_code < 400:
        logger.info(f"[store-files] created private bucket {PRODUCT_BUCKET}")


def storage_upload(path: str, blob: bytes, content_type: str) -> bool:
    """Upload to the private bucket; creates the bucket on first use.
    x-upsert so re-uploading the same path replaces in place."""
    base = _storage_base()
    if not base:
        logger.warning("[store-files] SUPABASE_URL not configured")
        return False
    headers = {**_service_headers(), "Content-Type": content_type,
               "x-upsert": "true"}
    url = f"{base}/storage/v1/object/{PRODUCT_BUCKET}/{path}"
    try:
        with httpx.Client(timeout=httpx.Timeout(connect=10.0, read=120.0,
                                                write=300.0, pool=10.0)) as c:
            r = c.post(url, headers=headers, content=blob)
            if r.status_code >= 400 and "not found" in r.text.lower():
                _ensure_bucket(c)
                r = c.post(url, headers=headers, content=blob)
            if r.status_code >= 400:
                logger.error(f"[store-files] upload {path}: "
                             f"{r.status_code} {r.text[:200]}")
                return False
        return True
    except Exception as e:
        logger.error(f"[store-files] upload {path} failed: {e}")
        return False


def storage_delete(path: str) -> bool:
    """Best-effort object delete (replace-on-reupload + detach)."""
    base = _storage_base()
    if not base:
        return False
    try:
        with httpx.Client(timeout=httpx.Timeout(30.0)) as c:
            r = c.request("DELETE",
                          f"{base}/storage/v1/object/{PRODUCT_BUCKET}",
                          headers={**_service_headers(),
                                   "Content-Type": "application/json"},
                          json={"prefixes": [path]})
        return r.status_code < 400
    except Exception as e:
        logger.warning(f"[store-files] delete {path} failed (non-fatal): {e}")
        return False


def storage_signed_url(path: str,
                       ttl: int = SIGNED_URL_TTL_SECONDS,
                       download_as: Optional[str] = None) -> Optional[str]:
    """Mint a short-lived signed URL for a private object."""
    base = _storage_base()
    if not base:
        return None
    try:
        with httpx.Client(timeout=httpx.Timeout(30.0)) as c:
            r = c.post(f"{base}/storage/v1/object/sign/{PRODUCT_BUCKET}/{path}",
                       headers={**_service_headers(),
                                "Content-Type": "application/json"},
                       json={"expiresIn": ttl})
        if r.status_code >= 400:
            logger.error(f"[store-files] sign {path}: "
                         f"{r.status_code} {r.text[:200]}")
            return None
        signed = (r.json() or {}).get("signedURL") or ""
        if not signed:
            return None
        url = f"{base}/storage/v1{signed}"
        if download_as:
            from urllib.parse import quote
            sep = "&" if "?" in url else "?"
            url += f"{sep}download={quote(str(download_as))}"
        return url
    except Exception as e:
        logger.error(f"[store-files] sign {path} failed: {e}")
        return None


# ─── Metadata (businesses.settings.store.product_files) ───────────────

def product_files_of(biz_row: Dict[str, Any]) -> Dict[str, Any]:
    """The offering_id → file-meta map from a business row's settings."""
    files = (((biz_row.get("settings") or {}).get("store") or {})
             .get("product_files")) or {}
    return files if isinstance(files, dict) else {}


def _save_product_files(business_id: str, settings: Dict[str, Any],
                        files: Dict[str, Any]) -> None:
    settings = dict(settings or {})
    store = dict(settings.get("store") or {})
    store["product_files"] = files
    settings["store"] = store
    sb_clients.sb_patch_as_service(f"/businesses?id=eq.{business_id}",
                                   {"settings": settings})


def _business(business_id: str) -> Optional[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}"
        "&select=id,name,settings&limit=1") or []
    return rows[0] if rows else None


def _sellable_offering_or_404(business_id: str, offering_id: str) -> Dict[str, Any]:
    """The offering must belong to this business (cross-tenant = 404,
    never a hint that the id exists) and be a sellable category."""
    from store_router import SELLABLE_CATEGORIES
    rows = sb_clients.sb_get_as_service(
        f"/offerings?id=eq.{offering_id}&business_id=eq.{business_id}"
        "&select=id,name,category&limit=1") or []
    if not rows:
        raise HTTPException(404, "offering not found")
    if (rows[0].get("category") or "") not in SELLABLE_CATEGORIES:
        raise HTTPException(400, "files attach to sellable offerings only "
                                 "(product, course, or package)")
    return rows[0]


# ─── Download token (derived, stateless, stable) ──────────────────────

def order_download_token(order_id: str) -> Optional[str]:
    """HMAC-SHA256(CUSTOMER_TOKEN_SECRET, 'order-download:<id>'),
    urlsafe-b64. Deterministic so email links never rot; None when the
    secret isn't configured (links simply don't render)."""
    try:
        from customer_token import _b64url_encode, _secret
        sig = hmac.new(_secret(), f"order-download:{order_id}".encode("utf-8"),
                       hashlib.sha256).digest()
        return _b64url_encode(sig)
    except Exception as e:
        logger.warning(f"[store-files] download token unavailable: {e}")
        return None


def verify_download_token(order_id: str, token: str) -> bool:
    expected = order_download_token(order_id)
    if not expected or not token:
        return False
    return hmac.compare_digest(expected, str(token))


def download_url(order_id: str, offering_id: str) -> Optional[str]:
    """The STABLE buyer-facing link (backend public URL, RAILWAY_BASE
    pattern — the store page's own convention)."""
    token = order_download_token(order_id)
    if not token:
        return None
    from store_router import RAILWAY_BASE
    return f"{RAILWAY_BASE}/public/store/download/{order_id}/{token}/{offering_id}"


# ─── Practitioner: attach / detach / list ─────────────────────────────

@router.post("/store/products/{business_id}/{offering_id}/file")
async def upload_product_file(
    business_id: str, offering_id: str,
    file: UploadFile = File(...),
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    from business_users_router import require_role
    require_role(business_id, str(user.id), "manager")
    offering = _sellable_offering_or_404(business_id, offering_id)

    blob = b""
    while True:
        chunk = await file.read(_READ_CHUNK)
        if not chunk:
            break
        blob += chunk
        if len(blob) > MAX_FILE_BYTES:
            raise HTTPException(413, "file is over the 200 MB limit")
    if not blob:
        raise HTTPException(400, "empty file")

    filename = safe_filename(file.filename or "")
    content_type = (file.content_type or "").strip() or "application/octet-stream"
    path = f"{business_id}/{offering_id}/{filename}"

    if not storage_upload(path, blob, content_type):
        raise HTTPException(502, "couldn't store the file — please try again")

    biz = _business(business_id)
    if not biz:
        raise HTTPException(404, "business not found")
    files = dict(product_files_of(biz))
    old = files.get(str(offering_id)) or {}
    # Replace-on-reupload: drop the previous object when the name changed
    # (same name was replaced in place by x-upsert).
    old_path = old.get("path")
    if old_path and old_path != path:
        storage_delete(old_path)
    meta = {"path": path, "filename": filename, "size_bytes": len(blob),
            "content_type": content_type, "uploaded_at": _now_iso()}
    files[str(offering_id)] = meta
    _save_product_files(business_id, biz.get("settings") or {}, files)

    logger.info(f"[store-files] biz={business_id[:8]} offering={offering_id[:8]} "
                f"attached {filename} ({len(blob)} bytes)")
    return {"ok": True, "offering_id": offering_id,
            "offering_name": offering.get("name"), "file": meta}


@router.delete("/store/products/{business_id}/{offering_id}/file")
def delete_product_file(
    business_id: str, offering_id: str,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    from business_users_router import require_role
    require_role(business_id, str(user.id), "manager")
    _sellable_offering_or_404(business_id, offering_id)

    biz = _business(business_id)
    if not biz:
        raise HTTPException(404, "business not found")
    files = dict(product_files_of(biz))
    meta = files.pop(str(offering_id), None)
    if not meta:
        raise HTTPException(404, "no file attached to this offering")
    if meta.get("path"):
        storage_delete(meta["path"])
    _save_product_files(business_id, biz.get("settings") or {}, files)
    return {"ok": True, "offering_id": offering_id, "detached": True}


@router.get("/store/products/{business_id}/files")
def list_product_files(
    business_id: str,
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    from business_users_router import require_role
    require_role(business_id, str(user.id), "viewer")
    biz = _business(business_id)
    if not biz:
        raise HTTPException(404, "business not found")
    return {"ok": True, "files": product_files_of(biz),
            "max_bytes": MAX_FILE_BYTES}


# ─── Buyer: the validated download ────────────────────────────────────

@router.get("/public/store/download/{order_id}/{token}/{offering_id}")
def public_download(order_id: str, token: str, offering_id: str,
                    request: Request):
    import rate_limit
    if not rate_limit.allow("store_download", rate_limit.client_ip(request)):
        raise HTTPException(429, "Rate limit exceeded")

    # Token first — everything below leaks nothing to a bad token.
    if not verify_download_token(order_id, token):
        raise HTTPException(404, "link not found")

    rows = sb_clients.sb_get_as_service(
        f"/orders?id=eq.{order_id}&select=id,business_id,status,paid_at&limit=1") or []
    if not rows:
        raise HTTPException(404, "link not found")
    order = rows[0]
    if order.get("status") not in ("paid", "fulfilled"):
        raise HTTPException(403, "this order hasn't been completed yet — "
                                 "your download unlocks once payment confirms")

    items = sb_clients.sb_get_as_service(
        f"/order_items?order_id=eq.{order_id}&select=offering_id&limit=100") or []
    if str(offering_id) not in {str(i.get("offering_id")) for i in items
                                if i.get("offering_id")}:
        raise HTTPException(404, "link not found")

    biz = _business(str(order["business_id"]))
    meta = (product_files_of(biz or {})).get(str(offering_id)) or {}
    path = meta.get("path")
    if not path:
        raise HTTPException(404, "no file is attached to this item")

    url = storage_signed_url(path, download_as=meta.get("filename"))
    if not url:
        raise HTTPException(502, "couldn't prepare your download — please try "
                                 "again in a moment")

    # Best-effort trail — the spine, never a new table.
    try:
        import event_spine
        event_spine.emit("order_download", str(order["business_id"]),
                         {"order_id": order_id, "offering_id": offering_id,
                          "filename": meta.get("filename")},
                         source="store")
    except Exception:
        pass

    return RedirectResponse(url, status_code=302)
