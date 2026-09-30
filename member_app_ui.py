"""
member_app_ui.py — the member app's look ("Broadcast", Kevin 2026-09-30).

The member page (/my, member_portal.py + member_portal_church.py +
member_portal_sermons.py) is one small app on a church's own address:
Home · Sermons · Groups · Me along the bottom. Kevin picked the dark
"Broadcast" direction after walking through his church's current app,
then asked that it not be the same blue for everyone: the ground is
TINTED FROM EACH CHURCH'S BRAND — near-black carrying the brand's hue
(Rivers reads ink-navy, a red church warm black, a green church
green-black), with the brand's own accent on the one main button per
screen. A church with no colour gets a warm neutral.

Series have no uploaded artwork yet, so each gets a generated poster
(brand-derived gradient, a large faded initial, a fine line texture) in
a colour that is stable per series.

Pure functions, no I/O.
"""
from __future__ import annotations

import colorsys
import hashlib
from typing import Any, Dict, Optional, Tuple

from public_form_theme import color, contrast, readable

NEUTRAL_HUE = 30 / 360        # warm, for a church with no colour at all
GOLD = "#F2C77E"

TABS = (
    ("home", "/my", "Home",
     '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>'),
    ("sermons", "/my/sermons", "Sermons",
     '<path d="M2 4h6a4 4 0 0 1 4 4v13a3 3 0 0 0-3-3H2z"/><path d="M22 4h-6a4 4 0 0 0-4 4v13a3 3 0 0 1 3-3h7z"/>'),
    ("groups", "/my/groups", "Groups",
     '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
     '<path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>'),
    ("me", "/my/me", "Me",
     '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>'),
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
    "doc": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h5"/>',
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
    }
    acc = color(theme.get("accent")) or p["tint"]
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
    from html import escape
    t = escape(str(title or ""))
    ghost = escape((str(title or "").strip()[:1] or "").upper())
    tid = f' id="{escape(title_id)}"' if title_id else ""
    play_html = f'<span class="mb-art-play" aria-hidden="true">{icon("play", 18)}</span>' if play else ""
    kick_html = f'<span class="mb-art-kick">{escape(kick)}</span>' if kick else ""
    return (f'<{tag} class="mb-art {cls}" style="{poster_style(key, pal)}"{(" " + attrs) if attrs else ""}>'
            f'<span class="mb-art-ghost" aria-hidden="true">{ghost}</span>{play_html}{kick_html}'
            f'<{title_tag} class="mb-art-title"{tid}>{t}</{title_tag}></{tag}>')


def initials(name: Any) -> str:
    """'Ana Rivers' → AR; 'Rivers of Living Water' → RL (small lowercase
    words like 'of' are skipped)."""
    words = [p for p in str(name or "").split() if p[:1].isalpha()]
    parts = [p for p in words if p[:1].isupper()] or words
    return ("".join(p[0] for p in parts[:2]) or "?").upper()


def nav(active: Optional[str]) -> str:
    items = []
    for key, href, label, paths in TABS:
        cur = ' aria-current="page"' if key == active else ""
        items.append(f'<a class="mb-tab" href="{href}"{cur}><span class="mb-pill"><svg width="22" height="22" '
                     f'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
                     f'stroke-linejoin="round" aria-hidden="true" focusable="false">{paths}</svg></span>{label}</a>')
    return f'<nav class="mb-nav mp-noprint" aria-label="Main">{"".join(items)}</nav>'


GRAIN = ("url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='140' height='140'>"
         "<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2' stitchTiles='stitch'/>"
         "</filter><rect width='140' height='140' filter='url(%23n)'/></svg>\")")


def css(biz: Dict[str, Any], theme: Dict[str, Any]) -> str:
    """The member app's stylesheet. The mp-* classes the older renderers
    use keep working through the same --tokens."""
    p = palette(biz, theme)
    return f""":root{{--surface:{p['ground']};--input-surface:{p['surface2']};--text-primary:{p['text']};--text-secondary:{p['muted']};
--text-muted:{p['dim']};--border:{p['line']};--accent:{p['accent']};--accent-text:{p['on_accent']};--focus:{p['accent']};
--error:{p['error']};--mb-surface:{p['surface']};--mb-surface-2:{p['surface2']};--mb-line:{p['line']};
--mb-soft:{_rgba(p['accent'], .16)};--mb-soft-line:{_rgba(p['accent'], .34)};--mb-nav:{_rgba(p['ground'], .92)};color-scheme:dark;}}
html,body{{margin:0;padding:0;font-family:var(--font-body);color:var(--text-primary);background:var(--surface);min-height:100vh;}}
body{{position:relative;}}
body::before{{content:"";position:absolute;inset:0 0 auto 0;height:420px;pointer-events:none;z-index:0;
  background:radial-gradient(120% 90% at 88% -12%,{_rgba(p['tint'], .55)} 0%,transparent 62%),
             radial-gradient(90% 70% at -12% 8%,{_rgba(p['accent'], .20)} 0%,transparent 58%);}}
body::after{{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;opacity:.06;mix-blend-mode:overlay;background-image:{GRAIN};}}
*{{box-sizing:border-box;}}
a{{color:var(--accent);}}
.mp-shell{{position:relative;z-index:1;max-width:520px;margin:0 auto;padding:16px 20px 40px;}}
.mp-shell.mb-has-nav{{padding-bottom:calc(112px + env(safe-area-inset-bottom,0px));}}
.mb-top{{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:6px;}}
.mb-brand{{display:flex;align-items:center;gap:10px;min-width:0;}}
.mb-mark{{width:34px;height:34px;flex:none;border-radius:10px;display:grid;place-items:center;font-weight:900;font-size:13px;
  background:var(--text-primary);color:var(--surface);overflow:hidden;}}
.mb-mark img{{width:100%;height:100%;object-fit:contain;background:#fff;}}
.mp-church{{font-family:var(--font-heading);font-size:13px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;margin:0;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}}
.mb-avatar{{width:38px;height:38px;flex:none;border-radius:50%;display:grid;place-items:center;font-weight:800;font-size:13px;
  text-decoration:none;color:var(--text-primary);border:1.5px solid {_rgba(p['text'], .3)};background:{_rgba(p['text'], .08)};}}
.mb-date{{font-size:13px;color:var(--text-secondary);margin:22px 0 4px;letter-spacing:.02em;min-height:1em;}}
h1{{font-family:var(--font-heading);font-size:30px;font-weight:800;line-height:1.05;letter-spacing:-.02em;margin:18px 0 8px;text-wrap:balance;}}
.mb-hello{{font-size:34px;margin:0;}}
h2{{font-family:var(--font-heading);font-size:18px;font-weight:800;margin:0 0 8px;}}
p{{line-height:1.55;margin:0 0 12px;}}
.mp-muted{{color:var(--text-secondary);font-size:14px;}}
.mp-card{{background:var(--mb-surface);border:1px solid var(--mb-line);border-radius:18px;padding:16px;margin-bottom:14px;}}
.mp-card>:last-child{{margin-bottom:0;}}
.mp-form{{display:flex;flex-direction:column;gap:10px;}}
label{{font-size:14px;font-weight:600;}}
.mp-input{{width:100%;padding:12px 14px;font-size:16px;border:1px solid var(--border);border-radius:12px;background:var(--input-surface);
  color:var(--text-primary);min-height:48px;font-family:var(--font-body);}}
.mp-code{{letter-spacing:.4em;text-align:center;font-size:24px;font-variant-numeric:tabular-nums;}}
.mp-go{{width:100%;padding:13px 16px;font-size:15px;font-weight:800;border:0;border-radius:14px;background:var(--accent);color:var(--accent-text);
  cursor:pointer;min-height:48px;font-family:var(--font-body);text-align:center;text-decoration:none;display:inline-flex;align-items:center;
  justify-content:center;gap:8px;}}
.mp-go-2{{background:transparent;color:var(--text-primary);border:1px solid var(--border);}}
.mb-soft{{background:var(--mb-soft);color:var(--accent);border:1px solid var(--mb-soft-line);}}
.mp-link{{background:none;border:0;padding:10px 0;min-height:44px;font:inherit;font-size:14px;color:var(--text-secondary);cursor:pointer;
  text-decoration:underline;text-underline-offset:3px;}}
.mb-back{{display:inline-flex;align-items:center;gap:4px;min-height:44px;color:var(--text-secondary);text-decoration:none;font-size:14px;
  margin:6px 0 0;}}
.mp-err{{color:var(--error);font-size:14px;font-weight:600;}}
.mp-flash{{padding:12px 14px;border-radius:14px;background:var(--mb-surface-2);border:1px solid var(--mb-line);margin:14px 0;}}
.mp-ok{{color:var(--text-primary);font-weight:600;font-size:14px;}}
.mp-total{{font-family:var(--font-heading);font-size:40px;font-weight:800;letter-spacing:-.02em;font-variant-numeric:tabular-nums;line-height:1;margin:6px 0 0;}}
.mp-gifts{{list-style:none;margin:8px 0 0;padding:0;}}
.mp-gifts li{{display:flex;justify-content:space-between;gap:12px;padding:10px 0;border-top:1px solid var(--mb-line);font-size:14px;}}
.mp-gifts li span:last-child{{font-variant-numeric:tabular-nums;white-space:nowrap;font-weight:600;}}
.mp-years{{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 12px;}}
.mp-years a{{padding:6px 12px;min-height:36px;border:1px solid var(--border);border-radius:999px;color:var(--text-secondary);text-decoration:none;
  font-size:13px;display:inline-flex;align-items:center;}}
.mp-years a[aria-current]{{background:var(--mb-soft);color:var(--accent);border-color:var(--mb-soft-line);font-weight:800;}}
.mp-row{{display:flex;flex-direction:column;gap:10px;}}
.mp-person{{width:100%;text-align:left;padding:14px 16px;min-height:52px;border:1px solid var(--border);border-radius:14px;
  background:var(--input-surface);color:var(--text-primary);font:inherit;font-size:16px;cursor:pointer;}}
.mp-sect{{font-family:var(--font-body);font-size:11px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:var(--text-muted);
  margin:26px 0 10px;display:flex;justify-content:space-between;align-items:baseline;}}
.mp-sect a{{letter-spacing:0;text-transform:none;font-size:13px;color:var(--text-secondary);text-decoration:none;font-weight:600;}}
.mp-when{{font-size:11px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:var(--accent);margin:0 0 4px;}}
.mp-occ h2,.mp-occ h3{{font-family:var(--font-heading);font-size:18px;font-weight:800;line-height:1.25;margin:0 0 4px;}}
.mp-mine{{font-size:13px;font-weight:700;margin:8px 0 0;color:var(--accent);}}
.mp-actions{{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;align-items:center;}}
.mp-actions:empty{{display:none;}}
.mp-actions form{{display:contents;}}
.mp-actions .mp-go{{width:auto;min-height:44px;padding:0 16px;font-size:14px;border-radius:999px;}}
.mp-serve{{display:flex!important;gap:8px;flex-wrap:wrap;flex:1 1 100%;}}
.mp-serve select{{flex:1 1 160px;min-width:0;min-height:44px;}}
.mp-text{{min-height:140px;resize:vertical;line-height:1.5;}}
.mp-check{{display:flex;gap:10px;align-items:flex-start;font-weight:500;}}
.mp-check input{{width:20px;height:20px;margin:2px 0 0;accent-color:var(--accent);}}
.mp-sr{{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0;}}
.mp-foot{{text-align:center;font-size:12px;color:var(--text-muted);margin-top:32px;padding-top:14px;border-top:1px solid var(--mb-line);}}
.mb-next{{margin:18px 0 0;border-radius:18px;padding:14px 14px 14px 16px;display:flex;align-items:center;gap:14px;text-decoration:none;
  color:var(--text-primary);background:{_rgba(p['surface'], .82)};border:1px solid var(--mb-line);backdrop-filter:blur(8px);}}
.mb-when{{width:50px;flex:none;text-align:center;border-right:1px solid var(--mb-line);padding-right:12px;}}
.mb-when span{{display:block;font-size:11px;font-weight:800;letter-spacing:.1em;color:var(--accent);text-transform:uppercase;}}
.mb-when b{{display:block;font-size:24px;font-weight:800;line-height:1.05;}}
.mb-what{{flex:1;min-width:0;display:flex;flex-direction:column;gap:3px;}}
.mb-what strong{{font-size:16px;}}
.mb-what>span:not(.mb-chip){{font-size:12.5px;color:var(--text-secondary);}}
.mb-what .mb-chip{{margin-top:4px;}}
.mb-chip{{display:inline-flex;align-items:center;gap:5px;font-size:12px;font-weight:800;padding:5px 10px;border-radius:999px;
  background:var(--mb-soft);color:var(--accent);white-space:nowrap;align-self:flex-start;}}
.mb-quick{{display:grid;grid-template-columns:repeat(auto-fit,minmax(64px,1fr));gap:6px;margin:18px 0 0;}}
.mb-quick a{{display:flex;flex-direction:column;align-items:center;gap:7px;text-decoration:none;font-size:12px;font-weight:600;
  color:var(--text-secondary);min-height:44px;}}
.mb-quick a span{{width:56px;height:56px;border-radius:18px;display:grid;place-items:center;background:var(--mb-surface);
  border:1px solid var(--mb-line);color:var(--text-primary);}}
.mb-quick a.mb-main span{{background:var(--accent);color:var(--accent-text);border-color:transparent;}}
.mb-art{{position:relative;display:flex;flex-direction:column;justify-content:flex-end;border-radius:18px;overflow:hidden;aspect-ratio:16/9;
  padding:14px 16px;text-decoration:none;isolation:isolate;}}
.mb-art::before{{content:"";position:absolute;inset:0;z-index:-1;background:repeating-linear-gradient(115deg,rgba(255,255,255,.06) 0 1px,transparent 1px 14px);}}
.mb-art-ghost{{position:absolute;right:-14px;top:-34px;font-family:var(--font-heading);font-size:190px;font-weight:900;line-height:1;opacity:.13;z-index:-1;}}
.mb-art-kick{{font-size:10.5px;font-weight:700;letter-spacing:.2em;text-transform:uppercase;opacity:.88;margin-bottom:6px;}}
.mb-art-title{{font-family:var(--font-heading);font-size:36px;font-weight:900;line-height:.9;letter-spacing:-.02em;text-transform:uppercase;
  overflow-wrap:anywhere;text-shadow:0 2px 24px rgba(0,0,0,.25);margin:0;}}
.mb-art-play{{position:absolute;right:14px;top:14px;width:46px;height:46px;border-radius:50%;display:grid;place-items:center;
  background:rgba(255,255,255,.92);color:#111;}}
.mb-art.mb-tall{{aspect-ratio:3/4;padding:12px;}}
.mb-art.mb-tall .mb-art-title{{font-size:22px;}}
.mb-art.mb-tall .mb-art-ghost{{font-size:150px;}}
.mb-art.mb-band{{aspect-ratio:auto;min-height:96px;border-radius:17px 17px 0 0;margin:-16px -16px 12px;}}
.mb-art.mb-band .mb-art-title{{font-size:22px;}}
.mb-art.mb-band .mb-art-ghost{{font-size:120px;top:-20px;}}
.mb-msg-title{{font-family:var(--font-heading);font-size:18px;font-weight:800;margin:12px 0 3px;line-height:1.2;}}
.mb-msg-title a{{color:inherit;text-decoration:none;}}
.mb-meta{{font-size:13px;color:var(--text-secondary);margin:0;}}
.mb-week{{display:flex;gap:10px;overflow-x:auto;scroll-snap-type:x mandatory;margin:0 -20px;padding:0 20px 4px;scrollbar-width:none;}}
.mb-week::-webkit-scrollbar{{display:none;}}
.mb-wk{{flex:none;width:156px;scroll-snap-align:start;border-radius:16px;padding:12px;background:var(--mb-surface);border:1px solid var(--mb-line);
  display:flex;flex-direction:column;gap:6px;text-decoration:none;color:var(--text-primary);}}
.mb-wk-d{{font-size:11px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:var(--accent);}}
.mb-wk strong{{font-size:14.5px;line-height:1.2;}}
.mb-wk-s{{font-size:12px;color:var(--text-secondary);}}
.mb-shelf{{display:grid;grid-template-columns:1fr 1fr;gap:12px;}}
.mb-list{{list-style:none;margin:0;padding:0;}}
.mb-list li+li{{border-top:1px solid var(--mb-line);}}
.mb-list a{{display:flex;align-items:center;gap:14px;min-height:60px;padding:8px 0;color:var(--text-primary);text-decoration:none;}}
.mb-list .mb-ic{{color:var(--text-muted);flex:none;}}
.mb-list-ic{{width:40px;height:40px;flex:none;border-radius:12px;display:grid;place-items:center;background:var(--mb-surface-2);}}
.mb-list-ic .mb-ic{{color:var(--accent);}}
.mb-list-text{{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}}
.mb-list-text strong{{font-size:15px;}}
.mb-list-text span{{font-size:12px;color:var(--text-secondary);}}
.mb-thumb{{width:64px;height:44px;flex:none;border-radius:10px;display:grid;place-items:center;color:#fff;}}
.mb-player{{margin:0 -20px;}}
.mb-video{{position:relative;width:100%;aspect-ratio:16/9;overflow:hidden;background:#000;}}
.mb-video iframe{{position:absolute;inset:0;width:100%;height:100%;border:0;}}
.mb-player .mb-art{{border-radius:0;aspect-ratio:16/9;}}
.mb-player audio{{width:calc(100% - 40px);margin:12px 20px 0;}}
.mb-acts{{display:flex;gap:8px;margin:16px 0 0;}}
.mb-acts>*{{flex:1;}}
.mb-text{{font-size:15.5px;line-height:1.65;white-space:pre-line;margin:0;color:var(--text-secondary);}}
.mb-q{{border-radius:18px;padding:16px;background:var(--mb-soft);border:1px solid var(--mb-soft-line);margin-top:16px;}}
.mb-q h2{{font-size:15px;}}
.mb-q .mb-text{{color:var(--text-primary);}}
.mb-profile{{display:flex;align-items:center;gap:14px;margin:22px 0 4px;}}
.mb-profile .mb-avatar{{width:60px;height:60px;font-size:20px;background:var(--accent);color:var(--accent-text);border:0;}}
.mb-profile h1{{margin:0;font-size:24px;}}
.mb-bars{{display:flex;align-items:flex-end;gap:5px;height:48px;margin:16px 0 6px;}}
.mb-bars i{{flex:1;border-radius:4px 4px 2px 2px;background:var(--mb-soft-line);min-height:3px;}}
.mb-bars i.mb-on{{background:var(--accent);}}
.mb-months{{display:flex;justify-content:space-between;font-size:10px;color:var(--text-muted);}}
.mb-months span{{flex:1;text-align:center;}}
.mb-give-row{{display:grid;grid-template-columns:1fr auto;gap:8px;margin-top:16px;}}
.mb-give-row .mp-go-2{{width:auto;padding:0 14px;}}
details.mb-each summary{{cursor:pointer;min-height:44px;display:flex;align-items:center;font-size:13px;color:var(--text-secondary);
  list-style:none;margin-top:6px;}}
details.mb-each summary::-webkit-details-marker{{display:none;}}
.mb-nav{{position:fixed;left:0;right:0;bottom:0;z-index:10;background:var(--mb-nav);backdrop-filter:blur(12px);border-top:1px solid var(--mb-line);
  padding:8px 10px calc(10px + env(safe-area-inset-bottom,0px));display:grid;grid-template-columns:repeat(4,minmax(0,1fr));}}
.mb-tab{{min-height:52px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;text-decoration:none;
  color:var(--text-muted);font-size:11px;font-weight:600;}}
.mb-pill{{width:54px;height:30px;border-radius:999px;display:grid;place-items:center;}}
.mb-tab[aria-current]{{color:var(--text-primary);font-weight:800;}}
.mb-tab[aria-current] .mb-pill{{background:var(--mb-soft);color:var(--accent);}}
@media (min-width:600px){{.mb-nav{{max-width:520px;margin:0 auto;border-left:1px solid var(--mb-line);border-right:1px solid var(--mb-line);
  border-radius:18px 18px 0 0;}}}}
.mp-go:focus-visible,.mp-input:focus-visible,.mp-link:focus-visible,.mp-person:focus-visible,.mp-years a:focus-visible,.mb-tab:focus-visible,
.mb-quick a:focus-visible,.mb-list a:focus-visible,.mb-wk:focus-visible,.mb-art:focus-visible,.mb-next:focus-visible,.mb-back:focus-visible,
.mb-avatar:focus-visible,.mb-msg-title a:focus-visible,details.mb-each summary:focus-visible{{outline:2px solid var(--focus);outline-offset:3px;}}
table{{width:100%;border-collapse:collapse;font-size:14px;}}
th,td{{text-align:left;padding:8px 6px;border-bottom:1px solid var(--mb-line);}}
td.n,th.n{{text-align:right;font-variant-numeric:tabular-nums;}}
@media (prefers-reduced-motion:no-preference){{.mb-art,.mb-wk,.mb-quick a span{{transition:transform .15s ease;}}
  .mb-art:active,.mb-wk:active,.mb-quick a:active span{{transform:scale(.98);}}}}
@media print{{.mp-noprint{{display:none!important;}} html,body{{background:#fff;color:#000;}} body::before,body::after{{display:none;}}
  .mp-shell{{max-width:none;padding:0;}} .mp-card{{background:#fff;border-color:#999;}} th,td{{border-color:#999;}} .mp-muted{{color:#333;}}}}"""
