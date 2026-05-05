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
