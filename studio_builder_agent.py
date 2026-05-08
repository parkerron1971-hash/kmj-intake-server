"""Builder Agent (LLM #3) — Pass 3.8d.

Receives the full DesignBrief + bundle + decoration scheme + offerings and
generates a complete bespoke HTML/CSS document. Treated as a senior
creative director with full context, not a code generator.

The output is a single self-contained HTML file. Motion JS modules are
injected by the platform AFTER validation; the LLM never writes JS.
"""
from __future__ import annotations
import sys
from typing import List, Optional, Tuple

from studio_substrands import get_substrand
from studio_designer_agent import _call_claude
from studio_html_validator import (
    extract_html_from_response,
    validate_html,
    inject_motion_modules,
)


# ─── Helpers (module-level so the prompt builder can call them directly) ─

def _format_palette(palette: list) -> str:
    if not palette:
        return "(use brand defaults)"
    lines = []
    for c in palette:
        if isinstance(c, dict):
            hex_val = c.get("hex", "")
            name = c.get("name", "")
            role = c.get("role", "")
            lines.append(f"- {hex_val} ({name}) — {role}")
    return "\n".join(lines) if lines else "(use brand defaults)"


def _format_sections(sections: list) -> str:
    if not sections:
        return "(decide section structure based on brief)"
    blocks = []
    for i, s in enumerate(sections, 1):
        if not isinstance(s, dict):
            continue
        name = s.get("name", f"Section {i}")
        layout_type = s.get("layoutType", "")
        line = f"{i}. {name}"
        if layout_type:
            line += f" (type: {layout_type})"
        if s.get("designNote"):
            line += f"\n   Design: {s['designNote']}"
        if s.get("copyDirection"):
            line += f"\n   Copy: {s['copyDirection']}"
        if s.get("ctaText"):
            line += f"\n   CTA: {s['ctaText']}"
        blocks.append(line)
    return "\n\n".join(blocks) if blocks else "(decide section structure based on brief)"


# ─── Prompt construction ──────────────────────────────────────────────

def _build_builder_prompt(
    brief: dict,
    bundle: dict,
    scheme: Optional[dict],
    products: list,
    testimonials: list,
) -> str:
    """Construct the creative-director prompt for the Builder."""
    brief = brief or {}
    bundle = bundle or {}
    business = bundle.get("business") or {}
    intel = bundle.get("practitioner_intelligence") or {}
    voice = bundle.get("voice") or {}

    business_name = business.get("name", "Unknown")

    sub_id = brief.get("subStrandId")
    sub_strand = get_substrand(sub_id) if sub_id else None

    # ── Practitioner / business context ─────────────────────────────
    practitioner_block = ""
    if intel.get("about_me"):
        practitioner_block += f"\nABOUT THE PRACTITIONER:\n{intel['about_me']}\n"
    if intel.get("about_business"):
        practitioner_block += f"\nABOUT THE BUSINESS:\n{intel['about_business']}\n"

    strategy = intel.get("strategy_track")
    if isinstance(strategy, dict) and strategy:
        strategy_lines = []
        for key in (
            "unique_value_proposition", "target_audience",
            "summary", "practitioner_background",
        ):
            val = strategy.get(key)
            if val:
                label = key.replace("_", " ").title()
                strategy_lines.append(f"  {label}: {val}")
        if strategy_lines:
            practitioner_block += (
                "\nSTRATEGY CONTEXT:\n" + "\n".join(strategy_lines) + "\n"
            )

    # ── Voice ───────────────────────────────────────────────────────
    voice_block = ""
    if voice.get("brand_voice"):
        voice_block += f"Brand voice: {voice['brand_voice']}\n"
    tones = voice.get("tones") or []
    if isinstance(tones, list) and tones:
        voice_block += f"Tone: {', '.join(str(t) for t in tones if t)}\n"
    if voice.get("voice_dos"):
        sample = [d for d in voice["voice_dos"][:5] if d]
        if sample:
            voice_block += f"Voice rules: {', '.join(sample)}\n"

    # ── Products ────────────────────────────────────────────────────
    products_block = ""
    if products:
        product_lines = []
        for p in products[:8]:
            if not isinstance(p, dict):
                continue
            name = p.get("name", "")
            desc = (p.get("description") or "").strip()[:200]
            price = p.get("price")
            line = f"- {name}"
            if price:
                line += f" (${price})"
            if desc:
                line += f": {desc}"
            product_lines.append(line)
        if product_lines:
            products_block = "OFFERINGS:\n" + "\n".join(product_lines) + "\n"

    # ── Testimonials ────────────────────────────────────────────────
    testimonials_block = ""
    if testimonials:
        t_lines = []
        for t in testimonials[:3]:
            if not isinstance(t, dict):
                continue
            quote = (t.get("quote") or t.get("content") or "").strip()[:300]
            author = t.get("author_name") or t.get("name") or ""
            role = t.get("author_title") or t.get("role") or ""
            if quote:
                attribution = f"{author}, {role}".strip(", ").rstrip(",")
                if attribution:
                    t_lines.append(f'"{quote}" — {attribution}')
                else:
                    t_lines.append(f'"{quote}"')
        if t_lines:
            testimonials_block = "TESTIMONIALS:\n" + "\n".join(t_lines) + "\n"

    # ── Decoration scheme ───────────────────────────────────────────
    scheme_block = ""
    if scheme:
        decorations = scheme.get("decorations") or {}
        scheme_block = (
            "\nDECORATION DIRECTION:\n"
            f"Divider style: {decorations.get('section_divider_style', 'thin-line')}\n"
            f"Corner treatment: {decorations.get('corner_treatment', 'none')}\n"
            f"Strand: {decorations.get('strand', 'light')}\n"
        )
        if scheme.get("marquee_text"):
            scheme_block += (
                f"\nMarquee available — use as a horizontally-scrolling band "
                f"between sections if it fits the rhythm: "
                f"{scheme['marquee_text']}\n"
            )
        sb_quotes = scheme.get("statement_bar_quotes") or []
        if sb_quotes:
            quotes = " | ".join(str(q) for q in sb_quotes[:3] if q)
            if quotes:
                scheme_block += (
                    f"\nStatement quotes available — use as oversized "
                    f"section-break statements if it fits: {quotes}\n"
                )

    # ── Sub-strand DNA ──────────────────────────────────────────────
    sub_block = ""
    if sub_strand:
        sub_block = (
            "\nSUB-STRAND VARIANT: "
            f"{sub_strand.get('name', '')}\n"
            f"Description: {sub_strand.get('description', '')}\n"
            f"Color direction: {sub_strand.get('colorDirection', '')}\n"
            f"Typography direction: {sub_strand.get('typographyDirection', '')}\n"
            f"Spatial direction: {sub_strand.get('spatialDirection', '')}\n"
            f"Hero pattern: {sub_strand.get('heroLayout', '')}\n"
            f"Signature detail: {sub_strand.get('signatureDetail', '')}\n"
            f"Reference brands: {sub_strand.get('exampleBrands', '')}\n"
        )

    # ── Color discipline / typography pulls ─────────────────────────
    color_disc = brief.get("colorDiscipline") or {}
    typography = brief.get("typography") or {}
    accent_cfg = brief.get("accentConfig") or {}

    display_font = (typography.get("display") or {}).get("name", "")
    body_font = (typography.get("body") or {}).get("name", "")
    accent_font = (typography.get("accent") or {}).get("name", "")

    return f"""You are a senior creative director and master frontend developer. You build production websites that feel genuinely designed — not assembled from templates. You read a creative brief the way a designer reads one: you understand the tension, feel the spatial logic, hear the copy voice. Then you build.

Output ONLY raw HTML starting with <!DOCTYPE html>. Nothing before. Nothing after. No markdown fences. No explanation. No commentary.

═══════════════════════════════════════
BUILD A HOME PAGE FOR {business_name.upper()}
═══════════════════════════════════════

# DESIGN THESIS

"{brief.get('tensionStatement', '')}"

This tension IS the brand signature. Every layout decision expresses it. The page is not a container for content — it is a physical manifestation of this tension.

# CONCEPT NAME

"{brief.get('conceptName', '')}"

# BLEND

{brief.get('blendRatio', '')}

# PHILOSOPHY

{brief.get('philosophy', '')}

# SPATIAL ARCHITECTURE

{brief.get('spatialDirection', '')}

This is how space MOVES through the page. Rhythm. Compression. Release. Where headlines sit. How sections relate.
{sub_block}
# COPY VOICE

{brief.get('copyVoice', '')}

Write copy in this voice. Don't write generic web copy.

# MOOD

{brief.get('mood', '')}

# COLOR DISCIPLINE

{_format_palette(brief.get('palette') or [])}

Accent rule: {color_disc.get('accentRule', '')}
CTA color: {color_disc.get('ctaColor', '')}
Max accent per section: {color_disc.get('maxAccentPerSection', 1)}
Neutral usage: {color_disc.get('neutralUsage', '')}

# TYPOGRAPHY

Display: {display_font} (use for hero headlines, section titles)
Body: {body_font} (use for paragraphs)
Accent: {accent_font} (use for eyebrows, labels, CTAs)

Import these fonts via Google Fonts <link> in <head>.

# ACCENT CONFIGURATION

Style: {accent_cfg.get('style', 'editorial')}
Divider: {accent_cfg.get('dividerStyle', 'thin-rule')}
Opacity: {accent_cfg.get('opacity', 0.08)}

# CLIENT CONTEXT
{practitioner_block}
{voice_block}
{products_block}
{testimonials_block}
{scheme_block}

# DESIGN BRIEF — SECTIONS TO INCLUDE

{_format_sections(brief.get('sections') or [])}

These are guidance, not script. The order, treatment, and layout of each section is your creative decision based on the spatial architecture and tension statement.

# RULES (NON-NEGOTIABLE)

- Output starts with <!DOCTYPE html> on the very first line. No preamble.
- Single HTML file. All CSS inlined in <style> block in <head>. No external stylesheets except Google Fonts via <link>.
- NO JavaScript. NO <script> tags. Motion modules will be injected by the platform after your output validates.
- NO external resources except Google Fonts (fonts.googleapis.com / fonts.gstatic.com).
- Use the COLOR DISCIPLINE rules. Accent appears with intent, not decoratively.
- Use the TYPOGRAPHY pairing. Don't substitute fonts.
- Hierarchy comes from typography + space + color, not decoration.
- Mobile-first. Use clamp() for fluid sizing. Single-column on mobile. @media queries for desktop expansion.
- Real copy in the practitioner's voice. NOT generic placeholder copy. Reference their actual practice, philosophy, offerings.
- The tension statement should be visible in the design, not just the copy.
- Every section earns its place. Empty space is design — but voids are bugs.

# DESIGN APPROACH

1. Read the tension statement again. Internalize it.
2. Decide the hero treatment. Where does the headline sit? What flanks it? Does it have a pull-quote? A manifesto? An asymmetric grid? The hero is the strongest expression of the tension.
3. Map the section rhythm. Compression and release. Loud and quiet. The brief gives you sections; you decide how they pace.
4. Make typographic decisions that express the strand. Luxury sets headlines in the lower third. Editorial uses asymmetric grids. Brutalist uses raw borders. Don't default to centered everything.
5. Use color with restraint. Accent appears once per section unless the brief explicitly allows more.
6. Write real copy that sounds like the practitioner. Not "We help businesses grow." Specific, voiced, honest.
7. Build it.

Now generate the complete production HTML for {business_name}. Begin with <!DOCTYPE html>."""


# ─── Public entry point ──────────────────────────────────────────────

def build_html(
    brief: dict,
    bundle: dict,
    scheme: Optional[dict],
    products: list,
    testimonials: list,
) -> Tuple[Optional[str], Optional[str], List[str]]:
    """Run the Builder Agent.

    Returns (html, error_message, validation_errors).
    On any failure html is None and error_message describes the cause.
    Validation errors (if any) are returned for diagnostics on the failure
    path; on success the list is empty.
    """
    # 1. Construct prompt
    try:
        prompt = _build_builder_prompt(
            brief or {}, bundle or {}, scheme, products or [], testimonials or [],
        )
    except Exception as e:
        return None, f"Prompt construction failed: {type(e).__name__}: {e}", []

    # 2. Call Claude — Builder is heavy. A complete bespoke HTML page with
    # inline CSS, custom hero treatments and section blocks routinely
    # exceeds 12 k output tokens; we observed the first run truncate at
    # 12 k mid-document, so the ceiling is lifted to 24 k. The HTTP timeout
    # is bumped accordingly (Opus generates ~150 tokens/sec).
    try:
        raw = _call_claude(prompt, max_tokens=24000, timeout=300.0)
    except Exception as e:
        print(f"[builder] Claude call failed: {e}", file=sys.stderr)
        return None, f"Claude call failed: {type(e).__name__}: {e}", []

    # 3. Extract HTML from the raw response
    html = extract_html_from_response(raw or "")
    if not html:
        print("[builder] Could not extract HTML from response", file=sys.stderr)
        return None, "Could not extract HTML from response", []

    # 4. Validate
    is_valid, errors = validate_html(html)
    if not is_valid:
        print(f"[builder] Validation failed: {errors}", file=sys.stderr)
        return None, "HTML failed validation", errors

    # 5. Inject motion modules + reactivity layer (post-validation).
    # Brief flows through so strand-aware gradients (Pass 3.8e) can render.
    try:
        html = inject_motion_modules(html, scheme, brief)
    except Exception as e:
        # Non-fatal: if injection fails we still ship the validated HTML.
        print(f"[builder] motion/reactivity inject failed: {e}", file=sys.stderr)

    return html, None, []
