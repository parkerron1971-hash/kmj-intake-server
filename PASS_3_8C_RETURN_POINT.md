# Pass 3.8c — Backend Return Point

Created: 2026-05-07 04:58 local
Tag: `pre-pass-3-8c-20260507-0458`
Branch: `pass-3-8c` (off `main` @ Pass 3.8b head)
Base: Pass 3.8b shipped (Brief Expander + auto-fire chain)

## Scope — 6 archetype renderers + debug preview endpoint

Pure rendering: no AI calls per visit. Each archetype takes a `RenderContext`
(pre-processed brief + bundle + content + scheme) and produces a complete HTML
page. Renderers are stateless pure functions — same input always gives the same
output.

NOT wired into live URLs in this pass — that's Pass 3.8d. Live URLs continue
rendering via Pass 3.7c Studio + 12-layout pipeline. The new debug preview
endpoint `/sites/{id}/preview-archetype/{archetype_id}` exposes the renderers
in isolation.

## New files

- `studio_render_context.py` — `RenderContext` TypedDict + `build_context()`
- `studio_archetypes/__init__.py`
- `studio_archetypes/_shared.py` — `safe()`, `base_html_shell()`, `base_styles()`, motion module wiring helpers
- `studio_archetypes/split.py` — Split (default for service businesses)
- `studio_archetypes/editorial_scroll.py` — Editorial Scroll (single-column reading)
- `studio_archetypes/showcase.py` — Showcase (portfolio-first, large images)
- `studio_archetypes/statement.py` — Statement (manifesto-scale typography)
- `studio_archetypes/immersive.py` — Immersive (cinematic gradient scenes)
- `studio_archetypes/minimal_single.py` — Minimal Single (radical condensation)
- `studio_archetypes/dispatch.py` — `render_archetype(archetype_id, context)`

## Modified

- `public_site.py`: `GET /sites/{id}/preview-archetype/{archetype_id}` returns
  HTML directly (no DB writes; preview only)

## Backwards compatibility

- No layout dispatch changes — existing `studio_layouts/dispatch.py` unchanged
- Live URLs unaffected
- Pass 3.7c motion modules reused via _shared.py wiring (no edits to motion modules)
- Defensive reads on optional content tables (testimonials/gallery_images/resources) — missing tables degrade silently

## Backups

- `public_site.py.pre-3-8c.bak`
- `studio_layouts.pre-3-8c.bak/` (all 12 layouts + sections + motion_modules)

## Rollback

```bash
git checkout main
git reset --hard pre-pass-3-8c-20260507-0458
git push --force-with-lease origin main
```
