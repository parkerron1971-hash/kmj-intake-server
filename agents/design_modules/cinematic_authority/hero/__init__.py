"""Cathedral Hero — Pass 4.0f spike.

Six-variant Hero section library. Each variant is one Python function
in variants/ returning an HTML <section> string. Treatments (color
emphasis, spacing density, emphasis weight) parameterize each variant
via CSS variable assignment, yielding 6 × 3 × 3 × 3 = 162 unique
structural combinations.

Public surface:
  types.py            Pydantic models for compositions + treatments
  primitives/         Shared rendering fragments (eyebrow, heading, ...)
  treatments/         Treatment-to-CSS-variable translators
  variants/           (Phase 2) one renderer per variant
  render_cathedral_hero.py  (Phase 4) top-level entry point
"""
