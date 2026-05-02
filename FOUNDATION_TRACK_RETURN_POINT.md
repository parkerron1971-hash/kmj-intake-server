# Foundation Track Return Point

**Tag:** `pre-foundation-track-20260502-2230`
**Branch:** `foundation-track` (off `main` HEAD)
**Created:** 2026-04-30

This is the canonical rollback point if Foundation Track work needs to be unwound without losing the existing Email Hub / SMS Hub / Chief / Stripe / Resend / Telnyx baseline.

## Repos

| Repo | Tag pushed? | Branch |
|---|---|---|
| Backend (this repo) | yes (`origin`) | `foundation-track` |
| Frontend (`solutionist-studio`) | local-only (no `origin` remote) | `foundation-track` |

## Rollback procedures

### Roll back the backend (code)
```
git checkout main
git reset --hard pre-foundation-track-20260502-2230
git push --force-with-lease origin main   # only if foundation-track was already merged
```

### Restore live files from .bak (no git ops needed)
```
cp kmj_intake_automation.py.pre-foundation.bak kmj_intake_automation.py
cp chief_of_staff.py.pre-foundation.bak chief_of_staff.py
```

### Roll back the database
```
psql <SUPABASE_URL> -f ../solutionist-studio/supabase/foundation-track-rollback.sql
```

## What this branch adds
- `foundation_agent.py` — phase logic, entity recommendation (Claude-backed), state filing lookup, document generators
- `foundation_router.py` — `/foundation/*` endpoints
- Hook in `kmj_intake_automation.py` to register `foundation_router` BEFORE `public_site_router`
- Hook in `chief_of_staff.py` to inject the foundation context block into the Chief system prompt

## Files modified
- `kmj_intake_automation.py` (router registration only)
- `chief_of_staff.py` (context block injection only)

## Pre-flight before merge to main
- `/foundation/health` responds 200
- `/foundation/progress/{biz}` returns the 7-phase shape
- Chief sees `## Foundation Track` in its system prompt
- `foundation_router` registered before `public_site_router` (verified by reading the order in `kmj_intake_automation.py`)
- All `TODO(foundation-track-v2):` markers reviewed
