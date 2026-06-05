"""
booking_page_renderer.py — Phase D.2.1 backend.

Server-side HTML rendering for the hosted booking page at
<slug>.mysolutionist.app/book. Builds a complete HTML document with:
  - <head>: title, meta description, OG tags, canonical URL, favicon
  - <body>: brand-applied header (logo + name + tagline), the booking
    widget mounted via embed.js, "Powered by Solutionist" footer

Brand kit applied as CSS variables on the document root so the
embedded widget (which uses var(--accent), var(--surface), etc.)
inherits the practitioner's colors automatically.

Per D.2 audit:
  E4 — practitioner brand + small Solutionist attribution footer
  E5 — logo + business name + tagline + widget + footer
  E7 — title + OG title + OG description + canonical
"""
from __future__ import annotations

import html
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("booking_page_renderer")


# Where the bundled embed script lives — same URL the practitioner
# would copy from the Embed tab (PR 2).
EMBED_SCRIPT_PATH = "/static/embed.js"


def _esc(s: Optional[str]) -> str:
    """HTML-escape a string for safe inclusion in attribute / body."""
    return html.escape(s or "", quote=True)


def _brand_kit(business: Dict[str, Any]) -> Dict[str, Any]:
    """Pull brand_kit out of business settings; tolerate missing."""
    settings = business.get("settings") or {}
    return settings.get("brand_kit") or {}


def _booking_page_settings(business: Dict[str, Any]) -> Dict[str, Any]:
    """Read settings.booking_page (the published flag + tagline + footer)."""
    settings = business.get("settings") or {}
    return settings.get("booking_page") or {}


def _css_vars(brand: Dict[str, Any]) -> str:
    """Translate brand_kit into a :root CSS-variable block. Fallback to
    neutral defaults when brand_kit fields are missing so the page
    always renders something credible."""
    return (
        ":root{"
        f"--accent: {_esc(brand.get('accent') or '#a78bfa')};"
        f"--accent-hover: {_esc(brand.get('accent_hover') or '#818cf8')};"
        f"--surface: {_esc(brand.get('surface') or '#ffffff')};"
        f"--text-primary: {_esc(brand.get('text_primary') or '#0f172a')};"
        f"--text-secondary: {_esc(brand.get('text_secondary') or '#475569')};"
        f"--text-muted: {_esc(brand.get('text_muted') or '#64748b')};"
        f"--border: {_esc(brand.get('border') or 'rgba(15,23,42,0.12)')};"
        f"--font-heading: {_esc(brand.get('font_heading') or 'system-ui, sans-serif')};"
        f"--font-body: {_esc(brand.get('font_body') or 'system-ui, sans-serif')};"
        "}"
    )


def render_booking_page(
    business: Dict[str, Any],
    canonical_url: str,
    *,
    embed_origin: str,
) -> str:
    """Return the complete HTML document for a hosted booking page.

    Args:
      business — the business row (must include id, name, settings).
      canonical_url — the full https://<slug>.mysolutionist.app/book
                      URL for the canonical + og:url tags.
      embed_origin — origin where embed.js is served (e.g.
                     "https://kmj-intake-server-production.up.railway.app"
                     for production, or whatever the request host
                     resolves to). The script src is built as
                     {embed_origin}{EMBED_SCRIPT_PATH}.

    Per D.2 audit E5/β: header (logo + name + tagline) + widget +
    Powered-by footer.
    """
    biz_id = business.get("id") or ""
    name = (business.get("name") or "").strip() or "Booking"
    brand = _brand_kit(business)
    page = _booking_page_settings(business)
    tagline = (page.get("tagline") or "").strip()
    footer_text = (page.get("footer_text") or "").strip()
    logo_url = (brand.get("logo_url") or brand.get("logo") or "").strip()

    title = f"Book with {name}"
    description = tagline or f"Book an appointment with {name}."
    css_vars = _css_vars(brand)

    embed_src = f"{embed_origin.rstrip('/')}{EMBED_SCRIPT_PATH}"

    parts: list = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="en">')
    parts.append("<head>")
    parts.append('<meta charset="UTF-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    parts.append(f"<title>{_esc(title)}</title>")
    parts.append(f'<meta name="description" content="{_esc(description)}">')
    # Canonical + Open Graph (E7-α light: title + description + canonical)
    parts.append(f'<link rel="canonical" href="{_esc(canonical_url)}">')
    parts.append(f'<meta property="og:title" content="{_esc(title)}">')
    parts.append(f'<meta property="og:description" content="{_esc(description)}">')
    parts.append(f'<meta property="og:url" content="{_esc(canonical_url)}">')
    parts.append('<meta property="og:type" content="website">')
    if logo_url:
        parts.append(f'<meta property="og:image" content="{_esc(logo_url)}">')
        parts.append(f'<link rel="icon" href="{_esc(logo_url)}">')
    # Brand kit → CSS variables. Shadow-DOM widget reads these via
    # theme_tokens but inheriting on the document root means the
    # surrounding page also matches the practitioner's brand.
    parts.append(f"<style>{css_vars}</style>")
    parts.append(
        "<style>"
        "html,body{margin:0;padding:0;font-family:var(--font-body);"
        "color:var(--text-primary);background:var(--surface);"
        "min-height:100vh;}"
        ".bk-shell{max-width:560px;margin:0 auto;padding:24px 16px 48px;}"
        ".bk-header{text-align:center;margin-bottom:24px;}"
        ".bk-logo{max-width:96px;max-height:96px;display:block;margin:0 auto 12px;}"
        ".bk-name{font-family:var(--font-heading);font-size:24px;font-weight:700;"
        "color:var(--text-primary);margin:0;}"
        ".bk-tagline{font-size:14px;color:var(--text-secondary);margin:6px 0 0;"
        "line-height:1.5;}"
        ".bk-widget{margin-top:16px;}"
        ".bk-footer{text-align:center;font-size:11px;color:var(--text-muted);"
        "margin-top:32px;padding-top:16px;"
        "border-top:1px solid var(--border);}"
        ".bk-footer a{color:var(--text-muted);text-decoration:none;}"
        ".bk-footer a:hover{color:var(--accent);}"
        "</style>"
    )
    parts.append("</head>")
    parts.append("<body>")
    parts.append('<main class="bk-shell">')
    parts.append('<header class="bk-header">')
    if logo_url:
        parts.append(f'<img class="bk-logo" src="{_esc(logo_url)}" alt="{_esc(name)} logo">')
    parts.append(f'<h1 class="bk-name">{_esc(name)}</h1>')
    if tagline:
        parts.append(f'<p class="bk-tagline">{_esc(tagline)}</p>')
    parts.append("</header>")
    # Embed mount point + script. The embed widget reads
    # data-business / data-archetype and renders the BookingForm in a
    # shadow DOM inside its own container.
    parts.append('<section class="bk-widget">')
    parts.append(
        f'<script src="{_esc(embed_src)}" '
        f'data-business="{_esc(biz_id)}" '
        f'data-archetype="booking_form"></script>'
    )
    parts.append("</section>")
    # Footer — practitioner override text if set, else default attribution.
    parts.append('<footer class="bk-footer">')
    if footer_text:
        parts.append(_esc(footer_text))
    else:
        parts.append(
            f'Powered by <a href="https://{_esc("mysolutionist.app")}/" '
            f'target="_blank" rel="noopener">Solutionist</a>'
        )
    parts.append("</footer>")
    parts.append("</main>")
    parts.append("</body>")
    parts.append("</html>")
    return "\n".join(parts)


def render_not_published_page(
    business: Dict[str, Any],
    canonical_url: str,
) -> str:
    """Render a "this booking page isn't published yet" page when a
    business has a slug but settings.booking_page.published is false.
    Brand still applies; no widget script."""
    name = (business.get("name") or "").strip() or "Booking"
    brand = _brand_kit(business)
    css_vars = _css_vars(brand)
    return "\n".join([
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        f"<title>{_esc(name)}</title>",
        '<meta name="robots" content="noindex,nofollow">',
        f'<link rel="canonical" href="{_esc(canonical_url)}">',
        f"<style>{css_vars}</style>",
        "<style>html,body{margin:0;padding:0;font-family:var(--font-body);"
        "color:var(--text-primary);background:var(--surface);min-height:100vh;}"
        ".bk-shell{max-width:480px;margin:96px auto 0;padding:24px 16px;"
        "text-align:center;}"
        ".bk-name{font-family:var(--font-heading);font-size:22px;font-weight:700;}"
        ".bk-msg{margin-top:16px;color:var(--text-secondary);line-height:1.5;}"
        "</style>",
        "</head>",
        "<body>",
        '<main class="bk-shell">',
        f'<h1 class="bk-name">{_esc(name)}</h1>',
        '<p class="bk-msg">This booking page isn\'t published yet.</p>',
        "</main>",
        "</body>",
        "</html>",
    ])
