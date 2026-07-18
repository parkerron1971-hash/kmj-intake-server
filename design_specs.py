# design_specs.py
# ─────────────────────────────────────────────────────────────────────
# Phase 3 (Kevin's Kimi Design Integration spec, §5): the nav pattern
# applied again. A generic authored-spec engine + two new surfaces:
#
#   HERO SPEC   (~216 legal heroes)  architecture × eyebrow ×
#               headline scale × atmosphere × CTA pair
#   MOTION SPEC  easing family × stagger density × reveal distance ×
#               hover physics — formalizes the Stage-C tokens into an
#               AUTHORED layer.
#
# Same mechanics as the nav spec: independent axes, schema-validated,
# TTL-cached per build, deterministic fallback (no spec → today's
# rendering, byte-identical). Models never touch markup — hand-written
# CSS renders every legal combination.
#
# Kill switches: SITE_HERO_SPEC=off / SITE_MOTION_SPEC=off; any
# authoring/parse/validation failure returns None (fail-open).
# Doctrine + instructed diversity ride the system prompt for BOTH
# providers (Symmetry Rule).
# ─────────────────────────────────────────────────────────────────────

import json
import logging
import os
import re
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("design_specs")

_TTL_SECONDS = 900.0
_cache: Dict[str, tuple] = {}

HERO_AXES: Dict[str, list] = {
    "architecture":   ["centered", "split", "asymmetric_offset", "banner"],
    "eyebrow":        ["flanked_rules", "side_rule", "none"],
    "headline_scale": ["display", "monumental", "editorial_contrast"],
    "atmosphere":     ["grid_glow", "glow_only", "texture", "none"],
    "cta_pair":       ["solid_ghost", "solid_text", "single"],
}

MOTION_AXES: Dict[str, list] = {
    "easing":          ["cubic_out", "soft_spring", "linear_drift"],
    "stagger_density": ["tight", "loose", "none"],
    "reveal_distance": ["subtle", "standard", "dramatic"],
    "hover_physics":   ["lift", "glow", "underline_slide"],
}

_HERO_SYSTEM_TAIL = """You AUTHOR the hero spec for a website — the axes below, composed, never
the first adequate option (doctrine D12). The hero must earn one
oversized moment (D8) and give its accent an atmospheric home (D4).

Output ONLY a JSON object with exactly these keys and allowed values:
  architecture:   "centered" | "split" | "asymmetric_offset" | "banner"
  eyebrow:        "flanked_rules" (rules flanking the label — implies a
                  centered composition) | "side_rule" | "none"
  headline_scale: "display" | "monumental" (oversized, tight leading) |
                  "editorial_contrast" (scale contrast + italic accent word)
  atmosphere:     "grid_glow" (subtle grid + radial accent glow) |
                  "glow_only" | "texture" | "none"
  cta_pair:       "solid_ghost" | "solid_text" | "single"
Honor every avoid-constraint. JSON only."""

_MOTION_SYSTEM_TAIL = """You AUTHOR the motion character for a website. Motion is physics
(doctrine D7): durations and distances come from the page's boldness
tokens — you choose the CHARACTER, not the numbers.

Output ONLY a JSON object with exactly these keys and allowed values:
  easing:          "cubic_out" (confident settle) | "soft_spring"
                   (a touch of life) | "linear_drift" (calm, editorial)
  stagger_density: "tight" | "loose" | "none"
  reveal_distance: "subtle" | "standard" | "dramatic"
  hover_physics:   "lift" | "glow" | "underline_slide"
Nothing bounces unless the brief says playful. JSON only."""


def _enabled(name: str) -> bool:
    env = "SITE_HERO_SPEC" if name == "hero" else "SITE_MOTION_SPEC"
    return (os.environ.get(env) or "on").strip().lower() not in ("off", "0", "false")


def validate_axes(raw: Any, axes: Dict[str, list],
                  required: str) -> Optional[Dict[str, str]]:
    """Clamp a parsed spec to its axes; `required` names the one axis
    that must be present for the spec to count."""
    if not isinstance(raw, dict):
        return None
    spec: Dict[str, str] = {}
    for key, allowed in axes.items():
        v = raw.get(key)
        if isinstance(v, str):
            vv = v.strip().lower().replace("-", "_").replace("+", "_")
            if vv in allowed:
                spec[key] = vv
    if required not in spec:
        return None
    return spec


def _brief_lines(business: Dict[str, Any], dna: Dict[str, Any],
                 site_prefs: Dict[str, Any]) -> str:
    prefs = site_prefs or {}
    story = prefs.get("story") or {}
    lines = [
        f"Business: {business.get('name') or 'Unknown'} ({business.get('type') or 'general'})",
        f"Design DNA: vibe={dna.get('vibe')}, intensity={dna.get('intensity')}, accent_style={dna.get('accent_style')}",
    ]
    if prefs.get("feel_words"):
        lines.append(f"Feel words: {', '.join(prefs['feel_words'][:3])}")
    if prefs.get("boldness"):
        lines.append(f"Boldness (1 quiet - 3 loud): {prefs['boldness']}")
    if prefs.get("type_personality"):
        lines.append(f"Type voice: {prefs['type_personality']}")
    if prefs.get("creative", {}).get("metaphor"):
        lines.append(f"Metaphor: {str(prefs['creative']['metaphor'])[:160]}")
    if prefs.get("avoid"):
        lines.append(f"AVOID (hard constraints): {str(prefs['avoid'])[:300]}")
    if story.get("atmosphere"):
        lines.append(f"Walking-in feeling: {str(story['atmosphere'])[:200]}")
    return "\n".join(lines)


def _author(name: str, axes: Dict[str, list], system_tail: str,
            required: str, business_id: str, business: Dict[str, Any],
            dna: Dict[str, Any], site_prefs: Dict[str, Any]) -> Optional[Dict[str, str]]:
    if not _enabled(name):
        return None
    cache_key = f"{name}:{business_id}"
    now = time.time()
    hit = _cache.get(cache_key)
    if hit and now - hit[0] < _TTL_SECONDS:
        return hit[1]
    spec: Optional[Dict[str, str]] = None
    try:
        import site_llm
        from design_doctrine import DOCTRINE, DIVERSITY_LINE
        msg = site_llm.create_message(
            model=(os.environ.get("DESIGN_SPEC_MODEL") or "claude-sonnet-4-5-20250929").strip(),
            max_tokens=300,
            system=DOCTRINE + "\n\n" + DIVERSITY_LINE + "\n\n" + system_tail,
            user_content=_brief_lines(business or {}, dna or {}, site_prefs or {}),
            timeout=45.0,
            task=f"{name}_spec",
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text").strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        spec = validate_axes(json.loads(text), axes, required)
        if spec:
            logger.info(f"[design-spec] {name} authored for {business_id[:8]}: {json.dumps(spec)}")
        else:
            logger.warning(f"[design-spec] {name} unusable for {business_id[:8]} — deterministic fallback")
    except Exception as e:
        logger.warning(f"[design-spec] {name} authoring failed for {business_id[:8]} "
                       f"({type(e).__name__}: {e}) — deterministic fallback")
        spec = None
    _cache[cache_key] = (now, spec)
    return spec


def author_hero_spec(business_id: str, business: Dict[str, Any],
                     dna: Dict[str, Any], site_prefs: Dict[str, Any]) -> Optional[Dict[str, str]]:
    return _author("hero", HERO_AXES, _HERO_SYSTEM_TAIL, "architecture",
                   business_id, business, dna, site_prefs)


def author_motion_spec(business_id: str, business: Dict[str, Any],
                       dna: Dict[str, Any], site_prefs: Dict[str, Any]) -> Optional[Dict[str, str]]:
    return _author("motion", MOTION_AXES, _MOTION_SYSTEM_TAIL, "easing",
                   business_id, business, dna, site_prefs)


# ─── Motion spec + Stage-C tokens → CSS custom properties ────────────

_EASING_CSS = {
    "cubic_out":    "cubic-bezier(0.33, 1, 0.68, 1)",
    "soft_spring":  "cubic-bezier(0.34, 1.35, 0.64, 1)",
    "linear_drift": "cubic-bezier(0.25, 0.1, 0.75, 0.9)",
}
_STAGGER_MULT = {"tight": 0.7, "loose": 1.3, "none": 0.0}
_REVEAL_MULT = {"subtle": 0.6, "standard": 1.0, "dramatic": 1.4}


def motion_css_vars(motion_tokens: Optional[Dict[str, Any]],
                    motion_spec: Optional[Dict[str, str]]) -> str:
    """One :root block: Stage-C tokens (the numbers) shaped by the
    authored motion spec (the character). Renderers consume the vars
    with today's values as fallbacks, so absence changes nothing."""
    t = motion_tokens or {}
    s = motion_spec or {}
    dur = float(t.get("duration_s") or 0.4)
    stagger = int(round(int(t.get("stagger_ms") or 70) * _STAGGER_MULT.get(s.get("stagger_density", ""), 1.0)))
    reveal = int(round(int(t.get("reveal_distance_px") or 20) * _REVEAL_MULT.get(s.get("reveal_distance", ""), 1.0)))
    lift = int(t.get("hover_lift_px") or 3)
    ease = _EASING_CSS.get(s.get("easing", ""), _EASING_CSS["cubic_out"])
    hover = s.get("hover_physics") or "lift"
    return (
        ":root { "
        f"--sx-motion-dur: {dur}s; "
        f"--sx-motion-ease: {ease}; "
        f"--sx-stagger: {stagger}ms; "
        f"--sx-reveal-dist: {reveal}px; "
        f"--sx-hover-lift: {lift}px; }}\n"
        f"body {{ --sx-hover-mode: {hover}; }}\n"
        # Hover physics as a shared utility: modules opting in via
        # .sx-hoverable pick up the authored character.
        "body.sx-hover-glow .sx-hoverable:hover { transform: none; "
        "box-shadow: 0 0 24px color-mix(in srgb, var(--sx-accent) 35%, transparent); }\n"
        "body.sx-hover-underline .sx-hoverable:hover { transform: none; }\n"
    )


def motion_body_class(motion_spec: Optional[Dict[str, str]]) -> str:
    hover = (motion_spec or {}).get("hover_physics") or ""
    return {"glow": "sx-hover-glow", "underline_slide": "sx-hover-underline",
            "lift": "sx-hover-lift"}.get(hover, "")


# ─── Hero spec → modifier classes + shared CSS ───────────────────────

def hero_spec_classes(spec: Optional[Dict[str, str]]) -> str:
    if not isinstance(spec, dict) or "architecture" not in spec:
        return ""
    parts = [f"sxh-arch-{spec['architecture']}"]
    for axis in ("eyebrow", "headline_scale", "atmosphere", "cta_pair"):
        if spec.get(axis):
            parts.append(f"sxh-{axis.replace('_', '-')}-{spec[axis].replace('_', '-')}")
    return " ".join(parts)


HERO_SPEC_CSS = """
/* ── Authored hero axes (design_specs.py, Phase 3) — each class is one
      independent decision; absent classes = today's rendering. ── */
/* architecture */
.sxh-arch-centered .sxm-inner { text-align: center; align-items: center;
  display: flex; flex-direction: column; }
.sxh-arch-asymmetric_offset .sxm-inner { margin-left: 0; margin-right: auto;
  max-width: min(720px, 82%); }
@media (min-width: 900px) {
  .sxh-arch-asymmetric_offset .sxm-inner { transform: translateX(6%); }
  .sxh-arch-banner .sxm-inner { max-width: none; width: 100%; }
  .sxh-arch-banner h1 { max-width: 16ch; }
}
/* eyebrow */
.sxh-eyebrow-flanked-rules .sxm-eyebrow { display: inline-flex;
  align-items: center; gap: 14px; }
.sxh-eyebrow-flanked-rules .sxm-eyebrow::before,
.sxh-eyebrow-flanked-rules .sxm-eyebrow::after { content: ""; width: 42px;
  height: 1px; background: var(--sx-accent); opacity: .75; }
.sxh-eyebrow-side-rule .sxm-eyebrow { display: inline-flex;
  align-items: center; gap: 12px; }
.sxh-eyebrow-side-rule .sxm-eyebrow::before { content: ""; width: 34px;
  height: 2px; background: var(--sx-accent); }
.sxh-eyebrow-none .sxm-eyebrow { display: none; }
/* headline scale */
.sxh-headline-scale-monumental h1 { font-size: clamp(3.2rem, 9vw, 7rem);
  line-height: .98; letter-spacing: -0.02em; }
.sxh-headline-scale-editorial-contrast h1 { font-size: clamp(2.4rem, 6vw, 4.6rem); }
.sxh-headline-scale-editorial-contrast h1 em,
.sxh-headline-scale-editorial-contrast h1 i { font-style: italic;
  color: var(--sx-accent); font-size: 1.12em; }
/* atmosphere — overlays on the hero section itself */
.sxh-atmosphere-grid-glow, .sxh-atmosphere-glow-only,
.sxh-atmosphere-texture { position: relative; isolation: isolate; }
.sxh-atmosphere-grid-glow::before { content: ""; position: absolute; inset: 0;
  z-index: -1; pointer-events: none;
  background-image:
    linear-gradient(color-mix(in srgb, var(--sx-text) 4%, transparent) 1px, transparent 1px),
    linear-gradient(90deg, color-mix(in srgb, var(--sx-text) 4%, transparent) 1px, transparent 1px);
  background-size: 56px 56px; }
.sxh-atmosphere-grid-glow::after, .sxh-atmosphere-glow-only::after {
  content: ""; position: absolute; z-index: -1; pointer-events: none;
  width: 60vw; height: 60vw; max-width: 760px; max-height: 760px;
  top: -12%; right: -8%; border-radius: 50%;
  background: radial-gradient(circle,
    color-mix(in srgb, var(--sx-accent) 16%, transparent) 0%, transparent 65%); }
.sxh-atmosphere-texture::before { content: ""; position: absolute; inset: 0;
  z-index: -1; pointer-events: none; opacity: .5;
  background-image: repeating-linear-gradient(45deg,
    color-mix(in srgb, var(--sx-text) 2.5%, transparent) 0 1px, transparent 1px 7px); }
/* cta pair */
.sxh-cta-pair-solid-ghost .sxm-cta ~ .sxm-cta,
.sxh-cta-pair-solid-ghost .sxm-cta.sxm-cta-secondary { background: transparent;
  color: var(--sx-text); box-shadow: inset 0 0 0 1.5px var(--sx-accent); }
.sxh-cta-pair-solid-text .sxm-cta ~ .sxm-cta,
.sxh-cta-pair-solid-text .sxm-cta.sxm-cta-secondary { background: transparent;
  color: var(--sx-accent); box-shadow: none; padding-left: 8px; padding-right: 8px; }
.sxh-cta-pair-single .sxm-cta ~ .sxm-cta { display: none; }
@media (prefers-reduced-motion: reduce) {
  .sxh-atmosphere-grid-glow::after, .sxh-atmosphere-glow-only::after { animation: none; }
}
"""
