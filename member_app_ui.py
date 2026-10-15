"""
member_app_ui.py — the member app's look ("Broadcast", Kevin 2026-09-30;
taken further for the phone 2026-10-14).

The member page (/my, member_portal.py + member_portal_church.py +
member_portal_sermons.py) is one small app on a church's own address:
Home · Sermons · Bible · Groups · Live in a bar that floats over the page,
Me on the profile picture. Kevin picked the dark "Broadcast" direction
after walking through his church's current app, then asked that it not
be the same blue for everyone: the ground is TINTED FROM EACH CHURCH'S
BRAND — near-black carrying the brand's hue (Rivers reads ink-navy, a red
church warm black, a green church green-black), with the brand's own
accent on the one main button per screen. A church with no colour gets a
warm neutral.

2026-10-14 (Kevin approved the "Member App, Next Level" design): Home
opens on the church's own photo with the greeting written on it, the next
gathering in a glass card over the photo's foot, a verse of the day, and
the tab bar floating. Photos come from member_app_photos and are toned to
the church's colour here in CSS, so a set of mixed photos reads as one.
A church with no photos gets generated art (gen_art), and series still
get generated posters (brand-derived gradient, a large faded initial, a
fine line texture) in a colour that is stable per series.

The display type is Archivo, narrowed, for every church: it is the
look's voice. Reading text stays in the church's own body font, and
scripture is set in Newsreader.

Pure functions, no I/O.
"""
from __future__ import annotations

import colorsys
import hashlib
from html import escape
from string import Template
from typing import Any, Dict, Optional, Tuple

from public_form_theme import color, contrast, readable

NEUTRAL_HUE = 30 / 360        # warm, for a church with no colour at all
GOLD = "#F2C77E"

TABS = (
    ("home", "/my", "Home",
     '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>'),
    ("sermons", "/my/sermons", "Sermons",
     '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/>'
     '<path d="M12 19v3"/>'),
    ("bible", "/my/bible", "Bible",
     '<path d="M2 4h6a4 4 0 0 1 4 4v13a3 3 0 0 0-3-3H2z"/><path d="M22 4h-6a4 4 0 0 0-4 4v13a3 3 0 0 1 3-3h7z"/>'),
    ("groups", "/my/groups", "Groups",
     '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
     '<path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>'),
    ("live", "/my/live", "Live",
     '<circle cx="12" cy="12" r="2"/><path d="M16.24 7.76a6 6 0 0 1 0 8.49M7.76 16.24a6 6 0 0 1 0-8.49'
     'M19.07 4.93a10 10 0 0 1 0 14.14M4.93 19.07a10 10 0 0 1 0-14.14"/>'),
)

ICONS = {
    "heart": '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7z"/>',
    "lock": '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "calendar": '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    "play": '<polygon points="7 4 20 12 7 20 7 4" fill="currentColor" stroke="none"/>',
    "chevron": '<path d="m9 18 6-6-6-6"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
             '<path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    "back": '<path d="m15 18-6-6 6-6"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "share": '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/>'
             '<path d="m8.6 13.5 6.8 4M15.4 6.5l-6.8 4"/>',
    "chat": '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    "doc": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h5"/>',
    "bell": '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    "pray": '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/><path d="M15.8 9.2a2.5 2.5 0 0 0-3.5 0l-.3.4-.35-.3a2.42 2.42 0 1 0-3.2 3.6l3.6 3.5 3.6-3.5c1.2-1.2 1.1-2.7.2-3.7"/>',
    "book": '<path d="M2 4h6a4 4 0 0 1 4 4v13a3 3 0 0 0-3-3H2z"/><path d="M22 4h-6a4 4 0 0 0-4 4v13a3 3 0 0 1 3-3h7z"/>',
    "live": '<circle cx="12" cy="12" r="2"/><path d="M16.24 7.76a6 6 0 0 1 0 8.49M7.76 16.24a6 6 0 0 1 0-8.49'
            'M19.07 4.93a10 10 0 0 1 0 14.14M4.93 19.07a10 10 0 0 1 0-14.14"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "send": '<path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/>',
    "video": '<path d="m22 8-6 4 6 4z"/><rect x="2" y="6" width="14" height="12" rx="2"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
}


def icon(name: str, size: int = 20) -> str:
    return (f'<svg class="mb-ic" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
            f'aria-hidden="true" focusable="false">{ICONS[name]}</svg>')


# ─── colour ──────────────────────────────────────────────────────────


def _hls(hex_: str) -> Tuple[float, float, float]:
    r, g, b = (int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hls(r, g, b)


def _hex(h: float, l: float, s: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h % 1.0, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def _rgba(hex_: str, a: float) -> str:
    return f"rgba({int(hex_[1:3], 16)},{int(hex_[3:5], 16)},{int(hex_[5:7], 16)},{a})"


def brand_colour(biz: Dict[str, Any], theme: Dict[str, Any]) -> Optional[str]:
    """The colour the ground is tinted from: the brand's primary (then
    secondary, then accent) — the first one with real colour in it."""
    kit = ((biz or {}).get("settings") or {}).get("brand_kit") or {}
    kit = kit if isinstance(kit, dict) else {}
    cols = kit.get("colors") if isinstance(kit.get("colors"), dict) else {}
    for c in (cols.get("primary"), kit.get("primary_color"), cols.get("secondary"), theme.get("accent")):
        c = color(c)
        if c and _hls(c)[2] >= 0.18 and 0.08 <= _hls(c)[1] <= 0.92:
            return c
    return None


def _fill(acc: str, ground: str) -> Optional[str]:
    """A button colour in the accent's own hue that carries WHITE text
    (4.5:1) and still stands off the ground (3:1), or None when the hue
    can't do both (gold, yellow): the light accent with dark text is used."""
    h, _, s = _hls(acc)
    # Gold, amber and yellow look muddy when darkened for white text.
    if s < 0.25 or 0.07 <= h <= 0.19:
        return None
    for i in range(20):
        c = _hex(h, 0.62 - i * 0.02, max(s, 0.55))
        if contrast("#FFFFFF", c) >= 4.5:
            return c if contrast(c, ground) >= 3 else None
    return None


def palette(biz: Dict[str, Any], theme: Dict[str, Any]) -> Dict[str, str]:
    """The page's colours. Ground, surfaces and text carry the brand's hue
    (near-black, low saturation); the accent is the brand's own accent,
    lightened in its own hue until it reads on the ground."""
    tint = brand_colour(biz, theme)
    h, s = (_hls(tint)[0], min(_hls(tint)[2], 0.55)) if tint else (NEUTRAL_HUE, 0.10)
    p = {
        "tint": tint or _hex(h, 0.45, 0.25),
        "ground": _hex(h, 0.065, s * 0.55),
        "surface": _hex(h, 0.115, s * 0.42),
        "surface2": _hex(h, 0.155, s * 0.40),
        "line": _hex(h, 0.21, s * 0.35),
        "text": _hex(h, 0.95, 0.30),
        "muted": _hex(h, 0.74, s * 0.25 + 0.06),
        "dim": _hex(h, 0.58, s * 0.20 + 0.05),
        # the glow behind Home's photo, and the colour photos are toned to
        "glow": _hex(h, 0.42, max(s, 0.5) if tint else 0.25),
        "ptint": _hex(h, 0.42, min(0.38, max(s, 0.18))),
    }
    brand_acc = color(theme.get("accent")) or p["tint"]
    acc = brand_acc
    ah, al, as_ = _hls(acc)
    for _ in range(12):
        if contrast(acc, p["ground"]) >= 4.5:
            break
        al = min(0.85, al + 0.06)
        acc = _hex(ah, al, max(as_, 0.45) if as_ > 0.08 else as_)
    if contrast(acc, p["ground"]) < 3:
        acc = GOLD
    p["accent"] = acc
    p["on_accent"] = readable(acc)
    fill = _fill(brand_acc, p["ground"]) if acc != GOLD else None
    p["fill"] = fill or acc
    p["on_fill"] = "#FFFFFF" if fill else p["on_accent"]
    p["error"] = "#FFB4A6"
    return p


def accent_for(biz: Dict[str, Any], theme: Dict[str, Any]) -> str:
    return palette(biz, theme)["accent"]


def poster_colours(key: Any, pal: Dict[str, str]) -> Tuple[str, str]:
    """A stable (light, deep) gradient pair per series/group: the brand's
    hue, the accent's hue, and three neighbours of them."""
    th = _hls(pal["tint"])[0]
    ah = _hls(pal["accent"])[0]
    hues = (th, ah, th + 0.11, th - 0.11, ah + 0.5)
    n = int(hashlib.sha256(str(key or "").encode()).hexdigest()[:8], 16)
    hue = hues[n % len(hues)]
    return _hex(hue, 0.50, 0.62), _hex(hue, 0.16, 0.55)


def poster_style(key: Any, pal: Dict[str, str]) -> str:
    light, deep = poster_colours(key, pal)
    return (f"background:radial-gradient(90% 90% at 85% 0%,{light} 0%,transparent 70%),"
            f"linear-gradient(160deg,{light} 0%,{deep} 100%);color:#fff")


def poster(key: Any, pal: Dict[str, str], title: str, kick: str = "", *, tag: str = "span",
           cls: str = "", play: bool = False, title_id: str = "", title_tag: str = "span",
           attrs: str = "") -> str:
    """Generated series art: gradient, the title's faded initial, a fine
    line texture and the title in heavy type. Text is escaped here;
    `attrs` is trusted markup from the caller (an href, aria)."""
    t = escape(str(title or ""))
    ghost = escape((str(title or "").strip()[:1] or "").upper())
    tid = f' id="{escape(title_id)}"' if title_id else ""
    play_html = f'<span class="mb-art-play" aria-hidden="true">{icon("play", 18)}</span>' if play else ""
    kick_html = f'<span class="mb-art-kick">{escape(kick)}</span>' if kick else ""
    return (f'<{tag} class="mb-art {cls}" style="{poster_style(key, pal)}"{(" " + attrs) if attrs else ""}>'
            f'<span class="mb-art-ghost" aria-hidden="true">{ghost}</span>{play_html}{kick_html}'
            f'<{title_tag} class="mb-art-title"{tid}>{t}</{title_tag}></{tag}>')


def photo(url: str, cls: str = "", *, eager: bool = False) -> str:
    """One of the church's photos, toned to its colour (CSS). Decorative:
    the card around it carries the words."""
    load = 'fetchpriority="high"' if eager else 'loading="lazy"'
    return (f'<span class="mb-ph {cls}" aria-hidden="true"><img src="{escape(url, quote=True)}" alt="" '
            f'{load} decoding="async"></span>')


def gen_art(name: Any, cls: str = "") -> str:
    """Art made from the church's colours and initials, for a church with
    no photos yet."""
    return (f'<span class="mb-gen {cls}" aria-hidden="true"><span class="mb-gen-ghost">'
            f'{escape(initials(name))}</span></span>')


def cover(url: str, key: Any, pal: Dict[str, str], title: str, kick: str = "") -> str:
    """A card's picture: the church's photo when it has one, else a poster."""
    if url:
        return photo(url, "mb-cover")
    return poster(key, pal, title, kick, cls="mb-cover")


def initials(name: Any) -> str:
    """'Ana Rivers' → AR; 'Rivers of Living Water' → RL (small lowercase
    words like 'of' are skipped)."""
    words = [p for p in str(name or "").split() if p[:1].isalpha()]
    parts = [p for p in words if p[:1].isupper()] or words
    return ("".join(p[0] for p in parts[:2]) or "?").upper()


def ring(n: int, of: int, size: int = 64) -> str:
    """A progress ring, n of `of`, with n in the middle."""
    r = size / 2 - 5
    c = 2 * 3.14159 * r
    done = max(0.0, min(1.0, n / of if of else 0))
    return (f'<span class="mb-ring" style="width:{size}px;height:{size}px" aria-hidden="true">'
            f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
            f'<circle cx="{size / 2}" cy="{size / 2}" r="{r}" fill="none" stroke="var(--mb-surface-2)" stroke-width="7"/>'
            f'<circle cx="{size / 2}" cy="{size / 2}" r="{r}" fill="none" stroke="var(--accent)" stroke-width="7" '
            f'stroke-linecap="round" stroke-dasharray="{c * done:.1f} {c:.1f}"/></svg><b>{int(n)}</b></span>')


def nav(active: Optional[str]) -> str:
    items = []
    for key, href, label, paths in TABS:
        cur = ' aria-current="page"' if key == active else ""
        items.append(f'<a class="mb-tab" href="{href}"{cur}><svg width="22" height="22" '
                     f'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
                     f'stroke-linejoin="round" aria-hidden="true" focusable="false">{paths}</svg><span>{label}</span></a>')
    return f'<nav class="mb-nav mp-noprint" aria-label="Main">{"".join(items)}</nav>'


# The look's own faces: Archivo (narrowed for display) and Newsreader for
# scripture. The church's body font still sets the reading text.
FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,400..900'
         '&amp;family=Newsreader:ital,opsz,wght@0,6..72,400..600;1,6..72,400..600&amp;display=swap">')

# The header turns solid once the page scrolls under it.
SCROLL_JS = ("<script>(function(){var t=document.querySelector('.mb-top');if(!t)return;"
             "function f(){t.classList.toggle('is-solid',window.scrollY>12);}"
             "f();window.addEventListener('scroll',f,{passive:true});})();</script>")

GRAIN = ("url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='140' height='140'>"
         "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2' stitchTiles='stitch'/>"
         "</filter><rect width='140' height='140' filter='url(%23n)'/></svg>\")")

_CSS = Template(""":root{--surface:$ground;--input-surface:$surface2;--text-primary:$text;--text-secondary:$muted;
--text-muted:$dim;--border:$line;--accent:$accent;--accent-text:$on_accent;--focus:$accent;
--error:$error;--mb-surface:$surface;--mb-surface-2:$surface2;--mb-line:$line;--mb-fill:$fill;--mb-on-fill:$on_fill;
--mb-soft:$soft;--mb-soft-line:$soft_line;--mb-nav:$nav_bg;--mb-ptint:$ptint;
--mb-display:"Archivo",var(--font-heading),system-ui,sans-serif;--mb-serif:"Newsreader",Georgia,"Times New Roman",serif;
color-scheme:dark;}
[hidden]{display:none!important}
html,body{margin:0;padding:0;font-family:var(--font-body);color:var(--text-primary);background:var(--surface);min-height:100vh;}
body{position:relative;-webkit-font-smoothing:antialiased;overflow-x:hidden;}
body::before{content:"";position:absolute;inset:0 0 auto 0;height:460px;pointer-events:none;z-index:0;
  background:radial-gradient(120% 90% at 88% -12%,$glow55 0%,transparent 62%),
             radial-gradient(90% 70% at -12% 8%,$accent20 0%,transparent 58%);}
body::after{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;opacity:.06;mix-blend-mode:overlay;background-image:$grain;}
*{box-sizing:border-box;}
a{color:var(--accent);}

/* the header: brand on the left, Give · Messages · Me on the right; it floats over Home's photo */
.mb-top{position:sticky;top:0;z-index:15;display:flex;align-items:center;justify-content:space-between;gap:10px;max-width:560px;margin:0 auto;
  padding:calc(10px + env(safe-area-inset-top,0px)) max(18px,env(safe-area-inset-right,0px)) 10px max(18px,env(safe-area-inset-left,0px));
  transition:background .25s ease,box-shadow .25s ease;}
.mb-top.is-solid{background:$ground86;-webkit-backdrop-filter:blur(18px) saturate(1.4);backdrop-filter:blur(18px) saturate(1.4);box-shadow:0 1px 0 var(--mb-line);}
.mb-brand{display:flex;align-items:center;gap:10px;min-width:0;text-decoration:none;color:var(--text-primary);height:40px;}
.mb-mark{width:36px;height:36px;flex:none;border-radius:11px;display:grid;place-items:center;font-weight:900;font-size:13px;
  font-family:var(--mb-display);background:var(--text-primary);color:var(--surface);overflow:hidden;}
.mb-mark img{width:100%;height:100%;object-fit:contain;background:#fff;}
.mb-wordmark{display:block;height:28px;width:auto;max-width:150px;object-fit:contain;filter:drop-shadow(0 1px 8px rgba(0,0,0,.35));}
.mp-church{font-family:var(--mb-display);font-size:13px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;margin:0;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.mb-top-right{display:flex;align-items:center;gap:8px;flex:none;}
.mb-give{display:inline-flex;align-items:center;gap:6px;height:38px;padding:0 13px 0 10px;border-radius:999px;text-decoration:none;
  background:$accent24;color:var(--accent);border:1px solid $accent50;font-size:13px;font-weight:800;
  -webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);}
.mb-chat-link{width:38px;height:38px;flex:none;border-radius:50%;display:grid;place-items:center;color:var(--text-primary);position:relative;
  border:1px solid $text20;background:rgba(0,0,0,.22);text-decoration:none;-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);}
.mb-avatar{width:38px;height:38px;flex:none;border-radius:50%;display:grid;place-items:center;font-weight:800;font-size:13px;
  text-decoration:none;color:#fff;background:linear-gradient(140deg,var(--mb-fill),$glow);box-shadow:0 0 0 2px $text25;}
.mb-avatar[aria-current]{box-shadow:0 0 0 2px var(--surface),0 0 0 4px var(--accent);}
.mb-preview{position:relative;z-index:16;display:flex;align-items:center;gap:10px;
  padding:calc(10px + env(safe-area-inset-top,0px)) max(18px,env(safe-area-inset-right,0px)) 10px max(18px,env(safe-area-inset-left,0px));
  background:var(--mb-fill);color:var(--mb-on-fill);font-size:13px;line-height:1.35;}
.mb-preview + .mb-top{padding-top:10px;}
.mb-preview span{flex:1;min-width:0;max-width:520px;margin:0 auto;}
.mb-preview form{margin:0;flex:none;}
.mb-preview button{min-height:36px;padding:0 12px;border-radius:999px;border:1.5px solid currentColor;background:transparent;color:inherit;
  font:inherit;font-weight:800;cursor:pointer;}

.mp-shell{position:relative;z-index:1;max-width:560px;margin:0 auto;padding:6px 20px 40px;}
.mp-shell.mb-has-nav{padding-bottom:calc(132px + env(safe-area-inset-bottom,0px));}
.mb-bare{padding-top:0;}

/* photos and generated art */
.mb-ph{position:relative;display:block;overflow:hidden;isolation:isolate;background:var(--mb-surface-2);}
.mb-ph img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;filter:grayscale(1) contrast(1.08) brightness(.9);}
.mb-ph::after{content:"";position:absolute;inset:0;background:var(--mb-ptint);mix-blend-mode:color;opacity:.5;}
.mb-gen{position:relative;display:block;overflow:hidden;background:
  radial-gradient(110% 80% at 88% -5%,$glow85 0%,transparent 62%),
  radial-gradient(80% 60% at -10% 40%,$accent28 0%,transparent 60%),var(--surface);}
.mb-gen::before{content:"";position:absolute;inset:0;background:repeating-linear-gradient(115deg,rgba(255,255,255,.05) 0 1px,transparent 1px 15px);}
.mb-gen-ghost{position:absolute;right:-22px;top:64px;font-family:var(--mb-display);font-stretch:62%;font-size:300px;font-weight:900;
  line-height:.8;letter-spacing:-.04em;color:var(--text-primary);opacity:.07;}
.mb-cover{position:absolute;inset:0;border-radius:0;aspect-ratio:auto;}

/* Home */
.mb-hero{position:relative;isolation:isolate;overflow:hidden;display:flex;align-items:flex-end;min-height:420px;
  margin:calc(-66px - env(safe-area-inset-top,0px)) -20px 0;padding:0 22px 26px;}
.mb-preview ~ .mp-shell .mb-hero{margin-top:-66px;}
.mb-hero.mb-over{min-height:470px;padding-bottom:96px;}
.mb-hero>.mb-ph,.mb-hero>.mb-gen{position:absolute;inset:0;z-index:-2;}
.mb-hero>.mb-ph img{object-position:center 22%;}
.mb-hero::after{content:"";position:absolute;inset:0;z-index:-1;background:linear-gradient(180deg,$ground78 0%,transparent 30%,$ground25 55%,var(--surface) 100%);}
.mb-hero-in{width:100%;}
.mb-date{font-size:11.5px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:var(--text-secondary);margin:0 0 8px;min-height:1em;}
h1{font-family:var(--mb-display);font-stretch:74%;font-size:36px;font-weight:900;line-height:.95;letter-spacing:-.01em;margin:18px 0 10px;text-wrap:balance;}
.mb-hello{font-size:clamp(44px,13vw,56px);font-stretch:70%;line-height:.9;margin:0;}
h2{font-family:var(--mb-display);font-stretch:85%;font-size:20px;font-weight:800;margin:0 0 8px;}
p{line-height:1.55;margin:0 0 12px;}
.mb-kick{display:block;font-size:11px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:var(--accent);}

.mb-next{position:relative;z-index:3;margin:18px 0 0;border-radius:26px;padding:16px;display:block;color:var(--text-primary);
  background:$surface84;-webkit-backdrop-filter:blur(22px) saturate(1.3);backdrop-filter:blur(22px) saturate(1.3);
  border:1px solid $text11;box-shadow:0 22px 50px rgba(0,0,0,.45);}
.mb-hero + .mb-next{margin-top:-80px;}
.mb-next-top{display:flex;gap:14px;align-items:flex-start;}
.mb-datebox{width:58px;flex:none;border-radius:17px;text-align:center;padding:8px 0 9px;display:flex;flex-direction:column;align-items:center;
  background:var(--mb-fill);color:var(--mb-on-fill);box-shadow:0 10px 22px $fill35;}
.mb-datebox span{font-size:10.5px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;opacity:.92;}
.mb-datebox b{font-family:var(--mb-display);font-size:30px;font-stretch:76%;font-weight:900;line-height:1;}
.mb-what{flex:1;min-width:0;display:flex;flex-direction:column;gap:3px;}
.mb-what strong{font-family:var(--mb-display);font-size:21px;font-stretch:84%;font-weight:800;line-height:1.1;}
.mb-what strong a{color:inherit;text-decoration:none;}
.mb-what>span:not(.mb-chip):not(.mb-kick){font-size:13px;color:var(--text-secondary);}
.mb-count{display:flex;align-items:center;gap:8px;margin:12px 0 0;font-size:13px;color:var(--text-secondary);}
.mb-count .mb-ic{color:var(--accent);}
.mb-next-acts{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:14px;}
.mb-next-acts form{margin:0;display:contents;}
.mb-next-acts>:only-child{grid-column:1/-1;}
.mb-next .mb-chip{margin-top:6px;}
.mb-live-now{display:flex;align-items:center;gap:14px;text-decoration:none;}
.mb-live-now .mb-what{flex:1 1 160px;}

.mb-quick{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(0,1fr);gap:10px;margin:20px 0 0;}
.mb-quick a{display:flex;flex-direction:column;align-items:center;gap:7px;text-decoration:none;font-size:12px;font-weight:600;color:var(--text-secondary);}
.mb-quick a span{width:100%;max-width:74px;aspect-ratio:1;border-radius:23px;display:grid;place-items:center;background:var(--mb-surface);
  border:1px solid var(--mb-line);color:var(--text-primary);}
.mb-quick a.mb-main span{background:var(--mb-fill);color:var(--mb-on-fill);border-color:transparent;box-shadow:0 12px 26px $fill38;}

.mb-verse{position:relative;overflow:hidden;margin:22px 0 0;padding:20px 20px 16px;border-radius:26px;border:1px solid var(--mb-line);
  background:radial-gradient(120% 120% at 100% 0%,$glow42 0%,transparent 62%),var(--mb-surface);}
.mb-verse::before{content:"\\201C";position:absolute;right:14px;top:-22px;font-family:var(--mb-serif);font-size:150px;line-height:1;color:var(--accent);opacity:.18;}
.mb-verse blockquote{position:relative;font-family:var(--mb-serif);font-style:italic;font-weight:500;font-size:25px;line-height:1.22;margin:10px 0 16px;text-wrap:balance;}
.mb-verse blockquote i{font-style:normal;}
.mb-verse-foot{display:flex;justify-content:space-between;align-items:center;gap:10px;font-size:13px;color:var(--text-secondary);}
.mb-verse-foot a{font-weight:700;text-decoration:none;display:inline-flex;align-items:center;gap:2px;}

.mp-sect{font-family:var(--font-body);font-size:12px;font-weight:800;letter-spacing:.16em;text-transform:uppercase;color:var(--text-muted);
  margin:30px 0 12px;display:flex;justify-content:space-between;align-items:baseline;gap:10px;}
.mp-sect a{letter-spacing:0;text-transform:none;font-size:13px;color:var(--text-secondary);text-decoration:none;font-weight:600;}

.mb-mcard{display:block;border-radius:26px;overflow:hidden;background:var(--mb-surface);border:1px solid var(--mb-line);text-decoration:none;color:var(--text-primary);}
.mb-mcard .mb-art{border-radius:0;}
.mb-mcard-b{display:block;padding:14px 16px 16px;}
.mb-msg-title{font-family:var(--mb-display);font-stretch:84%;font-size:20px;font-weight:800;margin:0 0 3px;line-height:1.15;}
.mb-msg-title a{color:inherit;text-decoration:none;}
.mb-meta{font-size:13px;color:var(--text-secondary);margin:0;}

.mb-week{display:flex;gap:12px;overflow-x:auto;scroll-snap-type:x mandatory;scroll-padding-inline:20px;margin:0 -20px;padding:0 20px 4px;scrollbar-width:none;}
.mb-week::-webkit-scrollbar{display:none;}
.mb-wk{position:relative;flex:none;width:176px;scroll-snap-align:start;border-radius:22px;overflow:hidden;background:var(--mb-surface);
  border:1px solid var(--mb-line);display:flex;flex-direction:column;text-decoration:none;color:var(--text-primary);}
.mb-wk-cov{position:relative;display:block;height:104px;overflow:hidden;}
.mb-wk-cov .mb-art{height:100%;padding:10px 12px;}
.mb-wk-cov .mb-art-title{font-size:22px;}
.mb-wk-cov .mb-art-ghost{font-size:130px;}
.mb-wk-d{position:absolute;left:10px;bottom:10px;z-index:3;padding:4px 8px;border-radius:8px;background:rgba(0,0,0,.55);color:#fff;
  -webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);font-size:10.5px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;}
.mb-wk-b{display:flex;flex-direction:column;gap:4px;padding:11px 12px 13px;}
.mb-wk strong{font-size:14.5px;line-height:1.2;}
.mb-wk-s{font-size:12px;color:var(--text-secondary);}

.mb-plan{display:flex;gap:16px;align-items:center;padding:16px;border-radius:24px;background:var(--mb-surface);border:1px solid var(--mb-line);margin:0;}
.mb-plan-b{flex:1;min-width:0;}
.mb-plan-b strong{display:block;font-family:var(--mb-display);font-stretch:85%;font-size:19px;line-height:1.15;margin:2px 0 0;}
.mb-plan-b .mb-plan-acts{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px;align-items:center;}
.mb-plan-b .mp-go{width:auto;min-height:38px;padding:0 14px;font-size:13px;border-radius:12px;}
.mb-plan-b form{margin:0;}
.mb-ring{position:relative;flex:none;display:block;}
.mb-ring svg{display:block;transform:rotate(-90deg);}
.mb-ring b{position:absolute;inset:0;display:grid;place-items:center;font-family:var(--mb-display);font-size:17px;font-weight:900;font-stretch:80%;}

.mb-reading-card{display:flex;align-items:center;gap:14px;padding:16px;border-radius:24px;background:var(--mb-surface);border:1px solid var(--mb-line);
  text-decoration:none;color:var(--text-primary);}
.mb-book{width:50px;height:60px;flex:none;border-radius:8px 14px 14px 8px;display:grid;place-items:center;font-family:var(--mb-serif);font-size:22px;
  font-weight:600;color:var(--mb-on-fill);background:linear-gradient(160deg,var(--mb-fill),$glow);box-shadow:inset 4px 0 0 rgba(0,0,0,.18);}
.mb-reading-card strong{display:block;font-size:16px;}
.mb-reading-card .mb-ic:last-child{color:var(--text-muted);flex:none;}

.mb-pray{display:flex;gap:14px;align-items:center;margin:26px 0 0;padding:18px;border-radius:24px;border:1.5px dashed $text24;
  color:var(--text-primary);text-decoration:none;}
.mb-pray-ic{width:46px;height:46px;flex:none;border-radius:15px;display:grid;place-items:center;background:var(--mb-soft);color:var(--accent);}
.mb-pray strong{display:block;font-size:16px;}
.mb-pray span span{font-size:13px;color:var(--text-secondary);}

/* large-title pages */
.mb-lt{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;margin:14px 0 6px;}
.mb-lt h1{font-size:44px;font-stretch:68%;line-height:.92;margin:0;}
.mb-soon{position:relative;isolation:isolate;display:flex;align-items:flex-end;min-height:250px;margin:16px 0 0;border-radius:28px;overflow:hidden;
  border:1px solid var(--mb-line);}
.mb-soon>.mb-gen{position:absolute;inset:0;z-index:-2;}
.mb-soon::after{content:"";position:absolute;inset:0;z-index:-1;background:linear-gradient(180deg,transparent 30%,$ground92);}
.mb-soon-in{padding:20px;}
.mb-soon h2{font-size:34px;font-stretch:68%;font-weight:900;line-height:.92;margin:6px 0 8px;text-transform:uppercase;}
.mb-soon p{margin:0;color:var(--text-secondary);font-size:14px;}
.mb-pair{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:14px 0 0;}
.mb-pair .mp-go{width:auto;padding:0 10px;font-size:14px;}

/* generic pieces, older renderers included */
.mp-muted{color:var(--text-secondary);font-size:14px;}
.mp-card{background:var(--mb-surface);border:1px solid var(--mb-line);border-radius:24px;padding:18px;margin-bottom:14px;}
.mp-card>:last-child{margin-bottom:0;}
.mp-form{display:flex;flex-direction:column;gap:10px;}
label{font-size:14px;font-weight:600;}
.mp-input{width:100%;padding:12px 16px;font-size:16px;border:1px solid var(--border);border-radius:16px;background:var(--input-surface);
  color:var(--text-primary);min-height:52px;font-family:var(--font-body);}
.mp-code{letter-spacing:.5em;text-align:center;font-size:28px;font-weight:800;font-variant-numeric:tabular-nums;min-height:64px;padding-left:.5em;}
.mp-go{width:100%;padding:13px 16px;font-size:15px;font-weight:800;border:0;border-radius:16px;background:var(--mb-fill);color:var(--mb-on-fill);
  cursor:pointer;min-height:50px;font-family:var(--font-body);text-align:center;text-decoration:none;display:inline-flex;align-items:center;
  justify-content:center;gap:8px;}
.mp-go-2{background:$text08;color:var(--text-primary);border:1px solid $text14;}
.mb-soft{background:var(--mb-soft);color:var(--accent);border:1px solid var(--mb-soft-line);}
.mp-link{background:none;border:0;padding:10px 0;min-height:44px;font:inherit;font-size:14px;color:var(--text-secondary);cursor:pointer;
  text-decoration:underline;text-underline-offset:3px;}
.mb-back{display:inline-flex;align-items:center;gap:4px;min-height:44px;color:var(--text-secondary);text-decoration:none;font-size:14px;margin:4px 0 0;}
.mp-err{color:var(--error);font-size:14px;font-weight:600;}
.mp-flash{padding:12px 14px;border-radius:16px;background:var(--mb-surface-2);border:1px solid var(--mb-line);margin:16px 0;}
.mp-ok{color:var(--text-primary);font-weight:600;font-size:14px;}
.mp-total{font-family:var(--mb-display);font-stretch:72%;font-size:48px;font-weight:900;letter-spacing:-.01em;font-variant-numeric:tabular-nums;line-height:1;margin:6px 0 0;}
.mp-gifts{list-style:none;margin:8px 0 0;padding:0;}
.mp-gifts li{display:flex;justify-content:space-between;gap:12px;padding:10px 0;border-top:1px solid var(--mb-line);font-size:14px;}
.mp-gifts li span:last-child{font-variant-numeric:tabular-nums;white-space:nowrap;font-weight:600;}
.mp-years{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 12px;}
.mp-years a{padding:6px 12px;min-height:34px;border:1px solid var(--border);border-radius:999px;color:var(--text-secondary);text-decoration:none;
  font-size:13px;font-weight:700;display:inline-flex;align-items:center;}
.mp-years a[aria-current]{background:var(--mb-soft);color:var(--accent);border-color:var(--mb-soft-line);}
.mp-row{display:flex;flex-direction:column;gap:10px;}
.mp-person{width:100%;text-align:left;padding:14px 16px;min-height:54px;border:1px solid var(--border);border-radius:16px;
  background:var(--input-surface);color:var(--text-primary);font:inherit;font-size:16px;cursor:pointer;}
.mp-when{font-size:11px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);margin:0 0 4px;}
.mp-occ h2,.mp-occ h3{font-family:var(--mb-display);font-stretch:84%;font-size:20px;font-weight:800;line-height:1.15;margin:0 0 4px;}
.mp-mine{font-size:13px;font-weight:700;margin:8px 0 0;color:var(--accent);}
.mp-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;align-items:center;}
.mp-actions:empty{display:none;}
.mp-actions form{display:contents;}
.mp-actions .mp-go{width:auto;min-height:44px;padding:0 16px;font-size:14px;border-radius:999px;}
.mp-serve{display:flex!important;gap:8px;flex-wrap:wrap;flex:1 1 100%;}
.mp-serve select{flex:1 1 160px;min-width:0;min-height:44px;}
.mp-text{min-height:150px;resize:vertical;line-height:1.5;}
.mp-check{display:flex;gap:10px;align-items:flex-start;font-weight:500;}
.mp-check input{width:20px;height:20px;margin:2px 0 0;accent-color:var(--accent);}
.mp-sr{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0;}
.mp-foot{text-align:center;font-size:12px;color:var(--text-muted);margin-top:34px;padding-top:14px;border-top:1px solid var(--mb-line);}
.mb-chip{display:inline-flex;align-items:center;gap:5px;font-size:12px;font-weight:800;padding:5px 10px;border-radius:999px;
  background:var(--mb-soft);color:var(--accent);white-space:nowrap;align-self:flex-start;}

/* sermons */
.mb-art{position:relative;display:flex;flex-direction:column;justify-content:flex-end;border-radius:22px;overflow:hidden;aspect-ratio:16/9;
  padding:14px 16px;text-decoration:none;isolation:isolate;}
.mb-art::before{content:"";position:absolute;inset:0;z-index:-1;background:repeating-linear-gradient(115deg,rgba(255,255,255,.06) 0 1px,transparent 1px 14px);}
.mb-art-ghost{position:absolute;right:-14px;top:-34px;font-family:var(--mb-display);font-stretch:62%;font-size:190px;font-weight:900;line-height:1;opacity:.14;z-index:-1;}
.mb-art-kick{font-size:10.5px;font-weight:800;letter-spacing:.2em;text-transform:uppercase;opacity:.9;margin-bottom:6px;}
.mb-art-title{font-family:var(--mb-display);font-stretch:66%;font-size:40px;font-weight:900;line-height:.9;letter-spacing:-.01em;text-transform:uppercase;
  overflow-wrap:anywhere;text-shadow:0 2px 24px rgba(0,0,0,.25);margin:0;}
.mb-art-play{position:absolute;right:14px;bottom:14px;width:52px;height:52px;border-radius:50%;display:grid;place-items:center;
  background:rgba(255,255,255,.95);color:#111;box-shadow:0 8px 24px rgba(0,0,0,.4);}
.mb-art.mb-tall{aspect-ratio:3/4;padding:12px;border-radius:18px;}
.mb-art.mb-tall .mb-art-title{font-size:23px;}
.mb-art.mb-tall .mb-art-ghost{font-size:150px;}
.mb-art.mb-band{aspect-ratio:16/8;border-radius:0;margin:0;}
.mb-art.mb-band .mb-art-title{font-size:30px;}
.mb-art.mb-band .mb-art-ghost{font-size:150px;top:-26px;}
.mb-shelf{display:flex;gap:12px;overflow-x:auto;scroll-snap-type:x mandatory;scroll-padding-inline:20px;margin:0 -20px;padding:0 20px 4px;scrollbar-width:none;}
.mb-shelf::-webkit-scrollbar{display:none;}
.mb-shelf>.mb-art{flex:none;width:138px;scroll-snap-align:start;}
.mb-list{list-style:none;margin:0;padding:0;}
.mb-list li+li{border-top:1px solid var(--mb-line);}
.mb-list a{display:flex;align-items:center;gap:13px;min-height:62px;padding:9px 0;color:var(--text-primary);text-decoration:none;}
.mb-list .mb-ic{color:var(--text-muted);flex:none;}
.mb-cards{border-radius:24px;background:var(--mb-surface);border:1px solid var(--mb-line);overflow:hidden;}
.mb-cards a{padding:10px 14px;}
.mb-list-ic{width:40px;height:40px;flex:none;border-radius:13px;display:grid;place-items:center;background:var(--mb-surface-2);}
.mb-list-ic .mb-ic{color:var(--accent);}
.mb-list-text{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}
.mb-list-text strong{font-size:15px;}
.mb-list-text span{font-size:12.5px;color:var(--text-secondary);}
.mb-thumb{width:72px;height:46px;flex:none;border-radius:12px;display:grid;place-items:center;color:#fff;}
.mb-player{margin:0 -20px;}
.mb-video{position:relative;width:100%;aspect-ratio:16/9;overflow:hidden;background:#000;}
.mb-video iframe{position:absolute;inset:0;width:100%;height:100%;border:0;}
.mb-player .mb-art{border-radius:0;aspect-ratio:16/9;}
.mb-player audio{width:calc(100% - 40px);margin:12px 20px 0;}
.mb-acts{display:flex;gap:8px;margin:16px 0 0;}
.mb-acts>*{flex:1;}
.mb-text{font-size:15.5px;line-height:1.65;white-space:pre-line;margin:0;color:var(--text-secondary);}
.mb-q{border-radius:22px;padding:16px 18px;background:var(--mb-soft);border:1px solid var(--mb-soft-line);margin-top:16px;}
.mb-q h2{font-size:15px;font-family:var(--font-body);letter-spacing:.12em;text-transform:uppercase;color:var(--accent);}
.mb-q .mb-text{color:var(--text-primary);}

/* live */
.mb-live-badge{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:7px;background:#E5484D;color:#fff;
  font-size:11px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;align-self:flex-start;}
.mb-live-dot{width:8px;height:8px;border-radius:50%;background:#fff;flex:none;}
.mb-live-dot.mb-off{background:var(--text-muted);width:10px;height:10px;margin-top:6px;}
@media (prefers-reduced-motion:no-preference){.mb-live-badge .mb-live-dot,.mb-chip .mb-live-dot{animation:mbpulse 1.6s ease-in-out infinite;}}
@keyframes mbpulse{0%,100%{opacity:1;}50%{opacity:.35;}}
.mb-offair{position:relative;isolation:isolate;overflow:hidden;display:flex;align-items:flex-end;min-height:300px;margin:0 -20px;padding:0 22px 22px;}
.mb-offair>.mb-gen,.mb-offair>.mb-ph{position:absolute;inset:0;z-index:-2;}
.mb-offair::after{content:"";position:absolute;inset:0;z-index:-1;background:linear-gradient(180deg,$ground40 0%,transparent 35%,var(--surface) 100%);}
.mb-offair h1{margin:6px 0 4px;font-size:44px;font-stretch:68%;}
.mb-prayer-link{display:flex;align-items:center;gap:12px;min-height:56px;margin-top:20px;padding:12px 14px;border-radius:18px;
  border:1px dashed var(--border);color:var(--text-secondary);text-decoration:none;font-size:14px;}
.mb-prayer-link span{flex:1;}
.mb-prayer-link .mb-ic:first-child{color:var(--accent);}
.mb-live-head{margin-top:14px;display:flex;flex-direction:column;}
.mb-live-actions{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:14px;align-items:center;}
.mb-live-actions form{margin:0;}
.mb-live-actions .mb-chip{justify-self:start;min-height:44px;padding:0 14px;font-size:13px;}
.mb-linkout{display:grid;place-items:center;padding:20px;background:var(--mb-surface-2);}
.mb-linkout .mp-go{width:auto;}
.mb-chat{list-style:none;margin:0;padding:12px;max-height:50vh;min-height:170px;overflow-y:auto;border-radius:22px;
  background:var(--mb-surface);border:1px solid var(--mb-line);display:flex;flex-direction:column;gap:8px;}
.mb-msg{max-width:84%;align-self:flex-start;display:flex;flex-direction:column;gap:2px;padding:8px 12px;border-radius:18px 18px 18px 6px;
  background:var(--mb-surface-2);}
.mb-msg.mb-mine{align-self:flex-end;border-radius:18px 18px 6px 18px;background:var(--mb-fill);color:var(--mb-on-fill);}
.mb-msg.mb-host{background:var(--mb-soft);border:1px solid var(--mb-soft-line);}
.mb-msg-who{font-size:11.5px;font-weight:800;color:var(--text-secondary);}
.mb-host .mb-msg-who{color:var(--accent);}
.mb-msg-body{font-size:15px;line-height:1.4;overflow-wrap:anywhere;}
.mb-chat-empty{align-self:center;margin:auto 0;font-size:13px;}
.mb-compose{display:flex;gap:8px;margin-top:10px;}
.mb-compose .mp-input{flex:1;min-width:0;border-radius:999px;padding:0 18px;}
.mb-compose .mp-go{width:52px;flex:none;padding:0;border-radius:50%;}
.mb-thread .mb-chat{max-height:none;min-height:46vh;background:transparent;border:0;padding:4px 0;}
.mb-thread .mb-compose{position:sticky;bottom:calc(10px + env(safe-area-inset-bottom,0px));z-index:5;padding:8px;margin:12px -8px 0;border-radius:999px;
  background:$ground86;-webkit-backdrop-filter:blur(18px);backdrop-filter:blur(18px);border:1px solid var(--mb-line);}
.mb-chat-note{margin:10px 2px 0;font-size:13px;}
.mb-chat-err{margin:8px 2px 0;}
.mb-chip .mb-live-dot,.mp-go .mb-live-dot{background:currentColor;}
.mb-start{display:flex!important;flex-wrap:wrap;gap:8px;flex:1 1 100%;}
.mb-start select{flex:1 1 200px;min-width:0;min-height:44px;}
.mb-meet{margin-top:14px;}
.mb-tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;}
.mb-tile{position:relative;aspect-ratio:4/3;border-radius:16px;overflow:hidden;background:var(--mb-surface-2);border:1px solid var(--mb-line);
  display:grid;place-items:center;}
.mb-tile video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;}
.mb-tile-name{position:absolute;left:8px;bottom:8px;z-index:1;padding:3px 8px;border-radius:999px;background:rgba(0,0,0,.55);color:#fff;
  font-size:12px;font-weight:700;max-width:calc(100% - 16px);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.mb-meet-bar{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-top:12px;}
.mb-meet-bar .mp-go{width:auto;min-height:48px;padding:0 10px;font-size:14px;}
.mb-meet-bar .mp-go[aria-pressed="true"]{background:var(--mb-soft);color:var(--accent);border-color:var(--mb-soft-line);}
.mb-end{margin-top:10px;}
.mb-end .mp-go{width:100%;}

/* messages */
.mb-unread{min-width:22px;height:22px;padding:0 7px;border-radius:999px;background:var(--mb-fill);color:var(--mb-on-fill);
  font-size:12px;font-weight:800;display:inline-grid;place-items:center;flex:none;}
.mb-chat-av{width:46px;height:46px;border-radius:50%;background:linear-gradient(140deg,var(--mb-surface-2),var(--mb-line));color:var(--text-primary);
  font-weight:800;font-size:14px;}
.mb-msg-held{font-size:11.5px;font-style:italic;opacity:.85;}
.mb-report{margin:0;}
.mb-report-btn{background:none;border:0;padding:4px 0 0;font:inherit;font-size:11.5px;color:var(--text-muted);cursor:pointer;text-decoration:underline;}
.mb-request{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:12px;}
.mb-request p{flex:1 1 100%;margin:0;}
.mb-request form{margin:0;}
.mb-request .mp-go{width:auto;}
.mb-chat-tools{margin-top:6px;}
.mb-guide-list{margin:10px 0 16px;padding-left:20px;display:flex;flex-direction:column;gap:8px;line-height:1.5;color:var(--text-secondary);}

/* the Bible */
.bb-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;}
.bb-head h1{margin-bottom:8px;}
.bb-tr{display:inline-flex;padding:3px;border-radius:999px;background:var(--mb-surface);border:1px solid var(--mb-line);flex:none;}
.bb-tr a{min-width:52px;min-height:34px;padding:0 12px;display:grid;place-items:center;border-radius:999px;font-size:13px;font-weight:800;
  letter-spacing:.04em;color:var(--text-secondary);text-decoration:none;}
.bb-tr a[aria-current]{background:var(--mb-fill);color:var(--mb-on-fill);}
.bb-go{display:flex;gap:8px;margin:10px 0 4px;}
.bb-go .mp-input{flex:1;min-width:0;border-radius:999px;padding:0 18px;}
.bb-go .mp-go{width:52px;flex:none;padding:0;border-radius:50%;display:grid;place-items:center;}
.bb-cont{margin-top:16px;}
.bb-cont .mb-list-text{flex:1;}
.bb-cont strong{font-family:var(--mb-display);font-stretch:84%;font-size:20px;font-weight:800;}
.bb-books{list-style:none;margin:0 0 6px;padding:0;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;}
.bb-books a{display:flex;align-items:center;min-height:48px;padding:0 14px;border-radius:14px;background:var(--mb-surface);
  border:1px solid var(--mb-line);color:var(--text-primary);text-decoration:none;font-size:15px;font-weight:600;}
.bb-chapters{list-style:none;margin:14px 0 0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(52px,1fr));gap:8px;}
.bb-chapters a{display:grid;place-items:center;aspect-ratio:1;border-radius:14px;background:var(--mb-surface);border:1px solid var(--mb-line);
  color:var(--text-primary);text-decoration:none;font-weight:800;font-variant-numeric:tabular-nums;}
.bb-text{font-family:var(--mb-serif);font-size:20px;line-height:1.7;letter-spacing:.005em;margin:6px 0 0;}
.bb-text p{margin:0 0 14px;}
.bb-text i{font-style:italic;opacity:.92;}
.bb-lines p{margin:0 0 8px;}
.bb-n{font-family:var(--font-body);font-size:11px;font-weight:800;color:var(--accent);margin-right:3px;vertical-align:super;line-height:0;
  scroll-margin-top:90px;}
.bb-hl{background:var(--mb-soft);color:inherit;border-radius:4px;box-shadow:0 0 0 3px var(--mb-soft);-webkit-box-decoration-break:clone;box-decoration-break:clone;}
.bb-steps{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:22px 0 0;}
.bb-step{display:flex;align-items:center;gap:8px;min-height:62px;padding:10px 14px;border-radius:18px;background:var(--mb-surface);
  border:1px solid var(--mb-line);color:var(--text-primary);text-decoration:none;}
.bb-step span{display:flex;flex-direction:column;font-size:12px;color:var(--text-muted);min-width:0;}
.bb-step strong{font-size:15px;color:var(--text-primary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.bb-next{justify-content:flex-end;text-align:right;}
.bb-src{margin:18px 0 0;font-size:12px;}
.bb-ref{color:var(--accent);font-weight:700;text-decoration:underline;text-decoration-thickness:1.5px;text-underline-offset:3px;}
.bb-pass{margin-top:16px;}
.bb-pass .bb-text{font-size:18px;}
.bb-pass-ref{margin:10px 0 2px;}

/* groups */
.mb-gcard{padding:0;overflow:hidden;}
.mb-gcard-cov{position:relative;display:block;aspect-ratio:16/8;overflow:hidden;}
.mb-gcard-cov .mb-art{position:absolute;inset:0;aspect-ratio:auto;border-radius:0;}
.mb-gcard-cov>h3,.mb-gcard-cov>h2{position:absolute;left:0;right:0;bottom:0;z-index:3;margin:0;padding:34px 16px 12px;color:#fff;
  font-family:var(--mb-display);font-stretch:66%;font-size:30px;font-weight:900;line-height:.92;text-transform:uppercase;
  background:linear-gradient(transparent,rgba(0,0,0,.72));}
.mb-gcard-cov>.mb-ph{position:absolute;inset:0;}
.mb-gcard-cov .mb-live-badge{position:absolute;right:12px;top:12px;z-index:4;}
.mb-gcard-b{padding:14px 16px 16px;}
.mb-gcard-b>:last-child{margin-bottom:0;}

/* Me */
.mb-profile{display:flex;align-items:center;gap:16px;margin:16px 0 4px;}
.mb-profile .mb-avatar{width:72px;height:72px;font-size:24px;box-shadow:0 0 0 3px var(--surface),0 0 0 5px var(--accent);}
.mb-profile h1{margin:0 0 4px;font-size:32px;font-stretch:72%;}
.mb-bars{display:flex;align-items:flex-end;gap:5px;height:58px;margin:18px 0 6px;}
.mb-bars i{flex:1;border-radius:5px 5px 2px 2px;background:var(--mb-soft-line);min-height:4px;}
.mb-bars i.mb-on{background:var(--accent);}
.mb-months{display:flex;justify-content:space-between;font-size:10px;color:var(--text-muted);}
.mb-months span{flex:1;text-align:center;}
.mb-give-row{display:grid;grid-template-columns:1fr auto;gap:8px;margin-top:16px;}
.mb-give-row .mp-go-2{width:auto;padding:0 14px;}
details.mb-each summary{cursor:pointer;min-height:44px;display:flex;align-items:center;font-size:13px;color:var(--text-secondary);
  list-style:none;margin-top:6px;}
details.mb-each summary::-webkit-details-marker{display:none;}

/* sign in */
.mb-si{position:relative;isolation:isolate;overflow:hidden;display:flex;flex-direction:column;justify-content:flex-end;min-height:440px;
  margin:0 -20px;padding:0 24px 8px;}
.mb-si>.mb-ph,.mb-si>.mb-gen{position:absolute;inset:0;z-index:-2;}
.mb-si>.mb-ph img{object-position:center 30%;}
.mb-si::after{content:"";position:absolute;inset:0;z-index:-1;background:linear-gradient(180deg,$ground55 0%,transparent 30%,var(--surface) 100%);}
.mb-si-logo{position:absolute;top:calc(56px + env(safe-area-inset-top,0px));left:50%;transform:translateX(-50%);max-width:70%;height:46px;width:auto;
  object-fit:contain;filter:drop-shadow(0 2px 14px rgba(0,0,0,.5));}
.mb-si-name{position:absolute;top:calc(58px + env(safe-area-inset-top,0px));left:24px;right:24px;text-align:center;font-family:var(--mb-display);
  font-size:15px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;}
.mb-si h1{font-size:clamp(50px,15vw,62px);font-stretch:66%;line-height:.88;margin:0;}

/* the floating tab bar */
.mb-nav{position:fixed;z-index:20;bottom:calc(12px + env(safe-area-inset-bottom,0px));left:max(12px,env(safe-area-inset-left,0px));
  right:max(12px,env(safe-area-inset-right,0px));max-width:520px;margin:0 auto;height:66px;padding:5px;border-radius:33px;
  display:grid;grid-template-columns:repeat(5,minmax(0,1fr));background:var(--mb-nav);-webkit-backdrop-filter:blur(22px) saturate(1.6);
  backdrop-filter:blur(22px) saturate(1.6);border:1px solid $text12;box-shadow:0 18px 40px rgba(0,0,0,.5),inset 0 1px 0 $text10;}
.mb-tab{border-radius:28px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;text-decoration:none;
  color:var(--text-muted);font-size:10.5px;font-weight:700;transition:background .2s ease,color .2s ease;}
.mb-tab[aria-current]{background:$accent20;color:var(--accent);}

.mp-go:focus-visible,.mp-input:focus-visible,.mp-link:focus-visible,.mp-person:focus-visible,.mp-years a:focus-visible,.mb-tab:focus-visible,
.mb-quick a:focus-visible,.mb-list a:focus-visible,.mb-wk:focus-visible,.mb-art:focus-visible,.mb-next a:focus-visible,.mb-back:focus-visible,
.mb-avatar:focus-visible,.mb-msg-title a:focus-visible,details.mb-each summary:focus-visible,.mb-mcard:focus-visible,.mb-pray:focus-visible,
.mb-reading-card:focus-visible,.mb-give:focus-visible,.mb-chat-link:focus-visible,.mb-verse-foot a:focus-visible,.bb-books a:focus-visible,
.bb-chapters a:focus-visible,.bb-tr a:focus-visible,.mb-live-now:focus-visible{outline:2px solid var(--focus);outline-offset:3px;}
table{width:100%;border-collapse:collapse;font-size:14px;}
th,td{text-align:left;padding:8px 6px;border-bottom:1px solid var(--mb-line);}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;}
@media (prefers-reduced-motion:no-preference){
  .mb-art,.mb-wk,.mb-quick a span,.mb-mcard,.mb-pray,.mb-reading-card{transition:transform .15s ease;}
  .mb-art:active,.mb-wk:active,.mb-quick a:active span,.mb-mcard:active,.mb-pray:active,.mb-reading-card:active{transform:scale(.98);}
  .mb-hero>.mb-ph img,.mb-hero>.mb-gen{animation:mbdrift 24s ease-in-out infinite alternate;}
  @keyframes mbdrift{from{transform:scale(1.02);}to{transform:scale(1.09) translateY(-8px);}}
}
@media (min-width:600px){.mb-hero,.mb-si,.mb-offair{border-radius:0 0 28px 28px;overflow:hidden;}}
@media print{.mp-noprint,.mb-nav,.mb-top{display:none!important;} html,body{background:#fff;color:#000;} body::before,body::after{display:none;}
  .mp-shell{max-width:none;padding:0;} .mp-card{background:#fff;border-color:#999;} th,td{border-color:#999;} .mp-muted{color:#333;}}""")


def css(biz: Dict[str, Any], theme: Dict[str, Any]) -> str:
    """The member app's stylesheet. The mp-* classes the older renderers
    use keep working through the same --tokens."""
    p = palette(biz, theme)
    return _CSS.substitute(
        ground=p["ground"], surface2=p["surface2"], text=p["text"], muted=p["muted"], dim=p["dim"], line=p["line"],
        accent=p["accent"], on_accent=p["on_accent"], error=p["error"], surface=p["surface"], fill=p["fill"],
        on_fill=p["on_fill"], soft=_rgba(p["accent"], .16), soft_line=_rgba(p["accent"], .34), nav_bg=_rgba(p["ground"], .74),
        ptint=p["ptint"], glow=p["glow"], glow55=_rgba(p["glow"], .55), glow85=_rgba(p["glow"], .85), glow42=_rgba(p["glow"], .42),
        accent20=_rgba(p["accent"], .20), accent24=_rgba(p["accent"], .24), accent28=_rgba(p["accent"], .28),
        accent50=_rgba(p["accent"], .50), grain=GRAIN, ground86=_rgba(p["ground"], .86), ground78=_rgba(p["ground"], .78),
        ground25=_rgba(p["ground"], .25), ground40=_rgba(p["ground"], .40), ground55=_rgba(p["ground"], .55),
        ground92=_rgba(p["ground"], .92), surface84=_rgba(p["surface"], .84), text08=_rgba(p["text"], .08),
        text10=_rgba(p["text"], .10), text11=_rgba(p["text"], .11), text12=_rgba(p["text"], .12), text14=_rgba(p["text"], .14),
        text20=_rgba(p["text"], .20), text24=_rgba(p["text"], .24), text25=_rgba(p["text"], .25),
        fill35=_rgba(p["fill"], .35), fill38=_rgba(p["fill"], .38))
