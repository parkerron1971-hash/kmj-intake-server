"""Shared contact section renderer with info + optional form.

The contact form posts to /sites/{business_id}/contact-submit. The
inline JS function name uses business_id with hyphens replaced by
underscores so it's a valid JavaScript identifier.
"""
from __future__ import annotations

from typing import Any, Dict

from studio_design_system import DesignSystem, _pick_accent_contrast, _pick_contrast_text
from studio_layouts.shared import safe_html


_RAILWAY_BASE = "https://kmj-intake-server-production.up.railway.app"


def render(
    design_system: DesignSystem,
    business_id: str,
    section_config: Dict[str, Any],
    bundle: Dict[str, Any],
) -> str:
    """section_config: {enabled, email, phone, address, show_form, heading, subtext}."""
    if not section_config.get("enabled", False):
        return ""

    fallback_email = (bundle.get("footer") or {}).get("contact_email") or ""
    email = safe_html(section_config.get("email") or fallback_email)
    phone = safe_html(section_config.get("phone") or "")
    address = safe_html(section_config.get("address") or "")
    show_form = bool(section_config.get("show_form", True))

    text = design_system["palette_text"]
    accent = design_system["palette_accent"]
    on_accent = _pick_accent_contrast(accent)
    surface = design_system["palette_surface"]
    surface_text = _pick_contrast_text(surface, dark_color=text)
    display_font = design_system["font_display"]

    info_blocks = []
    if email:
        info_blocks.append(
            f'<div style="margin-bottom:1.5rem;">'
            f'<div style="font-size:0.75rem;text-transform:uppercase;letter-spacing:0.15em;color:color-mix(in srgb,{surface_text} 60%,transparent);margin-bottom:0.25rem;">Email</div>'
            f'<a href="mailto:{email}" style="color:{accent};text-decoration:none;font-size:1.1rem;">{email}</a></div>'
        )
    if phone:
        info_blocks.append(
            f'<div style="margin-bottom:1.5rem;">'
            f'<div style="font-size:0.75rem;text-transform:uppercase;letter-spacing:0.15em;color:color-mix(in srgb,{surface_text} 60%,transparent);margin-bottom:0.25rem;">Phone</div>'
            f'<a href="tel:{phone}" style="color:{accent};text-decoration:none;font-size:1.1rem;">{phone}</a></div>'
        )
    if address:
        info_blocks.append(
            f'<div style="margin-bottom:1.5rem;">'
            f'<div style="font-size:0.75rem;text-transform:uppercase;letter-spacing:0.15em;color:color-mix(in srgb,{surface_text} 60%,transparent);margin-bottom:0.25rem;">Address</div>'
            f'<div style="color:{surface_text};font-size:1rem;line-height:1.5;">{address}</div></div>'
        )

    info_html = "".join(info_blocks) if info_blocks else (
        f'<div style="color:color-mix(in srgb,{surface_text} 70%,transparent);">'
        f'Reach out using the form.</div>' if show_form else ''
    )

    # Inline form + submit JS. business_id contains hyphens which are
    # invalid in JS identifiers — replace with underscores for the
    # function name.
    form_html = ""
    if show_form:
        js_safe_id = business_id.replace("-", "_")
        form_html = f"""
<form id="contact-form-{business_id}" onsubmit="return submitContact_{js_safe_id}(event)" style="display:flex;flex-direction:column;gap:1rem;">
  <div>
    <label style="display:block;font-size:0.85rem;color:color-mix(in srgb,{surface_text} 70%,transparent);margin-bottom:0.25rem;">Your name</label>
    <input type="text" name="name" required maxlength="200" style="width:100%;padding:12px;border:1px solid color-mix(in srgb,{surface_text} 20%,transparent);border-radius:4px;background:transparent;color:{surface_text};font-family:inherit;font-size:1rem;">
  </div>
  <div>
    <label style="display:block;font-size:0.85rem;color:color-mix(in srgb,{surface_text} 70%,transparent);margin-bottom:0.25rem;">Your email</label>
    <input type="email" name="email" required maxlength="200" style="width:100%;padding:12px;border:1px solid color-mix(in srgb,{surface_text} 20%,transparent);border-radius:4px;background:transparent;color:{surface_text};font-family:inherit;font-size:1rem;">
  </div>
  <div>
    <label style="display:block;font-size:0.85rem;color:color-mix(in srgb,{surface_text} 70%,transparent);margin-bottom:0.25rem;">Message</label>
    <textarea name="message" required rows="5" maxlength="5000" style="width:100%;padding:12px;border:1px solid color-mix(in srgb,{surface_text} 20%,transparent);border-radius:4px;background:transparent;color:{surface_text};font-family:inherit;resize:vertical;font-size:1rem;"></textarea>
  </div>
  <button type="submit" style="padding:14px 32px;background:{accent};color:{on_accent};border:none;border-radius:4px;font-weight:600;cursor:pointer;font-family:inherit;font-size:1rem;">Send Message</button>
  <div id="contact-status-{business_id}" style="font-size:0.9rem;min-height:1.25em;"></div>
</form>
<script>
(function() {{
  window.submitContact_{js_safe_id} = function(e) {{
    e.preventDefault();
    var form = e.target;
    var statusEl = document.getElementById('contact-status-{business_id}');
    statusEl.textContent = 'Sending...';
    statusEl.style.color = 'color-mix(in srgb, {surface_text} 60%, transparent)';
    var data = {{
      name: form.name.value,
      email: form.email.value,
      message: form.message.value
    }};
    fetch('{_RAILWAY_BASE}/sites/{business_id}/contact-submit', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify(data)
    }})
      .then(function(r) {{ return r.json().catch(function() {{ return {{ ok: false, error: 'Server error' }}; }}); }})
      .then(function(d) {{
        if (d && d.ok) {{
          statusEl.textContent = 'Message sent successfully.';
          statusEl.style.color = '{accent}';
          form.reset();
        }} else {{
          statusEl.textContent = (d && d.error) || 'Something went wrong. Please email directly.';
          statusEl.style.color = '#c0392b';
        }}
      }})
      .catch(function() {{
        statusEl.textContent = 'Network error. Please email directly.';
        statusEl.style.color = '#c0392b';
      }});
    return false;
  }};
}})();
</script>
"""

    heading = safe_html(section_config.get("heading") or "Get in touch")
    subtext = safe_html(section_config.get("subtext") or "")
    subtext_html = (
        f'<p style="font-size:1.1rem;color:color-mix(in srgb,{surface_text} 80%,transparent);margin:0 0 3rem;max-width:600px;">{subtext}</p>'
        if subtext else ''
    )

    grid_template = "1fr 1.5fr" if (info_html and form_html) else "1fr"
    return f"""
<section style="background:{surface};color:{surface_text};padding:96px 48px;">
  <div style="max-width:1100px;margin:0 auto;">
    <h2 style="font-family:'{display_font}',Georgia,serif;font-size:2rem;margin:0 0 1rem;color:{surface_text};">
      {heading}
    </h2>
    {subtext_html}
    <div style="display:grid;grid-template-columns:{grid_template};gap:64px;align-items:start;">
      {f'<div>{info_html}</div>' if info_html else ''}
      {f'<div>{form_html}</div>' if form_html else ''}
    </div>
  </div>
</section>
"""
