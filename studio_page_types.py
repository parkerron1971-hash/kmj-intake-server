"""Pass 3.8g — multi-page architecture page types.

Each PAGE_TYPE entry tells the system:
  - what URL the page lives at (slug)
  - what the page is for (role + brief_focus)
  - what sections typically appear
  - whether the site nav links to it

The Brief Expander reads brief_focus + typical_sections to produce a
page-specific brief variant. The Multi-page Builder uses has_nav to
decide which entries appear in the generated <nav>.

The page set itself is stored on a business as site_config.site_pages
(list of page_id strings). Two helper getters return the canonical
default sets for "multi-page" and "landing-page" site_types.
"""
from __future__ import annotations

from typing import Optional, TypedDict


class PageType(TypedDict):
    id: str
    name: str
    slug: str
    role: str
    brief_focus: str
    typical_sections: list
    has_nav: bool
    has_hero: bool


PAGE_TYPES: dict = {
    "home": {
        "id": "home",
        "name": "Home",
        "slug": "/",
        "role": "First impression. Brand thesis. Top of funnel.",
        "brief_focus": (
            "Tension statement, philosophy, primary offering, social proof, CTA."
        ),
        "typical_sections": [
            "hero",
            "stats_band",
            "philosophy",
            "primary_offering",
            "social_proof",
            "cta",
        ],
        "has_nav": True,
        "has_hero": True,
    },
    "about": {
        "id": "about",
        "name": "About",
        "slug": "/about",
        "role": "Practitioner story. Trust. Voice.",
        "brief_focus": (
            "Practitioner background, story, philosophy expanded, voice "
            "samples in narrative form."
        ),
        "typical_sections": [
            "hero",
            "practitioner_story",
            "philosophy_expanded",
            "method",
            "values",
            "cta",
        ],
        "has_nav": True,
        "has_hero": True,
    },
    "services": {
        "id": "services",
        "name": "Services",
        "slug": "/services",
        "role": "What's offered. How. For whom. Pricing.",
        "brief_focus": (
            "Offerings detailed, pricing if shown, audience descriptions, "
            "methodology."
        ),
        "typical_sections": [
            "hero",
            "offerings_detailed",
            "audience",
            "methodology",
            "pricing",
            "cta",
        ],
        "has_nav": True,
        "has_hero": True,
    },
    "contact": {
        "id": "contact",
        "name": "Contact",
        "slug": "/contact",
        "role": "Direct invitation. Conversion.",
        "brief_focus": (
            "Direct invitation, low friction, contact methods."
        ),
        "typical_sections": [
            "hero",
            "invitation",
            "form_or_email",
            "alternatives",
            "footer_cta",
        ],
        "has_nav": True,
        "has_hero": False,
    },
}


def get_page_type(page_id: str) -> Optional[dict]:
    """Look up a page type. Returns None for unknown ids (caller decides
    whether to skip or fall back)."""
    return PAGE_TYPES.get(page_id)


def default_page_set() -> list:
    """Default 4-page configuration — Home, About, Services, Contact."""
    return ["home", "about", "services", "contact"]


def landing_page_set() -> list:
    """Single-page configuration — just home."""
    return ["home"]


def slug_to_page_id(path: str) -> str:
    """Map a request path to a page_id. Falls back to 'home'.

    Accepts both the canonical PAGE_TYPES slug and a /<page_id> form so
    /about and /about both resolve. Anything unknown → home.
    """
    if not path:
        return "home"
    p = path.strip()
    if p == "" or p == "/":
        return "home"
    # Strip query/fragment if a caller passes a full URL portion
    p = p.split("?", 1)[0].split("#", 1)[0]
    # Normalize trailing slash
    if p.endswith("/") and len(p) > 1:
        p = p.rstrip("/")
    if not p.startswith("/"):
        p = "/" + p
    for pid, ptype in PAGE_TYPES.items():
        if ptype["slug"] == p or p == f"/{pid}":
            return pid
    return "home"
