"""
upload_images.py — what an uploaded picture really is, read from its bytes.

A browser's declared MIME type and a file's extension are the uploader's
say-so. Since #1464 the brand and Studio drop uploads write with the
service role, so the bytes have to prove themselves before they are
stored: a known raster signature, a file Pillow opens as that same
format, every frame of it decoded, and the stored MIME type and
extension taken from what was found — never from the request.

Decoding is the proof. Pillow's verify() checks structure and decodes
nothing, so a JPEG missing its last bytes passed it (Codex re-check,
2026-10-16). A format this server can't decode is refused, never taken
on its signature: AVIF needs a Pillow built with libavif.

SVG is refused, not sanitised: it can carry script, and a public bucket
serves it as a document. No brand upload has ever been an SVG (checked
2026-10-16), so nothing that works today stops working. (Codex review of
#1464, 2026-10-16.)
"""
from __future__ import annotations

import io
from typing import Iterable, Optional, Tuple

# kind -> (stored MIME, stored extension, the format names Pillow gives it).
# A JPEG with a multi-picture block (an Android Ultra HDR photo carries its
# gain map that way) opens as MPO; browsers show it as the JPEG it is.
KINDS = {
    "png":  ("image/png",    "png",  ("PNG",)),
    "jpeg": ("image/jpeg",   "jpg",  ("JPEG", "MPO")),
    "webp": ("image/webp",   "webp", ("WEBP",)),
    "gif":  ("image/gif",    "gif",  ("GIF",)),
    "ico":  ("image/x-icon", "ico",  ("ICO",)),
    "avif": ("image/avif",   "avif", ("AVIF",)),
}

# Decoding costs memory, so it is bounded before it starts: a header that
# claims more than MAX_PIXELS is refused unread (a few hundred bytes of
# PNG can claim billions), and an animated file decodes at most
# MAX_FRAMES frames and MAX_TOTAL_PIXELS pixels in all. A 50-megapixel
# phone photo fits; a single JPEG decodes at an eighth of its size, which
# still reads and checks every byte of it.
MAX_PIXELS = 50_000_000
MAX_FRAMES = 200
MAX_TOTAL_PIXELS = 100_000_000


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


def can_decode(kind: str) -> bool:
    """Whether this server can decode `kind` — and so whether it can
    accept it at all."""
    if kind == "avif":
        return _pillow_reads_avif()
    return kind in KINDS


def verified_image(data: bytes, allowed: Iterable[str]) -> Optional[Tuple[str, str]]:
    """(mime, ext) when `data` is a whole picture of an allowed kind that
    this server decoded, judged from the bytes alone; otherwise None."""
    kind = sniff(data)
    if not kind or kind not in set(allowed) or not can_decode(kind):
        return None
    mime, ext, names = KINDS[kind]
    try:
        from PIL import Image
        opener = [names[0]]
        # Structure: the format matches, the size is in budget, and
        # verify()'s checks (PNG chunk checksums and the like) pass.
        with Image.open(io.BytesIO(data), formats=opener) as img:
            if (img.format or "").upper() not in names or not _in_budget(img.size):
                return None
            img.verify()
        # Pixels: verify() leaves the image unusable, so open it again.
        with Image.open(io.BytesIO(data), formats=opener) as img:
            if not _decodes(img):
                return None
    except Exception:  # noqa: BLE001 — unreadable, truncated, or a bomb
        return None
    return mime, ext


def _in_budget(size: Tuple[int, int]) -> bool:
    width, height = size
    return 0 < width and 0 < height and width * height <= MAX_PIXELS


def _decodes(img) -> bool:
    """Decode every frame; a short or corrupt file raises on the way."""
    frames = int(getattr(img, "n_frames", 1) or 1)
    width, height = img.size
    if frames > MAX_FRAMES or width * height * frames > MAX_TOTAL_PIXELS:
        return False
    if frames == 1 and img.format == "JPEG":
        img.draft(img.mode, (max(1, width // 8), max(1, height // 8)))
    for index in range(frames):
        if index:
            img.seek(index)
            if not _in_budget(img.size):
                return False
        img.load()
    return True
