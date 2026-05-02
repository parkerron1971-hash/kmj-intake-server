# Business Profile Return Point

**Tag:** `pre-business-profile-20260502-2330`
**Branch:** `business-profile` (off `foundation-track`)
**Created:** 2026-05-02

## Repos

| Repo | Origin | Branch |
|---|---|---|
| Backend (this repo) | github.com/parkerron1971-hash/kmj-intake-server | `business-profile` |
| Frontend | github.com/parkerron1971-hash/solutionist-studio | `business-profile` |

## Rollback procedures

### Roll back the backend (code)
```
git checkout foundation-track
git reset --hard pre-business-profile-20260502-2330
```

### Restore live files from .bak (no git ops)
```
cp kmj_intake_automation.py.pre-profile.bak kmj_intake_automation.py
cp chief_of_staff.py.pre-profile.bak chief_of_staff.py
```

### Roll back the database
```
psql <SUPABASE_URL> -f ../solutionist-studio/supabase/business-profile-rollback.sql
```

## What this branch adds
- `business_profile_agent.py` — archetype lookup, profile CRUD, completeness math, required-disclaimer aggregation, Chief context block.
- `business_profile_router.py` — `/business-profile/*` endpoints.
- `kmj_intake_automation.py` registers `business_profile_router` BEFORE `foundation_router` and `public_site_router`.
- `chief_of_staff.py` imports `business_profile_agent.chief_context_block as bp_chief_context_block` and injects its output alongside Foundation Track block (with `{{` `}}` brace escaping).

## Files modified
- `kmj_intake_automation.py` (router registration only)
- `chief_of_staff.py` (context block injection only)

## Pre-flight before merge
- `/business-profile/health` returns 200
- `/business-profile/archetypes` returns 8 rows
- Chief sees `## Business Profile` in its system prompt alongside `## Foundation Track`
- `business_profile_router` registered before `public_site_router` (verified by reading order in `kmj_intake_automation.py`)
