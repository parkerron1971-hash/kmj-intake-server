"""Studio-spirit AI generation pipeline.
Claude Opus = Director + Creative agent (single call)
GPT-5.4 = Structural Validator (translates creative output to valid JSON)
"""
from __future__ import annotations

import json
import os
import re
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


def _voice_signal_breakdown(bundle, products=None):
    """Return a dict naming which voice-depth signals are present.
    Used for both the cold-start gate and diagnostics."""
    if not isinstance(bundle, dict):
        bundle = {}
    business = bundle.get("business") or {}
    voice = bundle.get("voice") or {}

    def _present(v):
        if v is None:
            return False
        if isinstance(v, str):
            return bool(v.strip())
        if isinstance(v, (list, tuple, dict)):
            return len(v) > 0
        return bool(v)

    return {
        "tagline": _present(business.get("tagline")),
        "elevator_pitch": _present(business.get("elevator_pitch")),
        "voice_tone": _present(voice.get("tone")) or _present(voice.get("tone_original")),
        "voice_dos": _present(voice.get("voice_dos")),
        "voice_donts": _present(voice.get("voice_donts")),
        "products_with_names": any(
            isinstance(p, dict) and _present(p.get("name"))
            for p in (products or [])
        ),
    }


def _has_meaningful_voice_signal(bundle, products=None):
    """Decide whether the prompt should run the rich-data branch.

    Returns True if AT LEAST 2 of the following exist non-empty:
      - business.tagline
      - business.elevator_pitch
      - voice.tone (or tone_original)
      - voice.voice_dos (signature phrases)
      - voice.voice_donts (don't-say list)
      - any product with a non-empty name

    The threshold (2-of-6) is deliberately permissive — we only want to
    fall into the empty-data branch when the practitioner has truly given
    us nothing. One signal could be coincidence; two means there is
    enough material for Claude to anchor specific creative choices on.
    """
    breakdown = _voice_signal_breakdown(bundle, products)
    return sum(1 for v in breakdown.values() if v) >= 2


def _format_list(items, max_items=8, joiner="; "):
    """Render a list of strings into a single comma-or-semicolon-joined
    line, truncating long lists. Returns '(none)' if empty."""
    if not items:
        return "(none)"
    cleaned = [str(x).strip() for x in items if x and str(x).strip()]
    if not cleaned:
        return "(none)"
    truncated = cleaned[:max_items]
    suffix = "" if len(cleaned) == max_items else (
        f" (+{len(cleaned) - max_items} more)" if len(cleaned) > max_items else ""
    )
    return joiner.join(truncated) + suffix


def _format_voice_samples(samples):
    """voice_samples is a dict like {greeting: '...', habit_phrase: '...'}."""
    if not isinstance(samples, dict) or not samples:
        return "(none)"
    parts = []
    for k, v in samples.items():
        if v and isinstance(v, str):
            parts.append(f'{k}: "{v.strip()}"')
        if len(parts) >= 6:
            break
    return _format_list(parts, max_items=6, joiner=" | ")


def _format_products(products):
    """products is a list of rows from the products table."""
    if not products:
        return "(none — no products defined yet)"
    names = []
    for p in products:
        if not isinstance(p, dict):
            continue
        name = (p.get("name") or "").strip()
        if name:
            names.append(name)
    return _format_list(names, max_items=8, joiner=" / ")


def build_director_prompt(
    business_data, bundle, vocab_id, layout_id, composite, products=None
):
    """Director-style prompt: gives Claude the full business context to make creative decisions."""
    vocab = VOCABULARIES.get(vocab_id, {}) if vocab_id else {}
    layout = LAYOUTS.get(layout_id, {}) if layout_id else {}
    voice = (bundle or {}).get("voice", {}) or {}
    practitioner = (bundle or {}).get("practitioner", {}) or {}
    business = (bundle or {}).get("business", {}) or {}
    legal = (bundle or {}).get("legal", {}) or {}

    vocab_section = vocab.get("section", "?") if isinstance(vocab, dict) else "?"
    vocab_desc = vocab.get("description", "?") if isinstance(vocab, dict) else "?"
    vocab_signals = ", ".join(
        (vocab.get("signal_words") or []) if isinstance(vocab, dict) else []
    )
    layout_desc = layout.get("description", "?") if isinstance(layout, dict) else "?"

    # Practitioner depth — read defensively. `bio` may live on the
    # practitioner row, in business.settings, or nowhere; check both.
    practitioner_bio = (
        practitioner.get("bio")
        or ((business_data or {}).get("settings") or {}).get("practitioner_bio")
        or ""
    ).strip()
    preferred_title = (practitioner.get("preferred_title") or "").strip()

    # Voice depth — surface what brand_engine.py already composes.
    voice_dos = voice.get("voice_dos") or []  # phrases they consistently use
    voice_donts = voice.get("voice_donts") or []  # phrases they explicitly avoid
    voice_samples = voice.get("voice_samples") or {}
    audience = voice.get("audience") or ""

    # Foundation Track stance — a meaningful brand signal.
    in_the_clear = bool(legal.get("in_the_clear"))
    foundation_line = (
        "Foundation Track: COMPLETE — practitioner has earned the In-The-Clear stance."
        if in_the_clear
        else "Foundation Track: in progress."
    )

    products_line = _format_products(products)
    elevator_pitch_full = (business.get("elevator_pitch") or "").strip() or "(none)"

    # ─── Empty-data vs rich-data branching ───────────────────────────
    has_signal = _has_meaningful_voice_signal(bundle, products)

    if has_signal:
        marquee_template = '"WORD1 - WORD2 - WORD3 - WORD4"'
        quotes_template = '["Short quote 1.", "Short quote 2."]'
        statement_bars_default = "true"
        guideline_5 = (
            '5. AVOID generic agency-speak in marquee_text and statement_bar_quotes. '
            'Banned phrases (NEVER use these or close paraphrases of them): "elevate '
            'the vision", "amplify the impact", "strategy meets craft", "built with '
            'intention", "crafted with intention", "creative excellence", "transform '
            'your business", "unlock potential", "deliver projects", "elevate entire '
            'visions", "strategic command", "forward-thinking", "breakthrough work", '
            '"earned through", "innovative solutions", "trusted partner", "drive '
            'results". These are the cliche phrases every consultant brand uses. '
            'Instead, draw from THIS practitioner\'s actual voice: their tagline, '
            'their elevator pitch wording, their signature phrases (listed above), '
            'their product names. The marquee should be 3-5 single words or very '
            'short phrases that feel ceremonial / specific to this practitioner. '
            'Example of strong marquee for a Sovereign Authority consultant: '
            '"CEREMONY - CRAFT - PRESENCE - CLARITY" - single words with weight, '
            'not agency phrases. Statement quotes should sound like the practitioner '
            'ACTUALLY SAID THEM, not like marketing copy. If you find yourself '
            'writing a complete sentence with subject-verb-object that sounds like '
            'a website footer, rewrite it as something terser, stranger, or more '
            'specific to their craft.'
        )
        empty_data_notice = ""
    else:
        # Empty-data branch: refuse to fabricate voice. The marquee uses
        # only ceremonial single words from the vocabulary's signal_words.
        # Statement bars are disabled until voice depth exists.
        marquee_template = (
            '"SIGNAL_WORD1 • SIGNAL_WORD2 • SIGNAL_WORD3 • SIGNAL_WORD4"  '
            '// 3-5 SINGLE words separated by " • " (BULLET with spaces). '
            'NO sentences, NO multi-word phrases. Pull words ONLY from the vocabulary\'s signal_words above.'
        )
        quotes_template = "[]  // MUST be empty array"
        statement_bars_default = "false  // MUST be false; no quotes = no statement bars"
        empty_data_notice = (
            "\n\n# COLD-START NOTICE — empty practitioner voice\n\n"
            "This practitioner has not yet filled out their voice profile. "
            "We refuse to generate content that pretends to know their voice. "
            "Marquee uses only ceremonial single words from the vocabulary's "
            "signal_words list. Statement bars are disabled until voice depth "
            "exists. Color tokens, typography, decorations, and other motion "
            "modules can still be intentional based on the vocabulary archetype "
            "alone.\n\nExamples of correct empty-data marquee output for various "
            "vocabularies:\n"
            "  - sovereign-authority: \"THRONE • RULE • CEREMONY • CRAFT • GOLD\"\n"
            "  - scholar-educator: \"INQUIRY • RIGOR • EVIDENCE • CLARITY\"\n"
            "  - faith-ministry: \"GRACE • PRESENCE • LIGHT • OFFERING\"\n"
            "  - wellness-healing: \"BREATH • ROOTS • RHYTHM • TENDER\"\n"
            "  - creative-artist: \"FLAME • RAW • MAKE • RISK\"\n"
        )
        guideline_5 = (
            '5. EMPTY-DATA RULE: marquee_text MUST be 3-5 single words separated '
            'by " • " (bullet character with spaces on each side). Words MUST '
            'come from the vocabulary signal_words list above (or be the same '
            'kind of single ceremonial word). NO multi-word phrases, NO sentences, '
            'NO English idioms, NO marketing copy. statement_bar_quotes MUST be '
            '[] (empty). motion_richness.enable_statement_bars MUST be false. '
            'Refuse to fabricate quotes the practitioner never said. The rest '
            'of the scheme (colors, typography, decorations, ghost numbers, '
            'marquee, magnetic buttons) can still be intentional based on the '
            'vocabulary archetype.'
        )

    cold_start_active = not has_signal

    prompt = f"""You are the Director of design generation for Smart Sites — a multi-tenant practitioner platform that renders unique websites per business by combining 12 deterministic layouts with vocabulary-driven design intelligence and per-business decoration schemes.

Your task: generate a UNIQUE decoration scheme for this specific business. The scheme will override default decoration on top of the chosen layout structure. Same layout x different scheme = visually distinct sites.

# Business context

Name: {business.get("name", "Unknown")}
Type: {business.get("type", "custom")}
Tagline: {business.get("tagline") or "(none)"}
Elevator pitch (full): {elevator_pitch_full}
{foundation_line}

# Practitioner context

Display name: {practitioner.get("display_name") or "(none)"}
Preferred title: {preferred_title or "(none)"}
Bio: {practitioner_bio or "(none)"}

Voice tone (free-text): {voice.get("tone_original") or voice.get("tone") or "(none)"}
Brand voice (canonical): {voice.get("brand_voice") or "(none)"}
Audience: {audience or "(none)"}
Voice samples (greetings/sign-offs/habit phrases): {_format_voice_samples(voice_samples)}
Phrases they consistently use (signature phrases): {_format_list(voice_dos)}
Phrases they explicitly avoid (don't say): {_format_list(voice_donts)}

# Their actual offerings (use these names, don't invent generic services)

Products / engagements: {products_line}

# Detected design intelligence

Primary vocabulary: {vocab_id}
  Section: {vocab_section}
  Description: {vocab_desc}
  Signal words: {vocab_signals}

Chosen layout: {layout_id}
  Description: {layout_desc}{empty_data_notice}

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
    "enable_statement_bars": {statement_bars_default},
    "stagger_delays": [0.08, 0.16, 0.24, 0.32],
    "parallax_backgrounds": false
  }},
  "marquee_text": {marquee_template},
  "statement_bar_quotes": {quotes_template}
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

{guideline_5}

# Constraints

- All colors must be valid 6-character hex (e.g. "#1A2B3C") except line color which can be rgba.
- All clamp() expressions must use rem/px/em/vh/vw units, three values comma-separated.
- Stagger delays: exactly 4 numbers, each 0.0-2.0.
- Statement quotes: max 200 characters each, max 3 quotes.
- Marquee text: max 500 characters.
- No script tags, no HTML in any string field.
- Output ONLY the JSON object. No commentary before or after.

Generate the decoration scheme now."""

    return prompt, cold_start_active


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


def _decode_utf8_response(response):
    """Force UTF-8 interpretation of the response body, regardless of any
    missing/incorrect charset header. Returns the parsed JSON dict.

    httpx defaults to charset from Content-Type, falling back to a guess
    that can land on Latin-1 — which corrupts smart-punctuation glyphs
    on the way back. Bypass that by decoding raw bytes ourselves.
    """
    return json.loads(response.content.decode("utf-8"))


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
    data = _decode_utf8_response(response)
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
            "Content-Type": "application/json; charset=utf-8",
            "Accept-Charset": "utf-8",
        },
        content=json.dumps({
            "model": GPT_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.0,
        }, ensure_ascii=False).encode("utf-8"),
        timeout=60,
    )
    response.raise_for_status()
    response.encoding = "utf-8"
    data = _decode_utf8_response(response)
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


def _run_creative_pass(prompt, retry_addendum=""):
    """One Claude → (try GPT, fall back to Claude raw) → JSON extract pass.
    Returns (scheme_or_none, error_or_none, raw_claude_output)."""
    claude_input = prompt + (("\n\n" + retry_addendum) if retry_addendum else "")
    try:
        claude_output = call_claude(claude_input, max_tokens=2500)
    except Exception as e:
        print(f"[decoration_gen] Claude call failed: {e}", file=sys.stderr)
        return None, f"Creative generation failed: {type(e).__name__}: {e}", ""

    try:
        gpt_output = call_gpt(build_validator_prompt(claude_output), max_tokens=2500)
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
        return None, "Generated content was not valid JSON", claude_output
    return scheme, None, claude_output


def generate_decoration_scheme(
    business_data, bundle, vocab_id, layout_id, composite, products=None
):
    """Run the full Studio-spirit pipeline. Returns (scheme, error_message).
    scheme is None on failure; error_message describes what went wrong.

    Banned-phrase handling: if the first generation lands cliche phrases
    in marquee_text or statement_bar_quotes, append a feedback addendum
    naming the offending phrases and retry the whole creative pass once.
    If the second pass still produces banned phrases, strip the bad
    fields (marquee_text -> null, statement_bar_quotes -> []) and stamp
    a `_validation_warnings` field on the scheme so downstream code can
    surface the fact that we sanitized.
    """
    director_prompt, cold_start_active = build_director_prompt(
        business_data, bundle, vocab_id, layout_id, composite, products=products
    )

    # First creative pass
    scheme, err, _claude1 = _run_creative_pass(director_prompt)
    if err:
        return None, err
    is_valid, error, banned_hits = validate_decoration_scheme(scheme)
    if not is_valid:
        print(f"[decoration_gen] Schema validation failed: {error}", file=sys.stderr)
        return None, f"Generated scheme failed validation: {error}"

    warnings = []

    if banned_hits:
        # Tell Claude exactly what it did wrong and try once more.
        offending = sorted({phrase for _field, phrase in banned_hits})
        print(
            f"[decoration_gen] First-pass banned phrases: {offending}; retrying",
            file=sys.stderr,
        )
        retry_addendum = (
            "RETRY — your previous output contained banned phrases: "
            + ", ".join(f'"{p}"' for p in offending)
            + ". These phrases (or close paraphrases) are forbidden. "
            "Generate the scheme again. For marquee_text and statement_bar_quotes, "
            "use ONLY single ceremonial words drawn from the vocabulary's "
            "signal_words list, OR phrases the practitioner actually uses (from "
            'their tagline / elevator pitch / signature phrases listed above). '
            "If you have no specific practitioner voice signal, use single "
            'words from signal_words separated by " • " for marquee_text and '
            "make statement_bar_quotes an empty array []. Output ONLY the "
            "corrected JSON, no commentary."
        )
        retry_scheme, retry_err, _claude2 = _run_creative_pass(director_prompt, retry_addendum)
        if retry_err:
            print(
                f"[decoration_gen] Retry failed ({retry_err}); falling back to strip",
                file=sys.stderr,
            )
        else:
            retry_valid, retry_verr, retry_hits = validate_decoration_scheme(retry_scheme)
            if retry_valid and not retry_hits:
                # Retry succeeded — use the cleaner scheme.
                scheme = retry_scheme
                banned_hits = []
                warnings.append("regenerated_after_banned_phrase_first_pass")
            elif retry_valid and retry_hits:
                # Retry valid but still cliche — strip the bad fields.
                still_offending = sorted({p for _f, p in retry_hits})
                print(
                    f"[decoration_gen] Retry still had banned phrases {still_offending}; stripping",
                    file=sys.stderr,
                )
                # Fall through to strip on the retry result so we keep
                # any other improvements it produced.
                scheme = retry_scheme
                banned_hits = retry_hits
            # If retry was invalid, keep first-pass scheme and strip below.

    if banned_hits:
        # Scrub marquee/quotes; keep everything else.
        scheme["marquee_text"] = None
        scheme["statement_bar_quotes"] = []
        try:
            mr = scheme.setdefault("motion_richness", {})
            if isinstance(mr, dict):
                mr["enable_statement_bars"] = False
                mr["enable_marquee_strips"] = False
        except Exception:
            pass
        warnings.append("stripped_banned_phrases")
        warnings.append(
            "banned_hits=" + ",".join(f"{f}:{p}" for f, p in banned_hits)
        )

    # ─── Cold-start contract enforcement ─────────────────────────────
    # Cold-start MUST rules ("statement_bar_quotes is []", "enable_statement_bars
    # is false", marquee uses single ceremonial words separated by " • ") are
    # platform guarantees, not prompt suggestions. Claude reliably follows the
    # marquee single-word structure but soft-ignores the "MUST be empty" /
    # "MUST be false" hard constraints. Enforce them server-side here.
    if cold_start_active:
        scheme["statement_bar_quotes"] = []
        motion = scheme.setdefault("motion_richness", {})
        if isinstance(motion, dict):
            motion["enable_statement_bars"] = False

        mt = scheme.get("marquee_text")
        if isinstance(mt, str) and mt.strip():
            # Replace any " — " / " - " / " | " / "/" / "–" separator with
            # " • " (bullet with surrounding spaces). Then collapse double
            # bullets and trim leading/trailing bullet-spaces.
            normalized = re.sub(r"\s*[—–|/\-]\s*", " • ", mt)
            normalized = re.sub(r"(\s*•\s*)+", " • ", normalized)
            stripped = normalized.strip(" •")
            scheme["marquee_text"] = stripped or normalized.strip()

        warnings.append("cold_start_enforced")

    if warnings:
        scheme["_validation_warnings"] = warnings

    scheme["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return scheme, None
