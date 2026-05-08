"""Pass 3.8f post-Builder quality validation.

Six heuristic checks against Builder output. Returns (passes, warnings).
The caller (build_html) uses this to drive a one-shot retry; if the
second attempt also fails the heuristics, the HTML ships anyway with
warnings persisted to site_config.quality_warnings for diagnostics.

The heuristics are intentionally LOOSE — false positives are tolerable
because the retry handles them. Aggressive checks would cause us to
loop or to ship unnecessarily-stamped warnings.
"""
from __future__ import annotations
import re
from typing import List, Optional, Tuple


def _has_real_hierarchy(html: str) -> bool:
    """Check the page has at minimum h1 + h2 hierarchy."""
    has_h1 = bool(re.search(r"<h1[\s>]", html, re.IGNORECASE))
    has_h2 = bool(re.search(r"<h2[\s>]", html, re.IGNORECASE))
    return has_h1 and has_h2


def _uses_palette_discipline(html: str, palette: list) -> Tuple[bool, str]:
    """Check that key palette colors actually appear in the rendered output."""
    if not palette:
        return True, ""
    # We only require the SEMANTICALLY KEY roles to show up — accent/text/background.
    key_roles = {"background", "primary", "accent", "text"}
    primary_colors: List[str] = []
    for c in palette:
        if not isinstance(c, dict):
            continue
        if c.get("role") in key_roles:
            hex_val = c.get("hex", "")
            if hex_val:
                primary_colors.append(hex_val)
    if not primary_colors:
        return True, ""
    html_lower = html.lower()
    found = sum(1 for c in primary_colors if c.lower() in html_lower)
    if found < len(primary_colors) * 0.6:
        return (
            False,
            f"Only {found}/{len(primary_colors)} key palette colors appear in output",
        )
    return True, ""


# Concept → likely HTML markers. If the signature_moment string mentions
# the concept (case-insensitive), one of the markers should appear in the
# output. Loose check: any single marker counts.
_CONCEPT_MARKERS: dict = {
    "gold rule": ["border", "rule", "<hr", "1px"],
    "drop cap": ["drop-cap", "first-letter", "::first-letter"],
    "eyebrow": ["eyebrow", "kicker", "small-caps", "uppercase"],
    "small caps": ["small-caps", "uppercase", "letter-spacing"],
    "roman numeral": [
        "i.", "ii.", "iii.", "&#8544;", "roman", "i&nbsp;", "ii&nbsp;",
    ],
    "diamond": ["diamond", "♦", "◆", "rotate(45"],
    "asterisk": ["asterisk", "&#42;", "*"],
    "monogram": ["monogram"],
    "watermark": ["watermark", "opacity"],
    "asymmetric": ["asymmetric", "grid-template-columns"],
    "lower-third": ["lower", "bottom", "65%", "70%"],
    "lower third": ["lower", "bottom", "65%", "70%"],
    "pull-quote": ["pull-quote", "blockquote", "italic"],
    "pull quote": ["pull-quote", "blockquote", "italic"],
    "manifesto": ["manifesto", "statement"],
    "section number": ["i.", "ii.", "iii.", "01", "no."],
}


def _has_signature_moment(
    html: str,
    signature_moment: Optional[str],
) -> Tuple[bool, str]:
    """Best-effort check that the signature_moment is reflected.
    Loose: matches any single marker associated with a recognized concept.
    """
    if not signature_moment:
        return True, ""
    sig_lower = signature_moment.lower()
    html_lower = html.lower()

    matched_concept = None
    for concept, markers in _CONCEPT_MARKERS.items():
        if concept in sig_lower:
            matched_concept = concept
            if any(m.lower() in html_lower for m in markers):
                return True, ""
    if matched_concept is not None:
        return False, (
            f"Signature moment references '{matched_concept}' but no markers found in output"
        )
    # Concept we don't have markers for — give benefit of the doubt.
    return True, ""


def _has_voice_proof_quote(html: str, quote: Optional[str]) -> Tuple[bool, str]:
    """Check if voice_proof_quote (or close paraphrase) appears in HTML."""
    if not quote or len(quote) < 20:
        return True, ""
    words = re.findall(r"\b[A-Za-z]{3,}\b", quote)
    if len(words) < 4:
        return True, ""
    head_phrase = " ".join(words[:4]).lower()
    tail_phrase = " ".join(words[-4:]).lower()
    html_lower = html.lower()
    if head_phrase in html_lower or tail_phrase in html_lower:
        return True, ""
    return False, (
        f"voice_proof_quote not found in output (looking for '{head_phrase}')"
    )


_BANNED_LABELS = (
    "what clients say",
    "why choose us",
    "our process",
    "get started today",
    "trusted by",
)


def _avoids_generic_section_labels(html: str) -> Tuple[bool, List[str]]:
    """Detect banned generic section labels rendered as visible text."""
    found: List[str] = []
    for label in _BANNED_LABELS:
        # Look for the label as its own visible text inside an element.
        if re.search(r">\s*" + re.escape(label) + r"\s*<", html, re.IGNORECASE):
            found.append(label)
    return len(found) == 0, found


_BANNED_CTAS = ("get started", "learn more", "click here", "find out more")


def _avoids_generic_ctas(html: str) -> Tuple[bool, List[str]]:
    """Detect banned generic CTA copy inside button/cta-link-shaped elements."""
    found: List[str] = []
    cta_matches = re.findall(
        r"<(?:button|a)[^>]*class=\"[^\"]*(?:cta|button|btn)[^\"]*\"[^>]*>"
        r"([^<]+)</",
        html,
        re.IGNORECASE,
    )
    for cta_text in cta_matches:
        text_lower = cta_text.strip().lower()
        for banned in _BANNED_CTAS:
            if banned in text_lower:
                found.append(cta_text.strip())
                break
    return len(found) == 0, found


def validate_quality(html: str, brief: dict) -> Tuple[bool, List[str]]:
    """Run all quality heuristics against Builder output.

    Returns (passes, warnings). passes is True only when warnings is empty.
    """
    warnings: List[str] = []

    if not _has_real_hierarchy(html):
        warnings.append("Missing h1+h2 hierarchy")

    palette = (brief or {}).get("palette") or []
    palette_ok, palette_msg = _uses_palette_discipline(html, palette)
    if not palette_ok:
        warnings.append(palette_msg)

    sig_ok, sig_msg = _has_signature_moment(html, (brief or {}).get("signature_moment"))
    if not sig_ok:
        warnings.append(sig_msg)

    vq_ok, vq_msg = _has_voice_proof_quote(html, (brief or {}).get("voice_proof_quote"))
    if not vq_ok:
        warnings.append(vq_msg)

    labels_ok, banned_labels = _avoids_generic_section_labels(html)
    if not labels_ok:
        warnings.append(f"Generic section labels found: {', '.join(banned_labels)}")

    ctas_ok, banned_ctas = _avoids_generic_ctas(html)
    if not ctas_ok:
        warnings.append(f"Generic CTA copy found: {', '.join(banned_ctas)}")

    return len(warnings) == 0, warnings
