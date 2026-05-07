"""Studio archetypes package — 6 layout concepts that consume DesignBriefs.

Each archetype is a complete page concept, not a layout variation:
  - split            — hero+services (default for service businesses)
  - editorial-scroll — single-column reading experience
  - showcase         — portfolio-first, large images
  - statement        — manifesto-scale typography, no image
  - immersive        — atmospheric backgrounds throughout
  - minimal-single   — radical condensation, 3-4 sections only

All renderers expose `render(context: RenderContext) -> str`.
"""
