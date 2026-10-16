"""
upload_images.py — what an uploaded picture really is, read from its bytes.

A browser's declared MIME type and a file's extension are the uploader's
say-so. Since #1464 the brand and Studio drop uploads write with the
service role, so the bytes have to prove themselves before they are
stored: a known raster signature, a header Pillow parses as that same
format, and the stored MIME type and extension taken from what was
found — never from the request.

SVG is refused, not sanitised: it can carry script, and a public bucket
serves it as a document. No brand upload has ever been an SVG (checked
2026-10-16), so nothing that works today stops working. (Codex review of
#1464, 2026-10-16.)
"""
from __future__ import annotations

import io
from typing import Iterable, Optional, Tuple

# kind -> (stored MIME, stored extension, Pillow's format name)
KINDS = {
    "png":  ("image/png",    "png",  "PNG"),
    "jpeg": ("image/jpeg",   "jpg",  "JPEG"),
    "webp": ("image/webp",   "webp", "WEBP"),
    "gif":  ("image/gif",    "gif",  "GIF"),
    "ico":  ("image/x-icon", "ico",  "ICO"),
    "avif": ("image/avif",   "avif", "AVIF"),
}


def sniff(data: bytes) -> Optional[str]:
    """The raster kind the leading bytes declare, or None."""
    data = data or b""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:4] == b"\x00\x00\x01\x00":
        return "ico"
    if data[4:8] == b"ftyp" and data[8:12] in (b"avif", b"avis"):
        return "avif"
    return None


def looks_like_svg(data: bytes) -> bool:
    """An SVG (or other XML/HTML text) — so the refusal can say so."""
    head = (data or b"")[:4096].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return head.startswith(b"<") and b"<svg" in head


def _pillow_reads_avif() -> bool:
    try:
        from PIL import features
        return bool(features.check("avif"))
    except Exception:  # noqa: BLE001 — older Pillow: no such feature
        return False


def verified_image(data: bytes, allowed: Iterable[str]) -> Optional[Tuple[str, str]]:
    """(mime, ext) when `data` is a well-formed picture of an allowed kind,
    judged from the bytes alone; otherwise None."""
    kind = sniff(data)
    if not kind or kind not in set(allowed):
        return None
    mime, ext, pil_format = KINDS[kind]
    if kind == "avif" and not _pillow_reads_avif():
        # This Pillow can't parse AVIF; the ISO-BMFF `ftyp avif` box is
        # the best evidence available, and the bytes are stored as
        # image/avif, which no browser runs as a page.
        return mime, ext
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as img:
            if (img.format or "").upper() != pil_format:
                return None
            width, height = img.size
            img.verify()
    except Exception:  # noqa: BLE001 — unreadable, truncated, or a bomb
        return None
    if width < 1 or height < 1:
        return None
    return mime, ext
