"""
site_modules/_base.py — Arc 26 PR2 — shared plumbing for section modules.

Contract every module follows:
    render(variant: str, content: dict, ctx: dict) -> tuple[str, str]
      → (section_html, section_css)

- HTML is built here in Python, never by the LLM. All content fields are
  escaped via safe(). Function (working links, responsive layout) is the
  module's job; the composer only chooses variants and writes copy.
- Styling references ONLY the --sx-* variables from brand_dna.css_variables.
- Editable text carries data-override-target="<section>/<field>" so the
  existing override system (Pass 4.0d/e) works unchanged.
- Images carry data-slot="<name>" with src="" so the existing slot
  population (Pass 4.0b.5) fills them (user upload > Unsplash > DALL-E).

ctx keys: dna (brand_dna tokens), business {name, type, tagline, slug},
booking {enabled, url}, offerings [rows], assets {logo_url, ...}.
"""
from __future__ import annotations

import hashlib as _hashlib
import html as _html
import json as _json
from typing import Any, Dict, List, Optional, Tuple

# Ultra-subtle SVG fractal noise, inlined as a data URI (Arc 3 finish;
# ported from the shelved cinematic_authority background_treatment).
# Shared by the page-level film-grain overlay and the constructed hero.
GRAIN_DATA_URI = (
    "url(\"data:image/svg+xml;utf8,"
    "<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160' "
    "viewBox='0 0 160 160'>"
    "<filter id='g'>"
    "<feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' "
    "stitchTiles='stitch'/>"
    "</filter>"
    "<rect width='100%25' height='100%25' filter='url(%23g)'/>"
    "</svg>\")"
)


def safe(value: Any) -> str:
    if value is None:
        return ""
    return _html.escape(str(value))


def safe_url(value: Any) -> str:
    """Escape + reject javascript:/data: URLs (defense in depth — these
    are practitioner/system URLs, but modules never trust input)."""
    s = str(value or "").strip()
    low = s.lower()
    if low.startswith(("javascript:", "data:", "vbscript:")):
        return ""
    return _html.escape(s, quote=True)


# Platform → profile-URL base. Shared by contact_footer (visible social
# links) and build_page_meta (JSON-LD sameAs). Handles may be full URLs
# or bare @handles.
SOCIAL_BASES: Dict[str, str] = {
    "instagram": "https://instagram.com/",
    "facebook": "https://facebook.com/",
    "youtube": "https://youtube.com/",
    "twitter": "https://twitter.com/",
    "linkedin": "https://linkedin.com/in/",
    "tiktok": "https://tiktok.com/@",
}


def social_profile_url(platform: str, handle: Any) -> str:
    """Full profile URL from a platform + handle (or pass-through URL).
    Empty string when it can't be resolved to a real URL."""
    h = str(handle or "").strip()
    if not h:
        return ""
    if h.startswith("http"):
        return h
    base = SOCIAL_BASES.get((platform or "").lower())
    return base + h.lstrip("@") if base else ""


def ov(section: str, field: str) -> str:
    """data-override-target attribute for an editable text node."""
    return f'data-override-target="{section}/{field}"'


def eyebrow(section: str, text: str, field: str = "eyebrow") -> str:
    if not text:
        return ""
    return f'<div class="sxm-eyebrow" {ov(section, field)}>{safe(text)}</div>'


def heading_accent(dna: Dict[str, Any]) -> str:
    """The brand accent mark that precedes section headings — visual
    signature varies by accent_style so verticals don't look identical."""
    style = dna.get("accent_style", "thin_rule")
    if style in ("block_mark", "block"):
        return '<span class="sxm-mark sxm-mark-block" aria-hidden="true"></span>'
    if style in ("soft_rule", "soft"):
        return '<span class="sxm-mark sxm-mark-soft" aria-hidden="true"></span>'
    return '<span class="sxm-mark sxm-mark-thin" aria-hidden="true"></span>'


def cta_button(ctx: Dict[str, Any], label: str, section: str,
               field: str = "cta_label") -> str:
    """A CTA that always WORKS: booking page when enabled, else a
    mailto/contact anchor. Never a dead button.

    Arc 5: ctx.cta_goal (the owner's stated #1 conversion goal) steers
    the destination deterministically — buy → the store page (when it
    exists), contact → the contact anchor. book/follow keep the default
    ladder (booking page > #contact; socials live in the contact
    section). Function-first: a goal never produces a dead href."""
    booking = ctx.get("booking") or {}
    store = ctx.get("store") or {}
    goal = str(ctx.get("cta_goal") or "")
    href = ""
    if goal == "buy" and store.get("enabled") and store.get("url"):
        href = safe_url(store["url"])
    elif goal == "contact":
        href = "#contact"
    if not href:
        if booking.get("enabled") and booking.get("url"):
            href = safe_url(booking["url"])
        else:
            href = "#contact"
    return (f'<a class="sxm-cta" href="{href}">'
            f'<span {ov(section, field)}>{safe(label or "Get in touch")}</span></a>')


# ─── DRO → body-class mappers (Arc 3 "Expressive Range") ─────────────

def signature_move_class(dna: Dict[str, Any],
                         design: Optional[Dict[str, Any]]) -> str:
    """DRO motion.signature_move (a free-text named motion idea) → one of
    three page-level signature moves, deterministically. Empty string when
    motion is subtle/none or no move was authored — the previous no-op
    stays the no-DRO behavior."""
    if (dna or {}).get("motion", "standard") == "subtle":
        return ""
    motion = (design or {}).get("motion") or {}
    move = str(motion.get("signature_move") or "").strip().lower()
    if not move:
        return ""
    if "none" in str(motion.get("temperature") or "").lower():
        return ""
    if any(w in move for w in ("cascade", "stagger", "sequen", "waterfall", "step")):
        return "sx-sig-cascade"
    if any(w in move for w in ("drift", "float", "ambient", "breath", "orbit", "sway", "hover")):
        return "sx-sig-drift"
    if any(w in move for w in ("underline", "sweep", "rule", "trace", "line")):
        return "sx-sig-underline"
    # A named move that matches no family still gets a thesis — stable
    # hash-pick so the same DRO always renders the same signature.
    pick = int(_hashlib.sha256(move.encode()).hexdigest()[:8], 16) % 3
    return ("sx-sig-cascade", "sx-sig-drift", "sx-sig-underline")[pick]


# Arc 6 "Creative Engine" — rule-break treatment → body class. The
# treatment vocabulary + free-text mapping live in brand_dna
# (resolve_rule_break); this is the render-side registry.
RULE_BREAK_CLASSES: Dict[str, str] = {
    "oversize_headline": "sx-rb-oversize",
    "hard_silence": "sx-rb-silence",
    "wrong_accent_moment": "sx-rb-wrongaccent",
    "broken_grid": "sx-rb-brokengrid",
}


def rule_break_treatment(design: Optional[Dict[str, Any]]) -> str:
    """DRO decisions.rule_break → treatment key ('' when absent)."""
    import brand_dna
    return brand_dna.resolve_rule_break((design or {}).get("rule_break"))


def image_treatment_class(dna: Dict[str, Any],
                          design: Optional[Dict[str, Any]]) -> str:
    """DRO palette temperature / accent strategy (vibe fallback) → one
    soft image-grade class. Treatments are capped-gentle by design —
    practitioner photos stay recognizable."""
    pal = (design or {}).get("palette") or {}
    strategy = str(pal.get("accent_strategy") or "").lower()
    temp = str(pal.get("temperature") or "").lower()
    if strategy in ("vivid_block", "dual_complement"):
        return "sx-img-duowash"
    if "warm" in temp:
        return "sx-img-warmfilm"
    if "cool" in temp:
        return "sx-img-mono"
    return {"warm": "sx-img-warmfilm", "bold": "sx-img-duowash",
            "formal": "sx-img-mono"}.get((dna or {}).get("vibe") or "", "")


# ─── Base CSS shared by all modules (emitted once per page) ───────────

# Signature-move CSS (Arc 3). Lives inside the motion!=subtle branch —
# the moves piggyback on the reveal observer's .sxm-in class, which only
# exists when the reveal script ships. reduced-motion kills all three.
_SIG_CSS = """
/* Signature moves — DRO motion.signature_move → body class (Arc 3) */
body.sx-sig-cascade .sxm-reveal .sxm-inner > * { opacity: 0; transform: translateY(16px);
  transition: opacity .6s var(--sx-ease), transform .6s var(--sx-ease); }
body.sx-sig-cascade .sxm-reveal.sxm-in .sxm-inner > * { opacity: 1; transform: none; }
body.sx-sig-cascade .sxm-reveal.sxm-in .sxm-inner > *:nth-child(2) { transition-delay: .08s; }
body.sx-sig-cascade .sxm-reveal.sxm-in .sxm-inner > *:nth-child(3) { transition-delay: .16s; }
body.sx-sig-cascade .sxm-reveal.sxm-in .sxm-inner > *:nth-child(4) { transition-delay: .24s; }
body.sx-sig-cascade .sxm-reveal.sxm-in .sxm-inner > *:nth-child(5) { transition-delay: .32s; }
body.sx-sig-cascade .sxm-reveal.sxm-in .sxm-inner > *:nth-child(6) { transition-delay: .4s; }
body.sx-sig-cascade .sxm-reveal.sxm-in .sxm-inner > *:nth-child(7) { transition-delay: .48s; }
body.sx-sig-cascade .sxm-reveal.sxm-in .sxm-inner > *:nth-child(n+8) { transition-delay: .56s; }
@keyframes sx-drift { from { transform: translate3d(0, 0, 0) rotate(0deg); }
  to { transform: translate3d(1.6%, -2.2%, 0) rotate(1.4deg); } }
@keyframes sx-drift-pan { from { transform: scale(1.04); }
  to { transform: scale(1.09) translate3d(-.8%, -.8%, 0); } }
body.sx-sig-drift .sxm-orn-layer { animation: sx-drift 16s ease-in-out infinite alternate; }
body.sx-sig-drift .sxm-orn-layer:nth-child(2) { animation-duration: 22s; animation-direction: alternate-reverse; }
body.sx-sig-drift .sxm-motif { animation: sx-drift 19s ease-in-out infinite alternate-reverse; }
body.sx-sig-drift .sxm-cine-bg, body.sx-sig-drift .sxm-hero-bgimg {
  animation: sx-drift-pan 26s ease-in-out infinite alternate; }
body.sx-sig-underline .sxm-reveal h2 { position: relative; padding-bottom: 14px; }
body.sx-sig-underline .sxm-reveal h2::after { content: ""; position: absolute; left: 0; bottom: 0;
  height: 3px; width: min(150px, 55%); border-radius: 99px;
  background: linear-gradient(90deg, var(--sx-accent), transparent);
  transform: scaleX(0); transform-origin: left; transition: transform .9s var(--sx-ease) .2s; }
body.sx-sig-underline .sxm-reveal.sxm-in h2::after { transform: scaleX(1); }
@media (prefers-reduced-motion: reduce) {
  body.sx-sig-cascade .sxm-reveal .sxm-inner > * { opacity: 1; transform: none; transition: none; }
  body.sx-sig-drift .sxm-orn-layer, body.sx-sig-drift .sxm-motif,
  body.sx-sig-drift .sxm-cine-bg, body.sx-sig-drift .sxm-hero-bgimg { animation: none !important; }
  body.sx-sig-underline .sxm-reveal h2::after { transform: scaleX(1); transition: none; }
}"""

# Image-treatment CSS (Arc 3): one soft grade per page via body class.
# Grades hit only slot imagery (img[data-slot]) — practitioner product
# photos (store) and logos are untouched. Overlays ride .sxm-imgbox
# wrappers; every gradient fades (soft-gradient rule).
_TREATMENT_CSS = """
.sxm-imgbox { position: relative; border-radius: var(--sx-radius-image); overflow: hidden; }
body.sx-img-warmfilm img[data-slot] { filter: sepia(.10) saturate(1.08) contrast(1.02) brightness(1.01); }
body.sx-img-warmfilm .sxm-imgbox::after { content: ""; position: absolute; inset: 0; pointer-events: none;
  border-radius: inherit; background: radial-gradient(ellipse at center, transparent 60%, rgba(16, 10, 4, .16) 100%); }
body.sx-img-mono img[data-slot] { filter: saturate(.45) contrast(1.09) brightness(1.01); }
body.sx-img-duowash img[data-slot] { filter: saturate(.9) contrast(1.04); }
body.sx-img-duowash .sxm-imgbox::after { content: ""; position: absolute; inset: 0; pointer-events: none;
  border-radius: inherit; background: color-mix(in srgb, var(--sx-accent) 26%, transparent);
  mix-blend-mode: soft-light; }"""

# Arc 6 "Creative Engine" — rule-break treatment CSS + the restraint
# budget's reduced tiers. Each treatment is ONE loud moment:
#   sx-rb-oversize    — hero display clamps up a tier (#top = every hero)
#   sx-rb-silence     — the emptiest section (render_page marks it
#                       .sx-rb-target) doubles its vertical air and drops
#                       ornament (eyebrow/mark/alternating band)
#   sx-rb-wrongaccent — the hero CTA + accent word spend --sx-accent-break
#   sx-rb-brokengrid  — the about image slips its column (offset + tilt)
# `.sx-rb-soft` = the rule-break at REDUCED strength (budget spent on the
# motion signature instead); `.sx-sig-soft` = the signature move at
# reduced strength (budget spent on the rule-break). page_shell applies
# exactly one of the two at loud strength — never both.
_RULE_BREAK_CSS = """
body.sx-rb-oversize #top h1 { font-size: clamp(3.9rem, 10vw, 8.2rem); line-height: .98; }
body.sx-rb-oversize.sx-rb-soft #top h1 { font-size: clamp(3.3rem, 8.2vw, 6.6rem); }
body.sx-rb-silence .sx-rb-target { padding-top: calc(var(--sx-section-pad) * 2);
  padding-bottom: calc(var(--sx-section-pad) * 2); background: var(--sx-bg); }
body.sx-rb-silence .sx-rb-target .sxm-eyebrow,
body.sx-rb-silence .sx-rb-target .sxm-mark { display: none; }
body.sx-rb-silence.sx-rb-soft .sx-rb-target { padding-top: calc(var(--sx-section-pad) * 1.4);
  padding-bottom: calc(var(--sx-section-pad) * 1.4); }
body.sx-rb-wrongaccent #top .sxm-cta { background: var(--sx-accent-break, var(--sx-accent));
  color: var(--sx-on-accent-break, var(--sx-on-accent)); }
body.sx-rb-wrongaccent #top .sxm-cta:hover { background: var(--sx-accent-break, var(--sx-accent-strong)); filter: brightness(1.08); }
body.sx-rb-wrongaccent #top .sxm-accent-word { color: var(--sx-accent-break, var(--sx-accent)); }
body.sx-rb-wrongaccent.sx-rb-soft #top .sxm-cta { background: var(--sx-accent); color: var(--sx-on-accent); filter: none; }
body.sx-rb-brokengrid #about .sxm-imgbox { transform: translateY(clamp(26px, 5vw, 64px)) rotate(-1.4deg); }
body.sx-rb-brokengrid.sx-rb-soft #about .sxm-imgbox { transform: translateY(clamp(12px, 2.4vw, 30px)) rotate(-0.5deg); }
@media (max-width: 768px) {
  body.sx-rb-brokengrid #about .sxm-imgbox { transform: translateY(14px) rotate(-0.8deg); }
}
/* Signature move at reduced strength (restraint budget: rule-break is loud) */
body.sx-sig-soft.sx-sig-cascade .sxm-reveal.sxm-in .sxm-inner > * { transition-delay: 0s !important; }
body.sx-sig-soft.sx-sig-drift .sxm-orn-layer, body.sx-sig-soft.sx-sig-drift .sxm-motif,
body.sx-sig-soft.sx-sig-drift .sxm-cine-bg, body.sx-sig-soft.sx-sig-drift .sxm-hero-bgimg {
  animation-duration: 44s !important; }
body.sx-sig-soft.sx-sig-underline .sxm-reveal h2::after { width: 64px; height: 2px; }"""

# Film-grain finish (Arc 3, quality-bar signature): ultra-subtle static
# noise over the whole page. pointer-events: none — purely atmospheric.
_GRAIN_CSS = (
    "\nbody::after { content: \"\"; position: fixed; inset: 0; z-index: 9998;"
    " pointer-events: none; background-image: " + GRAIN_DATA_URI + ";"
    " background-size: 160px 160px; opacity: .02; }"
)


def base_css(dna: Dict[str, Any]) -> str:
    motion = dna.get("motion", "standard")
    reveal_css = "" if motion == "subtle" else """
.sxm-reveal { opacity: 0; transform: translateY(18px); transition: opacity .7s var(--sx-ease), transform .7s var(--sx-ease); }
.sxm-reveal.sxm-in { opacity: 1; transform: none; }
@media (prefers-reduced-motion: reduce) { .sxm-reveal { opacity: 1; transform: none; transition: none; } }""" + _SIG_CSS
    return f"""
*, *::before, *::after {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0; background: var(--sx-bg); color: var(--sx-text);
  font-family: var(--sx-font-body); font-size: 16.5px; line-height: 1.65;
  -webkit-font-smoothing: antialiased;
}}
img {{ max-width: 100%; display: block; }}
h1, h2, h3 {{ font-family: var(--sx-font-heading); line-height: 1.08; margin: 0; }}
h1 {{ font-size: var(--sx-h1); font-weight: var(--sx-heading-weight); letter-spacing: var(--sx-letter-tight); }}
h2 {{ font-size: var(--sx-h2); font-weight: var(--sx-heading-weight); letter-spacing: var(--sx-letter-tight); }}
p {{ margin: 0 0 1.15em; max-width: 62ch; }}
a {{ color: var(--sx-accent); text-decoration: none; }}
.sxm-section {{ padding: var(--sx-section-pad) var(--sx-gutter); }}
.sxm-inner {{ max-width: var(--sx-content-max); margin: 0 auto; }}
.sxm-eyebrow {{
  font-size: .76rem; letter-spacing: .26em; text-transform: uppercase;
  color: var(--sx-accent); font-weight: 600; margin-bottom: 14px;
}}
.sxm-mark {{ display: block; margin-bottom: 22px; }}
.sxm-mark-thin {{ width: 56px; height: 2px; background: var(--sx-accent); }}
.sxm-mark-soft {{ width: 72px; height: 6px; border-radius: 99px; background: var(--sx-accent-soft); }}
.sxm-mark-block {{ width: 26px; height: 26px; background: var(--sx-accent); }}
.sxm-cta {{
  display: inline-block; padding: 16px 30px; border-radius: var(--sx-radius-button);
  background: var(--sx-accent); color: var(--sx-on-accent); font-weight: 700;
  letter-spacing: .04em; font-size: .95rem; transition: transform .22s var(--sx-ease), background .22s var(--sx-ease);
}}
.sxm-cta:hover {{ transform: translateY(-2px); background: var(--sx-accent-strong); }}
.sxm-muted {{ color: var(--sx-muted); }}
/* Palette discipline — dark/light section alternation gives the page rhythm
   (a "stage then room then stage" cadence) instead of one flat ground. */
.sxm-section:nth-of-type(even) {{ background: var(--sx-surface); }}
/* Accent scarcity (DRO single_semantic): the accent carries MEANING, so it
   stays on CTAs + links only; decorative accent (eyebrows, marks) goes quiet. */
body.sx-scarce-accent .sxm-eyebrow {{ color: var(--sx-muted); }}
body.sx-scarce-accent .sxm-mark-thin,
body.sx-scarce-accent .sxm-mark-block {{ background: var(--sx-border); }}
body.sx-scarce-accent .sxm-mark-soft {{ background: color-mix(in srgb, var(--sx-muted) 45%, transparent); }}
{reveal_css}
{_TREATMENT_CSS}
{_RULE_BREAK_CSS}
{_GRAIN_CSS}
@media (max-width: 768px) {{ body {{ font-size: 15.5px; }} }}
"""


def reveal_script(dna: Dict[str, Any]) -> str:
    """Tiny self-contained IntersectionObserver — the only JS a composed
    page ships. Deterministic platform code (same trust model as the
    motion-module injections), never LLM-written."""
    if dna.get("motion", "standard") == "subtle":
        return ""
    return ("<script>(function(){try{var els=document.querySelectorAll('.sxm-reveal');"
            "if(!('IntersectionObserver'in window)){els.forEach(function(e){e.classList.add('sxm-in')});return}"
            "var io=new IntersectionObserver(function(entries){entries.forEach(function(en){"
            "if(en.isIntersecting){en.target.classList.add('sxm-in');io.unobserve(en.target)}})},"
            "{threshold:.12});els.forEach(function(e){io.observe(e)})}catch(e){}})();</script>")


def _trim_words(text: str, limit: int) -> str:
    """Trim to <= limit chars on a word boundary (no mid-word cuts)."""
    t = " ".join(str(text or "").split())
    if len(t) <= limit:
        return t
    cut = t[:limit].rsplit(" ", 1)[0].rstrip(",;:—- ")
    return cut


def build_page_meta(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic SEO/identity payload for page_shell — built ONLY
    from real business data; every field may be empty and empty fields
    emit no tags. (Arc 1 'Wear the Brand'.)"""
    bundle = ctx.get("bundle") or {}
    b = bundle.get("business") or {}
    intel = bundle.get("practitioner_intelligence") or {}
    assets = bundle.get("assets") or {}
    biz = ctx.get("business") or {}
    contact = ctx.get("contact") or {}

    name = (biz.get("name") or b.get("name") or "").strip()
    tagline = str(b.get("tagline") or "").strip()
    pitch = str(b.get("elevator_pitch") or "").strip()
    about = str(intel.get("about_business") or "").strip()
    description = tagline or pitch or (_trim_words(about, 155) if about else "")

    slug = str(biz.get("slug") or "").strip()
    canonical = f"https://{slug}.mysolutionist.app" if slug else ""

    favicon = assets.get("favicon") or ""
    social_card = assets.get("social_card") or ""
    og_title = f"{name} — {tagline}" if (name and tagline) else name

    same_as = [u for u in (
        social_profile_url(k, v) for k, v in (contact.get("social") or {}).items()
    ) if u.startswith("http")]

    # JSON-LD LocalBusiness — only fields that exist; empties are omitted.
    jsonld: Dict[str, Any] = {"@context": "https://schema.org",
                              "@type": "LocalBusiness"}
    for key, val in (("name", name), ("description", description),
                     ("url", canonical), ("telephone", contact.get("phone")),
                     ("email", contact.get("email")),
                     ("address", contact.get("address"))):
        if str(val or "").strip():
            jsonld[key] = str(val).strip()
    hours = str(contact.get("hours") or "").strip()
    if hours:
        jsonld["openingHours"] = hours.replace("–", "-")
    if same_as:
        jsonld["sameAs"] = same_as
    if len(jsonld) <= 2:  # only @context/@type → nothing real to state
        jsonld = {}

    return {
        "description": description,
        "canonical": canonical,
        "favicon": favicon if str(favicon).startswith("http") else "",
        "og_title": og_title,
        "og_image": social_card if str(social_card).startswith("http") else "",
        "jsonld": jsonld,
    }


def _head_meta_block(meta: Optional[Dict[str, Any]]) -> str:
    """Emit description/canonical/favicon/OG/Twitter/JSON-LD tags —
    ONLY for fields that carry data (never an empty tag). og:image at
    shell time is the brand social card; when absent, the composer
    injects the resolved hero image post slot-resolution
    (site_composer._ensure_og_image)."""
    if not meta:
        return ""
    lines: List[str] = []
    desc = str(meta.get("description") or "").strip()
    canonical = str(meta.get("canonical") or "").strip()
    og_title = str(meta.get("og_title") or "").strip()
    og_image = str(meta.get("og_image") or "").strip()
    favicon = str(meta.get("favicon") or "").strip()

    if desc:
        lines.append(f'<meta name="description" content="{safe(desc)}">')
    if canonical:
        lines.append(f'<link rel="canonical" href="{safe_url(canonical)}">')
    if favicon:
        lines.append(f'<link rel="icon" href="{safe_url(favicon)}">')
    if og_title:
        lines.append(f'<meta property="og:title" content="{safe(og_title)}">')
    if desc:
        lines.append(f'<meta property="og:description" content="{safe(desc)}">')
    if canonical:
        lines.append(f'<meta property="og:url" content="{safe_url(canonical)}">')
    lines.append('<meta property="og:type" content="website">')
    if og_image:
        lines.append(f'<meta property="og:image" content="{safe_url(og_image)}">')
        lines.append('<meta name="twitter:card" content="summary_large_image">')
        lines.append(f'<meta name="twitter:image" content="{safe_url(og_image)}">')
    jsonld = meta.get("jsonld") or {}
    if jsonld:
        payload = _json.dumps(jsonld, ensure_ascii=False).replace("</", "<\\/")
        lines.append(f'<script type="application/ld+json">{payload}</script>')
    return "\n".join(lines)


def page_shell(dna: Dict[str, Any], title: str, body: str, css: str,
               design: Optional[Dict[str, Any]] = None,
               meta: Optional[Dict[str, Any]] = None) -> str:
    import brand_dna
    fonts = brand_dna.google_fonts_url(dna)
    # DRO single_semantic → accent scarcity body class (CSS in base_css).
    accent_strategy = ((design or {}).get("palette") or {}).get("accent_strategy")
    classes = []
    if accent_strategy == "single_semantic":
        classes.append("sx-scarce-accent")
    # Arc 3: signature move + image treatment reach the pixels as body
    # classes (deterministic; empty strings drop out).
    sig = signature_move_class(dna, design)
    if sig:
        classes.append(sig)
    treat = image_treatment_class(dna, design)
    if treat:
        classes.append(treat)
    # Arc 6 — rule-break treatment + the RESTRAINT BUDGET. When BOTH a
    # signature move and a rule-break exist, exactly ONE applies at loud
    # strength: the owner's loud_where='motion' (design_prefs v3, stamped
    # onto decisions as _owner_loud_where by site_composer) hands the
    # budget to the signature move (rule-break renders reduced via
    # .sx-rb-soft); otherwise the DRO's ONE deliberate rule-break is the
    # loud moment and the signature move renders reduced (.sx-sig-soft).
    rb_treatment = rule_break_treatment(design)
    rb_class = RULE_BREAK_CLASSES.get(rb_treatment, "")
    if rb_class:
        classes.append(rb_class)
        if sig:
            loud_where = str((design or {}).get("_owner_loud_where") or "")
            if loud_where == "motion":
                classes.append("sx-rb-soft")     # motion is loud, break quiet
            else:
                classes.append("sx-sig-soft")    # break is loud, motion quiet
    body_class = " ".join(classes)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{safe(title)}</title>
{_head_meta_block(meta)}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="{fonts}" rel="stylesheet">
<style>
{brand_dna.css_variables(dna)}
{base_css(dna)}
{css}
</style>
</head>
<body class="{body_class}">
{body}
{reveal_script(dna)}
</body>
</html>"""
