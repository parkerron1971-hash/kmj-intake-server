# Onboarding Unification Return Point

**Tag:** `pre-onboarding-unify-20260503-0030`
**Branch:** `onboarding-unify` (off `main` HEAD)
**Created:** 2026-05-02

## Repos

| Repo | Origin | Branch |
|---|---|---|
| Backend (this repo) | github.com/parkerron1971-hash/kmj-intake-server | `onboarding-unify` |
| Frontend | github.com/parkerron1971-hash/solutionist-studio | `onboarding-unify` |

## Rollback procedures

### Roll back the backend (code)
```
git checkout main
git reset --hard pre-onboarding-unify-20260503-0030
git push --force-with-lease origin main
```

### Restore live files from .bak (no git ops)
```
cp kmj_intake_automation.py.pre-unify.bak kmj_intake_automation.py
cp chief_of_staff.py.pre-unify.bak chief_of_staff.py
cp business_profile_agent.py.pre-unify.bak business_profile_agent.py
cp business_profile_router.py.pre-unify.bak business_profile_router.py
```

### Roll back the database
```
psql <SUPABASE_URL> -f ../solutionist-studio/supabase/onboarding-unify-rollback.sql
```

## What this branch adds
- `business_profile_router.py`: new POST `/business-profile/profile/seed-from-onboarding` endpoint (idempotent — only fills NULL fields).
- `business_profile_agent.py`: new `import_from_strategy_track(business_id)` function plus a `seed_from_onboarding` helper that handles tone-to-brand_voice mapping and archetype defaults.
- `chief_of_staff.py`: in the `complete_strategy_track` action handler (~line 4052), a new non-fatal call to `import_from_strategy_track` that pulls `service_packages`/`pricing_strategy.tiers` into the profile.

## Pre-flight before merge
- `/business-profile/profile/seed-from-onboarding` round-trips successfully on a test business.
- `complete_strategy_track` log shows the new line printing on success and not crashing on any failure path.
- All four files compile (`python -m py_compile`).
- `business_profile_router` registered before `public_site_router` (still last).
