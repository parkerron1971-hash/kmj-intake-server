"""Pass 4.0i Phase C — Composer-side creative_expression inference + persistence.

Three responsibilities:

  1. INFERENCE — when Composer must pick font_id / accent_id / intensity
     without a practitioner choice, infer from the enriched brief.
     Pure-Python heuristics on archetype + brand_metaphor + tone words.
     Used by hero_composer's post-validation normalizer as a server-side
     safety net AND used to pre-warm the system-recommendation hint in
     the user prompt.

  2. RESOLUTION — given (a) the practitioner's stored creative_expression
     with per-field source markers and (b) Composer's freshly-inferred
     values, produce the FINAL composition's creative_expression.
     Practitioner-set values are sticky; inferred values are re-computed
     on every build to track evolving brand context.

  3. PERSISTENCE — write the final creative_expression back to
     businesses.settings.brand_kit.creative_expression with a sibling
     creative_expression_meta carrying per-field source markers
     (inferred | practitioner). Surgical PATCH — does NOT push a brand-kit
     history snapshot (history is for practitioner-driven kit changes,
     not every server-side inference re-run).

Field source semantics:
  inferred     — Composer chose this value (or a prior Composer did);
                 future builds may re-infer freely.
  practitioner — practitioner explicitly set this via the Brand Kit UI;
                 future builds MUST honor it (never overwrite).
  missing field in meta = same as "inferred" — re-infer freely.

Vocabulary lock per Pass 4.0i Phase B finalize (5 fonts, 6 accents,
3 intensities). Source of truth: agents/design_modules/studio_brut/
hero/creative_expression/fonts.py + accent_renderer.py.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from agents.design_modules.studio_brut.hero.creative_expression import (
    STUDIO_BRUT_FONT_IDS,
    STUDIO_BRUT_FONT_DEFAULT,
    STUDIO_BRUT_ACCENT_IDS,
    STUDIO_BRUT_ACCENT_DEFAULT,
    INTENSITY_CONFIG,
    INTENSITY_DEFAULT,
)

logger = logging.getLogger(__name__)

# ─── Vocabulary surface ────────────────────────────────────────────

VALID_INTENSITIES: List[str] = list(INTENSITY_CONFIG.keys())

VALID_SOURCES = frozenset({"inferred", "practitioner"})


# ─── Inference heuristics ──────────────────────────────────────────

# Tokens that strongly suggest each font choice. Matched case-insensitive
# against any of the brief's free-text fields (archetype label, vibe,
# brand_metaphor, tone_words). Order matters — first font with a hit wins.
# Intentionally narrow keyword sets — better to default to brutalist_default
# than to over-claim.
_FONT_KEYWORDS: List[Tuple[str, List[str]]] = [
    # Editorial: serif, writer, publisher, narrative, refined-maker
    ("brutalist_editorial", [
        "editorial", "publisher", "publishing", "writer", "author",
        "narrative", "literary", "essay", "journal", "magazine",
        "refined-maker", "considered editorial",
    ]),
    # Mono: technical, code, developer, software, engineering
    ("brutalist_mono", [
        "technical", "developer", "developers", "software", "engineering",
        "engineer", "code", "code-native", "devtool", "saas", "platform",
        "infrastructure",
    ]),
    # Sharp: refined-heavy, fashion, premium-considered, design-aware
    ("brutalist_sharp", [
        "premium", "fashion", "refined-heavy", "considered-fashion",
        "luxury streetwear", "design-aware", "considered urban",
        "refined", "considered",
    ]),
    # Geometric: precision, architectural, engineered, design-firm
    ("brutalist_geometric", [
        "geometric", "engineered", "architectural", "precision",
        "machined", "design firm", "design studio", "branding agency",
        "tech-adjacent",
    ]),
    # Default (Bebas/condensed) gets the broad streetwear/poster catch-all.
    # Explicit tokens so the brief can still steer toward it.
    ("brutalist_default", [
        "streetwear", "urban", "custom apparel", "poster", "graphic",
        "skate", "music", "subculture", "merch",
    ]),
]


def infer_font_id(brief: Dict[str, Any]) -> Tuple[str, str]:
    """Pick a font_id from the brief. Returns (font_id, reason_str).

    Strategy: scan the brief's free-text fields for category-signal tokens;
    first match wins. Fall back to brutalist_default with the streetwear/
    poster catch-all reason.

    `reason_str` is a short human-readable string for the Composer's
    reasoning section and the inferred-value audit trail.
    """
    haystack = _brief_haystack(brief)
    for font_id, tokens in _FONT_KEYWORDS:
        hit = _first_token_hit(haystack, tokens)
        if hit:
            return font_id, f"matched {hit!r} in brief"
    return STUDIO_BRUT_FONT_DEFAULT, "no category signal; default condensed poster"


def infer_intensity(brief: Dict[str, Any]) -> Tuple[str, str]:
    """Pick an intensity from the brief. Returns (intensity, reason_str).

    Heuristic ladder:
      statement-forward / loud / declarative / identity-forward -> bold
      creative / personality-led / maker / expressive            -> confident
      authority / established / professional / restrained        -> restrained
      otherwise: confident (mid-tier default — leans into Studio Brut's
      'lean loud' baseline without going maximum)
    """
    haystack = _brief_haystack(brief)
    BOLD_TOKENS = [
        "statement", "loud", "declarative", "identity-forward",
        "manifesto", "shout", "maximum", "bold", "poster-grade",
    ]
    CONFIDENT_TOKENS = [
        "creative", "personality-led", "maker", "expressive",
        "considered-loud", "confident", "warm-warm", "lively",
    ]
    RESTRAINED_TOKENS = [
        "authority", "established", "professional", "restrained",
        "editorial-quiet", "quiet", "minimal", "subtle",
        "thought leadership", "consultancy",
    ]
    hit = _first_token_hit(haystack, BOLD_TOKENS)
    if hit:
        return "bold", f"matched {hit!r} (statement-forward)"
    hit = _first_token_hit(haystack, RESTRAINED_TOKENS)
    if hit:
        return "restrained", f"matched {hit!r} (authority/quiet)"
    hit = _first_token_hit(haystack, CONFIDENT_TOKENS)
    if hit:
        return "confident", f"matched {hit!r} (creative/personality)"
    return "confident", "no clear signal; default mid-tier (Studio Brut leans loud)"


def infer_accent_id(brief: Dict[str, Any]) -> Tuple[str, str]:
    """Pick an accent from the brief. Returns (accent_id, reason_str).

    Conservative bias: default to no_accent unless the brand archetype
    strongly suggests a specific accent. Per design doc §3.2, accents are
    optional signature moments — the variant + treatment + font already
    carry brand; an accent is bonus character.

    Heuristic:
      'EST. YYYY' / founded-year / heritage / volume / issue   -> code_label
      design-firm / identity-driven / stamp                    -> geometric_stamp
      single-initial / monogram brands                         -> type_initial
      quote-driven / declarative-loud                          -> oversized_punctuation
      otherwise: no_accent
    """
    haystack = _brief_haystack(brief)
    if _first_token_hit(haystack, [
        "est.", "established", "heritage", "volume", "issue",
        "vol.", "edition", "since", "founded",
    ]):
        return "code_label", "founded-year / heritage signal -> code label"
    if _first_token_hit(haystack, [
        "monogram", "single initial", "initial-driven",
        "single-character", "brand letter",
    ]):
        return "type_initial", "single-initial brand -> type_initial accent"
    if _first_token_hit(haystack, [
        "quote-driven", "declarative-loud", "manifesto",
        "exclamation", "punchy",
    ]):
        return "oversized_punctuation", "quote-led / declarative -> oversized punctuation"
    if _first_token_hit(haystack, [
        "design studio", "design firm", "branding agency",
        "stamp", "badge", "identity-driven",
    ]):
        return "geometric_stamp", "design-firm / identity-driven -> geometric stamp"
    return STUDIO_BRUT_ACCENT_DEFAULT, "no strong accent signal; default no_accent"


def infer_all(brief: Dict[str, Any]) -> Dict[str, str]:
    """Convenience: run all three inferences and return a dict shaped like
    a CreativeExpression. Used by post-validation fallback when Composer
    omits the creative_expression field entirely."""
    font_id, _ = infer_font_id(brief)
    accent_id, _ = infer_accent_id(brief)
    intensity, _ = infer_intensity(brief)
    return {
        "font_id": font_id,
        "accent_id": accent_id,
        "intensity": intensity,
    }


# ─── Validation ────────────────────────────────────────────────────

def validate_creative_expression(
    raw: Optional[Dict[str, Any]],
    brief: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, str], List[str]]:
    """Validate a creative_expression dict against the locked vocabulary.

    Per-field fallback strategy (NOT all-or-nothing — invalid font_id
    falls back independently of valid accent_id, etc.):
      - missing or invalid field -> fall back to inferred value (or
        STUDIO_BRUT_FONT_DEFAULT / STUDIO_BRUT_ACCENT_DEFAULT /
        INTENSITY_DEFAULT if brief is None)
      - log a warning per invalid field

    Returns (validated_ce_dict, warnings_list). Caller can check warnings
    to decide whether the composition should be flagged.
    """
    warnings: List[str] = []
    raw = raw or {}
    inferred = infer_all(brief or {}) if brief is not None else {
        "font_id": STUDIO_BRUT_FONT_DEFAULT,
        "accent_id": STUDIO_BRUT_ACCENT_DEFAULT,
        "intensity": INTENSITY_DEFAULT,
    }

    out: Dict[str, str] = {}

    # font_id
    raw_font = raw.get("font_id")
    if raw_font in STUDIO_BRUT_FONT_IDS:
        out["font_id"] = raw_font
    else:
        out["font_id"] = inferred["font_id"]
        if raw_font is not None:
            warnings.append(
                f"font_id={raw_font!r} not in Studio Brut vocabulary; "
                f"fell back to {out['font_id']}"
            )

    # accent_id
    raw_accent = raw.get("accent_id")
    if raw_accent in STUDIO_BRUT_ACCENT_IDS:
        out["accent_id"] = raw_accent
    else:
        out["accent_id"] = inferred["accent_id"]
        if raw_accent is not None:
            warnings.append(
                f"accent_id={raw_accent!r} not in Studio Brut vocabulary; "
                f"fell back to {out['accent_id']}"
            )

    # intensity
    raw_intensity = raw.get("intensity")
    if raw_intensity in VALID_INTENSITIES:
        out["intensity"] = raw_intensity
    else:
        out["intensity"] = inferred["intensity"]
        if raw_intensity is not None:
            warnings.append(
                f"intensity={raw_intensity!r} not valid; "
                f"fell back to {out['intensity']}"
            )

    return out, warnings


# ─── Resolution (sticky-with-source) ───────────────────────────────

def resolve_creative_expression(
    stored_ce: Optional[Dict[str, Any]],
    stored_meta: Optional[Dict[str, Any]],
    composer_ce: Dict[str, str],
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Apply the sticky-with-source rule.

    For each of the three fields:
      - if stored meta marks the field as 'practitioner', use the stored
        value and keep the 'practitioner' source
      - otherwise (meta missing, or marked 'inferred'): use composer's
        freshly-inferred value and mark source as 'inferred'

    Returns (final_ce, final_meta). final_ce maps field -> chosen value;
    final_meta maps `{field}_source` -> 'inferred' | 'practitioner'.
    """
    stored_ce = stored_ce or {}
    stored_meta = stored_meta or {}

    final_ce: Dict[str, str] = {}
    final_meta: Dict[str, str] = {}

    for field in ("font_id", "accent_id", "intensity"):
        meta_key = f"{field}_source"
        source = stored_meta.get(meta_key)
        if source == "practitioner" and stored_ce.get(field):
            final_ce[field] = stored_ce[field]
            final_meta[meta_key] = "practitioner"
        else:
            final_ce[field] = composer_ce[field]
            final_meta[meta_key] = "inferred"

    return final_ce, final_meta


# ─── Persistence ───────────────────────────────────────────────────

def load_stored_creative_expression(
    business_id: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Fetch the practitioner's stored creative_expression + meta from
    businesses.settings.brand_kit. Returns (ce, meta) — both may be None
    if no creative_expression has ever been stored.

    Soft-fail: any Supabase or brand_engine error returns (None, None)
    so the Composer pipeline falls through to pure inference."""
    try:
        from brand_engine import _sb_get as be_get
    except Exception as e:
        logger.warning(f"[creative_expression.load] brand_engine import failed: {e}")
        return None, None
    try:
        rows = be_get(
            f"/businesses?id=eq.{business_id}&select=settings&limit=1"
        ) or []
        if not rows:
            return None, None
        settings = rows[0].get("settings") or {}
        bk = settings.get("brand_kit") or {}
        return bk.get("creative_expression"), bk.get("creative_expression_meta")
    except Exception as e:
        logger.warning(
            f"[creative_expression.load] fetch failed for {business_id}: "
            f"{type(e).__name__}: {e}"
        )
        return None, None


def persist_creative_expression(
    business_id: str,
    ce: Dict[str, str],
    meta: Dict[str, str],
) -> bool:
    """Surgical PATCH of businesses.settings.brand_kit with the resolved
    creative_expression + meta. Preserves all other brand_kit keys
    (colors, fonts, tagline, etc.). Does NOT push a brand_kit_history
    snapshot — history is reserved for practitioner-driven kit edits,
    not server-side re-inference noise.

    Returns True on success, False on any failure (soft-fail; never
    raises since persistence is non-blocking to the composition output)."""
    try:
        from brand_engine import _sb_get as be_get, _sb_patch as be_patch
    except Exception as e:
        logger.warning(f"[creative_expression.persist] brand_engine import failed: {e}")
        return False
    try:
        rows = be_get(
            f"/businesses?id=eq.{business_id}&select=settings&limit=1"
        ) or []
        if not rows:
            logger.warning(
                f"[creative_expression.persist] no business row for {business_id}"
            )
            return False
        settings = dict(rows[0].get("settings") or {})
        bk = dict(settings.get("brand_kit") or {})
        bk["creative_expression"] = dict(ce)
        bk["creative_expression_meta"] = {
            **dict(meta),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        settings["brand_kit"] = bk
        be_patch(
            f"/businesses?id=eq.{business_id}",
            {"settings": settings},
        )
        return True
    except Exception as e:
        logger.warning(
            f"[creative_expression.persist] patch failed for {business_id}: "
            f"{type(e).__name__}: {e}"
        )
        return False


# ─── Internal helpers ──────────────────────────────────────────────

def _brief_haystack(brief: Dict[str, Any]) -> str:
    """Concatenate all free-text fields of an enriched brief into one
    case-folded blob for keyword scanning. Pulls the obvious slots —
    intentionally broad rather than picky so a brief that uses a
    relevant keyword anywhere reaches the heuristic."""
    if not isinstance(brief, dict):
        return ""
    parts: List[str] = []
    for key in (
        "inferred_archetype", "content_archetype",
        "inferred_vibe", "brand_metaphor", "brand_metaphor_application",
        "audience_profile", "business_description", "business_name",
    ):
        v = brief.get(key)
        if isinstance(v, str):
            parts.append(v)
    # tone_words is typically a list of short strings
    tw = brief.get("tone_words")
    if isinstance(tw, list):
        parts.extend(s for s in tw if isinstance(s, str))
    # emotional_progression is also a list
    ep = brief.get("emotional_progression")
    if isinstance(ep, list):
        parts.extend(s for s in ep if isinstance(s, str))
    return " ".join(parts).lower()


_WORD_BOUNDARY_LEFT = re.compile(r"(?:^|[^A-Za-z0-9])")
_WORD_BOUNDARY_RIGHT = re.compile(r"(?:[^A-Za-z0-9]|$)")


def _first_token_hit(haystack: str, tokens: List[str]) -> Optional[str]:
    """Return the first token from `tokens` found in haystack (case-folded
    already), or None. Word-boundary match — token must be flanked by
    non-alphanumeric characters (or string edges). Prevents false positives
    like 'author' matching inside 'authority' (the Pass 4.0i Phase C initial
    sanity-test caught this). Tokens with embedded punctuation
    (e.g. 'code-native', 'est.') still match because the boundary check
    is on the surrounding characters of the full token, not its internals."""
    for tok in tokens:
        tok_lc = tok.lower()
        # Manual scan for occurrences with adjacent non-alphanumeric flanking.
        start = 0
        n = len(tok_lc)
        while True:
            idx = haystack.find(tok_lc, start)
            if idx < 0:
                break
            left_ok = (idx == 0) or not haystack[idx - 1].isalnum()
            right_idx = idx + n
            right_ok = (right_idx == len(haystack)) or not haystack[right_idx].isalnum()
            if left_ok and right_ok:
                return tok
            start = idx + 1
    return None
