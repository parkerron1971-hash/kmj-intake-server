"""Shared rendering helpers used by all 12 layout modules.

Every layout calls these for: head, footer, in-the-clear badge, archetype
touches, disclaimers. Layout-specific CSS lives in each layout's own module.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from studio_composite import CompositeDirection
from studio_design_system import DesignSystem, _pick_contrast_text, _pick_accent_contrast


def safe_html(text: Optional[str], default: str = "") -> str:
    """Escape HTML special chars."""
    if not text:
        return default
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def render_motion_styles() -> str:
    """Pass 3.7: global CSS for scroll reveals, hover effects, marquee.
    Honors prefers-reduced-motion and suppresses heavy decorations on
    mobile (< 640px viewport). One block, included once per page via
    render_head().
    """
    return """
<style>
/* Scroll reveal — sections fade up as they enter viewport */
.reveal {
  opacity: 0;
  transform: translateY(20px);
  transition: opacity 0.8s ease-out, transform 0.8s ease-out;
}
.reveal.visible { opacity: 1; transform: translateY(0); }

/* Hover lift — cards rise on hover */
.hover-lift {
  transition: transform 0.3s ease, box-shadow 0.3s ease;
}
.hover-lift:hover {
  transform: translateY(-4px);
  box-shadow: 0 12px 28px rgba(0,0,0,0.10);
}

/* Marquee for ticker bands */
.marquee { display: flex; overflow: hidden; white-space: nowrap; }
.marquee-content {
  display: inline-flex;
  animation: marquee-roll 30s linear infinite;
}
@keyframes marquee-roll {
  from { transform: translateX(0); }
  to   { transform: translateX(-50%); }
}

/* Form-field focus glow */
input:focus, select:focus, textarea:focus {
  outline: 2px solid currentColor;
  outline-offset: 2px;
}

/* Mobile: suppress heavy decorations (corner brackets, glow halos,
   geometric ornaments). Section dividers stay because they're cheap. */
@media (max-width: 640px) {
  .heavy-decoration { display: none !important; }
}

/* Honor users who prefer reduced motion: kill all animation. */
@media (prefers-reduced-motion: reduce) {
  .reveal { opacity: 1; transform: none; transition: none; }
  .hover-lift { transition: none; }
  .hover-lift:hover { transform: none; box-shadow: none; }
  .marquee-content { animation: none; }
  *, *::before, *::after {
    animation-duration: 0s !important;
    transition-duration: 0s !important;
  }
}
</style>
"""


def render_motion_script() -> str:
    """Pass 3.7: single inline IntersectionObserver script for scroll
    reveals. Self-contained, no dependencies, no library. Place once
    per page near </body>.
    """
    return """
<script>
(function() {
  if (!('IntersectionObserver' in window)) {
    document.querySelectorAll('.reveal').forEach(function(el) { el.classList.add('visible'); });
    return;
  }
  var observer = new IntersectionObserver(function(entries) {
    entries.forEach(function(entry) {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.1, rootMargin: '0px 0px -50px 0px' });
  document.querySelectorAll('.reveal').forEach(function(el) { observer.observe(el); });
})();
</script>
"""


def render_head(
    business_name: str,
    design_system: DesignSystem,
    head_meta_extra: str = "",
) -> str:
    """Return the <head> section common to all layouts.

    Includes meta charset/viewport, title, Google Fonts link, base
    typography CSS, reveal animation CSS, motion styles (Pass 3.7),
    and any extra meta passed by the caller (favicon/social card from
    public_site._brand_head_meta_tags).
    """
    google_fonts_link = (
        f'<link href="{design_system["google_fonts_url"]}" rel="stylesheet">'
        if design_system.get("google_fonts_url")
        else ""
    )
    return f"""<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{safe_html(business_name)}</title>
{head_meta_extra}
{google_fonts_link}
<style>
{design_system['typography_css']}
{design_system['reveal_css']}
</style>
{render_motion_styles()}
</head>"""


def render_in_the_clear_badge(bundle: Dict[str, Any], design_system: DesignSystem) -> str:
    """Return a styled badge HTML when bundle.legal.in_the_clear is true.
    Empty string otherwise — caller can drop it directly into output."""
    if not (bundle.get("legal") or {}).get("in_the_clear"):
        return ""
    accent = design_system["palette_accent"]
    bg = design_system["palette_bg"]
    text_color = _pick_contrast_text(bg, dark_color=design_system["palette_text"])
    return (
        '<div class="itc-badge" '
        'style="display:inline-flex;align-items:center;gap:6px;'
        'padding:6px 14px;border-radius:999px;'
        f'background:color-mix(in srgb,{accent} 18%,transparent);'
        f'color:{text_color};font-size:0.85rem;font-weight:500;">'
        '✓ Verified Business</div>'
    )


def render_archetype_touch(
    archetype: str,
    position: str,
    design_system: DesignSystem,
    bundle: Dict[str, Any],
) -> str:
    """Return archetype-specific HTML fragment for a position.

    Position is one of:
      - 'before_about'      — disclosure box above the about section
      - 'after_services'    — callout below the services section
      - 'footer_addendum'   — extra block in the footer

    Empty string when the archetype + position combination has no touch.
    """
    accent = design_system["palette_accent"]
    bg = design_system["palette_bg"]
    text = design_system["palette_text"]
    box_text = _pick_contrast_text(bg, dark_color=text)
    box_bg = "rgba(0,0,0,0.03)" if _pick_contrast_text(bg) == "#1A1A1A" else "rgba(255,255,255,0.04)"

    if archetype == "financial_educator" and position == "before_about":
        return f"""
<section style="max-width:960px;margin:0 auto;padding:32px 24px;">
  <div style="border-left:4px solid {accent};padding:18px 24px;background:{box_bg};color:{box_text};font-size:0.95rem;line-height:1.6;border-radius:6px;">
    <strong>Educational Content Only.</strong> All material is for educational purposes only and does not constitute financial, investment, or tax advice. Past performance does not guarantee future results.
  </div>
</section>
"""
    if archetype == "fitness_wellness" and position == "after_services":
        return f"""
<section style="max-width:960px;margin:0 auto;padding:32px 24px;">
  <div style="border:1px solid color-mix(in srgb,{text} 12%,transparent);padding:20px 24px;border-radius:8px;color:{box_text};font-size:0.9rem;line-height:1.6;">
    <strong>Health Disclaimer.</strong> Information provided is for educational purposes and is not medical advice. Consult a qualified healthcare provider before starting any health, fitness, or wellness program.
  </div>
</section>
"""
    if archetype == "coach" and position == "after_services":
        return f"""
<section style="max-width:960px;margin:0 auto;padding:32px 24px;">
  <div style="border-left:4px solid {accent};padding:18px 24px;background:{box_bg};color:{box_text};font-size:0.9rem;line-height:1.6;border-radius:6px;">
    <strong>Results vary.</strong> Coaching outcomes depend on the participant's engagement and effort. Outcomes are not guaranteed.
  </div>
</section>
"""
    if archetype == "consultant" and position == "after_services":
        return f"""
<section style="max-width:960px;margin:0 auto;padding:32px 24px;">
  <div style="border:1px solid color-mix(in srgb,{accent} 30%,transparent);padding:18px 24px;border-radius:6px;color:{box_text};font-size:0.9rem;line-height:1.6;">
    <strong>Engagements are bespoke.</strong> Scope and deliverables are defined in writing per engagement. Past client results do not guarantee future outcomes.
  </div>
</section>
"""
    if archetype == "creative" and position == "after_services":
        return f"""
<section style="max-width:960px;margin:0 auto;padding:32px 24px;">
  <div style="padding:18px 24px;background:{box_bg};color:{box_text};font-size:0.9rem;line-height:1.6;border-radius:6px;">
    <strong>Portfolio rights.</strong> Provider retains the right to display work in portfolio unless otherwise agreed. Deliverables transfer to the client upon final payment.
  </div>
</section>
"""
    if archetype == "course_creator" and position == "after_services":
        return f"""
<section style="max-width:960px;margin:0 auto;padding:32px 24px;">
  <div style="padding:18px 24px;background:{box_bg};color:{box_text};font-size:0.9rem;line-height:1.6;border-radius:6px;">
    <strong>Course access &amp; terms.</strong> Course content may not be redistributed. Refund and access terms are stated in the enrollment agreement.
  </div>
</section>
"""
    if archetype == "service_provider" and position == "after_services":
        slug = (bundle.get("business") or {}).get("slug")
        href = f"/public/booking/{slug}" if slug else "#contact"
        return f"""
<section style="max-width:960px;margin:0 auto;padding:32px 24px;">
  <div style="padding:18px 24px;background:{box_bg};color:{box_text};font-size:0.95rem;line-height:1.6;border-radius:6px;">
    <strong>Book with us.</strong> Choose a time that works for you. <a href="{href}" style="color:{accent};">View open slots →</a>
  </div>
</section>
"""
    return ""


def render_disclaimers(bundle: Dict[str, Any]) -> str:
    """Return all required disclaimers joined into a single text block.

    Pulls from brand_engine.DISCLAIMER_PHRASES — keeps Smart Sites' source
    of truth aligned. Returns empty string when no disclaimers configured
    or when brand_engine isn't importable in this context.
    """
    disclaimers = (bundle.get("legal") or {}).get("required_disclaimers") or []
    if not disclaimers:
        return ""
    try:
        from brand_engine import DISCLAIMER_PHRASES
    except Exception:
        return ""
    items = [DISCLAIMER_PHRASES.get(d, "") for d in disclaimers if DISCLAIMER_PHRASES.get(d)]
    return " ".join(items) if items else ""


def render_footer(
    business_data: Dict[str, Any],
    bundle: Dict[str, Any],
    design_system: DesignSystem,
    footer_extra_text: Optional[str] = None,
) -> str:
    """Return the <footer> section common to all layouts.

    Pulls copyright_line from bundle.footer, contact_email if present,
    and required disclaimers. Layout-specific styling can wrap this.
    """
    bg = design_system["palette_bg"]
    text = design_system["palette_text"]

    practitioner = (bundle.get("practitioner") or {}).get("display_name") or "The Practitioner"
    copyright_line = (
        (bundle.get("footer") or {}).get("copyright_line")
        or f"© {datetime.now().year} {safe_html(practitioner)}"
    )
    contact_email = (bundle.get("footer") or {}).get("contact_email") or ""
    disclaimers = render_disclaimers(bundle)

    disc_html = (
        f'<div style="max-width:700px;margin:1em auto;font-size:0.8rem;line-height:1.5;">{safe_html(disclaimers)}</div>'
        if disclaimers else ''
    )
    contact_html = (
        f'<div style="margin-top:1em;"><a href="mailto:{safe_html(contact_email)}" style="color:inherit;">{safe_html(contact_email)}</a></div>'
        if contact_email else ''
    )
    extra_html = (
        f'<div style="margin-top:1em;font-size:0.85rem;">{safe_html(footer_extra_text)}</div>'
        if footer_extra_text else ''
    )
    return f"""
<footer style="background:color-mix(in srgb,{text} 4%,{bg});padding:48px 24px;text-align:center;font-size:0.9rem;color:color-mix(in srgb,{text} 65%,transparent);">
  <div>{safe_html(copyright_line)}</div>
  {disc_html}
  {extra_html}
  {contact_html}
</footer>
"""


# ─── Pass 3.6: section dispatchers + Stripe button ──────────────────


def render_stripe_button(product: Dict[str, Any], design_system: DesignSystem) -> str:
    """Pass 3.6: when a product has stripe_payment_url set, render a
    vibe-aware Purchase button. Returns empty string when the URL is
    absent, so callers can append unconditionally.
    """
    if not isinstance(product, dict):
        return ""
    url = product.get("stripe_payment_url")
    if not url or not isinstance(url, str) or not url.strip():
        return ""
    accent = design_system["palette_accent"]
    on_accent = _pick_accent_contrast(accent)
    return (
        f'<a href="{safe_html(url)}" target="_blank" rel="noopener" '
        f'style="display:inline-block;padding:10px 20px;background:{accent};'
        f'color:{on_accent};text-decoration:none;border-radius:4px;'
        f'font-weight:500;margin-top:0.75rem;font-size:0.9rem;">Purchase &rarr;</a>'
    )


def _safe_section_render(fn, *args, **kwargs) -> str:
    """Run a section renderer; swallow any exception and return empty
    string. Pass 3.6 invariant: a single section's failure must NEVER
    break the page."""
    try:
        result = fn(*args, **kwargs)
        return result if isinstance(result, str) else ""
    except Exception:
        return ""


def render_testimonials_section(
    design_system: DesignSystem,
    sections_config: Dict[str, Any],
    bundle: Dict[str, Any],
    bespoke=None,
    vocab_id: Optional[str] = None,
) -> str:
    """Render the testimonials section with try/except safety.
    `bespoke`: optional callable with the same signature as the shared
    renderer; layouts that need a bespoke override (e.g. community-hub)
    pass it in. `vocab_id` (Pass 3.7): drives decoration character.
    """
    cfg = (sections_config or {}).get("testimonials") or {}
    if not cfg.get("enabled", False):
        return ""
    items = cfg.get("items") or []
    if bespoke is not None:
        return _safe_section_render(bespoke, design_system, items, cfg, bundle, vocab_id)
    from studio_layouts.sections.testimonials import render as _shared
    return _safe_section_render(_shared, design_system, items, cfg, bundle, vocab_id)


def render_gallery_section(
    design_system: DesignSystem,
    sections_config: Dict[str, Any],
    bundle: Dict[str, Any],
    bespoke=None,
    vocab_id: Optional[str] = None,
) -> str:
    cfg = (sections_config or {}).get("gallery") or {}
    if not cfg.get("enabled", False):
        return ""
    items = cfg.get("items") or []
    if bespoke is not None:
        return _safe_section_render(bespoke, design_system, items, cfg, bundle, vocab_id)
    from studio_layouts.sections.gallery import render as _shared
    return _safe_section_render(_shared, design_system, items, cfg, bundle, vocab_id)


def render_resources_section(
    design_system: DesignSystem,
    sections_config: Dict[str, Any],
    bundle: Dict[str, Any],
    bespoke=None,
    vocab_id: Optional[str] = None,
) -> str:
    cfg = (sections_config or {}).get("resources") or {}
    if not cfg.get("enabled", False):
        return ""
    items = cfg.get("items") or []
    if bespoke is not None:
        return _safe_section_render(bespoke, design_system, items, cfg, bundle, vocab_id)
    from studio_layouts.sections.resources import render as _shared
    return _safe_section_render(_shared, design_system, items, cfg, bundle, vocab_id)


def render_contact_section(
    design_system: DesignSystem,
    business_id: str,
    sections_config: Dict[str, Any],
    bundle: Dict[str, Any],
    bespoke=None,
    vocab_id: Optional[str] = None,
) -> str:
    cfg = (sections_config or {}).get("contact") or {}
    if not cfg.get("enabled", False):
        return ""
    if bespoke is not None:
        return _safe_section_render(bespoke, design_system, business_id, cfg, bundle, vocab_id)
    from studio_layouts.sections.contact import render as _shared
    return _safe_section_render(_shared, design_system, business_id, cfg, bundle, vocab_id)


def render_appendix_sections(
    design_system: DesignSystem,
    business_id: str,
    sections_config: Dict[str, Any],
    bundle: Dict[str, Any],
    *,
    bespoke_testimonials=None,
    bespoke_gallery=None,
    bespoke_resources=None,
    bespoke_contact=None,
    vocab_id: Optional[str] = None,
) -> str:
    """Render testimonials + gallery + resources + contact in order.

    Each section is wrapped in `_safe_section_render` so any failure
    yields an empty string instead of breaking the layout. Pass a
    `bespoke_*=` callable to swap the default shared renderer for a
    layout-specific override.

    Pass 3.7: `vocab_id` flows through to section renderers so they can
    apply vocabulary-specific decoration via studio_decoration.
    """
    parts = [
        render_testimonials_section(design_system, sections_config, bundle, bespoke=bespoke_testimonials, vocab_id=vocab_id),
        render_gallery_section(design_system, sections_config, bundle, bespoke=bespoke_gallery, vocab_id=vocab_id),
        render_resources_section(design_system, sections_config, bundle, bespoke=bespoke_resources, vocab_id=vocab_id),
        render_contact_section(design_system, business_id, sections_config, bundle, bespoke=bespoke_contact, vocab_id=vocab_id),
    ]
    return "".join(p for p in parts if p)


# ─── Pass 3.7c: scheme override slot system ──────────────────────────
#
# Layouts use these helpers to read the AI-generated decoration scheme
# with deterministic fallbacks. When `scheme` is None or any field is
# missing, the existing Pass 3.7/3.7b deterministic decoration takes
# over via the fallback argument.
#
# Every read goes through safe_read so a malformed scheme can never
# break a layout — worst case is "fall back to defaults".


def get_color_token(scheme, token_name, fallback):
    """Read a color token from scheme with deterministic fallback.

    token_name: 'bg' | 'bg2' | 'bg3' | 'accent' | 'accent_secondary' |
                'text' | 'muted' | 'line'
    """
    try:
        from studio_decoration_scheme import safe_read
        val = safe_read(scheme, f"color_tokens.{token_name}")
        return val if val else fallback
    except Exception:
        return fallback


def get_typography(scheme, key, fallback):
    """Read a typography field with fallback.

    key: 'font_display' | 'font_body' | 'font_accent' | 'h1_size' |
         'h1_letter_spacing' | 'h2_size' | 'eyebrow_letter_spacing'
    """
    try:
        from studio_decoration_scheme import safe_read
        val = safe_read(scheme, f"typography.{key}")
        return val if val else fallback
    except Exception:
        return fallback


def get_spatial(scheme, key, fallback):
    """Read a spatial DNA field with fallback."""
    try:
        from studio_decoration_scheme import safe_read
        val = safe_read(scheme, f"spatial_dna.{key}")
        return val if val else fallback
    except Exception:
        return fallback


def get_decoration_choice(scheme, key, fallback):
    """Read a decoration choice field with fallback."""
    try:
        from studio_decoration_scheme import safe_read
        val = safe_read(scheme, f"decorations.{key}")
        return val if val else fallback
    except Exception:
        return fallback


def is_motion_enabled(scheme, module):
    """Test whether a motion module is enabled in the scheme.

    module: 'enable_ghost_numbers' | 'enable_marquee_strips' |
            'enable_magnetic_buttons' | 'enable_statement_bars' |
            'parallax_backgrounds'
    """
    try:
        from studio_decoration_scheme import safe_read
        val = safe_read(scheme, f"motion_richness.{module}")
        return bool(val) if val is not None else False
    except Exception:
        return False


def get_marquee_text(scheme):
    try:
        from studio_decoration_scheme import safe_read
        return safe_read(scheme, "marquee_text")
    except Exception:
        return None


def get_statement_quotes(scheme):
    try:
        from studio_decoration_scheme import safe_read
        val = safe_read(scheme, "statement_bar_quotes", [])
        return val if isinstance(val, list) else []
    except Exception:
        return []


def apply_scheme_to_design_system(design_system, scheme):
    """Apply scheme color/typography overrides to a design_system dict.

    Returns a NEW dict — caller's design_system is not mutated. When
    scheme is None or has empty token blocks, returns a copy of the
    original. Layout code below this point reads palette_bg /
    palette_accent / palette_text / etc. and gets the overridden
    values transparently.
    """
    if not isinstance(design_system, dict):
        return design_system
    ds = dict(design_system)
    if not isinstance(scheme, dict):
        return ds

    # color_tokens.* -> design_system.palette_*
    color_map = {
        "bg":      "palette_bg",
        "accent":  "palette_accent",
        "text":    "palette_text",
        "muted":   "palette_muted",
        # bg2 maps to palette_surface (the "card / panel" background)
        "bg2":     "palette_surface",
    }
    for scheme_key, ds_key in color_map.items():
        try:
            from studio_decoration_scheme import safe_read
            val = safe_read(scheme, f"color_tokens.{scheme_key}")
            if val:
                ds[ds_key] = val
        except Exception:
            pass

    # typography.* -> design_system fields
    type_map = {
        "font_display": "font_display",
        "font_body":    "font_body",
    }
    for scheme_key, ds_key in type_map.items():
        try:
            from studio_decoration_scheme import safe_read
            val = safe_read(scheme, f"typography.{scheme_key}")
            if val:
                ds[ds_key] = val
        except Exception:
            pass

    return ds


def render_decoration_head(design_system, scheme):
    """Combined motion-module styles to inject into <head>.

    Each module's styles are loaded only when its enable_* flag is true
    in the scheme. Any import error swallows silently so a missing
    module never breaks rendering.
    """
    if not scheme:
        return ""
    parts = []
    if is_motion_enabled(scheme, "enable_ghost_numbers"):
        try:
            from studio_layouts.motion_modules.ghost_numbers import render_styles as gn_styles
            parts.append(gn_styles())
        except Exception:
            pass
    if is_motion_enabled(scheme, "enable_marquee_strips"):
        try:
            from studio_layouts.motion_modules.marquee_strip import render_styles as ms_styles
            parts.append(ms_styles(design_system))
        except Exception:
            pass
    if is_motion_enabled(scheme, "enable_magnetic_buttons"):
        try:
            from studio_layouts.motion_modules.magnetic_button import render_styles as mb_styles
            parts.append(mb_styles())
        except Exception:
            pass
    if is_motion_enabled(scheme, "enable_statement_bars"):
        try:
            from studio_layouts.motion_modules.statement_bar import render_styles as sb_styles
            parts.append(sb_styles(design_system))
        except Exception:
            pass
    return "\n".join(parts)


def render_decoration_scripts(scheme):
    """Combined motion-module scripts to inject before </body>."""
    if not scheme:
        return ""
    parts = []
    if is_motion_enabled(scheme, "enable_ghost_numbers"):
        try:
            from studio_layouts.motion_modules.ghost_numbers import render_script as gn_script
            parts.append(gn_script())
        except Exception:
            pass
    if is_motion_enabled(scheme, "enable_magnetic_buttons"):
        try:
            from studio_layouts.motion_modules.magnetic_button import render_script as mb_script
            parts.append(mb_script())
        except Exception:
            pass
    return "\n".join(parts)


def render_scheme_after_hero(design_system, scheme):
    """Inline modules that go directly after the hero section: a
    statement bar with the first quote, then a marquee strip if
    enabled. Returns "" when no modules are enabled or content is
    missing — safe to inject unconditionally.
    """
    if not scheme:
        return ""
    parts = []
    try:
        if is_motion_enabled(scheme, "enable_statement_bars"):
            quotes = get_statement_quotes(scheme)
            if quotes:
                from studio_layouts.motion_modules.statement_bar import render_inline as sb_inline
                parts.append(sb_inline(quotes[0]))
        if is_motion_enabled(scheme, "enable_marquee_strips"):
            mt = get_marquee_text(scheme)
            if mt:
                from studio_layouts.motion_modules.marquee_strip import render_inline as ms_inline
                parts.append(ms_inline(mt))
    except Exception:
        pass
    return "\n".join(parts)


def render_scheme_between_sections(scheme, idx=1):
    """Optional second statement bar between content sections; uses the
    next quote if available.
    """
    if not scheme:
        return ""
    try:
        if is_motion_enabled(scheme, "enable_statement_bars"):
            quotes = get_statement_quotes(scheme)
            if len(quotes) > idx:
                from studio_layouts.motion_modules.statement_bar import render_inline as sb_inline
                return sb_inline(quotes[idx])
    except Exception:
        pass
    return ""


def magnetic_class(scheme, base_class=""):
    """Append ' magnetic' to a CSS class list when magnetic CTAs are
    enabled. Use in layout HTML like:
        class="auth-cta{magnetic_class(scheme)}"
    """
    if is_motion_enabled(scheme, "enable_magnetic_buttons"):
        return f" magnetic" if not base_class else f"{base_class} magnetic"
    return base_class
