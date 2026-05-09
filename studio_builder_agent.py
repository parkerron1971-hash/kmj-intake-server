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

def _format_punch_list_block(punch_list: Optional[List[dict]]) -> str:
    """Render Director's critique punch list as a leading prompt block.
    Empty string when punch_list is None or empty (preserves the legacy
    prompt for first-attempt builds)."""
    if not punch_list:
        return ""
    lines = [
        "═══════════════════════════════════════",
        "PUNCH LIST — FIX EACH ITEM",
        "═══════════════════════════════════════",
        "",
        "The previous build attempt failed these specific design quality",
        "rules. Fix each one in this build:",
        "",
    ]
    for v in punch_list:
        if not isinstance(v, dict):
            continue
        sev = (v.get("severity") or "MEDIUM").upper()
        rid = v.get("rule_id") or "(unknown_rule)"
        desc = (v.get("description") or "").strip()
        fix = (v.get("fix_hint") or "").strip()
        lines.append(f"[{sev}] {rid}: {desc}")
        if fix:
            lines.append(f"  Fix: {fix}")
        lines.append("")
    lines.append("Do NOT repeat these mistakes. The fixes are non-negotiable.")
    lines.append("")
    return "\n".join(lines)


def _format_maintain_block(rubric: Optional[Dict]) -> str:
    """Render the MAINTAIN — DO NOT REGRESS block (Pass 4.0b.4).

    When the Builder regenerates against a Director punch list, fixing
    the listed violations sometimes regresses on rules the previous
    attempt already satisfied (e.g., v2 introduces pure #FFFFFF that
    v1 didn't have). This block lists every canonical rule from the
    rubric so the Builder sees what it must preserve while fixing the
    punch list items. Source is the rubric file via
    rubric_to_canonical_checklist, so the prompt updates automatically
    when the rubric is edited.

    Returns empty string when rubric is missing — caller can concatenate
    unconditionally."""
    try:
        from agents.design_intelligence.rubrics import rubric_to_canonical_checklist
    except Exception:
        return ""
    checklist = rubric_to_canonical_checklist(rubric)
    if not checklist:
        return ""
    return (
        "═══════════════════════════════════════\n"
        "MAINTAIN — DO NOT REGRESS\n"
        "═══════════════════════════════════════\n"
        "\n"
        "While fixing the punch list above, you MUST preserve every rule\n"
        "below. These are the canonical standards of this Design\n"
        "Intelligence Module. Fixing one violation by introducing another\n"
        "is not progress.\n"
        "\n"
        f"{checklist}\n"
        "\n"
        "If the previous attempt already satisfied any of these, keep\n"
        "doing what worked. Only change what's needed to address the\n"
        "punch list.\n"
        "\n"
    )


def _build_builder_prompt(
    brief: dict,
    bundle: dict,
    scheme: Optional[dict],
    products: list,
    testimonials: list,
    punch_list: Optional[List[dict]] = None,
    rubric: Optional[Dict] = None,
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

    # ── Pass 3.8g — Solutionist Quality rules block ─────────────────
    # Embedded directly in the prompt so Builder receives the measurable
    # rules verbatim. Behind the SOLUTIONIST_QUALITY_ENABLED kill switch.
    solutionist_block = ""
    try:
        from studio_config import SOLUTIONIST_QUALITY_ENABLED
        if SOLUTIONIST_QUALITY_ENABLED:
            from studio_solutionist_quality import get_quality_rules_block_for_prompt
            solutionist_block = get_quality_rules_block_for_prompt()
    except Exception as e:
        import sys as _sys
        print(f"[builder] solutionist block import failed: {e}", file=_sys.stderr)

    # ── Pass 3.8g — multi-page navigation context (optional) ────────
    # When the multi-page builder is active, brief carries _nav_html +
    # _other_pages + _current_page so the Builder knows it is producing
    # one of N pages, not a standalone landing page.
    multipage_block = ""
    other_pages = brief.get("_other_pages") if isinstance(brief, dict) else None
    current_page = brief.get("_current_page") if isinstance(brief, dict) else None
    page_id = brief.get("_page_id") if isinstance(brief, dict) else None
    page_name = brief.get("_page_name") if isinstance(brief, dict) else None
    if (other_pages and current_page) or page_id:
        mp_lines = [
            "═══════════════════════════════════════",
            "MULTI-PAGE CONTEXT",
            "═══════════════════════════════════════",
        ]
        if page_name or page_id:
            mp_lines.append(
                f"\nThis is the {page_name or page_id} page of a multi-page site."
            )
        if other_pages:
            mp_lines.append(
                f"Other pages exist at: {', '.join(other_pages)}. "
                "Do NOT repeat the home-page hero verbatim — this page has its own role."
            )
        mp_lines.append(
            "A site-wide nav bar will be injected at <body>. Do NOT design your own nav."
        )
        multipage_block = "\n".join(mp_lines)

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

    punch_list_block = _format_punch_list_block(punch_list)
    # Pass 4.0b.4: MAINTAIN block only renders when there's a punch list
    # AND a rubric. First-attempt builds (no punch list) and regenerates
    # without a rubric supplied (legacy callers) get the legacy prompt.
    maintain_block = _format_maintain_block(rubric) if punch_list else ""

    # Pass 4.0b.5 PART 4: SLOT TAGS instruction. Tells the Builder to
    # emit <img data-slot="..." src=""> for image positions; the slot
    # system populates src at render time from Unsplash / DALL-E / user
    # uploads. Without this block the model invents ad-hoc placeholders
    # like 'PRE-IMAGE' / 'PRO-IMAGE' (seen in Pass 4.0b.4 output).
    slot_tags_block = """═══════════════════════════════════════
IMAGE SLOTS — USE THE SLOT SYSTEM
═══════════════════════════════════════

When an image is needed, embed it as:

    <img data-slot="<slot_name>" src="" alt="<one-sentence description>">

Leave src="" empty. The platform fills it at render time from Unsplash
(atmosphere), DALL-E (decorative), or practitioner uploads (profile).
Do NOT hardcode image URLs. Do NOT invent placeholder text like
"PRE-IMAGE", "[hero image goes here]", or empty <div> rectangles.

Available slot names (pick the most fitting role for each position):

  PROFILE — practitioner / founder portraits.
  Render as upload-prompt placeholders by default. Never auto-fill.
    about_subject   — Practitioner headshot/portrait (4:5)
    founder_photo   — Founder portrait (1:1)

  ATMOSPHERE — environmental / contextual photography (Unsplash).
    hero_main       — Primary hero image (16:9)
    chamber_main    — Atmospheric / environmental (3:2)
    gallery_1       — Gallery image 1 (4:3)
    gallery_2       — Gallery image 2 (4:3)
    gallery_3       — Gallery image 3 (4:3)
    gallery_4       — Gallery image 4 (4:3)

  DECORATIVE — abstract textures, accents (DALL-E).
    decorative_1    — Texture / abstract accent (1:1)
    decorative_2    — Texture / abstract accent (1:1)
    decorative_3    — Texture / abstract accent (1:1)

Slot Usage Floor — by content archetype:

A complete site demands visual richness layered with typographic restraint.
The 'less is more' principle applies to TYPE, COPY, and SECTIONING — NOT
to imagery. A premium site with one hero image and nothing else reads as
undercooked, regardless of how strong the typography is.

Required slots by archetype:
  - service_business / coaching_practice:
      hero_main, about_subject (the practitioner is the brand),
      2-3 gallery slots showing the work or environment,
      1 decorative accent. Minimum 5 image-bearing slots.
  - knowledge_brand / course_creator:
      hero_main, founder_photo (or about_subject),
      1-2 gallery slots, 2 decorative accents. Minimum 5 slots.
  - ministry / community_platform:
      hero_main, founder_photo, chamber_main,
      2 gallery slots. Minimum 5 slots.
  - product_business / ecommerce:
      hero_main, 4 gallery slots, 1-2 decorative.
      Minimum 6 slots.
  - creative_agency / consultant:
      hero_main, founder_photo, 2-3 gallery slots,
      2 decorative. Minimum 6 slots.
  - custom / general:
      hero_main, about_subject, 2 gallery slots,
      1 decorative. Minimum 5 slots.

Profile slots (about_subject, founder_photo) are critical — they
represent the human at the center of the brand. Always include at
least one profile slot for service-led businesses. The slot will
render as a styled "Add your photo" placeholder until the practitioner
uploads — that placeholder IS part of the design language, not a
missing image.

Decorative slots are NOT optional for premium aesthetic. They provide
texture and atmosphere that typography alone cannot deliver. Use at
least one for every site claiming Cinematic Authority, Cathedral, or
premium positioning.

Other rules:
  - Each slot can appear AT MOST ONCE per page.
  - Match role to position: hero gets atmosphere (hero_main), about
    section gets profile (about_subject), accent shapes get decorative.
  - Profile slot alt text is a prompt for the practitioner — describe
    what kind of photo would suit ("Practitioner portrait, three-quarter
    angle, warm low light"), not what to fill in temporarily.
  - Atmosphere slot alt text becomes the Unsplash search seed — be
    specific and evocative ("leather barber chair under tungsten light"
    beats "barber chair").
  - Decorative slot alt text becomes part of the DALL-E prompt — describe
    the texture or shape, not a literal subject.

Example:

    <img data-slot="hero_main" src=""
         alt="Royal Palace Barbershop interior at dusk, leather chairs
              catching low gold light, deep shadows in the corners">

"""

    return f"""{punch_list_block}{maintain_block}{slot_tags_block}You are a senior creative director and master frontend developer. You build production websites that feel genuinely designed — not assembled from templates. You read a creative brief the way a designer reads one: you understand the tension, feel the spatial logic, hear the copy voice. Then you build.

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

{solutionist_block}

{multipage_block}

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

# RULES (Pass 3.8g — Solutionist Quality additions)

- Every h2 MUST contain ONE italic accent word wrapped in <em class="accent-word">. The accent word is the emotional core of the heading.
- Every h2 MUST be preceded by (1) a 3px-tall gold accent line (about 48px wide), AND (2) a small uppercase letter-spaced eyebrow label.
- All buttons MUST be pill-shaped (border-radius: 999px). NEVER 4-12px corners on buttons.
- All cards MUST have border-radius: 28px or greater. NEVER use 4-12px corners on cards.
- All section padding MUST be 80px minimum top/bottom (120-140px ideal on desktop).
- Use warm whites: #F8F6F1 backgrounds, #F4F0E8 text on dark. NEVER pure #FFFFFF anywhere.
- Every primary CTA button MUST have class="cta-button" so the reactivity layer applies the shimmer pass.
- Every section MUST be a <section> tag OR carry a data-reveal attribute so the scroll-reveal layer animates it.
- Hero photo / feature image wrapper MUST carry data-headshot-frame so the pulse-glow layer attaches.
- Use the custom easing curve cubic-bezier(0.16, 1, 0.3, 1) for all transitions (it will be reinforced by the reactivity layer; specifying it locally on hover transforms is correct).
- h1 weight MUST be 900; h2 weight MUST be 800. h1 letter-spacing -2.4px; h2 letter-spacing -1.6px.

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
    punch_list: Optional[List[dict]] = None,
    rubric: Optional[Dict] = None,
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

    `punch_list` (Pass 4.0b PART 3) is the Director's external critique
    output — a list of violation dicts {rule_id, severity, description,
    fix_hint}. When provided, it's prepended to the prompt as a
    non-negotiable fix list. The internal first-pass→retry quality loop
    still runs after; punch list addresses Director's findings, internal
    retry addresses Builder's own quality warnings. Default None preserves
    backward compatibility for first-attempt builds.

    `rubric` (Pass 4.0b.4) is the Design Intelligence Module rubric
    dict. When supplied alongside a non-empty punch_list, the prompt
    also gets a MAINTAIN — DO NOT REGRESS block listing every canonical
    rule from the rubric, so fixing the punch list doesn't regress on
    rules the previous attempt already satisfied. Ignored without a
    punch list (first-attempt builds don't need a maintenance check).
    """
    from studio_quality_validator import validate_quality

    quality_warnings_first_pass: List[str] = []
    # Pass 4.0b.4 observability: every iteration of the internal retry
    # logs its start + outcome so Railway logs prove the retry runs even
    # on punch-list-driven (regenerate) builds. Otherwise it's hard to
    # tell from outside whether v2 quality warnings come from a single
    # attempt that gave up or a true 2-attempt retry that still failed.
    print(
        f"[builder] build_html invoked: "
        f"punch_list_size={len(punch_list or [])}, "
        f"rubric_supplied={bool(rubric)}",
        file=sys.stderr,
    )

    for attempt in range(2):
        print(
            f"[builder] attempt {attempt+1}/2 starting "
            f"(punch_list={'present' if punch_list else 'absent'}, "
            f"maintain_block={'present' if (punch_list and rubric) else 'absent'})",
            file=sys.stderr,
        )

        # 1. Construct prompt (with retry guidance on attempt #2)
        try:
            prompt = _build_builder_prompt(
                brief or {}, bundle or {}, scheme,
                products or [], testimonials or [],
                punch_list=punch_list,
                rubric=rubric,
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

        # 5. Quality validation — Pass 3.8f checks (signature moment, voice
        # quote, banned labels, palette discipline) PLUS Pass 3.8g
        # Solutionist Quality checks (italic accent words, padding, radii,
        # warm whites, heading weights, generic colors).
        quality_ok, quality_warnings = validate_quality(html, brief or {})
        try:
            from studio_config import SOLUTIONIST_QUALITY_ENABLED
            if SOLUTIONIST_QUALITY_ENABLED:
                from studio_solutionist_quality import validate_solutionist_quality
                sq_ok, sq_warnings = validate_solutionist_quality(html)
                if not sq_ok:
                    quality_warnings = list(quality_warnings) + list(sq_warnings)
                    quality_ok = False
        except Exception as e:
            print(
                f"[builder] solutionist quality validate failed: {e}",
                file=sys.stderr,
            )
        if quality_ok:
            print(
                f"[builder] attempt {attempt+1}/2 quality_ok=True; shipping clean",
                file=sys.stderr,
            )
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
            f"[builder] Quality validation failed (attempt {attempt+1}/2): "
            f"{quality_warnings}",
            file=sys.stderr,
        )
        if attempt == 0:
            quality_warnings_first_pass = quality_warnings
            continue

        # Second attempt also failed — ship anyway with warnings persisted.
        print(
            f"[builder] retry loop completed; both attempts had quality "
            f"warnings; shipping with {len(quality_warnings)} warnings",
            file=sys.stderr,
        )
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
