# design_invariants.py
# ─────────────────────────────────────────────────────────────────────
# Phase 2, §3-G (Kevin's Kimi Design Integration spec): three
# deterministic invariants graded against the RENDERED page.
#
#   MOTIF-1    each accent appears as NON-typographic material often
#              enough (doctrine D3) — accents living only in type read
#              as template.
#   RHYTHM-1   section vertical spacing comes from the page's rhythm
#              scale (doctrine D5) — no ad-hoc margins.
#   CONTRAST-1 body text meets WCAG AA against its ground.
#
# Rollout safety: severity is ADVISORY by default — findings flow into
# the critique/feedback stream and telemetry without failing builds.
# env DESIGN_INVARIANTS=enforce promotes them to HIGH (build-affecting)
# once renderers consume the rhythm tokens (Phase 3). This is the
# spec's fail-open ethos applied to its own verification layer.
# ─────────────────────────────────────────────────────────────────────

import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("design_invariants")

# CSS properties that count as "material" (non-typographic) accent use.
_MATERIAL_PROPS = (
    "background", "background-color", "background-image", "border",
    "border-top", "border-bottom", "border-left", "border-right",
    "border-color", "box-shadow", "outline", "fill", "stroke",
)
_ACCENT_TOKENS = ("--sx-accent", "var(--sx-accent", "--sx-secondary", "var(--sx-secondary")

_HEX_RE = re.compile(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")


def _severity() -> str:
    return ("HIGH" if (os.environ.get("DESIGN_INVARIANTS") or "").strip().lower() == "enforce"
            else "ADVISORY")


def _finding(rule_id: str, description: str, evidence: str, fix_hint: str) -> Dict[str, Any]:
    return {
        "rule_id": rule_id,
        "severity": _severity(),
        "description": description,
        "evidence": evidence[:400],
        "fix_hint": fix_hint,
    }


# ─── MOTIF-1 ─────────────────────────────────────────────────────────

def check_motif(html: str, css: str) -> Optional[Dict[str, Any]]:
    """Accent-as-material count vs. page length. Approximation of the
    spec's '≥1 per 100vh': require one material accent use per ~3
    sections (a screenful is roughly 2-3 sections)."""
    sections = max(1, html.count("<section"))
    required = max(1, round(sections / 3))
    material_uses = 0
    for decl in re.finditer(r"([a-z\-]+)\s*:\s*([^;{}]+)[;}]", css):
        prop, value = decl.group(1).strip(), decl.group(2)
        if any(prop.startswith(mp) for mp in _MATERIAL_PROPS):
            if any(tok in value for tok in _ACCENT_TOKENS):
                material_uses += 1
    if material_uses >= required:
        return None
    return _finding(
        "MOTIF-1",
        "Accent color lives almost only in type (doctrine D3).",
        f"{material_uses} material accent use(s) across {sections} sections "
        f"(needed >= {required}): glows, rules, tags, dividers, icon grounds, "
        f"or hover states in the accent color",
        "Give the accent at least one non-typographic home per screenful — "
        "a hairline rule, a soft glow behind the loudest headline, a tag "
        "ground, or an accent hover state.",
    )


# ─── RHYTHM-1 ────────────────────────────────────────────────────────

# F2 (2026-07-18): the lookbehind `(?<![\w-])` keeps `scroll-padding-top`
# out — it is anchor math, not section rhythm.
_SECTION_PAD_RE = re.compile(
    r"(?:section|\.sxm-[a-z\-]+)\s*[^{}]*\{[^}]*?"
    r"(?<![\w-])padding(?:-top|-bottom|-block)?\s*:\s*([^;}]+)", re.IGNORECASE)
_PX_RE = re.compile(r"(\d{2,3})px")


def _split_css_shorthand(value: str) -> List[str]:
    """Split a CSS value on TOP-LEVEL whitespace — clamp()/var() arguments
    contain spaces and must stay one component."""
    parts: List[str] = []
    depth = 0
    cur: List[str] = []
    for ch in value.strip():
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch.isspace() and depth == 0:
            if cur:
                parts.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur))
    return parts


def _vertical_padding_components(value: str) -> List[str]:
    """Only the VERTICAL components of a padding shorthand carry section
    rhythm: 1-value → it; 2-value → first; 3/4-value → first + third.
    (The old text scan flagged a button's `18px 44px` HORIZONTAL 44px as
    a rhythm break.)"""
    parts = _split_css_shorthand(value)
    if len(parts) <= 2:
        return parts[:1]
    return [parts[0], parts[2]]


def check_rhythm(css: str, scale: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not scale or not isinstance(scale.get("allowed_px"), list):
        return None
    allowed = scale["allowed_px"]
    tol = int(scale.get("tolerance_px") or 8)
    offenders: List[str] = []
    for m in _SECTION_PAD_RE.finditer(css):
        for comp in _vertical_padding_components(m.group(1)):
            # var(--sx-*) components are token-governed — the tokens are
            # on-scale by construction, so the author's fallback constants
            # inside them are not rhythm evidence.
            if comp.startswith("var("):
                continue
            for px in _PX_RE.findall(comp):
                v = int(px)
                if v < 40:      # small paddings are component-level, not rhythm
                    continue
                if not any(abs(v - a) <= tol for a in allowed):
                    offenders.append(f"{v}px")
    if not offenders:
        return None
    uniq = sorted(set(offenders), key=lambda s: int(s[:-2]))[:8]
    return _finding(
        "RHYTHM-1",
        "Section spacing off the page's rhythm scale (doctrine D5).",
        f"off-scale paddings {', '.join(uniq)} — allowed steps "
        f"{allowed} (±{tol}px)",
        "Snap section vertical padding to the rhythm scale; break rhythm "
        "only at an intentional seam.",
    )


# ─── CONTRAST-1 ──────────────────────────────────────────────────────

def _hex_to_rgb(h: str):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rel_luminance(rgb) -> float:
    def chan(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    la, lb = _rel_luminance(_hex_to_rgb(hex_a)), _rel_luminance(_hex_to_rgb(hex_b))
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def check_contrast(css: str) -> Optional[Dict[str, Any]]:
    """Body text (--sx-text) vs page ground (--sx-bg) must clear AA."""
    def _var(name: str) -> Optional[str]:
        m = re.search(name + r"\s*:\s*(#[0-9a-fA-F]{3,6})", css)
        return m.group(1) if m else None
    text, bg = _var("--sx-text"), _var("--sx-bg")
    if not text or not bg:
        return None  # tokens resolved elsewhere — nothing to grade here
    try:
        ratio = contrast_ratio(text, bg)
    except Exception:
        return None
    if ratio >= 4.5:
        return None
    return _finding(
        "CONTRAST-1",
        "Body text fails WCAG AA against its ground.",
        f"--sx-text {text} on --sx-bg {bg} = {ratio:.2f}:1 (AA needs 4.5:1)",
        "Deepen the ground or lift the text color until the pair clears 4.5:1.",
    )


# ─── Entry ───────────────────────────────────────────────────────────

def check_design_invariants(html: str, css: str,
                            enriched_brief: Optional[Dict[str, Any]] = None
                            ) -> List[Dict[str, Any]]:
    """Run MOTIF-1 / RHYTHM-1 / CONTRAST-1. Never raises."""
    findings: List[Dict[str, Any]] = []
    try:
        from design_tokens import boldness_from_prefs, rhythm_scale
        brief = enriched_brief or {}
        scale = rhythm_scale(boldness_from_prefs(
            brief.get("site_prefs") or {"boldness": brief.get("boldness")}))
    except Exception:
        scale = None
    for fn, args in ((check_motif, (html, css)),
                     (check_rhythm, (css, scale)),
                     (check_contrast, (css,))):
        try:
            f = fn(*args)
            if f:
                findings.append(f)
                logger.info(f"[design-invariant] {f['rule_id']}: {f['evidence'][:160]}")
        except Exception as e:
            logger.warning(f"[design-invariant] {fn.__name__} raised: "
                           f"{type(e).__name__}: {e}")
    return findings
