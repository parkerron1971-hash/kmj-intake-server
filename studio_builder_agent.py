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

    # ── Pass 3.8f — strand primitives reference ─────────────────────
    # Resolve the dominant strand id from blendRatio ("60% Editorial /
    # 40% Luxury" → "editorial"). Fall back to subStrandId's parent or
    # to "minimal" so we never crash in primitive lookup.
    dominant_strand_id = ""
    blend_ratio = (brief.get("blendRatio") or "").strip()
    if blend_ratio:
        import re as _re
        m = _re.match(r"\s*\d+%\s+([A-Za-z\-]+)", blend_ratio)
        if m:
            dominant_strand_id = m.group(1).lower()
    if not dominant_strand_id and sub_strand:
        dominant_strand_id = (sub_strand.get("parentStrandId") or "").lower()
    if not dominant_strand_id:
        dominant_strand_id = "minimal"

    primitives_block = ""
    try:
        from studio_design_primitives import get_primitives_for_strand
        primitives = get_primitives_for_strand(dominant_strand_id)
    except Exception:
        primitives = []
    if primitives:
        lines = [
            "═══════════════════════════════════════",
            f"PRIMITIVE PATTERNS FOR {dominant_strand_id.upper()}",
            "═══════════════════════════════════════",
            "",
            "These are reference patterns that fit this strand. Pick one or synthesize across them. They are inspiration, not templates.",
        ]
        for i, p in enumerate(primitives, 1):
            lines.append(f"\n{i}. {p.get('name', '')}")
            lines.append(f"   What it is: {p.get('description', '')}")
            lines.append(f"   Spatial logic: {p.get('spatial_logic', '')}")
            lines.append(f"   When to use: {p.get('when_to_use', '')}")
        primitives_block = "\n".join(lines)

    # ── Pass 3.8f — creative anchors block ──────────────────────────
    signature_moment = (brief.get("signature_moment") or "").strip()
    pacing_rhythm = (brief.get("pacing_rhythm") or "").strip()
    voice_proof_quote = (brief.get("voice_proof_quote") or "").strip()
    pacing_description = ""
    if pacing_rhythm:
        try:
            from studio_design_primitives import get_pacing_description
            pacing_description = get_pacing_description(pacing_rhythm)
        except Exception:
            pacing_description = ""

    anchors_block = ""
    if signature_moment or pacing_rhythm or voice_proof_quote:
        anchor_lines = [
            "═══════════════════════════════════════",
            "CREATIVE ANCHORS — NON-NEGOTIABLE",
            "═══════════════════════════════════════",
        ]
        if signature_moment:
            anchor_lines.append(f"\nSIGNATURE MOMENT: {signature_moment}")
            anchor_lines.append(
                "This specific detail MUST be visible in the rendered HTML. Not approximated. Present."
            )
        if pacing_rhythm:
            anchor_lines.append(f"\nPACING RHYTHM: {pacing_rhythm}")
            if pacing_description:
                anchor_lines.append(f"  {pacing_description}")
            anchor_lines.append("Order the sections to express this rhythm.")
        if voice_proof_quote:
            anchor_lines.append(f'\nVOICE PROOF QUOTE: "{voice_proof_quote}"')
            anchor_lines.append(
                "This exact sentence (or very close paraphrase preserving voice) MUST appear in the rendered site. Decide where it lives — likely a pull-quote, statement bar, or sub-headline."
            )
        anchors_block = "\n".join(anchor_lines)

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
WHAT GREAT LOOKS LIKE vs WHAT MEDIOCRE LOOKS LIKE
═══════════════════════════════════════

GREAT (Power-In-Restraint barbershop site, real reference):
- Hero is a single line of display serif at lower-third of viewport
- Beneath: a quote in italic from the founder, attributed
- Right column holds a thin gold rule and a single client testimonial in 14px serif
- No image of a chair. No tagline like "premium grooming."
- Section break is a single horizontal rule — gold, 1px, 60% width, centered
- Service section is a numbered list (I, II, III) — not cards. Each service has a price right-aligned and a single sentence of description
- About section: practitioner's words about the work, not bio. Photo is small, monochrome, far right
- Closing CTA is a single line: "Schedule a chair, by appointment."

MEDIOCRE (what to avoid):
- Hero with centered "Welcome to [Business Name]" + generic value prop + "Get Started" button
- Three-card services grid with stock icons (clock, checkmark, gear)
- Testimonial section with three quote bubbles laid out in a row
- About section with practitioner photo as circular avatar + "I help businesses..." copy
- Generic gradient background that could belong to any SaaS
- "What clients say" / "Why choose us" / "Our process" — generic section labels

The difference is specificity. Great design encodes THIS practice's actual character. Mediocre design fills a template with this practice's data.

═══════════════════════════════════════
ANTI-PATTERNS — DO NOT DO THESE
═══════════════════════════════════════

- DO NOT center every headline. Decide where it sits.
- DO NOT use generic icons (checkmarks, clocks, gears) as section decoration.
- DO NOT label sections "What Clients Say", "Our Process", "Why Choose Us", "Trusted By", "Get Started Today". Name them after THIS practice's actual rhythm.
- DO NOT default to a 3-column card grid for services. Decide if they're a numbered list, a vertical sequence, an editorial spread.
- DO NOT use stock photography references. If no real photo exists, use typographic dignity instead.
- DO NOT add filler sections (FAQ, Stats with random numbers, "Trusted by") to fill space.
- DO NOT use "Get Started", "Learn More", "Click Here", "Find Out More" as CTA copy. Write the actual invitation.
- DO NOT forget the SIGNATURE MOMENT. If the brief specifies one, it MUST be visible.
- DO NOT drop the VOICE PROOF QUOTE. If the brief specifies one, it MUST appear somewhere on the page.

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
{primitives_block}

{anchors_block}

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

# RULES (Pass 3.8f additions)

- The SIGNATURE MOMENT from CREATIVE ANCHORS must be visible in the output. If the brief specifies a gold rule above section headings, render that rule. If it specifies roman-numeral section numbers, render them.
- The VOICE PROOF QUOTE (if specified, non-empty) must appear in the page — verbatim, or as a very close paraphrase that preserves voice. Place it where it belongs (pull-quote, statement bar, sub-headline) — that's your creative call.
- Section ordering must reflect the PACING RHYTHM. compression-release alternates dense/quiet; cathedral grand-quiet-grand; essay-arc setup→tension→development→resolution; etc.
- Section labels are SPECIFIC to this practice. Avoid: "What Clients Say", "Our Process", "Why Choose Us", "Trusted By", "Get Started Today". CTAs are SPECIFIC: never "Get Started" / "Learn More" / "Click Here".

# DESIGN APPROACH

0. Read the CREATIVE ANCHORS first. Internalize the signature moment, the pacing rhythm, the voice proof quote. These are non-negotiable. The rest of your design decisions flow around honoring them.
1. Read the tension statement again. Internalize it.
2. Look at the PRIMITIVE PATTERNS for this strand. Pick one or synthesize across them — they're inspiration, not templates. Reject any that fight the signature moment.
3. Decide the hero treatment. Where does the headline sit? What flanks it? Does it have a pull-quote? A manifesto? An asymmetric grid? The hero is the strongest expression of the tension.
4. Map the section rhythm to the pacing_rhythm. Compression and release. Loud and quiet. The brief gives you sections; you decide how they pace.
5. Make typographic decisions that express the strand. Luxury sets headlines in the lower third. Editorial uses asymmetric grids. Brutalist uses raw borders. Don't default to centered everything.
6. Use color with restraint. Accent appears once per section unless the brief explicitly allows more.
7. Write real copy that sounds like the practitioner. Not "We help businesses grow." Specific, voiced, honest.
8. Place the voice_proof_quote (if any) somewhere visible. Render the signature moment. Verify before finishing.
9. Build it.

Now generate the complete production HTML for {business_name}. Begin with <!DOCTYPE html>."""


# ─── Public entry point ──────────────────────────────────────────────

def build_html(
    brief: dict,
    bundle: dict,
    scheme: Optional[dict],
    products: list,
    testimonials: list,
) -> Tuple[Optional[str], Optional[str], List[str]]:
    """Run the Builder Agent with quality validation and one auto-retry.

    Returns (html, error_message, warnings).
    Three outcome shapes:
      • (html, None, [])           — clean success, no warnings
      • (html, None, warnings)     — success but quality heuristics found
                                     issues; html still ships
      • (None, error_message, errs)— hard failure; errs is the structural
                                     validator's error list when applicable

    Up to 2 attempts. The retry, when triggered by quality failure on the
    first attempt, appends corrective guidance to the prompt before the
    second LLM call. Hard failures (Claude error, extraction error, HTML
    structural validation) do NOT retry — those are not quality issues.
    """
    from studio_quality_validator import validate_quality

    quality_warnings_first_pass: List[str] = []

    for attempt in range(2):
        # 1. Construct prompt (with retry guidance on attempt #2)
        try:
            prompt = _build_builder_prompt(
                brief or {}, bundle or {}, scheme,
                products or [], testimonials or [],
            )
        except Exception as e:
            return (
                None,
                f"Prompt construction failed: {type(e).__name__}: {e}",
                [],
            )

        if attempt == 1 and quality_warnings_first_pass:
            corrective = (
                "\n\n# RETRY GUIDANCE\n\n"
                "Your previous attempt had these quality issues:\n"
                + "\n".join(f"- {w}" for w in quality_warnings_first_pass)
                + "\n\nFix all of these in this attempt. The signature moment "
                "and voice proof quote especially must be visibly present."
            )
            prompt = prompt + corrective

        # 2. Call Claude
        try:
            raw = _call_claude(prompt, max_tokens=24000, timeout=300.0)
        except Exception as e:
            print(
                f"[builder] Claude call failed (attempt {attempt+1}): {e}",
                file=sys.stderr,
            )
            return (
                None,
                f"Claude call failed: {type(e).__name__}: {e}",
                [],
            )

        # 3. Extract
        html = extract_html_from_response(raw or "")
        if not html:
            print(
                f"[builder] HTML extraction failed (attempt {attempt+1})",
                file=sys.stderr,
            )
            return None, "Could not extract HTML from response", []

        # 4. Structural validation
        is_valid_html, html_errors = validate_html(html)
        if not is_valid_html:
            print(
                f"[builder] HTML validation failed (attempt {attempt+1}): "
                f"{html_errors}",
                file=sys.stderr,
            )
            return None, "HTML failed validation", html_errors

        # 5. Quality validation
        quality_ok, quality_warnings = validate_quality(html, brief or {})
        if quality_ok:
            try:
                html = inject_motion_modules(html, scheme, brief)
            except Exception as e:
                print(
                    f"[builder] motion/reactivity inject failed: {e}",
                    file=sys.stderr,
                )
            return html, None, []

        # Quality fail
        print(
            f"[builder] Quality validation failed (attempt {attempt+1}): "
            f"{quality_warnings}",
            file=sys.stderr,
        )
        if attempt == 0:
            quality_warnings_first_pass = quality_warnings
            continue

        # Second attempt also failed — ship anyway with warnings persisted.
        try:
            html = inject_motion_modules(html, scheme, brief)
        except Exception as e:
            print(
                f"[builder] motion/reactivity inject failed: {e}",
                file=sys.stderr,
            )
        return html, None, quality_warnings

    # Defensive — the for-loop always returns. Reaching here is a logic bug.
    return None, "Builder retry loop fell through unexpectedly", []
