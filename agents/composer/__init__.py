"""Composer Agent — Pass 4.0f spike.

Selects component-library variants from enriched briefs. The spike
implementation handles ONE section (Cathedral Hero) and one module
(Cinematic Authority); if validated, the architecture extends to
About / Services / Gallery / Testimonials / CTA / Footer and to
other modules (Pulpit, Atelier, Studio Brut, etc.).

Modules:
  cathedral_hero_composer  Sonnet 4.5 picks 1 of 11 hero variants +
                           3 treatment dimensions + writes content,
                           outputs typed JSON validated against
                           CathedralHeroComposition.
  router                   FastAPI router for the diagnostic endpoint
                           POST /composer/_diag/compose_hero.
                           Mounted into the FastAPI app only when the
                           spike branch ships to production (not
                           during the spike itself — direct Python
                           invocation is used for Phase 3 testing).
"""
