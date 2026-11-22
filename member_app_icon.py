"""
member_app_icon.py — the member app's icon and opening screen, the church's
own (Kevin approved the Member page mock's "Icon & opening screen",
2026-11-22: "build this").

Until a church chooses, nothing here changes anything: the icon stays its
initials on its colour (member_app_install._icon) and pages carry no
opening screen. Once it saves its choice in Settings → Member page:

    settings.member_portal.app_icon = {
        "source": "logo" | "upload",        the brand kit's logo, or a square
                                            icon the church uploaded (>= 1024)
        "background": "colour" | "black" | "white" | "photo",
        "photo": <one of the church's photos, when background is photo>,
        "ground": "#rrggbb",                the background as one colour (a
                                            photo's, darkened), for the
                                            manifest's background_color
        "at": <when it was saved>,          in every address, so a new choice
                                            is a new picture to phones
    }
    settings.member_portal.app_icon_upload = <the uploaded square icon>
    settings.member_portal.app_short_name = <the name under the icon, <= 12>

What it draws:
  icon(size)          the logo inside the maskable safe zone (the middle
                      circle of 80%, so a round launcher mask never cuts it)
                      on the background; or the uploaded icon. A logo that
                      wouldn't show on the background (dark on black, light
                      on white) is drawn in white or near-black instead.
  startup(w, h)       iPhone/iPad opening screens (apple-touch-startup-image):
                      the same logo centred on the background, "Powered by
                      Solutionist" fixed at the bottom. It can't be removed.
  head_tags / opening the startup links per device size, and the in-app
                      opening screen: shown ONLY when the app was opened from
                      the home screen (display-mode standalone), once per
                      launch, for about a second or until the page has
                      loaded, then a fade (none with reduced motion). It's a
                      layer on <html> a script adds, so without script there
                      is nothing over the page.

Pictures are read only from the church's own storage folder or its site's
files (member_lumen_share.picture_bytes) and drawn on the server, kept per
server copy by what they're drawn from (the choice's "at" is in the key).
"""
from __future__ import annotations

import hashlib
import io
import logging
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("member_app_icon")

SOURCES = ("logo", "upload")
BACKGROUNDS = ("colour", "black", "white", "photo")
SHORT_MAX = 12
UPLOAD_MIN = 1024
POWERED = ("POWERED BY", "Solutionist")
# (CSS width, CSS height, pixel ratio) of the iPhones and iPads that read
# apple-touch-startup-image, portrait. The picture is width*ratio x height*ratio.
DEVICES: Tuple[Tuple[int, int, int], ...] = (
    (440, 956, 3), (402, 874, 3), (430, 932, 3), (393, 852, 3), (428, 926, 3), (390, 844, 3),
    (375, 812, 3), (414, 896, 3), (414, 896, 2), (414, 736, 3), (375, 667, 2), (320, 568, 2),
    (1024, 1366, 2), (834, 1194, 2), (820, 1180, 2), (834, 1112, 2), (810, 1080, 2), (768, 1024, 2),
)
STARTUP_SIZES = {(w * r, h * r) for w, h, r in DEVICES}
STARTUP_RE = re.compile(r"/my/startup-(\d{3,4})x(\d{3,4})\.png")
_HEX = re.compile(r"#[0-9a-fA-F]{6}")


# ─── the choice ──────────────────────────────────────────────────────


def _cfg(biz: Dict[str, Any]) -> Dict[str, Any]:
    cfg = ((biz or {}).get("settings") or {}).get("member_portal") or {}
    return cfg if isinstance(cfg, dict) else {}


def choice(biz: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """The church's saved icon choice, checked, or None (today's initials)."""
    got = _cfg(biz).get("app_icon")
    if not isinstance(got, dict):
        return None
    source, background = got.get("source"), got.get("background")
    if source not in SOURCES or background not in BACKGROUNDS:
        return None
    if source == "upload" and not upload_url(biz):
        return None
    photo = str(got.get("photo") or "")
    if background == "photo" and not photo:
        return None
    ground = str(got.get("ground") or "")
    return {"source": source, "background": background, "photo": photo if background == "photo" else "",
            "ground": ground.lower() if _HEX.fullmatch(ground) else "", "at": str(got.get("at") or "")[:40]}


def upload_url(biz: Dict[str, Any]) -> str:
    u = str(_cfg(biz).get("app_icon_upload") or "")
    return u if u.startswith("https://") else ""


def short(biz: Dict[str, Any]) -> Optional[str]:
    """The name under the icon the church typed, or None (member_app_install.short_name's)."""
    return clean_short(_cfg(biz).get("app_short_name"))


def clean_short(raw: Any) -> Optional[str]:
    """A name for under the icon: one line, at most 12 characters, no
    markup. None when there's nothing usable."""
    if not isinstance(raw, str):
        return None
    s = " ".join(raw.split())
    s = re.sub(r"[<>\"'`\x00-\x1f]", "", s).strip()
    return s[:SHORT_MAX].strip() or None


def logo_url(biz: Dict[str, Any]) -> str:
    """The brand kit's logo (the same order as brand_mark), or ''."""
    kit = ((biz or {}).get("settings") or {}).get("brand_kit") or {}
    kit = kit if isinstance(kit, dict) else {}
    logos = kit.get("logos") if isinstance(kit.get("logos"), dict) else {}
    assets = kit.get("assets") if isinstance(kit.get("assets"), dict) else {}
    for v in (logos.get("primary"), kit.get("logo_url"), assets.get("primary"), kit.get("logo")):
        if isinstance(v, str) and (v.startswith("https://") or v.startswith("/public/site-assets/")):
            return v
    return ""


def version(c: Dict[str, str]) -> str:
    """A short tag for a choice, in every address its pictures are at."""
    return hashlib.sha256(repr(sorted(c.items())).encode()).hexdigest()[:10]


def ground(biz: Dict[str, Any], c: Dict[str, str], pal: Dict[str, Any]) -> str:
    """The background as one colour: the app's colour, black, white, or the
    photo's (saved with the choice)."""
    if c["background"] == "black":
        return "#000000"
    if c["background"] == "white":
        return "#ffffff"
    if c["background"] == "photo":
        return c["ground"] or "#111111"
    return str(pal.get("tint") or pal.get("accent") or "#1c1c1e")


# ─── drawing ─────────────────────────────────────────────────────────


def _bytes(url: str, business_id: str, at: str = "") -> Optional[bytes]:
    """A picture of the church's own, read at most once an hour per server
    copy for each choice (its "at" is in the key)."""
    import time
    return _kept(url, business_id, at, int(time.time() // 3600)) if url else None


@lru_cache(maxsize=32)
def _kept(url: str, business_id: str, at: str, hour: int) -> Optional[bytes]:
    import member_lumen_share as msh
    return msh.picture_bytes(url, business_id)


def _open(raw: Optional[bytes]):
    """Bytes → an upright RGBA picture (transparency kept), or None."""
    if not raw:
        return None
    from PIL import Image, ImageOps
    try:
        im = Image.open(io.BytesIO(raw))
        if im.format not in ("JPEG", "PNG", "WEBP", "MPO") or im.width * im.height > 40_000_000:
            return None
        im.load()
        im = ImageOps.exif_transpose(im)
        im.thumbnail((2048, 2048))
        return im.convert("RGBA")
    except Exception:  # noqa: BLE001
        return None


def _rgb(hex_: str) -> Tuple[int, int, int]:
    return int(hex_[1:3], 16), int(hex_[3:5], 16), int(hex_[5:7], 16)


def _lum(rgb: Tuple[float, float, float]) -> float:
    def lin(x: float) -> float:
        x /= 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _contrast(a: float, b: float) -> float:
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def photo_ground(raw: Optional[bytes]) -> str:
    """A photo as one colour (its average, darkened as it is under the logo)."""
    im = _open(raw)
    if im is None:
        return "#111111"
    r, g, b, _a = im.convert("RGBA").resize((1, 1)).getpixel((0, 0))
    return "#%02x%02x%02x" % (int(r * 0.55), int(g * 0.55), int(b * 0.55))


def _canvas(w: int, h: int, bg: str, photo_raw: Optional[bytes]):
    from PIL import Image, ImageOps
    im = Image.new("RGBA", (w, h), _rgb(bg) + (255,))
    ph = _open(photo_raw)
    if ph is not None:
        ph = ImageOps.fit(ph.convert("RGB"), (w, h), Image.LANCZOS)
        shade = Image.new("RGB", (w, h), (0, 0, 0))
        im = Image.blend(ph, shade, 0.45).convert("RGBA")
    return im


def _logo_on(logo, bg_lum: float):
    """The logo, recoloured white or near-black when its own colours
    wouldn't show on the background (a transparent logo only)."""
    from PIL import Image
    alpha = logo.getchannel("A")
    if alpha.getextrema()[0] >= 250:          # no transparency: drawn as it is
        return logo
    small = logo.resize((64, 64))
    px = [p for p in small.getdata() if p[3] > 128]
    if not px:
        return logo
    mean = tuple(sum(p[i] for p in px) / len(px) for i in range(3))
    if _contrast(_lum(mean), bg_lum) >= 1.8:
        return logo
    ink = (255, 255, 255) if bg_lum < 0.4 else (17, 17, 19)
    flat = Image.new("RGBA", logo.size, ink + (255,))
    flat.putalpha(alpha)
    return flat


def _fit_safe(logo, box: int):
    """The logo scaled to sit inside a circle of diameter `box` (the
    maskable safe zone), with a little air."""
    from PIL import Image
    w, h = logo.size
    a = w / h
    r = box / 2 * 0.92
    tw = 2 * r * a / (1 + a * a) ** 0.5
    th = 2 * r / (1 + a * a) ** 0.5
    scale = min(tw / w, th / h)
    return logo.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)


def _initials(size: int, name: str, ink: str):
    """The church's initials, on nothing (the canvas is the ground)."""
    from PIL import Image, ImageDraw, ImageFont
    import member_app_ui as ui
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    text = (ui.initials(name) or "C")[:3]
    font = ImageFont.load_default(size=int(size * (0.40 if len(text) < 3 else 0.30)))
    box = draw.textbbox((0, 0), text, font=font)
    draw.text(((size - (box[2] - box[0])) / 2 - box[0], (size - (box[3] - box[1])) / 2 - box[1]), text, font=font,
              fill=_rgb(ink) + (255,))
    return img


def _mark(name: str, bg: str, bg_lum: float, logo_raw: Optional[bytes], box: int):
    """What sits in the middle: the logo fitted to `box`, or the initials."""
    logo = _open(logo_raw)
    if logo is None:
        return _initials(box, name, "#ffffff" if bg_lum < 0.4 else "#111113")
    return _fit_safe(_logo_on(logo, bg_lum), box)


def _png(im) -> bytes:
    out = io.BytesIO()
    im.convert("RGB").save(out, format="PNG", optimize=False, compress_level=6)
    return out.getvalue()


@lru_cache(maxsize=24)
def _icon(size: int, name: str, source: str, bg: str, logo_raw: Optional[bytes], photo_raw: Optional[bytes],
          upload_raw: Optional[bytes]) -> bytes:
    from PIL import Image, ImageOps
    up = _open(upload_raw) if source == "upload" else None
    if up is not None:
        im = _canvas(size, size, bg, None)
        im.alpha_composite(ImageOps.fit(up, (size, size), Image.LANCZOS))
        return _png(im)
    im = _canvas(size, size, bg, photo_raw)
    mean = im.convert("RGB").resize((1, 1)).getpixel((0, 0))
    mark = _mark(name, bg, _lum(mean), logo_raw, int(size * 0.8))
    im.alpha_composite(mark, ((size - mark.width) // 2, (size - mark.height) // 2))
    return _png(im)


@lru_cache(maxsize=8)
def _startup(w: int, h: int, name: str, source: str, bg: str, logo_raw: Optional[bytes],
             photo_raw: Optional[bytes], upload_raw: Optional[bytes]) -> bytes:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    im = _canvas(w, h, bg, photo_raw)
    mean = im.convert("RGB").resize((1, 1)).getpixel((0, 0))
    bg_lum = _lum(mean)
    side = int(min(w, h) * 0.5)
    up = _open(upload_raw) if source == "upload" else None
    if up is not None:
        art = ImageOps.fit(up, (side, side), Image.LANCZOS)
        mask = Image.new("L", art.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, side - 1, side - 1), radius=int(side * 0.22), fill=255)
        art.putalpha(mask)
    else:
        art = _mark(name, bg, bg_lum, logo_raw, int(min(w, h) * 0.62))
    im.alpha_composite(art, ((w - art.width) // 2, (h - art.height) // 2))
    ink = (255, 255, 255) if bg_lum < 0.4 else (17, 17, 19)
    draw = ImageDraw.Draw(im)
    unit = min(w, h) / 100
    small = ImageFont.load_default(size=max(10, int(unit * 2.6)))
    big = ImageFont.load_default(size=max(14, int(unit * 4.2)))
    top_line, word = POWERED
    spaced = " ".join(top_line)
    y = h - int(unit * 16)
    for text, font, alpha in ((spaced, small, 170), (word, big, 255)):
        box = draw.textbbox((0, 0), text, font=font)
        draw.text(((w - (box[2] - box[0])) / 2 - box[0], y - box[1]), text, font=font, fill=ink + (alpha,))
        y += (box[3] - box[1]) + int(unit * 1.6)
    return _png(im)


def _inputs(biz: Dict[str, Any], c: Dict[str, str]) -> Tuple[Optional[bytes], Optional[bytes], Optional[bytes]]:
    bid = str(biz.get("id") or "")
    logo = _bytes(logo_url(biz), bid, c["at"]) if c["source"] == "logo" else None
    photo = _bytes(c["photo"], bid, c["at"]) if c["background"] == "photo" else None
    up = _bytes(upload_url(biz), bid, c["at"]) if c["source"] == "upload" else None
    return logo, photo, up


def icon_png(biz: Dict[str, Any], pal: Dict[str, Any], size: int) -> Optional[bytes]:
    """The church's chosen icon at `size`, or None (no choice: today's)."""
    c = choice(biz)
    if not c:
        return None
    logo, photo, up = _inputs(biz, c)
    return _icon(int(size), str(biz.get("name") or "Church"), c["source"], ground(biz, c, pal), logo, photo, up)


def startup_png(biz: Dict[str, Any], pal: Dict[str, Any], w: int, h: int) -> Optional[bytes]:
    """The opening screen at w x h (one of STARTUP_SIZES), or None."""
    c = choice(biz)
    if not c or (w, h) not in STARTUP_SIZES:
        return None
    logo, photo, up = _inputs(biz, c)
    return _startup(w, h, str(biz.get("name") or "Church"), c["source"], ground(biz, c, pal), logo, photo, up)


def mark_png(biz: Dict[str, Any], pal: Dict[str, Any]) -> Optional[bytes]:
    """The opening screen's middle on its own (transparent), for the in-app
    opening layer: the logo, the uploaded icon, or the initials."""
    c = choice(biz)
    if not c:
        return None
    logo, photo, up = _inputs(biz, c)
    return _mark_png(str(biz.get("name") or "Church"), c["source"], ground(biz, c, pal), logo, photo, up)


@lru_cache(maxsize=16)
def _mark_png(name: str, source: str, bg: str, logo_raw: Optional[bytes], photo_raw: Optional[bytes],
              upload_raw: Optional[bytes]) -> bytes:
    from PIL import Image, ImageDraw, ImageOps
    side = 640
    up = _open(upload_raw) if source == "upload" else None
    if up is not None:
        art = ImageOps.fit(up, (side, side), Image.LANCZOS)
        mask = Image.new("L", art.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, side - 1, side - 1), radius=int(side * 0.22), fill=255)
        art.putalpha(mask)
    else:
        lum = _lum(_rgb(bg)) if not photo_raw else 0.05
        art = _mark(name, bg, lum, logo_raw, side)
    out = io.BytesIO()
    art.save(out, format="PNG")
    return out.getvalue()


# ─── the page ────────────────────────────────────────────────────────


def head_tags(biz: Dict[str, Any], pal: Dict[str, Any]) -> str:
    """The opening screen's tags for a member page's <head>: '' with no
    choice (the page is today's page)."""
    c = choice(biz)
    if not c:
        return ""
    v = version(c)
    links = "".join(
        f'<link rel="apple-touch-startup-image" href="/my/startup-{w * r}x{h * r}.png?v={v}" '
        f'media="(device-width: {w}px) and (device-height: {h}px) and (-webkit-device-pixel-ratio: {r}) '
        f'and (orientation: portrait)">' for w, h, r in DEVICES)
    return links + opening(biz, c, pal, v)


def opening(biz: Dict[str, Any], c: Dict[str, str], pal: Dict[str, Any], v: str) -> str:
    """The in-app opening screen: a layer on <html>, added by the script
    only when the app was opened from the home screen, once per launch.
    About a second, or until the page has loaded (whichever is later, at
    most 2.5 s), then a fade; with reduced motion it's simply removed.
    Without script, nothing covers the page."""
    bg = ground(biz, c, pal)
    lum = _lum(_rgb(bg))
    ink = "#ffffff" if lum < 0.4 or c["background"] == "photo" else "#111113"
    photo = ""
    if c["background"] == "photo" and re.fullmatch(r"[^\s\"'()<>\\]{1,500}", c["photo"]):
        photo = f",linear-gradient(rgba(0,0,0,.45),rgba(0,0,0,.45)),url(\"{c['photo']}\") center/cover no-repeat"
    css = (
        "html.mb-open::before,html.mb-open::after{position:fixed;z-index:2147483647;pointer-events:none;"
        "transition:opacity .35s ease;}"
        f"html.mb-open::before{{content:\"\";inset:0;background:url(\"/my/opening-mark.png?v={v}\") center/"
        f"min(62vw,340px) auto no-repeat{photo},{bg};}}"
        f"html.mb-open::after{{content:\"POWERED BY\\A Solutionist\";white-space:pre;left:0;right:0;"
        "bottom:calc(48px + env(safe-area-inset-bottom));text-align:center;"
        f"font:600 11px/1.6 system-ui,-apple-system,sans-serif;letter-spacing:.18em;color:{ink};}}"
        "html.mb-open.mb-open-out::before,html.mb-open.mb-open-out::after{opacity:0;}"
        "@media (prefers-reduced-motion:reduce){html.mb-open::before,html.mb-open::after{transition:none;}}"
    )
    js = ("(function(){try{var s=window.matchMedia('(display-mode: standalone)').matches||navigator.standalone===true;"
          "if(!s||sessionStorage.getItem('mb-opened'))return;sessionStorage.setItem('mb-opened','1');}catch(e){return;}"
          "var h=document.documentElement,t0=Date.now();h.classList.add('mb-open');"
          "var still=window.matchMedia('(prefers-reduced-motion: reduce)').matches,done=false;"
          "function off(){if(done)return;done=true;if(still){h.classList.remove('mb-open');return;}"
          "h.classList.add('mb-open-out');setTimeout(function(){h.classList.remove('mb-open','mb-open-out');},400);}"
          "function soon(){setTimeout(off,Math.max(0,1000-(Date.now()-t0)));}"
          "if(document.readyState==='complete')soon();else window.addEventListener('load',soon);"
          "setTimeout(off,2500);})();")
    return f"<style>{css}</style><script>{js}</script>"


def manifest_overrides(biz: Dict[str, Any], pal: Dict[str, Any]) -> Dict[str, Any]:
    """What the chosen icon changes in the manifest: {} with no choice."""
    c = choice(biz)
    out: Dict[str, Any] = {}
    name = short(biz)
    if name:
        out["short_name"] = name
    if not c:
        return out
    v = version(c)
    out["background_color"] = ground(biz, c, pal)
    out["icons"] = ([{"src": f"/my/icon-{s}.png?v={v}", "sizes": f"{s}x{s}", "type": "image/png", "purpose": "any"}
                     for s in (192, 512)]
                    + [{"src": f"/my/icon-{s}.png?v={v}", "sizes": f"{s}x{s}", "type": "image/png", "purpose": "maskable"}
                       for s in (192, 512)])
    return out


def startup_size(path: str) -> Optional[Tuple[int, int]]:
    m = STARTUP_RE.fullmatch(path or "")
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    return (w, h) if (w, h) in STARTUP_SIZES else None


# ─── the office ──────────────────────────────────────────────────────


def office_payload(biz: Dict[str, Any], photos: List[str]) -> Dict[str, Any]:
    """What Settings → Member page shows: the choice, the name, and what
    the previews are drawn from."""
    import member_app_install as mai
    return {"app_icon": choice(biz), "app_short_name": short(biz),
            "short_name_default": mai.short_name(biz.get("name") or ""),
            "icon_logo": logo_url(biz), "icon_upload": upload_url(biz), "icon_photos": photos[:24]}


def clean_choice(raw: Any, biz: Dict[str, Any], photos: List[str]) -> Optional[Dict[str, str]]:
    """The owner's choice, checked: None when it isn't one we can draw."""
    if not isinstance(raw, dict):
        return None
    source, background = raw.get("source"), raw.get("background")
    if source not in SOURCES or background not in BACKGROUNDS:
        return None
    if source == "upload" and not upload_url(biz):
        return None
    if source == "logo" and not logo_url(biz):
        return None
    photo = str(raw.get("photo") or "") if background == "photo" else ""
    if background == "photo" and photo not in photos:
        return None
    return {"source": source, "background": background, "photo": photo}


# ─── an uploaded icon ────────────────────────────────────────────────


def prepare_icon(raw: bytes) -> bytes:
    """A square icon made safe to keep: a JPG, PNG or WebP under 12 MB,
    square (within 2%) and at least 1024 on a side, turned upright and kept
    as a 1024 PNG (transparency kept, the camera's data gone). Raises
    member_photos.PhotoError."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    import member_app_pictures as mapic
    import member_photos as ph
    if not raw:
        raise ph.PhotoError("empty")
    if len(raw) > mapic.MAX_BYTES:
        raise ph.PhotoError("too large")
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in ("JPEG", "PNG", "WEBP", "MPO") or im.width * im.height > 40_000_000:
                raise ph.PhotoError("kind")
            im.load()
            im = ImageOps.exif_transpose(im)
            w, h = im.size
            if min(w, h) < UPLOAD_MIN or abs(w - h) > max(w, h) * 0.02:
                raise ph.PhotoError("shape")
            im = ImageOps.fit(im.convert("RGBA"), (UPLOAD_MIN, UPLOAD_MIN), Image.LANCZOS)
            out = io.BytesIO()
            im.save(out, "PNG", optimize=True)
            return out.getvalue()
    except ph.PhotoError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise ph.PhotoError("unreadable")


def store_icon(business_id: str, png: bytes) -> Optional[str]:
    """The icon in the public business-assets bucket; its URL, or None."""
    import secrets
    import brand_engine
    import storage_links
    try:
        key = storage_links.business_object_key(business_id, f"member-app-icon-{secrets.token_hex(8)}.png", prefix="brand/")
    except ValueError:
        return None
    url, _why = brand_engine._storage_upload(key, png, "image/png")
    return url
