# Brand Assets v1 Return Point

**Tag:** `pre-brand-assets-20260503-0500`
**Branch:** `brand-assets` (off `main` HEAD)
**Created:** 2026-05-03

## Repos

| Repo | Origin | Branch |
|---|---|---|
| Backend (this repo) | github.com/parkerron1971-hash/kmj-intake-server | `brand-assets` |
| Frontend | github.com/parkerron1971-hash/solutionist-studio | `brand-assets` |

## Rollback procedures

### Roll back the backend (code)
```
git checkout main
git reset --hard pre-brand-assets-20260503-0500
git push --force-with-lease origin main
```

### Restore live files from .bak (no git ops, no Railway redeploy)
Files live at the repo root (not under `railway/`):
```
cp brand_engine.py.pre-assets.bak brand_engine.py
cp brand_engine_router.py.pre-assets.bak brand_engine_router.py
cp public_site.py.pre-assets.bak public_site.py
```

### Roll back the database
```
psql <SUPABASE_URL> -f ../solutionist-studio/supabase/brand-assets-rollback.sql
```
Removes `brand_kit.assets` from every row. Storage objects already
uploaded to `business-assets/brand/<biz>/...` are NOT deleted by the
rollback — they orphan silently and represent only minor storage cost.

## What this branch will add
- `brand_engine.py`:
  - `ASSET_VARIANTS` config + `upload_asset` + `remove_asset` functions
    that talk to Supabase Storage `business-assets` bucket via the
    REST API (matches the existing httpx + REST helper pattern; no
    supabase-py client introduced).
  - `_normalize_brand_kit` extended to mirror `assets.primary` ↔
    `logo_url` (both directions, idempotent).
  - Bundle composition adds an `assets` section with all six variants
    and graceful fallbacks (missing → primary → null).
  - `chief_context_block` reports asset coverage to the Chief.
- `brand_engine_router.py`:
  - `POST /brand/asset/upload` — multipart `(business_id, variant, file)`.
  - `POST /brand/asset/remove/{business_id}` — JSON `{variant}`.
- `public_site.py`:
  - `_brand_head_meta_tags(business_id)` helper returns favicon link +
    Open Graph + Twitter Card meta tags for injection into rendered
    HTML `<head>`.

## Files modified
- `brand_engine.py` (asset normalization, upload/remove, bundle assets, chief context)
- `brand_engine_router.py` (two new endpoints)
- `public_site.py` (head meta helper)

## Pre-flight before merge to main
- All three Python files compile (`python -m py_compile`).
- `/brand/health` still returns 200 after Railway redeploy.
- `/brand/bundle/{biz}` includes `assets` section with all six keys.
- `/brand/asset/upload` accepts multipart and writes to Supabase
  Storage `business-assets/brand/<biz>/<variant>-<timestamp>.<ext>`.
- Storage object URL is reachable (public read RLS on
  `business-assets` bucket already in place).
