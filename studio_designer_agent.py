"""Designer Agent — LLM #1.

Picks strand pair + ratio + sub-strand + archetype + accent style,
plus 2 alternatives + rationale. Single Claude Opus call.

Cold-start path: deterministic, no LLM. Uses vocabulary affinity to
return a sensible default pick. Used when bundle has fewer than 2 of
9 voice signals (per studio_vocab_detect.has_meaningful_voice_signal).

Output is persisted into business_sites.site_config.design_recommendation
by the endpoint in public_site.py. Pass 3.8a does NOT consume the output
in rendering yet — that's Pass 3.8c-d.
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Optional, TypedDict

import httpx

from studio_strands import STYLE_STRANDS, STRAND_IDS, get_strand
from studio_substrands import SUB_STRANDS, SUBSTRAND_IDS, get_substrands_for_parent
from studio_design_constants import (
    LAYOUT_ARCHETYPE_IDS, LAYOUT_ARCHETYPE_DESCRIPTIONS,
    ACCENT_STYLE_IDS, SITE_TYPE_IDS,
    is_valid_archetype, is_valid_accent_style,
)
from studio_data import VOCABULARIES


CLAUDE_MODEL = "claude-opus-4-7"
ANTHROPIC_API_BASE = "https://api.anthropic.com/v1/messages"


class DesignAlternative(TypedDict, total=False):
    strand_a_id: str
    strand_a_name: str
    ratio_a: int
    strand_b_id: str
    strand_b_name: str
    ratio_b: int
    rationale: str
    tradeoff: str


class DesignRecommendation(TypedDict, total=False):
    strand_a_id: str
    ratio_a: int
    strand_b_id: str
    ratio_b: int
    sub_strand_id: Optional[str]
    layout_archetype: str
    accent_style: str
    site_type: str
    rationale: str
    alternatives: list
    cold_start: bool
    generated_at: str


# ─── Prompt assembly ─────────────────────────────────────────────


def _build_strand_options_block() -> str:
    lines = []
    for s in STYLE_STRANDS:
        # Truncate DNA to keep prompt tight; designer mostly needs the
        # high-level identity not the full creative essay.
        dna_short = s["dna"][:240]
        lines.append(f"- {s['id']} ({s['name']}): {dna_short}")
    return "\n".join(lines)


def _build_archetype_options_block() -> str:
    lines = []
    for aid in LAYOUT_ARCHETYPE_IDS:
        lines.append(f"- {aid}: {LAYOUT_ARCHETYPE_DESCRIPTIONS[aid]}")
    return "\n".join(lines)


def _build_substrand_index() -> str:
    """Compact one-line-per-strand index of available sub-strands."""
    by_parent: dict = {}
    for sub in SUB_STRANDS:
        by_parent.setdefault(sub["parentStrandId"], []).append(sub["id"])
    lines = []
    for parent_id, sub_ids in by_parent.items():
        lines.append(f"  {parent_id}: {', '.join(sub_ids)}")
    return "\n".join(lines)


def build_director_prompt(
    bundle: dict,
    vocab_id: str,
    products: list,
) -> str:
    """Build the full Director prompt for Claude. Pure function — no IO."""
    bundle = bundle or {}
    business = bundle.get("business") or {}
    voice = bundle.get("voice") or {}
    practitioner = bundle.get("practitioner") or {}
    intel = bundle.get("practitioner_intelligence") or {}
    vocab = VOCABULARIES.get(vocab_id) or {}

    strategy = intel.get("strategy_track") or {}

    # Pull product names for prompt context (max 8)
    product_names = []
    for p in (products or [])[:8]:
        if isinstance(p, dict) and p.get("name"):
            product_names.append(str(p["name"]).strip())
    products_line = "; ".join(product_names) if product_names else "(none)"

    strand_options = _build_strand_options_block()
    archetype_options = _build_archetype_options_block()
    substrand_index = _build_substrand_index()

    return f"""You are the Designer Agent for The Solutionist System — a senior creative director who makes visual identity decisions for practitioners on a multi-tenant platform.

You receive practitioner intelligence and independently decide the design direction. You respond ONLY with a raw JSON object. No markdown. No explanation.

# Practitioner intelligence

Business: {business.get("name") or "Unknown"}
Type: {business.get("type") or "custom"}
Subtype: {business.get("subtype") or "(none)"}
Tagline: {business.get("tagline") or "(none)"}
Elevator pitch: {business.get("elevator_pitch") or "(none)"}
Practitioner: {practitioner.get("display_name") or "(none)"}
Voice tone: {voice.get("tone_original") or voice.get("tone") or "(none)"}
Brand voice (canonical): {voice.get("brand_voice") or "(none)"}
Audience: {voice.get("audience") or "(none)"}

# About Me

{intel.get("about_me") or "(none)"}

# About My Business

{intel.get("about_business") or "(none)"}

# Strategy Track (discovery)

Unique value proposition: {strategy.get("unique_value_proposition") or "(none)"}
Target audience: {strategy.get("target_audience") or "(none)"}
Summary: {strategy.get("summary") or "(none)"}
Practitioner background: {strategy.get("practitioner_background") or "(none)"}

# Their actual offerings

Products / engagements: {products_line}

# Detected vocabulary

Primary: {vocab_id} ({vocab.get("name", "?")})
Section: {vocab.get("section", "?")}
Description: {vocab.get("description", "?")}
Signal words: {", ".join(vocab.get("signal_words") or [])}

# THE 10 STYLE STRANDS YOU CAN CHOOSE FROM

{strand_options}

# THE 30 SUB-STRANDS (refinements of the parent)

{substrand_index}

# THE 6 LAYOUT ARCHETYPES YOU CAN CHOOSE FROM

{archetype_options}

# THE 6 ACCENT STYLES YOU CAN CHOOSE FROM

- ceremonial: diamond marks, gold rules, four-point stars (luxury, faith, sovereign)
- cinematic: film-inspired noir treatments (dark, premium experiential)
- editorial: registration marks, asterisks, double rules (editorial, scholarly)
- cultural-african: Adinkra symbols, kente patterns, geometric grid marks (Black diaspora brands)
- botanical: leaf motifs, vine dividers, organic curves (wellness, natural)
- structural: grid lines, hard rules, technical marks (corporate, technical)

# DECISION RULES

- The ratio (30-70 range) controls copy tone, spacing aggression, warmth, and structural weight simultaneously.
- Pick TWO strands that create productive tension — not one dominant aesthetic alone.
- Higher luxury ratio: more ceremonial copy, longer sentences, gold sparingly.
- Higher brutalist ratio: harder borders, shorter sentences, structural aggression.
- Higher editorial ratio: typographic hierarchy dominates, asymmetry, pull-quotes.
- Higher minimal ratio: radical negative space, one focal element.
- Higher dark ratio: atmospheric depth, glowing accents, cinematic pacing.
- Higher bold ratio: type as illustration, rule-breaking scale.
- Layout archetype should match the brand's structural needs:
  - editorial-scroll for narrative-driven, scholarly, story-led brands
  - showcase for portfolio brands, designers, artists
  - statement for manifesto brands, single-message landings
  - immersive for premium experiential brands
  - split for general service businesses
  - minimal-single for radical minimalist brands
- Accent style should match cultural identity AND aesthetic direction.
- Pick a sub-strand that refines the dominant strand's flavor — its id MUST belong to strand_a_id's parent group.
- Provide 2 alternatives that are genuinely different creative positions, not ratio variations of the same pair.

# DELIVERABLE

Output JSON exactly matching this shape:

{{
  "strand_a_id": "one of: {', '.join(STRAND_IDS)}",
  "ratio_a": <integer 30-70>,
  "strand_b_id": "one of the same set, MUST differ from strand_a_id",
  "ratio_b": <integer, MUST equal 100 - ratio_a>,
  "sub_strand_id": "a valid sub-strand id whose parentStrandId equals strand_a_id, or null",
  "layout_archetype": "one of: {', '.join(LAYOUT_ARCHETYPE_IDS)}",
  "accent_style": "one of: {', '.join(ACCENT_STYLE_IDS)}",
  "site_type": "one of: {', '.join(SITE_TYPE_IDS)}",
  "rationale": "2-3 sentences explaining the creative logic of this pick for THIS practitioner specifically. Reference what you saw in their About Me / About My Business / Strategy Track that drove the choice.",
  "alternatives": [
    {{
      "strand_a_id": "...",
      "strand_a_name": "...",
      "ratio_a": <int>,
      "strand_b_id": "...",
      "strand_b_name": "...",
      "ratio_b": <int>,
      "rationale": "one sentence",
      "tradeoff": "what this alternative gains vs the primary"
    }},
    {{ second alternative same shape }}
  ]
}}

Generate the recommendation now. JSON only. No markdown fences."""


# ─── Cold-start deterministic mapping ────────────────────────────


_COLD_START_MAP: dict = {
    "cultural-identity": {
        "sovereign-authority": ("luxury", 60, "editorial", 40, "luxury-noir", "editorial-scroll", "ceremonial"),
        "expressive-vibrancy": ("bold", 60, "editorial", 40, "bold-statement", "showcase", "cultural-african"),
        "warm-community": ("organic", 60, "editorial", 40, "organic-earth", "editorial-scroll", "botanical"),
        "cultural-fusion": ("editorial", 55, "bold", 45, "editorial-magazine", "showcase", "cultural-african"),
        "diaspora-modern": ("luxury", 55, "editorial", 45, "luxury-warm", "editorial-scroll", "cultural-african"),
        "asian-excellence": ("minimal", 60, "editorial", 40, "minimal-warm", "editorial-scroll", "structural"),
        "indigenous-earth": ("organic", 65, "minimal", 35, "organic-earth", "editorial-scroll", "botanical"),
        "universal-premium": ("luxury", 60, "minimal", 40, "luxury-warm", "split", "ceremonial"),
    },
    "community-movement": {
        "scholar-educator": ("editorial", 60, "luxury", 40, "editorial-magazine", "editorial-scroll", "editorial"),
        "faith-ministry": ("luxury", 55, "organic", 45, "luxury-warm", "editorial-scroll", "ceremonial"),
        "wellness-healing": ("organic", 65, "minimal", 35, "organic-botanical", "editorial-scroll", "botanical"),
        "creative-artist": ("bold", 55, "editorial", 45, "bold-pop", "showcase", "editorial"),
        "activist-advocate": ("brutalist", 55, "bold", 45, "brutalist-raw", "statement", "structural"),
        "street-culture": ("bold", 60, "brutalist", 40, "bold-pop", "showcase", "structural"),
    },
    "life-stage": {
        "rising-entrepreneur": ("editorial", 55, "bold", 45, "editorial-magazine", "split", "editorial"),
        "established-authority": ("luxury", 60, "corporate", 40, "luxury-noir", "split", "ceremonial"),
        "legacy-builder": ("luxury", 65, "editorial", 35, "luxury-noir", "editorial-scroll", "ceremonial"),
        "reinvention": ("editorial", 55, "minimal", 45, "editorial-portfolio", "editorial-scroll", "editorial"),
    },
    "aesthetic-movement": {
        "minimalist": ("minimal", 70, "editorial", 30, "minimal-cold", "minimal-single", "structural"),
        "maximalist": ("bold", 65, "editorial", 35, "bold-statement", "showcase", "editorial"),
        "editorial": ("editorial", 70, "luxury", 30, "editorial-magazine", "editorial-scroll", "editorial"),
        "organic-natural": ("organic", 65, "minimal", 35, "organic-earth", "editorial-scroll", "botanical"),
        "futurist-tech": ("retrotech", 55, "minimal", 45, "retrotech-blueprint", "split", "structural"),
    },
}


def cold_start_recommendation(vocab_id: str) -> DesignRecommendation:
    """Deterministic strand pair from vocabulary affinity. No LLM call."""
    vocab = VOCABULARIES.get(vocab_id) or {}
    section = vocab.get("section", "aesthetic-movement")

    section_map = _COLD_START_MAP.get(section) or {}
    pick = section_map.get(vocab_id)

    # Defensive fallback if vocab is unmapped
    if not pick:
        pick = ("editorial", 55, "minimal", 45, "editorial-magazine", "split", "editorial")

    a_id, ratio_a, b_id, ratio_b, sub_id, archetype, accent = pick

    a_strand = get_strand(a_id) or {}
    b_strand = get_strand(b_id) or {}

    return {
        "strand_a_id": a_id,
        "ratio_a": ratio_a,
        "strand_b_id": b_id,
        "ratio_b": ratio_b,
        "sub_strand_id": sub_id,
        "layout_archetype": archetype,
        "accent_style": accent,
        "site_type": "full-site",
        "rationale": (
            f"Cold-start pick: {a_strand.get('name', a_id)} ({ratio_a}%) with "
            f"{b_strand.get('name', b_id)} ({ratio_b}%) accent, derived from "
            f"{vocab_id} vocabulary affinity. Practitioner intelligence was insufficient "
            f"to drive a unique creative call; this is the safe default for the {section} section."
        ),
        "alternatives": [],
        "cold_start": True,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


# ─── Claude call + JSON extraction ────────────────────────────────


def _call_claude(prompt: str, max_tokens: int = 2500) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    response = httpx.post(
        ANTHROPIC_API_BASE,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json; charset=utf-8",
            "Accept-Charset": "utf-8",
        },
        content=json.dumps({
            "model": CLAUDE_MODEL,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }, ensure_ascii=False).encode("utf-8"),
        timeout=60,
    )
    response.raise_for_status()
    response.encoding = "utf-8"
    data = json.loads(response.content.decode("utf-8"))
    return "".join(
        b.get("text", "")
        for b in data.get("content", [])
        if b.get("type") == "text"
    )


def _extract_json(text: str) -> Optional[dict]:
    """Extract first JSON object from raw text. Tolerates markdown fences."""
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except Exception:
        pass
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        try:
            return json.loads(text[first:last + 1])
        except Exception:
            return None
    return None


def _validate_recommendation(rec) -> tuple:
    """Validate recommendation. Returns (is_valid, error_message)."""
    if not isinstance(rec, dict):
        return False, "Not a dict"
    a = rec.get("strand_a_id")
    b = rec.get("strand_b_id")
    if a not in STRAND_IDS:
        return False, f"Invalid strand_a_id: {a}"
    if b not in STRAND_IDS:
        return False, f"Invalid strand_b_id: {b}"
    if a == b:
        return False, "strand_a_id and strand_b_id must differ"
    ra = rec.get("ratio_a")
    rb = rec.get("ratio_b")
    if not isinstance(ra, int) or not 30 <= ra <= 70:
        return False, "ratio_a must be int 30-70"
    if not isinstance(rb, int) or rb != 100 - ra:
        return False, "ratio_b must equal 100 - ratio_a"
    sub_id = rec.get("sub_strand_id")
    if sub_id is not None and sub_id != "" and sub_id not in SUBSTRAND_IDS:
        return False, f"Invalid sub_strand_id: {sub_id}"
    if not is_valid_archetype(rec.get("layout_archetype", "")):
        return False, f"Invalid layout_archetype: {rec.get('layout_archetype')}"
    if not is_valid_accent_style(rec.get("accent_style", "")):
        return False, f"Invalid accent_style: {rec.get('accent_style')}"
    if rec.get("site_type") not in SITE_TYPE_IDS:
        return False, f"Invalid site_type: {rec.get('site_type')}"
    return True, ""


def _normalize_alternatives(rec: dict) -> None:
    """Enrich alternatives with canonical names and swatches when omitted."""
    alts = rec.get("alternatives") or []
    if not isinstance(alts, list):
        rec["alternatives"] = []
        return
    out = []
    for alt in alts:
        if not isinstance(alt, dict):
            continue
        a_id = alt.get("strand_a_id")
        b_id = alt.get("strand_b_id")
        if a_id not in STRAND_IDS or b_id not in STRAND_IDS:
            continue
        a_strand = get_strand(a_id) or {}
        b_strand = get_strand(b_id) or {}
        normalized = dict(alt)
        normalized.setdefault("strand_a_name", a_strand.get("name") or a_id)
        normalized.setdefault("strand_b_name", b_strand.get("name") or b_id)
        normalized.setdefault("swatches_a", a_strand.get("swatches") or [])
        normalized.setdefault("swatches_b", b_strand.get("swatches") or [])
        out.append(normalized)
    rec["alternatives"] = out[:2]  # cap at 2 alternatives


def generate_design_recommendation(
    bundle: dict,
    vocab_id: str,
    products: list,
    cold_start: bool,
) -> tuple:
    """Run the Designer Agent.

    Returns (recommendation: dict | None, error_message: str | None).
    """
    if cold_start:
        rec = cold_start_recommendation(vocab_id)
        return rec, None

    try:
        prompt = build_director_prompt(bundle, vocab_id, products)
    except Exception as e:
        print(f"[designer] prompt build failed: {e}", file=sys.stderr)
        return None, f"Prompt build failed: {type(e).__name__}: {e}"

    try:
        raw = _call_claude(prompt)
    except Exception as e:
        print(f"[designer] Claude call failed: {e}", file=sys.stderr)
        return None, f"Claude call failed: {type(e).__name__}: {e}"

    rec = _extract_json(raw)
    if not rec:
        print(f"[designer] JSON extraction failed; raw head: {raw[:300]!r}", file=sys.stderr)
        return None, "Failed to extract JSON from Claude output"

    is_valid, error = _validate_recommendation(rec)
    if not is_valid:
        print(f"[designer] validation failed: {error}", file=sys.stderr)
        return None, f"Recommendation failed validation: {error}"

    _normalize_alternatives(rec)
    rec["cold_start"] = False
    rec["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return rec, None
