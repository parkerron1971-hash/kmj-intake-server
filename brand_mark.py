"""
brand_mark.py — the owner's logo, resolved once, for everyone.

WHY THIS EXISTS (2026-08-09, Kevin: "my logo for the business doesn't get
on the site"). The word "logo" appeared ZERO times in builder_v2.py,
canvas.py and atelier.py — every module that authors a page. The builders'
entire image inventory is `site_config.slots` plus `ctx["gallery"]`, and
the brand mark lives in neither: it is uploaded to
`businesses.settings.brand_kit` by the Brand Kit surface.

So the chain was broken in the middle, and in the most misleading way:

  · the DIRECTOR could see it — spec_author._brand_mark_urls sends the
    mark to the spec author as a vision block, and the prompt even orders
    "when an image labeled THE BRAND MARK is present, your palette section
    MUST name the mark's actual colors"
  · so the spec confidently referenced a mark in the header
  · the BUILDER was never handed the url, and its only images were
    portfolio pieces
  · so it put a 1200x675 gallery image in a 59x34 header slot

On kmjcreate.com that shipped as the brand: a campaign flyer reading
"UPGRADE", squashed to thumbnail size, with alt="KMJ Creative Solutions
mark". Same shape as the moves bug — one half of the system knows a thing
the other half has never been told.

The resolver below is lifted from spec_author._brand_mark_urls, which was
already correct, and promoted so the authors share it. Note the real
storage shape varies: KMJ's kit carries `assets.primary` AND `logo_url`,
older kits carry `logos.primary`. All three are checked.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("brand_mark")

MAX_MARKS = 2


def _settings(ctx: Optional[Dict[str, Any]], business_id: str) -> Dict[str, Any]:
    """ctx first (already loaded), service fetch as the fallback."""
    settings: Dict[str, Any] = {}
    try:
        settings = (((ctx or {}).get("bundle") or {}).get("business") or {}
                    ).get("settings") or {}
    except Exception:
        settings = {}
    if not settings:
        try:
            settings = ((ctx or {}).get("business") or {}).get("settings") or {}
        except Exception:
            settings = {}
    if not settings and business_id:
        try:
            import sb_clients
            rows = sb_clients.sb_get_as_service(
                f"/businesses?id=eq.{business_id}&select=settings&limit=1") or []
            settings = (rows[0].get("settings") if rows else None) or {}
        except Exception as e:
            logger.info(f"[brand-mark] settings fetch skipped: {e}")
            return {}
    return settings if isinstance(settings, dict) else {}


def mark_urls(ctx: Optional[Dict[str, Any]] = None,
              business_id: str = "") -> List[str]:
    """Every https brand-mark url we know about, best first, max 2.

    Checked in order: brand_kit.logos.primary, brand_kit.logo_url,
    brand_kit.assets.primary, settings.site_images.logo, then any other
    named logo in the kit. https-only — the page is served over TLS and a
    mixed-content mark is a broken mark."""
    settings = _settings(ctx, business_id)
    bk = settings.get("brand_kit")
    bk = bk if isinstance(bk, dict) else {}
    logos = bk.get("logos") if isinstance(bk.get("logos"), dict) else {}
    assets = bk.get("assets") if isinstance(bk.get("assets"), dict) else {}
    si = (settings.get("site_images")
          if isinstance(settings.get("site_images"), dict) else {})

    candidates = [logos.get("primary"), bk.get("logo_url"),
                  assets.get("primary"), si.get("logo")]
    candidates += [v for k, v in sorted(logos.items()) if k != "primary"]
    candidates += [v for k, v in sorted(assets.items()) if k != "primary"]

    out: List[str] = []
    for v in candidates:
        if isinstance(v, str) and v.strip().lower().startswith("https://"):
            u = v.strip()
            if u not in out:
                out.append(u)
        if len(out) >= MAX_MARKS:
            break
    return out


def mark_url(ctx: Optional[Dict[str, Any]] = None,
             business_id: str = "") -> Optional[str]:
    """The one mark to put in the header, or None."""
    urls = mark_urls(ctx, business_id)
    return urls[0] if urls else None


def real_data_block(ctx: Optional[Dict[str, Any]] = None,
                    business_id: str = "", business_name: str = "") -> str:
    """The line that goes into an author's real-data inventory.

    Stated as an INSTRUCTION, not a fact, because the failure mode was
    never "the builder chose badly" — it was "the builder had no logo and
    used the only images it had." Naming the url is necessary; saying it
    is THE mark and belongs in the header is what stops a portfolio piece
    being drafted into the role."""
    url = mark_url(ctx, business_id)
    name = (business_name or "").strip()
    if not url:
        # Honest absence. Without this the author invents a mark from the
        # gallery, which is exactly what shipped.
        return ("BRAND MARK: none uploaded. Do NOT substitute a portfolio "
                "or gallery image as the logo — set the wordmark in type "
                f"instead{(' (' + name + ')') if name else ''}.")
    return (
        "BRAND MARK (the owner's real logo — THE identity artifact):\n"
        f"- {url}\n"
        "  This is the logo. It belongs in the header/nav as the brand "
        "mark, and in the footer if the design calls for one. NEVER use a "
        "gallery or portfolio image as the logo. Give it its own box and "
        "let it keep its aspect ratio (object-fit: contain) — a mark "
        "squashed into a fixed 59x34 is a broken mark. If the design is "
        "better served by a typographic wordmark, set it in type and use "
        "this file nowhere rather than distorting it.")
