# Brand Engine v1 Return Point

**Tag:** `pre-brand-engine-20260503-0400`
**Branch:** `brand-engine` (off `main` HEAD)
**Created:** 2026-05-03

## Repos

| Repo | Origin | Branch |
|---|---|---|
| Backend (this repo) | github.com/parkerron1971-hash/kmj-intake-server | `brand-engine` |
| Frontend | github.com/parkerron1971-hash/solutionist-studio | `brand-engine` |

## Rollback procedures

### Roll back the backend (code)
```
git checkout main
git reset --hard pre-brand-engine-20260503-0400
git push --force-with-lease origin main
```

### Restore live files from .bak (no git ops, no Railway redeploy)
Files live at the repo root (not under `railway/`):
```
cp chief_of_staff.py.pre-brand.bak chief_of_staff.py
cp public_site.py.pre-brand.bak public_site.py
cp stripe_proxy.py.pre-brand.bak stripe_proxy.py
cp foundation_agent.py.pre-brand.bak foundation_agent.py
cp kmj_intake_automation.py.pre-brand.bak kmj_intake_automation.py
```

### Roll back the database
```
psql <SUPABASE_URL> -f ../solutionist-studio/supabase/brand-engine-rollback.sql
```

## What this branch will add
- `brand_engine.py` (new) — single read/write authority for brand bundle.
- `brand_engine_router.py` (new) — six `/brand/*` endpoints.
- `kmj_intake_automation.py` registers `brand_engine_router` before
  `public_site_router` (still last).
- `chief_of_staff.py`:
  - Imports `brand_engine` + alias `brand_engine_chief_context_block`.
  - Brand context block injected into the Chief system prompt between
    the practitioner and business-profile blocks.
  - `handle_propose_brand_kit_from_context` action handler registered
    and taught.
  - Email handlers read bundle for signatures and legal footers, with
    fallback to existing voice_profile reads if the bundle fetch fails.
- `foundation_agent.py`: PDF generators (operating agreement, privacy
  policy, TOS) read bundle for legal name, governing state, contact
  email, and full required-disclaimer set.
- `stripe_proxy.py:391–395`: legacy color/font reads route through
  `get_bundle` with both-shapes fallback.
- `public_site.py`: bundle drives footer copyright + legal disclaimers
  on rendered pages, plus the In The Clear badge when the foundation
  bundle is complete.

## Files modified
- `chief_of_staff.py` (context, action handler, email signature reads)
- `foundation_agent.py` (PDF generators)
- `stripe_proxy.py` (lines 391–395)
- `public_site.py` (footer + disclaimers + in-the-clear badge)
- `kmj_intake_automation.py` (router registration)

## Pre-flight before merge to main
- All five Python files compile (`python -m py_compile`).
- `/brand/health` returns 200 after Railway redeploy.
- `brand_engine_router` registered before `public_site_router` (router
  order check).
- Brand context block uses plain string concat or properly escaped
  `{{` `}}` if it lands inside an f-string.
