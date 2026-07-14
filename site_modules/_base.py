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

TOTAL EDITABILITY (Site Arc 11) — the targeting rule every module obeys:
  * EVERY visible PRESENTATION-text node — headlines, eyebrows, subheads,
    body paragraphs, taglines, CTA/button labels, statement-bar lines,
    footer lines — carries a data-override-target path. If a module adds
    a new visible presentation string, it gets a target.
  * BUSINESS-DATA text stays UN-targeted BY DESIGN: prices, offering
    names/descriptions, testimonial quotes/attributions, stat numbers,
    showcase module titles/entries, contact logistics (hours/address/
    phone/email), social handles, store product cards, marquee tone
    words. These are edited at the SOURCE (offerings, testimonials,
    settings…) and re-render live — an override here would mask the
    record and go stale.
  * COMPLIANCE COPY (the SMS consent disclosure) and PLATFORM CHROME
    ("Powered by Solutionist", header nav anchor labels) are also
    un-targeted — the first is legally fixed wording, the second is
    structural.
  The composer's quality gate reports 'editability_coverage' (count of
  visible presentation-text nodes lacking a target) on every render.

ctx keys: dna (brand_dna tokens), business {name, type, tagline, slug},
booking {enabled, url}, offerings [rows], assets {logo_url, ...}.
"""
from __future__ import annotations

import hashlib as _hashlib
import html as _html
import json as _json
import re as _re2
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


_ALPHA_RE = _re2.compile(r"[A-Za-z0-9']+")


def accent_headline(headline: str) -> str:
    """The quality-bar accent-word idiom (the original bar's 'one italic
    accent word in every heading'), promoted from hero.py to shared
    plumbing (quality-floor arc 7): exactly ONE emphasized italic word in
    the accent color, picked deterministically — the longest word, the
    heading's likely center of gravity (first wins ties). Every fragment
    is escaped; single-word headings pass through plain. Styling lives in
    base_css (.sxm-accent-word); accent/authority bands re-tone it."""
    words = str(headline or "").split()
    if len(words) < 2:
        return safe(headline)

    def _alpha_len(w: str) -> int:
        return sum(len(m) for m in _ALPHA_RE.findall(w))

    target = max(range(len(words)), key=lambda i: _alpha_len(words[i]))
    return " ".join(
        f'<em class="sxm-accent-word">{safe(w)}</em>' if i == target else safe(w)
        for i, w in enumerate(words))


def is_brut(dna: Optional[Dict[str, Any]]) -> bool:
    """The studio-brut / 'bold formal' identity (the brutalist-radius
    branch of brand_dna.derive_radius): its language is sharp edges and
    color-blocks — ornament layers (diamonds) are skipped for it."""
    d = dna or {}
    return d.get("vibe") == "bold" and d.get("intensity") == "bold"


def diamond_field(dna: Optional[Dict[str, Any]], count: int = 3) -> str:
    """2-3 floating diamond ornaments (the original bar's brand shape —
    a rotated square, opacity .04-.08, gentle float; static when motion
    is subtle, killed by prefers-reduced-motion). Empty string for the
    brut identity — their language is color-blocks, not ornament."""
    if is_brut(dna):
        return ""
    n = max(2, min(int(count or 3), 3))
    return "".join(
        f'<span class="sxm-diamond sxm-d{i}" aria-hidden="true"></span>'
        for i in range(1, n + 1))


def diamond_mark(dna: Optional[Dict[str, Any]]) -> str:
    """Small STATIC diamond (header wordmark / footer brand mark).
    Skipped for the brut identity."""
    if is_brut(dna):
        return ""
    return '<span class="sxm-diamond-mark" aria-hidden="true"></span>'


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
    section). Function-first: a goal never produces a dead href.

    Site Arc 11 (connections): an EXPLICIT owner connections.booking=True
    outranks the goal steering — the booking URL leads the ladder on the
    hero + cta band. connections.booking=False is handled upstream
    (gather_context disables ctx.booking), so the ladder falls to
    #contact naturally. Absent connections → byte-identical ladder."""
    booking = ctx.get("booking") or {}
    store = ctx.get("store") or {}
    conn = ctx.get("connections") if isinstance(ctx.get("connections"), dict) else {}
    goal = str(ctx.get("cta_goal") or "")
    href = ""
    # Kevin's second ruling (2026-07-10): creative button copy is
    # welcome, but the LABEL'S INTENT governs the destination — a button
    # that TALKS like contact ("get in touch", "send a message") must
    # never route to booking, and a button that talks like booking
    # ("book", "schedule", "reserve") must never dead-end at the contact
    # form while booking exists. Ambiguous/creative labels ("Bring me
    # the pieces") keep the primary-action ladder (booking first).
    label_intent = _cta_label_intent(label)
    if label_intent == "contact":
        href = "#contact"
    elif label_intent == "booking" and booking.get("enabled") and booking.get("url"):
        href = safe_url(booking["url"])
    elif conn.get("booking") and booking.get("enabled") and booking.get("url"):
        href = safe_url(booking["url"])
    elif goal == "buy" and store.get("enabled") and store.get("url"):
        href = safe_url(store["url"])
    # Kevin's first ruling (2026-07-10): when booking exists, the PRIMARY
    # action is booking — "the connect part is if they want information,
    # not a booking itself." A stored cta_goal of "contact" (often set
    # before booking was connected) no longer hijacks primaries to the
    # contact anchor; it only steers when there's nothing to book. The
    # contact section stays one scroll away for information seekers.
    elif booking.get("enabled") and booking.get("url"):
        href = safe_url(booking["url"])
    elif goal == "contact":
        href = "#contact"
    if not href:
        if booking.get("enabled") and booking.get("url"):
            href = safe_url(booking["url"])
        else:
            href = "#contact"
    return (f'<a class="sxm-cta" href="{href}">'
            f'<span {ov(section, field)}>{safe(label or "Get in touch")}</span></a>')


# Label-intent vocabulary for _cta_label_intent + the gate's
# cta_link_coherence check — one list, no drift.
CTA_CONTACT_WORDS = ("touch", "contact", "message", "talk", "chat",
                     "write", "email", "reach", "question", "hello",
                     "say hi", "connect with", "conversation")
CTA_BOOKING_WORDS = ("book", "schedule", "appointment", "session",
                     "reserve", "slot", "availability", "calendar")


def _cta_label_intent(label: str) -> str:
    """'contact' | 'booking' | '' (ambiguous/creative) from the label's
    own words. Booking wins ties ('book a chat' is a booking ask)."""
    s = f" {str(label or '').lower()} "
    if any(w in s for w in CTA_BOOKING_WORDS):
        return "booking"
    if any(w in s for w in CTA_CONTACT_WORDS):
        return "contact"
    return ""


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


def reveal_focus_class(dna: Dict[str, Any],
                       design: Optional[Dict[str, Any]]) -> str:
    """Site Arc 10 "wow" — the blur-to-focus ARRIVAL (exemplar e5:
    'sections arrive by coming into focus — sharper is the entrance,
    not higher'). An ALTERNATIVE reveal the DRO's motion energy selects:
    expressive/cinematic energy → focus reveals (blur 8px→0 + a .98→1
    settle); calm pages keep the classic fade-up. Wired as a body class
    (sx-reveal-focus) exactly like the signature moves; empty string =
    no change. Rides the same .sxm-reveal observer, so motion=subtle
    (no reveal script) never gets it."""
    if (dna or {}).get("motion", "standard") == "subtle":
        return ""
    motion = (design or {}).get("motion") or {}
    temp = str(motion.get("temperature") or "").lower()
    move = str(motion.get("signature_move") or "").lower()
    if "expressive" in temp:
        return "sx-reveal-focus"
    if any(w in move for w in ("focus", "blur", "cinema", "lens", "sharpen",
                               "resolve", "develop")):
        return "sx-reveal-focus"
    return ""


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
/* Site quality (2026-07-14): FADE the heading underline in, don't WIPE it.
   The old scaleX(0)->scaleX(1) read as a line drawing itself out of nothing
   on every scroll; a quiet opacity fade keeps the accent without the artifact. */
body.sx-sig-underline .sxm-reveal h2::after { content: ""; position: absolute; left: 0; bottom: 0;
  height: 2px; width: min(120px, 44%); border-radius: 99px;
  background: linear-gradient(90deg, var(--sx-accent), transparent);
  opacity: 0; transition: opacity .7s var(--sx-ease) .15s; }
body.sx-sig-underline .sxm-reveal.sxm-in h2::after { opacity: 1; }
@media (prefers-reduced-motion: reduce) {
  body.sx-sig-cascade .sxm-reveal .sxm-inner > * { opacity: 1; transform: none; transition: none; }
  body.sx-sig-drift .sxm-orn-layer, body.sx-sig-drift .sxm-motif,
  body.sx-sig-drift .sxm-cine-bg, body.sx-sig-drift .sxm-hero-bgimg { animation: none !important; }
  body.sx-sig-underline .sxm-reveal h2::after { opacity: 1; transition: none; }
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

# Quality-floor arc 7 — the owner's original design bar, ported into the
# live renderer as its DEFAULT floor (source: agents/design_intelligence/
# cinematic_authority_intelligence.md; enforcement values from the retired
# studio_solutionist_quality.py). Shared card depth + hover, the AUTHORITY
# rhythm band, the diamond ornament layer, and the CTA shimmer keyframes.
# All motion here is killed by prefers-reduced-motion (below) and the
# looping pieces also stop on motion=subtle (base_css branch).
_QUALITY_CSS = """
/* Card depth + hover (bar: resting 22/60 shadow, hover -8px + accent border).
   Site Arc 9: shadow ink branches by palette mode — light grounds keep the
   ink-tinted color-mix, dark grounds get TRUE BLACK (a text-tinted shadow
   on a dark ground is a white haze, not depth). */
.sxm-card { box-shadow: 0 22px 60px {SHADOW_REST};
  transition: transform .5s var(--sx-ease), box-shadow .5s var(--sx-ease),
    border-color .5s var(--sx-ease); }
.sxm-card:hover { transform: translateY(-8px); border-color: var(--sx-accent);
  box-shadow: 0 40px 80px {SHADOW_HOVER}; }
.sxm-card-lite { box-shadow: 0 22px 60px {SHADOW_REST};
  transition: transform .5s var(--sx-ease), box-shadow .5s var(--sx-ease); }
.sxm-card-lite:hover { transform: translateY(-4px);
  box-shadow: 0 30px 64px {SHADOW_HOVER_LITE}; }
/* TRUE RHYTHM — the AUTHORITY band: ONE mid-page section on the deep
   authority ground (render_page marks it). Custom-property overrides
   re-ink everything inside (text, muted, borders, cards, accent) with
   the contrast-enforced on-authority variants from brand_dna. */
.sxm-section.sxm-authority { position: relative; overflow: hidden;
  background: var(--sx-authority); color: var(--sx-on-authority);
  --sx-text: var(--sx-on-authority);
  --sx-muted: color-mix(in srgb, var(--sx-on-authority) 74%, var(--sx-authority));
  --sx-border: color-mix(in srgb, var(--sx-on-authority) 18%, transparent);
  --sx-surface: color-mix(in srgb, var(--sx-on-authority) 7%, transparent);
  --sx-surface-2: color-mix(in srgb, var(--sx-on-authority) 11%, transparent);
  --sx-accent: var(--sx-accent-on-authority); }
.sxm-section.sxm-authority h2, .sxm-section.sxm-authority h3 { color: var(--sx-on-authority); }
/* Diamond ornament layer — the bar's brand shape (rotated square). */
.sxm-diamond { position: absolute; width: 110px; height: 110px; z-index: 0;
  border: 1.5px solid currentColor; color: var(--sx-accent); opacity: .07;
  transform: rotate(45deg); pointer-events: none;
  animation: sxm-float 6s ease-in-out infinite; }
.sxm-d1 { top: 12%; right: 7%; }
.sxm-d2 { bottom: 16%; left: 5%; width: 64px; height: 64px; opacity: .05;
  animation-duration: 7.2s; animation-delay: 1.1s; }
.sxm-d3 { top: 44%; right: 26%; width: 40px; height: 40px; opacity: .04;
  animation-duration: 5.2s; animation-delay: .5s; }
.sxm-diamond-mark { display: inline-block; width: 9px; height: 9px;
  margin-right: 10px; background: var(--sx-accent); transform: rotate(45deg);
  flex-shrink: 0; }
.sxm-footer .sxm-diamond-mark { width: 7px; height: 7px; margin-right: 8px; }
@keyframes sxm-float {
  0%, 100% { transform: rotate(45deg) translateY(0); }
  50% { transform: rotate(45deg) translateY(-14px); } }
@keyframes sxm-shimmer {
  0% { background-position: -200% 0; }
  100% { background-position: 200% 0; } }
@media (prefers-reduced-motion: reduce) {
  .sxm-cta::before, .sxm-diamond { animation: none !important; }
  .sxm-cta:hover, .sxm-card:hover, .sxm-card-lite:hover { transform: none; }
}"""

# Site Arc 10 "wow" — the depth layers the shell OWNS (the atelier
# validator bans url()/fixed positioning in bespoke css; shell css is
# ours): the WHISPER VOICE (the third type voice — micro-caps at
# 9-11px, wide tracking, muted — the ~40:1 scale gap against the
# display face is what makes the display feel monumental), ghost
# chapter numerals (huge serif indexes at ~5% ink, injected by
# render_page onto major sections), and the dark-ground accent orb
# (blur(120px) at 6-8%, slow 9s pulse; markup emitted by page_shell on
# dark palettes only, hidden on mobile + reduced-motion). All
# sub-perceptual — depth the eye discovers, never notices.
_WOW_CSS = """
/* The whisper voice — the third type voice (Site Arc 10). */
.sxm-whisper { font-family: var(--sx-font-body); font-size: .68rem; font-weight: 600;
  letter-spacing: .22em; text-transform: uppercase; color: var(--sx-muted);
  font-style: normal; }
/* Double-class boosts: the utility must win over the module rules that
   style these elements (module css is emitted after base_css). */
.sxm-off-price.sxm-whisper { font-family: var(--sx-font-body); font-size: .7rem;
  font-weight: 650; letter-spacing: .22em; color: var(--sx-muted); }
.sxm-eyebrow.sxm-whisper { font-size: .66rem; letter-spacing: .3em; font-weight: 600;
  color: var(--sx-muted); }
.sxm-footer-inner.sxm-whisper { font-size: .66rem; letter-spacing: .18em; }
.sxm-contact-social a.sxm-whisper { font-size: .68rem; font-weight: 600;
  letter-spacing: .2em; }
/* Ghost chapter numerals — sub-perceptual section indexes (~5% ink). */
.sxm-ghostnum-host { position: relative; }
.sxm-ghostnum-host > .sxm-inner { position: relative; z-index: 1; }
.sxm-ghostnum { position: absolute; top: clamp(10px, 3vw, 30px); right: clamp(8px, 4vw, 48px);
  font-family: var(--sx-font-heading); font-weight: var(--sx-heading-weight);
  font-size: clamp(4rem, 9vw, 7rem); line-height: 1; letter-spacing: var(--sx-letter-tight);
  color: var(--sx-text); opacity: .05; pointer-events: none; user-select: none; z-index: 0; }
.sxm-ghostnum.sxm-gn-left { right: auto; left: clamp(8px, 4vw, 48px); }
/* The dark-ground accent orb — one blurred pool of brand light. */
.sxm-depth-orb { position: fixed; top: -12vw; right: -14vw; width: 46vw; height: 46vw;
  border-radius: 50%; background: var(--sx-accent); filter: blur(120px); opacity: .07;
  z-index: -1; pointer-events: none;
  animation: sxm-orb-pulse 9s ease-in-out infinite alternate; }
@keyframes sxm-orb-pulse {
  from { opacity: .055; transform: scale(1); }
  to { opacity: .08; transform: scale(1.06); } }
@media (max-width: 768px) { .sxm-depth-orb { display: none; } }
@media (prefers-reduced-motion: reduce) { .sxm-depth-orb { display: none; } }"""

# Film-grain finish (Arc 3, quality-bar signature): ultra-subtle static
# noise over the whole page. pointer-events: none — purely atmospheric.
_GRAIN_CSS = (
    "\nbody::after { content: \"\"; position: fixed; inset: 0; z-index: 9998;"
    " pointer-events: none; background-image: " + GRAIN_DATA_URI + ";"
    " background-size: 160px 160px; opacity: .02; }"
)


_SHADOWS_LIGHT = {
    "{SHADOW_REST}": "color-mix(in srgb, var(--sx-text) 8%, transparent)",
    "{SHADOW_HOVER}": "color-mix(in srgb, var(--sx-text) 12%, transparent)",
    "{SHADOW_HOVER_LITE}": "color-mix(in srgb, var(--sx-text) 11%, transparent)",
}
_SHADOWS_DARK = {
    "{SHADOW_REST}": "rgba(0, 0, 0, .45)",
    "{SHADOW_HOVER}": "rgba(0, 0, 0, .55)",
    "{SHADOW_HOVER_LITE}": "rgba(0, 0, 0, .50)",
}


def _quality_css(dna: Dict[str, Any]) -> str:
    """_QUALITY_CSS with the card shadows toned for the palette mode."""
    dark = ((dna.get("palette") or {}).get("mode") == "dark")
    css = _QUALITY_CSS
    for k, v in (_SHADOWS_DARK if dark else _SHADOWS_LIGHT).items():
        css = css.replace(k, v)
    return css


def base_css(dna: Dict[str, Any]) -> str:
    motion = dna.get("motion", "standard")
    # Quality-floor arc 7: reveal travels 48px over .9s — the bar's
    # "things don't rush in, they arrive" (was 18px/.7s).
    reveal_css = "" if motion == "subtle" else """
/* Site quality (2026-07-14): gentler rise (32px -> 14px). A shorter travel
   still reads as an arrival but stops the compositor-promoted edge from
   flashing a 1px seam against the fixed grain/blur layers mid-transition. */
.sxm-reveal { opacity: 0; transform: translateY(14px); transition: opacity .8s var(--sx-ease), transform .8s var(--sx-ease); }
.sxm-reveal.sxm-in { opacity: 1; transform: none; }
/* Slide cleanup (2026-07-10): late reveals — the 6s failsafe, or any
   section revealed while off-screen — SNAP instead of sliding, so the
   failsafe never plays a wave of drifting sections and off-screen
   arrivals don't animate to nobody. */
.sxm-reveal.sxm-in-snap { transition: none !important; }
.sxm-reveal.sxm-in-snap .sxm-inner > * { transition: none !important; }
/* Motion System (2026-07-10): choreography is staged on ARRIVAL, not on
   page load — the reveal SCRIPT injects a holding rule (animation-name:
   none on everything inside un-arrived .sxm-stage/.sxm-reveal sections)
   and the observer's .sxm-in releases it, so authored entrance chains
   START FRESH the moment the visitor reaches the section instead of
   finishing invisibly at load. The holding rule lives in the script, not
   here: no JS → no holding → animations run natively (never a page held
   invisible). See reveal_script(). */
/* Site Arc 10 — blur-to-focus arrival (body.sx-reveal-focus, selected by
   the DRO's motion energy): sections come into FOCUS — blur 8px→0 with a
   .98→1 settle — instead of rising. Sharper is the entrance, not higher. */
body.sx-reveal-focus .sxm-reveal { transform: scale(.98); filter: blur(8px);
  transition: opacity .8s var(--sx-ease), transform .8s var(--sx-ease), filter .8s var(--sx-ease); }
body.sx-reveal-focus .sxm-reveal.sxm-in { transform: none; filter: blur(0); }
@media (prefers-reduced-motion: reduce) { .sxm-reveal { opacity: 1; transform: none; transition: none; }
  body.sx-reveal-focus .sxm-reveal { filter: none; } }""" + _SIG_CSS
    # motion=subtle stills the LOOPING pieces (CTA shimmer, diamond float,
    # depth orb) — a stilled page keeps the premium statics, drops the
    # perpetual motion.
    loop_kill = ("\n.sxm-cta::before, .sxm-diamond, .sxm-depth-orb { animation: none; }"
                 if motion == "subtle" else "")
    return f"""
*, *::before, *::after {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
/* Anchor-entry fix (2026-07-10, reproduced live at #cta): deep links
   landed section tops UNDER the sticky header — heading text sliced
   by the header band. Every anchor target clears the header. */
[id] {{ scroll-margin-top: 96px; }}
body {{
  margin: 0; background: var(--sx-bg); color: var(--sx-text);
  font-family: var(--sx-font-body); font-size: 16.5px; line-height: 1.65;
  -webkit-font-smoothing: antialiased;
}}
img {{ max-width: 100%; display: block; }}
h1, h2, h3 {{ font-family: var(--sx-font-heading); line-height: 1.08; margin: 0; }}
h1 {{ font-size: var(--sx-h1); font-weight: var(--sx-heading-weight); letter-spacing: var(--sx-letter-tight); }}
h2 {{ font-size: var(--sx-h2); font-weight: var(--sx-h2-weight, var(--sx-heading-weight)); letter-spacing: var(--sx-letter-tight); }}
/* Site quality (2026-07-14): h3 gets a real scale rung (was un-sized, jumping
   straight from a huge h2 to flat body). Modules that style h3 still win. */
h3 {{ font-size: var(--sx-h3, 1.6rem); font-weight: var(--sx-h3-weight, 700);
  line-height: 1.2; letter-spacing: var(--sx-letter-tight); }}
p {{ margin: 0 0 1.15em; max-width: 62ch; }}
/* Lead / caption steps — the intro-paragraph and fine-print rungs. */
.sxm-lead {{ font-size: var(--sx-lead, 1.2rem); line-height: 1.5; max-width: 60ch; }}
.sxm-small {{ font-size: var(--sx-small, .82rem); }}
a {{ color: var(--sx-accent); text-decoration: none; }}
.sxm-section {{ padding: var(--sx-section-pad) var(--sx-gutter); }}
/* Site Arc 11b — dead-band fix: a section straight after a ceremony seam
   trims its top pad ~45% (the interstitial already carries the pause). */
.sxm-section.sxm-after-seam {{ padding-top: calc(var(--sx-section-pad) * 0.55); }}
.sxm-inner {{ max-width: var(--sx-content-max); margin: 0 auto; }}
.sxm-eyebrow {{
  font-size: .76rem; letter-spacing: .26em; text-transform: uppercase;
  color: var(--sx-accent); font-weight: 700; margin-bottom: 14px;
}}
.sxm-accent-word {{ font-style: italic; color: var(--sx-accent); }}
.sxm-mark {{ display: block; margin-bottom: 22px; }}
.sxm-mark-thin {{ width: 48px; height: 3px;
  background: linear-gradient(90deg, var(--sx-accent), var(--sx-accent-soft)); }}
.sxm-mark-soft {{ width: 72px; height: 6px; border-radius: 99px; background: var(--sx-accent-soft); }}
.sxm-mark-block {{ width: 26px; height: 26px; background: var(--sx-accent); }}
.sxm-cta {{
  position: relative; overflow: hidden;
  display: inline-block; padding: 18px 44px; border-radius: var(--sx-radius-button);
  background: var(--sx-accent); color: var(--sx-on-accent); font-weight: 800;
  font-size: 13px; letter-spacing: .18em; text-transform: uppercase;
  box-shadow: 0 16px 40px color-mix(in srgb, var(--sx-accent) 25%, transparent);
  transition: transform .4s var(--sx-ease), background .4s var(--sx-ease), box-shadow .4s var(--sx-ease);
}}
.sxm-cta::before {{ content: ""; position: absolute; inset: 0; pointer-events: none;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, .35), transparent);
  background-size: 200% 100%; animation: sxm-shimmer 2.5s linear infinite; }}
.sxm-cta:hover {{ transform: translateY(-3px); background: var(--sx-accent-strong);
  box-shadow: 0 20px 50px color-mix(in srgb, var(--sx-accent) 35%, transparent); }}
.sxm-muted {{ color: var(--sx-muted); }}
/* Accent scarcity (DRO single_semantic): the accent carries MEANING, so it
   stays on CTAs + links only; decorative accent (eyebrows, marks) goes quiet. */
body.sx-scarce-accent .sxm-eyebrow {{ color: var(--sx-muted); }}
body.sx-scarce-accent .sxm-mark-thin,
body.sx-scarce-accent .sxm-mark-block {{ background: var(--sx-border); }}
body.sx-scarce-accent .sxm-mark-soft {{ background: color-mix(in srgb, var(--sx-muted) 45%, transparent); }}
{reveal_css}
{_quality_css(dna)}{loop_kill}
{_TREATMENT_CSS}
{_RULE_BREAK_CSS}
{_WOW_CSS}
{_GRAIN_CSS}
@media (max-width: 768px) {{ body {{ font-size: 15.5px; }} }}
/* Print + capture tools get the full page — reveal states forced on. */
@media print {{
  .sxm-reveal, .sxm-reveal .sxm-inner > * {{
    opacity: 1 !important; transform: none !important; filter: none !important;
  }}
  /* Motion System: print never advances animations — jump every staged
     entrance to its end state (0s duration + fill lands the to-frame). */
  .sxm-stage, .sxm-stage *, .sxm-stage *::before, .sxm-stage *::after {{
    animation-play-state: running !important;
    animation-duration: 0s !important;
    animation-delay: 0s !important;
    animation-fill-mode: forwards !important;
  }}
}}
"""


def reveal_script(dna: Dict[str, Any]) -> str:
    """Tiny self-contained IntersectionObserver — the only JS a composed
    page ships. Deterministic platform code (same trust model as the
    motion-module injections), never LLM-written."""
    if dna.get("motion", "standard") == "subtle":
        return ""
    # Reveal FAILSAFE (2026-07-10, Kevin's "crash" screenshot): full-page
    # capture tools (and any environment where the observer never fires)
    # snapshot below-the-fold sections at opacity 0 — thousands of pixels
    # of void with only aria-hidden decorations visible, which reads as a
    # crashed page. After 6s everything reveals unconditionally: real
    # visitors keep the scroll choreography for the opening screens, and
    # nothing can stay invisible forever.
    # Slide cleanup (2026-07-10): the failsafe adds sxm-in-snap so late
    # reveals appear instantly — no wave of sections sliding at the 6s
    # mark. Scroll reveals also pre-trigger slightly (rootMargin) so the
    # rise starts as a section ENTERS view rather than after it's there.
    # ANCHOR-ENTRY fix (same day, REPRODUCED live via headless Chrome at
    # /#cta): deep links left in-view sections stuck at opacity 0 — a
    # viewport of black, Kevin's "crash in parts of the site". A page
    # entered via ANY hash reveals everything instantly: a deep-linked
    # visitor came for the content, not the choreography.
    # Motion System (2026-07-10): .sxm-stage roots (bespoke sections) ride
    # the same observer. The script INJECTS the holding rule (animations
    # inside un-arrived sections don't exist yet — animation-name:none),
    # so .sxm-in makes each section's authored entrance chain start fresh
    # on arrival. Injection-from-script means JS-off degrades to native
    # load-time animation, never to a held-invisible page. The end-of-body
    # script runs before first paint, so nothing flashes.
    # NOSCRIPT: reveals would sit at opacity 0 forever without the
    # observer — force them visible (pre-existing hole, now closed).
    return ("<noscript><style>.sxm-reveal{opacity:1 !important;transform:none !important;filter:none !important}"
            "</style></noscript>"
            "<script>(function(){try{"
            "var hold=document.createElement('style');"
            "hold.textContent='.sxm-stage:not(.sxm-in),.sxm-stage:not(.sxm-in) *,"
            ".sxm-stage:not(.sxm-in) *::before,.sxm-stage:not(.sxm-in) *::after,"
            ".sxm-reveal:not(.sxm-in) *,.sxm-reveal:not(.sxm-in) *::before,"
            ".sxm-reveal:not(.sxm-in) *::after{animation-name:none !important}';"
            "document.head.appendChild(hold);"
            "var els=document.querySelectorAll('.sxm-reveal,.sxm-stage');"
            "var all=function(){els.forEach(function(e){"
            "if(!e.classList.contains('sxm-in')){e.classList.add('sxm-in-snap');e.classList.add('sxm-in')}})};"
            "if(location.hash){all();return}"
            "if(!('IntersectionObserver'in window)){all();return}"
            "var io=new IntersectionObserver(function(entries){entries.forEach(function(en){"
            "if(en.isIntersecting){en.target.classList.add('sxm-in');io.unobserve(en.target)}})},"
            "{threshold:.08,rootMargin:'0px 0px 12% 0px'});els.forEach(function(e){io.observe(e)});"
            "window.addEventListener('hashchange',all,{once:true});"
            "setTimeout(all,6000)}catch(e){}})();</script>")


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
    # Site Arc 10 — the DRO's motion energy may swap the reveal grammar
    # to blur-to-focus (body class, same wiring as the signature moves).
    focus = reveal_focus_class(dna, design)
    if focus:
        classes.append(focus)
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
    # Site Arc 10 — the dark-ground depth orb: ONE blurred pool of brand
    # light behind everything (markup on dark palettes only; the CSS
    # hides it on mobile + reduced-motion, motion=subtle stills it).
    dark = ((dna.get("palette") or {}).get("mode") == "dark")
    orb = ('<div class="sxm-depth-orb" aria-hidden="true"></div>\n'
           if dark else "")
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
{orb}{body}
{reveal_script(dna)}
</body>
</html>"""
