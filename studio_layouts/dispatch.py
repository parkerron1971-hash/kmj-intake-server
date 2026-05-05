"""Layout dispatcher. Single entry point: render_layout(layout_id, **kwargs).

External callers (e.g., studio_preview.py and Session 3's smart_sites
integration) should always import from here rather than from individual
layout modules. This keeps the layout registry and validation in one
place.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

from studio_layouts import (
    authority,
    celebration,
    clean_launch,
    community_hub,
    empire_platform,
    experience,
    gallery,
    magazine,
    movement,
    story_arc,
    studio_portfolio,
    throne,
)


LAYOUT_RENDERERS: Dict[str, Callable[..., str]] = {
    "magazine":         magazine.render,
    "throne":           throne.render,
    "community-hub":    community_hub.render,
    "gallery":          gallery.render,
    "authority":        authority.render,
    "story-arc":        story_arc.render,
    "movement":         movement.render,
    "experience":       experience.render,
    "clean-launch":     clean_launch.render,
    "celebration":      celebration.render,
    "studio-portfolio": studio_portfolio.render,
    "empire-platform":  empire_platform.render,
}


def render_layout(layout_id: str, **kwargs: Any) -> str:
    """Dispatch to the appropriate layout renderer.

    Required kwargs:
      - business_data: dict (with at least 'name')
      - design_system: from studio_design_system.build_design_system
      - composite:     from studio_composite.build_composite
      - sections_config: dict
      - bundle:        brand_engine bundle dict

    Optional kwargs:
      - head_meta_extra: str (favicon/social card html)
      - products:        list[dict]

    Returns: complete HTML string.
    """
    renderer = LAYOUT_RENDERERS.get(layout_id)
    if not renderer:
        raise ValueError(
            f"Unknown layout: {layout_id!r}. "
            f"Known: {sorted(LAYOUT_RENDERERS.keys())}"
        )
    return renderer(**kwargs)


def all_layouts() -> List[str]:
    """Return all 12 layout IDs in stable insertion order."""
    return list(LAYOUT_RENDERERS.keys())
