"""site_kit.py — THE KIT: pages assembled from finished sections (2026-11-10, a test).

Kevin, 2026-11-10: a new site costs about $3.34, nearly all of it the builder
writing every page's code from scratch. The hybrid keeps the parts that
understand the owner (the Coach, the Director's blueprint) and replaces the
writing: finished sections, designed once, filled by code with the real facts.
The AI writes only the words, and one custom section where the kit has no piece.

Why this is not the June module path again (docs/REVAMP_TARGET.md demoted those
templates to the emergency fallback): those modules picked from a thin font and
colour library, so every page wore the median. Here the page wears the
blueprint's own palette, type and words, the library's finished objects
(site_objects: letterboard, hours card, dock...) carry the craft, and the
Director still decides everything the July review said a page must decide.

THE RULES THE KIT KEEPS
  * Facts come only from the data: prices, minutes, hours, address, phone,
    people, testimonials and photos are filled by code. The model never
    writes a fact, so it can never invent one.
  * Every section is whole on a phone at 390px with nothing off the side.
    Grids use minmax(0, 1fr); headings wrap; the dock leaves room under it.
  * Content is visible at rest. Nothing waits for a script to appear.
  * A section with no data is left out, never filled with a stand-in.

ONE LAYOUT SO FAR: the Booking desk (site_layouts "booking"). The test decides
whether the rest get built.
"""
from __future__ import annotations

import html as _html
import json
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

import site_objects

KIT_LAYOUTS = ("booking",)

# ─── small helpers ────────────────────────────────────────────────────


def e(text: Any) -> str:
    return _html.escape(str(text or ""), quote=True)


_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_FONT = re.compile(r"^[A-Za-z0-9 ]{2,40}$")


def _hex(value: Any, fallback: str) -> str:
    v = str(value or "").strip()
    return v if _HEX.match(v) else fallback


def _font(value: Any, fallback: str) -> str:
    v = str(value or "").strip()
    return v if _FONT.match(v) else fallback


def _opt(tag: str, cls: str, text: Any) -> str:
    """<tag class="cls">text</tag>, or nothing when there is no text."""
    return f'<{tag} class="{cls}">{e(text)}</{tag}>' if str(text or "").strip() else ""


def _raw(tag: str, cls: str, markup: str, hidden: bool = False) -> str:
    """Like _opt for markup that is already built and escaped."""
    if not str(markup or "").strip():
        return ""
    aria = ' aria-hidden="true"' if hidden else ""
    return f'<{tag} class="{cls}"{aria}>{markup}</{tag}>'


def _money(price: Any) -> str:
    try:
        n = float(price)
    except (TypeError, ValueError):
        return str(price or "").strip()
    return f"${n:,.0f}" if n == int(n) else f"${n:,.2f}"


def _first(name: str) -> str:
    return (str(name or "").split() or [""])[0]


DAYS = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")


def _clock(hhmm: str) -> str:
    h, m = (int(x) for x in hhmm.split(":"))
    suffix = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12}{suffix}" if m == 0 else f"{h12}:{m:02d}{suffix}"


def clean_hours(rows: Any) -> List[Dict[str, Any]]:
    """Validated hours rows: day 0-6, open/close HH:MM or closed. Bad rows drop."""
    out: Dict[int, Dict[str, Any]] = {}
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        try:
            day = int(r.get("day"))
        except (TypeError, ValueError):
            continue
        if not 0 <= day <= 6:
            continue
        if r.get("closed"):
            out[day] = {"day": day, "closed": True}
            continue
        o, c = str(r.get("open") or ""), str(r.get("close") or "")
        if re.match(r"^\d{2}:\d{2}$", o) and re.match(r"^\d{2}:\d{2}$", c) and o < c:
            out[day] = {"day": day, "open": o, "close": c}
    return [out[d] for d in sorted(out, key=lambda d: (d - 1) % 7)]  # Monday first


# ─── the look: the blueprint's palette and type as tokens ─────────────

DEFAULT_TOKENS = {
    "bg": "#121010", "surface": "#1c1816", "deep": "#0f1513", "text": "#ede6da",
    "muted": "#a0978b", "accent": "#d9a35a", "on_accent": "#121010", "second": "#b9bec3",
    "band": "#7e3a2a", "line": "#3a322d",
    "display_font": "Big Shoulders Display", "display_weight": 800, "display_upper": True,
    "body_font": "Work Sans", "label_font": "IBM Plex Mono", "glow": True, "dark": True,
    "script_font": "", "radius": 0, "pill": False,
}


def _lum(hexv: str) -> float:
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hexv[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def ink_for(ground: str, *candidates: str, need: float = 4.5) -> str:
    """The first candidate that reads on this ground, else white or near-black."""
    for c in candidates:
        if c and contrast(c, ground) >= need:
            return c
    return max(("#ffffff", "#111111"), key=lambda c: contrast(c, ground))


def _mix(a: str, b: str, share_b: float) -> str:
    """a with share_b of b mixed in, as #rrggbb."""
    pa = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    pb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * share_b):02x}" for x, y in zip(pa, pb))


def tokens(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    t = dict(DEFAULT_TOKENS)
    t["bg"] = _hex(raw.get("bg"), DEFAULT_TOKENS["bg"])
    t["text"] = _hex(raw.get("text"), DEFAULT_TOKENS["text"] if _lum(t["bg"]) < .2 else "#1a1714")
    # (a missing colour once fell back to the dark look's own, on a light page)
    derived = {"surface": _mix(t["bg"], t["text"], .05), "line": _mix(t["bg"], t["text"], .16),
               "muted": _mix(t["text"], t["bg"], .32), "second": _mix(t["text"], t["bg"], .25),
               "deep": _mix(t["text"], "#000000", .15) if _lum(t["bg"]) > .2 else _mix(t["bg"], "#000000", .35)}
    derived["band"] = derived["deep"]
    for k in ("surface", "deep", "muted", "second", "band", "line"):
        t[k] = _hex(raw.get(k), derived[k])
    t["accent"] = _hex(raw.get("accent"), DEFAULT_TOKENS["accent"])
    t["on_accent"] = _hex(raw.get("on_accent"), t["bg"])
    for k in ("display_font", "body_font", "label_font"):
        t[k] = _font(raw.get(k), DEFAULT_TOKENS[k])
    try:
        t["display_weight"] = max(300, min(900, int(raw.get("display_weight") or 800) // 100 * 100))
    except (TypeError, ValueError):
        pass
    for k in ("display_upper", "glow", "dark", "pill"):
        if isinstance(raw.get(k), bool):
            t[k] = raw[k]
    t["script_font"] = _font(raw.get("script_font"), "") if raw.get("script_font") else ""
    try:
        t["radius"] = max(0, min(32, int(raw.get("radius") or 0)))
    except (TypeError, ValueError):
        t["radius"] = 0
    # (round 1: a light look's dark chapters kept dark text, and its band line
    # vanished) every ground gets an ink that reads on it
    t["on_accent"] = ink_for(t["accent"], t["on_accent"], t["bg"], t["text"])
    t["ink_deep"] = ink_for(t["deep"], t["text"], t["bg"])
    t["second_deep"] = t["second"] if contrast(t["second"], t["deep"]) >= 3 else t["ink_deep"]
    t["ink_band"] = ink_for(t["band"], t["text"], t["bg"])
    t["text"] = ink_for(t["bg"], t["text"])
    t["muted"] = ink_for(t["bg"], t["muted"], t["text"])
    t["second"] = ink_for(t["bg"], t["second"], t["muted"], t["text"])
    return t


def fonts_link(t: Dict[str, Any]) -> str:
    fams = [(t["display_font"], f"wght@{t['display_weight']}"),
            (t["body_font"], "wght@400;500;600"), (t["label_font"], "wght@400;500")]
    if t.get("script_font"):
        fams.append((t["script_font"], ""))
    seen, parts = set(), []
    for name, axis in fams:
        if name in seen:
            continue
        seen.add(name)
        parts.append(f"family={quote_plus(name)}" + (f":{axis}" if axis else ""))
    return ('<link rel="preconnect" href="https://fonts.googleapis.com">'
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            f'<link rel="stylesheet" href="https://fonts.googleapis.com/css2?{"&".join(parts)}&display=swap">')


def root_css(t: Dict[str, Any]) -> str:
    return f""":root{{
  --k-bg:{t['bg']};--k-surface:{t['surface']};--k-deep:{t['deep']};--k-text:{t['text']};
  --k-muted:{t['muted']};--k-accent:{t['accent']};--k-on-accent:{t['on_accent']};
  --k-second:{t['second']};--k-band:{t['band']};--k-line:{t['line']};
  --k-ink-deep:{t['ink_deep']};--k-second-deep:{t['second_deep']};--k-ink-band:{t['ink_band']};
  --k-display:'{t['display_font']}',Impact,'Arial Narrow',sans-serif;--k-body:'{t['body_font']}',system-ui,sans-serif;
  --k-label:'{t['label_font']}',ui-monospace,monospace;--k-dw:{t['display_weight']};
  --k-case:{'uppercase' if t['display_upper'] else 'none'};
  --k-script:'{t.get('script_font') or t['body_font']}',cursive;--k-r:{t.get('radius', 0)}px;
  --k-r2:{min(32, round(t.get('radius', 0) * 1.3))}px;--k-btn-r:{'999px' if t.get('pill') else '2px'};
  --k-lh1:{'.92' if t['display_upper'] else '1.02'};--k-lh2:{'.95' if t['display_upper'] else '1.08'};
  --obj-paper:var(--k-surface);--obj-ink:var(--k-text);--obj-accent:var(--k-accent);
  --obj-line:var(--k-line);--obj-display:var(--k-display);--obj-body:var(--k-body);--obj-label:var(--k-label);
  --sx-bg:var(--k-bg);--sx-surface:var(--k-surface);--sx-text:var(--k-text);--sx-accent:var(--k-accent);
  color-scheme:{'dark' if t['dark'] else 'light'};
}}"""


# The kit's own CSS: written once, for every page in this layout.
BASE_CSS = r"""
*,*::before,*::after{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:84px;-webkit-text-size-adjust:100%}
body{margin:0;background:var(--k-bg);color:var(--k-text);font:400 17px/1.6 var(--k-body);
  overflow-x:hidden;-webkit-font-smoothing:antialiased}
img{display:block;max-width:100%}
a{color:inherit}
:focus-visible{outline:2px solid var(--k-accent);outline-offset:3px}
.k-wrap{width:min(1280px,100%);margin:0 auto;padding:0 clamp(20px,5vw,64px)}
.k-grain{position:fixed;inset:0;pointer-events:none;z-index:60;opacity:.5;
  background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 0.5  0 0 0 0 0.5  0 0 0 0 0.5  0 0 0 .05 0'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>")}
.k-eyebrow{font:500 12.5px/1.4 var(--k-label);letter-spacing:.16em;text-transform:uppercase;color:var(--k-second);margin:0 0 18px}
.k-h1,.k-h2,.k-h3{font-family:var(--k-display);font-weight:var(--k-dw);text-transform:var(--k-case);
  letter-spacing:-.01em;margin:0;overflow-wrap:break-word;text-wrap:balance}
.k-h1{font-size:clamp(2.8rem,6.6vw,6.6rem);line-height:var(--k-lh1)}
.k-h1-tail{display:block;font-size:.42em;line-height:1.08;margin-top:.55em;letter-spacing:0}
.k-h2{font-size:clamp(2.3rem,5.4vw,4.6rem);line-height:var(--k-lh2)}
.k-h3{font-size:clamp(1.6rem,2.4vw,2.1rem);line-height:1}
.k-acc{color:var(--k-accent)}
.k-lead{font-size:clamp(17px,1.35vw,19px);color:var(--k-muted);max-width:38ch;margin:26px 0 0}
.k-intro{color:var(--k-muted);max-width:52ch;margin:0}
.k-btn{display:inline-flex;align-items:center;gap:.6em;font:500 13px/1 var(--k-label);letter-spacing:.14em;
  text-transform:uppercase;text-decoration:none;padding:17px 24px;border-radius:var(--k-btn-r);
  background:var(--k-accent);color:var(--k-on-accent);transition:transform .2s ease,box-shadow .2s ease;white-space:nowrap}
.k-btn:hover{transform:translateY(-1px);box-shadow:0 8px 28px -10px var(--k-accent)}
.k-link{font:500 13px/1 var(--k-label);letter-spacing:.14em;text-transform:uppercase;color:var(--k-second);
  text-decoration:none;padding:17px 4px;background:linear-gradient(currentColor,currentColor) 0 calc(100% - 12px)/0 1px no-repeat;
  transition:background-size .3s ease}
.k-link:hover{background-size:100% 1px}
.k-section{position:relative;padding:clamp(80px,11vw,150px) 0;isolation:isolate}
.k-ghost{position:absolute;z-index:-1;font-family:var(--k-display);font-weight:var(--k-dw);text-transform:uppercase;
  font-size:clamp(9rem,30vw,30rem);line-height:.8;color:var(--k-text);opacity:.045;pointer-events:none;
  user-select:none;white-space:nowrap;top:clamp(40px,6vw,90px)}
.k-ghost.l{left:-.06em}.k-ghost.r{right:-.06em}
.k-rule{height:1px;background:var(--k-second);opacity:.35;position:relative;margin:0}
.k-rule::before,.k-rule::after{content:"";position:absolute;top:-3px;width:7px;height:7px;background:var(--k-second)}
.k-rule::before{left:0}.k-rule::after{right:0}

/* NAV */
.k-nav{position:fixed;inset:0 0 auto;z-index:50;height:68px;display:flex;align-items:center;
  background:color-mix(in srgb,var(--k-bg) 88%,transparent);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);
  border-bottom:1px solid var(--k-line)}
.k-nav .k-wrap{display:flex;align-items:center;justify-content:space-between;gap:24px}
.k-mark{text-decoration:none;display:flex;flex-direction:column;gap:3px;min-width:0}
.k-mark b{font:var(--k-dw) 25px/1 var(--k-display);text-transform:var(--k-case);letter-spacing:-.01em;white-space:nowrap}
.k-mark>span{font:500 10.5px/1 var(--k-label);letter-spacing:.16em;text-transform:uppercase;color:var(--k-second);white-space:nowrap}
.k-links{display:flex;gap:34px;list-style:none;margin:0;padding:0}
.k-links a{text-decoration:none;display:flex;flex-direction:column;align-items:center;gap:4px;
  font:500 12.5px/1 var(--k-label);letter-spacing:.14em;text-transform:uppercase}
.k-links small{font:400 10px/1 var(--k-body);letter-spacing:.04em;text-transform:none;color:var(--k-muted)}
.k-nav-end{display:flex;align-items:center;gap:22px}
.k-tel{font:500 13px/1 var(--k-label);letter-spacing:.06em;color:var(--k-second);text-decoration:none;white-space:nowrap}
.k-nav .k-btn{padding:14px 18px;font-size:12px}

/* HERO */
.k-hero{position:relative;min-height:min(100vh,940px);display:grid;align-items:end;padding:118px 0 clamp(56px,8vw,96px);overflow:hidden}
.k-hero-grid{display:grid;grid-template-columns:minmax(0,7fr) minmax(0,5fr);gap:clamp(24px,4vw,56px);align-items:end}
.k-hero-copy{position:relative;z-index:2}
.k-status{display:flex;align-items:center;gap:10px;font:500 13px/1.4 var(--k-label);letter-spacing:.14em;text-transform:uppercase;margin:26px 0 30px}
.k-status i{width:8px;height:8px;border-radius:50%;background:var(--k-muted);flex:none}
.k-status.open i{background:var(--k-accent);box-shadow:0 0 0 4px color-mix(in srgb,var(--k-accent) 22%,transparent),0 0 16px var(--k-accent)}
.k-ctas{display:flex;flex-wrap:wrap;align-items:center;gap:14px 26px}
.k-hero-photo{position:absolute;top:0;right:0;bottom:0;width:58%;z-index:0}
.k-hero-photo img{width:100%;height:100%;object-fit:cover;filter:saturate(.9) contrast(1.04)}
.k-photos img,.k-person{border-radius:var(--k-r)}
.k-hero-photo::before{content:"";position:absolute;inset:0;z-index:1;
  background:linear-gradient(90deg,var(--k-bg) 0%,color-mix(in srgb,var(--k-bg) 72%,transparent) 18%,color-mix(in srgb,var(--k-bg) 30%,transparent) 42%,transparent 70%),
             linear-gradient(0deg,var(--k-bg) 0%,transparent 26%)}
.k-glow .k-hero-photo::after{content:"";position:absolute;z-index:2;width:72vmin;height:72vmin;top:-14vmin;right:14%;
  background:radial-gradient(circle,color-mix(in srgb,var(--k-accent) 30%,transparent) 0%,color-mix(in srgb,var(--k-band) 16%,transparent) 42%,transparent 70%);
  mix-blend-mode:screen;animation:k-lamp 2.4s ease-out both}
@keyframes k-lamp{from{opacity:0}to{opacity:1}}
.k-cap{position:absolute;z-index:3;right:clamp(20px,5vw,64px);bottom:clamp(64px,8vw,104px);max-width:30ch;text-align:right;
  font:500 11.5px/1.7 var(--k-label);letter-spacing:.14em;text-transform:uppercase;color:var(--k-second)}
.k-hero.k-no-photo .k-hero-grid{grid-template-columns:minmax(0,7fr) minmax(0,5fr);align-items:center}
@media (max-width:1100px){.k-cap{display:none}}
.k-hero.k-no-photo{align-items:center;min-height:0;padding:140px 0 clamp(72px,8vw,104px)}
.k-hero.k-no-photo .k-hero-edge{height:clamp(24px,3.5vw,48px)}
.k-hero.k-no-photo .k-hero-side{position:relative}
.k-glow.k-no-photo .k-hero-side::before{content:"";position:absolute;inset:-30%;z-index:-1;
  background:radial-gradient(circle,color-mix(in srgb,var(--k-accent) 20%,transparent) 0%,transparent 62%);animation:k-lamp 2.4s ease-out both}
.k-hero-edge{position:absolute;left:0;right:0;bottom:-1px;height:clamp(40px,6vw,80px);background:var(--k-surface);
  clip-path:polygon(0 100%,100% 0,100% 100%);z-index:1}

/* THE BOARD + THE DESK */
.k-board{background:linear-gradient(180deg,var(--k-surface),var(--k-bg))}
.k-head{display:grid;grid-template-columns:minmax(0,6fr) minmax(0,5fr);gap:clamp(24px,5vw,80px);align-items:end;margin-bottom:clamp(44px,6vw,80px)}
.k-desk-grid{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,7fr);gap:clamp(28px,4.5vw,64px);align-items:start}
.k-stick{position:sticky;top:96px}
.sxo-board-row span:first-child{min-width:0;overflow-wrap:break-word}
.sxo-board-row.k-board-sub{justify-content:flex-start;padding-left:1.4em;opacity:.8}
.sxo-board-row.k-board-sub span{white-space:normal!important}
.k-stick .sxo{max-width:100%}
.k-board-head .k-intro{margin-top:24px}
.k-note{font:500 12px/1.7 var(--k-label);letter-spacing:.14em;text-transform:uppercase;color:var(--k-second);margin:18px 0 0}
.k-desk{list-style:none;margin:0;padding:0;border-top:1px solid var(--k-line)}
.k-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px 28px;align-items:center;
  padding:28px clamp(0px,1.6vw,26px);border-bottom:1px solid var(--k-line);transition:background .25s ease}
.k-row:hover{background:color-mix(in srgb,var(--k-text) 3%,transparent)}
.k-row-name{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 16px}
.k-row-name .k-h3{font-size:clamp(1.55rem,2.3vw,2rem)}
.k-meta{font:500 13px/1 var(--k-label);letter-spacing:.12em;text-transform:uppercase;color:var(--k-second);white-space:nowrap}
.k-meta b{color:var(--k-accent);font-weight:500}
.k-row p{grid-column:1;margin:4px 0 0;color:var(--k-muted);max-width:54ch}
.k-row .k-btn{grid-column:2;grid-row:1/span 2;padding:15px 20px}

/* WORK */
.k-work{overflow:hidden}
.k-points{list-style:none;margin:30px 0 0;padding:0;max-width:44ch}
.k-points li{display:flex;gap:16px;align-items:baseline;padding:14px 0;border-top:1px solid var(--k-line);font-weight:500}
.k-points li::before{content:"";width:7px;height:7px;flex:none;background:var(--k-second);transform:translateY(-2px)}
.k-photos{display:grid;grid-template-columns:minmax(0,7fr) minmax(0,5fr);gap:clamp(16px,2.4vw,32px);margin-top:clamp(44px,6vw,72px);align-items:start}
.k-photos.one{grid-template-columns:minmax(0,1fr)}
.k-photos figure{margin:0}
.k-photos figure:nth-child(2) img{aspect-ratio:5/8}
.k-photos img{width:100%;aspect-ratio:7/8;object-fit:cover;object-position:50% 25%;border:1px solid var(--k-line)}
.k-photos.one img{aspect-ratio:16/9}
.k-photos figcaption{font:500 11.5px/1.7 var(--k-label);letter-spacing:.14em;text-transform:uppercase;color:var(--k-second);margin-top:14px}

/* BAND */
.k-band{background:var(--k-band);padding:clamp(48px,7vw,88px) 0;text-align:center;position:relative;overflow:hidden}
.k-band p{margin:0 auto;max-width:24ch;font:var(--k-dw) clamp(1.9rem,4.2vw,3.4rem)/1.02 var(--k-display);
  text-transform:var(--k-case);letter-spacing:-.01em;color:var(--k-ink-band);text-wrap:balance}

/* PROOF */
.k-proof-grid{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,7fr);gap:clamp(28px,5vw,88px);align-items:center}
.k-proof .sxo-quote{margin:0;max-width:none}
.k-proof .sxo-quote blockquote p{font-size:clamp(1.5rem,2.5vw,2.25rem);line-height:1.25}

/* TEAM */
.k-team,.k-visit{background:var(--k-deep);color:var(--k-ink-deep);--obj-ink:var(--k-ink-deep)}
.k-team{overflow:hidden}
.k-team .k-eyebrow,.k-visit .k-eyebrow,.k-visit .k-link{color:var(--k-second-deep)}
.k-team .k-lead,.k-visit .k-lead,.k-team .k-person p{color:color-mix(in srgb,var(--k-ink-deep) 70%,var(--k-deep))}
.k-team .k-ghost{color:var(--k-ink-deep)}
.k-visit .sxo-hours{--obj-ink:var(--k-text)}
.k-people{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:clamp(18px,2.4vw,32px);margin-top:clamp(40px,5vw,64px)}
.k-person{border:1px solid color-mix(in srgb,var(--k-ink-deep) 18%,transparent);background:color-mix(in srgb,var(--k-ink-deep) 4%,transparent);padding:clamp(26px,3vw,40px);
  display:flex;flex-direction:column;gap:14px;min-width:0}
.k-person .k-init{font:var(--k-dw) clamp(4rem,7vw,6rem)/.8 var(--k-display);color:var(--k-accent);opacity:.9}
.k-person p{margin:0;color:var(--k-muted)}
.k-person .k-btn{align-self:flex-start;margin-top:10px}

/* VISIT */
.k-visit-grid{display:grid;grid-template-columns:minmax(0,6fr) minmax(0,5fr);gap:clamp(28px,5vw,80px);align-items:start}
.k-visit .sxo-details{margin-top:34px}
.k-visit .sxo-hours{width:100%;max-width:none;margin:0}
.k-visit-grid.solo{grid-template-columns:minmax(0,1fr);max-width:780px}
.k-gather-card td small{display:block;color:var(--k-muted);font-size:14px}
.k-visit .k-ctas{margin-top:34px}
.k-map{font:500 12px/1 var(--k-label);letter-spacing:.14em;text-transform:uppercase;color:var(--k-second)}

/* FOOTER */
.k-foot{border-top:1px solid var(--k-line);padding:56px 0 40px;background:var(--k-bg)}
.k-foot .k-wrap{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:28px;align-items:end}
.k-foot p{margin:10px 0 0;color:var(--k-muted);max-width:44ch}
.k-foot small{grid-column:1/-1;font:500 11px/1.6 var(--k-label);letter-spacing:.12em;text-transform:uppercase;color:var(--k-muted);
  border-top:1px solid var(--k-line);padding-top:22px}
.k-foot nav{display:flex;flex-wrap:wrap;gap:18px 26px}
.k-foot nav a{font:500 12px/1 var(--k-label);letter-spacing:.14em;text-transform:uppercase;text-decoration:none;color:var(--k-second)}

/* PHONE */
@media (max-width:1100px){.k-links{gap:20px}.k-links small{display:none}.k-tel{display:none}}
@media (max-width:860px){
  .k-links{display:none}
}
@media (max-width:760px){
  .k-nav{height:62px}
  .k-mark b{font-size:21px}
  .k-tel{display:none}
  .k-nav .k-btn{padding:12px 14px;font-size:11px;letter-spacing:.1em}
  .k-hero{min-height:0;padding:96px 0 48px;align-items:start}
  .k-hero-grid,.k-hero.k-no-photo .k-hero-grid{grid-template-columns:minmax(0,1fr)}
  .k-hero{display:flex;flex-direction:column}
  .k-hero-photo{position:relative;width:100%;margin-top:26px;aspect-ratio:4/5;order:2}
  .k-hero-photo img{object-position:62% 28%}
  .k-hero-photo::before{background:linear-gradient(180deg,var(--k-bg) 0%,transparent 22%)}
  .k-head,.k-desk-grid,.k-visit-grid,.k-proof-grid{grid-template-columns:minmax(0,1fr)}
  .k-stick{position:static}
  .k-row{grid-template-columns:minmax(0,1fr);padding:24px 0}
  .k-row .k-btn{grid-column:1;grid-row:auto;justify-self:start;margin-top:8px}
  .k-photos{grid-template-columns:minmax(0,1fr)}
  .k-photos img,.k-photos figure:nth-child(2) img{aspect-ratio:4/5}
  .k-ghost{font-size:48vw}
  .k-foot .k-wrap{grid-template-columns:minmax(0,1fr)}
}
.k-dock{display:none}
@media (max-width:760px){
  .k-dock{display:flex;position:fixed;left:10px;right:10px;bottom:calc(10px + env(safe-area-inset-bottom,0px));z-index:55;
    align-items:center;justify-content:space-between;gap:12px;padding:10px 10px 10px 16px;border-radius:14px;
    background:color-mix(in srgb,var(--k-surface) 94%,transparent);border:1px solid var(--k-line);
    backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);box-shadow:0 12px 40px -12px rgba(0,0,0,.5);
    transform:translateY(140%);transition:transform .35s ease}
  .k-dock.up{transform:none}
  .k-dock p{margin:0;display:flex;flex-direction:column;min-width:0;line-height:1.25}
  .k-dock b{font:var(--k-dw) 17px/1.1 var(--k-display);text-transform:var(--k-case);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .k-dock span{font:500 11.5px/1.3 var(--k-label);letter-spacing:.1em;text-transform:uppercase;color:var(--k-second)}
  .k-dock .k-btn{padding:14px 16px;font-size:12px}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
"""

STATUS_JS = r"""
(function(){var k=document.querySelector('.k-dock'),h=document.getElementById('top');if(!k||!h||!('IntersectionObserver' in window)){if(k)k.classList.add('up');return}
var seen={};var ends=[h,document.getElementById('visit'),document.querySelector('.k-foot')].filter(Boolean);
new IntersectionObserver(function(es){es.forEach(function(x){seen[ends.indexOf(x.target)]=x.isIntersecting});
k.classList.toggle('up',!Object.keys(seen).some(function(i){return seen[i]}))},{threshold:0}).observe(h);
var io=new IntersectionObserver(function(es){es.forEach(function(x){seen[ends.indexOf(x.target)]=x.isIntersecting});
k.classList.toggle('up',!Object.keys(seen).some(function(i){return seen[i]}))},{threshold:0});ends.slice(1).forEach(function(n){io.observe(n)})})();
(function(){var el=document.querySelector('[data-k-status]');if(!el)return;var rows;try{rows=JSON.parse(el.getAttribute('data-k-status'))}catch(x){return}
var tz=el.getAttribute('data-tz')||undefined,now=new Date();
try{var p=new Intl.DateTimeFormat('en-US',{timeZone:tz,weekday:'short',hour:'2-digit',minute:'2-digit',hour12:false}).formatToParts(now);
var map={};p.forEach(function(q){map[q.type]=q.value});var day=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].indexOf(map.weekday);var hm=(map.hour==='24'?'00':map.hour)+':'+map.minute}catch(x){return}
var by={};rows.forEach(function(r){by[r.day]=r});
function fmt(t){var h=+t.slice(0,2),m=t.slice(3);var s=h<12?'am':'pm';h=h%12||12;return h+(m==='00'?'':':'+m)+s}
var names=['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];var t=by[day],txt;
if(t&&!t.closed&&hm>=t.open&&hm<t.close){txt='Open now until '+fmt(t.close);el.classList.add('open')}
else{for(var i=0;i<8;i++){var d=(day+i)%7,r=by[d];if(!r||r.closed)continue;if(i===0&&hm>=r.open)continue;
 txt=(i===0?'Closed now. Opens today at ':(i===1?'Closed now. Back tomorrow at ':'Closed today. Back '+names[d]+' at '))+fmt(r.open);break}}
if(txt)el.querySelector('span').textContent=txt})();
"""


# ─── the sections ─────────────────────────────────────────────────────

def _wordmark(main: str) -> str:
    """The name, with an ampersand in the accent when it has one."""
    if "&" in main:
        a, b = main.split("&", 1)
        return e(a.strip()) + ' <span class="k-acc">&amp;</span> ' + e(b.strip())
    return e(main)


_TARGET_ALIASES = {"people": "album", "photos": "album", "gallery": "album", "pastors": "leaders",
                   "leader": "leaders", "about": "story", "schedule": "times", "gather": "times",
                   "prices": "board", "services": "board", "barbers": "team", "contact": "visit",
                   "ministry": "ministries", "calendar": "events", "topic": "topics", "talks": "topics"}


def _target(raw: Any, present: set) -> str:
    t = str(raw or "").strip().lstrip("#").lower()
    t = t if t in present else _TARGET_ALIASES.get(t, t)
    return t if t in present else ""


def _nav_items(d, w) -> List[Dict[str, str]]:
    out = _nav_raw(d, w)
    if sum(1 for n in out if n["sub"]) * 2 < len(out):
        out = [dict(n, sub="") for n in out]
    return out


def _nav_raw(d, w) -> List[Dict[str, str]]:
    out, seen = [], set()
    for n in w.get("nav") or []:
        t = _target(n.get("target"), d["_present"])
        if t and t not in seen:
            seen.add(t)
            out.append({"label": n.get("label") or t.title(), "sub": n.get("sub") or "", "target": t})
    return out


def nav(d, w) -> str:
    links = "".join(
        f'<li><a href="#{e(n["target"])}">{e(n["label"])}'
        f'{f"<small>{e(n["sub"])}</small>" if n["sub"] else ""}</a></li>'
        for n in _nav_items(d, w))
    tel = (f'<a class="k-tel" href="tel:{e(re.sub(r"[^0-9+]", "", d["phone"]))}">{e(d["phone"])}</a>'
           if d.get("phone") else "")
    cta = f'<a class="k-btn" href="{e(d["action_url"])}">{e(w["action_label"])}</a>' if d.get("action_url") else ""
    mark = w.get("wordmark") or {}
    return (f'<header class="k-nav"><div class="k-wrap">'
            f'<a class="k-mark" href="#top"><b>{_wordmark(mark.get("main") or d["name"])}</b>'
            f'{f"<span>{e(mark.get("sub"))}</span>" if mark.get("sub") else ""}</a>'
            f'<nav aria-label="Sections"><ul class="k-links">{links}</ul></nav>'
            f'<div class="k-nav-end">{tel}{cta}</div></div></header>')


def _headline(lines: List[str], accent: str) -> str:
    """Two short lines carry the headline; a third and longer one is its tail,
    set smaller under it (round 1: three big lines ran seven deep at 1440)."""
    out, done = [], False
    tail = lines[2:] if len(lines) >= 3 else []
    lines = lines[:2]
    for line in lines:
        txt = e(line)
        if accent and not done and accent.lower() in line.lower():
            pat = re.compile(re.escape(e(accent)), re.IGNORECASE)
            txt = pat.sub(lambda m: f'<span class="k-acc">{m.group(0)}</span>', txt, count=1)
            done = True
        out.append(txt)
    head = "<br>".join(out)
    if tail:
        head += f'<span class="k-h1-tail">{e(" ".join(tail))}</span>'
    return head


def _status(d) -> str:
    if not d.get("hours_rows"):
        return ""
    fallback = e(d.get("hours_text") or "")
    return (f'<p class="k-status" data-k-status="{e(json.dumps(d["hours_rows"]))}" data-tz="{e(d.get("tz") or "")}">'
            f'<i aria-hidden="true"></i><span>{fallback}</span></p>')


def hero(d, w) -> str:
    h = w.get("hero") or {}
    photo = d["photos"][0] if d["photos"] else None
    lines = [x for x in (h.get("lines") or []) if str(x).strip()][:4] or [d["name"]]
    sub = f'<p class="k-lead">{e(h.get("subhead"))}</p>' if h.get("subhead") else ""
    label = str(h.get("secondary") or "").rstrip(" ↓→>").strip()
    second = (f'<a class="k-link" href="#{e(h.get("secondary_target") or "board")}">{e(label)} &darr;</a>'
              if label else "")
    cta = f'<a class="k-btn" href="{e(d["action_url"])}">{e(w["action_label"])}</a>' if d.get("action_url") else ""
    copy = (f'<div class="k-hero-copy">'
            f'{_opt("p", "k-eyebrow", h.get("eyebrow"))}'
            f'<h1 class="k-h1">{_headline(lines, h.get("accent_word") or "")}</h1>{sub}'
            f'{_status(d)}<div class="k-ctas">{cta}{second}</div></div>')
    glow = " k-glow" if d["tokens"]["glow"] else ""
    if photo:
        return (f'<section class="k-hero{glow}" id="top">'
                f'<div class="k-wrap"><div class="k-hero-grid">{copy}<div></div></div></div>'
                f'<div class="k-hero-photo"><img src="{e(photo["url"])}" alt="{e(photo.get("alt"))}" fetchpriority="high"></div>'
                f'<div class="k-hero-edge" aria-hidden="true"></div></section>')
    side = board_object(d, w) if d.get("board_rows") else ""
    return (f'<section class="k-hero k-no-photo{glow}" id="top"><div class="k-wrap"><div class="k-hero-grid">'
            f'{copy}<div class="k-hero-side">{side}</div></div></div>'
            f'<div class="k-hero-edge" aria-hidden="true"></div></section>')


def _board_title(d, w) -> str:
    t = str((w.get("board") or {}).get("board_title") or "").strip()
    if not t or len(t) > 28 or re.search(r"\b(book|call|order|tap|click)\b", t, re.I):
        return (w.get("wordmark") or {}).get("main") or d["name"]
    return t


def board_object(d, w, split_over: int = 30) -> str:
    b = w.get("board") or {}
    rows = [f'<p class="sxo-board-row sxo-board-title">{e(_board_title(d, w))}</p>',
            '<p class="sxo-board-row sxo-board-gap" aria-hidden="true"></p>']
    for left, right in d["board_rows"][:9]:
        if len(left) + len(right) > split_over:
            rows.append(f'<p class="sxo-board-row"><span>{e(left)}</span></p>')
            rows.append(f'<p class="sxo-board-row k-board-sub"><span>{e(right)}</span></p>')
        else:
            rows.append(f'<p class="sxo-board-row"><span>{e(left)}</span><span>{e(right)}</span></p>')
    extra = [x for x in (b.get("board_extra_rows") or []) if str(x).strip()][:2]
    if extra:
        rows.append('<p class="sxo-board-row sxo-board-gap" aria-hidden="true"></p>')
        rows += [f'<p class="sxo-board-row sxo-board-title">{e(x)}</p>' for x in extra]
    return ('<div class="sxo sxo-board" data-sx-object="letterboard"><div class="sxo-board-felt">'
            + "".join(rows) + "</div></div>")


def hours_object(d, w) -> str:
    rows = {r["day"]: r for r in d["hours_rows"]}
    trs = []
    for day in (1, 2, 3, 4, 5, 6, 0):
        r = rows.get(day)
        if not r or r.get("closed"):
            trs.append(f'<tr data-day="{day}" data-closed><th scope="row">{DAYS[day]}</th><td>Closed</td></tr>')
        else:
            trs.append(f'<tr data-day="{day}" data-open="{r["open"]}" data-close="{r["close"]}">'
                       f'<th scope="row">{DAYS[day]}</th><td>{_clock(r["open"])} to {_clock(r["close"])}</td></tr>')
    label = e((w.get("visit") or {}).get("hours_label") or "Hours")
    return (f'<div class="sxo sxo-hours sxo-paper" data-sx-object="hours-card" data-tz="{e(d.get("tz") or "")}">'
            f'<p class="sxo-hours-head"><span class="sxo-label">{label}</span>'
            f'<span class="sxo-hours-now" hidden><i aria-hidden="true"></i><span></span></span></p>'
            f'<table class="sxo-hours-table"><caption class="sxo-sr">{label}, by day</caption><tbody>'
            + "".join(trs) + "</tbody></table></div>")


def board(d, w) -> str:
    b = w.get("board") or {}
    if not d["desk"]:
        return ""
    side = board_object(d, w) if d["photos"] and d.get("board_rows") else ""
    note = f'<p class="k-note">{e(b.get("note"))}</p>' if b.get("note") else ""
    rows = []
    for o in d["desk"]:
        meta = " &middot; ".join(x for x in (f"<b>{e(o['price'])}</b>" if o.get("price") else "",
                                             e(o["minutes"]) if o.get("minutes") else "") if x)
        btn = (f'<a class="k-btn" href="{e(o["book_url"])}" aria-label="{e(w["row_label"])}: {e(o["name"])}">'
               f'{e(w["row_label"])} &rarr;</a>' if o.get("book_url") else "")
        rows.append(f'<li class="k-row"><div class="k-row-name"><h3 class="k-h3">{e(o["name"])}</h3>'
                    f'{_raw("span", "k-meta", meta)}</div>'
                    f'{f"<p>{e(o["description"])}</p>" if o.get("description") else ""}{btn}</li>')
    head = (f'{_opt("p", "k-eyebrow", b.get("eyebrow"))}'
            f'<h2 class="k-h2">{e(b.get("headline") or "Prices")}</h2>')
    desk = f'<ul class="k-desk">{"".join(rows)}</ul>'
    if side:
        body = (f'<div class="k-head"><div>{head}</div>{_opt("p", "k-intro", b.get("intro"))}</div>'
                f'<div class="k-desk-grid"><div class="k-stick">{side}{note}</div>{desk}</div>')
    else:  # no board beside the desk: the heading holds the left column
        body = (f'<div class="k-desk-grid"><div class="k-stick k-board-head">{head}'
                f'{_opt("p", "k-intro", b.get("intro"))}{note}</div>{desk}</div>')
    return f'<section class="k-section k-board" id="board"><div class="k-wrap">{body}</div></section>'


def work(d, w) -> str:
    if not d["photos"]:
        return ""
    k = w.get("work") or {}
    pics = d["photos"][1:3] if len(d["photos"]) > 2 else d["photos"][:2]
    figs = "".join(f'<figure><img src="{e(p["url"])}" alt="{e(p.get("alt"))}" loading="lazy">'
                   f'{f"<figcaption>{e(p.get("caption"))}</figcaption>" if p.get("caption") else ""}</figure>'
                   for p in pics)
    points = "".join(f"<li>{e(s)}</li>" for s in (k.get("statements") or [])[:3] if str(s).strip())
    ghost = f'<span class="k-ghost r" aria-hidden="true">{e(k.get("ghost"))}</span>' if k.get("ghost") else ""
    return (f'<section class="k-section k-work" id="work">{ghost}<div class="k-wrap">'
            f'{_opt("p", "k-eyebrow", k.get("eyebrow"))}'
            f'<h2 class="k-h2">{e(k.get("headline") or "The work")}</h2>'
            f'{_raw("ul", "k-points", points)}'
            f'<div class="k-photos{" one" if len(pics) == 1 else ""}">{figs}</div></div></section>')


def band(d, w) -> str:
    line = str(w.get("band") or "").strip()
    return f'<div class="k-band"><p>{e(line)}</p></div>' if line else ""


def proof(d, w) -> str:
    if not d["quotes"]:
        return ""
    p = w.get("proof") or {}
    q = d["quotes"][0]
    return (f'<section class="k-section k-proof" id="proof"><div class="k-wrap"><div class="k-proof-grid"><div>'
            f'{_opt("p", "k-eyebrow", p.get("eyebrow"))}'
            f'{_opt("h2", "k-h2", p.get("headline"))}</div>'
            f'<figure class="sxo sxo-quote" data-sx-object="pull-quote"><span class="sxo-quote-mark" aria-hidden="true">&ldquo;</span>'
            f'<blockquote><p>{e(q["quote"])}</p></blockquote><figcaption><b>{e(q["name"])}</b>'
            f'{_opt("span", "sxo-label", q.get("role"))}</figcaption></figure>'
            f'</div></div></section>')


def team(d, w) -> str:
    if len(d["people"]) < 2:
        return ""
    t = w.get("team") or {}
    cards = []
    for person in d["people"][:4]:
        label = str(t.get("book_label") or "").replace("{first}", _first(person["name"]))
        btn = (f'<a class="k-btn" href="{e(d["booking_url"])}">{e(label)}</a>'
               if d.get("booking_url") and label else "")
        cards.append(f'<article class="k-person"><span class="k-init" aria-hidden="true">{e(person["name"][:1])}</span>'
                     f'<h3 class="k-h3">{e(person["name"])}</h3><p>{e(person.get("role"))}</p>{btn}</article>')
    ghost = f'<span class="k-ghost r" aria-hidden="true">{e(t.get("ghost"))}</span>' if t.get("ghost") else ""
    return (f'<section class="k-section k-team" id="team">{ghost}<div class="k-wrap">'
            f'{_opt("p", "k-eyebrow", t.get("eyebrow"))}'
            f'<h2 class="k-h2">{e(t.get("headline") or "The team")}</h2>'
            f'<div class="k-people">{"".join(cards)}</div></div></section>')


def visit(d, w) -> str:
    v = w.get("visit") or {}
    rows = []
    if d.get("address"):
        rows.append(f'<div><dt class="sxo-label">Where</dt><dd><span>{e(d["address"])}</span>'
                    f'<button type="button" class="sxo-details-copy" data-copy="{e(d["address"])}">Copy</button></dd></div>')
    if d.get("phone"):
        rows.append(f'<div><dt class="sxo-label">Call</dt><dd><a href="tel:{e(re.sub(r"[^0-9+]", "", d["phone"]))}">'
                    f'{e(d["phone"])}</a></dd></div>')
    if d.get("email"):
        rows.append(f'<div><dt class="sxo-label">Write</dt><dd><a href="mailto:{e(d["email"])}">{e(d["email"])}</a></dd></div>')
    if v.get("extra_label") and v.get("extra"):
        rows.append(f'<div><dt class="sxo-label">{e(v["extra_label"])}</dt><dd>{e(v["extra"])}</dd></div>')
    if not rows and not d.get("hours_rows"):
        return ""
    details = f'<dl class="sxo sxo-details" data-sx-object="visit-details">{"".join(rows)}</dl>' if rows else ""
    mapl = (f'<a class="k-link k-map" href="https://maps.google.com/?q={quote_plus(d["address"])}" '
            f'rel="noopener" target="_blank">Directions &rarr;</a>' if d.get("address") else "")
    cta = f'<a class="k-btn" href="{e(d["action_url"])}">{e(w["action_label"])}</a>' if d.get("action_url") else ""
    side = hours_object(d, w) if d.get("hours_rows") else gatherings_card(d, w)
    return (f'<section class="k-section k-visit" id="visit"><div class="k-wrap"><div class="k-visit-grid{"" if side else " solo"}"><div>'
            f'{_opt("p", "k-eyebrow", v.get("eyebrow"))}'
            f'<h2 class="k-h2">{e(v.get("headline") or "Visit")}</h2>'
            f'{_opt("p", "k-lead", v.get("intro"))}'
            f'{details}<div class="k-ctas">{cta}{mapl}</div></div><div>{side}</div></div></div></section>')


def gatherings_card(d, w) -> str:
    """When they gather, on the visit section's side, for a church with no opening hours."""
    if not d.get("gatherings"):
        return ""
    label = e((w.get("visit") or {}).get("hours_label") or "When we gather")
    rows = "".join(f'<tr><th scope="row">{e(g["day_label"])}s</th><td>{e(g["time_label"])}'
                   f'<small>{e(g["label"])}</small></td></tr>' for g in d["gatherings"])
    return (f'<div class="sxo sxo-hours sxo-paper k-gather-card" data-sx-object="hours-card">'
            f'<p class="sxo-hours-head"><span class="sxo-label">{label}</span></p>'
            f'<table class="sxo-hours-table"><caption class="sxo-sr">{label}</caption><tbody>{rows}</tbody></table></div>')


def footer(d, w) -> str:
    f = w.get("footer") or {}
    mark = (w.get("wordmark") or {}).get("main") or d["name"]
    links = "".join(f'<a href="#{e(n["target"])}">{e(n["label"])}</a>' for n in _nav_items(d, w))
    return (f'<footer class="k-foot"><div class="k-wrap"><div><span class="k-mark"><b>{_wordmark(mark)}</b></span>'
            f'{f"<p>{e(f.get("line"))}</p>" if f.get("line") else ""}</div><nav aria-label="Footer">{links}</nav>'
            f'<small>&copy; {e(d.get("year") or "")} {e(d["name"])} &middot; Made with the Solutionist System</small>'
            f'</div></footer>')


def dock(d, w) -> str:
    """The phone's one action, risen only once the hero is gone (round 1: the
    library dock rose at 60% of a screen, over a tall phone hero's headline).
    Its line is a fact: the lowest price, else the hours."""
    if not d.get("action_url"):
        return ""
    k = w.get("dock") or {}
    prices = []
    for o in d["desk"]:
        try:
            prices.append(float(str(o.get("price") or "").replace("$", "").replace(",", "")))
        except ValueError:
            pass
    if d.get("gatherings"):
        g = d["gatherings"][0]
        fact = f'{g["day_label"]}s {g["time_label"]}'
    elif prices:
        fact = f"From {_money(min(prices))}"
    else:
        fact = (d.get("hours_text") or "")[:48]
    mark = (w.get("wordmark") or {}).get("main") or d["name"]
    return (f'<div class="k-dock" aria-label="{e(w["action_label"])}"><p><b>{e(mark)}</b>'
            f'{_opt("span", "", fact)}</p><a class="k-btn" href="{e(d["action_url"])}">'
            f'{e(k.get("cta") or w["action_label"])}</a></div>')


SECTIONS = (("hero", hero), ("board", board), ("work", work), ("band", band), ("proof", proof),
            ("team", team), ("visit", visit))


# ─── the facts, from the data only ────────────────────────────────────

def facts(fx: Dict[str, Any], w: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the page states as fact, read from the business's data. The
    words sheet (w) may add captions to real photos and the hours rows the data
    states in words; it can't add a price, a person or a quote."""
    biz = fx.get("business") or {}
    contact = fx.get("contact") or {}
    dossier = fx.get("discovery_dossier") or {}
    truth = dossier.get("truth") if isinstance(dossier.get("truth"), dict) else {}
    booking = str(fx.get("booking_url") or "").strip()
    caps = (w.get("work") or {}).get("captions") or {}
    hero_cap = (w.get("hero") or {}).get("caption") or ""
    photos = []
    for i, g in enumerate(fx.get("gallery") or []):
        if isinstance(g, dict) and str(g.get("url") or "").startswith("https://"):
            photos.append({"url": g["url"], "alt": g.get("alt") or "",
                           "caption": (hero_cap if i == 0 else "") or caps.get(g["url"]) or ""})
    if len(photos) > 1:  # the work section shows the photos under their own captions
        photos[0] = dict(photos[0])
    desk = []
    for o in fx.get("offerings") or []:
        if not isinstance(o, dict) or not str(o.get("name") or "").strip():
            continue
        mins = o.get("duration_min")
        desk.append({"name": o["name"].strip(), "price": _money(o.get("price")) if o.get("price") not in (None, "") else "",
                     "minutes": f"{int(mins)} min" if isinstance(mins, (int, float)) and mins else "",
                     "description": str(o.get("description") or "").strip(), "book_url": booking})
    # The letterboard carries the menu they told the Coach (name and price),
    # when there is one; otherwise the bookable services with their minutes.
    menu = [m for m in (truth.get("offers") if isinstance(truth.get("offers"), list) else [])
            if isinstance(m, dict) and m.get("name") and m.get("price")]
    asked = [r for r in ((w.get("board") or {}).get("rows") or []) if isinstance(r, list) and len(r) == 2]
    if asked and rows_are_facts(asked, fact_records(fx)):
        # whole, never cut: "1200 E 6" for "1200 E 6TH ST" is a wrong address
        board_rows = [(str(a).upper(), str(b).upper()) for a, b in asked[:9]
                      if len(str(a)) + len(str(b)) <= 90]
    elif menu:
        board_rows = [(str(m["name"]).upper(), str(m["price"]).upper()) for m in menu]
    else:
        board_rows = [(o["name"].upper(), " · ".join(x for x in (o["price"], o["minutes"].upper()) if x))
                      for o in desk]
    team_rows = ((dossier.get("identity") or {}).get("team")) or []
    people = [{"name": p["name"], "role": p.get("role") or ""} for p in team_rows
              if isinstance(p, dict) and str(p.get("name") or "").strip()]
    quotes = [{"quote": t["quote"], "name": t.get("name") or "", "role": t.get("role") or ""}
              for t in fx.get("testimonials") or [] if isinstance(t, dict) and t.get("quote")]
    action = booking or (w.get("action_url") if str(w.get("action_url") or "").startswith(("https://", "#", "tel:", "mailto:")) else "")
    truth_hours = truth.get("hours")
    truth_hours = truth_hours.get("value") if isinstance(truth_hours, dict) else truth_hours
    records = fact_records(fx)
    leaders = [{"name": p["name"], "role": p.get("role") or ""} for p in team_rows
               if isinstance(p, dict) and str(p.get("name") or "").strip()]
    if not leaders and fx.get("practitioner_name"):
        leaders = [{"name": fx["practitioner_name"], "role": ""}]
    address = contact.get("address") or ""
    return {
        "gatherings": clean_gatherings(w.get("gatherings"), records),
        "leaders": leaders,
        "ministries": [m for m in (fx.get("ministries") or []) if isinstance(m, dict) and m.get("name")],
        "events": [x for x in (fx.get("events") or []) if isinstance(x, dict) and x.get("title")],
        "photo_urls": {ph["url"] for ph in photos},
        "map_url": f"https://maps.google.com/?q={quote_plus(address)}" if address else "",
        "name": biz.get("name") or "", "type": biz.get("type") or "",
        "phone": contact.get("phone") or "", "email": contact.get("email") or "",
        "address": contact.get("address") or "",
        "hours_text": contact.get("hours") or truth_hours or "",
        "hours_rows": clean_hours(w.get("hours_rows")), "tz": str(w.get("tz") or ""),
        "booking_url": booking, "action_url": action, "photos": photos, "desk": desk,
        "board_rows": board_rows, "people": people, "quotes": quotes,
        "year": str(fx.get("year") or "2026"), "tokens": tokens(w.get("tokens")),
    }


def fact_records(fx: Dict[str, Any]) -> List[str]:
    """The data as separate records, so a number can only vouch for its own row:
    one service with its price and minutes, one thing they told the Coach they
    sell, one sentence of where they'll be, one stretch of hours."""
    out: List[str] = []
    for o in fx.get("offerings") or []:
        if isinstance(o, dict):
            out.append(" ".join(str(o.get(k) or "") for k in ("name", "price", "duration_min", "description")))
    dossier = fx.get("discovery_dossier") or {}
    truth = dossier.get("truth") if isinstance(dossier.get("truth"), dict) else {}
    for m in truth.get("offers") or []:
        if isinstance(m, dict):
            out.append(f"{m.get('name') or ''} {m.get('price') or ''}")
    th = truth.get("hours")
    th = th.get("value") if isinstance(th, dict) else th
    contact = fx.get("contact") or {}
    for text in (th, contact.get("hours")):
        out += [x for x in re.split(r"\.\s+|;\s*|,\s*(?=(?:mon|tue|wed|thu|fri|sat|sun|closed))",
                                    str(text or ""), flags=re.I) if x.strip()]
    out += [str(contact.get(k) or "") for k in ("address", "phone", "email") if contact.get(k)]
    for p in ((dossier.get("identity") or {}).get("team")) or []:
        if isinstance(p, dict):
            out.append(f"{p.get('name') or ''} {p.get('role') or ''}")
    for x in fx.get("events") or []:
        if isinstance(x, dict):
            out.append(" ".join(str(x.get(k) or "") for k in ("title", "date", "time", "place", "note")))
    for m in fx.get("ministries") or []:
        if isinstance(m, dict):
            out.append(" ".join(str(m.get(k) or "") for k in ("name", "when", "who", "description")))
    return [r for r in out if r.strip()]


_GATHER_WORDS = {"service", "services", "worship", "gathering", "study", "bible", "prayer", "class", "classes",
                 "meeting", "night", "morning", "evening", "sunday", "midweek", "practice", "open"}


def clean_gatherings(rows: Any, records: List[str]) -> List[Dict[str, Any]]:
    """Weekly gatherings, kept only when one record of the data holds the day and
    the hour together ("Sundays 11am"), and the label's words are the data's own
    or plain words for a gathering. Sunday first, then the week in order."""
    out = []
    low = [r.lower() for r in records]
    every = " ".join(low)
    for g in rows if isinstance(rows, list) else []:
        if not isinstance(g, dict):
            continue
        try:
            day = int(g.get("day"))
        except (TypeError, ValueError):
            continue
        t = str(g.get("time") or "")
        if not (0 <= day <= 6 and re.match(r"^\d{2}:\d{2}$", t)):
            continue
        h = int(t[:2])
        h12 = str(h % 12 or 12)
        name = DAYS[day].lower()
        if not any((name in r or name[:3] in r) and re.search(rf"(?<!\d){h12}(?!\d)", r) for r in low):
            continue
        label = " ".join(str(g.get("label") or "").split())[:60]
        words = re.findall(r"[a-z]{4,}", label.lower())
        if words and sum(1 for x in words if x in every or x in _GATHER_WORDS) < len(words):
            label = ""
        out.append({"day": day, "time": t, "label": label or "Gathering", "day_label": DAYS[day],
                    "time_label": _clock(t)})
    seen, uniq = set(), []
    for g in sorted(out, key=lambda g: (g["day"], g["time"])):
        if (g["day"], g["time"]) not in seen:
            seen.add((g["day"], g["time"]))
            uniq.append(g)
    return uniq[:6]


def rows_are_facts(rows: List[List[Any]], data: Any) -> bool:
    """The blueprint may choose what the board shows, never what it says: most of
    a row's words appear in the data, and one record of the data holds the row's
    name and every number in it ("Classic Cut $9" fails when 9 is only in the
    hours, and so does a real price under the wrong service)."""
    records = data if isinstance(data, list) else re.split(r"(?<=\})|\.\s+|\n", str(data or ""))
    records = [r.lower() for r in records if str(r).strip()]
    every = " ".join(records)
    for cells in rows:
        left = str(cells[0]).lower()
        text = " ".join(str(c) for c in cells).lower()
        words = [x for x in re.findall(r"[a-z]{4,}", text) if x not in ("from", "with", "each", "until")]
        if words and sum(1 for x in words if x in every) < 0.75 * len(words):
            return False
        nums = re.findall(r"\d+", text)
        if not nums:
            continue
        key = next(iter(re.findall(r"[a-z]{3,}", left)), "")
        if not any((not key or key in r) and all(re.search(rf"(?<!\d){n}(?!\d)", r) for n in nums)
                   for r in records):
            return False
    return True


# ─── the page ─────────────────────────────────────────────────────────

_CUSTOM_BAD = re.compile(r"<\s*(script|iframe|object|embed|link|meta|base|form)\b|\bon[a-z]+\s*=|javascript:|@import|url\(\s*['\"]?https?:", re.I)


def custom_ok(html: str, css: str) -> Tuple[bool, str]:
    """A custom section may carry no script, no outside file and no handler,
    and its styles must stay inside its own class."""
    if _CUSTOM_BAD.search(html or "") or _CUSTOM_BAD.search(css or ""):
        return False, "carries a script, a handler, a form or an outside file"
    for sel in re.findall(r"(^|})\s*([^{}@]+)\{", css or ""):
        for part in sel[1].split(","):
            part = part.strip()
            if part and not part.startswith(".k-custom") and not re.match(r"^(from|to|\d+%)$", part):
                return False, f"a style reaches outside the section: {part[:60]}"
    return True, ""


def layout_sections(layout: str) -> Tuple[List[Tuple[str, Any]], Any, str]:
    """(sections, footer, extra css) for a kit layout."""
    if layout == "booking":
        return list(SECTIONS), footer, ""
    import site_kit_church as church
    return church.LAYOUTS[layout], church.FOOTERS[layout], church.CSS


def kit_layout(spec: str, fx: Optional[Dict[str, Any]] = None) -> str:
    """The layout the blueprint decided, when the kit has it; '' when it doesn't."""
    m = re.search(r"^\s*LAYOUT:\s*([A-Za-z -]+?)(?:\s*[-.(:,]|$)", spec or "", re.M)
    raw = m.group(1) if m else ""
    if not raw and fx:
        lay = (((fx.get("discovery_dossier") or {}).get("taste") or {}).get("layout")) or {}
        raw = lay.get("value") if isinstance(lay, dict) else str(lay or "")
    try:
        import site_layouts
        key = site_layouts.normalize(raw) or ""
    except Exception:
        key = str(raw or "").strip().lower()
    return key if key in kit_layouts() else ""


def kit_layouts() -> Tuple[str, ...]:
    import site_kit_church as church
    return ("booking",) + tuple(church.LAYOUTS)


def assemble(fx: Dict[str, Any], w: Dict[str, Any], custom: Optional[List[Dict[str, str]]] = None,
             layout: Optional[str] = None) -> str:
    d = facts(fx, w)
    w = dict(w)
    layout = layout or str(w.get("layout") or "") or "booking"
    if layout not in kit_layouts():
        layout = "booking"
    if d.get("booking_url"):
        default_label = "Book now"
    elif d.get("gatherings"):
        default_label = "Plan a visit"
    else:
        default_label = "Get in touch"
    w.setdefault("action_label", default_label)
    if not d.get("action_url") and d.get("gatherings"):
        d["action_url"] = "#visit"
    w.setdefault("row_label", "Book")
    sections, foot, extra_css = layout_sections(layout)
    order = [k for k, _ in sections]
    built = {k: fn for k, fn in sections}
    # which sections will exist, so nav links never point at nothing
    d["_present"] = set()
    parts: Dict[str, str] = {}
    for key in order:
        parts[key] = built[key](d, w) if key != "hero" else ""
        if parts[key]:
            d["_present"].add(key)
    customs = []
    for c in custom or []:
        ok, why = custom_ok(c.get("html", ""), c.get("css", ""))
        if ok and c.get("html"):
            customs.append(c)
            d["_present"].add(c.get("id") or "custom")
    parts["hero"] = built["hero"](d, w)
    body = []
    for key in order:
        if parts.get(key):
            body.append(parts[key])
        for c in customs:
            if c.get("after") == key:
                body.append(c["html"])
    page_css = root_css(d["tokens"]) + BASE_CSS + extra_css + "".join(c.get("css", "") for c in customs)
    title = f"{d['name']} | {(w.get('hero') or {}).get('title_tail') or d['type'].title()}"
    desc = (w.get("hero") or {}).get("subhead") or ""
    doc = (f'<!doctype html><html lang="{e(w.get("lang") or "en")}"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width,initial-scale=1">'
           f'<title>{e(title)}</title><meta name="description" content="{e(desc)}">'
           f'{fonts_link(d["tokens"])}<style>{page_css}</style></head>'
           f'<body><div class="k-grain" aria-hidden="true"></div>{nav(d, w)}<main>{"".join(body)}</main>'
           f'{foot(d, w)}{dock(d, w)}<script>{STATUS_JS}</script></body></html>')
    return site_objects.inject_library(doc)


# ─── the words: one cheap call turns the blueprint into the sheet ──────

WORDS_SYSTEM = """You fill in a website kit's words sheet from a finished design blueprint.

The kit is a set of finished, designed sections for the BOOKING DESK layout: a fixed
nav, a hero, the board + desk (the price list, every service bookable), the work
(photos), a one-line band, a testimonial, the team, the visit section, a footer and a
phone dock. Code fills every FACT from the business's data: prices, minutes, hours,
address, phone, people, quotes, photos. You write only the WORDS around them, taken
from the blueprint as closely as you can, and the look's tokens.

Rules:
- Use the blueprint's own words wherever it gives them (headlines, eyebrows, captions,
  button labels). Keep its voice. Never add a fact the blueprint or the data doesn't
  hold: no prices, numbers, years, names or claims of your own.
- hours_rows: turn the HOURS line from the data into rows. day 0 is Sunday to 6
  Saturday; open/close are 24-hour "HH:MM"; a closed day is {"day": n, "closed": true}.
  Leave the list empty when the data gives no clock hours.
- tz: an IANA timezone for the business's city when the address makes it plain, else "".
- tokens: the blueprint's palette and type. bg is the page ground, surface the raised
  ground, deep the darkest chapter ground, text the main ink, muted the secondary ink,
  accent THE accent, on_accent the ink on an accent button, second the secondary
  citizen (labels, rules), band the punctuation-band colour, line the hairline colour.
  All "#rrggbb". Fonts are Google Fonts family names. dark is true for a dark ground.
- hero lines: the headline as TWO short lines (about 16 characters each at most), plus
  an optional third, longer line the kit sets smaller beneath them.
- board: the felt letterboard. board_title is its header (the business name, "Menu",
  "This week"), never a call to action. rows: when the blueprint puts something on the
  board other than the price list (this week's stops, today's specials), give its rows
  as [left, right] pairs copied from THE DATA, word for word; otherwise leave rows empty
  and the kit posts the prices.
- What the kit already has: the letterboard (any short rows of facts), the hours card
  (days and times), the desk (every bookable service with price and minutes), a
  testimonial, the team, visit details (address, phone, email, one extra line), the
  band. It has NO menu-card section, no map and no timeline.
- custom: list ONLY a section the blueprint calls for that none of those can carry. For
  each give an id (lowercase letters), where it goes ("after":
  hero|board|work|band|proof|team|visit), and a brief: what it must show, and the data
  it shows, quoted from the data. At most one. Most pages need none.

Reply with ONLY the JSON object, no prose, no code fence."""

WORDS_SHAPE = {
    "lang": "en", "tz": "", "hours_rows": [], "action_label": "", "row_label": "",
    "tokens": {"bg": "", "surface": "", "deep": "", "text": "", "muted": "", "accent": "", "on_accent": "",
               "second": "", "band": "", "line": "", "display_font": "", "display_weight": 800,
               "display_upper": True, "body_font": "", "label_font": "", "glow": True, "dark": True},
    "wordmark": {"main": "", "sub": ""},
    "nav": [{"label": "", "sub": "", "target": "board|work|proof|team|visit|<custom id>"}],
    "hero": {"eyebrow": "", "lines": ["", ""], "accent_word": "", "subhead": "", "secondary": "",
             "secondary_target": "board", "caption": "", "title_tail": ""},
    "board": {"eyebrow": "", "headline": "", "intro": "", "board_title": "", "rows": [["", ""]],
              "board_extra_rows": [""], "note": ""},
    "work": {"eyebrow": "", "headline": "", "statements": ["", "", ""], "ghost": "", "captions": {"<photo url>": ""}},
    "band": "",
    "proof": {"eyebrow": "", "headline": ""},
    "team": {"eyebrow": "", "headline": "", "ghost": "", "book_label": "Book with {first}"},
    "visit": {"eyebrow": "", "headline": "", "intro": "", "hours_label": "", "extra_label": "", "extra": ""},
    "footer": {"line": ""},
    "dock": {"cta": ""},
    "custom": [{"id": "", "after": "", "brief": ""}],
}


LAYOUT_SECTIONS = {
    "booking": "a fixed nav, a hero with one photo, the board + desk (the price list, every service "
               "bookable), the work (photos), a one-line band, a testimonial, the team, the visit section",
    "poster": "a fixed nav, a POSTER hero (the owner's own three or four short lines at poster size, up to "
              "two of their photos set inside the words, the when-and-where card beside the subhead), the "
              "weekly gatherings strip, a band of the owner's own phrases drifting by, an album of their "
              "photos, the leaders, the story with polaroids, a testimonial, a closing ceremony band (one "
              "line, one underlined word), the visit section with first-time steps",
    "bulletin": "a fixed nav, a BULLETIN hero (headline beside this week's gatherings on a felt board, one "
                "wide photo under it), the gatherings strip, events, ministries, the leaders, the album, a "
                "testimonial, a closing ceremony band, the visit section with first-time steps",
    "magazine": "a fixed nav, a MAGAZINE cover hero (masthead, one lead photo, the cover line, a rail of "
                "what's inside), ministries as departments, the gatherings strip, the story, the leaders, "
                "events, the album, a testimonial, a closing ceremony band, the visit section",
    "leader": "a fixed nav, a LEADER hero (the person's name at billboard size beside their portrait, one "
              "line under it), their story, what they offer (topics, talks, sessions, from their "
              "offerings), a testimonial, the album, events, a closing band, the contact section",
}

LAYOUT_SHAPES = {
    "poster": {"hero": {"eyebrow": "", "lines": ["", "", ""], "accent_word": "", "inset_photos": ["<photo url>"],
                        "subhead": "", "hand_line": "", "secondary": "", "secondary_target": "times", "ghost": ""},
               "times": {"eyebrow": "", "headline": "", "strip_label": "", "note": ""},
               "marquee": ["", "", ""],
               "album": {"eyebrow": "", "headline": "", "captions": {"<photo url>": ""}},
               "leaders": {"head": "", "head_script": "", "role_label": "", "body": "", "photo": "<photo url>",
                           "link_label": "", "link_target": "visit"},
               "story": {"eyebrow": "", "headline": "", "paragraphs": ["", ""],
                         "polaroids": [{"url": "<photo url>", "caption": ""}], "ghost": ""},
               "proof": {"eyebrow": "", "headline": ""},
               "ceremony": {"line": "", "accent_word": "", "sub": ""}},
}
LAYOUT_SHAPES["bulletin"] = {**{k: v for k, v in LAYOUT_SHAPES["poster"].items() if k not in ("story", "marquee")},
                             "hero": {"eyebrow": "", "lines": ["", ""], "accent_word": "", "subhead": "",
                                      "board_title": "", "secondary": "", "secondary_target": "visit"},
                             "events": {"eyebrow": "", "headline": ""},
                             "ministries": {"eyebrow": "", "headline": "", "intro": ""}}
LAYOUT_SHAPES["magazine"] = {**LAYOUT_SHAPES["bulletin"],
                             "hero": {"eyebrow": "", "lines": ["", ""], "accent_word": "", "subhead": "",
                                      "issue_line": "", "rail_title": "", "secondary": "", "secondary_target": "visit"},
                             "ministries": {"eyebrow": "", "headline": "", "intro": "", "kicker": ""},
                             "story": LAYOUT_SHAPES["poster"]["story"]}
LAYOUT_SHAPES["leader"] = {"hero": {"eyebrow": "", "subhead": "", "portrait": "<photo url>", "secondary": "",
                                    "secondary_target": "story"},
                           "story": LAYOUT_SHAPES["poster"]["story"],
                           "topics": {"eyebrow": "", "headline": "", "intro": ""},
                           "album": LAYOUT_SHAPES["poster"]["album"],
                           "events": {"eyebrow": "", "headline": ""},
                           "proof": {"eyebrow": "", "headline": ""},
                           "ceremony": LAYOUT_SHAPES["poster"]["ceremony"]}
_COMMON = ("lang", "tz", "hours_rows", "action_label", "row_label", "tokens", "wordmark", "nav", "footer",
           "dock", "custom", "visit")


def shape_for(layout: str) -> Dict[str, Any]:
    if layout == "booking" or layout not in LAYOUT_SHAPES:
        return WORDS_SHAPE
    shape = {k: WORDS_SHAPE[k] for k in _COMMON if k in WORDS_SHAPE}
    shape["layout"] = layout
    shape["gatherings"] = [{"day": 0, "time": "11:00", "label": ""}]
    shape["visit"] = {**WORDS_SHAPE["visit"], "steps": ["", "", ""]}
    shape["tokens"] = {**WORDS_SHAPE["tokens"], "script_font": "", "radius": 0, "pill": False}
    shape.update(LAYOUT_SHAPES[layout])
    import site_kit_church as church
    targets = "|".join(k for k, _ in church.LAYOUTS[layout] if k != "hero")
    shape["nav"] = [{"label": "", "sub": "", "target": targets}]
    return shape


def data_digest(fx: Dict[str, Any]) -> str:
    contact = fx.get("contact") or {}
    truth = ((fx.get("discovery_dossier") or {}).get("truth")) or {}
    th = truth.get("hours")
    th = th.get("value") if isinstance(th, dict) else th
    return json.dumps({
        "name": (fx.get("business") or {}).get("name"), "type": (fx.get("business") or {}).get("type"),
        "address": contact.get("address"), "phone": contact.get("phone"),
        "hours": contact.get("hours") or th, "booking": bool(fx.get("booking_url")),
        "offerings": [o.get("name") for o in fx.get("offerings") or []],
        "menu_told_the_coach": truth.get("offers") or [],
        "people": [p.get("name") for p in ((fx.get("discovery_dossier") or {}).get("identity") or {}).get("team") or []],
        "photos": [{"url": g.get("url"), "alt": g.get("alt")} for g in fx.get("gallery") or []],
        "testimonials": len(fx.get("testimonials") or []),
        "events": fx.get("events") or [], "ministries": fx.get("ministries") or [],
        "owner_words": (fx.get("owner_brief") or "")[:1200],
    }, ensure_ascii=False)


def _json_from(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1]) if start >= 0 else {}


def _usage(resp, model: str, task: str, business_id: str) -> None:
    try:
        import api_usage_logger
        u = resp.usage
        api_usage_logger.log_api_usage_sync(endpoint="site_kit", model=model, input_tokens=u.input_tokens,
                                            output_tokens=u.output_tokens, business_id=business_id, task_type=task)
    except Exception:
        pass


WORDS_MODEL = "claude-sonnet-5-5"
CUSTOM_MODEL = "claude-opus-5-5"


def write_words(spec: str, fx: Dict[str, Any], business_id: str = "", layout: str = "booking") -> Dict[str, Any]:
    import llm_call
    client = llm_call.sdk_client(timeout=120.0, max_retries=2)
    system = WORDS_SYSTEM.replace("for the BOOKING DESK layout: a fixed\nnav, a hero, the board + desk (the price list, every service bookable), the work\n(photos), a one-line band, a testimonial, the team, the visit section, a footer and a\nphone dock.",
                                  f"for the {layout.upper()} layout: {LAYOUT_SECTIONS.get(layout, '')}, a footer and a phone dock.")
    if layout != "booking":
        system += GATHERING_RULES
    msg = (f"THE BLUEPRINT:\n{spec[:60000]}\n\nTHE DATA (facts the code fills):\n{data_digest(fx)}\n\n"
           f"THE SHEET TO FILL (this shape, every key):\n{json.dumps(shape_for(layout), ensure_ascii=False)}")
    resp = client.messages.create(model=WORDS_MODEL, max_tokens=12000, system=system,
                                  messages=[{"role": "user", "content": msg}])
    _usage(resp, WORDS_MODEL, "site_kit_words", business_id)
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return _json_from(text)


GATHERING_RULES = """

For this layout also:
- gatherings: the weekly gatherings exactly as THE DATA states them (day 0 Sunday to 6
  Saturday, 24-hour "HH:MM", the label in the data's own words). The code drops any that
  the data doesn't state.
- Photos: only urls from THE DATA's photos. inset_photos, the leaders' photo, the
  portrait and polaroids each name one; captions describe what the photo shows. The
  leaders' photo and the portrait must SHOW that person (its alt says so: "The pastor
  preaching"); leave them empty when no photo does.
- story paragraphs: the owner's own sentences from THE DATA where it has them, lightly
  joined; never a claim, number or event the data doesn't hold.
- marquee: the owner's own short phrases (their motto, values, the words on their wall).
- ceremony: one short line a visitor remembers, with one word underlined.
- visit steps: two to four plain first-time steps built only from the data (when, where,
  who to look for)."""


CUSTOM_SYSTEM = """You write ONE section for a page assembled from a finished kit.

The rest of the page is already designed. Your section must look like it was made with
it: the same tokens, type and rhythm. You get the kit's CSS so you can match it.

Write:
- html: one <section class="k-section k-custom k-custom-ID" id="ID"> ... </section>.
  Reuse the kit's classes for the parts they cover (k-wrap, k-eyebrow, k-h2, k-h3,
  k-intro, k-lead, k-btn, k-link, k-rule, k-meta). Add your own classes for the rest,
  all starting with k-custom-ID.
- css: rules for your own classes only, every selector starting with .k-custom-ID.
  Colours and fonts only through the kit's variables (var(--k-...)); no colour literals
  except rgba() for shadows. Grids use minmax(0,1fr). Include a @media (max-width:760px)
  block so it is whole at 390px wide with nothing off the side.
- No script, no form, no iframe, no outside file, no event handler, no image.
- Every fact comes from the brief's data, word for word. Never add a time, place,
  price or claim it doesn't hold.
- Balance it at 1440 wide: no column left mostly empty. A short list sits in one
  centred column or two even columns beside its heading, never trailing in a corner.
  If the brief asks for columns that would come out uneven (one with far fewer rows
  than the other), set it as ONE list with the groups as small labels inside it.

Reply with ONLY a JSON object: {"html": "...", "css": "..."}."""


def write_custom(brief: Dict[str, str], w: Dict[str, Any], fx: Dict[str, Any], business_id: str = "") -> Dict[str, str]:
    import llm_call
    cid = re.sub(r"[^a-z]", "", str(brief.get("id") or "custom").lower())[:20] or "custom"
    t = tokens(w.get("tokens"))
    client = llm_call.sdk_client(timeout=300.0, max_retries=2)
    msg = (f"ID: {cid}\nWHAT IT MUST SHOW: {brief.get('brief')}\n\nTHE DATA:\n{data_digest(fx)}\n"
           f"THE OWNER'S WORDS: {fx.get('owner_brief') or ''}\n\nTHE LOOK: {json.dumps(t)}\n"
           f"THE PAGE'S VOICE (its other headlines): {json.dumps([(w.get(k) or {}).get('headline') for k in ('board', 'work', 'visit')])}\n\n"
           f"THE KIT'S CSS:\n{BASE_CSS}")
    resp = client.messages.create(model=CUSTOM_MODEL, max_tokens=12000, system=CUSTOM_SYSTEM,
                                  messages=[{"role": "user", "content": msg}])
    _usage(resp, CUSTOM_MODEL, "site_kit_custom", business_id)
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    out = _json_from(text)
    return {"id": cid, "after": str(brief.get("after") or "board"),
            "html": str(out.get("html") or ""), "css": str(out.get("css") or "")}
