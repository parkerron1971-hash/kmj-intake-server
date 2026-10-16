"""Delivering a file out of a PRIVATE storage bucket.

On 2026-08-10 the vault migration closed `proposals` and
`business-documents` (`public = false`) and replaced their
"Allow public read" policies with business-scoped `authenticated`
ones. That was right — those two buckets hold client records.

What it silently broke is delivery. Three call sites were still
building `/storage/v1/object/public/<bucket>/<path>` URLs by string
concatenation, and a public URL on a private bucket does not 403 in a
way anyone reads as a permissions problem — it answers

    400 {"error": "Bucket not found", "code": "NoSuchBucket"}

so the practitioner sees "Could not fetch the PDF" and the bucket looks
like it was deleted. `contract_agent` was worse off still: it POSTed
the upload with the ANON key, which the new insert policy refuses
outright ("new row violates row-level security policy"), so the PDF
never reached storage at all.

A signed URL is the delivery mechanism a private bucket wants. It is
minted with the service role, it carries its own authorisation, and it
expires — which means it works in the two places an authenticated
`fetch` does not:

  * `window.open` / `<a href>`, which send no Authorization header
  * an unauthenticated `fetch()` for the bytes, so the browser gets a
    real download instead of opening a viewer tab

There used to be a third: BoldSign's servers, which fetched the PDF
from us by URL. The DocuSeal switch (2026-08-30) removed it — that
adapter posts the bytes inline, so a signed link is no longer minted
for a third party at all. Worth knowing if the last two reasons ever
go away, because then so does this module.

This module is the one place that knows how. Nothing here composes a
`/object/public/` URL, and nothing here should.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger("storage_links")

# One hour. The practitioner generates a document and clicks through to
# it — usually at once, sometimes after reading the preview or taking a
# call. Five minutes turns an ordinary pause into a dead link; a day
# would leave an unauthenticated handle on a governance document lying
# around in browser history. An hour covers the human gap without
# becoming a durable credential.
SIGNED_URL_TTL_SECONDS = 3600


def _base() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def service_headers() -> dict:
    """Service-role headers for storage writes.

    Storage RLS on these buckets is written for `authenticated` with a
    business check. The backend holds no user JWT at upload time, so
    the anon key fails the policy — this is genuinely server-initiated
    traffic and the service role is the correct actor for it. Callers
    stay responsible for the access check on the way in; every one of
    them runs `business_access.assert_access` or an owner check first.
    """
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def has_service_key() -> bool:
    return bool(os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""))


# What a practitioner reads when a storage write does not land. The raw
# answer ("new row violates row-level security policy", a bare 400) is
# for the log; the person uploading a logo needs to know whether it was
# their file or us, and what to do next.
UPLOAD_NOT_CONFIGURED = ("File storage isn't set up on our side yet, so nothing "
                         "can be saved. That's not your file — it's been logged.")
UPLOAD_REFUSED = ("Our file storage turned the upload away. That's a problem "
                  "on our side, not your file — it's been logged. Try again "
                  "in a few minutes.")
UPLOAD_TOO_LARGE = "That file is bigger than storage accepts. Try a smaller copy."
UPLOAD_WRONG_TYPE = "Storage doesn't accept that kind of file. Try a PNG or JPG."
UPLOAD_UNREACHABLE = "We couldn't reach file storage just now. Try again in a minute."


def upload_refusal(status_code: int, body: str) -> str:
    """Plain words for a refused storage write.

    Storage answers most refusals as HTTP 400 and puts the real status
    in the JSON body — the RLS refusal behind the 2026-10 logo bug came
    back as `400 {"statusCode":"403", ...}` — so the body is read first.
    """
    code = str(status_code)
    text = (body or "").lower()
    try:
        parsed = json.loads(body or "")
        if isinstance(parsed, dict) and parsed.get("statusCode"):
            code = str(parsed["statusCode"])
    except Exception:  # noqa: BLE001 — a non-JSON body keeps the HTTP code
        pass
    if code in ("401", "403") or "row-level security" in text:
        return UPLOAD_REFUSED
    if code == "413" or "maximum allowed size" in text or "too large" in text:
        return UPLOAD_TOO_LARGE
    if code == "415" or "mime type" in text:
        return UPLOAD_WRONG_TYPE
    return UPLOAD_UNREACHABLE


def _finish(base: str, payload: dict, download_as: Optional[str]) -> Optional[str]:
    signed = (payload or {}).get("signedURL") or ""
    if not signed:
        return None
    url = f"{base}/storage/v1{signed}"
    if download_as:
        # `?download=` makes Supabase answer with a Content-Disposition
        # attachment header, so a plain link saves the file under a
        # readable name instead of opening an inline viewer.
        url += ("&" if "?" in url else "?") + f"download={quote(str(download_as))}"
    return url


async def signed_url(client: httpx.AsyncClient, bucket: str, path: str, *,
                     ttl: int = SIGNED_URL_TTL_SECONDS,
                     download_as: Optional[str] = None) -> Optional[str]:
    """Mint a signed URL for a private object. None on any failure —
    the caller decides whether that is fatal."""
    base = _base()
    if not base:
        logger.warning("SUPABASE_URL not configured; cannot sign %s", path)
        return None
    try:
        r = await client.post(
            f"{base}/storage/v1/object/sign/{bucket}/{path}",
            headers={**service_headers(), "Content-Type": "application/json"},
            json={"expiresIn": ttl},
            timeout=httpx.Timeout(30.0),
        )
        if r.status_code >= 400:
            logger.error("sign %s/%s: %s %s", bucket, path,
                         r.status_code, r.text[:200])
            return None
        return _finish(base, r.json(), download_as)
    except Exception as e:  # noqa: BLE001 — a dead link beats a 500
        logger.error("sign %s/%s failed: %s", bucket, path, e)
        return None


def signed_url_sync(bucket: str, path: str, *,
                    ttl: int = SIGNED_URL_TTL_SECONDS,
                    download_as: Optional[str] = None) -> Optional[str]:
    """Blocking variant, for callers outside an async request."""
    base = _base()
    if not base:
        return None
    try:
        with httpx.Client(timeout=httpx.Timeout(30.0)) as c:
            r = c.post(f"{base}/storage/v1/object/sign/{bucket}/{path}",
                       headers={**service_headers(),
                                "Content-Type": "application/json"},
                       json={"expiresIn": ttl})
        if r.status_code >= 400:
            logger.error("sign %s/%s: %s %s", bucket, path,
                         r.status_code, r.text[:200])
            return None
        return _finish(base, r.json(), download_as)
    except Exception as e:  # noqa: BLE001
        logger.error("sign %s/%s failed: %s", bucket, path, e)
        return None
