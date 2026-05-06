"""Movement layout — mission statement front & center, full-bleed accent
hero, action-oriented language, prominent join/signup CTA.

Vocabulary affinity: activist-advocate, faith-ministry, street-culture,
warm-community.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from studio_composite import CompositeDirection
from studio_design_system import DesignSystem, _pick_accent_contrast, _pick_contrast_text
from studio_layouts.shared import (
    render_appendix_sections, render_archetype_touch, render_footer,
    render_head, render_in_the_clear_badge, render_stripe_button, safe_html, render_motion_script,
    render_decoration_head, render_decoration_scripts, render_scheme_after_hero,
)
from studio_decoration import render_decoration_for


def _bespoke_contact(design_system, business_id, section_config, bundle, vocab_id=None):
    """Pass 3.6: bespoke movement contact — full-bleed accent band,
    'Get in touch' as a call to action, oversize form, action-oriented
    button copy ('Send it', 'Speak up')."""
    if not section_config.get("enabled", False):
        return ""

    accent = design_system["palette_accent"]
    on_accent = _pick_accent_contrast(accent)
    bg = design_system["palette_bg"]
    text = design_system["palette_text"]
    display_font = design_system["font_display"]
    body_font = design_system["font_body"]

    fallback_email = (bundle.get("footer") or {}).get("contact_email") or ""
    email = safe_html(section_config.get("email") or fallback_email)
    phone = safe_html(section_config.get("phone") or "")
    show_form = bool(section_config.get("show_form", True))
    js_safe_id = business_id.replace("-", "_")

    info_inline = []
    if email:
        info_inline.append(
            f'<a href="mailto:{email}" style="color:{on_accent};text-decoration:underline;">{email}</a>'
        )
    if phone:
        info_inline.append(
            f'<a href="tel:{phone}" style="color:{on_accent};text-decoration:underline;">{phone}</a>'
        )
    info_html = " &middot; ".join(info_inline) if info_inline else ""

    form_html = ""
    if show_form:
        form_html = f"""
<form id="contact-form-{business_id}" onsubmit="return submitContact_{js_safe_id}(event)" style="display:flex;flex-direction:column;gap:1.25rem;max-width:680px;margin-top:2.5rem;">
  <input type="text" name="name" required maxlength="200" placeholder="Your name" style="width:100%;padding:18px 22px;border:2px solid {on_accent};border-radius:0;background:transparent;color:{on_accent};font-family:'{body_font}',sans-serif;font-size:1.1rem;">
  <input type="email" name="email" required maxlength="200" placeholder="Your email" style="width:100%;padding:18px 22px;border:2px solid {on_accent};border-radius:0;background:transparent;color:{on_accent};font-family:'{body_font}',sans-serif;font-size:1.1rem;">
  <textarea name="message" required rows="5" maxlength="5000" placeholder="What's on your mind?" style="width:100%;padding:18px 22px;border:2px solid {on_accent};border-radius:0;background:transparent;color:{on_accent};font-family:'{body_font}',sans-serif;resize:vertical;font-size:1.1rem;"></textarea>
  <button type="submit" style="padding:20px 48px;background:{bg};color:{text};border:2px solid {bg};border-radius:0;font-weight:800;cursor:pointer;font-family:'{body_font}',sans-serif;font-size:0.95rem;letter-spacing:0.18em;text-transform:uppercase;align-self:flex-start;">Send it</button>
  <div id="contact-status-{business_id}" style="font-size:0.95rem;min-height:1.25em;color:{on_accent};"></div>
</form>
<script>
(function() {{
  window.submitContact_{js_safe_id} = function(e) {{
    e.preventDefault();
    var form = e.target;
    var statusEl = document.getElementById('contact-status-{business_id}');
    statusEl.textContent = 'Sending...';
    var data = {{ name: form.name.value, email: form.email.value, message: form.message.value }};
    fetch('https://kmj-intake-server-production.up.railway.app/sites/{business_id}/contact-submit', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify(data)
    }})
      .then(function(r) {{ return r.json().catch(function() {{ return {{ ok: false, error: 'Server error' }}; }}); }})
      .then(function(d) {{
        if (d && d.ok) {{ statusEl.textContent = 'Message sent. We will be in touch.'; form.reset(); }}
        else {{ statusEl.textContent = (d && d.error) || 'Something went wrong. Please email directly.'; }}
      }})
      .catch(function() {{ statusEl.textContent = 'Network error. Please email directly.'; }});
    return false;
  }};
}})();
</script>
"""

    heading = safe_html(section_config.get("heading") or "Get in")
    subtext = safe_html(section_config.get("subtext") or "Be part of the work. Reach out.")
    info_inline_html = (
        f'<p style="margin:1.5rem 0 0;font-family:\'{body_font}\',sans-serif;font-size:1rem;color:{on_accent};">{info_html}</p>'
        if info_html else ''
    )
    return f"""
<section style="background:{accent};color:{on_accent};padding:120px 32px;">
  <div style="max-width:1100px;margin:0 auto;">
    <h2 style="font-family:'{display_font}',Georgia,serif;font-size:clamp(2.4rem,5vw,4rem);font-weight:800;margin:0 0 1rem;color:{on_accent};text-transform:uppercase;letter-spacing:-0.01em;">
      {heading}
    </h2>
    <p style="font-family:'{body_font}',sans-serif;font-size:1.2rem;color:{on_accent};opacity:0.9;margin:0;">{subtext}</p>
    {info_inline_html}
    {form_html}
  </div>
</section>
"""


def render(
    business_data: Dict[str, Any],
    design_system: DesignSystem,
    composite: CompositeDirection,
    sections_config: Dict[str, Any],
    bundle: Dict[str, Any],
    head_meta_extra: str = "",
    products: Optional[List[Dict[str, Any]]] = None,
    scheme: Optional[Dict[str, Any]] = None,
) -> str:
    products = products or []
    business_name = business_data.get("name") or "Welcome"
    archetype = business_data.get("type") or "custom"
    vocab_id = ((composite or {}).get("primary_vocabulary") or {}).get("id")
    section_break = render_decoration_for(vocab_id, design_system, "section_break")

    # Pass 3.7b — vocab-eyebrow text (letter-spacing: 0.3em)
    try:
        from studio_layouts.sections.typography import render_eyebrow
        eyebrow_html = render_eyebrow(safe_html(business_data.get("type", "")).replace("_", " ").upper() or "STUDIO", design_system, vocab_id)
    except Exception:
        eyebrow_html = ""

    bg = design_system["palette_bg"]
    accent = design_system["palette_accent"]
    text = design_system["palette_text"]
    on_accent = _pick_accent_contrast(accent)
    on_bg = _pick_contrast_text(bg, dark_color=text)
    display_font = design_system["font_display"]
    body_font = design_system["font_body"]

    layout_css = f"""
<style>
.mvm-hero {{
  background: {accent};
  color: {on_accent};
  padding: 96px 32px;
  text-align: center;
}}
.mvm-hero-inner {{ max-width: 920px; margin: 0 auto; }}
.mvm-statement {{
  font-family: '{display_font}', Georgia, serif;
  font-size: clamp(2.4rem, 7vw, 5rem);
  line-height: 1.05;
  font-weight: 800;
  margin: 0 0 1.5rem;
  text-transform: uppercase;
  letter-spacing: -0.01em;
}}
.mvm-tagline {{
  font-family: '{body_font}', sans-serif;
  font-size: 1.15rem;
  line-height: 1.5;
  margin: 0 0 2.5rem;
  opacity: 0.85;
}}
.mvm-cta {{
  display: inline-block;
  padding: 1.2rem 3rem;
  background: {bg};
  color: {on_bg};
  text-decoration: none;
  font-weight: 700;
  font-size: 0.95rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  border: 2px solid {bg};
  font-family: '{body_font}', sans-serif;
}}
.mvm-impact {{
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 24px;
  max-width: 1100px;
  margin: 0 auto;
  padding: 64px 32px;
}}
.mvm-stat {{
  text-align: center;
  font-family: '{body_font}', sans-serif;
}}
.mvm-stat .num {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 3rem;
  font-weight: 800;
  color: {accent};
  line-height: 1;
}}
.mvm-stat .label {{
  font-size: 0.85rem;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: color-mix(in srgb, {on_bg} 60%, transparent);
  margin-top: 0.6rem;
}}
.mvm-section {{ max-width: 960px; margin: 0 auto; padding: 80px 32px; }}
.mvm-section h2 {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 2.4rem;
  font-weight: 800;
  margin: 0 0 1.5rem;
  color: {on_bg};
  text-transform: uppercase;
}}
.mvm-section p {{
  font-family: '{body_font}', sans-serif;
  font-size: 1.1rem;
  line-height: 1.7;
  color: color-mix(in srgb, {on_bg} 80%, transparent);
}}
.mvm-services-list {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 24px;
  margin-top: 2rem;
}}
.mvm-service-card {{
  padding: 28px;
  border: 2px solid {on_bg};
  background: {bg};
}}
.mvm-service-card h3 {{
  font-family: '{display_font}', Georgia, serif;
  font-size: 1.3rem;
  margin: 0 0 0.6rem;
  color: {on_bg};
  text-transform: uppercase;
}}
.mvm-service-card p {{
  font-family: '{body_font}', sans-serif;
  font-size: 0.95rem;
  line-height: 1.6;
}}
@media (max-width: 768px) {{
  .mvm-hero {{ padding: 64px 24px; }}
  .mvm-impact {{ grid-template-columns: 1fr; padding: 48px 24px; }}
  .mvm-section {{ padding: 56px 24px; }}
}}
</style>
"""

    hero_config = sections_config.get("hero") or {}
    statement = safe_html(hero_config.get("headline")) or safe_html(business_data.get("tagline") or business_name)
    tagline = safe_html(hero_config.get("subheadline")) or ""
    cta_label = safe_html(hero_config.get("cta_label")) or "Join the movement"
    cta_link = safe_html(hero_config.get("cta_link")) or "#join"
    badge = render_in_the_clear_badge(bundle, design_system)

    badge_html = f'<div style="margin-bottom:1.5rem;">{badge}</div>' if badge else ""
    tagline_html = f'<p class="mvm-tagline">{tagline}</p>' if tagline else ""
    hero_html = f"""
<section class="mvm-hero reveal">
  <div class="mvm-hero-inner">
    {badge_html}
    <h1 class="mvm-statement">{statement}</h1>
    {tagline_html}
    <a href="{cta_link}" class="mvm-cta">{cta_label}</a>
  </div>
</section>
<section class="mvm-impact reveal">
  <div class="mvm-stat"><div class="num">10K+</div><div class="label">People reached</div></div>
  <div class="mvm-stat"><div class="num">50+</div><div class="label">Communities served</div></div>
  <div class="mvm-stat"><div class="num">100%</div><div class="label">Mission-driven</div></div>
</section>
"""

    before_about = render_archetype_touch(archetype, "before_about", design_system, bundle)

    about_html = ""
    about_config = sections_config.get("about") or {}
    if about_config.get("enabled", True):
        about_text = safe_html(about_config.get("text")) or safe_html(business_data.get("elevator_pitch") or "")
        if about_text:
            about_html = f"""
<section class="mvm-section reveal">
  <h2>Why we exist</h2>
  <p>{about_text}</p>
</section>
"""

    services_html = ""
    services_config = sections_config.get("services") or {}
    if services_config.get("enabled", True) and products:
        cards = []
        for p in products[:6]:
            name = safe_html(p.get("name", "Way to engage"))
            desc = safe_html(p.get("description") or "")
            desc_html = f"<p>{desc}</p>" if desc else ""
            cta_html = render_stripe_button(p, design_system)
            cards.append(f'<div class="mvm-service-card"><h3>{name}</h3>{desc_html}{cta_html}</div>')
        services_html = f"""
<section class="mvm-section reveal">
  <h2>How you can join</h2>
  <div class="mvm-services-list">{''.join(cards)}</div>
</section>
"""

    after_services = render_archetype_touch(archetype, "after_services", design_system, bundle)
    appendix_html = render_appendix_sections(
        design_system, business_data.get("id", "") or "", sections_config, bundle,
        bespoke_contact=_bespoke_contact,
    )
    footer_html = render_footer(business_data, bundle, design_system, sections_config.get("footer_extra_text"))
    head = render_head(business_name, design_system, head_meta_extra)
    return f"""<!DOCTYPE html>
<html lang="en">
{head}
{layout_css}
{render_decoration_head(design_system, scheme)}
<body style="background:{bg};color:{on_bg};margin:0;">
{render_scheme_after_hero(design_system, scheme)}
{hero_html}
<div style="max-width:1100px;margin:0 auto;padding:24px 24px 0;text-align:center;">{eyebrow_html}</div>
{before_about}
{about_html}
{services_html}
{section_break}
{after_services}
{appendix_html}
{footer_html}
{render_decoration_scripts(scheme)}
{render_motion_script()}
</body>
</html>"""
