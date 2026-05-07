"""RenderContext — unified pre-processed context that archetype renderers consume.

Built once per render call from brief + bundle + content + scheme.
Renderers don't reach back into raw data; they consume RenderContext.
"""
from __future__ import annotations
from typing import TypedDict, Optional


class RenderContext(TypedDict, total=False):
    # Identity
    business_id: str
    business_name: str
    business_slug: str
    business_type: str

    # Brief content
    concept_name: str
    tagline: str
    tension_statement: str
    philosophy: str
    copy_voice: str
    spatial_direction: str
    industry: str
    mood: str

    # Visual system
    palette: dict
    typography: dict
    accent_config: dict
    color_discipline: dict

    # Structure
    sections: list
    layout_archetype: str
    sub_strand_id: Optional[str]

    # Bundle data
    practitioner_name: Optional[str]
    practitioner_bio: Optional[str]
    practitioner_photo_url: Optional[str]
    about_me: Optional[str]
    about_business: Optional[str]
    products: list
    testimonials: list
    gallery_images: list
    resources: list
    contact_email: Optional[str]
    social_links: dict

    # Decoration scheme (Pass 3.7c override layer)
    scheme: Optional[dict]

    # Motion flags (resolved from scheme + brief)
    enable_ghost_numbers: bool
    enable_marquee_strips: bool
    enable_magnetic_buttons: bool
    enable_statement_bars: bool
    marquee_text: Optional[str]
    statement_bar_quotes: list


def build_context(
    business_id: str,
    business_data: dict,
    bundle: dict,
    brief: dict,
    scheme,
    products: list,
    testimonials: list,
    gallery: list,
    resources: list,
):
    """Pre-process all inputs into a unified RenderContext."""
    bundle = bundle or {}
    business = bundle.get("business") or {}
    practitioner = bundle.get("practitioner") or {}
    intel = bundle.get("practitioner_intelligence") or {}
    brief = brief or {}

    # Resolve palette by role (brief.palette is a list of dicts with hex/role)
    palette_by_role = {}
    for c in (brief.get("palette") or []):
        if not isinstance(c, dict):
            continue
        role = c.get("role", "")
        hex_val = c.get("hex")
        if role and hex_val:
            palette_by_role.setdefault(role, hex_val)  # first wins

    # Sensible defaults if brief palette is sparse
    palette_by_role.setdefault("background", "#0a0a0a")
    palette_by_role.setdefault("text", "#f4f4f4")
    palette_by_role.setdefault("accent", "#c9a84c")
    palette_by_role.setdefault("secondary", palette_by_role["background"])
    palette_by_role.setdefault("primary", palette_by_role["accent"])
    palette_by_role.setdefault("highlight", palette_by_role["text"])

    # Resolve motion flags from scheme (brief doesn't carry them)
    motion = (scheme or {}).get("motion_richness") or {}
    enable_ghost = bool(motion.get("enable_ghost_numbers", False))
    enable_marquee = bool(motion.get("enable_marquee_strips", False))
    enable_magnetic = bool(motion.get("enable_magnetic_buttons", False))
    enable_statement = bool(motion.get("enable_statement_bars", False))

    # Slug from business_data, fallback to bundle
    slug = (
        (business_data or {}).get("slug")
        or business.get("slug")
        or ""
    )

    # Contact email from business_data settings, falls back to footer.contact_email
    settings = (business_data or {}).get("settings") or {}
    contact_email = (
        settings.get("contact_email")
        or (bundle.get("footer") or {}).get("contact_email")
    )

    # Practitioner photo — check practitioner row + brand_kit for any usable
    # avatar URL. Returns None when no photo is available so the renderer
    # can hide the photo column instead of showing an empty placeholder.
    brand_kit = settings.get("brand_kit") or {}
    photo_url = (
        practitioner.get("photo_url")
        or practitioner.get("avatar_url")
        or practitioner.get("headshot_url")
        or brand_kit.get("practitioner_photo")
        or brand_kit.get("headshot_url")
        or None
    )

    return {
        "business_id": business_id,
        "business_name": business.get("name") or "Welcome",
        "business_slug": slug,
        "business_type": business.get("type") or "",
        "concept_name": brief.get("conceptName") or "",
        "tagline": brief.get("tagline") or "",
        "tension_statement": brief.get("tensionStatement") or "",
        "philosophy": brief.get("philosophy") or "",
        "copy_voice": brief.get("copyVoice") or "",
        "spatial_direction": brief.get("spatialDirection") or "",
        "industry": brief.get("industry") or business.get("type") or "",
        "mood": brief.get("mood") or "",
        "palette": palette_by_role,
        "typography": brief.get("typography") or {},
        "accent_config": brief.get("accentConfig") or {},
        "color_discipline": brief.get("colorDiscipline") or {},
        "sections": brief.get("sections") or [],
        "layout_archetype": brief.get("layoutArchetype") or "split",
        "sub_strand_id": brief.get("subStrandId"),
        "practitioner_name": practitioner.get("display_name") or practitioner.get("full_legal_name"),
        "practitioner_bio": intel.get("about_me"),
        "practitioner_photo_url": photo_url,
        "about_me": intel.get("about_me"),
        "about_business": intel.get("about_business"),
        "products": products or [],
        "testimonials": testimonials or [],
        "gallery_images": gallery or [],
        "resources": resources or [],
        "contact_email": contact_email,
        "social_links": (settings.get("social_links") or {}) if isinstance(settings, dict) else {},
        "scheme": scheme,
        "enable_ghost_numbers": enable_ghost,
        "enable_marquee_strips": enable_marquee,
        "enable_magnetic_buttons": enable_magnetic,
        "enable_statement_bars": enable_statement,
        "marquee_text": (scheme or {}).get("marquee_text"),
        "statement_bar_quotes": (scheme or {}).get("statement_bar_quotes") or [],
    }
