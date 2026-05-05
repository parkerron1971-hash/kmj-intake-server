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


def render_head(
    business_name: str,
    design_system: DesignSystem,
    head_meta_extra: str = "",
) -> str:
    """Return the <head> section common to all layouts.

    Includes meta charset/viewport, title, Google Fonts link, base
    typography CSS, reveal animation CSS, and any extra meta passed
    by the caller (favicon/social card from public_site._brand_head_meta_tags).
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
