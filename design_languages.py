"""
design_languages.py — THE LANGUAGE LIBRARY (2026-07-22, Kevin's go).

A design language is a complete, hand-crafted visual system distilled
from a reference the platform owner curated — the transferable RULES
(band rhythm, texture, type discipline, accent behavior), never the
source's identity. Frameworks decide structure; a language decides
craft; the DRO + atelier + art direction dress the result per business.

Selection is the BRAIN'S: the DRO receives each language's character
sheet (what it believes / when it sings / when it fails) and argues a
choice with a because — validated here, rubric fallback when the DRO
stays silent, logged + persisted either way. Anti-rut: the rubric
never hard-locks one language to a vertical; evidence wins.

Each language ships:
  key / label / source  — identity (source = provenance note)
  believes              — one sentence of creed (rides every prompt)
  sings / fails         — the honest selection evidence
  brief                 — art-direction notes for atelier/AD/hero
  pairing_hint          — type-direction words the DNA resolver understands
  css                   — the deterministic FLOOR (token-driven, scoped
                          under .sx-lang-<key>, targets only modules
                          whose ink it also controls — never repaints
                          arbitrary sections)

Env: DESIGN_LANGUAGES=off — kill switch (default on).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("design_languages")


def enabled() -> bool:
    return (os.environ.get("DESIGN_LANGUAGES") or "on").strip().lower() != "off"


LANGUAGES: Dict[str, Dict[str, Any]] = {
    "mural": {
        "label": "Mural",
        "source": "distilled 2026-07-22 from a speaker/ministry reference "
                  "(color-block bands, textured grounds, person-through-type)",
        "believes": "Conviction is loud, color is courage, the person is "
                    "the message.",
        "sings": "strong portraits, bold or loud boldness, action verbs, "
                 "speaker/creative/ministry/coach energy, statement tastes, "
                 "brands with a saturated accent",
        "fails": "no photography, quiet-luxury or minimal tastes, dense "
                 "professional-services content, owners who chose calm",
        "brief": (
            "MURAL LANGUAGE — execute these instincts: (1) COLOR-BLOCK "
            "RHYTHM: sections commit to one saturated ground each — hard "
            "cuts between bands, never gradient bleeds; at least one "
            "full-accent band and one near-black band per page. (2) EVERY "
            "GROUND HAS A MATERIAL: ink-marble, diagonal ribs, halftone "
            "wash — via CSS gradients only. (3) PERSON THROUGH THE TYPE: "
            "when a portrait exists, the hero may set the display name "
            "gigantic with the portrait overlapping the letters (portrait "
            "in front, type behind). (4) Display type is architectural "
            "caps at monumental scale; hierarchy by weight, not font "
            "variety. (5) Numbers are monuments: stats huge and ghosted "
            "into the band. (6) The accent owns every action; a second "
            "hue may own identity marks only."),
        "pairing_hint": "bold statement architectural caps",
        "standard": "bold_statement",
        "css": """
/* ── MURAL floor — scoped, token-driven, ink-safe ─────────────────── */
/* Stat band becomes a monument wall: full-accent ground, ghosted
   numerals, ink forced dark-on-accent in the same rule. */
.sx-lang-mural .sxm-statband { background:
    linear-gradient(120deg,
      color-mix(in srgb, var(--sx-accent) 96%, #000) 0%,
      color-mix(in srgb, var(--sx-accent) 82%, #000) 100%); }
.sx-lang-mural .sxm-statband .sxm-stat-value,
.sx-lang-mural .sxm-statband .sxm-stat-label {
  color: color-mix(in srgb, #000 82%, var(--sx-accent)); }
.sx-lang-mural .sxm-statband .sxm-stat-value {
  font-size: clamp(4rem, 9vw, 7.5rem); line-height: 1;
  letter-spacing: -0.02em; }
/* CTA band: ink-marble material (layered radials), hard cut.
   CONTRAST GUARANTEE (2026-07-23, the unreadable closing section):
   this band's ground is near-black, so its ink is FORCED light — no
   authored layer may leave dark words on it. */
.sx-lang-mural .sxm-cta-section, .sx-lang-mural .sxm-ctaed { background:
    radial-gradient(90rem 40rem at 15% 20%,
      color-mix(in srgb, var(--sx-accent) 20%, transparent), transparent 60%),
    radial-gradient(70rem 50rem at 85% 80%,
      color-mix(in srgb, var(--sx-accent) 12%, transparent), transparent 55%),
    color-mix(in srgb, #000 88%, var(--sx-accent)); }
.sx-lang-mural .sxm-cta-section h2, .sx-lang-mural .sxm-ctaed h2,
.sx-lang-mural .sxm-cta-section p, .sx-lang-mural .sxm-ctaed p {
  color: #f2eee4 !important; }
.sx-lang-mural .sxm-cta-section .sxm-accent-word,
.sx-lang-mural .sxm-ctaed .sxm-accent-word {
  color: var(--sx-accent) !important; }
.sx-lang-mural .sxm-ctaed .sxm-cta {
  background: var(--sx-accent); color: #14100a; }
/* Footer + contact: diagonal-rib material. */
.sx-lang-mural .sxm-contact { background:
    repeating-linear-gradient(-55deg,
      transparent 0 26px,
      color-mix(in srgb, var(--sx-text) 3%, transparent) 26px 27px),
    var(--sx-bg); }
/* Interstitial seams read as painted band edges, not soft washes. */
.sx-lang-mural .sxm-interstitial { background:
    color-mix(in srgb, var(--sx-accent) 10%, var(--sx-surface)); }
/* Gallery boards go full-conviction: solid accent plates, dark ink. */
.sx-lang-mural .sxm-gal-board { background:
    linear-gradient(140deg,
      color-mix(in srgb, var(--sx-accent) 88%, #000) 0%,
      color-mix(in srgb, var(--sx-accent) 70%, #000) 100%);
  border-color: transparent; }
.sx-lang-mural .sxm-gal-board-line {
  color: color-mix(in srgb, #000 84%, var(--sx-accent));
  font-style: normal; font-weight: 800;
  text-transform: uppercase; letter-spacing: 0.02em;
  font-size: clamp(0.95rem, 1.5vw, 1.2rem); }
.sx-lang-mural .sxm-gal-board-num {
  color: color-mix(in srgb, #000 30%, transparent); }
.sx-lang-mural .sxm-gal-board-rule {
  background: color-mix(in srgb, #000 70%, var(--sx-accent)); }
/* Headings step toward monumental; the accent word drops italic for
   a painted underline instead. */
.sx-lang-mural .sxm-section h2 { text-transform: uppercase;
  letter-spacing: -0.01em; }
.sx-lang-mural .sxm-accent-word { font-style: normal;
  box-shadow: inset 0 -0.18em 0 color-mix(in srgb, var(--sx-accent) 55%, transparent); }
""",
    },
    "monograph": {
        "label": "Monograph",
        "source": "distilled 2026-07-22 from a design-studio reference "
                  "(monochrome frame, the work is the only color, ticker "
                  "ribbon, annotation layer, curved seams)",
        "believes": "The frame stays silent so the work can speak — one "
                    "color on this page: yours.",
        "sings": "portfolio-led businesses with colorful work (designers, "
                 "photographers, beauty, fashion, events), strong personal "
                 "brand + studio portraits, editorial or modern-minimal "
                 "tastes, owners who answered calm or middle boldness",
        "fails": "no portfolio imagery, businesses needing the site itself "
                 "to supply warmth or color, loud tastes, text-heavy "
                 "advisory content",
        "brief": (
            "MONOGRAPH LANGUAGE — execute these instincts: (1) MONOCHROME "
            "FRAME: the page lives on a grayscale ladder (near-black, two "
            "grays, white); the practitioner's WORK is the only color — "
            "gallery and portfolio imagery full-bleed against the quiet "
            "frame. The brand accent appears only as small marks (a star, "
            "a link arrow), never as washes. (2) TICKER RIBBON: one "
            "services marquee in giant caps with star separators as a "
            "section divider. (3) FASHION-EDITORIAL HERO: portrait on a "
            "seamless gray, thin wide headline, tracked-out kicker, "
            "text-link CTA with a long arrow. (4) ANNOTATION LAYER: one "
            "handwritten-style aside or note-card of personal facts — "
            "humanity against the monochrome. (5) Monogram wallpaper: the "
            "business initials repeated tone-on-tone on one dark band. "
            "(6) CURVED SEAMS: at least one section edge arcs instead of "
            "cutting straight."),
        "pairing_hint": "modern minimal thin grotesque editorial",
        "standard": "editorial",
        "css": """
/* ── MONOGRAPH floor — scoped, token-driven ───────────────────────── */
/* The frame goes quiet: headings lighten, tracking opens. */
.sx-lang-monograph .sxm-section h2 { font-weight: 500;
  letter-spacing: 0.02em; }
.sx-lang-monograph .sxm-eyebrow { letter-spacing: 0.42em;
  color: color-mix(in srgb, var(--sx-text) 62%, transparent); }
/* Interstitial seams become the ticker ribbon: giant caps, star
   separators, a slow drift (stilled under reduced motion). */
.sx-lang-monograph .sxm-interstitial { overflow: hidden;
  border-block: 1px solid color-mix(in srgb, var(--sx-text) 14%, transparent);
  background: var(--sx-bg); padding-block: clamp(18px, 3vh, 34px); }
.sx-lang-monograph .sxm-interstitial p,
.sx-lang-monograph .sxm-interstitial .sxm-ceremony-line {
  font-family: var(--sx-font-heading); text-transform: uppercase;
  font-size: clamp(1.6rem, 4.2vw, 3.2rem); letter-spacing: 0.04em;
  white-space: nowrap; width: max-content; margin-inline: auto;
  animation: sxlm-drift 26s ease-in-out infinite alternate; }
.sx-lang-monograph .sxm-interstitial p::before,
.sx-lang-monograph .sxm-interstitial .sxm-ceremony-line::before {
  content: "\\2605\\2002"; color: var(--sx-accent); }
.sx-lang-monograph .sxm-interstitial p::after,
.sx-lang-monograph .sxm-interstitial .sxm-ceremony-line::after {
  content: "\\2002\\2605"; color: var(--sx-accent); }
@keyframes sxlm-drift { from { transform: translateX(4%); }
  to { transform: translateX(-4%); } }
@media (prefers-reduced-motion: reduce) {
  .sx-lang-monograph .sxm-interstitial p,
  .sx-lang-monograph .sxm-interstitial .sxm-ceremony-line {
    animation: none; } }
/* Gallery: the work carries the color — mats dissolve to a whisper so
   nothing competes with the pieces. Boards go quiet-editorial. */
.sx-lang-monograph .sxm-gal-fig:not(.sxm-gal-fig-over) {
  background: transparent; border-color:
    color-mix(in srgb, var(--sx-text) 10%, transparent); }
.sx-lang-monograph .sxm-gal-board { background: var(--sx-bg);
  border: 1px solid color-mix(in srgb, var(--sx-text) 16%, transparent); }
.sx-lang-monograph .sxm-gal-board-line { font-style: normal;
  font-weight: 500; letter-spacing: 0.01em; }
.sx-lang-monograph .sxm-gal-board-num { color:
    color-mix(in srgb, var(--sx-text) 12%, transparent); }
.sx-lang-monograph .sxm-gal-board-rule { height: 1px;
  background: color-mix(in srgb, var(--sx-text) 40%, transparent); }
/* CTAs step back to quiet confidence: outline + arrow, no glow. */
.sx-lang-monograph .sxm-cta { box-shadow: none; }
.sx-lang-monograph .sxm-cta::after { content: "\\2002\\27F6"; }
/* One curved seam: the contact section rises on an arc. */
.sx-lang-monograph .sxm-contact { border-top-left-radius: 50% 4.5rem;
  border-top-right-radius: 50% 4.5rem;
  background: color-mix(in srgb, var(--sx-text) 4%, var(--sx-bg));
  margin-top: -2rem; }
""",
    },
    "broadsheet": {
        "label": "Broadsheet",
        "source": "designed 2026-08-29 for the wider shelf (the builder bench: "
                  "every site drew from three languages)",
        "believes": 'A page you read is a page you trust: the argument is the design.',
        "sings": 'consultants, coaches and advisors with a real story; owners who write; copy-rich businesses with few photos; editorial or classic type tastes',
        "fails": 'photo-led studios, loud brands, businesses with nothing to say yet, owners who chose bold',
        "brief": ("BROADSHEET LANGUAGE — execute these instincts: (1) PAPER GROUND: one warm off-white for the whole page; ink is near-black; the single accent is a printer's red used only for the standfirst, the dateline and the one button. (2) COLUMNS: body copy runs in two or three measured columns with a hairline between them; a drop cap opens the first paragraph of each chapter. (3) DATELINES: every section carries a small mono eyebrow (volume, number, place) — the page's own masthead grammar. (4) RULES EARN INK: a 2px rule under the masthead, 1px hairlines elsewhere, no boxes, no cards. (5) The hero is a headline and a standfirst, not an image; a portrait, when one exists, runs as a cut-out at column width with a caption. (6) Numbers appear in running text, never as monuments."),
        "pairing_hint": "editorial serif columns",
        "standard": "editorial_serif",
        "css": """
/* ── BROADSHEET floor — paper, ink, one red ───────────────────────── */
.sx-lang-broadsheet .sxm-section h2 { font-weight: 600; letter-spacing: -0.01em; }
.sx-lang-broadsheet .sxm-accent-word { font-style: italic;
  color: var(--sx-accent); box-shadow: none; }
.sx-lang-broadsheet .sxm-statband { background: var(--sx-bg);
  border-top: 2px solid var(--sx-text); border-bottom: 1px solid
  color-mix(in srgb, var(--sx-text) 22%, transparent); }
.sx-lang-broadsheet .sxm-statband .sxm-stat-value { font-size: clamp(2rem, 4vw, 3rem);
  font-weight: 600; letter-spacing: -0.01em; }
.sx-lang-broadsheet .sxm-cta-section, .sx-lang-broadsheet .sxm-ctaed {
  background: var(--sx-bg); border-top: 1px solid
  color-mix(in srgb, var(--sx-text) 22%, transparent); }
.sx-lang-broadsheet .sxm-ctaed .sxm-cta { background: var(--sx-accent); color: #fff; border-radius: 0; }
.sx-lang-broadsheet .sxm-interstitial { background: var(--sx-bg);
  border-top: 1px solid color-mix(in srgb, var(--sx-text) 14%, transparent); }
.sx-lang-broadsheet .sxm-contact { background: var(--sx-surface); }
""",
    },
    "signal": {
        "label": "Signal",
        "source": "designed 2026-08-29 for the wider shelf (the builder bench: "
                  "every site drew from three languages)",
        "believes": 'Clarity is generosity: one grid, one colour, nothing that is not information.',
        "sings": 'agencies, systems and process businesses, software-adjacent services, numbered offers, owners who chose modern or minimal, brands with one strong primary colour',
        "fails": 'warm or handmade tastes, ministry intimacy, portfolio-led beauty work, owners who asked for texture',
        "brief": ('SIGNAL LANGUAGE — execute these instincts: (1) WHITE GROUND, ONE COLOUR: the page is white or near-black end to end; the accent is a flat block colour used as solid panels, never a glow or a gradient. (2) THE GRID SHOWS: a strict 12-column grid; hairline column rules may be visible; everything aligns to it, including images. (3) EVERYTHING NUMBERED: offerings, steps and sections carry mono index numbers (01, 02); the numbers are typographic, not decorative. (4) DISPLAY IS A GROTESK: heavy, tight-tracked, oversized headlines set flush-left; no italics anywhere. (5) ARROWS AND BARS: the only ornaments are arrows on links and solid accent bars as section markers. (6) Photos run square-cropped, in the grid, never bleeding.'),
        "pairing_hint": "modern minimal geometric grotesque",
        "standard": "modern_grotesque",
        "css": """
/* ── SIGNAL floor — the grid shows, one flat colour ───────────────── */
.sx-lang-signal .sxm-section h2 { font-weight: 800; letter-spacing: -0.03em; text-transform: none; }
.sx-lang-signal .sxm-accent-word { font-style: normal; color: var(--sx-accent); box-shadow: none; }
.sx-lang-signal .sxm-statband { background: var(--sx-accent); }
.sx-lang-signal .sxm-statband .sxm-stat-value,
.sx-lang-signal .sxm-statband .sxm-stat-label { color: #fff; }
.sx-lang-signal .sxm-statband .sxm-stat-value { font-size: clamp(3rem, 7vw, 5.5rem); font-weight: 800; letter-spacing: -0.04em; }
.sx-lang-signal .sxm-cta-section, .sx-lang-signal .sxm-ctaed { background: var(--sx-text); }
.sx-lang-signal .sxm-cta-section h2, .sx-lang-signal .sxm-ctaed h2,
.sx-lang-signal .sxm-cta-section p, .sx-lang-signal .sxm-ctaed p { color: var(--sx-bg) !important; }
.sx-lang-signal .sxm-ctaed .sxm-cta { background: var(--sx-accent); color: #fff; border-radius: 0; }
.sx-lang-signal .sxm-interstitial { background: var(--sx-bg);
  border-top: 4px solid var(--sx-accent); }
.sx-lang-signal .sxm-contact { background: var(--sx-bg);
  border-top: 1px solid color-mix(in srgb, var(--sx-text) 16%, transparent); }
""",
    },
    "atelier": {
        "label": "Atelier",
        "source": "designed 2026-08-29 for the wider shelf (the builder bench: "
                  "every site drew from three languages)",
        "believes": 'The frame is wide and quiet so the work can be looked at, not scrolled past.',
        "sings": 'photographers, lash and beauty artists, florists, luxury services with real photos; calm or middle boldness; owners who chose refined or minimal type',
        "fails": 'no photography, bold or loud tastes, text-heavy advisory content, owners who want colour from the page itself',
        "brief": ('ATELIER LANGUAGE — execute these instincts: (1) BONE GROUND, WIDE MATS: a pale ground; every photo sits inside a wide flat mat with a hairline frame, gallery-hung, with generous white space around it. (2) THIN SERIF, SMALL CAPTIONS: display is a light or regular serif at moderate scale; captions are tiny, tracked mono; nothing bold. (3) ONE MUTED ACCENT: a single muted metallic or clay for roman numerals, hairlines and the one button; never a saturated colour. (4) THE WORK LEADS EVERY CHAPTER: each section opens on an image, then the words. (5) MOTION IS STILL: at most one slow reveal on the hero image; nothing else moves. (6) Stats are a single line of small caps, never large.'),
        "pairing_hint": "refined thin serif quiet luxury",
        "standard": "quiet_luxury",
        "css": """
/* ── ATELIER floor — bone ground, wide mats, one muted accent ─────── */
.sx-lang-atelier .sxm-section h2 { font-weight: 400; letter-spacing: 0.01em; }
.sx-lang-atelier .sxm-accent-word { font-style: italic; color: var(--sx-accent); box-shadow: none; }
.sx-lang-atelier .sxm-gal-board { background: var(--sx-surface);
  border: 1px solid color-mix(in srgb, var(--sx-text) 14%, transparent); padding: 1.25rem; }
.sx-lang-atelier .sxm-gal-board-line { font-style: italic; font-weight: 400; text-transform: none; }
.sx-lang-atelier .sxm-statband { background: var(--sx-bg);
  border-top: 1px solid color-mix(in srgb, var(--sx-text) 14%, transparent);
  border-bottom: 1px solid color-mix(in srgb, var(--sx-text) 14%, transparent); }
.sx-lang-atelier .sxm-statband .sxm-stat-value { font-size: clamp(1.4rem, 2.4vw, 2rem); font-weight: 400; letter-spacing: 0.06em; }
.sx-lang-atelier .sxm-cta-section, .sx-lang-atelier .sxm-ctaed { background: var(--sx-surface); }
.sx-lang-atelier .sxm-ctaed .sxm-cta { background: transparent; color: var(--sx-text);
  border: 1px solid var(--sx-accent); border-radius: 0; }
.sx-lang-atelier .sxm-interstitial { background: var(--sx-bg); }
.sx-lang-atelier .sxm-contact { background: var(--sx-bg); }
""",
    },
    "neon": {
        "label": "Neon",
        "source": "designed 2026-08-29 for the wider shelf (the builder bench: "
                  "every site drew from three languages)",
        "believes": 'The sign is on: one colour that glows, the rest is night.',
        "sings": 'barbers, tattoo studios, fitness and gyms, streetwear and drops, nightlife, e-commerce with attitude; bold tastes; dark grounds with one electric accent',
        "fails": 'quiet advisory, therapists and clinical services, elder-facing businesses, owners who chose calm or classic',
        "brief": ("NEON LANGUAGE — execute these instincts: (1) NIGHT GROUND: near-black end to end; surfaces are a shade lighter, never grey cards. (2) ONE COLOUR GLOWS: the accent carries a soft glow (box-shadow or text-shadow tinted with the accent) on the headline word, the live indicator and the one button — nowhere else. (3) CONDENSED CAPS: display is a tall condensed face in uppercase at big scale; body is a plain sans. (4) THE MARQUEE: a single hairline-bound ribbon of the shop's promise runs across the page once (services, hours, walk-ins) — the sign in the window. (5) CHROME HAIRLINES: 1px lines at low alpha separate everything; no boxes with fills. (6) Photos run full-bleed and dark-graded, the accent nowhere in them."),
        "pairing_hint": "condensed impact caps poster",
        "standard": "condensed_impact",
        "css": """
/* ── NEON floor — night ground, one colour that glows ─────────────── */
.sx-lang-neon .sxm-section h2 { text-transform: uppercase; letter-spacing: 0.02em; }
.sx-lang-neon .sxm-accent-word { font-style: normal; color: var(--sx-accent); box-shadow: none;
  text-shadow: 0 0 18px color-mix(in srgb, var(--sx-accent) 55%, transparent); }
.sx-lang-neon .sxm-statband { background: color-mix(in srgb, #000 92%, var(--sx-accent));
  border-top: 1px solid color-mix(in srgb, var(--sx-accent) 40%, transparent);
  border-bottom: 1px solid color-mix(in srgb, var(--sx-accent) 40%, transparent); }
.sx-lang-neon .sxm-statband .sxm-stat-value { color: var(--sx-accent);
  text-shadow: 0 0 22px color-mix(in srgb, var(--sx-accent) 45%, transparent);
  font-size: clamp(3rem, 7vw, 5.5rem); letter-spacing: 0.02em; }
.sx-lang-neon .sxm-statband .sxm-stat-label { color: #e8e8e6; }
.sx-lang-neon .sxm-cta-section, .sx-lang-neon .sxm-ctaed { background: color-mix(in srgb, #000 94%, var(--sx-accent)); }
.sx-lang-neon .sxm-cta-section h2, .sx-lang-neon .sxm-ctaed h2,
.sx-lang-neon .sxm-cta-section p, .sx-lang-neon .sxm-ctaed p { color: #f2f2f0 !important; }
.sx-lang-neon .sxm-ctaed .sxm-cta { background: var(--sx-accent); color: #0a0a0c;
  box-shadow: 0 0 24px color-mix(in srgb, var(--sx-accent) 40%, transparent); }
.sx-lang-neon .sxm-interstitial { background: color-mix(in srgb, #000 90%, var(--sx-accent));
  border-top: 1px solid color-mix(in srgb, var(--sx-accent) 30%, transparent); }
.sx-lang-neon .sxm-contact { background: color-mix(in srgb, #000 96%, var(--sx-accent)); }
""",
    },
    "hearth": {
        "label": "Hearth",
        "source": "designed 2026-08-29 for the wider shelf (the builder bench: "
                  "every site drew from three languages)",
        "believes": 'People first, light second: the room feels held before it is impressive.',
        "sings": 'nonprofits, churches and ministries, community coaches, therapists and wellness practices; warm tastes; a real portrait or people photos; owners who answered gentle or grounded',
        "fails": 'luxury or corporate brands, product drops, owners who asked for edge or minimal, photo-less advisory firms',
        "brief": ('HEARTH LANGUAGE — execute these instincts: (1) DEEP WARM GROUND: a dark green or brown ground with a warm light that seems to come from inside the page (one large soft radial in the accent at low alpha). (2) SOFT CORNERS: photos and panels carry generous rounded corners; nothing sharp, no hairline boxes. (3) A HUMANIST SERIF for display at moderate scale, a rounded sans for body; one hand-set accent line (a caption, a blessing, a promise) in the accent colour. (4) PEOPLE IN THE LIGHT: portraits and gatherings run large and warm-graded; the accent never sits on a face. (5) GENTLE MOTION: reveals ease in slowly; nothing snaps. (6) Stats are stated as people served, gifts, gatherings — in sentences, not monuments.'),
        "pairing_hint": "warm humanist rounded approachable",
        "standard": "warm_humanist",
        "css": """
/* ── HEARTH floor — deep warm ground, soft corners, inner light ───── */
.sx-lang-hearth .sxm-section h2 { font-weight: 600; letter-spacing: 0; }
.sx-lang-hearth .sxm-accent-word { font-style: italic; color: var(--sx-accent); box-shadow: none; }
.sx-lang-hearth .sxm-statband { background:
    radial-gradient(60rem 30rem at 50% 0%, color-mix(in srgb, var(--sx-accent) 22%, transparent), transparent 60%),
    var(--sx-surface); border-radius: 24px; }
.sx-lang-hearth .sxm-statband .sxm-stat-value { font-size: clamp(2rem, 4vw, 3.2rem); font-weight: 600; }
.sx-lang-hearth .sxm-cta-section, .sx-lang-hearth .sxm-ctaed { background:
    radial-gradient(50rem 26rem at 50% 100%, color-mix(in srgb, var(--sx-accent) 18%, transparent), transparent 60%),
    var(--sx-bg); }
.sx-lang-hearth .sxm-ctaed .sxm-cta { background: var(--sx-accent); color: #1f2a24; border-radius: 999px; }
.sx-lang-hearth .sxm-gal-board { border-radius: 18px; }
.sx-lang-hearth .sxm-interstitial { background: color-mix(in srgb, var(--sx-accent) 8%, var(--sx-surface)); }
.sx-lang-hearth .sxm-contact { background: var(--sx-surface); border-radius: 24px 24px 0 0; }
""",
    },
    "ledger": {
        "label": "Ledger",
        "source": "distilled 2026-07-22 from the Kimi noir-gold reference "
                  "(three-font discipline, one wash, texture over emptiness)",
        "believes": "Discipline is the luxury: one gold, one wash, every "
                    "rule earned.",
        "sings": "consultancies, finance/legal/advisory, quiet or middle "
                 "boldness, owners who chose editorial or classic type, "
                 "dark grounds with a metallic accent",
        "fails": "playful brands, photo-led studios wanting color, owners "
                 "who asked for loud",
        "brief": (
            "LEDGER LANGUAGE — execute these instincts: (1) ONE accent-"
            "tinted wash on the whole page, elsewhere the accent is ink: "
            "words, hairlines, one button. (2) Fine grid-line texture on "
            "the hero ground (1px lines at low alpha) instead of empty "
            "dark. (3) Three type roles with strict jobs — display caps, "
            "working sans, serif italic for turns of phrase. (4) Hairline "
            "rules organize; no heavy borders. (5) Numbers set tabular, "
            "small-caps labels with wide tracking."),
        "pairing_hint": "editorial refined condensed display",
        "standard": "refined_luxury",
        "css": """
/* ── LEDGER floor — scoped, token-driven ──────────────────────────── */
.sx-lang-ledger .sxm-hero-statement, .sx-lang-ledger .sxm-hero-anchored {
  background-image:
    linear-gradient(color-mix(in srgb, var(--sx-text) 3%, transparent) 1px, transparent 1px),
    linear-gradient(90deg, color-mix(in srgb, var(--sx-text) 3%, transparent) 1px, transparent 1px);
  background-size: 72px 72px; }
.sx-lang-ledger .sxm-section h2 { letter-spacing: 0.01em; }
.sx-lang-ledger .sxm-eyebrow { letter-spacing: 0.34em; }
.sx-lang-ledger .sxm-gal-board { background: var(--sx-surface);
  border: 1px solid color-mix(in srgb, var(--sx-accent) 45%, transparent); }
.sx-lang-ledger .sxm-gal-board-rule { height: 1px; width: 64px; }
.sx-lang-ledger .sxm-cta { box-shadow: none; }
.sx-lang-ledger .sxm-stat-value { font-variant-numeric: tabular-nums; }
.sx-lang-ledger .sxm-interstitial { border-block: 1px solid
    color-mix(in srgb, var(--sx-accent) 30%, transparent);
  background: transparent; }
""",
    },
}


def character_sheets() -> str:
    """The block the DRO reasons over — every language, honestly stated,
    plus the permission to choose none."""
    lines: List[str] = [
        "DESIGN LANGUAGES — pick the one this business's evidence argues "
        "for, or \"none\" when no language fits better than a neutral "
        "build. State your because from the evidence, not the label."]
    for k, l in LANGUAGES.items():
        lines.append(f'- "{k}" ({l["label"]}): believes {l["believes"]} '
                     f'SINGS with: {l["sings"]}. FAILS on: {l["fails"]}.')
    return "\n".join(lines)


def validate_choice(raw: Any) -> Tuple[Optional[str], str]:
    """Clamp a DRO's language block to reality. Returns (key|None, because)."""
    if not isinstance(raw, dict):
        return None, ""
    choice = str(raw.get("choice") or "").strip().lower()
    because = str(raw.get("because") or "").strip()[:300]
    if choice in LANGUAGES:
        return choice, because
    return None, ""


def rubric_select(ctx: Dict[str, Any]) -> Tuple[Optional[str], str]:
    """Deterministic fallback when the DRO stayed silent — same evidence,
    plainer instinct, honest because."""
    prefs = ctx.get("site_prefs") if isinstance(ctx.get("site_prefs"), dict) else {}
    photos = len(ctx.get("gallery") or [])
    boldness = str(prefs.get("boldness") or "")
    tp = str(prefs.get("type_personality") or "")
    btype = str((ctx.get("business") or {}).get("type") or "").lower()
    # Loudness / a statement type-voice is decisive evidence; after
    # that, WHAT the photos are of (portfolio vs person) separates
    # monograph from mural. Live lesson (2026-07-22): a business-type
    # STRING like 'consultant' must never outvote conviction evidence —
    # a gold-brand statement-voiced ministry got the law-firm language.
    offerings = len(ctx.get("offerings") or [])
    products = len(ctx.get("products") or ctx.get("store_products") or [])
    testimonials = len(ctx.get("testimonials") or [])
    # THE WIDER SHELF (2026-08-29): five more languages, each chosen on
    # evidence that already exists in the context — never a type string
    # alone (the 2026-07-22 lesson still holds).
    if (boldness in ("bold", "loud") or tp in ("statement", "condensed")) and any(
            w in btype for w in ("barber", "tattoo", "fitness", "gym", "street",
                                 "night", "ecommerce", "apparel", "sneaker")):
        return "neon", (f"rubric: boldness={boldness or 'n/a'}, type={btype[:24]!r} "
                        "— a night trade that asked to be loud")
    if boldness in ("bold", "loud") or tp == "statement":
        return "mural", (f"rubric: boldness={boldness or 'n/a'}, "
                         f"type_voice={tp or 'n/a'}, {photos} photos — "
                         "conviction evidence")
    if photos >= 5 and boldness in ("", "calm", "quiet", "middle", "medium") and any(
            w in btype for w in ("photo", "lash", "beauty", "brow", "florist", "wedding",
                                 "esthet", "skin", "luxury", "jewel")):
        return "atelier", (f"rubric: {photos} photos, boldness={boldness or 'unset'}, "
                           f"type={btype[:24]!r} — the work wants a quiet frame")
    if any(w in btype for w in ("nonprofit", "church", "minist", "faith", "community",
                                "therap", "counsel", "wellness")) and boldness not in ("bold", "loud"):
        return "hearth", (f"rubric: type={btype[:24]!r}, boldness={boldness or 'unset'} "
                          "— a people trade that did not ask for edge")
    if tp in ("modern", "minimal", "geometric") and any(
            w in btype for w in ("agency", "software", "saas", "tech", "system", "consult", "market")):
        return "signal", (f"rubric: type_personality={tp!r}, type={btype[:24]!r} "
                          "— systems want a grid")
    if photos < 3 and (offerings >= 4 or testimonials >= 2) and any(
            w in btype for w in ("coach", "consult", "advis", "writer", "author", "speak")) \
            and tp in ("", "editorial", "classic", "serif"):
        return "broadsheet", (f"rubric: {photos} photos, {offerings} offerings, "
                              f"{testimonials} testimonials — the words carry the page")
    if photos >= 4 and any(
            w in btype for w in ("design", "photo", "beauty", "fashion",
                                 "salon", "event", "brand", "studio",
                                 "makeup", "stylist")):
        return "monograph", (f"rubric: {photos} portfolio photos, "
                             f"type={btype[:24]!r}, boldness="
                             f"{boldness or 'unset'} — the work carries "
                             "the color")
    if photos >= 3 and any(
            w in btype for w in ("creativ", "minist", "church", "coach",
                                 "speak", "artist", "media")):
        return "mural", (f"rubric: {photos} photos, "
                         f"person-forward type={btype[:24]!r}")
    if (tp in ("editorial", "classic")
            or (photos < 3 and any(
                w in btype for w in ("law", "account", "financ", "consult",
                                     "advis", "insur")))):
        return "ledger", (f"rubric: type_personality={tp or 'n/a'}, "
                          f"type={btype[:24]!r}, {photos} photos")
    return None, "rubric: no language fits better than neutral"


def resolve(ctx: Dict[str, Any], dro: Optional[Dict[str, Any]]) -> Tuple[Optional[str], str, str]:
    """(key|None, because, chooser). NEVER raises."""
    if not enabled():
        return None, "", "disabled"
    try:
        d = (dro or {}).get("decisions") or (dro or {}) or {}
        key, because = validate_choice(d.get("language"))
        if key:
            return key, because, "dro"
        key, because = rubric_select(ctx)
        return key, because, "rubric"
    except Exception as e:
        logger.warning(f"[languages] resolve failed open: {e}")
        return None, "", "error"


def css_for(key: Optional[str]) -> str:
    return LANGUAGES.get(key or "", {}).get("css", "")


def brief_for(key: Optional[str]) -> str:
    return LANGUAGES.get(key or "", {}).get("brief", "")


def label_for(key: Optional[str]) -> str:
    return LANGUAGES.get(key or "", {}).get("label", "")
