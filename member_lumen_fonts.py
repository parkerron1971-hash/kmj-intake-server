"""member_lumen_fonts.py — the type of the member app's new look ("Lumen Next").

Kevin, 2026-11-19, after the Lumen Next type board: "go with font A ... but
allow for each church to choose what font they want for the list that we
selected from." Three pairings, A the default:

  A · Literata + Figtree ... Literata for headings and the italic word, Bible
                             chapters and Give's amount (its tabular figures);
                             Figtree for everything you tap.
  B · Fraunces + Onest ..... Fraunces (soft) for headings; Onest for
                             everything you tap and the amount (Fraunces has
                             no tabular figures); Literata for reading.
  C · Mona Sans ............ Mona Sans wide for headings and Mona Sans for
                             everything else, the amount in its regular
                             figures (its tabular zero is slashed, like code);
                             Source Serif 4 for reading.

THE FILES. Every face is a variable font under the SIL Open Font License,
taken unmodified from Google Fonts (the latin and latin-ext subsets) and kept
in assets/member-fonts with each family's licence (its README lists where each
file came from). They are served from our own address,
/my/fonts/<face>.<hash>.woff2: the same file for every church and every host,
kept a year by the phone and by Cloudflare (the hash of the bytes is in the
address, as with the stylesheets), so a member's phone never asks Google for
anything. A Lumen page drops today's Google Fonts link (member_app_ui.FONTS).

THE PICK. The church's owner picks in Settings → Member page
(businesses.settings.member_portal.fonts = "a" | "b" | "c"; nothing is A). It
is read from the church's row the page already has: no read of its own. It
applies only to the new look; today's look keeps its type, byte for byte.

ON A PAGE. The faces and the rules live in the Lumen sheet (template(), the
last part of member_lumen_ui.templates()); a Lumen page's head preloads its
pairing's two faces (head()) and its body carries the pairing's class
(body_class(): nothing for A, lm-fb, lm-fc). The rules set these on body.lm,
for anything new that draws type:

  --mb-ui     the face for everything you tap (today's name, so every rule
              written for the app follows)
  --mb-serif  the face for headings and the italic word
  --lm-read   the face for reading: Bible chapters, devotional days, verses
  --lm-num    the face for amounts
  --lm-dw / --lm-iw     a heading's weight / its italic word's
  --lm-dtr    a big heading's tracking
  --lm-dvar / --lm-dst  a heading's variation settings / width
  --lm-nw / --lm-nst / --lm-nvn  an amount's weight / width / figures

Pure functions; the only I/O is reading the font files once per server copy.
"""
from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from pathlib import Path
from string import Template
from typing import Any, Dict, List, Mapping, Optional, Tuple

FONT_DIR = Path(__file__).resolve().parent / "assets" / "member-fonts"

# The pairings, in the order the owner sees them.
DEFAULT = "a"
PAIRS: Dict[str, Dict[str, Any]] = {
    "a": {"label": "A · Literata + Figtree", "display": "Literata", "ui": "Figtree", "read": "Literata",
          "num": "Literata", "note": "Warm headings, Bible chapters made for long reading, clear buttons.",
          "preload": ("literata-normal-latin", "figtree-normal-latin")},
    "b": {"label": "B · Fraunces + Onest", "display": "Fraunces", "ui": "Onest", "read": "Literata",
          "num": "Onest", "note": "Soft, rounded headings with a friendly, modern sans.",
          "preload": ("fraunces-normal-latin", "onest-normal-latin")},
    "c": {"label": "C · Mona Sans", "display": "Mona Sans", "ui": "Mona Sans", "read": "Source Serif 4",
          "num": "Mona Sans", "note": "Bold, wide headings, one clean family, a classic serif for reading.",
          "preload": ("mona-sans-normal-latin",)},
}

# Each face: (file stem, family, style, weight range, width range). Every
# stem has a -latin and a -latin-ext file.
FACES: Tuple[Tuple[str, str, str, str, str], ...] = (
    ("literata-normal", "Literata", "normal", "200 900", ""),
    ("literata-italic", "Literata", "italic", "200 900", ""),
    ("figtree-normal", "Figtree", "normal", "300 900", ""),
    ("fraunces-normal", "Fraunces", "normal", "100 900", ""),
    ("fraunces-italic", "Fraunces", "italic", "100 900", ""),
    ("onest-normal", "Onest", "normal", "100 900", ""),
    ("mona-sans-normal", "Mona Sans", "normal", "200 900", "75% 125%"),
    ("mona-sans-italic", "Mona Sans", "italic", "200 900", "75% 125%"),
    ("source-serif-4-normal", "Source Serif 4", "normal", "200 900", ""),
    ("source-serif-4-italic", "Source Serif 4", "italic", "200 900", ""),
)
# Google Fonts' own subset ranges, so a phone fetches latin-ext only for a
# name that needs it.
RANGES = {
    "latin": ("U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,"
              "U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD"),
    "latin-ext": ("U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,"
                  "U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C4,U+2113,U+2C60-2C7F,U+A720-A7FF"),
}
# What the phone draws while a face loads, sized to match it so nothing
# jumps when it arrives: (local font, size-adjust, ascent, descent) in %
# (assets/member-fonts/README.md says how they were measured).
FALLBACKS: Dict[str, Tuple[str, float, float, float]] = {
    "Literata": ("Georgia", 108.52, 108.46, 28.38),
    "Fraunces": ("Georgia", 105.96, 92.3, 24.07),
    "Source Serif 4": ("Georgia", 108.6, 95.39, 30.85),
    "Figtree": ("Arial", 101.52, 93.57, 24.62),
    "Onest": ("Arial", 106.21, 91.33, 28.72),
    "Mona Sans": ("Arial", 104.81, 104.0, 30.53),
}
_SERIF_TAIL = 'Georgia,"Times New Roman",serif'
_SANS_TAIL = '-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,system-ui,sans-serif'

FONT_PATH_RE = re.compile(r"^/my/fonts/([a-z0-9-]+)\.([0-9a-f]{12})\.woff2$")


@lru_cache(maxsize=None)
def files() -> Dict[str, Tuple[bytes, str]]:
    """Every font file, by name (stem-subset): (its bytes, the 12-hex hash
    in its address). Read once per server copy."""
    out: Dict[str, Tuple[bytes, str]] = {}
    for stem, *_ in FACES:
        for sub in RANGES:
            name = f"{stem}-{sub}"
            data = (FONT_DIR / f"{name}.woff2").read_bytes()
            out[name] = (data, hashlib.sha256(data).hexdigest()[:12])
    return out


def url(name: str) -> str:
    return f"/my/fonts/{name}.{files()[name][1]}.woff2"


def serve(path: str) -> Optional[Any]:
    """One of the fonts, or None if `path` isn't one's address. Like the
    stylesheets (member_app_install.serve_sheet): kept a year when the hash
    is today's, and another hash (a page from the other side of a deploy)
    still gets today's file, kept by nobody. Any site may use it (the
    owner's settings show samples from their own address)."""
    from fastapi.responses import Response
    m = FONT_PATH_RE.match(path or "")
    if not m or m.group(1) not in files():
        return None
    data, digest = files()[m.group(1)]
    keep = "public, max-age=31536000, immutable" if m.group(2) == digest else "no-store"
    return Response(data, media_type="font/woff2",
                    headers={"Cache-Control": keep, "X-Content-Type-Options": "nosniff",
                             "Access-Control-Allow-Origin": "*"})


def pick(biz: Optional[Mapping[str, Any]]) -> str:
    """The church's pairing: "a", "b" or "c" (A unless the owner picked
    another), from the church's row the page already has."""
    settings = (biz or {}).get("settings") or {}
    raw = settings.get("member_portal") if isinstance(settings, dict) else None
    key = str((raw or {}).get("fonts") or "").strip().lower() if isinstance(raw, dict) else ""
    return key if key in PAIRS else DEFAULT


def body_class(biz: Optional[Mapping[str, Any]]) -> List[str]:
    """The body's class for the church's pairing: none for A."""
    key = pick(biz)
    return [] if key == DEFAULT else [f"lm-f{key}"]


def head(biz: Optional[Mapping[str, Any]]) -> str:
    """A Lumen page's font tags, in place of today's Google Fonts link: the
    pairing's faces, preloaded (the italic and the reading face come when a
    page uses them)."""
    return "".join(f'<link rel="preload" href="{url(n)}" as="font" type="font/woff2" crossorigin>'
                   for n in PAIRS[pick(biz)]["preload"])


def clean(value: Any) -> Optional[str]:
    """An owner's pick as stored, or None if it isn't one."""
    key = str(value or "").strip().lower()
    return key if key in PAIRS else None


def choices() -> List[Dict[str, Any]]:
    """The pairings for Settings → Member page."""
    return [{"key": k, "label": p["label"] + (" (recommended)" if k == DEFAULT else ""), "display": p["display"],
             "ui": p["ui"], "read": p["read"], "note": p["note"], "recommended": k == DEFAULT}
            for k, p in PAIRS.items()]


def faces() -> List[Dict[str, str]]:
    """Every face, for the settings' live samples: family, style, weights,
    width, subset range and its address on this server."""
    return [{"family": fam, "style": style, "weight": wght, "stretch": wdth, "range": RANGES[sub],
             "url": url(f"{stem}-{sub}")}
            for stem, fam, style, wght, wdth in FACES for sub in RANGES]


def picker_open(biz: Mapping[str, Any], user: Any) -> bool:
    """Whether Settings → Member page shows the pick: wherever the new look
    can be seen (member_lumen: off nowhere; preview the platform owner at a
    church they own; owner that church; on every church). Elsewhere a pick
    would change nothing anyone sees."""
    try:
        import member_lumen
        m = member_lumen.mode()
        if m == "off":
            return False
        if m == "on":
            return True
        if m == "preview":
            # Only the platform owner sees it: anyone else is a no without
            # looking the church's owner up.
            want = member_lumen._platform_email()
            if not want or member_lumen._norm(getattr(user, "email", "")) != want:
                return False
        return bool(biz.get("id")) and member_lumen._platform_church(biz["id"])
    except Exception:
        return False


def _stack(family: str) -> str:
    tail = _SERIF_TAIL if FALLBACKS[family][0] == "Georgia" else _SANS_TAIL
    return f'"{family}","{family} Fallback",{tail}'


def _vars(key: str) -> str:
    p = PAIRS[key]
    ui, disp = _stack(p["ui"]), _stack(p["display"])
    return (f"--mb-ui:{ui};--mb-serif:{disp};--mb-display:var(--mb-ui);--font-body:var(--mb-ui);"
            f"--lm-read:{_stack(p['read'])};--lm-num:{_stack(p['num'])};")


# The type board's numbers (Lumen Next, 2026-11-19): Display XL 44/44,
# Display M 36/37, Title 20/24 700 −2%, Body 15/23, Bible reading 19/33,
# Label 11/13 650 +14% capitals (already), Give's amount 94. Each pairing's
# heading weight, italic weight, tracking, width and figures are variables.
_RULES = """
/* type (member_lumen_fonts): the church's pairing */
body.lm{%(a)s
  --lm-dw:500;--lm-iw:500;--lm-dtr:-.03em;--lm-dvar:normal;--lm-dst:100%%;
  --lm-nw:450;--lm-nst:100%%;--lm-nvn:tabular-nums lining-nums;line-height:1.53;}
body.lm.lm-fb{%(b)s
  --lm-dw:560;--lm-iw:470;--lm-dtr:-.024em;--lm-dvar:"SOFT" 50,"WONK" 0;--lm-nw:640;}
body.lm.lm-fc{%(c)s
  --lm-dw:770;--lm-iw:620;--lm-dtr:-.04em;--lm-dst:112%%;--lm-nw:720;--lm-nst:112%%;--lm-nvn:lining-nums;}
/* headings: the pairing's weight, tracking and width; the italic word its own weight */
body.lm .lm-disp,body.lm .mb-lt h1,body.lm .lm-ct,body.lm .lm-gave h2,body.lm .lm-poster .mb-art-title,
body.lm .lm-poster .mb-titled b,body.lm .lv-t h1,body.lm .lm-prof h1,body.lm .lm-rp-t,body.lm .lm-night-t,
body.lm .lm-cempty-t,body.lm .lm-acadt,body.lm .lv-sheet-h h2{font-weight:var(--lm-dw);letter-spacing:var(--lm-dtr);
  font-variation-settings:var(--lm-dvar);font-stretch:var(--lm-dst);}
body.lm .lm-stile .mb-art-title,body.lm .lm-stile .mb-titled b,body.lm .lm-th .mb-art-title,body.lm .lm-book b,
body.lm .lm-bk .bk-n,body.lm .lm-wdate b,body.lm .lm-chap b,body.lm .lm-rp-n b,body.lm .lm-evd b,
body.lm .lm-gtlink{font-weight:var(--lm-dw);font-variation-settings:var(--lm-dvar);font-stretch:var(--lm-dst);}
body.lm .lm-disp em,body.lm .mb-lt h1 em,body.lm .lm-ct em,body.lm .lm-gave h2 em,body.lm .lv-t h1 em,
body.lm .lm-prof h1 em,body.lm .lm-rp-t em,body.lm .lm-night-t em,body.lm .lm-cempty-t em,body.lm .lm-acadt em,
body.lm .lv-sheet-h h2 em,body.lm .lm-gtlink em,body.lm .lm-poster .mb-art-title em,body.lm .lm-stile .mb-art-title em,
body.lm .lm-logo,body.lm .lm-gmini,body.lm .lm-spine b,body.lm .lm-gart b,body.lm .lm-cv b,body.lm .lm-plan b,
body.lm .lm-len b,body.lm .lm-mono,body.lm .lm-av.ch,body.lm .lm-av.gp,body.lm .lm-prof .mb-avatar{
  font-weight:var(--lm-iw);font-variation-settings:var(--lm-dvar);font-stretch:var(--lm-dst);}
body.lm .lm-disp{font-size:44px;line-height:1;}
body.lm .lm-disp.m{font-size:40px;}
body.lm .lm-disp.s{font-size:36px;line-height:1.03;}
body.lm .lm-h2,body.lm .mb-sh h2{font-size:20px;line-height:1.2;}
/* reading: Bible chapters, devotional days, verses, a prayer being written */
body.lm .bb-text,body.lm .dv-body,body.lm .dv-scrip blockquote,body.lm .dv-pull,body.lm .dv-about,body.lm .dv-vl,
body.lm .bb-note-v,body.lm .bb-it-v,body.lm .bb-hn-v,body.lm .bb-hits span,body.lm .mb-verse blockquote,
body.lm .lm-page q,body.lm .lm-ta,body.lm .lm-hits span{font-family:var(--lm-read);}
body.lm .bb-text.f-sans{font-family:var(--mb-ui);}
body.lm .lm-read .bb-text{font-size:19px;line-height:1.74;letter-spacing:.002em;}
/* amounts and times */
body.lm .lm-amt{font-family:var(--lm-num);font-size:94px;font-weight:var(--lm-nw);font-stretch:var(--lm-nst);
  letter-spacing:-.02em;font-variant-numeric:var(--lm-nvn);}
body.lm .lm-amt sup{font-family:var(--lm-num);font-stretch:var(--lm-nst);}
body.lm .lm-total{font-family:var(--lm-num);font-weight:var(--lm-nw);font-stretch:var(--lm-nst);font-variant-numeric:var(--lm-nvn);}
body.lm time,body.lm .lm-pre .gv-amt,body.lm .lm-lvchip b,body.lm .lm-tr time{font-variant-numeric:var(--lm-nvn);}
"""


def _faces_css() -> str:
    out = []
    for stem, fam, style, wght, wdth in FACES:
        for sub, rng in RANGES.items():
            out.append(f'@font-face{{font-family:"{fam}";font-style:{style};font-weight:{wght};'
                       + (f"font-stretch:{wdth};" if wdth else "")
                       + f'font-display:swap;src:url({url(stem + "-" + sub)}) format("woff2");unicode-range:{rng};}}')
    for fam, (local, size, asc, desc) in FALLBACKS.items():
        out.append(f'@font-face{{font-family:"{fam} Fallback";src:local("{local}");size-adjust:{size}%;'
                   f"ascent-override:{asc}%;descent-override:{desc}%;line-gap-override:0%;}}")
    return "\n".join(out)


@lru_cache(maxsize=None)
def css() -> str:
    """The type part of the Lumen sheet: every face (a phone fetches only
    those a page uses), their fallbacks, each pairing's variables and the
    rules that read them."""
    return ("\n/* the faces (member_lumen_fonts) */\n" + _faces_css()
            + _RULES % {"a": _vars("a"), "b": _vars("b"), "c": _vars("c")})


def template() -> Template:
    """css() as the sheet's last part (member_lumen_ui.templates())."""
    return Template(css().replace("$", "$$"))
