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
screen still looks finished.

Which photo goes where (Kevin, 2026-10-19: "so that it's not random
pictures and if they build an area they can have a default picture until
they have replace it"): choose() takes the picture the church put on that
spot (settings.member_portal.pictures, with its look: colour, black and
white, or washed in the church colour), else one of its photos whose file
name names the thing (supper-house.webp on Supper House), else nothing,
and the screen draws the spot's default picture (member_app_ui.default_art).
Home and sign-in fall back to the church's own best photo by name (hero,
welcome). Nothing is picked by chance any more.

The wordmark: a hand-built site's light assets/logo.* on a dark base, its
dark logo-ink.* on a light one, measured once per file. Series art: a
site's assets/series-<name>.* (it keeps its colour; photos go black and
white, member_app_ui).
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
# Photos are matched to spots by name now, never at random, so the pool is
# wide enough to hold a church's whole photo set (Love City's has 36).
MAX_PHOTOS = 80
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


def photos(biz: Dict[str, Any], site: Optional[Dict[str, Any]], limit: Optional[int] = MAX_PHOTOS) -> List[str]:
    """The church's photo URLs, best first. [] when it has none. `limit`
    None is every one (named() looks past the first MAX_PHOTOS)."""
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
    return uniq if limit is None else uniq[:limit]


def named(biz: Dict[str, Any], site: Optional[Dict[str, Any]], words: Tuple[str, ...]) -> str:
    """The church's photo whose file name says it shows this (a Youth
    space's 'youth-fellowship'), among ALL its photos, not just the first
    MAX_PHOTOS; '' when none does."""
    return _by_words(photos(biz, site, limit=None), words) or ""


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


LOOKS = ("colour", "bw", "church")
# Words too common to say what a picture shows.
_STOP = {"the", "and", "with", "for", "our", "your", "night", "day", "sunday", "monday", "tuesday", "wednesday",
         "thursday", "friday", "saturday", "service", "meeting", "church", "this", "week", "time", "group"}


def assigned(biz: Dict[str, Any], key: str) -> Optional[Dict[str, str]]:
    """The picture the church put on one spot: {"url", "look"}, or
    {"url": ""} when it chose the default picture there. None when it
    hasn't chosen."""
    cfg = (((biz or {}).get("settings") or {}).get("member_portal") or {})
    pics = cfg.get("pictures") if isinstance(cfg, dict) else None
    got = pics.get(key) if isinstance(pics, dict) else None
    if not isinstance(got, dict):
        return None
    url = str(got.get("url") or "")
    if url and not good_url(url):
        return None
    look = got.get("look") if got.get("look") in LOOKS else "colour"
    return {"url": url, "look": look}


def good_url(url: str) -> bool:
    """A picture the app may show: https, or one of a hand-built site's own
    assets."""
    import re
    return bool(re.fullmatch(r"https://[^\s<>\"']{1,500}", url)
                or re.fullmatch(r"/public/site-assets/[\w.-]+/[\w.%-]+", url))


def by_name(pool: List[str], title: Any, avoid: Any = ()) -> str:
    """One of the church's photos whose file name says it shows this
    (a "Supper House" card gets supper-house.webp). '' when none does."""
    import re
    skip = {avoid} if isinstance(avoid, str) else set(avoid or ())
    words = [w for w in re.findall(r"[a-z]{4,}", str(title or "").lower()) if w not in _STOP]
    if not words:
        return ""
    return _by_words([u for u in pool if u not in skip], tuple(words)) or ""


def choose(biz: Dict[str, Any], key: str, pool: List[str], *, title: Any = "", words: Tuple[str, ...] = (),
           fallback: str = "", look: str = "bw", used: Optional[set] = None) -> Tuple[str, str]:
    """(url, look) for one spot on a screen; ('', '') means draw the spot's
    default picture. The church's own choice wins, then a photo named for
    the thing (its title, or `words`), then `fallback` (Home's and
    sign-in's best photo). `used` keeps one photo off two cards of a
    screen, except where the church chose it."""
    got = assigned(biz, key)
    if got is not None:
        if got["url"] and used is not None:
            used.add(got["url"])
        return (got["url"], got["look"]) if got["url"] else ("", "")
    taken = used or set()
    pic = by_name(pool, title, taken) if title else ""
    if not pic and words:
        pic = _by_words([u for u in pool if u not in taken], words) or ""
    pic = pic or fallback
    if pic and used is not None:
        used.add(pic)
    return (pic, look) if pic else ("", "")


def pick_for(pool: List[str], words: Tuple[str, ...], key: Any, avoid: Any = "") -> str:
    """A photo whose file name fits the card (a prayer tile, a praying
    photo), else a stable one (pick). `avoid` as in pick."""
    skip = {avoid} if isinstance(avoid, str) else set(avoid or ())
    found = _by_words([u for u in pool if u not in skip], words)
    return found or pick(pool, key, avoid)


def pick(pool: List[str], key: Any, avoid: Any = "") -> str:
    """A stable photo for one card (an event, a group). `avoid` is a photo,
    or several, already on the screen. '' with no photos."""
    skip = {avoid} if isinstance(avoid, str) else set(avoid or ())
    choices = [u for u in pool if u not in skip] or pool
    if not choices:
        return ""
    n = int(hashlib.sha256(str(key or "").encode()).hexdigest()[:8], 16)
    return choices[n % len(choices)]


def _is_light(path: str) -> bool:
    """True when a logo's visible pixels are light enough to sit on a
    dark base."""
    v = _lum(path)
    return v is not None and v >= 0.7


def wordmark(site: Optional[Dict[str, Any]], light: bool = True) -> str:
    """A hand-built site's logo for the app's top bar and sign-in: a light
    one for a dark base (light=True), a dark one for a light base. ''
    when the site has none that reads on that base."""
    d = _site_dir(site)
    if d is None:
        return ""
    names = ("logo.webp", "logo.png") if light else ("logo-ink.webp", "logo-dark.webp", "logo-ink.png",
                                                     "logo-dark.png", "logo.webp", "logo.png")
    for name in names:
        p = d / name
        if not p.is_file():
            continue
        v = _lum(str(p))
        if v is not None and (v >= 0.7 if light else v <= 0.4):
            return f"/public/site-assets/{quote(str(site['slug']), safe='')}/{name}"
    return ""


@lru_cache(maxsize=64)
def _lum(path: str) -> Optional[float]:
    """How light a logo's visible pixels are (0 black … 1 white), measured
    once per file. None for an unreadable file or one with an opaque
    background (it would sit on the app as a box)."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            im = im.convert("RGBA")
            im.thumbnail((160, 160))
            px = [p for p in im.getdata() if p[3] > 128]
        if not px or len(px) > 0.9 * im.width * im.height:
            return None
        return sum(0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b, _ in px) / (255 * len(px))
    except Exception:
        logger.info("member app: logo %s could not be measured", Path(path).name)
        return None


def has_site_page(site: Optional[Dict[str, Any]], page: str) -> bool:
    """True when a hand-built site has its own page by this name
    (sites/<slug>/<page>.html, served at /<page>)."""
    d = _site_dir(site)
    return bool(d is not None and page.isidentifier() and (d.parent / f"{page}.html").is_file())


def _slug(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")


def series_art(site: Optional[Dict[str, Any]], title: str) -> str:
    """A hand-built site's own art for a sermon series:
    assets/series-<the series' name>.webp (Love City's "To the Future" is
    series-to-the-future.webp). '' when there's none."""
    d = _site_dir(site)
    want = _slug(title)
    if d is None or not want:
        return ""
    for name, _size in _site_files(str(d)):
        stem, _, ext = name.rpartition(".")
        if stem.lower() == f"series-{want}" and f".{ext.lower()}" in PHOTO_EXT:
            return f"/public/site-assets/{quote(str(site['slug']), safe='')}/{quote(name)}"
    return ""
