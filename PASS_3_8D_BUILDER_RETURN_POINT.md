# Pass 3.8d (Builder Agent) — Return Point

## Purpose

Pass 3.8c shipped deterministic archetype renderers that consume design briefs.
They produce competent but templated output — businesses with similar briefs
get visually similar layouts.

Pass 3.8d ships **LLM #3 — the Builder Agent**: a creative-director-tier
prompt that consumes the full DesignBrief + bundle + scheme + offerings and
generates a **complete bespoke HTML/CSS document** for one business at a time.
The generated HTML is persisted into `business_sites.site_config.generated_html`
and served on every request — zero AI calls per page load.

## Pre-pass safety

- Branch: `pass-3-8d-builder` (off `main` at `b826f1c`)
- Safety tag: `pre-pass-3-8d-builder-20260507-144110` (pushed to origin)
- Backups in place:
  - `public_site.py.pre-3-8d-builder.bak`
  - `smart_sites.py.pre-3-8d-builder.bak`

## Files added

- `studio_html_validator.py` — banned-pattern detection, markdown-fence
  stripping, motion-module injection, binary validate verdict.
- `studio_builder_agent.py` — Builder prompt construction, Claude Opus call
  via `studio_designer_agent._call_claude`, output extraction + validation.

## Files modified

- `public_site.py`
  - New endpoint: `POST /sites/{business_id}/generate-html` (60 s cooldown)
  - `/generate-design-recommendation` now auto-fires Builder after Brief
    Expander (non-fatal if Builder fails)
  - `/decoration-status` extended with `has_generated_html`,
    `html_generated_at`, `html_build_error`, `html_validation_errors`
- `smart_sites.py`
  - `render_smart_site_page()` extended with 4-layer fallback chain:
    1. Builder `generated_html` (with motion injection)
    2. Pass 3.8c archetype renderer (when brief has `layoutArchetype`)
    3. Existing Pass 3.7c Studio layout system (`_try_render_via_studio_layouts`)
    4. Legacy `_render_page` (existing safety net)

## Cooldown

60 s per business, in-memory `defaultdict(float)`. Resets on Railway redeploy
(matches Pass 3.7c / 3.8a / 3.8b).

## Out of scope (deferred)

- Frontend UI to surface `generated_html` status (Pass 3.8e)
- Per-page generation — Builder generates home page only in v1
- Editing generated HTML through MySite
- Versioning / history of generated HTML

## Rollback

```bash
git checkout main
git reset --hard pre-pass-3-8d-builder-20260507-144110
```
