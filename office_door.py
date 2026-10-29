"""office_door.py — a church's own door into the office app.

Kevin, 2026-10-28: "should we consider change up solutionist key access for
those that have a key so it doesn't look like the admin access point?", then
"yes build the church-branded office door". An office login (a seat, see
business_users_router) used to sign in on Solutionist's own page, the one
that sells a business owner a trial. A church's office now has its own door:

  lovecityc.com/office            the church's address (public_site's
                                  catch-all) sends it to the app's door
  <app>/office/<slug>             the app's sign-in in the church's colours,
                                  with its logo, saying "Office"

and every invite to a church's office opens there. The look is the member
app's (member_app_ui.palette): the church's base, its colour, its logo, so
the office and the member app read as one church.

Only what the church's public site already shows: its name, colours, logo.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional
from urllib.parse import quote

import sb_clients

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def _site_for(q: str) -> Optional[Dict[str, Any]]:
    """{business, site} for a church's live site, or None (not a church, no
    such site, or a site taken offline)."""
    import church_follow_up as cfu
    rows = sb_clients.sb_get_as_service(
        f"/business_sites?{q}&order=updated_at.desc&limit=1"
        f"&select=slug,business_id,site_config,business:businesses(id,name,type,settings)") or []
    if not rows or (rows[0].get("site_config") or {}).get("offline"):
        return None
    site = dict(rows[0])
    biz = site.pop("business", None)
    if not isinstance(biz, dict) or not biz.get("id") or not cfu.is_church(biz) or not site.get("slug"):
        return None
    return {"business": biz, "site": site}


def church_by_slug(slug: Any) -> Optional[Dict[str, Any]]:
    s = str(slug or "").strip().lower()
    return _site_for(f"slug=eq.{quote(s, safe='')}") if _SLUG.match(s) else None


def church_by_business(business_id: Any) -> Optional[Dict[str, Any]]:
    b = str(business_id or "").strip()
    return _site_for(f"business_id=eq.{quote(b, safe='')}") if b else None


def path_for(business_id: Any) -> Optional[str]:
    """The app path of a church's office door, '/office/<slug>', or None for
    a business that isn't a church (its invites keep the plain sign-in)."""
    found = church_by_business(business_id)
    return f"/office/{quote(found['site']['slug'], safe='')}" if found else None


def brand(found: Dict[str, Any]) -> Dict[str, Any]:
    """The door's look, the member app's: base, colour, logo, fonts."""
    import member_app_ui as ui
    import member_app_photos as photos
    import public_site
    from public_form_theme import resolve_theme
    biz, site = found["business"], found["site"]
    theme = resolve_theme(biz, site)
    pal = ui.palette(biz, theme)
    logo = theme.get("logo_url") or ""
    if not logo:
        word = photos.wordmark(site, light=pal["dark"])
        logo = f"{public_site._EMBED_ORIGIN}{word}" if word else ""
    return {
        "name": (biz.get("name") or "").strip() or "Your church",
        "slug": site["slug"],
        "logo_url": logo or None,
        "dark": bool(pal["dark"]),
        "bg": pal["bg"], "surface": pal["s1"], "surface2": pal["s2"], "line": pal["line"],
        "fg": pal["fg"], "fg2": pal["fg2"], "fg3": pal["fg3"],
        "accent": pal["accent"], "fill": pal["fill"], "on_fill": pal["on_fill"],
        "font_heading": theme.get("font_heading"), "font_body": theme.get("font_body"),
    }
