# Pass 3.7c — Backend Return Point

Created: 2026-05-06 05:24 local
Tag: `pre-pass-3-7c-20260506-0524`
Branch: `pass-3-7c`
Base commit: `da6d571` (Pass 3.7b PART 4 follow-up — render_eyebrow per-section)

## Scope

Studio-Spirit Generation Pipeline. Two phases:

1. **Phase 1 (Foundation)** — generation infrastructure:
   - `studio_decoration_scheme.py` — JSON schema + validators + defaults
   - `studio_decoration_generator.py` — Claude+GPT orchestration
   - `studio_layouts/motion_modules/` — ghost_numbers, marquee_strip, magnetic_button, statement_bar
   - `POST /sites/{id}/generate-decoration` + `GET /sites/{id}/decoration-status`
   - 60-second per-business cooldown (in-memory)
2. **Phase 2 (Integration, after checkpoint)** — wire schemes into rendering:
   - Override slot helpers in `studio_layouts/shared.py`
   - Update all 12 layouts to consume `scheme` kwarg
   - Thread `scheme` through `smart_sites.py` and `dispatch.py`

After Phase 1, sites render exactly as before — generation works in isolation. Layouts only consume the scheme after Phase 2.

## Backwards-compatibility guarantees

- Every scheme override read uses `safe_read()` with deterministic fallback. Missing/malformed scheme fields → fall back to Pass 3.7/3.7b deterministic decoration.
- Sites without a `generated_decoration` key in `site_config` render identically to before (no API calls, no error paths triggered).
- Generation failure never blocks a render — exceptions caught in the endpoint, layout never sees a half-built scheme.
- `schema_version: 1` for all generated schemes; future schema changes increment this and old schemes still readable via `safe_read`.

## Env var dependencies

- `ANTHROPIC_API_KEY` — must be set on Railway (already used by other endpoints)
- `OPENAI_API_KEY` — **NEW; required for full pipeline.** If missing, generator falls back to Claude-only output (lower quality but functional).
- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` — already required

## Files modified

### Phase 1 (new)
- `studio_decoration_scheme.py` (new)
- `studio_decoration_generator.py` (new)
- `studio_layouts/motion_modules/__init__.py` (new)
- `studio_layouts/motion_modules/ghost_numbers.py` (new)
- `studio_layouts/motion_modules/marquee_strip.py` (new)
- `studio_layouts/motion_modules/magnetic_button.py` (new)
- `studio_layouts/motion_modules/statement_bar.py` (new)
- `public_site.py` (add 2 endpoints + cooldown tracker)

### Phase 2 (modify, after checkpoint)
- `studio_layouts/shared.py` (add override-slot helpers + `render_decoration_head` + `render_decoration_scripts`)
- `studio_layouts/{magazine,throne,authority,empire_platform,community_hub,gallery,studio_portfolio,movement,story_arc,experience,clean_launch,celebration}.py` (consume scheme)
- `smart_sites.py` (read scheme from site_config, pass to render)
- `dispatch.py` (thread scheme kwarg)

## Backups

- `studio_layouts.pre-3-7c.bak/` (16 layout files + 6 section files)
- `public_site.py.pre-3-7c.bak`
- `smart_sites.py.pre-3-7c.bak`
- `studio_decoration.py.pre-3-7c.bak`
- `studio_layouts/shared.py.pre-3-7c.bak`

## Rollback

### Soft (revert this branch only, keep tag)
```bash
git checkout main
git branch -D pass-3-7c
# Reapply backups if any local edits leaked outside branch:
cp studio_layouts.pre-3-7c.bak/*.py studio_layouts/
cp studio_layouts.pre-3-7c.bak/sections/*.py studio_layouts/sections/
cp public_site.py.pre-3-7c.bak public_site.py
cp smart_sites.py.pre-3-7c.bak smart_sites.py
```

### Hard (after merge to main, full reset to pre-pass tag)
```bash
git checkout main
git reset --hard pre-pass-3-7c-20260506-0524
git push --force-with-lease origin main
```
This rolls Railway back automatically on next deploy. Confirm /public/health 200 after.

### Database
No SQL migration. `generated_decoration` is a new key inside existing JSONB `business_sites.site_config`. To strip on rollback (optional, only if a generated scheme is somehow rendering broken HTML even after code rollback):
```sql
UPDATE business_sites SET site_config = site_config - 'generated_decoration' WHERE site_config ? 'generated_decoration';
```

## Verification commands

```bash
# Health
curl https://kmj-intake-server-production.up.railway.app/public/health

# Phase 1 — generate
curl -X POST https://kmj-intake-server-production.up.railway.app/sites/12773842-3cc6-41a7-9094-b8606e3f7549/generate-decoration

# Phase 1 — status (always available)
curl https://kmj-intake-server-production.up.railway.app/sites/12773842-3cc6-41a7-9094-b8606e3f7549/decoration-status

# Phase 1 — cooldown (call generate twice within 60s, expect 429 second time)

# Phase 2 — visit live site, expect generated tokens applied
# https://kmj-creative-solutions.mysolutionist.app
```

## Cost notes

- Each generation: ~$0.10–$0.30 (Claude Opus + GPT-5.x)
- 60s per-business cooldown prevents accidental rapid-fire
- No regen count cap during testing phase (per user instruction)
- Cooldown is in-memory; Railway restart resets it (acceptable for v1)

## Known concerns flagged for user decision

1. **Model name `gpt-5.4`** — spec specifies this but the OpenAI API model registry does not include `gpt-5.4`. Closest valid model is `gpt-5` (released Aug 2025). The generator code will be implemented with `gpt-5.4` per spec; if it 404s on first deploy, fallback path uses Claude output directly, and we can switch to `gpt-5` after user confirms.
2. **`OPENAI_API_KEY` on Railway** — user must verify this is set before Phase 1 deploy. If missing, generator falls back to Claude-only path.
