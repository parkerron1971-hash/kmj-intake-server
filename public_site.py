"""
public_site.py — Solutionist System public site data + widget endpoints

Unauthenticated read-only endpoints that serve practitioner site data
and embeddable widget HTML. Only exposes modules with
public_display.enabled = true and only the fields listed in visible_fields.

═══════════════════════════════════════════════════════════════════════
DEPLOYMENT
═══════════════════════════════════════════════════════════════════════

1. Drop into Railway alongside the other agent files.
2. In main.py:
       from public_site import router as public_site_router
       app.include_router(public_site_router)
3. No env vars beyond the existing SUPABASE_URL + SUPABASE_ANON.

Brand Engine v1 helpers (_brand_footer_html, _in_the_clear_badge_html)
are available for any renderer to call. The brand-engine-migration.sql
also promotes nested keys into the legacy flat keys this file reads
at lines 741, 870, 1700 — so existing color reads now resolve to the
real practitioner brand color instead of defaults. Smart Sites (Pass 3)
will wire the helpers into every page footer.
"""

import asyncio
import html as _html
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


def _brand_footer_html(business_id: str) -> str:
    """Return a small footer block (copyright + legal disclaimers) sourced
    from the Brand Engine bundle. Returns "" if the bundle can't compose,
    so callers can safely append unconditionally."""
    if not business_id:
        return ""
    try:
        from brand_engine import get_bundle as _be_get_bundle
        bundle = _be_get_bundle(business_id) or {}
    except Exception:
        return ""
    footer = bundle.get("footer") or {}
    cr = footer.get("copyright_line") or ""
    legal = footer.get("legal_footer") or ""
    if not cr and not legal:
        return ""
    parts: List[str] = []
    if cr:
        parts.append(f'<div class="brand-copyright">{_html.escape(cr)}</div>')
    if legal:
        parts.append(f'<div class="brand-legal-footer">{_html.escape(legal)}</div>')
    return (
        '<footer class="brand-footer" style="margin-top:2rem;padding:1rem;'
        'font-size:.8rem;color:#666;text-align:center;line-height:1.6;">'
        + "".join(parts)
        + "</footer>"
    )


def _in_the_clear_badge_html(business_id: str) -> str:
    """Inline badge marking the business as foundation-complete. Smart
    Sites in Pass 3 will style this properly via the
    `.in-the-clear-badge` class. v1 ships unstyled markup."""
    if not business_id:
        return ""
    try:
        from brand_engine import get_bundle as _be_get_bundle
        bundle = _be_get_bundle(business_id) or {}
    except Exception:
        return ""
    if not (bundle.get("legal") or {}).get("in_the_clear"):
        return ""
    return (
        '<span class="in-the-clear-badge" '
        'title="Foundation Track complete">'
        '✓ Business In The Clear</span>'
    )


def _brand_head_meta_tags(business_id: str) -> str:
    """Return favicon link + Open Graph + Twitter Card meta tags sourced
    from the Brand Engine bundle's assets section. Inject before
    </head> in any rendered public page. Returns "" when no relevant
    assets are configured, so callers can append unconditionally."""
    if not business_id:
        return ""
    try:
        from brand_engine import get_bundle as _be_get_bundle
        bundle = _be_get_bundle(business_id) or {}
    except Exception:
        return ""
    assets = bundle.get("assets") or {}
    favicon = assets.get("favicon")
    social_card = assets.get("social_card")
    business = bundle.get("business") or {}
    biz_name = (business.get("name") or "").replace('"', '&quot;')
    tagline = (business.get("tagline") or "").replace('"', '&quot;')

    parts: List[str] = []
    if favicon:
        parts.append(f'<link rel="icon" type="image/png" href="{favicon}">')
        parts.append(f'<link rel="shortcut icon" href="{favicon}">')
        parts.append(f'<link rel="apple-touch-icon" href="{favicon}">')
    if social_card:
        parts.append(f'<meta property="og:image" content="{social_card}">')
        if biz_name:
            parts.append(f'<meta property="og:title" content="{biz_name}">')
        if tagline:
            parts.append(f'<meta property="og:description" content="{tagline}">')
        parts.append('<meta property="og:type" content="website">')
        parts.append('<meta name="twitter:card" content="summary_large_image">')
        parts.append(f'<meta name="twitter:image" content="{social_card}">')
        if biz_name:
            parts.append(f'<meta name="twitter:title" content="{biz_name}">')
        if tagline:
            parts.append(f'<meta name="twitter:description" content="{tagline}">')
    return "\n    ".join(parts)

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# ═══════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════

HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
RATE_LIMIT_PER_MIN = 100
RATE_WINDOW_SEC = 60

# Business-type → color palette for widgets
TYPE_PALETTES: Dict[str, Dict[str, str]] = {
    "church":     {"bg": "#faf7f2", "card": "#fff", "accent": "#8B6914", "text": "#2d2417", "muted": "#7a6e5e", "border": "#e8dfd2"},
    "coaching":   {"bg": "#f0f4f8", "card": "#fff", "accent": "#1a6b8a", "text": "#1a2a3a", "muted": "#5a6a7a", "border": "#dce4ec"},
    "consulting": {"bg": "#f3f4f6", "card": "#fff", "accent": "#3730a3", "text": "#111827", "muted": "#6b7280", "border": "#e5e7eb"},
    "nonprofit":  {"bg": "#f0fdf4", "card": "#fff", "accent": "#166534", "text": "#14532d", "muted": "#4d7c5e", "border": "#d1e7d8"},
    "freelance":  {"bg": "#fdf4ff", "card": "#fff", "accent": "#7c3aed", "text": "#1e1033", "muted": "#6b5b7b", "border": "#e8d5f5"},
}
DEFAULT_PALETTE = TYPE_PALETTES["consulting"]

# ═══════════════════════════════════════════════════════════════════════
# SUBDOMAIN DETECTION
# ═══════════════════════════════════════════════════════════════════════

BASE_DOMAINS = ["mysolutionist.app", "solutionistsystem.com", "getsolutionist.com", "mysolutionist.com"]

# Hosts where the Railway API is served directly. When the incoming
# Host matches one of these, the root + catch-all handlers MUST 404 so
# requests fall through to the real API routers (chief, email, etc.)
# without being intercepted by the subdomain site-server.
API_HOSTS = (
    "kmj-intake-server-production.up.railway.app",
    ".railway.app",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
)


def _is_api_host(host: str) -> bool:
    """True when the request arrived on the Railway API domain (or local dev)."""
    h = (host or "").split(":")[0].lower().strip()
    if not h:
        return True  # no host header → treat as API to be safe
    for needle in API_HOSTS:
        if needle.startswith("."):
            if h.endswith(needle):
                return True
        elif h == needle:
            return True
    return False


def extract_slug_from_host(request: Request) -> Optional[str]:
    """Extract the business slug from subdomain.
    embrace-the-shift.mysolutionist.app → 'embrace-the-shift'
    www.mysolutionist.app → None (root)
    mysolutionist.app → None (root)
    kmj-intake-server-production.up.railway.app → None (API domain)
    """
    host = (request.headers.get("host") or "").split(":")[0].lower().strip()
    if not host:
        return None

    for base in BASE_DOMAINS:
        if host == base or host == f"www.{base}":
            return None
        if host.endswith(f".{base}"):
            slug = host.replace(f".{base}", "")
            if slug and slug != "www":
                return slug

    return None


def _inject_canonical(html: str, slug: str) -> str:
    """Inject canonical URL + OG tags into the HTML head section."""
    canonical = f"https://{slug}.mysolutionist.app"
    tags = (
        f'\n<link rel="canonical" href="{canonical}" />'
        f'\n<meta property="og:url" content="{canonical}" />'
    )
    if "</head>" in html:
        return html.replace("</head>", tags + "\n</head>", 1)
    if "</HEAD>" in html:
        return html.replace("</HEAD>", tags + "\n</HEAD>", 1)
    return html


def _inject_brand_meta(html: str, business_id: Optional[str]) -> str:
    """Pass 3: wire `_brand_head_meta_tags` into legacy HTML before </head>.
    Activates the dormant Pass 2.5a helper for users who haven't opted into
    Smart Sites yet — favicons + OG tags + Twitter Cards finally render.
    Defensive: any failure returns the original HTML unchanged."""
    if not business_id:
        return html
    try:
        tags = _brand_head_meta_tags(business_id)
    except Exception:
        return html
    if not tags:
        return html
    if "</head>" in html:
        return html.replace("</head>", tags + "\n</head>", 1)
    if "</HEAD>" in html:
        return html.replace("</HEAD>", tags + "\n</HEAD>", 1)
    return html


def _use_smart_sites(site_row: Dict[str, Any]) -> bool:
    """Pass 3: check if this business has opted into Smart Sites rendering."""
    cfg = (site_row or {}).get("site_config") or {}
    return bool(cfg.get("use_smart_sites"))


def _esc(text: Any) -> str:
    """Cheap HTML escape."""
    if text is None:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _format_price_label(price: float, pricing_type: str, currency: str) -> str:
    """Produce a display-friendly price tag. Honors pricing_type semantics
    so 'free' / 'custom' / 'starting_at' render correctly on the site."""
    sym = "$" if (currency or "USD").upper() == "USD" else ""
    pt = (pricing_type or "fixed").lower()
    if pt == "free":
        return "Free"
    if pt == "custom" or price <= 0:
        return "Contact for pricing"
    base = f"{sym}{price:,.2f}".rstrip("0").rstrip(".") if price % 1 else f"{sym}{price:,.0f}"
    if pt == "hourly" or pt == "per_hour":
        return f"{base}/hr"
    if pt == "per_session":
        return f"{base}/session"
    if pt == "subscription" or pt == "monthly":
        return f"{base}/mo"
    if pt == "starting_at":
        return f"Starting at {base}"
    return base


def _get_product_cta(
    product: Dict[str, Any],
    slug: str,
    brand_color: str,
    settings: Dict[str, Any],
    price_label: str,
) -> str:
    """Return the CTA HTML for a single product card.

    Priority order for buy buttons:
      1. Shopify Buy Button embed (rendered as-is when from cdn.shopify.com)
      2. Stripe payment link (auto-generated for the platform owner; can
         be set manually for other practitioners)
      3. Shopify URL (cart link, paste-in)
      4. Square checkout URL
      5. PayPal URL
      6. External / catch-all URL
      7. Fallbacks: 'Contact for pricing' -> #contact, 'Free' -> #contact

    Services route to /{slug}/book even when a payment link exists, so
    the practitioner can collect time + intake before charging.
    """
    ptype = (product.get("type") or "service").lower()
    metadata = product.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    stripe_url = (product.get("stripe_payment_url") or "").strip()
    shopify_url = (metadata.get("shopify_buy_url") or "").strip()
    square_url = (metadata.get("square_buy_url") or "").strip()
    paypal_url = (metadata.get("paypal_buy_url") or "").strip()
    external_url = (metadata.get("external_buy_url") or "").strip()
    shopify_embed = (metadata.get("shopify_embed") or "").strip()

    btn_style = (
        f"display:inline-block;margin-top:10px;padding:10px 18px;"
        f"background:{brand_color};color:#fff;text-decoration:none;"
        f"border-radius:6px;font-weight:600;text-align:center;"
    )
    secondary_btn_style = (
        f"display:inline-block;margin-top:6px;padding:8px 14px;"
        f"background:transparent;color:{brand_color};border:1px solid {brand_color};"
        f"text-decoration:none;border-radius:6px;font-weight:500;font-size:13px;"
        f"text-align:center;"
    )

    # 1. Shopify Buy Button embed wins — sanitize: only allow embeds that
    # reference cdn.shopify.com so the renderer can't be tricked into
    # injecting arbitrary scripts.
    if shopify_embed and "cdn.shopify.com" in shopify_embed:
        return f'<div class="shopify-embed" style="margin-top:10px;">{shopify_embed}</div>'

    # 2. Services always use /book — booking captures slot + contact info
    # AND can collect payment via Stripe afterwards if the practitioner
    # wires it up. Override only if a specific service has a stripe_url
    # set on the product (rare).
    if ptype == "service":
        booking_slug = slug
        return (
            f'<a href="/{_esc(booking_slug)}/book" style="{btn_style}">'
            f'Book Now &mdash; {price_label}</a>'
        )

    # 3. Provider priority for non-services. Stripe first because it's
    # the only one we can auto-generate.
    primary = ""
    label_suffix = f" &mdash; {price_label}" if price_label and price_label != "Contact for pricing" else ""
    if stripe_url:
        primary = f'<a href="{_esc(stripe_url)}" target="_blank" rel="noopener" style="{btn_style}">Buy Now{label_suffix}</a>'
    elif shopify_url:
        primary = f'<a href="{_esc(shopify_url)}" target="_blank" rel="noopener" style="{btn_style}">Buy on Shopify{label_suffix}</a>'
    elif square_url:
        primary = f'<a href="{_esc(square_url)}" target="_blank" rel="noopener" style="{btn_style}">Buy Now{label_suffix}</a>'
    elif paypal_url:
        primary = f'<a href="{_esc(paypal_url)}" target="_blank" rel="noopener" style="{btn_style}">Buy with PayPal{label_suffix}</a>'
    elif external_url:
        primary = f'<a href="{_esc(external_url)}" target="_blank" rel="noopener" style="{btn_style}">Buy Now{label_suffix}</a>'
    else:
        # No payment link at all -> contact CTA
        pricing_type = (product.get("pricing_type") or "fixed").lower()
        if pricing_type == "custom":
            return f'<a href="#contact" style="{btn_style}">Get a Quote</a>'
        if pricing_type == "free":
            return f'<a href="#contact" style="{btn_style}">Get It Free</a>'
        return f'<div style="margin-top:10px;font-weight:700;color:#222;">{price_label}</div>'

    # 4. Alternate-provider buttons under the primary, if multiple exist.
    alts: List[str] = []
    if stripe_url and shopify_url:
        alts.append(f'<a href="{_esc(shopify_url)}" target="_blank" rel="noopener" style="{secondary_btn_style}">Also on Shopify</a>')
    if stripe_url and paypal_url:
        alts.append(f'<a href="{_esc(paypal_url)}" target="_blank" rel="noopener" style="{secondary_btn_style}">Pay with PayPal</a>')
    return primary + "".join(alts)


def _render_products_section(
    products: List[Dict[str, Any]],
    slug: str,
    brand_color: str = "#D4AF37",
    settings: Optional[Dict[str, Any]] = None,
) -> str:
    """Render a Products & Services section. Returns '' when nothing to show.

    `brand_color` flows in from settings.brand_kit.primary_color so the
    CTA buttons match the practitioner's brand instead of always gold.
    `settings` carries the rest of the business settings (subdomain,
    payment_providers, etc.) for CTA routing decisions.
    """
    settings = settings or {}
    visible = [
        p for p in (products or [])
        if (p.get("status") or "active") == "active"
        and p.get("display_on_website", True)
    ]
    if not visible:
        return ""

    visible.sort(key=lambda p: (
        0 if p.get("featured") else 1,
        p.get("sort_order") or 0,
        p.get("name") or "",
    ))

    cards: List[str] = []
    for p in visible:
        name = _esc(p.get("name") or "")
        desc = _esc((p.get("description") or "")[:240])
        ptype = (p.get("type") or "service").lower()
        try:
            price = float(p.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        currency = (p.get("currency") or "USD").upper()
        pricing_type = (p.get("pricing_type") or "fixed").lower()
        price_label = _format_price_label(price, pricing_type, currency)

        image_url = p.get("image_url")
        image_html = (
            f'<div style="width:100%;aspect-ratio:4/3;overflow:hidden;background:#f5f5f5;">'
            f'<img src="{_esc(image_url)}" alt="{name}" style="width:100%;height:100%;object-fit:cover;display:block;" loading="lazy" />'
            f'</div>'
        ) if image_url else ""

        # Featured badge
        featured_badge = ""
        if p.get("featured"):
            featured_badge = (
                f'<span style="display:inline-block;padding:2px 8px;border-radius:99px;'
                f'background:{brand_color};color:#fff;font-size:10px;font-weight:700;'
                f'text-transform:uppercase;letter-spacing:0.06em;margin-left:6px;">'
                f'Popular</span>'
            )

        # Duration badge for services
        duration_badge = ""
        duration = p.get("duration_minutes")
        if duration and ptype == "service":
            duration_badge = (
                f'<span style="display:inline-block;padding:2px 8px;border-radius:99px;'
                f'background:rgba(0,0,0,0.06);color:#666;font-size:11px;margin-left:6px;">'
                f'{int(duration)} min</span>'
            )

        cta = _get_product_cta(p, slug, brand_color, settings, price_label)

        includes = p.get("includes") or []
        includes_html = ""
        if ptype == "package" and isinstance(includes, list) and includes:
            items = "".join(
                f'<li style="font-size:13px;color:#555;padding:3px 0;">&#10003; {_esc((i.get("item") if isinstance(i, dict) else i) or "")}</li>'
                for i in includes[:6]
            )
            includes_html = f'<ul style="list-style:none;margin:8px 0 4px;padding-left:0;">{items}</ul>'

        # Featured card gets a tinted background + accent border
        card_style = (
            "background:#fff;border:1px solid rgba(0,0,0,0.08);border-radius:12px;"
            "overflow:hidden;display:flex;flex-direction:column;"
        )
        if p.get("featured"):
            card_style = (
                f"background:#fff;border:2px solid {brand_color};border-radius:12px;"
                f"overflow:hidden;display:flex;flex-direction:column;"
                f"box-shadow:0 4px 24px rgba(0,0,0,0.06);"
            )

        price_color = brand_color
        cards.append(
            f'<div style="{card_style}">'
            f'{image_html}'
            f'<div style="padding:16px;display:flex;flex-direction:column;gap:6px;flex:1;">'
            f'<h3 style="margin:0;font-size:18px;color:#222;">{name}{duration_badge}{featured_badge}</h3>'
            f'<div style="font-size:22px;font-weight:700;color:{price_color};margin:4px 0;">{price_label}</div>'
            + (f'<p style="margin:0;font-size:14px;color:#555;line-height:1.5;">{desc}</p>' if desc else '')
            + f'{includes_html}'
            f'{cta}'
            f'</div></div>'
        )

    return (
        '<section id="services" style="padding:60px 24px;background:#fafafa;">'
        '<div style="max-width:1100px;margin:0 auto;">'
        '<h2 style="text-align:center;font-size:32px;margin:0 0 32px;color:#222;">Services &amp; Products</h2>'
        '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:20px;">'
        + "".join(cards) +
        '</div></div></section>'
    )


def _render_gallery_section(gallery: List[Dict[str, Any]]) -> str:
    """Render the Gallery section from settings.media_library.gallery.
    Returns '' if nothing public to show."""
    visible = [
        g for g in (gallery or [])
        if g.get("show_on_website", True) and g.get("url")
    ]
    if not visible:
        return ""
    visible.sort(key=lambda g: g.get("sort_order") or 0)

    tiles = []
    for g in visible:
        url = _esc(g.get("url"))
        alt = _esc(g.get("alt") or "")
        caption = _esc(g.get("caption") or "")
        cap_html = (
            f'<p style="margin:6px 0 0;font-size:12px;color:#666;text-align:center;">{caption}</p>'
            if caption else ""
        )
        tiles.append(
            f'<div class="gallery-item" style="display:flex;flex-direction:column;">'
            f'<div style="aspect-ratio:1/1;overflow:hidden;border-radius:8px;background:#f5f5f5;">'
            f'<img src="{url}" alt="{alt}" loading="lazy" style="width:100%;height:100%;object-fit:cover;display:block;" />'
            f'</div>{cap_html}</div>'
        )

    return (
        '<section id="gallery" style="padding:60px 24px;background:#fff;">'
        '<div style="max-width:1100px;margin:0 auto;">'
        '<h2 style="text-align:center;font-size:32px;margin:0 0 32px;color:#222;">Gallery</h2>'
        '<div class="gallery-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px;">'
        + "".join(tiles) +
        '</div></div></section>'
    )


def _render_testimonials_section(testimonials: List[Dict[str, Any]]) -> str:
    """Render the Testimonials section from settings.website_content.testimonials.
    ONLY renders when there are real, opt-in testimonials — never produces a
    placeholder. Quotes are HTML-escaped but otherwise rendered verbatim;
    we never modify the practitioner's words."""
    visible = [
        t for t in (testimonials or [])
        if t.get("show_on_website", True) and (t.get("quote") or "").strip()
    ]
    if not visible:
        return ""

    cards: List[str] = []
    for t in visible:
        quote = _esc(t.get("quote") or "")
        name = _esc(t.get("name") or "")
        role = _esc(t.get("role") or "")
        role_html = (
            f'<div style="font-size:12px;color:#777;margin-top:2px;">{role}</div>'
            if role else ""
        )
        cards.append(
            '<figure style="margin:0;padding:24px;background:#fff;border:1px solid #ececec;'
            'border-radius:12px;display:flex;flex-direction:column;gap:14px;">'
            f'<blockquote style="margin:0;font-size:16px;line-height:1.6;color:#222;">'
            f'&ldquo;{quote}&rdquo;</blockquote>'
            '<figcaption style="display:flex;align-items:flex-start;justify-content:space-between;">'
            f'<div><div style="font-weight:600;color:#222;">— {name}</div>{role_html}</div>'
            '</figcaption></figure>'
        )

    return (
        '<section id="testimonials" style="padding:60px 24px;background:#fafafa;">'
        '<div style="max-width:1100px;margin:0 auto;">'
        '<h2 style="text-align:center;font-size:32px;margin:0 0 32px;color:#222;">What people are saying</h2>'
        '<div class="testimonial-grid" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px;">'
        + "".join(cards) +
        '</div></div></section>'
    )


def _inject_dynamic_sections(
    html: str,
    products_html: str,
    gallery_html: str,
    testimonials_html: str = "",
) -> str:
    """Inject the products + gallery + testimonials sections into the
    served HTML.

    Placeholder-aware: if the template contains `{{PRODUCTS_SECTION}}`,
    `{{GALLERY_SECTION}}`, or `{{TESTIMONIALS_SECTION}}`, those tokens
    are replaced in place. This lets generated templates control where
    each section lives. Otherwise the sections fall back to being
    appended right before </body> (legacy templates).

    The site itself is regenerated rarely; this gives practitioners
    live updates without a regen cycle.
    """
    products_html = products_html or ""
    gallery_html = gallery_html or ""
    testimonials_html = testimonials_html or ""

    placeholder_replaced = False
    if "{{PRODUCTS_SECTION}}" in html:
        html = html.replace("{{PRODUCTS_SECTION}}", products_html)
        placeholder_replaced = True
    if "{{GALLERY_SECTION}}" in html:
        html = html.replace("{{GALLERY_SECTION}}", gallery_html)
        placeholder_replaced = True
    if "{{TESTIMONIALS_SECTION}}" in html:
        html = html.replace("{{TESTIMONIALS_SECTION}}", testimonials_html)
        placeholder_replaced = True
    if placeholder_replaced:
        # Old templates may have ONE placeholder but not all three; for
        # the missing ones, fall through and append before </body>.
        leftovers = []
        if "{{PRODUCTS_SECTION}}" not in (products_html + gallery_html + testimonials_html):
            # the placeholder we just replaced was already filled; nothing to add
            pass
        # Append remaining sections only if they weren't placed via placeholder
        # and haven't already been written into the document.
        # Since placeholder replacement was scoped above, the legacy append
        # path still runs for any section without a placeholder.
        if "{{PRODUCTS_SECTION}}" not in html and products_html and products_html not in html:
            leftovers.append(products_html)
        if "{{GALLERY_SECTION}}" not in html and gallery_html and gallery_html not in html:
            leftovers.append(gallery_html)
        if "{{TESTIMONIALS_SECTION}}" not in html and testimonials_html and testimonials_html not in html:
            leftovers.append(testimonials_html)
        extra = "".join(leftovers)
        if not extra:
            return html
        if "</body>" in html:
            return html.replace("</body>", extra + "\n</body>", 1)
        if "</BODY>" in html:
            return html.replace("</BODY>", extra + "\n</BODY>", 1)
        return html + extra

    # No placeholders at all -> legacy append-before-</body> behavior.
    extra = products_html + gallery_html + testimonials_html
    if not extra:
        return html
    if "</body>" in html:
        return html.replace("</body>", extra + "\n</body>", 1)
    if "</BODY>" in html:
        return html.replace("</BODY>", extra + "\n</BODY>", 1)
    return html + extra


logger = logging.getLogger("public_site")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] public: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

def _supabase_url(): return os.environ.get("SUPABASE_URL", "")
def _supabase_anon(): return os.environ.get("SUPABASE_ANON", "")

# In-memory rate limiter
_rate_buckets: Dict[str, Dict[str, Any]] = {}

def _check_rate(slug: str) -> bool:
    now = time.time()
    bucket = _rate_buckets.get(slug)
    if not bucket or now - bucket["start"] > RATE_WINDOW_SEC:
        _rate_buckets[slug] = {"start": now, "count": 1}
        return True
    if bucket["count"] >= RATE_LIMIT_PER_MIN:
        return False
    bucket["count"] += 1
    return True

# ═══════════════════════════════════════════════════════════════════════
# SUPABASE HELPER
# ═══════════════════════════════════════════════════════════════════════

async def _sb(client: httpx.AsyncClient, path: str):
    url = f"{_supabase_url()}/rest/v1{path}"
    headers = {
        "apikey": _supabase_anon(),
        "Authorization": f"Bearer {_supabase_anon()}",
        "Content-Type": "application/json",
    }
    resp = await client.get(url, headers=headers, timeout=HTTP_TIMEOUT)
    if resp.status_code >= 400:
        return None
    text = resp.text
    return json.loads(text) if text else None

async def _sb_post(client: httpx.AsyncClient, path: str, body: dict):
    url = f"{_supabase_url()}/rest/v1{path}"
    headers = {
        "apikey": _supabase_anon(),
        "Authorization": f"Bearer {_supabase_anon()}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    resp = await client.post(url, headers=headers, content=json.dumps(body), timeout=HTTP_TIMEOUT)
    if resp.status_code >= 400:
        logger.error(f"Supabase POST {path}: {resp.status_code} {resp.text[:200]}")
        return None
    text = resp.text
    return json.loads(text) if text else None


async def _sb_patch(client: httpx.AsyncClient, path: str, body: dict):
    """Pass 3: PATCH helper for the new Smart Sites endpoints."""
    url = f"{_supabase_url()}/rest/v1{path}"
    headers = {
        "apikey": _supabase_anon(),
        "Authorization": f"Bearer {_supabase_anon()}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    resp = await client.patch(url, headers=headers, content=json.dumps(body), timeout=HTTP_TIMEOUT)
    if resp.status_code >= 400:
        logger.error(f"Supabase PATCH {path}: {resp.status_code} {resp.text[:200]}")
        return None
    text = resp.text
    return json.loads(text) if text else None

# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def _filter_entry(entry_data: Dict, visible: List[str], hidden: List[str]) -> Dict:
    """Keep only visible fields, remove hidden ones. If visible is empty, show all except hidden."""
    if visible:
        return {k: v for k, v in entry_data.items() if k in visible and k not in hidden}
    return {k: v for k, v in entry_data.items() if k not in hidden}


def _palette_for(biz_type: str) -> Dict[str, str]:
    return TYPE_PALETTES.get(biz_type, DEFAULT_PALETTE)


def _render_entries_html(entries: List[Dict], display_type: str, palette: Dict[str, str]) -> str:
    """Render module entries as HTML based on display_type."""
    if not entries:
        return '<p style="color:' + palette["muted"] + ';font-style:italic;">No items yet.</p>'

    if display_type == "grid":
        cards = []
        for e in entries:
            title = e.get("title") or e.get("deliverable_name") or e.get("name") or ""
            body_parts = [f'<strong>{title}</strong>'] if title else []
            for k, v in e.items():
                if k in ("title", "deliverable_name", "name") or v is None or v == "":
                    continue
                body_parts.append(f'<span style="color:{palette["muted"]};font-size:0.85em">{k}: {v}</span>')
            cards.append(
                f'<div style="background:{palette["card"]};border:1px solid {palette["border"]};'
                f'border-radius:10px;padding:16px;display:flex;flex-direction:column;gap:6px;">'
                + "<br>".join(body_parts) + '</div>'
            )
        return (
            '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:14px;">'
            + "".join(cards) + '</div>'
        )

    if display_type == "wall":
        tiles = []
        for e in entries:
            title = e.get("title") or e.get("quote") or next((str(v) for v in e.values() if v), "")
            status = e.get("status") or ""
            tiles.append(
                f'<div style="background:{palette["card"]};border:1px solid {palette["border"]};'
                f'border-left:3px solid {palette["accent"]};border-radius:0 8px 8px 0;'
                f'padding:14px;break-inside:avoid;margin-bottom:10px;">'
                f'<div style="font-size:0.95em;line-height:1.5;">{title}</div>'
                + (f'<div style="font-size:0.75em;color:{palette["muted"]};margin-top:6px;text-transform:uppercase;letter-spacing:1px;">{status}</div>' if status else '')
                + '</div>'
            )
        return (
            '<div style="column-count:2;column-gap:14px;">'
            + "".join(tiles) + '</div>'
        )

    if display_type == "catalog":
        items = []
        for e in entries:
            title = e.get("title") or e.get("name") or ""
            desc = e.get("description") or ""
            price = e.get("price")
            price_str = f'${price}' if price is not None else ""
            items.append(
                f'<div style="background:{palette["card"]};border:1px solid {palette["border"]};'
                f'border-radius:10px;padding:18px;display:flex;flex-direction:column;gap:8px;">'
                f'<div style="font-size:1.1em;font-weight:600;">{title}</div>'
                + (f'<div style="font-size:0.85em;color:{palette["muted"]};line-height:1.5;">{desc[:200]}</div>' if desc else '')
                + (f'<div style="font-size:1.2em;font-weight:700;color:{palette["accent"]};">{price_str}</div>' if price_str else '')
                + '</div>'
            )
        return (
            '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px;">'
            + "".join(items) + '</div>'
        )

    # Default: list
    rows = []
    for e in entries:
        title = e.get("title") or e.get("deliverable_name") or e.get("name") or str(next(iter(e.values()), ""))
        sub = e.get("description") or e.get("status") or ""
        rows.append(
            f'<div style="padding:12px 0;border-bottom:1px solid {palette["border"]};display:flex;justify-content:space-between;align-items:center;">'
            f'<span>{title}</span>'
            + (f'<span style="font-size:0.8em;color:{palette["muted"]};">{sub}</span>' if sub else '')
            + '</div>'
        )
    return '<div>' + "".join(rows) + '</div>'


def _build_widget_html(module: Dict, entries: List[Dict], biz: Dict) -> str:
    pd = module.get("public_display") or {}
    display_type = pd.get("display_type", "list")
    title = pd.get("title_override") or module.get("name", "")
    description = pd.get("description") or ""
    palette = _palette_for(biz.get("type", "general"))

    entries_html = _render_entries_html(entries, display_type, palette)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: 'Inter', system-ui, sans-serif;
  background: {palette['bg']};
  color: {palette['text']};
  padding: 24px;
  line-height: 1.6;
}}
h2 {{ font-size: 1.4em; font-weight: 700; margin-bottom: 6px; color: {palette['text']}; }}
.desc {{ font-size: 0.9em; color: {palette['muted']}; margin-bottom: 18px; }}
</style>
</head>
<body>
<h2>{title}</h2>
{f'<p class="desc">{description}</p>' if description else ''}
{entries_html}
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════════

router = APIRouter(tags=["public_site"])


@router.get("/public/site/{slug}")
async def get_site_html(slug: str):
    """Return the full generated site HTML for hosting/preview."""
    if not _check_rate(slug):
        raise HTTPException(429, "Rate limit exceeded")

    async with httpx.AsyncClient() as client:
        # Accept both draft and published sites so practitioners can preview
        sites = await _sb(client,
            f"/business_sites?slug=eq.{slug}&order=updated_at.desc&limit=1"
            f"&select=html_content,business_id,status,site_config")
        if not sites:
            raise HTTPException(404, "Site not found")
        site = sites[0]
        biz_id = site.get("business_id")

        # Pass 3: Smart Sites flag-gate. ANY failure falls through to legacy.
        if _use_smart_sites(site) and biz_id:
            products_for_smart = await _sb(client,
                f"/products?business_id=eq.{biz_id}&status=eq.active&display_on_website=eq.true"
                f"&order=sort_order.asc,created_at.desc&select=*&limit=100") or []
            smart_html = await _try_render_smart_site(
                biz_id, "home", products=products_for_smart)
            if smart_html:
                return HTMLResponse(
                    content=smart_html, status_code=200, media_type="text/html",
                    headers={"X-Solutionist-Source": "smart-sites"})

        html = site.get("html_content") or ""
        if not html:
            raise HTTPException(404, "Site has no content")

        # Pull live products + media library + verified testimonials so
        # they update without a regen.
        products: List[Dict[str, Any]] = []
        gallery: List[Dict[str, Any]] = []
        testimonials: List[Dict[str, Any]] = []
        brand_color = "#D4AF37"
        biz_settings: Dict[str, Any] = {}
        if biz_id:
            prod_rows, biz_rows = await asyncio.gather(
                _sb(client,
                    f"/products?business_id=eq.{biz_id}&status=eq.active&display_on_website=eq.true"
                    f"&order=sort_order.asc,created_at.desc&select=*&limit=100"),
                _sb(client, f"/businesses?id=eq.{biz_id}&select=settings&limit=1"),
            )
            products = prod_rows or []
            if biz_rows:
                biz_settings = biz_rows[0].get("settings") or {}
                lib = biz_settings.get("media_library") or {}
                gallery = lib.get("gallery") or []
                website_content = biz_settings.get("website_content") or {}
                testimonials = website_content.get("testimonials") or []
                bk = biz_settings.get("brand_kit") or {}
                bc = (bk.get("primary_color") or "").strip() if isinstance(bk, dict) else ""
                if bc.startswith("#") and (len(bc) == 7 or len(bc) == 4):
                    brand_color = bc

        html = _inject_canonical(html, slug)
        # Pass 3: activate the dormant Pass 2.5a meta-tag helper.
        html = _inject_brand_meta(html, biz_id)
        html = _inject_dynamic_sections(
            html,
            _render_products_section(products, slug, brand_color, biz_settings),
            _render_gallery_section(gallery),
            _render_testimonials_section(testimonials),
        )
        return HTMLResponse(
            content=html,
            status_code=200,
            media_type="text/html",
            headers={"X-Solutionist-Source": "public-site"},
        )


@router.get("/public/site/{slug}/data")
async def get_site_data(slug: str):
    """Return structured JSON for dynamic site sections + forms."""
    if not _check_rate(slug):
        raise HTTPException(429, "Rate limit exceeded")

    async with httpx.AsyncClient() as client:
        sites = await _sb(client,
            f"/business_sites?slug=eq.{slug}&limit=1&select=business_id,site_config")
        if not sites:
            raise HTTPException(404, "Site not found")
        biz_id = sites[0]["business_id"]

        biz_rows, modules, forms = await asyncio.gather(
            _sb(client, f"/businesses?id=eq.{biz_id}&select=name,type,voice_profile&limit=1"),
            _sb(client, f"/custom_modules?business_id=eq.{biz_id}&is_active=eq.true"
                        f"&select=id,name,schema,public_display&limit=50"),
            _sb(client, f"/intake_forms?business_id=eq.{biz_id}&is_active=eq.true"
                        f"&select=id,name,form_type,settings&limit=20"),
        )

        biz = biz_rows[0] if biz_rows else {}

        # Filter to public modules and fetch their entries
        public_modules = [
            m for m in (modules or [])
            if (m.get("public_display") or {}).get("enabled")
        ]

        entry_tasks = [
            _sb(client,
                f"/module_entries?module_id=eq.{m['id']}&status=eq.active"
                f"&order={(m.get('public_display') or {}).get('sort_by', 'created_at')}.desc"
                f"&limit={(m.get('public_display') or {}).get('max_display', 20)}"
                f"&select=id,data,created_at")
            for m in public_modules
        ]
        entry_results = await asyncio.gather(*entry_tasks) if entry_tasks else []

        sections = []
        for i, m in enumerate(public_modules):
            pd = m.get("public_display") or {}
            visible = pd.get("visible_fields") or []
            hidden = pd.get("hidden_fields") or ["assigned_to", "internal_notes", "contact_id"]
            filter_status = pd.get("filter_status") or []

            raw_entries = entry_results[i] or []
            filtered = []
            for e in raw_entries:
                data = e.get("data") or {}
                if filter_status and data.get("status") not in filter_status:
                    continue
                filtered.append({
                    **_filter_entry(data, visible, hidden),
                    "created_at": e.get("created_at"),
                })

            sections.append({
                "module_id": m["id"],
                "title": pd.get("title_override") or m.get("name"),
                "display_type": pd.get("display_type", "list"),
                "description": pd.get("description") or "",
                "entries": filtered,
            })

        # Forms linked to public modules
        public_mod_ids = {m["id"] for m in public_modules}
        linked_forms = [
            {"form_id": f["id"], "name": f["name"],
             "embed_url": f"/public/widget/form/{f['id']}"}
            for f in (forms or [])
            if (f.get("settings") or {}).get("linked_module_id") in public_mod_ids
        ]

        return {
            "business": {
                "name": biz.get("name"),
                "type": biz.get("type"),
            },
            "sections": sections,
            "forms": linked_forms,
        }


@router.get("/public/{slug}/thank-you")
async def thank_you_page(slug: str):
    """Branded thank-you page shown after a Stripe checkout completes.

    Reads the business name + brand_kit.primary_color from settings so
    the success state matches the rest of the practitioner's site.
    """
    if not _check_rate(f"thank-you-{slug}"):
        raise HTTPException(429, "Rate limit exceeded")

    name = "Thank You"
    accent = "#D4AF37"
    home_link = f"/public/site/{slug}"
    biz_id: Optional[str] = None

    async with httpx.AsyncClient() as client:
        sites = await _sb(client,
            f"/business_sites?slug=eq.{slug}&limit=1&select=business_id,site_config")
        if sites:
            biz_id = sites[0].get("business_id")
            # Pass 3: Smart Sites flag-gate (try/except always falls through)
            if _use_smart_sites(sites[0]) and biz_id:
                smart_html = await _try_render_smart_site(biz_id, "thank_you")
                if smart_html:
                    return HTMLResponse(content=smart_html, media_type="text/html",
                                        headers={"X-Solutionist-Source": "smart-sites"})
            if biz_id:
                biz_rows = await _sb(client,
                    f"/businesses?id=eq.{biz_id}&select=name,settings&limit=1")
                if biz_rows:
                    biz = biz_rows[0]
                    name = biz.get("name") or name
                    bk = (biz.get("settings") or {}).get("brand_kit") or {}
                    if isinstance(bk, dict):
                        bc = (bk.get("primary_color") or "").strip()
                        if bc.startswith("#") and (len(bc) == 7 or len(bc) == 4):
                            accent = bc

    safe_name = _esc(name)
    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<title>Thank You &mdash; {safe_name}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<style>
* {{ box-sizing: border-box; }}
body {{
  margin:0; min-height:100vh; padding:24px;
  display:flex; align-items:center; justify-content:center;
  background:#0a0a0f; color:#e8e6e3;
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Inter,sans-serif;
  text-align:center;
}}
.wrap {{ max-width: 480px; }}
.check {{
  width:72px; height:72px; border-radius:50%;
  background: color-mix(in srgb, {accent} 16%, transparent);
  border: 2px solid {accent};
  display:flex; align-items:center; justify-content:center;
  margin:0 auto 24px;
  font-size:34px; color:{accent}; font-weight:700;
}}
h1 {{ font-size:30px; font-weight:700; margin:0 0 12px; letter-spacing:-0.01em; }}
p {{ color:#aaa; font-size:16px; line-height:1.6; margin:0 0 28px; }}
a.btn {{
  display:inline-block; padding:12px 24px;
  background:{accent}; color:#0a0a0f; font-weight:600;
  text-decoration:none; border-radius:8px;
  transition: opacity 0.2s;
}}
a.btn:hover {{ opacity: 0.9; }}
.muted {{ color:#666; font-size:13px; margin-top:18px; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="check">&#10003;</div>
  <h1>Thank you!</h1>
  <p>Your purchase is confirmed. A confirmation email is on its way &mdash; and if your purchase includes a download, you'll get a delivery email shortly.</p>
  <a class="btn" href="{home_link}">&larr; Back to {safe_name}</a>
  <div class="muted">Powered by The Solutionist System</div>
</div>
</body></html>"""

    # Pass 3: legacy thank-you also gets favicons + OG tags now.
    html = _inject_brand_meta(html, biz_id)
    return HTMLResponse(content=html, status_code=200, media_type="text/html")


@router.post("/sites/{business_id}/invalidate")
async def invalidate_site_cache(business_id: str):
    """Bump business_sites.updated_at so consumers see a fresh
    revision after products / brand_kit / testimonials change.

    The static template HTML is regenerated client-side via the BUILD
    > My Site flow; what changes here is only the dynamically-injected
    sections (products, gallery, testimonials) and the brand colors
    applied at request time. Calling this endpoint is a no-op if the
    business has no published site row yet.
    """
    async with httpx.AsyncClient() as client:
        sites = await _sb(client, f"/business_sites?business_id=eq.{business_id}&select=id&limit=1")
        if not sites:
            return {"status": "no_site"}
        site_id = sites[0]["id"]
        url = f"{_supabase_url()}/rest/v1/business_sites?id=eq.{site_id}"
        headers = {
            "apikey": _supabase_anon(),
            "Authorization": f"Bearer {_supabase_anon()}",
            "Content-Type": "application/json",
        }
        try:
            await client.patch(
                url,
                headers=headers,
                content=json.dumps({"updated_at": datetime.now(timezone.utc).isoformat()}),
                timeout=HTTP_TIMEOUT,
            )
        except Exception as e:
            logger.warning(f"site invalidate patch failed: {e}")
        return {"status": "invalidated", "site_id": site_id}


# ═══════════════════════════════════════════════════════════════════════
# SMART SITES v1 — config + preview + enable/disable endpoints (Pass 3)
# ═══════════════════════════════════════════════════════════════════════


@router.post("/sites/{business_id}/smart-config")
async def save_smart_config_endpoint(business_id: str, body: Dict[str, Any]):
    """Save (merge into) site_config without flipping the use_smart_sites
    flag. Body shape: any subset of SmartSiteConfig keys."""
    try:
        from smart_sites import save_smart_config
        result = save_smart_config(business_id, body or {})
        if not result.get("ok"):
            raise HTTPException(404, result.get("error", "save failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[smart_sites] save_smart_config failed: {e}")
        raise HTTPException(500, "save failed")


@router.post("/sites/{business_id}/smart-preview")
async def smart_preview_endpoint(business_id: str, body: Dict[str, Any]):
    """Render Smart Sites preview from a draft config without persisting.
    Used by MySite.tsx live preview iframe."""
    try:
        from smart_sites import render_smart_site_preview
        html = render_smart_site_preview(business_id, body or {})
        return HTMLResponse(content=html, media_type="text/html")
    except Exception as e:
        logger.warning(f"[smart_sites] preview failed: {e}")
        raise HTTPException(500, f"preview failed: {e}")


@router.post("/sites/{business_id}/smart-enable")
async def smart_enable_endpoint(business_id: str):
    """Flip use_smart_sites = true. Seeds defaults from bundle if empty."""
    try:
        from smart_sites import enable_smart_sites
        result = enable_smart_sites(business_id)
        if not result.get("ok"):
            raise HTTPException(404, result.get("error", "enable failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[smart_sites] enable failed: {e}")
        raise HTTPException(500, "enable failed")


@router.post("/sites/{business_id}/smart-disable")
async def smart_disable_endpoint(business_id: str):
    """Flip use_smart_sites = false. Falls back to legacy rendering."""
    try:
        from smart_sites import disable_smart_sites
        result = disable_smart_sites(business_id)
        if not result.get("ok"):
            raise HTTPException(404, result.get("error", "disable failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[smart_sites] disable failed: {e}")
        raise HTTPException(500, "disable failed")


# ─── Pass 3.5 Session 3: layout-options + layout-override endpoints ───


@router.get("/sites/{business_id}/layout-options")
async def layout_options_endpoint(business_id: str):
    """Return detected vocabularies (top 3) + available layouts for the
    primary vocabulary. Drives the MySite Design System override UI."""
    try:
        from brand_engine import _sb_get as be_get
        from studio_data import LAYOUTS, VOCAB_LAYOUT_MAP
        from studio_vocab_detect import detect_vocabularies

        biz_rows = be_get(f"/businesses?id=eq.{business_id}&select=*&limit=1") or []
        if not biz_rows:
            raise HTTPException(404, "Business not found")
        business_data = biz_rows[0]
        voice_profile = business_data.get("voice_profile") or {}
        brand_kit = (business_data.get("settings") or {}).get("brand_kit") or {}

        profile_rows = be_get(
            f"/business_profiles?business_id=eq.{business_id}&select=*&limit=1"
        ) or []
        business_profile = profile_rows[0] if profile_rows else {}

        site_rows = be_get(
            f"/business_sites?business_id=eq.{business_id}&select=site_config&limit=1"
        ) or []
        site_config = (site_rows[0].get("site_config") if site_rows else {}) or {}

        matches = detect_vocabularies(
            business_data, business_profile, voice_profile, brand_kit
        )

        vocab_options = [
            {
                "id": m["vocabulary"]["id"],
                "name": m["vocabulary"]["name"],
                "section": m["vocabulary"]["section"],
                "color_palette": m["vocabulary"]["color_palette"],
                "confidence": round(m["confidence"], 2),
                "reasons": m["reasons"][:3],
            }
            for m in matches
        ]

        active_vocab = (
            site_config.get("vocabulary_override")
            or (matches[0]["vocabulary"]["id"] if matches else None)
        )

        layout_ids = VOCAB_LAYOUT_MAP.get(active_vocab, []) if active_vocab else []
        layout_options = [
            {
                "id": lid,
                "name": LAYOUTS[lid]["name"],
                "description": LAYOUTS[lid]["description"],
            }
            for lid in layout_ids
            if lid in LAYOUTS
        ]

        active_layout = site_config.get("layout_id") or (
            layout_ids[0] if layout_ids else None
        )

        return {
            "ok": True,
            "vocab_options": vocab_options,
            "layout_options": layout_options,
            "active_vocab": active_vocab,
            "active_layout": active_layout,
            "is_using_override": bool(
                site_config.get("layout_id") or site_config.get("vocabulary_override")
            ),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[smart_sites] layout-options failed for {business_id}: {e}")
        raise HTTPException(500, "layout-options failed")


@router.post("/sites/{business_id}/layout-override")
async def layout_override_endpoint(business_id: str, body: Dict[str, Any]):
    """Save vocabulary or layout override into site_config.

    Body: { vocabulary_override: <vocab-id> | null, layout_id: <layout-id> | null }
    Pass null (or omit either key) to reset to auto-detect.
    """
    try:
        from brand_engine import _sb_get as be_get, _sb_patch as be_patch
        from studio_data import LAYOUTS, VOCABULARIES

        body = body or {}

        # Validate against the known sets (None / null is always allowed = clear)
        vocab_value = body.get("vocabulary_override", "__unset__")
        layout_value = body.get("layout_id", "__unset__")
        if vocab_value not in ("__unset__", None) and vocab_value not in VOCABULARIES:
            raise HTTPException(400, f"Unknown vocabulary: {vocab_value}")
        if layout_value not in ("__unset__", None) and layout_value not in LAYOUTS:
            raise HTTPException(400, f"Unknown layout: {layout_value}")

        sites = be_get(
            f"/business_sites?business_id=eq.{business_id}&select=id,site_config&limit=1"
        ) or []
        if not sites:
            raise HTTPException(404, "No business_sites row")
        site_id = sites[0]["id"]
        current = sites[0].get("site_config") or {}

        new_config = dict(current)
        if vocab_value != "__unset__":
            if vocab_value is None:
                new_config.pop("vocabulary_override", None)
            else:
                new_config["vocabulary_override"] = vocab_value
        if layout_value != "__unset__":
            if layout_value is None:
                new_config.pop("layout_id", None)
            else:
                new_config["layout_id"] = layout_value

        be_patch(f"/business_sites?id=eq.{site_id}", {"site_config": new_config})
        return {"ok": True, "site_config": new_config}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"[smart_sites] layout-override failed for {business_id}: {e}")
        raise HTTPException(500, "layout-override failed")


@router.get("/public/widget/{module_id}")
async def get_widget(module_id: str):
    """Return a self-contained styled HTML page for iframe embedding."""
    if not _check_rate(module_id):
        raise HTTPException(429, "Rate limit exceeded")

    async with httpx.AsyncClient() as client:
        modules = await _sb(client,
            f"/custom_modules?id=eq.{module_id}&is_active=eq.true&limit=1&select=*")
        if not modules:
            raise HTTPException(404, "Module not found")
        module = modules[0]

        pd = module.get("public_display") or {}
        if not pd.get("enabled"):
            raise HTTPException(403, "Module not publicly visible")

        biz_id = module["business_id"]
        biz_rows = await _sb(client,
            f"/businesses?id=eq.{biz_id}&select=name,type,voice_profile&limit=1")
        biz = biz_rows[0] if biz_rows else {}

        sort_field = pd.get("sort_by", "created_at")
        max_display = pd.get("max_display", 20)
        filter_status = pd.get("filter_status") or []
        visible = pd.get("visible_fields") or []
        hidden = pd.get("hidden_fields") or ["assigned_to", "internal_notes", "contact_id"]

        raw = await _sb(client,
            f"/module_entries?module_id=eq.{module_id}&status=eq.active"
            f"&order={sort_field}.desc&limit={max_display}&select=id,data,created_at") or []

        entries = []
        for e in raw:
            data = e.get("data") or {}
            if filter_status and data.get("status") not in filter_status:
                continue
            entries.append(_filter_entry(data, visible, hidden))

        html = _build_widget_html(module, entries, biz)
        return HTMLResponse(content=html)


# ═══════════════════════════════════════════════════════════════════════
# LINK PAGE ENDPOINT
# ═══════════════════════════════════════════════════════════════════════


@router.get("/public/link/{slug}")
async def link_page_html(slug: str):
    """Render a Linktree-style link page."""
    if not _check_rate(f"link-{slug}"):
        raise HTTPException(429, "Rate limit exceeded")

    async with httpx.AsyncClient() as client:
        # Find business by link_page slug
        biz_rows = await _sb(client, "/businesses?select=id,name,type,settings&limit=200")
        biz = None
        for b in (biz_rows or []):
            lp = (b.get("settings") or {}).get("link_page") or {}
            if lp.get("slug") == slug and lp.get("enabled"):
                biz = b
                break
        if not biz:
            raise HTTPException(404, "Link page not found")

        # Pass 3: Smart Sites flag-gate. Pull site_config to check the flag.
        biz_id_for_smart = biz["id"]
        site_rows = await _sb(client,
            f"/business_sites?business_id=eq.{biz_id_for_smart}&limit=1&select=site_config")
        if site_rows and _use_smart_sites(site_rows[0]):
            lp_for_smart = (biz.get("settings") or {}).get("link_page") or {}
            smart_links = lp_for_smart.get("custom_links") or []
            smart_html = await _try_render_smart_site(
                biz_id_for_smart, "link", links=smart_links)
            if smart_html:
                return HTMLResponse(content=smart_html, media_type="text/html",
                                    headers={"X-Solutionist-Source": "smart-sites"})

        brand = (biz.get("settings") or {}).get("brand_kit") or {}
        lp = (biz.get("settings") or {}).get("link_page") or {}
        colors = brand.get("colors") or _palette_for(biz.get("type", "general"))
        biz_name = biz.get("name", "")
        tagline = brand.get("tagline", "")
        practitioner = (biz.get("settings") or {}).get("practitioner_name", biz_name)

        layout = lp.get("layout", "stack")
        bg_style = lp.get("background", "gradient")
        primary = colors.get("primary", "#333")
        secondary = colors.get("secondary", "#666")
        bg = colors.get("background", "#faf8f5")
        text_color = colors.get("text", "#1a1a2e")

        if bg_style == "gradient":
            bg_css = f"linear-gradient(135deg, {primary}22, {secondary}22)"
        elif bg_style == "dark":
            bg_css = "#0d0d12"
            text_color = "#E8E4DD"
        else:
            bg_css = bg

        # Gather links
        biz_id = biz["id"]
        sites, forms, modules = await asyncio.gather(
            _sb(client, f"/business_sites?business_id=eq.{biz_id}&limit=1&select=slug"),
            _sb(client, f"/intake_forms?business_id=eq.{biz_id}&is_active=eq.true&select=id,name&limit=20"),
            _sb(client, f"/custom_modules?business_id=eq.{biz_id}&is_active=eq.true&select=id,name,icon,public_display&limit=20"),
        )

        links_html = ""
        auto_links = []
        site_slug = sites[0]["slug"] if sites else None
        if site_slug:
            auto_links.append(("🌐", "Website", f"/public/site/{site_slug}"))
        booking = (biz.get("settings") or {}).get("booking") or {}
        if booking.get("enabled") and site_slug:
            auto_links.append(("📅", "Book a Session", f"/public/booking/{site_slug}"))
        for f in (forms or []):
            auto_links.append(("📥", f["name"], "#"))
        for m in (modules or []):
            if (m.get("public_display") or {}).get("enabled"):
                auto_links.append((m.get("icon", "🧩"), m["name"], f"/public/widget/{m['id']}"))
        for cl in (lp.get("custom_links") or []):
            auto_links.append((cl.get("icon", "🔗"), cl.get("label", "Link"), cl.get("url", "#")))

        btn_style = (
            f"display:block;width:100%;padding:14px 20px;margin-bottom:10px;background:#fff;"
            f"border:1.5px solid {primary}30;border-radius:10px;text-decoration:none;"
            f"color:{text_color};font-weight:600;font-size:0.95em;text-align:center;"
            f"transition:transform 0.15s,box-shadow 0.15s;"
        )
        for icon, label, url in auto_links:
            links_html += f'<a href="{url}" style="{btn_style}" onmouseover="this.style.transform=\'translateY(-2px)\';this.style.boxShadow=\'0 4px 12px rgba(0,0,0,0.1)\'" onmouseout="this.style.transform=\'\';this.style.boxShadow=\'\'">{icon} {label}</a>\n'

        # Social icons
        socials = lp.get("social_profiles") or {}
        social_html = ""
        social_map = {"instagram": "📸", "facebook": "📘", "youtube": "📺", "twitter": "🐦", "linkedin": "💼", "tiktok": "🎵"}
        for platform, handle in socials.items():
            if not handle:
                continue
            social_html += f'<span style="font-size:1.4em;cursor:pointer;" title="{platform}: {handle}">{social_map.get(platform, "🔗")}</span> '

        # Optional gallery — pulls from media_library when toggled on
        gallery_html = ""
        if lp.get("show_gallery"):
            lib = ((biz.get("settings") or {}).get("media_library") or {})
            gallery_items = [g for g in (lib.get("gallery") or []) if g.get("show_on_website", True) and g.get("url")]
            gallery_items.sort(key=lambda g: g.get("sort_order") or 0)
            if gallery_items:
                tiles = "".join(
                    f'<a href="{_esc(g.get("url"))}" target="_blank" rel="noreferrer" '
                    f'style="display:block;aspect-ratio:1/1;border-radius:8px;overflow:hidden;background:#0001;">'
                    f'<img src="{_esc(g.get("url"))}" alt="{_esc(g.get("alt") or "")}" loading="lazy" '
                    f'style="width:100%;height:100%;object-fit:cover;display:block;" /></a>'
                    for g in gallery_items[:9]
                )
                gallery_html = (
                    f'<div style="margin-top:24px;display:grid;grid-template-columns:repeat(3,1fr);gap:8px;">{tiles}</div>'
                )

        html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{practitioner} — {biz_name}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:'Inter',sans-serif;background:{bg_css};color:{text_color};min-height:100vh;display:flex;justify-content:center;padding:40px 20px;}}
.container{{max-width:420px;width:100%;text-align:center;}}
.avatar{{width:80px;height:80px;border-radius:50%;background:{primary};color:#fff;display:inline-flex;align-items:center;justify-content:center;font-size:2em;font-weight:700;margin-bottom:12px;}}
h1{{font-size:1.4em;font-weight:700;margin-bottom:4px;}}
.tagline{{color:{primary};font-size:0.9em;margin-bottom:24px;font-style:italic;}}
.socials{{margin-top:20px;display:flex;gap:12px;justify-content:center;}}
.footer{{margin-top:30px;font-size:0.7em;color:{text_color}55;}}
</style></head>
<body><div class="container">
<div class="avatar">{biz_name[0] if biz_name else '?'}</div>
<h1>{practitioner}</h1>
{f'<p class="tagline">{tagline}</p>' if tagline else f'<p class="tagline">{biz_name}</p>'}
{links_html}
{f'<div class="socials">{social_html}</div>' if social_html else ''}
{gallery_html}
<div class="footer">Powered by The Solutionist System</div>
</div></body></html>"""
        # Pass 3: legacy link page also gets favicons + OG tags now.
        html = _inject_brand_meta(html, biz_id_for_smart)
        return HTMLResponse(content=html)


@router.post("/public/link/{slug}/track")
async def track_link_click(slug: str, link_id: str = "", referrer: str = ""):
    """Log a link page click event."""
    if not _check_rate(f"link-track-{slug}"):
        raise HTTPException(429, "Rate limit exceeded")
    async with httpx.AsyncClient() as client:
        biz_rows = await _sb(client, "/businesses?select=id,settings&limit=200")
        biz_id = None
        for b in (biz_rows or []):
            if ((b.get("settings") or {}).get("link_page") or {}).get("slug") == slug:
                biz_id = b["id"]
                break
        if not biz_id:
            raise HTTPException(404, "Business not found")
        await _sb_post(client, "/events", {
            "business_id": biz_id,
            "event_type": "link_page_click",
            "data": {"link_id": link_id, "referrer": referrer, "slug": slug},
            "source": "link_page",
        })
        return {"tracked": True}


# ═══════════════════════════════════════════════════════════════════════
# RESOURCE LIBRARY ENDPOINT
# ═══════════════════════════════════════════════════════════════════════


@router.get("/public/resources/{slug}")
async def resource_library_html(slug: str):
    """Render a public resource library page."""
    if not _check_rate(f"resources-{slug}"):
        raise HTTPException(429, "Rate limit exceeded")

    async with httpx.AsyncClient() as client:
        sites = await _sb(client,
            f"/business_sites?slug=eq.{slug}&limit=1&select=business_id,site_config")
        if not sites:
            raise HTTPException(404, "Business not found")
        biz_id = sites[0]["business_id"]

        biz_rows, modules = await asyncio.gather(
            _sb(client, f"/businesses?id=eq.{biz_id}&select=name,type,settings&limit=1"),
            _sb(client, f"/custom_modules?business_id=eq.{biz_id}&name=eq.Resources&is_active=eq.true&limit=1&select=id"),
        )
        biz = biz_rows[0] if biz_rows else {}
        brand = (biz.get("settings") or {}).get("brand_kit") or {}
        colors = brand.get("colors") or _palette_for(biz.get("type", "general"))
        module_id = modules[0]["id"] if modules else None

        if not module_id:
            raise HTTPException(404, "No resource library")

        entries = await _sb(client,
            f"/module_entries?module_id=eq.{module_id}&status=eq.active&order=created_at.desc&limit=50&select=id,data") or []

        # Pass 3: Smart Sites flag-gate (try/except always falls through).
        if _use_smart_sites(sites[0]):
            smart_resources = [
                {**(e.get("data") or {}), "url": (e.get("data") or {}).get("resource_url")}
                for e in entries
            ]
            smart_html = await _try_render_smart_site(
                biz_id, "resources", resources=smart_resources)
            if smart_html:
                return HTMLResponse(content=smart_html, media_type="text/html",
                                    headers={"X-Solutionist-Source": "smart-sites"})

        primary = colors.get("primary", "#333")
        bg = colors.get("background", "#faf8f5")
        biz_name = biz.get("name", "")

        cards_html = ""
        for e in entries:
            d = e.get("data") or {}
            title = d.get("title", "(untitled)")
            desc = d.get("description", "")
            cat = d.get("category", "")
            access_type = d.get("access", "free")
            url = d.get("resource_url", "")
            is_gated = access_type == "gated"

            icon = "🔒" if is_gated else "📄"
            btn = f'<a href="{url}" target="_blank" style="display:inline-block;margin-top:10px;padding:8px 16px;background:{primary};color:#fff;border-radius:6px;text-decoration:none;font-size:0.85em;font-weight:600;">View Resource</a>' if url and not is_gated else '<span style="display:inline-block;margin-top:10px;padding:8px 16px;background:#ddd;color:#888;border-radius:6px;font-size:0.85em;">Contact us to access</span>'

            cards_html += f'''<div style="background:#fff;border:1px solid #e8e4dd;border-radius:10px;padding:18px;">
<div style="font-size:0.75em;text-transform:uppercase;letter-spacing:1px;color:{primary};font-weight:600;margin-bottom:6px;">{icon} {cat}</div>
<div style="font-size:1.05em;font-weight:600;margin-bottom:4px;">{title}</div>
{f'<div style="font-size:0.85em;color:#666;line-height:1.5;margin-bottom:4px;">{desc}</div>' if desc else ''}
{btn}
</div>'''

        html = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Resources — {biz_name}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:'Inter',sans-serif;background:{bg};color:#1a1a2e;padding:40px 20px;}}
.container{{max-width:800px;margin:0 auto;}}
h1{{font-size:1.8em;font-weight:700;margin-bottom:8px;}}
.sub{{color:#666;margin-bottom:24px;}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px;}}
</style></head>
<body><div class="container">
<h1>Resources</h1>
<p class="sub">{biz_name}</p>
<div class="grid">{cards_html}</div>
</div></body></html>"""
        # Pass 3: legacy resources page also gets favicons + OG tags now.
        html = _inject_brand_meta(html, biz_id)
        return HTMLResponse(content=html)


@router.post("/public/resources/{slug}/track")
async def track_resource_download(slug: str, resource_id: str = ""):
    """Log a resource download event."""
    if not _check_rate(f"res-track-{slug}"):
        raise HTTPException(429, "Rate limit exceeded")
    async with httpx.AsyncClient() as client:
        sites = await _sb(client, f"/business_sites?slug=eq.{slug}&limit=1&select=business_id")
        if not sites:
            raise HTTPException(404, "Business not found")
        await _sb_post(client, "/events", {
            "business_id": sites[0]["business_id"],
            "event_type": "resource_download",
            "data": {"resource_id": resource_id},
            "source": "resource_library",
        })
        return {"tracked": True}


# ═══════════════════════════════════════════════════════════════════════
# BOOKING ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════


@router.get("/public/booking/{slug}/slots")
async def booking_slots(slug: str, days: int = 14):
    """Return available time slots for the next N days."""
    if not _check_rate(f"booking-{slug}"):
        raise HTTPException(429, "Rate limit exceeded")

    async with httpx.AsyncClient() as client:
        # Look up business by slug from business_sites
        sites = await _sb(client, f"/business_sites?slug=eq.{slug}&limit=1&select=business_id")
        if not sites:
            raise HTTPException(404, "Business not found")
        biz_id = sites[0]["business_id"]

        biz_rows = await _sb(client, f"/businesses?id=eq.{biz_id}&select=name,settings&limit=1")
        if not biz_rows:
            raise HTTPException(404, "Business not found")
        biz = biz_rows[0]
        booking = (biz.get("settings") or {}).get("booking") or {}
        if not booking.get("enabled"):
            raise HTTPException(404, "Booking not enabled")

        available_days = set(booking.get("available_days", [1, 2, 3, 4, 5]))
        hours_start = booking.get("hours", {}).get("start", "09:00")
        hours_end = booking.get("hours", {}).get("end", "17:00")
        buffer = booking.get("buffer_minutes", 15)
        window = min(days, booking.get("booking_window_days", 14))
        session_types = list(booking.get("session_types", []) or [])
        durations = dict(booking.get("durations", {}) or {})

        # Pull bookable services from the products catalog. Any product
        # with type=service, status=active, display_on_website=true is
        # offered as a session type — that way adding a product in
        # BUILD -> Products & Services automatically makes it bookable.
        product_services = []
        try:
            product_services = await _sb(
                client,
                f"/products?business_id=eq.{biz_id}&status=eq.active"
                f"&type=eq.service&display_on_website=eq.true"
                f"&order=sort_order.asc&limit=50"
                f"&select=id,name,description,price,currency,pricing_type,duration_minutes"
            ) or []
        except Exception:
            product_services = []

        # Merge product services into the legacy session_types/durations
        # shape so the existing booking UI keeps working. Each product
        # name becomes a session type and its duration_minutes seeds the
        # durations map. Practitioner-defined session_types still win
        # for any name conflict.
        existing_keys = {str(t).lower() for t in session_types}
        product_meta: List[Dict[str, Any]] = []
        for p in product_services:
            name = (p.get("name") or "").strip()
            if not name:
                continue
            key = name.lower()
            if key not in existing_keys:
                session_types.append(name)
                existing_keys.add(key)
            dur = p.get("duration_minutes") or 60
            try:
                dur = int(dur)
            except (TypeError, ValueError):
                dur = 60
            if name not in durations:
                durations[name] = dur
            product_meta.append({
                "id": p.get("id"),
                "name": name,
                "description": p.get("description") or "",
                "price": p.get("price"),
                "currency": p.get("currency") or "USD",
                "pricing_type": p.get("pricing_type") or "fixed",
                "duration_minutes": dur,
            })
        min_duration = min(durations.values()) if durations else 60

        # Parse hours
        try:
            start_h, start_m = int(hours_start.split(":")[0]), int(hours_start.split(":")[1])
            end_h, end_m = int(hours_end.split(":")[0]), int(hours_end.split(":")[1])
        except (ValueError, IndexError):
            start_h, start_m, end_h, end_m = 9, 0, 17, 0

        # Get existing sessions in the window
        now = datetime.now(timezone.utc)
        window_end = now + timedelta(days=window)
        existing = await _sb(client,
            f"/sessions?business_id=eq.{biz_id}&status=eq.scheduled"
            f"&scheduled_for=gte.{now.isoformat()}&scheduled_for=lte.{window_end.isoformat()}"
            f"&select=scheduled_for,duration_minutes&limit=200") or []

        booked_ranges = []
        for s in existing:
            try:
                sdt = datetime.fromisoformat(s["scheduled_for"].replace("Z", "+00:00"))
                dur = s.get("duration_minutes") or 60
                booked_ranges.append((sdt, sdt + timedelta(minutes=dur + buffer)))
            except (ValueError, TypeError):
                pass

        # Generate slots
        slots = []
        for d in range(window):
            day = now.date() + timedelta(days=d + 1)
            # isoweekday: Mon=1 .. Sun=7
            if day.isoweekday() not in available_days:
                continue

            day_slots = []
            t_h, t_m = start_h, start_m
            while t_h < end_h or (t_h == end_h and t_m < end_m):
                slot_start = datetime(day.year, day.month, day.day, t_h, t_m, tzinfo=timezone.utc)
                slot_end = slot_start + timedelta(minutes=min_duration)
                if slot_end.hour > end_h or (slot_end.hour == end_h and slot_end.minute > end_m):
                    break

                # Check conflicts
                conflict = any(bs <= slot_start < be or bs < slot_end <= be for bs, be in booked_ranges)
                if not conflict:
                    day_slots.append(f"{t_h:02d}:{t_m:02d}")

                t_m += min_duration + buffer
                while t_m >= 60:
                    t_h += 1
                    t_m -= 60

            if day_slots:
                slots.append({"date": day.isoformat(), "times": day_slots})

        return {
            "slots": slots,
            "session_types": session_types,
            "durations": durations,
            "products": product_meta,
        }


class BookingSubmission(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    session_type: str
    date: str        # YYYY-MM-DD
    time: str        # HH:MM
    message: Optional[str] = None


@router.post("/public/booking/{slug}/submit")
async def booking_submit(slug: str, req: BookingSubmission):
    """Process a booking: create contact + session."""
    if not _check_rate(f"booking-{slug}"):
        raise HTTPException(429, "Rate limit exceeded")

    async with httpx.AsyncClient() as client:
        sites = await _sb(client, f"/business_sites?slug=eq.{slug}&limit=1&select=business_id")
        if not sites:
            raise HTTPException(404, "Business not found")
        biz_id = sites[0]["business_id"]

        biz_rows = await _sb(client, f"/businesses?id=eq.{biz_id}&select=name,settings&limit=1")
        if not biz_rows:
            raise HTTPException(404, "Business not found")
        biz = biz_rows[0]
        booking = (biz.get("settings") or {}).get("booking") or {}
        if not booking.get("enabled"):
            raise HTTPException(404, "Booking not enabled")

        durations = booking.get("durations") or {}
        duration = durations.get(req.session_type, 60)

        # Parse scheduled time
        try:
            scheduled = datetime.fromisoformat(f"{req.date}T{req.time}:00+00:00")
        except ValueError:
            raise HTTPException(400, "Invalid date/time")

        # Conflict check
        buffer = booking.get("buffer_minutes", 15)
        slot_end = scheduled + timedelta(minutes=duration + buffer)
        conflicts = await _sb(client,
            f"/sessions?business_id=eq.{biz_id}&status=eq.scheduled"
            f"&scheduled_for=gte.{(scheduled - timedelta(minutes=duration + buffer)).isoformat()}"
            f"&scheduled_for=lte.{slot_end.isoformat()}"
            f"&select=id&limit=1")
        if conflicts:
            raise HTTPException(409, "Time slot no longer available")

        # Find or create contact
        contact_id = None
        if req.email:
            existing = await _sb(client,
                f"/contacts?business_id=eq.{biz_id}&email=eq.{req.email}&limit=1&select=id")
            if existing:
                contact_id = existing[0]["id"]

        if not contact_id:
            new_contact = await _sb_post(client, "/contacts", {
                "business_id": biz_id,
                "name": req.name.strip(),
                "email": req.email or None,
                "phone": req.phone or None,
                "status": "lead",
                "source": "booking_page",
            })
            if new_contact and isinstance(new_contact, list):
                contact_id = new_contact[0]["id"]

        # Create session
        session_title = f"{req.session_type.replace('_', ' ').title()} with {req.name}"
        new_session = await _sb_post(client, "/sessions", {
            "business_id": biz_id,
            "contact_id": contact_id,
            "title": session_title,
            "session_type": req.session_type,
            "status": "scheduled",
            "scheduled_for": scheduled.isoformat(),
            "duration_minutes": duration,
            "notes": req.message or None,
        })
        session_id = new_session[0]["id"] if (new_session and isinstance(new_session, list)) else None

        # Log event
        await _sb_post(client, "/events", {
            "business_id": biz_id,
            "contact_id": contact_id,
            "event_type": "booking_created",
            "data": {"session_id": session_id, "session_type": req.session_type, "source": "public_booking_page"},
            "source": "booking_page",
        })

        practitioner = (biz.get("settings") or {}).get("practitioner_name", biz.get("name", ""))
        return {
            "success": True,
            "session_id": session_id,
            "contact_id": contact_id,
            "message": f"You're booked! {req.session_type.replace('_', ' ').title()} with {practitioner} on {req.date} at {req.time}.",
        }


@router.get("/public/booking/{slug}")
async def booking_page_html(slug: str):
    """Return the public booking page HTML."""
    if not _check_rate(f"booking-{slug}"):
        raise HTTPException(429, "Rate limit exceeded")

    async with httpx.AsyncClient() as client:
        sites = await _sb(client,
            f"/business_sites?slug=eq.{slug}&limit=1&select=business_id,site_config")
        if not sites:
            raise HTTPException(404, "Business not found")
        biz_id = sites[0]["business_id"]

        biz_rows = await _sb(client, f"/businesses?id=eq.{biz_id}&select=name,type,settings&limit=1")
        if not biz_rows:
            raise HTTPException(404, "Business not found")
        biz = biz_rows[0]
        booking = (biz.get("settings") or {}).get("booking") or {}
        if not booking.get("enabled"):
            raise HTTPException(404, "Booking not enabled")

        # Pass 3: Smart Sites flag-gate. v1 booking page is intentionally
        # minimal — Smart Sites v2 will inline the slot picker.
        if _use_smart_sites(sites[0]):
            smart_html = await _try_render_smart_site(biz_id, "booking")
            if smart_html:
                return HTMLResponse(content=smart_html, media_type="text/html",
                                    headers={"X-Solutionist-Source": "smart-sites"})

        brand = (biz.get("settings") or {}).get("brand_kit") or {}
        colors = brand.get("colors") or _palette_for(biz.get("type", "general"))
        practitioner = (biz.get("settings") or {}).get("practitioner_name", biz.get("name", ""))
        message = booking.get("message", "Pick a time that works for you.")
        biz_name = biz.get("name", "")
        primary = colors.get("primary") or colors.get("accent", "#333")
        bg = colors.get("background", "#faf8f5")

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Book with {practitioner} — {biz_name}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:'Inter',sans-serif;background:{bg};color:#1a1a2e;min-height:100vh;display:flex;justify-content:center;padding:40px 20px;}}
.container{{max-width:480px;width:100%;}}
h1{{font-size:1.6em;font-weight:700;margin-bottom:4px;}}
.sub{{color:#666;font-size:0.9em;margin-bottom:24px;line-height:1.5;}}
.msg{{padding:16px;background:rgba(0,0,0,0.03);border-radius:10px;margin-bottom:24px;font-style:italic;color:#555;line-height:1.5;}}
#slots{{margin-bottom:24px;}}
.day-header{{font-weight:600;font-size:0.85em;color:#888;text-transform:uppercase;letter-spacing:1px;margin:16px 0 8px;}}
.time-grid{{display:flex;flex-wrap:wrap;gap:8px;}}
.time-btn{{padding:8px 16px;border:1.5px solid {primary}40;border-radius:8px;background:#fff;color:{primary};font-weight:600;cursor:pointer;font-size:0.85em;transition:all 0.15s;}}
.time-btn:hover,.time-btn.sel{{background:{primary};color:#fff;border-color:{primary};}}
#form{{display:none;padding:20px;background:#fff;border:1px solid #e8e4dd;border-radius:12px;}}
.field{{margin-bottom:14px;}}
.field label{{display:block;font-size:0.75em;font-weight:600;text-transform:uppercase;letter-spacing:1px;color:#888;margin-bottom:4px;}}
.field input,.field select,.field textarea{{width:100%;padding:10px 12px;border:1px solid #ddd;border-radius:6px;font-size:0.9em;font-family:inherit;}}
.field textarea{{resize:vertical;min-height:60px;}}
.submit-btn{{width:100%;padding:12px;background:{primary};color:#fff;border:none;border-radius:8px;font-weight:700;font-size:1em;cursor:pointer;margin-top:8px;}}
.submit-btn:disabled{{opacity:0.5;cursor:default;}}
#confirm{{display:none;text-align:center;padding:40px 20px;}}
#confirm h2{{color:{primary};margin-bottom:8px;}}
.loading{{color:#888;font-style:italic;padding:20px;text-align:center;}}
</style>
</head>
<body>
<div class="container">
<h1>Book with {practitioner}</h1>
<p class="sub">{biz_name}</p>
<div class="msg">{message}</div>
<div id="slots"><div class="loading">Loading available times…</div></div>
<div id="form">
<div class="field"><label>Name</label><input id="f-name" required></div>
<div class="field"><label>Email</label><input id="f-email" type="email"></div>
<div class="field"><label>Session Type</label><select id="f-type"></select></div>
<div class="field"><label>Message (optional)</label><textarea id="f-msg"></textarea></div>
<button class="submit-btn" id="book-btn" onclick="submitBooking()">Book Now</button>
</div>
<div id="confirm"><h2>✓ You're booked!</h2><p id="confirm-msg"></p></div>
</div>
<script>
const BASE='';
let selectedDate='',selectedTime='';
async function load(){{
  try{{
    const r=await fetch(BASE+'/public/booking/{slug}/slots');
    const d=await r.json();
    const c=document.getElementById('slots');
    if(!d.slots||d.slots.length===0){{c.innerHTML='<p>No available times right now. Please check back later.</p>';return;}}
    let h='';
    d.slots.forEach(day=>{{
      const dt=new Date(day.date+'T00:00:00');
      h+='<div class="day-header">'+dt.toLocaleDateString(undefined,{{weekday:'long',month:'short',day:'numeric'}})+'</div>';
      h+='<div class="time-grid">';
      day.times.forEach(t=>{{h+='<button class="time-btn" onclick="pick(\\''+day.date+'\\',\\''+t+'\\',this)">'+t+'</button>';}});
      h+='</div>';
    }});
    c.innerHTML=h;
    const sel=document.getElementById('f-type');
    (d.session_types||[]).forEach(t=>{{const o=document.createElement('option');o.value=t;o.textContent=t.replace(/_/g,' ');sel.appendChild(o);}});
  }}catch(e){{document.getElementById('slots').innerHTML='<p>Could not load times.</p>';}}
}}
function pick(date,time,btn){{
  selectedDate=date;selectedTime=time;
  document.querySelectorAll('.time-btn').forEach(b=>b.classList.remove('sel'));
  btn.classList.add('sel');
  document.getElementById('form').style.display='block';
  document.getElementById('form').scrollIntoView({{behavior:'smooth'}});
}}
async function submitBooking(){{
  const btn=document.getElementById('book-btn');btn.disabled=true;btn.textContent='Booking…';
  try{{
    const r=await fetch(BASE+'/public/booking/{slug}/submit',{{
      method:'POST',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{
        name:document.getElementById('f-name').value,
        email:document.getElementById('f-email').value,
        session_type:document.getElementById('f-type').value,
        date:selectedDate,time:selectedTime,
        message:document.getElementById('f-msg').value||null,
      }})
    }});
    const d=await r.json();
    if(d.success){{
      document.getElementById('slots').style.display='none';
      document.getElementById('form').style.display='none';
      document.getElementById('confirm').style.display='block';
      document.getElementById('confirm-msg').textContent=d.message;
    }}else{{btn.disabled=false;btn.textContent='Book Now';alert(d.detail||'Booking failed');}}
  }}catch(e){{btn.disabled=false;btn.textContent='Book Now';alert('Booking failed');}}
}}
load();
</script>
</body>
</html>"""
        # Pass 3: legacy booking page also gets favicons + OG tags now.
        html = _inject_brand_meta(html, biz_id)
        return HTMLResponse(content=html)


@router.get("/public/health")
async def public_health():
    return {
        "status": "ok",
        "supabase_configured": bool(_supabase_url()),
        "rate_limit_per_min": RATE_LIMIT_PER_MIN,
        "palettes": list(TYPE_PALETTES.keys()),
        "base_domains": BASE_DOMAINS,
    }


# ═══════════════════════════════════════════════════════════════════════
# SUBDOMAIN ROUTING — Root domain + catch-all
# ═══════════════════════════════════════════════════════════════════════
# MUST be registered LAST so they don't shadow API routes.
# They only fire when the Host header is a mysolutionist.app subdomain.
# API calls from kmj-intake-server-production.up.railway.app pass through
# because extract_slug_from_host returns None → 404 → FastAPI continues.

MARKETING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>The Solutionist System — AI-Powered Operating System for Your Business</title>
<meta name="description" content="An AI-powered operating system that runs your contacts, sessions, proposals, payments, and website — so you can focus on the people you serve.">
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@300;400;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box;}
body{font-family:'Inter',sans-serif;background:#0d0d12;color:#E8E4DD;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:40px 24px;}
.wrap{max-width:600px;text-align:center;}
.badge{display:inline-block;padding:6px 16px;font-size:10px;font-weight:700;letter-spacing:3px;text-transform:uppercase;color:#C8973E;border:1px solid rgba(200,151,62,0.3);border-radius:99px;margin-bottom:24px;}
h1{font-family:'Cormorant Garamond',Georgia,serif;font-size:3em;font-weight:300;line-height:1.1;margin-bottom:16px;letter-spacing:-0.5px;}
h1 span{color:#C8973E;}
p{font-size:1.05em;color:#8B8880;line-height:1.7;margin-bottom:32px;}
.cta{display:inline-block;padding:14px 32px;font-size:14px;font-weight:700;color:#0C1120;background:linear-gradient(135deg,#C8973E,#B8872E);border:none;border-radius:10px;text-decoration:none;box-shadow:0 4px 20px rgba(200,151,62,0.3);transition:transform 0.15s;}
.cta:hover{transform:translateY(-2px);}
.footer{margin-top:60px;font-size:11px;color:#4A4F5E;}
</style>
</head>
<body>
<div class="wrap">
<div class="badge">The Solutionist System</div>
<h1>An AI-powered <span>operating system</span> for your business</h1>
<p>Contacts, sessions, proposals, payments, website, and a Chief of Staff that manages it all — built for pastors, coaches, consultants, and practitioners who serve people.</p>
<a href="https://kmjcreate.com" class="cta">Get Started</a>
<div class="footer">Built by KMJ Creative Solutions</div>
</div>
</body>
</html>"""


async def _augment_html(client: httpx.AsyncClient, biz_id: Optional[str], slug: str, html: str) -> str:
    """Inject canonical + live products + gallery into served HTML."""
    products: List[Dict[str, Any]] = []
    gallery: List[Dict[str, Any]] = []
    brand_color = "#D4AF37"
    biz_settings: Dict[str, Any] = {}
    if biz_id:
        prod_rows, biz_rows = await asyncio.gather(
            _sb(client,
                f"/products?business_id=eq.{biz_id}&status=eq.active&display_on_website=eq.true"
                f"&order=sort_order.asc,created_at.desc&select=*&limit=100"),
            _sb(client, f"/businesses?id=eq.{biz_id}&select=settings&limit=1"),
        )
        products = prod_rows or []
        if biz_rows:
            biz_settings = (biz_rows[0].get("settings") or {})
            lib = biz_settings.get("media_library") or {}
            gallery = lib.get("gallery") or []
            bk = biz_settings.get("brand_kit") or {}
            bc = (bk.get("primary_color") or "").strip() if isinstance(bk, dict) else ""
            if bc.startswith("#") and (len(bc) == 7 or len(bc) == 4):
                brand_color = bc
    html = _inject_canonical(html, slug)
    # Pass 3: activate the Pass 2.5a `_brand_head_meta_tags` helper for
    # legacy sites too — favicons + OG + Twitter Cards now render for
    # everyone, not just Smart Sites users.
    html = _inject_brand_meta(html, biz_id)
    html = _inject_dynamic_sections(
        html,
        _render_products_section(products, slug, brand_color, biz_settings),
        _render_gallery_section(gallery),
    )
    return html


async def _try_render_smart_site(business_id: str, page_type: str, **opts) -> Optional[str]:
    """Pass 3: attempt Smart Sites render. Returns HTML on success, None on
    any failure so the caller can fall through to legacy. NEVER raises."""
    try:
        from smart_sites import render_smart_site_page
        return render_smart_site_page(business_id, page_type, **opts)
    except Exception as e:
        logger.warning(f"[smart_sites] render failed for {business_id} {page_type}: {e}")
        return None


async def _serve_site_by_slug(slug: str) -> HTMLResponse:
    """Shared logic: look up site by slug and return HTML.
    Pass 3: when site_config.use_smart_sites is true, attempt Smart Sites
    render first. ANY failure falls through to legacy."""
    async with httpx.AsyncClient() as client:
        sites = await _sb(client,
            f"/business_sites?slug=eq.{slug}&order=updated_at.desc&limit=1"
            f"&select=html_content,business_id,site_config")
        if not sites:
            raise HTTPException(404, "Site not found")
        site = sites[0]
        biz_id = site.get("business_id")

        if _use_smart_sites(site) and biz_id:
            # Fetch products to pass into the home page renderer.
            products = await _sb(client,
                f"/products?business_id=eq.{biz_id}&status=eq.active&display_on_website=eq.true"
                f"&order=sort_order.asc,created_at.desc&select=*&limit=100") or []
            smart_html = await _try_render_smart_site(biz_id, "home", products=products)
            if smart_html:
                return HTMLResponse(content=smart_html, media_type="text/html",
                                    headers={"X-Solutionist-Source": "smart-sites"})
            # else: fall through to legacy

        if not site.get("html_content"):
            raise HTTPException(404, "Site not found")
        html = await _augment_html(client, biz_id, slug, site["html_content"])
        return HTMLResponse(content=html, media_type="text/html")


async def _serve_site_by_custom_domain(domain: str) -> HTMLResponse:
    """Look up a site by its custom domain.
    Pass 3: same flag check as _serve_site_by_slug."""
    async with httpx.AsyncClient() as client:
        sites = await _sb(client,
            f"/business_sites?site_config->>custom_domain=eq.{domain}"
            f"&order=updated_at.desc&limit=1"
            f"&select=html_content,slug,business_id,site_config")
        if not sites:
            return None  # type: ignore
        site = sites[0]
        biz_id = site.get("business_id")
        slug = site.get("slug") or domain

        if _use_smart_sites(site) and biz_id:
            products = await _sb(client,
                f"/products?business_id=eq.{biz_id}&status=eq.active&display_on_website=eq.true"
                f"&order=sort_order.asc,created_at.desc&select=*&limit=100") or []
            smart_html = await _try_render_smart_site(biz_id, "home", products=products)
            if smart_html:
                return HTMLResponse(content=smart_html, media_type="text/html",
                                    headers={"X-Solutionist-Source": "smart-sites"})

        if not site.get("html_content"):
            return None  # type: ignore
        html = await _augment_html(client, biz_id, slug, site["html_content"])
        return HTMLResponse(content=html, media_type="text/html")


@router.get("/", include_in_schema=False)
async def subdomain_root(request: Request):
    """Handle subdomain requests at the root path.

    When the request arrives on the Railway API host, raise 404 so it
    falls through to whatever real route might be registered (e.g. the
    `@app.get("/")` root defined in main.py). Do NOT serve the marketing
    page from the API domain — it was shadowing every API endpoint.
    """
    host = (request.headers.get("host") or "").split(":")[0].lower()

    slug = extract_slug_from_host(request)
    if slug:
        if not _check_rate(slug):
            raise HTTPException(429, "Rate limit exceeded")
        return await _serve_site_by_slug(slug)

    # Custom domain lookup (skip for API/local hosts)
    if not _is_api_host(host):
        is_known_base = any(host == base or host.endswith(f".{base}") for base in BASE_DOMAINS)
        if not is_known_base and "." in host:
            result = await _serve_site_by_custom_domain(host)
            if result:
                return result

    # API domain: let other routers / the app root handler take over.
    if _is_api_host(host):
        raise HTTPException(404, "Not found")

    # Known base domain with no subdomain — serve the marketing page.
    return HTMLResponse(content=MARKETING_HTML, media_type="text/html")


@router.get("/{path:path}", include_in_schema=False)
async def subdomain_catch_all(request: Request, path: str):
    """Catch-all for subdomain requests. Serves the practitioner's site
    regardless of path (SPA routing). API-host requests MUST 404 here so
    they fall through to the real API routers — otherwise this handler
    shadows /email/health, /agents/*, everything."""
    host = (request.headers.get("host") or "").split(":")[0].lower()

    # API / local dev: bail immediately. Don't even look at the body.
    if _is_api_host(host):
        raise HTTPException(404, "Not found")

    slug = extract_slug_from_host(request)
    if slug:
        if not _check_rate(slug):
            raise HTTPException(429, "Rate limit exceeded")
        return await _serve_site_by_slug(slug)

    # Custom domain check
    is_known_base = any(host == base or host.endswith(f".{base}") for base in BASE_DOMAINS)
    if not is_known_base and "." in host:
        result = await _serve_site_by_custom_domain(host)
        if result:
            return result

    # Not a subdomain/custom domain — 404
    raise HTTPException(404, "Not found")
