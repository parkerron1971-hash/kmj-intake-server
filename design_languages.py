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
/* CTA band: ink-marble material (layered radials), hard cut. */
.sx-lang-mural .sxm-cta-section, .sx-lang-mural .sxm-ctaed { background:
    radial-gradient(90rem 40rem at 15% 20%,
      color-mix(in srgb, var(--sx-accent) 20%, transparent), transparent 60%),
    radial-gradient(70rem 50rem at 85% 80%,
      color-mix(in srgb, var(--sx-accent) 12%, transparent), transparent 55%),
    color-mix(in srgb, #000 88%, var(--sx-accent)); }
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
    if boldness in ("bold", "loud") or tp == "statement":
        return "mural", (f"rubric: boldness={boldness or 'n/a'}, "
                         f"type_voice={tp or 'n/a'}, {photos} photos — "
                         "conviction evidence")
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
