"""
member_app_photos.py — the church's own photos and logo, for the member app.

The member app (Kevin, 2026-10-14: "take the layout to another level")
leads Home and sign-in with a photo, and puts photos on this week's cards
and the group cards. They are always the church's OWN pictures, never
stock:

  1. Photos the church added to its media library (settings.media_library
     .gallery, the ones shown on its website, in its order).
  2. A hand-built site's photos (sites/<slug>/assets, served by
     public_site at /public/site-assets/<slug>/<file>). Logos, marks and
     icons are left out by name, and so is anything too small to be a
     photo.

A church with neither gets the generated art (member_app_ui), so every
screen still looks finished. The app tones every photo to the church's
colour in CSS, so mixed photos read as one set.

The wordmark: a hand-built site's assets/logo.* when it is LIGHT (the app
is dark), measured once per file.
"""
from __future__ import annotations

import hashlib
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

logger = logging.getLogger("member_app_photos")

SITES_DIR = Path(__file__).resolve().parent / "sites"
PHOTO_EXT = (".webp", ".jpg", ".jpeg", ".png")
# Logos and marks, and artwork with words on it (a sermon series' art, a
# flyer), are not photos of the church.
NOT_PHOTOS = ("logo", "mark", "icon", "favicon", "og-", "apple-touch", "badge", "qr",
              "series", "flyer", "poster", "banner", "graphic")
MIN_PHOTO_BYTES = 25_000
MAX_PHOTOS = 24
# Words in a file name that make a good Home photo (the whole church in
# the room), and a good sign-in photo (people together).
HERO_WORDS = ("service", "worship", "sanctuary", "congregation", "stage", "hero", "church")
WELCOME_WORDS = ("family", "congregation", "community", "people", "together", "group", "church")


def _site_dir(site: Optional[Dict[str, Any]]) -> Optional[Path]:
    slug = str((site or {}).get("slug") or "")
    if not slug or "/" in slug or "\\" in slug or slug.startswith("."):
        return None
    d = SITES_DIR / slug / "assets"
    try:
        d.resolve().relative_to(SITES_DIR.resolve())
    except ValueError:
        return None
    return d if d.is_dir() else None


@lru_cache(maxsize=64)
def _site_files(dir_: str) -> Tuple[Tuple[str, int], ...]:
    """(name, size) for every file in a site's assets folder. Site assets
    ship with the code, so they can't change while this process runs."""
    out = []
    for p in sorted(Path(dir_).iterdir()):
        if p.is_file():
            try:
                out.append((p.name, p.stat().st_size))
            except OSError:
                continue
    return tuple(out)


def _is_photo(name: str, size: int) -> bool:
    low = name.lower()
    return (low.endswith(PHOTO_EXT) and size >= MIN_PHOTO_BYTES
            and not any(w in low for w in NOT_PHOTOS))


def photos(biz: Dict[str, Any], site: Optional[Dict[str, Any]]) -> List[str]:
    """The church's photo URLs, best first. [] when it has none."""
    out: List[str] = []
    lib = (((biz or {}).get("settings") or {}).get("media_library") or {})
    gallery = lib.get("gallery") if isinstance(lib, dict) else None
    if isinstance(gallery, list):
        shown = [g for g in gallery if isinstance(g, dict) and g.get("show_on_website", True)
                 and str(g.get("url") or "").startswith("https://")]
        shown.sort(key=lambda g: g.get("sort_order", 0))
        out.extend(str(g["url"]) for g in shown)
    d = _site_dir(site)
    if d is not None:
        slug = quote(str(site["slug"]), safe="")
        try:
            files = _site_files(str(d))
        except OSError:
            files = ()
        out.extend(f"/public/site-assets/{slug}/{quote(n, safe='')}" for n, s in files if _is_photo(n, s))
    seen, uniq = set(), []
    for u in out:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq[:MAX_PHOTOS]


def _by_words(pool: List[str], words: Tuple[str, ...]) -> Optional[str]:
    for w in words:
        for u in pool:
            if w in u.rsplit("/", 1)[-1].lower():
                return u
    return None


def hero(pool: List[str]) -> str:
    """Home's photo: the church's first own photo, or one whose name says
    it shows a service. '' when there are none."""
    if not pool:
        return ""
    return _by_words(pool, HERO_WORDS) or pool[0]


def welcome(pool: List[str]) -> str:
    """The sign-in photo: people together, else anything but Home's."""
    if not pool:
        return ""
    found = _by_words(pool, WELCOME_WORDS)
    if found and (found != hero(pool) or len(pool) == 1):
        return found
    rest = [u for u in pool if u != hero(pool)]
    return rest[0] if rest else pool[0]


def pick(pool: List[str], key: Any, avoid: Any = "") -> str:
    """A stable photo for one card (an event, a group). `avoid` is a photo,
    or several, already on the screen. '' with no photos."""
    skip = {avoid} if isinstance(avoid, str) else set(avoid or ())
    choices = [u for u in pool if u not in skip] or pool
    if not choices:
        return ""
    n = int(hashlib.sha256(str(key or "").encode()).hexdigest()[:8], 16)
    return choices[n % len(choices)]


@lru_cache(maxsize=64)
def _is_light(path: str) -> bool:
    """True when a logo's visible pixels are light enough to sit on the
    dark app. Unreadable or opaque-background files count as not light."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert("RGBA")
            im.thumbnail((160, 160))
            px = [p for p in im.getdata() if p[3] > 128]
        if not px or len(px) > 0.9 * im.width * im.height:
            return False
        lum = sum(0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b, _ in px) / (255 * len(px))
        return lum >= 0.7
    except Exception:
        logger.info("member app: logo %s could not be measured", Path(path).name)
        return False


def wordmark(site: Optional[Dict[str, Any]]) -> str:
    """A hand-built site's light logo, for the app's header and sign-in.
    '' when there isn't one that reads on the dark app."""
    d = _site_dir(site)
    if d is None:
        return ""
    for name in ("logo.webp", "logo.png"):
        p = d / name
        if p.is_file() and _is_light(str(p)):
            return f"/public/site-assets/{quote(str(site['slug']), safe='')}/{name}"
    return ""
