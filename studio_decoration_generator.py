"""Studio-spirit AI generation pipeline.
Claude Opus = Director + Creative agent (single call)
GPT-5.4 = Structural Validator (translates creative output to valid JSON)
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Optional

import httpx

from studio_data import VOCABULARIES, LAYOUTS
from studio_decoration_scheme import validate_decoration_scheme


CLAUDE_MODEL = "claude-opus-4-7"
GPT_MODEL = "gpt-5.4"

ANTHROPIC_API_BASE = "https://api.anthropic.com/v1/messages"
OPENAI_API_BASE = "https://api.openai.com/v1/chat/completions"


def build_director_prompt(business_data, bundle, vocab_id, layout_id, composite):
    """Director-style prompt: gives Claude the full business context to make creative decisions."""
    vocab = VOCABULARIES.get(vocab_id, {}) if vocab_id else {}
    layout = LAYOUTS.get(layout_id, {}) if layout_id else {}
    voice = (bundle or {}).get("voice", {}) or {}
    practitioner = (bundle or {}).get("practitioner", {}) or {}
    business = (bundle or {}).get("business", {}) or {}

    vocab_section = vocab.get("section", "?") if isinstance(vocab, dict) else "?"
    vocab_desc = vocab.get("description", "?") if isinstance(vocab, dict) else "?"
    vocab_signals = ", ".join(
        (vocab.get("signal_words") or []) if isinstance(vocab, dict) else []
    )
    layout_desc = layout.get("description", "?") if isinstance(layout, dict) else "?"

    return f"""You are the Director of design generation for Smart Sites — a multi-tenant practitioner platform that renders unique websites per business by combining 12 deterministic layouts with vocabulary-driven design intelligence and per-business decoration schemes.

Your task: generate a UNIQUE decoration scheme for this specific business. The scheme will override default decoration on top of the chosen layout structure. Same layout x different scheme = visually distinct sites.

# Business context

Name: {business.get("name", "Unknown")}
Type: {business.get("type", "custom")}
Tagline: {business.get("tagline") or "(none)"}
Elevator pitch: {business.get("elevator_pitch") or "(none)"}

# Practitioner context

Display name: {practitioner.get("display_name") or "(none)"}
Voice tone (free-text): {voice.get("tone") or "(none)"}
Brand voice (canonical): {voice.get("brand_voice") or "(none)"}

# Detected design intelligence

Primary vocabulary: {vocab_id}
  Section: {vocab_section}
  Description: {vocab_desc}
  Signal words: {vocab_signals}

Chosen layout: {layout_id}
  Description: {layout_desc}

# Deliverable

Output a JSON object that conforms EXACTLY to this schema:

{{
  "schema_version": 1,
  "color_tokens": {{
    "bg": "#XXXXXX",
    "bg2": "#XXXXXX",
    "bg3": "#XXXXXX",
    "accent": "#XXXXXX",
    "accent_secondary": "#XXXXXX",
    "text": "#XXXXXX",
    "muted": "#XXXXXX",
    "line": "rgba(R,G,B,A)"
  }},
  "typography": {{
    "font_display": "Font Family Name",
    "font_body": "Font Family Name",
    "font_accent": "Font Family Name",
    "h1_size": "clamp(Xrem, Xvw, Xrem)",
    "h1_letter_spacing": "-X.XXem",
    "h2_size": "clamp(Xrem, Xvw, Xrem)",
    "eyebrow_letter_spacing": "X.XXem"
  }},
  "spatial_dna": {{
    "section_x": "clamp(Xrem, Xvw, Xrem)",
    "section_y": "clamp(Xrem, Xvh, Xrem)",
    "container_width": "XXXXpx"
  }},
  "decorations": {{
    "section_divider_style": "ONE OF: gold-rule-diamond, double-hairline, ornamental, geometric, organic, thin-line, minimal",
    "accent_style": "ONE OF: ceremonial, cinematic, editorial, cultural-african, botanical, structural",
    "corner_treatment": "ONE OF: thin-gold, soft-glow, geometric, none",
    "strand": "ONE OF: dark, light, warm, cool"
  }},
  "motion_richness": {{
    "enable_ghost_numbers": true,
    "enable_marquee_strips": true,
    "enable_magnetic_buttons": true,
    "enable_statement_bars": true,
    "stagger_delays": [0.08, 0.16, 0.24, 0.32],
    "parallax_backgrounds": false
  }},
  "marquee_text": "WORD1 - WORD2 - WORD3 - WORD4",
  "statement_bar_quotes": ["Quote 1.", "Quote 2."]
}}

# Creative direction guidelines

1. Color tokens should pair to make the practitioner's voice visible. Sovereign-authority + corporate = dark cinematic with gold restraint. Wellness + warm = soft sage greens with warm earth. Faith ministry + warm = royal purples with ceremonial gold.

2. Typography should have intentional pairing. Display fonts can be expressive (Syne, Playfair, Anton, Bebas Neue, Cormorant). Body fonts should be readable (Inter, Outfit, DM Sans, Manrope). Accent fonts for eyebrows often Montserrat, Inter Bold, Plus Jakarta Sans.

3. Decorations.accent_style should match vocabulary character:
   - sovereign-authority/established-authority -> ceremonial
   - scholar-educator -> editorial
   - faith-ministry -> ceremonial or botanical
   - wellness-healing -> botanical or organic
   - creative-artist/expressive-vibrancy -> cinematic or cultural-african
   - corporate/clean -> editorial or structural

4. Motion richness should feel intentional, not maxed-out. Enable 2-3 modules max. Loud brands (expressive, celebration, sovereign) can have more motion. Restrained brands (minimalist, scholar) should have less.

5. Marquee text and statement bar quotes should sound like they were written FOR this practitioner. Use their actual language patterns. Reference their work, their craft, their stance. Don't write generic phrases.

# Constraints

- All colors must be valid 6-character hex (e.g. "#1A2B3C") except line color which can be rgba.
- All clamp() expressions must use rem/px/em/vh/vw units, three values comma-separated.
- Stagger delays: exactly 4 numbers, each 0.0-2.0.
- Statement quotes: max 200 characters each, max 3 quotes.
- Marquee text: max 500 characters.
- No script tags, no HTML in any string field.
- Output ONLY the JSON object. No commentary before or after.

Generate the decoration scheme now."""


def build_validator_prompt(claude_output):
    """GPT prompt: take Claude's creative output and ensure it's valid JSON conforming to the schema."""
    return f"""You are a JSON validator and structural normalizer. The input below is meant to be a decoration scheme JSON object. Your task: parse it, fix any structural issues (invalid color formats, malformed clamp() expressions, missing required fields), and output ONLY the corrected JSON.

# Rules

1. Output ONLY valid JSON. No commentary, no markdown, no code fences.
2. All hex colors must be 6 characters with leading #. If a 3-char hex like #FFF appears, expand to #FFFFFF.
3. Line color can be rgba() string.
4. All clamp() expressions must be `clamp(X<unit>, X<unit>, X<unit>)` with three values comma-separated and matching units (rem, px, em, vh, vw).
5. Required top-level keys: schema_version (must equal 1), color_tokens, typography, spatial_dna, decorations, motion_richness.
6. If marquee_text is empty string, output null instead.
7. statement_bar_quotes must be array (empty if no quotes), max 3 items, each max 200 chars.
8. motion_richness.stagger_delays must be array of exactly 4 numbers between 0 and 2.
9. decorations.section_divider_style must be one of: gold-rule-diamond, double-hairline, ornamental, geometric, organic, thin-line, minimal.
10. decorations.accent_style must be one of: ceremonial, cinematic, editorial, cultural-african, botanical, structural.
11. decorations.corner_treatment must be one of: thin-gold, soft-glow, geometric, none.
12. decorations.strand must be one of: dark, light, warm, cool.
13. If any field is missing or invalid and cannot be fixed, OMIT it entirely (don't make up values).
14. Preserve all valid creative decisions. Don't change colors, fonts, or content unless they're structurally broken.

# Input

{claude_output}

# Output

Output the corrected JSON object now."""


def call_claude(prompt, max_tokens=2500):
    """Call Claude Opus via Anthropic API. Returns text response."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    response = httpx.post(
        ANTHROPIC_API_BASE,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": CLAUDE_MODEL,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    return "".join(
        block.get("text", "")
        for block in data.get("content", [])
        if block.get("type") == "text"
    )


def call_gpt(prompt, max_tokens=2500):
    """Call GPT-5.4 via OpenAI API. Returns text response."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    response = httpx.post(
        OPENAI_API_BASE,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": GPT_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.0,
        },
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


def extract_json(raw_text):
    """Extract first JSON object from raw text. Tolerates markdown fences."""
    text = (raw_text or "").strip()
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


def generate_decoration_scheme(business_data, bundle, vocab_id, layout_id, composite):
    """Run the full Studio-spirit pipeline. Returns (scheme, error_message).
    scheme is None on failure; error_message describes what went wrong.
    """
    try:
        director_prompt = build_director_prompt(
            business_data, bundle, vocab_id, layout_id, composite
        )
        claude_output = call_claude(director_prompt, max_tokens=2500)
    except Exception as e:
        print(f"[decoration_gen] Claude call failed: {e}", file=sys.stderr)
        return None, f"Creative generation failed: {type(e).__name__}: {e}"

    try:
        validator_prompt = build_validator_prompt(claude_output)
        gpt_output = call_gpt(validator_prompt, max_tokens=2500)
    except Exception as e:
        print(
            f"[decoration_gen] GPT validator failed ({type(e).__name__}: {e}); "
            "falling back to Claude raw output",
            file=sys.stderr,
        )
        gpt_output = claude_output

    scheme = extract_json(gpt_output)
    if not scheme:
        print("[decoration_gen] JSON extraction failed", file=sys.stderr)
        return None, "Generated content was not valid JSON"

    is_valid, error = validate_decoration_scheme(scheme)
    if not is_valid:
        print(f"[decoration_gen] Schema validation failed: {error}", file=sys.stderr)
        return None, f"Generated scheme failed validation: {error}"

    scheme["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return scheme, None
