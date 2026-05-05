# Smart Sites v1 — Return Point (Backend)

## Pre-flight

- **Tag**: `pre-smart-sites-20260504-0659` (pushed to origin)
- **Branch**: `smart-sites` (created from `main`)
- **Base commit**: `7ab1299` (Merge voice-depth: Pass 2.5b Brand Voice Depth backend)

## Backups (sibling files, .pre-smart.bak)

- `public_site.py.pre-smart.bak`
- `brand_engine.py.pre-smart.bak`
- `kmj_intake_automation.py.pre-smart.bak`

## Files this build adds or modifies

| File | Change |
|------|--------|
| `smart_sites.py` | NEW — vibe families + archetype touches + render entry |
| `public_site.py` | Flag-gated handler delegation + new smart-config/preview/enable endpoints + legacy meta-tag wiring |
| `kmj_intake_automation.py` | (no change planned — smart_sites endpoints live on the existing public_site router) |
| `brand_engine.py` | (no change planned — read-only consumer of `get_bundle()` and `DISCLAIMER_PHRASES`) |

## No SQL migration

`business_sites.site_config` is currently `{}` for every row. Smart Sites adds keys as users opt in via the new `/smart-enable` endpoint. Schema is unchanged.

## Rollback procedures

### Symptom 1 — existing legacy sites break

```bash
cp public_site.py.pre-smart.bak public_site.py
git add public_site.py && git commit -m "Restore public_site from backup" && git push
```

### Symptom 2 — Smart Sites preview crashes

Frontend issue. See frontend return point doc.

### Symptom 3 — vibe family rendering bug

Most common cause: unescaped `{` / `}` in CSS inside an f-string. Fix the specific renderer. No revert needed.

### Symptom 4 — `_brand_head_meta_tags` errors

```bash
cp brand_engine.py.pre-smart.bak brand_engine.py
```

### Symptom 5 — full revert

```bash
git reset --hard pre-smart-sites-20260504-0659
git push --force-with-lease origin main
```

No SQL rollback needed — site_config keys can be ignored.

## Pre-build verification checklist

- [x] Both repos clean on main / module-system
- [x] Tag created and pushed (both repos)
- [x] `smart-sites` branch created (both repos)
- [x] `.pre-smart.bak` backups in place (both repos)
- [ ] Supabase backups verified by user (Database → Backups)
- [ ] User confirms ready to proceed past PART 0

## Architectural invariants

- `public_site_router` MUST stay last in `kmj_intake_automation.py` router registration (the catch-all route would shadow `/voice/*`, `/brand/*`, etc. otherwise).
- Smart Sites is **opt-in** via `site_config.use_smart_sites = true`. Default is `false` — legacy rendering path unchanged.
- All Smart Sites calls wrapped in try/except so any failure falls through to legacy rendering.
- `_brand_head_meta_tags` (defined at `public_site.py:85`) is wired into BOTH legacy AND Smart Sites `<head>` blocks in this build — finally activates the Pass 2.5a helper.
- F-string brace escaping: every literal `{` / `}` inside CSS embedded in an f-string must be `{{` / `}}`.
