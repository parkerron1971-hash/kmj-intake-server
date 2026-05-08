# Pass 3.8e (Reactivity & Motion Layer) — Return Point

## Purpose

Pass 3.8d ships bespoke Builder HTML per business. Output is structurally
correct but currently static. Pass 3.8e adds an interaction + motion layer
that gets injected into Builder output **at validation time** (alongside
the Pass 3.7c motion modules already wired). No Builder regeneration.
Sites become reactive on the next page load.

Three categories injected:
1. **Micro-interactions** — hover lifts, link underline reveals, button
   press states, image zoom on hover. Gated to hover-capable devices via
   `@media (hover: hover)`.
2. **Scroll behaviors** — fade-up reveals via IntersectionObserver,
   subtle parallax, smooth anchor scrolling, auto-built sticky CTA bar.
3. **Strand-aware gradients** — distinct gradient character per dominant
   strand (luxury → ceremonial gold radial, brutalist → hard contrast,
   editorial → asymmetric, etc.). Read from `design_brief.blendRatio`.

Every animation respects `prefers-reduced-motion`. Touch devices skip
hover lifts via `@media (hover: none)`.

## Pre-pass safety

- Branch: `pass-3-8e` (off `main` at `ccc4ae6`)
- Safety tag: `pre-pass-3-8e-20260507-211849` (pushed to origin)
- Backup: `studio_html_validator.py.pre-3-8e.bak`

## Files added

- `studio_reactivity/__init__.py` — package marker
- `studio_reactivity/micro_interactions.py` — `render_styles()`
- `studio_reactivity/scroll_behaviors.py` — `render_styles()`, `render_script()`
- `studio_reactivity/strand_gradients.py` — 10 strands × gradient character,
  `render_styles_for_strand()`, `parse_dominant_strand()`,
  `parse_palette_from_brief()`
- `studio_reactivity/inject.py` — orchestrator: `inject_reactivity(html, brief)`

## Files modified

- `studio_html_validator.py`
  - `inject_motion_modules(html, scheme, brief=None)` — extended signature.
    After existing Pass 3.7c motion injection, calls
    `studio_reactivity.inject.inject_reactivity(html, brief)`.
- `studio_builder_agent.py` — `build_html` passes `brief` through.
- `smart_sites.py` — `_try_serve_builder_html` reads `design_brief` from
  `site_config` and passes it through.

## Out of scope (deferred)

- Custom cursor effects (only default pointer)
- Audio/video reactivity
- Page transitions between routes
- Custom JS interactions per archetype

## Rollback

```bash
git checkout main
git reset --hard pre-pass-3-8e-20260507-211849
```
