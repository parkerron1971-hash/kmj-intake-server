"""
member_app_ui.py — the member app's look.

The member page (/my, member_portal.py and its parts) is one small app on
a church's own address.

2026-10-15, "Member App, Top Tier" (Kevin: "it's a 7/10, I want 10/10 ...
the biggest thing is layout design"; he approved the design the same day,
"this is it. layout is better and it flows"). It mixes in what Love City's
members know from their Subsplash app, its five tabs and its stacked
picture tiles, on one strict grid:

- Five tabs: Home · Watch (messages and live) · Bible · Give · Connect
  (groups and chats). Me is the picture at the top right.
- One grid: 20-point edges, three corner sizes (14 / 18 / 24), one section
  header (a bold title, "See all" in the accent), iPhone large titles that
  hand over to the bar at the top as the page scrolls under it.
- A neutral base the church picks (Settings → Member page,
  settings.member_portal.base): black (the default, and the pick for Love
  City), dark gray, light gray or white. The church's own brand colour is
  the only colour in the app, and only on what you tap: buttons, the live
  dot, unread counts, links.
- Photos in black and white, so a dozen photos from different phones read
  as one set. Sermon art keeps its colour.

Type is Geist for everything and Newsreader italic for scripture and the
name in the greeting. Generated series posters stay for a church with no
photos and no art.

Pure functions, no I/O.
"""
from __future__ import annotations

import colorsys
import hashlib
from html import escape
from string import Template
from typing import Any, Dict, Optional, Tuple

from public_form_theme import color, contrast, readable

GOLD = "#F2C77E"

# The bases a church picks from. fg3 is the quietest text and still reads
# at 4.5:1 on its own base.
BASES: Dict[str, Dict[str, Any]] = {
    "black": {"bg": "#000000", "s1": "#161618", "s2": "#222225", "s3": "#2f2f33", "line": "#2c2c30",
              "fg": "#f5f5f7", "fg2": "#a8a8ae", "fg3": "#7a7a80", "dark": True},
    "charcoal": {"bg": "#171719", "s1": "#222225", "s2": "#2d2d31", "s3": "#3a3a3f", "line": "#38383d",
                 "fg": "#f3f3f5", "fg2": "#b0b0b6", "fg3": "#88888e", "dark": True},
    "gray": {"bg": "#efeff2", "s1": "#ffffff", "s2": "#e3e3e8", "s3": "#d4d4da", "line": "#d9d9de",
             "fg": "#111113", "fg2": "#55555c", "fg3": "#6b6b72", "dark": False},
    "white": {"bg": "#ffffff", "s1": "#f3f3f5", "s2": "#e8e8ec", "s3": "#d9d9de", "line": "#e2e2e6",
              "fg": "#0b0b0c", "fg2": "#55555c", "fg3": "#6b6b72", "dark": False},
}
BASE_LABELS = {"black": "Black", "charcoal": "Dark gray", "gray": "Light gray", "white": "White"}
# Kids (member_spaces_kids): cream, warm ink, an orange accent; sunshine,
# sky, coral, grass and grape in its pieces. Not a base a church picks.
KIDS_BASE: Dict[str, Any] = {"bg": "#fff8ec", "s1": "#ffffff", "s2": "#fbefd9", "s3": "#f0dfbd", "line": "#f1e3c7",
                             "fg": "#2b1d0e", "fg2": "#65533f", "fg3": "#7a6650", "dark": False}
KIDS_ACCENT = "#f28c28"
DEFAULT_BASE = "black"

TABS = (
    ("home", "/my", "Home", '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>'),
    ("watch", "/my/sermons", "Watch",
     '<rect x="2.5" y="4" width="19" height="13" rx="3"/><path d="m10.5 8.3 4 2.2-4 2.2z"/><path d="M8 21h8"/>'),
    ("bible", "/my/bible", "Bible",
     '<path d="M2 4h6a4 4 0 0 1 4 4v13a3 3 0 0 0-3-3H2z"/><path d="M22 4h-6a4 4 0 0 0-4 4v13a3 3 0 0 1 3-3h7z"/>'),
    ("give", "/my/give", "Give",
     '<path d="M11 14h2a2 2 0 1 0 0-4h-3c-.6 0-1.1.2-1.4.6L3 16"/><path d="m7 20 1.6-1.4c.3-.4.8-.6 1.4-.6h4c1.1 0 '
     '2.1-.4 2.8-1.2l4.6-4.4a2 2 0 0 0-2.75-2.91l-4.2 3.9"/><path d="m2 15 6 6"/><path d="M19.5 8.5c.7-.7 1.5-1.6 '
     '1.5-2.7A2.73 2.73 0 0 0 16 4a2.78 2.78 0 0 0-5 1.8c0 1.2.8 2 1.5 2.8L16 12Z"/>'),
    ("connect", "/my/groups", "Connect",
     '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
     '<path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>'),
)
# Youth's bar (member_spaces): its chats and its crew where Church has Give
# and Connect.
YOUTH_TABS = (
    TABS[0], TABS[1], TABS[2],
    ("chats", "/my/messages", "Chats", '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-4.9A8 8 0 1 1 21 12z"/>'),
    ("crew", "/my/groups", "Crew", TABS[4][3]),
)
YOUTH_TAB_OF = {"home": "home", "watch": "watch", "sermons": "watch", "live": "watch", "bible": "bible",
                "messages": "chats", "chats": "chats", "groups": "crew", "connect": "crew", "crew": "crew"}
# Kids' bar (member_spaces_kids): its stories, its Sundays and the family.
# A leader who isn't a parent gets the first three, Home called Room.
KIDS_TABS = (
    ("home", "/my", "Kids", '<path d="m12 2.5 2.9 5.9 6.6 1-4.8 4.6 1.1 6.5L12 17.4l-5.9 3.1 1.1-6.5-4.8-4.6 6.6-1z"/>'),
    TABS[1],
    ("stories", "/my/kids/stories", "Stories", TABS[2][3]),
    ("sundays", "/my/kids/sundays", "Sundays", '<rect x="3" y="4" width="18" height="18" rx="3"/><path d="M16 2v4M8 2v4M3 10h18"/>'),
    ("family", "/my/kids/family", "Family", TABS[4][3]),
)
KIDS_TAB_OF = {"home": "home", "watch": "watch", "sermons": "watch", "live": "watch", "stories": "stories",
               "sundays": "sundays", "family": "family"}
# Which tab a page belongs under.
TAB_OF = {"home": "home", "watch": "watch", "sermons": "watch", "live": "watch", "bible": "bible",
          "give": "give", "connect": "connect", "groups": "connect", "messages": "connect", "lead": "lead"}
# A member who holds a church role (church_follow_up) gets a sixth tab:
# the people Chief hands them (member_portal_lead).
LEAD_TAB = ("lead", "/my/lead", "Lead", '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>')

ICONS = {
    "heart": '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7z"/>',
    "lock": '<rect x="4" y="11" width="16" height="10" rx="2.5"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    "calendar": '<rect x="3" y="4" width="18" height="18" rx="3"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    "play": '<path d="M7 4.5v15a1 1 0 0 0 1.5.86l12.4-7.5a1 1 0 0 0 0-1.72L8.5 3.64A1 1 0 0 0 7 4.5z" fill="currentColor" stroke="none"/>',
    "chevron": '<path d="m9 18 6-6-6-6"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
             '<path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    "back": '<path d="m15 18-6-6 6-6"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "share": '<path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><path d="m16 6-4-4-4 4M12 2v13"/>',
    "chat": '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-4.9A8 8 0 1 1 21 12z"/>',
    "doc": '<path d="M4 2v20l3-2 3 2 2-2 2 2 3-2 3 2V2l-3 2-3-2-2 2-2-2-3 2z"/><path d="M8 9h8M8 13h6"/>',
    "bell": '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    "pray": '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/><path d="M15.8 9.2a2.5 2.5 0 0 0-3.5 0l-.3.4-.35-.3a2.42 2.42 0 1 0-3.2 3.6l3.6 3.5 3.6-3.5c1.2-1.2 1.1-2.7.2-3.7"/>',
    "book": '<path d="M2 4h6a4 4 0 0 1 4 4v13a3 3 0 0 0-3-3H2z"/><path d="M22 4h-6a4 4 0 0 0-4 4v13a3 3 0 0 1 3-3h7z"/>',
    "live": '<circle cx="12" cy="12" r="2"/><path d="M16.24 7.76a6 6 0 0 1 0 8.49M7.76 16.24a6 6 0 0 1 0-8.49'
            'M19.07 4.93a10 10 0 0 1 0 14.14M4.93 19.07a10 10 0 0 1 0-14.14"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "send": '<path d="M12 19V5M5 12l7-7 7 7"/>',
    "video": '<path d="m22 8-6 4 6 4z"/><rect x="2" y="6" width="14" height="12" rx="2"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "mail": '<rect x="2" y="4" width="20" height="16" rx="3"/><path d="m22 7-10 6L2 7"/>',
    "phone": '<rect x="6" y="2" width="12" height="20" rx="3"/><path d="M11 18h2"/>',
    "at": '<circle cx="12" cy="12" r="4"/><path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-4 8"/>',
    "arrow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
    "refresh": '<path d="M21 12a9 9 0 1 1-2.64-6.36L21 8"/><path d="M21 3v5h-5"/>',
    "give": TABS[3][3],
    "headphones": '<path d="M3 14h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a9 9 0 0 1 18 0v7a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3"/>',
    "out": '<path d="M7 17 17 7M8 7h9v9"/>',
    "home": '<path d="M3 21h18M5 21V8l7-5 7 5v13"/><path d="M10 21v-6h4v6"/>',
    "down": '<path d="m6 9 6 6 6-6"/>',
    "star": '<path d="m12 2.5 2.9 5.9 6.6 1-4.8 4.6 1.1 6.5L12 17.4l-5.9 3.1 1.1-6.5-4.8-4.6 6.6-1z"/>',
    "camera": '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3z"/><circle cx="12" cy="13" r="3.5"/>',
}


def icon(name: str, size: int = 20) -> str:
    return (f'<svg class="mb-ic" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" '
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


def base_of(biz: Dict[str, Any]) -> str:
    """The church's base (settings.member_portal.base), black by default."""
    cfg = ((biz or {}).get("settings") or {}).get("member_portal") or {}
    b = cfg.get("base") if isinstance(cfg, dict) else None
    return b if b in BASES else DEFAULT_BASE


def brand_colour(biz: Dict[str, Any], theme: Dict[str, Any]) -> Optional[str]:
    """The church's own colour: its accent, then its brand primary or
    secondary — the first one with real colour in it."""
    kit = ((biz or {}).get("settings") or {}).get("brand_kit") or {}
    kit = kit if isinstance(kit, dict) else {}
    cols = kit.get("colors") if isinstance(kit.get("colors"), dict) else {}
    for c in (theme.get("accent"), kit.get("accent"), cols.get("accent"), cols.get("primary"),
              kit.get("primary_color"), cols.get("secondary")):
        c = color(c)
        if c and _hls(c)[2] >= 0.18 and 0.08 <= _hls(c)[1] <= 0.92:
            return c
    return None


def _readable_on(c: str, bg: str, dark: bool, need: float = 4.5) -> str:
    """`c` moved lighter (on a dark base) or darker (on a light one), in
    its own hue, until it reads on `bg`."""
    h, l, s = _hls(c)
    out = c
    for _ in range(30):
        if contrast(out, bg) >= need:
            return out
        l = min(0.92, l + 0.025) if dark else max(0.08, l - 0.025)
        out = _hex(h, l, max(s, 0.45) if s > 0.08 else s)
    return out


def palette(biz: Dict[str, Any], theme: Dict[str, Any], space: str = "church") -> Dict[str, Any]:
    """The page's colours: the church's base, and its colour as the accent.
    `accent` is for words and icons (4.5:1 on the base); `fill` is the
    button colour, with `on_fill` the words on it (white when they read,
    else near-black, as on gold). Youth (member_spaces) sits on black with
    its own colour, volt green unless the church picked one."""
    if space == "youth":
        import member_spaces
        name, brand = "black", member_spaces.youth_colour(biz)
        b = BASES[name]
    elif space == "kids":
        name, brand, b = "kids", KIDS_ACCENT, KIDS_BASE
    else:
        name, brand = base_of(biz), None
        b = BASES[name]
    bg, dark = b["bg"], b["dark"]
    brand = brand or brand_colour(biz, theme) or ("#e8e8ec" if dark else "#1c1c1e")
    fill = brand
    if dark and contrast(fill, bg) < 2.2:
        fill = _readable_on(fill, bg, True, 2.2)
    elif not dark and contrast(fill, bg) < 1.35:
        fill = _readable_on(fill, bg, False, 1.35)
    on_fill = "#FFFFFF" if contrast("#FFFFFF", fill) >= 4.5 else "#0B0B0C"
    accent = _readable_on(brand, bg, dark)
    h = _hls(brand)[0]
    return {
        "base": name, "dark": dark, "bg": bg, "s1": b["s1"], "s2": b["s2"], "s3": b["s3"], "line": b["line"],
        "fg": b["fg"], "fg2": b["fg2"], "fg3": b["fg3"],
        # the older names, which other parts still read
        "ground": bg, "surface": b["s1"], "surface2": b["s2"], "text": b["fg"], "muted": b["fg2"], "dim": b["fg3"],
        "tint": brand, "glow": _hex(h, 0.42, 0.5), "ptint": _hex(h, 0.42, 0.3),
        "accent": accent, "on_accent": readable(accent), "fill": fill, "on_fill": on_fill,
        "error": "#FF6B5E" if dark else "#C5221F", "on_white": _readable_on(brand, "#FFFFFF", False),
    }


def accent_for(biz: Dict[str, Any], theme: Dict[str, Any]) -> str:
    return palette(biz, theme)["accent"]


def poster_colours(key: Any, pal: Dict[str, str]) -> Tuple[str, str]:
    """A stable (light, deep) gradient pair per series/group: the church
    colour's hue and its neighbours."""
    th = _hls(pal["tint"])[0]
    hues = (th, th + 0.06, th - 0.06, th + 0.12, th - 0.12)
    n = int(hashlib.sha256(str(key or "").encode()).hexdigest()[:8], 16)
    hue = hues[n % len(hues)]
    return _hex(hue, 0.46, 0.55), _hex(hue, 0.14, 0.5)


def poster_style(key: Any, pal: Dict[str, str]) -> str:
    light, deep = poster_colours(key, pal)
    return (f"background:radial-gradient(90% 90% at 85% 0%,{light} 0%,transparent 70%),"
            f"linear-gradient(160deg,{light} 0%,{deep} 100%);color:#fff")


def poster(key: Any, pal: Dict[str, str], title: str, kick: str = "", *, tag: str = "span",
           cls: str = "", play: bool = False, title_id: str = "", title_tag: str = "span",
           attrs: str = "") -> str:
    """Generated series art for a church with no photos: the church colour
    in a gradient and the title in heavy type. Text is escaped here;
    `attrs` is trusted markup from the caller (an href, aria)."""
    t = escape(str(title or ""))
    tid = f' id="{escape(title_id)}"' if title_id else ""
    play_html = f'<span class="mb-art-play" aria-hidden="true">{icon("play", 18)}</span>' if play else ""
    kick_html = f'<span class="mb-art-kick">{escape(kick)}</span>' if kick else ""
    return (f'<{tag} class="mb-art {cls}" style="{poster_style(key, pal)}"{(" " + attrs) if attrs else ""}>'
            f'{play_html}{kick_html}<{title_tag} class="mb-art-title"{tid}>{t}</{title_tag}></{tag}>')


def photo(url: str, cls: str = "", *, eager: bool = False) -> str:
    """One of the church's photos, in black and white (CSS). Decorative:
    the card around it carries the words."""
    load = 'fetchpriority="high"' if eager else 'loading="lazy"'
    return (f'<span class="mb-ph {cls}" aria-hidden="true"><img src="{escape(url, quote=True)}" alt="" '
            f'{load} decoding="async"></span>')


def art(url: str, cls: str = "") -> str:
    """Sermon art: it keeps its colour."""
    return (f'<span class="mb-ph mb-keep {cls}" aria-hidden="true"><img src="{escape(url, quote=True)}" alt="" '
            f'loading="lazy" decoding="async"></span>')


def titled_photo(url: str, title: str, cls: str = "") -> str:
    """A series with no art of its own: one of the church's photos with
    the series name set on it."""
    return (f'<span class="mb-ph mb-titled {cls}" aria-hidden="true"><img src="{escape(url, quote=True)}" alt="" '
            f'loading="lazy" decoding="async"><b>{escape(str(title or ""))}</b></span>')


def gen_art(name: Any, cls: str = "") -> str:
    """Art for a church with no photos yet: its colour, softly lit."""
    return (f'<span class="mb-gen {cls}" aria-hidden="true"><span class="mb-gen-ghost">'
            f'{escape(initials(name))}</span></span>')


def cover(url: str, key: Any, pal: Dict[str, str], title: str, kick: str = "") -> str:
    """A card's picture: the church's photo when it has one, else a poster."""
    if url:
        return photo(url, "mb-cover")
    return poster(key, pal, title, kick, cls="mb-cover")


def sample_tag() -> str:
    """'Sample' on something only the owner's preview shows."""
    return '<span class="mb-sample">Sample</span>'


def sample_hint(text: str) -> str:
    """Where the owner adds the real thing (member_app_samples.WHERE)."""
    return f'<p class="mb-hint">{icon("plus", 14)}<span>{escape(text)}</span></p>'


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
            f'<circle cx="{size / 2}" cy="{size / 2}" r="{r}" fill="none" stroke="var(--s3)" stroke-width="6"/>'
            f'<circle cx="{size / 2}" cy="{size / 2}" r="{r}" fill="none" stroke="var(--mb-fill)" stroke-width="6" '
            f'stroke-linecap="round" stroke-dasharray="{c * done:.1f} {c:.1f}"/></svg><b>{int(n)}</b></span>')


def section(title: str, link: str = "", link_label: str = "", hid: str = "") -> str:
    """The one section header: a bold title, and "See all" in the accent."""
    ida = f' id="{escape(hid)}"' if hid else ""
    more = f'<a href="{escape(link, quote=True)}">{escape(link_label)}</a>' if link else ""
    return f'<div class="mb-sh"><h2{ida}>{escape(title)}</h2>{more}</div>'


def segmented(items: Tuple[Tuple[str, str, str], ...], current: str, label: str) -> str:
    """Two or three linked pages under one title (Connect: Groups,
    Messages). items = (key, href, label-markup)."""
    out = []
    for key, href, text in items:
        cur = ' aria-current="page"' if key == current else ""
        out.append(f'<a href="{escape(href, quote=True)}"{cur}>{text}</a>')
    return f'<nav class="mb-seg" aria-label="{escape(label)}">{"".join(out)}</nav>'


def nav(active: Optional[str], *, give: bool = True, space: str = "church", kids_parent: bool = True,
        lead: bool = False) -> str:
    """The tab bar. Give is always there (Kevin, 2026-10-15): before the
    church takes gifts in the app, it says how to give
    (member_portal.render_give_off). Youth and Kids have their own bars;
    a Kids leader who isn't a parent gets Room, Watch and Stories. A
    church leader (lead=True) gets Lead last. On a wide screen the bar is
    a rail down the left (Kevin, 2026-10-17: a desktop view too)."""
    if space == "youth":
        tabs, of = YOUTH_TABS, YOUTH_TAB_OF
    elif space == "kids":
        tabs, of = KIDS_TABS, KIDS_TAB_OF
        if not kids_parent:
            tabs = ((tabs[0][0], tabs[0][1], "Room", tabs[0][3]),) + tabs[1:3]
    else:
        tabs, of = (TABS + (LEAD_TAB,) if lead else TABS), TAB_OF
    cur_tab = of.get(active or "", "")
    items = []
    for key, href, label, paths in tabs:
        if key == "give" and not give:
            continue
        cur = ' aria-current="page"' if key == cur_tab else ""
        items.append(f'<a class="mb-tab" href="{href}"{cur}><svg width="25" height="25" viewBox="0 0 24 24" fill="none" '
                     f'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" '
                     f'aria-hidden="true" focusable="false">{paths}</svg><span>{label}</span></a>')
    return (f'<nav class="mb-nav mp-noprint" aria-label="Main" style="grid-template-columns:repeat({len(items)},1fr)">'
            f'{"".join(items)}</nav>')


# Geist for everything; Newsreader for scripture and the greeting's name.
FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@400..800'
         '&amp;family=Newsreader:ital,opsz,wght@0,6..72,400..600;1,6..72,400..600'
         '&amp;family=Fredoka:wght@500..700&amp;display=swap">')

# The bar at the top turns solid once the page scrolls under it, and the
# page's title moves into it when the large title has scrolled away.
SCROLL_JS = ("<script>(function(){var t=document.querySelector('.mb-top');if(!t)return;"
             "var h=document.querySelector('.mb-lt h1,.mb-hello');"
             "function f(){var y=window.scrollY;t.classList.toggle('is-solid',y>8);"
             "t.classList.toggle('is-titled',!!h&&h.getBoundingClientRect().bottom<70);}"
             "f();window.addEventListener('scroll',f,{passive:true});})();</script>")


class _Tokens(dict):
    """The palette for the stylesheet: $fg is the colour itself, $fg_08 is
    it at 8% opacity."""

    def __missing__(self, key: str) -> str:
        name, _, pct = key.rpartition("_")
        return _rgba(self[name], int(pct) / 100)


_CSS = Template(""":root{--bg:$bg;--s1:$s1;--s2:$s2;--s3:$s3;--line:$line;--fg:$fg;--fg2:$fg2;--fg3:$fg3;
--acc:$accent;--acc-fill:$fill;--on-acc:$on_fill;--acc-soft:$fill_18;--acc-on-white:$on_white;--bar:$bg_82;--hair:$fg_10;
--surface:$bg;--input-surface:$s1;--text-primary:$fg;--text-secondary:$fg2;--text-muted:$fg3;--border:$line;--accent:$accent;
--accent-text:$on_fill;--focus:$accent;--error:$error;--mb-surface:$s1;--mb-surface-2:$s2;--mb-line:$line;--mb-fill:$fill;
--mb-on-fill:$on_fill;--mb-soft:$fill_18;--mb-soft-line:$fill_40;
--mb-ui:"Geist",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,system-ui,sans-serif;--mb-display:var(--mb-ui);--font-body:var(--mb-ui);
--mb-serif:"Newsreader",Georgia,"Times New Roman",serif;--g:20px;--r-lg:24px;--r-md:18px;--r-sm:14px;color-scheme:$scheme;}
[hidden]{display:none!important}
html,body{margin:0;padding:0;background:var(--bg);color:var(--fg);min-height:100vh;}
body{font-family:var(--mb-ui);font-size:15px;line-height:1.45;letter-spacing:-.006em;-webkit-font-smoothing:antialiased;overflow-x:hidden;
  -webkit-tap-highlight-color:transparent;}
*{box-sizing:border-box;}
a{color:var(--acc);}
h1{font-size:34px;font-weight:720;letter-spacing:-.035em;line-height:1.06;margin:6px 0 10px;text-wrap:balance;}
h2{font-size:21px;font-weight:700;letter-spacing:-.025em;line-height:1.2;margin:0 0 8px;}
h3{font-size:17px;font-weight:650;letter-spacing:-.02em;margin:0 0 4px;}
p{line-height:1.5;margin:0 0 12px;}
.mb-ic{flex:none;}

/* the bar at the top: clear over the page, solid once the page slides under it */
.mb-top{position:sticky;top:0;z-index:15;display:flex;align-items:center;justify-content:space-between;gap:10px;max-width:600px;margin:0 auto;
  min-height:56px;padding:calc(8px + env(safe-area-inset-top,0px)) max(16px,env(safe-area-inset-right,0px)) 8px max(20px,env(safe-area-inset-left,0px));
  transition:background .25s ease,box-shadow .25s ease;}
.mb-top.is-solid{background:var(--bar);-webkit-backdrop-filter:blur(22px) saturate(1.7);backdrop-filter:blur(22px) saturate(1.7);box-shadow:0 .5px 0 var(--hair);}
.mb-top-l{display:flex;align-items:center;min-width:0;flex:1;}
.mb-top-t{position:absolute;left:96px;right:96px;bottom:16px;text-align:center;font-size:16px;font-weight:650;letter-spacing:-.015em;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;opacity:0;transition:opacity .2s ease;pointer-events:none;}
.mb-top.is-titled .mb-top-t{opacity:1;}
.mb-brand{display:flex;align-items:center;gap:10px;min-width:0;text-decoration:none;color:var(--fg);height:40px;}
.mb-mark{width:34px;height:34px;flex:none;border-radius:10px;display:grid;place-items:center;font-weight:750;font-size:13px;
  background:var(--fg);color:var(--bg);overflow:hidden;}
.mb-mark img{width:100%;height:100%;object-fit:contain;background:#fff;}
.mb-wordmark{display:block;height:30px;width:auto;max-width:150px;object-fit:contain;}
.mp-church{font-size:15px;font-weight:700;letter-spacing:-.02em;margin:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.mb-top-right{display:flex;align-items:center;gap:8px;flex:none;}
.mb-chat-link{position:relative;width:40px;height:40px;flex:none;border-radius:50%;display:grid;place-items:center;color:var(--fg);
  background:var(--s1);text-decoration:none;}
.mb-chat-link .mb-unread{position:absolute;top:-3px;right:-4px;box-shadow:0 0 0 2.5px var(--bg);}
.mb-avatar{width:40px;height:40px;flex:none;border-radius:50%;display:grid;place-items:center;font-weight:650;font-size:14px;
  text-decoration:none;color:var(--fg);background:var(--s2);letter-spacing:-.01em;}
.mb-avatar[aria-current]{box-shadow:0 0 0 2px var(--bg),0 0 0 4px var(--acc);}
.mb-avatar img,.mb-chat-av img,.mb-msg-av img{width:100%;height:100%;object-fit:cover;border-radius:50%;display:block;}
.mb-avatar.has-photo,.mb-msg-av.has-photo{background:var(--s2);overflow:hidden;}
.mb-back{display:inline-flex;align-items:center;gap:2px;min-height:44px;margin-left:-8px;padding-right:8px;color:var(--acc);text-decoration:none;
  font-size:17px;letter-spacing:-.015em;}
.mb-back .mb-ic{width:24px;height:24px;}
.mb-preview{position:relative;z-index:16;display:flex;align-items:center;gap:10px;
  padding:calc(10px + env(safe-area-inset-top,0px)) max(18px,env(safe-area-inset-right,0px)) 10px max(18px,env(safe-area-inset-left,0px));
  background:var(--acc-fill);color:var(--on-acc);font-size:13px;line-height:1.35;}
.mb-preview + .mb-top{padding-top:8px;}
.mb-preview span{flex:1;min-width:0;max-width:560px;margin:0 auto;}
.mb-preview form{margin:0;flex:none;}
.mb-preview button{min-height:36px;padding:0 12px;border-radius:999px;border:1.5px solid currentColor;background:transparent;color:inherit;
  font:inherit;font-weight:700;cursor:pointer;}

.mp-shell{position:relative;z-index:1;max-width:600px;margin:0 auto;padding:4px var(--g) 40px;}
.mp-shell.mb-has-nav{padding-bottom:calc(118px + env(safe-area-inset-bottom,0px));}
.mb-bare{padding-top:0;}

/* photos: black and white, so the church's colour is the only colour */
.mb-ph{position:relative;display:block;overflow:hidden;background:var(--s2);}
.mb-ph img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;filter:grayscale(1) contrast(1.06);}
.mb-ph.mb-keep img{filter:none;}
.mb-titled b{position:absolute;inset:auto 0 0 0;padding:28px 14px 12px;color:#fff;font-size:22px;font-weight:760;letter-spacing:-.04em;line-height:1.02;
  background:linear-gradient(transparent,rgba(0,0,0,.66));}
.mb-gen{position:relative;display:block;overflow:hidden;background:radial-gradient(90% 70% at 80% 10%,$fill_55 0%,transparent 65%),
  radial-gradient(70% 60% at 10% 90%,$fill_30 0%,transparent 60%),var(--s2);}
.mb-gen-ghost{position:absolute;right:-10px;bottom:-34px;font-size:180px;font-weight:800;letter-spacing:-.06em;line-height:1;color:#fff;opacity:.12;}
.mb-cover{position:absolute;inset:0;}

/* section header, large titles */
.mb-sh{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin:36px 0 14px;}
.mb-sh h2{margin:0;}
.mb-sh a{font-size:15px;font-weight:500;text-decoration:none;color:var(--acc);flex:none;}
.mp-sect{font-size:21px;font-weight:700;letter-spacing:-.025em;color:var(--fg);margin:36px 0 14px;display:flex;justify-content:space-between;
  align-items:baseline;gap:10px;text-transform:none;}
.mp-sect a{font-size:15px;font-weight:500;letter-spacing:-.01em;text-decoration:none;color:var(--acc);}
.mb-lt{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;margin:4px 0 6px;}
.mb-lt h1{margin:0;}
.mb-lt-r{display:flex;align-items:center;gap:8px;flex:none;padding-bottom:4px;}
.mb-sub{color:var(--fg2);font-size:15px;margin:2px 0 0;}
.mb-kick,.mb-eyebrow{display:block;font-size:12.5px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;color:var(--fg3);}

/* buttons, fields */
.mp-go{display:inline-flex;align-items:center;justify-content:center;gap:8px;width:100%;min-height:52px;padding:0 20px;border:0;border-radius:16px;
  background:var(--acc-fill);color:var(--on-acc);font:inherit;font-size:16px;font-weight:600;letter-spacing:-.01em;cursor:pointer;
  text-decoration:none;text-align:center;}
.mp-go:active{transform:scale(.985);}
.mp-go-2{background:var(--s1);color:var(--fg);}
.mb-soft{background:var(--acc-soft);color:var(--acc);}
.mb-line{background:transparent;color:var(--acc);box-shadow:inset 0 0 0 1.5px var(--acc);}
.mb-pill{width:auto;min-height:44px;padding:0 18px;border-radius:999px;font-size:15px;}
.mp-link{background:none;border:0;padding:10px 0;min-height:44px;font:inherit;font-size:15px;color:var(--acc);cursor:pointer;text-decoration:none;}
label{font-size:14px;font-weight:600;color:var(--fg2);}
.mp-form{display:flex;flex-direction:column;gap:10px;}
.mp-input{width:100%;min-height:52px;padding:12px 16px;font:inherit;font-size:16px;color:var(--fg);background:var(--s1);border:1px solid transparent;
  border-radius:14px;}
.mp-input:focus{outline:none;border-color:var(--acc);box-shadow:0 0 0 4px $fill_22;}
.mp-input option{background:var(--s1);color:var(--fg);}
.mp-text{min-height:150px;resize:vertical;line-height:1.5;}
.mp-code{letter-spacing:.5em;text-align:center;font-size:28px;font-weight:700;font-variant-numeric:tabular-nums;min-height:64px;padding-left:.5em;}
.mp-check{display:flex;gap:10px;align-items:flex-start;font-weight:500;color:var(--fg);font-size:15px;}
.mp-check input{width:20px;height:20px;margin:2px 0 0;accent-color:var(--acc-fill);}
.mp-sr{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0;}
.mp-muted{color:var(--fg2);font-size:15px;}
.mp-err{color:var(--error);font-size:14px;font-weight:600;}
.mp-flash{padding:13px 16px;border-radius:14px;background:var(--s1);margin:16px 0;font-size:15px;}
.mp-ok{color:var(--fg);font-weight:550;}
.mp-card{background:var(--s1);border-radius:var(--r-md);padding:18px;margin-bottom:12px;}
.mp-card>:last-child{margin-bottom:0;}
.mp-card h1,.mp-card h2{margin-top:0;}
.mp-foot{text-align:center;font-size:12px;color:var(--fg3);margin-top:44px;padding-top:0;border:0;}
.mb-chip{display:inline-flex;align-items:center;gap:6px;height:26px;padding:0 10px;border-radius:999px;font-size:12.5px;font-weight:650;
  background:var(--acc-soft);color:var(--acc);white-space:nowrap;align-self:flex-start;}
.mb-unread{min-width:21px;height:21px;padding:0 6px;border-radius:11px;background:var(--acc-fill);color:var(--on-acc);font-size:12px;
  font-weight:700;display:inline-grid;place-items:center;flex:none;}

/* Home: the greeting */
.mb-hello-wrap{margin:2px 0 14px;}
.mb-date{font-size:12.5px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;color:var(--fg3);margin:0;min-height:1em;}
.mb-hello{font-size:34px;font-weight:720;letter-spacing:-.035em;line-height:1.06;margin:2px 0 0;}
.mb-hello em,.mb-lt em{font-family:var(--mb-serif);font-style:italic;font-weight:500;letter-spacing:-.02em;}

/* Home: the next gathering, on the church's photo */
.mb-hero{position:relative;isolation:isolate;display:block;border-radius:var(--r-lg);overflow:hidden;aspect-ratio:350/392;color:#fff;
  text-decoration:none;background:var(--s2);}
.mb-hero>.mb-ph,.mb-hero>.mb-gen{position:absolute;inset:0;z-index:-2;}
.mb-hero>.mb-ph img{object-position:center 35%;}
.mb-hero::after{content:"";position:absolute;inset:0;z-index:-1;background:linear-gradient(180deg,rgba(0,0,0,0) 28%,rgba(0,0,0,.28) 50%,rgba(0,0,0,.88) 100%);}
.mb-hero-in{position:absolute;left:0;right:0;bottom:0;padding:20px;}
.mb-when{display:inline-flex;align-items:center;gap:7px;height:28px;padding:0 11px;border-radius:999px;background:rgba(255,255,255,.18);
  -webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px);font-size:12.5px;font-weight:600;letter-spacing:.01em;}
.mb-when.is-live{background:#ff3b30;}
.mb-hero h2,.mb-hero h3{color:#fff;font-size:30px;font-weight:720;letter-spacing:-.035em;line-height:1.04;margin:12px 0 6px;}
.mb-hero p{margin:0;font-size:14.5px;color:rgba(255,255,255,.8);}
.mb-hero-row{display:flex;align-items:center;flex-wrap:wrap;gap:10px 12px;margin-top:16px;}
.mb-hero-row form{margin:0;}
.mb-hero .mp-go{width:auto;min-height:46px;padding:0 20px;border-radius:999px;font-size:15.5px;}
.mb-hero .mp-go-2{background:rgba(255,255,255,.18);color:#fff;-webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px);}
.mb-hero .mb-chip{background:rgba(255,255,255,.18);color:#fff;-webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px);height:30px;}
.mb-going{display:flex;align-items:center;gap:7px;font-size:13.5px;color:rgba(255,255,255,.86);}
.mb-going .mb-ic{opacity:.9;}
.mb-hero .mb-hint{margin:12px 0 0;background:rgba(0,0,0,.45);color:#fff;border-color:rgba(255,255,255,.4);}

/* quick ways in */
.mb-quick{display:grid;grid-auto-flow:column;grid-auto-columns:minmax(0,1fr);gap:10px;margin:12px 0 0;}
.mb-quick a{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:7px;height:82px;border-radius:var(--r-md);
  background:var(--s1);text-decoration:none;font-size:12.5px;font-weight:550;color:var(--fg2);}
.mb-quick a .mb-ic{color:var(--fg);width:24px;height:24px;}

/* a message, Subsplash-style: its art, the title below */
.mb-mtile{display:block;text-decoration:none;color:var(--fg);}
.mb-mtile-art{position:relative;display:block;aspect-ratio:16/9;border-radius:var(--r-md);overflow:hidden;background:var(--s2);}
.mb-mtile-art>.mb-ph,.mb-mtile-art>.mb-art{position:absolute;inset:0;}
.mb-play{position:absolute;left:14px;bottom:14px;width:46px;height:46px;border-radius:50%;display:grid;place-items:center;background:#fff;color:#000;
  box-shadow:0 8px 24px rgba(0,0,0,.35);z-index:2;}
.mb-play .mb-ic{width:18px;height:18px;margin-left:2px;}
.mb-mtile-b{display:flex;flex-direction:column;gap:3px;padding:12px 2px 0;}
.mb-mtile-b strong{font-size:17px;font-weight:650;letter-spacing:-.02em;}
.mb-mtile-b span,.mb-meta{font-size:13.5px;color:var(--fg2);margin:0;}
.mb-mtile .mb-sample{position:absolute;left:12px;top:12px;z-index:3;}

/* the verse */
.mb-verse{position:relative;margin:36px 0 0;padding:22px 22px 18px;border-radius:var(--r-lg);background:var(--s1);}
.mb-verse .mb-kick{color:var(--acc);}
.mb-verse blockquote{margin:12px 0 18px;font-family:var(--mb-serif);font-style:italic;font-weight:500;font-size:23px;line-height:1.26;
  letter-spacing:-.01em;text-wrap:pretty;}
.mb-verse blockquote i{font-style:normal;}
.mb-verse-foot{display:flex;justify-content:space-between;align-items:center;gap:10px;font-size:13.5px;color:var(--fg2);}
.mb-verse-foot a{font-weight:550;text-decoration:none;display:inline-flex;align-items:center;gap:2px;}

/* the church's own tiles (what its Subsplash Home held), on one grid */
.mb-bento{display:grid;grid-template-columns:1fr 1fr;gap:10px;}
.mb-bt{position:relative;isolation:isolate;display:block;border-radius:var(--r-md);overflow:hidden;color:#fff;text-decoration:none;background:var(--s2);}
.mb-bt>.mb-ph,.mb-bt>.mb-gen{position:absolute;inset:0;z-index:-2;}
.mb-bt::after{content:"";position:absolute;inset:0;z-index:-1;background:linear-gradient(180deg,rgba(0,0,0,0) 38%,rgba(0,0,0,.74));}
.mb-bt.is-wide{grid-column:1/-1;aspect-ratio:16/9;}
.mb-bt.is-sq{aspect-ratio:1/1.05;}
.mb-bt.is-band{grid-column:1/-1;aspect-ratio:16/5.6;}
.mb-bt-t{position:absolute;left:16px;right:16px;bottom:14px;display:flex;flex-direction:column;gap:2px;}
.mb-bt-t strong{font-size:19px;font-weight:700;letter-spacing:-.025em;line-height:1.12;display:flex;align-items:center;gap:6px;}
.mb-bt-t span{font-size:12.5px;color:rgba(255,255,255,.78);}

/* rails */
.mb-rail{display:flex;gap:12px;overflow-x:auto;scroll-snap-type:x mandatory;scroll-padding-inline:var(--g);margin:0 calc(var(--g) * -1);
  padding:0 var(--g) 2px;scrollbar-width:none;}
.mb-rail::-webkit-scrollbar{display:none;}
.mb-rail>*{position:relative;}
.mb-ev{flex:none;width:158px;scroll-snap-align:start;text-decoration:none;color:var(--fg);}
.mb-ev-p{position:relative;display:block;aspect-ratio:4/5;border-radius:var(--r-md);overflow:hidden;background:var(--s2);}
.mb-ev-p>.mb-ph,.mb-ev-p>.mb-art{position:absolute;inset:0;}
.mb-datebox{position:absolute;z-index:2;left:10px;top:10px;width:46px;padding:5px 0 6px;border-radius:11px;background:#fff;color:#000;text-align:center;line-height:1;}
.mb-datebox small{display:block;font-size:10px;font-weight:700;letter-spacing:.08em;color:var(--acc-on-white);}
.mb-datebox b{display:block;font-size:19px;font-weight:720;letter-spacing:-.03em;margin-top:3px;}
.mb-ev-b{display:flex;flex-direction:column;gap:2px;padding:10px 2px 0;}
.mb-ev-b strong{font-size:15px;font-weight:620;letter-spacing:-.015em;line-height:1.22;}
.mb-ev-b span{font-size:13px;color:var(--fg2);}
.mb-ev-b .mb-mine{color:var(--acc);font-weight:550;}
.mb-ev .mb-sample{position:absolute;right:10px;top:10px;z-index:3;}

/* a row card: an icon, two lines, a chevron */
.mb-pray,.mb-row{display:flex;align-items:center;gap:14px;margin:12px 0 0;padding:16px;border-radius:var(--r-md);background:var(--s1);
  color:var(--fg);text-decoration:none;}
.mb-pray{margin-top:36px;}
.mb-pray-ic,.mb-row-ic{width:44px;height:44px;flex:none;border-radius:50%;display:grid;place-items:center;background:var(--acc-soft);color:var(--acc);}
.mb-pray>span:nth-child(2),.mb-row-t{flex:1;min-width:0;display:flex;flex-direction:column;gap:1px;}
.mb-pray strong,.mb-row-t strong{font-size:16px;font-weight:620;letter-spacing:-.015em;}
.mb-pray span span,.mb-row-t span{font-size:13.5px;color:var(--fg2);}
.mb-pray>.mb-ic:last-child,.mb-row>.mb-ic:last-child{color:var(--fg3);}

/* reading: a chapter to continue, the church's plan */
.mb-reading-card{display:flex;align-items:center;gap:16px;padding:16px;border-radius:var(--r-md);background:var(--s1);text-decoration:none;color:var(--fg);}
.mb-book{width:52px;height:66px;flex:none;border-radius:6px 12px 12px 6px;display:grid;place-items:center;font-family:var(--mb-serif);font-size:22px;
  font-weight:600;color:var(--on-acc);background:var(--acc-fill);box-shadow:inset 5px 0 0 rgba(0,0,0,.18);}
.mb-reading-card strong{display:block;font-size:17px;font-weight:650;letter-spacing:-.02em;}
.mb-reading-card .mb-list-text span{font-size:13.5px;color:var(--fg2);}
.mb-reading-card>.mb-ic:last-child{color:var(--fg3);}
.mb-plan{display:flex;gap:16px;align-items:center;padding:16px;border-radius:var(--r-md);background:var(--s1);margin:0;}
.mb-plan-b{flex:1;min-width:0;}
.mb-plan-b .mb-kick{font-size:12px;}
.mb-plan-b strong{display:block;font-size:16.5px;font-weight:650;letter-spacing:-.02em;line-height:1.2;margin:2px 0 0;}
.mb-plan-b .mb-plan-acts{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px;align-items:center;}
.mb-plan-b .mp-go{width:auto;min-height:36px;padding:0 14px;font-size:14px;border-radius:999px;}
.mb-plan-b form{margin:0;}
.mb-ring{position:relative;flex:none;display:block;}
.mb-ring svg{display:block;transform:rotate(-90deg);}
.mb-ring b{position:absolute;inset:0;display:grid;place-items:center;font-size:18px;font-weight:720;letter-spacing:-.03em;}

/* lists: messages, chats, settings */
.mb-list{list-style:none;margin:0;padding:0;}
.mb-cards{border-radius:var(--r-md);background:var(--s1);overflow:hidden;}
.mb-list li{position:relative;}
.mb-cards li+li::before{content:"";position:absolute;top:0;right:0;left:var(--inset,70px);height:.5px;background:var(--hair);}
.mb-list a{display:flex;align-items:center;gap:12px;min-height:60px;padding:10px 0;color:var(--fg);text-decoration:none;}
.mb-cards a{padding:11px 14px;}
.mb-list a>.mb-ic:last-child{color:var(--fg3);}
.mb-list-ic{width:32px;height:32px;flex:none;border-radius:9px;display:grid;place-items:center;background:var(--s3);color:var(--fg);}
.mb-list-ic .mb-ic{width:17px;height:17px;}
.mb-list-text{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}
.mb-list-text strong{font-size:15.5px;font-weight:600;letter-spacing:-.015em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.mb-list-text span{font-size:13px;color:var(--fg2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.mb-thumb{position:relative;width:96px;height:54px;flex:none;border-radius:10px;overflow:hidden;display:grid;place-items:center;color:#fff;background:var(--s2);}
.mb-thumb>.mb-ph{position:absolute;inset:0;}
.mb-chat-av{width:50px;height:50px;border-radius:50%;background:var(--s2);color:var(--fg);font-weight:650;font-size:16px;}

/* large-title pages, coming soon */
.mb-soon{position:relative;isolation:isolate;display:flex;align-items:flex-end;min-height:260px;margin:16px 0 0;border-radius:var(--r-lg);overflow:hidden;color:#fff;}
.mb-soon>.mb-gen,.mb-soon>.mb-ph{position:absolute;inset:0;z-index:-2;}
.mb-soon::after{content:"";position:absolute;inset:0;z-index:-1;background:linear-gradient(180deg,transparent 30%,rgba(0,0,0,.82));}
.mb-soon-in{padding:20px;}
.mb-soon .mb-kick{color:rgba(255,255,255,.75);}
.mb-soon h2{font-size:28px;font-weight:720;letter-spacing:-.035em;line-height:1.05;margin:6px 0 8px;color:#fff;}
.mb-soon p{margin:0;color:rgba(255,255,255,.82);font-size:14.5px;}
.mb-pair{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:14px 0 0;}
.mb-pair .mp-go{padding:0 10px;font-size:15px;}

/* Watch */
.mb-livecard{display:flex;align-items:center;gap:14px;margin:16px 0 0;padding:14px 14px 14px 16px;border-radius:var(--r-md);background:var(--s1);
  color:var(--fg);text-decoration:none;}
.mb-livecard .mb-row-ic{background:var(--acc-soft);color:var(--acc);}
.mb-livecard .mb-row-t small{display:block;font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--fg3);}
.mb-livecard .mb-row-t span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-variant-numeric:tabular-nums;}
.mb-livecard .mp-go{width:auto;min-height:38px;padding:0 14px;font-size:14px;border-radius:999px;flex:none;}
.mb-livecard.is-live{background:#ff3b30;color:#fff;}
.mb-livecard.is-live .mb-row-ic{background:rgba(255,255,255,.2);color:#fff;}
.mb-livecard.is-live .mb-row-t small,.mb-livecard.is-live .mb-row-t span{color:rgba(255,255,255,.88);}
.mb-livecard.is-live .mp-go{background:#fff;color:#d70015;box-shadow:none;}
.mb-feat{margin-top:28px;}
.mb-feat .mb-mtile-art{border-radius:var(--r-lg);}
.mb-feat .mb-kick{margin-top:16px;}
.mb-feat h2{font-size:24px;font-weight:720;letter-spacing:-.035em;line-height:1.1;margin:4px 0 4px;}
.mb-feat h2 a{color:inherit;text-decoration:none;}
.mb-acts{display:flex;gap:10px;margin:14px 0 0;}
.mb-acts>*{flex:1;width:auto;}
.mb-acts .mb-sq{flex:0 0 52px;padding:0;}
.mb-ser{flex:none;width:236px;scroll-snap-align:start;text-decoration:none;color:var(--fg);}
.mb-ser .mb-mtile-art{border-radius:var(--r-sm);}
.mb-art{position:relative;display:flex;flex-direction:column;justify-content:flex-end;overflow:hidden;padding:14px 16px;text-decoration:none;isolation:isolate;
  border-radius:var(--r-md);aspect-ratio:16/9;}
.mb-art-kick{font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;opacity:.9;margin-bottom:4px;}
.mb-art-title{font-size:26px;font-weight:760;letter-spacing:-.045em;line-height:1;overflow-wrap:anywhere;margin:0;}
.mb-art-play{position:absolute;right:14px;bottom:14px;width:46px;height:46px;border-radius:50%;display:grid;place-items:center;background:#fff;color:#000;}
.mb-mtile-art .mb-art,.mb-thumb .mb-art{border-radius:0;aspect-ratio:auto;}
.mb-thumb .mb-art{padding:6px 8px;}
.mb-thumb .mb-titled b{font-size:11.5px;letter-spacing:-.02em;padding:14px 7px 5px;}
.mb-thumb .mb-art-title{font-size:12px;letter-spacing:-.02em;}
.mb-shelf{display:flex;gap:12px;overflow-x:auto;margin:0 calc(var(--g) * -1);padding:0 var(--g) 2px;scrollbar-width:none;}
.mb-shelf::-webkit-scrollbar{display:none;}

/* a message */
.mb-player{margin:0 calc(var(--g) * -1);}
.mb-player>.mb-ph,.mb-player>.mb-art{aspect-ratio:16/9;border-radius:0;}
.mb-video{position:relative;width:100%;aspect-ratio:16/9;overflow:hidden;background:#000;}
.mb-video iframe{position:absolute;inset:0;width:100%;height:100%;border:0;}
.mb-player audio{width:calc(100% - 40px);margin:12px 20px 0;}
.mb-scrip{display:inline-flex;align-items:center;gap:6px;min-height:32px;padding:0 12px;border-radius:999px;background:var(--acc-soft);color:var(--acc);
  font-size:13.5px;font-weight:600;margin-top:12px;}
.mb-scrip a{color:inherit;text-decoration:none;}
.mb-text{font-size:16px;line-height:1.62;white-space:pre-line;margin:0;color:var(--fg);}
.mb-q{border-radius:var(--r-md);padding:18px;background:var(--s1);margin-top:22px;}
.mb-q h2{font-size:12.5px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;color:var(--acc);margin:0 0 10px;}
.mb-q .mb-text{font-size:15.5px;}

/* live */
.mb-live-badge{display:inline-flex;align-items:center;gap:6px;height:26px;padding:0 10px;border-radius:999px;background:#ff3b30;color:#fff;
  font-size:12px;font-weight:700;letter-spacing:.02em;align-self:flex-start;}
.mb-live-dot{width:8px;height:8px;border-radius:50%;background:#ff3b30;flex:none;}
.mb-live-badge .mb-live-dot,.mb-when.is-live .mb-live-dot,.mb-livecard.is-live .mb-live-dot{background:#fff;}
.mb-live-dot.mb-off{background:var(--fg3);width:10px;height:10px;margin-top:6px;}
.mb-chip .mb-live-dot,.mp-go .mb-live-dot{background:currentColor;}
@media (prefers-reduced-motion:no-preference){.mb-live-badge .mb-live-dot,.mb-chip .mb-live-dot,.mb-when .mb-live-dot{animation:mbpulse 1.6s ease-in-out infinite;}}
@keyframes mbpulse{0%,100%{opacity:1;}50%{opacity:.35;}}
.mb-offair{position:relative;isolation:isolate;overflow:hidden;display:flex;align-items:flex-end;min-height:300px;margin:8px 0 0;padding:0 20px 20px;
  border-radius:var(--r-lg);color:#fff;}
.mb-offair>.mb-gen,.mb-offair>.mb-ph{position:absolute;inset:0;z-index:-2;}
.mb-offair::after{content:"";position:absolute;inset:0;z-index:-1;background:linear-gradient(180deg,rgba(0,0,0,.1) 20%,rgba(0,0,0,.86) 100%);}
.mb-offair h1{margin:8px 0 4px;font-size:30px;color:#fff;}
.mb-offair p,.mb-offair .mp-muted{color:rgba(255,255,255,.82);}
.mb-offair .mb-kick{color:rgba(255,255,255,.7);}
.mb-prayer-link{display:flex;align-items:center;gap:12px;min-height:56px;margin-top:20px;padding:14px 16px;border-radius:var(--r-md);background:var(--s1);
  color:var(--fg);text-decoration:none;font-size:15px;}
.mb-prayer-link span{flex:1;}
.mb-prayer-link .mb-ic:first-child{color:var(--acc);}
.mb-prayer-link .mb-ic:last-child{color:var(--fg3);}
.mb-live-head{margin-top:14px;display:flex;flex-direction:column;}
.mb-live-actions{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:14px;align-items:center;}
.mb-live-actions form{margin:0;}
.mb-live-actions .mb-chip{justify-self:start;height:44px;padding:0 14px;font-size:13.5px;}
.mb-linkout{display:grid;place-items:center;padding:20px;background:var(--s1);}
.mb-linkout .mp-go{width:auto;}
.mb-chat{list-style:none;margin:0;padding:12px;max-height:50vh;min-height:170px;overflow-y:auto;border-radius:var(--r-md);background:var(--s1);
  display:flex;flex-direction:column;gap:6px;}
.mb-msg{max-width:80%;align-self:flex-start;display:flex;flex-direction:column;gap:2px;padding:9px 13px;border-radius:20px;background:var(--s2);}
.mb-msg.mb-mine{align-self:flex-end;background:var(--acc-fill);color:var(--on-acc);}
.mb-msg.mb-host{background:var(--acc-soft);}
.mb-msg-who{font-size:12px;font-weight:650;color:var(--fg3);}
.mb-host .mb-msg-who{color:var(--acc);}
.mb-msg-body{font-size:16px;line-height:1.35;overflow-wrap:anywhere;}
.mb-msg-held{font-size:12px;font-style:italic;opacity:.85;}
.mb-msg.has-av{position:relative;margin-left:38px;}
.mb-msg-av{position:absolute;left:-38px;bottom:0;width:30px;height:30px;border-radius:50%;display:grid;place-items:center;
  font-size:11px;font-weight:650;background:var(--s2);color:var(--fg);}
.mb-chat-empty{align-self:center;margin:auto 0;font-size:14px;}
.mb-compose{display:flex;gap:8px;margin-top:10px;align-items:center;}
.mb-compose .mp-input{flex:1;min-width:0;min-height:44px;border-radius:22px;padding:0 18px;background:var(--bg);box-shadow:inset 0 0 0 1px var(--line);}
.mb-compose .mp-go{width:40px;min-height:40px;height:40px;flex:none;padding:0;border-radius:50%;}
.mb-thread .mb-chat{max-height:none;min-height:50vh;background:transparent;padding:6px 0;}
.mb-thread .mb-compose{position:sticky;bottom:0;z-index:5;padding:10px var(--g) calc(10px + env(safe-area-inset-bottom,0px));
  margin:12px calc(var(--g) * -1) 0;background:var(--bar);-webkit-backdrop-filter:blur(22px);backdrop-filter:blur(22px);box-shadow:0 -.5px 0 var(--hair);}
.mb-chat-note{margin:10px 2px 0;font-size:13px;}
.mb-chat-err{margin:8px 2px 0;}
.mb-report{margin:0;}
.mb-report-btn{background:none;border:0;padding:4px 0 0;font:inherit;font-size:12px;color:var(--fg3);cursor:pointer;text-decoration:underline;}
.mb-request{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:12px;}
.mb-request p{flex:1 1 100%;margin:0;}
.mb-request form{margin:0;}
.mb-request .mp-go{width:auto;min-height:44px;}
.mb-chat-tools{margin-top:6px;}
.mb-guide-list{margin:10px 0 16px;padding-left:20px;display:flex;flex-direction:column;gap:8px;line-height:1.5;color:var(--fg2);}
.mb-start{display:flex!important;flex-wrap:wrap;gap:8px;flex:1 1 100%;}
.mb-start select{flex:1 1 200px;min-width:0;min-height:44px;}
.mb-meet{margin-top:14px;}
.mb-tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;}
.mb-tile{position:relative;aspect-ratio:4/3;border-radius:14px;overflow:hidden;background:var(--s1);display:grid;place-items:center;}
.mb-tile video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;}
.mb-tile-name{position:absolute;left:8px;bottom:8px;z-index:1;padding:3px 8px;border-radius:999px;background:rgba(0,0,0,.55);color:#fff;
  font-size:12px;font-weight:650;max-width:calc(100% - 16px);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.mb-meet-bar{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-top:12px;}
.mb-meet-bar .mp-go{min-height:48px;padding:0 10px;font-size:14px;}
.mb-meet-bar .mp-go[aria-pressed="true"]{background:var(--acc-soft);color:var(--acc);}
.mb-end{margin-top:10px;}

/* the Bible */
.bb-head{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;flex-wrap:wrap;}
.bb-head h1{margin-bottom:6px;}
.bb-tr{display:inline-flex;padding:3px;border-radius:999px;background:var(--s1);flex:none;margin-bottom:8px;}
.bb-tr a{min-width:52px;min-height:32px;padding:0 12px;display:grid;place-items:center;border-radius:999px;font-size:13px;font-weight:650;
  letter-spacing:.02em;color:var(--fg2);text-decoration:none;}
.bb-tr a[aria-current]{background:var(--s3);color:var(--fg);}
.bb-go{display:flex;gap:8px;margin:12px 0 4px;}
.bb-go .mp-input{flex:1;min-width:0;min-height:44px;border-radius:12px;padding:0 14px;}
.bb-go .mp-go{width:44px;min-height:44px;flex:none;padding:0;border-radius:12px;}
.bb-cont{margin-top:16px;}
.bb-cont .mb-list-text{flex:1;}
.bb-cont strong{font-size:17px;font-weight:650;}
.bb-books{list-style:none;margin:0 0 6px;padding:0;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;}
.bb-books a{display:flex;align-items:center;min-height:50px;padding:0 14px;border-radius:12px;background:var(--s1);color:var(--fg);text-decoration:none;
  font-size:15px;font-weight:550;}
.bb-chapters{list-style:none;margin:14px 0 0;padding:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(54px,1fr));gap:8px;}
.bb-chapters a{display:grid;place-items:center;aspect-ratio:1;border-radius:14px;background:var(--s1);color:var(--fg);text-decoration:none;font-weight:650;
  font-variant-numeric:tabular-nums;}
.bb-text{font-family:var(--mb-serif);font-size:20px;line-height:1.72;letter-spacing:.003em;margin:6px 0 0;}
.bb-text p{margin:0 0 14px;}
.bb-text i{font-style:italic;opacity:.92;}
.bb-lines p{margin:0 0 8px;}
.bb-n{font-family:var(--mb-ui);font-size:11px;font-weight:700;color:var(--acc);margin-right:3px;vertical-align:super;line-height:0;scroll-margin-top:90px;}
.bb-hl{background:var(--acc-soft);color:inherit;border-radius:4px;box-shadow:0 0 0 3px var(--acc-soft);-webkit-box-decoration-break:clone;box-decoration-break:clone;}
.bb-steps{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:22px 0 0;}
.bb-step{display:flex;align-items:center;gap:8px;min-height:62px;padding:10px 14px;border-radius:var(--r-md);background:var(--s1);color:var(--fg);text-decoration:none;}
.bb-step span{display:flex;flex-direction:column;font-size:12px;color:var(--fg3);min-width:0;}
.bb-step strong{font-size:15px;color:var(--fg);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.bb-next{justify-content:flex-end;text-align:right;}
.bb-src{margin:18px 0 0;font-size:12px;}
.bb-ref{color:var(--acc);font-weight:650;text-decoration:none;}
.bb-pass{margin-top:16px;}
.bb-pass .bb-text{font-size:18px;}
.bb-pass-ref{margin:10px 0 2px;}

/* Connect: groups */
.mb-seg{display:grid;grid-auto-flow:column;grid-auto-columns:1fr;padding:3px;border-radius:12px;background:var(--s1);margin:14px 0 4px;}
.mb-seg a{display:grid;place-items:center;min-height:36px;border-radius:9px;font-size:14px;font-weight:600;color:var(--fg2);text-decoration:none;}
.mb-seg a[aria-current]{background:var(--s3);color:var(--fg);box-shadow:0 1px 3px rgba(0,0,0,.12);}
.mb-seg a .mb-unread{margin-left:6px;min-width:19px;height:19px;font-size:11px;}
.mb-grp{background:var(--s1);border-radius:var(--r-md);padding:12px;margin-bottom:10px;}
.mb-grp-top{display:flex;gap:14px;align-items:center;}
.mb-grp-pic{position:relative;width:76px;height:76px;flex:none;border-radius:14px;overflow:hidden;background:var(--s2);}
.mb-grp-pic>.mb-ph,.mb-grp-pic>.mb-art{position:absolute;inset:0;border-radius:0;aspect-ratio:auto;padding:6px;}
.mb-grp-pic .mb-art-title{font-size:13px;}
.mb-grp-t{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}
.mb-grp-t h3{font-size:16.5px;margin:0;}
.mb-grp-t>span{font-size:13px;color:var(--fg2);}
.mb-grp-t .mb-chip,.mb-grp-t .mb-live-badge{margin-top:5px;}
.mb-grp-more{margin:10px 2px 0;font-size:14px;color:var(--fg2);}
.mb-grp-more p{margin:0 0 6px;}
/* Connect > Classes (member_portal_classes): the next class night, the road, your classes, classes to join. */
.mb-cnext{margin:16px 0 0;padding:18px;border-radius:var(--r-lg);background:var(--acc-soft);border:1px solid var(--mb-soft-line);}
.mb-cnext .mb-when{background:var(--acc-fill);color:var(--on-acc);}
.mb-cnext.is-live .mb-when{background:#ff3b30;color:#fff;}
.mb-cnext h2{font-size:22px;font-weight:720;letter-spacing:-.02em;line-height:1.15;margin:10px 0 4px;}
.mb-cnext p{margin:0;color:var(--fg2);font-size:14.5px;}
.mb-road{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;}
.mb-road li{position:relative;display:grid;grid-template-columns:32px minmax(0,1fr) auto;gap:12px;align-items:center;padding:10px 0;}
.mb-road li:not(:last-child)::after{content:"";position:absolute;left:15px;top:44px;bottom:-8px;width:2px;background:var(--line);}
.mb-road-dot{width:32px;height:32px;border-radius:50%;display:grid;place-items:center;font-size:13px;font-weight:700;
background:var(--s2);color:var(--fg2);position:relative;z-index:1;}
.mb-road li[data-state=done] .mb-road-dot{background:var(--acc-soft);color:var(--acc);}
.mb-road li[data-state=now] .mb-road-dot{background:var(--acc-fill);color:var(--on-acc);}
.mb-road li[data-state=finish] .mb-road-dot{background:var(--s1);color:var(--acc);}
.mb-road-t{min-width:0;display:flex;flex-direction:column;gap:2px;}
.mb-road-t b{font-size:16px;}
.mb-road-t span{font-size:13px;color:var(--fg2);}
.mb-road li[data-state=later] .mb-road-t b{color:var(--fg2);}
.mb-road .mp-actions{margin:0;}
.mb-clist{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:10px;}
.mb-cls{display:flex;align-items:center;gap:12px;padding:14px;border-radius:var(--r-md);background:var(--s1);}
.mb-cls-t{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}
.mb-cls-t b{font-size:16px;}
.mb-cls-t>span:not(.mb-kick){font-size:13px;color:var(--fg2);}
.mb-cls-bar{display:block;height:4px;margin-top:6px;border-radius:2px;background:var(--s3);overflow:hidden;}
.mb-cls-bar i{display:block;height:100%;background:var(--acc);border-radius:2px;}
.mb-cls .mp-go{width:auto;min-height:40px;padding:0 16px;font-size:14px;border-radius:999px;flex:none;}
.mb-copen{padding:16px;border-radius:var(--r-md);background:var(--s1);margin-bottom:10px;}
.mb-copen h3{font-size:17px;margin:4px 0 2px;}
.mb-copen-f{display:block;font-size:13px;color:var(--fg2);}
.mb-copen p{margin:8px 0 0;font-size:14px;color:var(--fg2);}
.mb-cfoot{font-size:13px;text-align:center;margin-top:6px;}
.mb-cempty{margin:20px 0 0;padding:28px 20px;border-radius:var(--r-lg);background:var(--s1);text-align:center;color:var(--fg2);}
.mb-cempty svg{color:var(--acc);}
.mb-cempty h2{color:var(--fg);font-size:20px;margin:10px 0 6px;}
.mb-cempty p{margin:0;font-size:14.5px;}
.mp-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;align-items:center;}
.mp-actions:empty{display:none;}
.mp-actions form{display:contents;}
.mp-actions .mp-go{width:auto;min-height:40px;padding:0 16px;font-size:14px;border-radius:999px;}
.mp-actions .mp-link{font-size:14px;padding:0 6px;min-height:40px;color:var(--fg2);}
.mb-find{flex:none;width:210px;scroll-snap-align:start;border-radius:var(--r-md);background:var(--s1);overflow:hidden;display:flex;flex-direction:column;}
.mb-find-p{position:relative;display:block;aspect-ratio:16/10;background:var(--s2);}
.mb-find-p>.mb-ph,.mb-find-p>.mb-art{position:absolute;inset:0;border-radius:0;aspect-ratio:auto;}
.mb-find-b{padding:12px 14px 14px;display:flex;flex-direction:column;gap:2px;flex:1;}
.mb-find-b h3{font-size:15.5px;margin:0;}
.mb-find-b>span{font-size:12.5px;color:var(--fg2);}
.mb-find-b p{font-size:13px;color:var(--fg2);margin:4px 0 0;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.mb-find-b form{margin-top:auto;padding-top:10px;}
.mb-find-b .mp-go{width:auto;min-height:36px;padding:0 16px;font-size:14px;border-radius:999px;}
.mp-occ h2,.mp-occ h3{font-size:19px;font-weight:700;letter-spacing:-.025em;line-height:1.15;margin:0 0 4px;}
.mp-when{font-size:12.5px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--acc);margin:0 0 4px;}
.mp-mine{font-size:13.5px;font-weight:600;margin:8px 0 0;color:var(--acc);}
.mp-serve{display:flex!important;gap:8px;flex-wrap:wrap;flex:1 1 100%;}
.mp-serve select{flex:1 1 160px;min-width:0;min-height:40px;}
.mp-row{display:flex;flex-direction:column;gap:10px;}
.mp-person{width:100%;text-align:left;padding:14px 16px;min-height:56px;border:0;border-radius:var(--r-md);background:var(--s1);color:var(--fg);
  font:inherit;font-size:16px;cursor:pointer;}

/* Me */
.mb-profile{display:flex;flex-direction:column;align-items:center;text-align:center;margin:4px 0 0;}
.mb-profile .mb-avatar{width:88px;height:88px;font-size:30px;font-weight:650;background:var(--acc-fill);color:var(--on-acc);box-shadow:none;}
.mb-profile h1{font-size:26px;margin:14px 0 2px;}
.mb-profile .mp-muted{font-size:14.5px;}
.mb-photo{margin:0;}
.mb-photo-pick{position:relative;display:block;cursor:pointer;border-radius:50%;}
.mb-photo-pick:focus-within{outline:2px solid var(--focus);outline-offset:4px;}
.mb-photo-badge{position:absolute;right:-2px;bottom:-2px;width:32px;height:32px;border-radius:50%;display:grid;place-items:center;
  background:var(--fg);color:var(--bg);box-shadow:0 0 0 3px var(--bg);}
.mb-photo-note{margin:10px 0 2px;font-size:13px;color:var(--fg3);max-width:300px;}
.mp-total{font-size:34px;font-weight:720;letter-spacing:-.04em;font-variant-numeric:tabular-nums;line-height:1;margin:4px 0 0;}
.mb-give-card{background:var(--s1);border-radius:var(--r-md);padding:18px;margin-top:24px;}
.mb-give-top{display:flex;align-items:flex-end;justify-content:space-between;flex-wrap:wrap;gap:12px;}
.mb-give-top .mb-kick{font-size:12px;}
.mb-bars{display:flex;align-items:flex-end;gap:5px;height:48px;flex:none;}
.mb-bars i{width:8px;border-radius:3px;background:var(--s3);min-height:4px;}
.mb-bars i.mb-on{background:var(--acc-fill);}
.mb-months{display:none;}
.mp-years{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 14px;}
.mp-years a{padding:0 12px;min-height:32px;border-radius:999px;color:var(--fg2);text-decoration:none;font-size:13px;font-weight:650;display:inline-flex;
  align-items:center;background:var(--s2);}
.mp-years a[aria-current]{background:var(--fg);color:var(--bg);}
.mp-gifts{list-style:none;margin:8px 0 0;padding:0;}
.mp-gifts li{display:flex;justify-content:space-between;gap:12px;padding:10px 0;border-top:.5px solid var(--hair);font-size:14px;}
.mp-gifts li span:last-child{font-variant-numeric:tabular-nums;white-space:nowrap;font-weight:600;}
.mb-give-row{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:16px;}
.mb-give-row .mp-go{min-height:46px;font-size:15px;}
details.mb-each summary{cursor:pointer;min-height:40px;display:flex;align-items:center;font-size:14px;color:var(--acc);list-style:none;margin-top:8px;}
details.mb-each summary::-webkit-details-marker{display:none;}
.mb-signout{display:block;width:100%;margin-top:20px;padding:0 16px;min-height:52px;border:0;border-radius:var(--r-md);background:var(--s1);
  color:var(--error);font:inherit;font-size:16px;text-align:left;cursor:pointer;}
table{width:100%;border-collapse:collapse;font-size:14px;}
th,td{text-align:left;padding:9px 6px;border-bottom:.5px solid var(--hair);}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;}

/* samples, in the owner's preview only (member_app_samples) */
.mb-sample{display:inline-flex;align-items:center;height:22px;padding:0 8px;border-radius:7px;font-size:10px;font-weight:700;letter-spacing:.12em;
  text-transform:uppercase;color:#fff;background:rgba(0,0,0,.6);border:1px dashed rgba(255,255,255,.65);vertical-align:middle;}
.mp-sect .mb-sample,.mb-kick .mb-sample,.mp-when .mb-sample,h1 .mb-sample,.mb-sh .mb-sample{margin-left:8px;color:var(--acc);background:transparent;
  border-color:var(--acc);}
.mb-hint{display:flex;align-items:center;gap:8px;margin:0 0 12px;padding:9px 12px;border-radius:12px;font-size:12.5px;line-height:1.35;
  color:var(--acc);border:1px dashed $accent_50;background:$fill_08;}
.mb-hint .mb-ic{flex:none;}

/* the tab bar */
.mb-nav{position:fixed;z-index:20;left:0;right:0;bottom:0;display:grid;padding:7px max(6px,env(safe-area-inset-right,0px)) calc(4px + env(safe-area-inset-bottom,0px)) max(6px,env(safe-area-inset-left,0px));
  background:var(--bar);-webkit-backdrop-filter:blur(22px) saturate(1.7);backdrop-filter:blur(22px) saturate(1.7);box-shadow:0 -.5px 0 var(--hair);}
.mb-tab{display:flex;flex-direction:column;align-items:center;gap:3px;min-height:49px;padding-top:2px;text-decoration:none;color:var(--fg3);
  font-size:10.5px;font-weight:600;letter-spacing:0;}
.mb-tab[aria-current]{color:var(--acc);}
@media (min-width:600px){.mb-hero{aspect-ratio:16/10;}}
@media (min-width:600px){.mb-nav{left:50%;right:auto;width:560px;margin-left:-280px;bottom:14px;border-radius:24px;padding-bottom:4px;
  box-shadow:0 18px 40px rgba(0,0,0,.35),0 0 0 .5px var(--hair);}}
@media (min-width:1100px){.mb-nav{top:0;bottom:0;left:0;right:auto;width:92px;margin-left:0;border-radius:0;display:flex;
  flex-direction:column;justify-content:center;align-items:center;gap:6px;padding:24px 8px;box-shadow:.5px 0 0 var(--hair);}
  .mb-tab{width:76px;min-height:60px;justify-content:center;border-radius:16px;padding-top:0;}
  .mb-tab[aria-current]{background:var(--s1);}
  .mp-shell.mb-has-nav{padding-bottom:48px;}}

.mp-go:focus-visible,.mp-input:focus-visible,.mp-link:focus-visible,.mp-person:focus-visible,.mp-years a:focus-visible,.mb-tab:focus-visible,
.mb-quick a:focus-visible,.mb-list a:focus-visible,.mb-ev:focus-visible,.mb-art:focus-visible,.mb-hero:focus-visible,.mb-back:focus-visible,
.mb-avatar:focus-visible,.mb-mtile:focus-visible,.mb-bt:focus-visible,details.mb-each summary:focus-visible,.mb-pray:focus-visible,.mb-row:focus-visible,
.mb-reading-card:focus-visible,.mb-chat-link:focus-visible,.mb-verse-foot a:focus-visible,.bb-books a:focus-visible,.bb-chapters a:focus-visible,
.bb-tr a:focus-visible,.mb-livecard:focus-visible,.mb-seg a:focus-visible,.mb-ser:focus-visible,.mb-sh a:focus-visible,.mb-signout:focus-visible
{outline:2px solid var(--focus);outline-offset:3px;}
@media (prefers-reduced-motion:no-preference){
  .mb-quick a,.mb-ev,.mb-mtile,.mb-bt,.mb-pray,.mb-row,.mb-reading-card,.mb-hero,.mb-ser{transition:transform .15s ease;}
  .mb-quick a:active,.mb-ev:active,.mb-mtile:active,.mb-bt:active,.mb-pray:active,.mb-row:active,.mb-reading-card:active,.mb-hero:active,
  .mb-ser:active{transform:scale(.98);}
}
@media print{.mp-noprint,.mb-nav,.mb-top{display:none!important;} html,body{background:#fff;color:#000;}
  .mp-shell{max-width:none;padding:0;} .mp-card{background:#fff;} th,td{border-color:#999;} .mp-muted{color:#333;}}""")


def css(biz: Dict[str, Any], theme: Dict[str, Any], space: str = "church") -> str:
    """The member app's stylesheet. The mp-* classes the older renderers
    use keep working through the same tokens. Youth adds its loud type and
    its pieces (member_spaces)."""
    import member_spaces
    p = palette(biz, theme, space)
    tokens = _Tokens({k: v for k, v in p.items() if isinstance(v, str)})
    tokens["scheme"] = "dark" if p["dark"] else "light"
    church = palette(biz, theme)
    tokens["church_dot"], tokens["on_church_dot"] = church["fill"], church["on_fill"]
    tokens["youth_dot"] = member_spaces.youth_colour(biz)
    tokens["hot"] = palette({**biz, "settings": {**(biz.get("settings") or {}), "member_portal": {"base": "black"}}},
                            theme)["accent"]
    out = _CSS.substitute(tokens) + _SPACES_CSS.substitute(tokens)
    if space == "youth":
        out += _YOUTH_CSS.substitute(tokens)
    elif space == "kids":
        out += _KIDS_CSS.substitute(tokens)
    return out


# The switcher (Church · Youth · Kids), for anyone with more than one space.
_SPACES_CSS = Template("""
.mb-spaces{position:relative;}
.mb-switch{display:inline-flex;align-items:center;gap:8px;height:40px;padding:0 12px 0 5px;border-radius:999px;background:var(--s1);
  font-weight:650;font-size:15px;cursor:pointer;list-style:none;color:var(--fg);}
.mb-switch::-webkit-details-marker{display:none;}
.mb-switch .mb-ic{color:var(--fg3);}
.mb-switch i,.mb-sp i{width:30px;height:30px;border-radius:50%;display:grid;place-items:center;font-style:normal;font-weight:750;font-size:12px;flex:none;}
.mb-sp-church i{background:$church_dot;color:$on_church_dot;}
.mb-sp-youth i{background:$youth_dot;color:#0b0b0c;}
.mb-sp-kids i{background:#ffc93c;color:#2b1d0e;}
.mb-spaces-menu{position:absolute;left:-4px;top:48px;z-index:40;width:min(340px,calc(100vw - 32px));padding:8px 8px 10px;border-radius:24px;
  background:#1b1b1e;color:#f5f5f7;box-shadow:0 24px 50px rgba(0,0,0,.55);}
.mb-sp-h{margin:6px 10px 8px;font-size:12px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:#8b8b92;}
.mb-sp{display:flex;align-items:center;gap:12px;padding:10px;border-radius:16px;color:#f5f5f7;text-decoration:none;}
.mb-sp[aria-current]{background:#2a2a2e;}
.mb-sp i{width:44px;height:44px;border-radius:14px;font-size:14px;}
.mb-sp b{display:block;font-size:16px;letter-spacing:-.015em;}
.mb-sp small{display:block;font-size:12.5px;color:#a8a8ae;}
.mb-sp .mb-sp-lead{margin-left:auto;background:$youth_dot;color:#111;}
.mb-sp-note{margin:8px 10px 2px;font-size:12px;color:#8b8b92;line-height:1.4;}
.mb-sp-lead{display:inline-flex;align-items:center;height:20px;padding:0 7px;border-radius:999px;background:var(--acc-fill);color:var(--on-acc);
  font-size:10px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;flex:none;}
.mb-spaces[open]>.mb-switch{box-shadow:0 0 0 2px var(--acc);}
""")


# Youth: black, its own colour, loud type, stickers (Kevin approved the
# concept 2026-10-15).
_YOUTH_CSS = Template("""
body.sp-youth{--hot:$hot;}
.sp-youth h1,.sp-youth .mb-lt h1{text-transform:uppercase;font-weight:800;letter-spacing:-.045em;}
.y-mark{display:inline-flex;align-items:center;gap:8px;font-weight:800;font-size:15px;letter-spacing:.14em;text-transform:uppercase;color:var(--fg);}
.y-mark b{background:var(--acc-fill);color:var(--on-acc);padding:3px 7px;border-radius:7px;letter-spacing:.04em;font-size:13px;}
.y-hello{font-size:44px;font-weight:800;letter-spacing:-.05em;line-height:.92;text-transform:uppercase;margin:6px 0 16px;}
.y-hello span{color:var(--acc);}
.y-hero{position:relative;isolation:isolate;border-radius:26px;overflow:hidden;aspect-ratio:350/360;color:#fff;transform:rotate(-.8deg);margin:4px 2px 0;}
.y-hero>.mb-ph,.y-hero>.mb-gen{position:absolute;inset:0;z-index:-2;}
.y-hero>.mb-ph img{filter:grayscale(1) contrast(1.25);}
.y-hero::after{content:"";position:absolute;inset:0;z-index:-1;background:linear-gradient(180deg,transparent 30%,rgba(0,0,0,.88));}
.y-hero-in{position:absolute;left:0;right:0;bottom:0;padding:20px;}
.y-when{font-weight:800;font-size:13px;letter-spacing:.1em;text-transform:uppercase;color:var(--acc);}
.y-hero h2{font-size:40px;font-weight:800;letter-spacing:-.05em;line-height:.9;text-transform:uppercase;margin:8px 0 6px;color:#fff;}
.y-hero p{margin:0;color:rgba(255,255,255,.8);font-size:14px;}
.y-go{display:flex;align-items:center;gap:12px;margin-top:14px;flex-wrap:wrap;}
.y-go form{margin:0;}
.y-btn{display:inline-flex;align-items:center;gap:8px;min-height:48px;padding:0 20px;border:0;border-radius:14px;background:var(--acc-fill);color:var(--on-acc);
  font:inherit;font-weight:800;font-size:15px;text-transform:uppercase;letter-spacing:.04em;box-shadow:4px 4px 0 var(--hot);cursor:pointer;}
.y-count{font-size:13.5px;color:rgba(255,255,255,.88);}
.y-in{display:inline-flex;align-items:center;gap:6px;height:40px;padding:0 14px;border-radius:12px;background:rgba(255,255,255,.16);color:#fff;
  font-weight:800;text-transform:uppercase;font-size:13px;letter-spacing:.04em;}
.y-card{flex:none;width:150px;min-height:150px;border-radius:18px;padding:14px;display:flex;flex-direction:column;justify-content:space-between;
  color:#fff;text-decoration:none;scroll-snap-align:start;}
.y-card small{font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;opacity:.85;}
.y-card b{font-size:19px;font-weight:800;letter-spacing:-.03em;line-height:1;text-transform:uppercase;}
.y-crew{display:block;margin:0 0 10px;padding:16px;border-radius:22px;background:var(--s1);border:1.5px solid var(--s3);color:var(--fg);text-decoration:none;}
.y-lab{font-size:11.5px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:var(--acc);}
.y-crew h3{margin:4px 0 2px;font-size:22px;font-weight:800;letter-spacing:-.03em;text-transform:uppercase;}
.y-crew p{margin:0;color:var(--fg2);font-size:13.5px;}
.y-crew .y-led{margin-top:4px;}
.y-post{padding:14px 16px;border-radius:20px;background:var(--s1);margin:0 0 10px;border-left:4px solid var(--acc);}
.y-post-who{display:flex;align-items:center;gap:8px;margin:0 0 4px;font-weight:700;font-size:14px;}
.y-post-t{margin-left:auto;font-weight:500;font-size:12px;color:var(--fg3);}
.y-post-b{margin:0;font-size:15.5px;line-height:1.4;white-space:pre-line;}
.y-post-x{margin:4px 0 0;}
.y-post-x .mp-link{padding:0;min-height:30px;font-size:13px;color:var(--fg3);}
.y-compose{display:flex;flex-direction:column;gap:8px;margin:18px 0 0;padding:16px;border-radius:22px;background:var(--s1);}
.y-compose label{font-size:12px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:var(--acc);}
.y-compose .mp-input{background:var(--bg);min-height:90px;}
.y-compose .y-btn{align-self:flex-start;}
.y-fine{margin:0;font-size:12.5px;color:var(--fg3);}
.y-tools{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:12px;}
.y-tools a{display:flex;flex-direction:column;gap:6px;min-height:106px;padding:14px;border-radius:20px;background:var(--s1);color:var(--fg);text-decoration:none;}
.y-tools a .mb-ic{color:var(--acc);}
.y-tools b{font-size:15px;line-height:1.2;}
.y-tools span{font-size:12.5px;color:var(--fg2);}
.y-safe{display:flex;gap:10px;align-items:flex-start;margin:16px 0 0;padding:12px 14px;border-radius:14px;background:$fill_08;border:1px solid $fill_30;
  font-size:13px;color:var(--fg);}
.y-safe .mb-ic{color:var(--acc);flex:none;margin-top:1px;}
.y-talk{margin-top:12px;}
.sp-youth .mb-tab[aria-current]{color:var(--acc);}
@media (prefers-reduced-motion:reduce){.y-hero{transform:none;}}
""")

# Kids (member_spaces_kids): a cream base, sunshine and sky, Fredoka for
# the big words (Kevin approved the concept 2026-10-15). Kids mode is the
# child's own screen: sky blue, big tiles, no bar, a hold-to-leave button.
_KIDS_CSS = Template("""
body.sp-kids{--k-sun:#ffc83d;--k-sky:#4cc3ff;--k-coral:#ff6b6b;--k-grass:#3cc47c;--k-grape:#7c5cff;--k-ink:#2b1d0e;--k-skyink:#0a6f9e;}
.sp-kids h1,.sp-kids h2,.sp-kids h3,.sp-kids .mb-lt h1,.sp-kids .mb-sh h2,.sp-kids .mb-top-t{font-family:"Fredoka",var(--mb-ui);letter-spacing:-.01em;}
.sp-kids .mb-lt h1{font-weight:700;}
.k-hello{font-size:38px;font-weight:700;line-height:1.02;margin:6px 0 14px;}
.k-hello span{color:var(--acc);}
.k-h2{font-size:22px;font-weight:700;margin:22px 0 10px;}
.k-chips{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 16px;}
.k-chip{display:inline-flex;align-items:center;gap:8px;height:46px;padding:0 16px 0 6px;border-radius:999px;background:var(--s1);
  border:2px solid var(--s3);font-weight:650;font-size:15px;}
.k-dot{width:36px;height:36px;border-radius:50%;display:grid;place-items:center;font-family:"Fredoka",var(--mb-ui);font-weight:700;
  font-size:16px;color:#fff;flex:none;}
.k-c0{background:var(--k-coral);}.k-c1{background:var(--k-grass);}.k-c2{background:var(--k-grape);}
.k-c3{background:var(--k-sky);color:#08304a;}.k-c4{background:#f28c28;}
.k-pass{position:relative;isolation:isolate;overflow:hidden;border-radius:28px;background:var(--k-sun);color:var(--k-ink);padding:20px;margin:0 0 14px;}
.k-pass::after{content:"";position:absolute;z-index:-1;right:-70px;top:-70px;width:200px;height:200px;border-radius:50%;background:rgba(255,255,255,.3);}
.k-kick{margin:0;font-size:12px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;}
.k-sky{color:var(--k-skyink);}
.k-pass h2{font-size:28px;font-weight:700;margin:6px 0 4px;}
.k-pass p{margin:0;font-size:14.5px;line-height:1.45;}
.k-pass .k-when{font-weight:700;margin-bottom:6px;}
.k-code{display:flex;gap:8px;margin:12px 0 10px;}
.k-code b{width:58px;height:70px;border-radius:16px;background:#fff;display:grid;place-items:center;font-family:"Fredoka",var(--mb-ui);
  font-size:40px;font-weight:700;color:var(--k-ink);box-shadow:0 3px 0 rgba(43,29,14,.12);}
.k-in{list-style:none;margin:14px 0 0;padding:6px 14px;border-radius:18px;background:#fff;}
.k-in li{display:flex;justify-content:space-between;gap:10px;padding:8px 0;font-size:14.5px;}
.k-in li+li{border-top:1px solid #f3e6cc;}
.k-in li span{color:#65533f;text-align:right;}
.k-card{display:block;border-radius:24px;background:var(--s1);padding:18px;margin:0 0 14px;box-shadow:0 2px 0 var(--s3);color:var(--fg);text-decoration:none;}
.k-card h3{font-size:24px;font-weight:700;margin:4px 0 6px;}
.k-body{margin:0;font-size:15.5px;line-height:1.5;color:var(--fg);white-space:pre-line;}
.k-ref{color:var(--fg2);white-space:nowrap;}
.k-verse{margin:14px 0 4px;padding:14px 16px;border-radius:16px;background:#fdf0d9;font-family:"Newsreader",Georgia,serif;font-style:italic;
  font-size:19px;line-height:1.35;color:var(--k-ink);}
.k-verse cite{display:block;margin-top:6px;font-family:var(--mb-ui);font-style:normal;font-size:13px;color:#65533f;}
.k-sub{margin:14px 0 4px;font-weight:700;font-size:15px;}
.k-qs{margin:0;padding-left:22px;font-size:15px;line-height:1.55;}
.k-link{display:inline-flex;margin-top:12px;font-weight:700;color:var(--acc);}
.k-play{display:flex;align-items:center;gap:14px;padding:18px;border-radius:24px;background:var(--k-sky);color:#08304a;text-decoration:none;
  margin:0 0 14px;box-shadow:0 4px 0 #2aa3dd;}
.k-play .mb-ic{flex:none;}
.k-play b{display:block;font-family:"Fredoka",var(--mb-ui);font-size:23px;font-weight:700;}
.k-play small{display:block;font-size:13.5px;line-height:1.35;}
.k-band{display:flex;align-items:center;gap:10px;padding:14px 18px;border-radius:20px;background:#dcf5e6;color:#17663b;margin:0 0 12px;font-size:15px;}
.k-band b{margin-left:auto;font-family:"Fredoka",var(--mb-ui);font-size:20px;}
.k-roster{border-radius:24px;background:var(--s1);overflow:hidden;margin:0 0 6px;box-shadow:0 2px 0 var(--s3);}
.k-row{display:flex;align-items:center;gap:12px;padding:12px 16px;}
.k-row+.k-row{border-top:1px solid var(--line);}
.k-row>span:not(.k-dot):not(.k-flag){min-width:0;}
.k-row b{display:block;font-size:16px;}
.k-row small{display:block;font-size:13px;color:var(--fg2);}
.k-flag{margin-left:auto;padding:5px 10px;border-radius:999px;font-size:12.5px;font-weight:700;font-style:normal;max-width:48%;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap;flex:none;}
.k-allergy{background:#ffe1e1;color:#a3191f;}
.k-ready{background:#dcf5e6;color:#17663b;}
.k-office{background:#fff0c7;color:#7a4e00;}
.k-gone{background:var(--s2);color:var(--fg2);}
.k-empty{margin:4px 0 14px;padding:16px;border-radius:20px;background:var(--s1);color:var(--fg2);font-size:14.5px;}
.k-pick{display:flex;gap:10px;margin:0 0 16px;}
.k-pick .mp-input{flex:1;min-width:0;text-transform:uppercase;letter-spacing:.24em;font-weight:700;font-size:20px;background:var(--s1);}
.k-pick .mp-input::placeholder{text-transform:none;letter-spacing:normal;font-weight:500;font-size:16px;}
.k-btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:52px;padding:0 22px;border:0;border-radius:16px;
  background:var(--k-ink);color:#fff;font:inherit;font-weight:700;font-size:16px;cursor:pointer;text-decoration:none;}
.k-form{display:flex;flex-direction:column;gap:8px;padding:18px;border-radius:24px;background:var(--s1);margin:0 0 16px;box-shadow:0 2px 0 var(--s3);}
.k-form>label{font-size:13.5px;font-weight:700;color:var(--fg2);margin-top:4px;}
.k-form .mp-input{background:var(--bg);}
.k-form .k-btn{align-self:flex-start;margin-top:6px;}
.k-fine{font-size:13px;color:var(--fg2);margin:8px 0 0;line-height:1.45;}
.k-who{display:flex;flex-direction:column;gap:8px;margin:8px 0 4px;}
.k-who label{display:flex;align-items:center;gap:12px;min-height:52px;padding:8px 14px;border-radius:14px;background:var(--s2);font-size:15.5px;color:var(--fg);}
.k-who label span{color:var(--fg2);font-size:13.5px;}
.k-who input{width:22px;height:22px;accent-color:var(--k-ink);flex:none;}
.k-who .k-flag{max-width:40%;}
.k-safe{display:flex;gap:10px;align-items:flex-start;margin:16px 0 0;padding:12px 14px;border-radius:14px;background:#fff3d6;font-size:13px;color:var(--fg);}
.k-safe .mb-ic{color:#9a6200;flex:none;margin-top:1px;}
.k-stop{background:#ffe1e1;}
.k-stop .mb-ic{color:#a3191f;}
.k-day{margin:0 0 12px;padding:14px 16px;border-radius:20px;background:var(--s1);}
.k-day h2{font-size:17px;font-weight:700;margin:0 0 6px;}
.k-day ul,.k-list{list-style:none;margin:0;padding:0;}
.k-day li,.k-list li{display:flex;justify-content:space-between;gap:12px;padding:7px 0;font-size:14.5px;}
.k-day li span,.k-list li span{color:var(--fg2);text-align:right;}
.k-list{padding:6px 16px;border-radius:20px;background:var(--s1);}
.k-list li+li{border-top:1px solid var(--line);}
.k-kid{display:flex;gap:14px;align-items:flex-start;}
.k-kid h3{font-size:21px;margin:2px 0 0;}
.k-kid .k-fine{margin:2px 0 0;}
.k-al{margin:10px 0 0;display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:14.5px;}
.k-al .k-flag{margin:0;max-width:none;}
.sp-kids .mb-tab[aria-current]{color:var(--acc);}
.sp-kids .mp-flash{border-radius:16px;}

/* Kids mode: the child's screen */
body.k-mode{background:#4cc3ff;color:#0b2540;}
body.k-mode .mp-foot{display:none;}
.k-mode main.mp-shell{padding:calc(18px + env(safe-area-inset-top,0px)) 20px calc(110px + env(safe-area-inset-bottom,0px));}
.k-mode-in{position:relative;isolation:isolate;}
.k-mode-in::before{content:"";position:fixed;z-index:-1;right:-90px;top:-90px;width:260px;height:260px;border-radius:50%;background:#ffc83d;}
.k-mode-in::after{content:"";position:fixed;z-index:-1;left:-80px;bottom:120px;width:180px;height:180px;border-radius:50%;background:#ff6b6b;opacity:.9;}
.k-stars{display:inline-flex;align-items:center;gap:6px;height:42px;padding:0 18px;border-radius:999px;background:#fff;margin:0;
  font-family:"Fredoka",var(--mb-ui);font-weight:700;font-size:17px;color:#0b2540;}
.k-stars span:first-child{color:#f2a100;}
.k-mode h1{font-family:"Fredoka",var(--mb-ui);font-size:48px;font-weight:700;color:#fff;margin:16px 0 2px;letter-spacing:-.01em;
  text-shadow:0 3px 0 rgba(8,48,74,.18);text-transform:none;}
.k-lead{margin:0;font-size:17px;font-weight:600;color:#0b2540;}
.k-tiles{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:20px;}
.k-tile{min-height:156px;border:0;border-radius:28px;padding:18px;text-align:left;display:flex;flex-direction:column;justify-content:flex-end;gap:4px;
  color:#fff;font:inherit;box-shadow:0 6px 0 rgba(8,48,74,.18);cursor:pointer;text-decoration:none;}
.k-tile.wide{grid-column:1/-1;min-height:140px;}
.k-tile b{font-family:"Fredoka",var(--mb-ui);font-size:23px;font-weight:700;line-height:1.05;}
.k-tile small{font-size:13.5px;font-weight:600;opacity:.92;}
.k-coral{background:#ff6b6b;}.k-grass{background:#2fb36e;}.k-grape{background:#7c5cff;}.k-sun{background:#ffc83d;color:#2b1d0e;}
.k-panel{margin-top:18px;padding:20px;border-radius:28px;background:#fff;color:#2b1d0e;box-shadow:0 6px 0 rgba(8,48,74,.18);}
.k-panel h2{font-family:"Fredoka",var(--mb-ui);font-size:28px;font-weight:700;margin:10px 0 10px;}
.k-back{border:0;background:#eef7fd;color:#0b2540;border-radius:999px;min-height:44px;padding:0 18px;font:inherit;font-weight:700;font-size:16px;cursor:pointer;}
.k-tell{font-size:21px;line-height:1.5;margin:0 0 16px;}
.k-big{display:flex;align-items:center;justify-content:center;width:100%;min-height:60px;border:0;border-radius:20px;background:#ff6b6b;color:#fff;
  font-family:"Fredoka",var(--mb-ui);font-size:21px;font-weight:700;cursor:pointer;box-shadow:0 4px 0 #d94b4b;}
.k-versegame{font-family:"Fredoka",var(--mb-ui);font-size:26px;line-height:1.5;margin:0 0 6px;}
.k-blank{color:#2fb36e;}
.k-blank.done{color:#2b1d0e;background:#dcf5e6;border-radius:8px;padding:0 4px;}
.k-panel cite{display:block;font-style:normal;font-size:14px;color:#65533f;margin-bottom:14px;}
.k-chipset{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0 0;}
.k-wchip{min-height:52px;padding:0 18px;border:0;border-radius:16px;background:#ffc83d;color:#2b1d0e;font-family:"Fredoka",var(--mb-ui);
  font-size:21px;font-weight:700;cursor:pointer;box-shadow:0 4px 0 #e0a800;}
.k-wchip:disabled{opacity:.3;box-shadow:none;}
.k-wchip.no{animation:k-shake .35s;}
@keyframes k-shake{25%{transform:translateX(-6px);}75%{transform:translateX(6px);}}
.k-yay{font-family:"Fredoka",var(--mb-ui);font-size:26px;font-weight:700;color:#2fb36e;margin:16px 0 0;}
.k-canvas{display:block;width:100%;aspect-ratio:4/3;border-radius:20px;background:#fff;border:3px dashed #cfe9f8;touch-action:none;}
.k-crayons{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin:12px 0;}
.k-crayon{width:44px;height:44px;border-radius:50%;border:3px solid #fff;box-shadow:0 0 0 2px #e6e0d6;cursor:pointer;}
.k-crayon[aria-pressed=true]{box-shadow:0 0 0 3px #2b1d0e;}
.k-clear{margin-left:auto;border:0;background:#f3efe8;color:#2b1d0e;border-radius:999px;min-height:44px;padding:0 16px;font:inherit;font-weight:700;cursor:pointer;}
.k-hold{position:fixed;left:50%;bottom:calc(18px + env(safe-area-inset-bottom,0px));transform:translateX(-50%);z-index:50;overflow:hidden;
  border:0;border-radius:999px;min-height:48px;padding:0 22px;background:#0b2540;color:#fff;font:inherit;font-weight:700;font-size:14.5px;
  white-space:nowrap;cursor:pointer;-webkit-user-select:none;user-select:none;-webkit-touch-callout:none;touch-action:none;}
.k-hold span{position:relative;z-index:1;}
.k-hold::before{content:"";position:absolute;inset:0;width:0;background:#ff6b6b;}
.k-hold.on::before{width:100%;transition:width 3s linear;}
@media (prefers-reduced-motion:reduce){.k-wchip.no{animation:none;}}
""")
