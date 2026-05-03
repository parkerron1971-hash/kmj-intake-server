# Practitioner Profile Return Point

**Tag:** `pre-practitioner-profile-20260503-0200`
**Branch:** `practitioner-profile` (off `main` HEAD)
**Created:** 2026-05-03

## Repos

| Repo | Origin | Branch |
|---|---|---|
| Backend (this repo) | github.com/parkerron1971-hash/kmj-intake-server | `practitioner-profile` |
| Frontend | github.com/parkerron1971-hash/solutionist-studio | `practitioner-profile` |

## Rollback procedures

### Roll back the backend (code)
```
git checkout main
git reset --hard pre-practitioner-profile-20260503-0200
git push --force-with-lease origin main
```

### Restore live files from .bak (no git ops)
Files live at the repo root (not under `railway/`):
```
cp chief_of_staff.py.pre-practitioner.bak chief_of_staff.py
cp kmj_intake_automation.py.pre-practitioner.bak kmj_intake_automation.py
```

### Roll back the database
```
psql <SUPABASE_URL> -f ../solutionist-studio/supabase/practitioner-profile-rollback.sql
```

## What this branch will add
- `practitioner_profile_agent.py` (new): `JIT_FIELDS_V1`, `PHRASING`, `get_phrasing`, `get_profile`, `upsert_profile`, `update_field`, `_calculate_completeness`, `get_missing_jit_fields`, `chief_context_block`, `is_complete`. Uses the existing httpx + REST pattern (not the supabase client) for consistency with sister modules.
- `practitioner_profile_router.py` (new): `/practitioner-profile/*` endpoints (health, profile GET+POST, proactive-mode, is-complete, missing).
- `kmj_intake_automation.py` registers `practitioner_profile_router` before `public_site_router`.
- `chief_of_staff.py` extended:
  - `_JIT_PRACTITIONER_TRIGGERS` + `_detect_practitioner_topics`.
  - `_was_recently_asked(prefix=...)` so the same helper works for `jit_asked:` (business) and `jit_asked_practitioner:` (practitioner).
  - `_build_jit_directive` extended to append a practitioner directive when triggered.
  - `_gather_context` stashes `ctx['practitioner_block']` and `ctx['practitioner_profile_raw']`.
  - System prompt block formatter `_format_practitioner_block` injected before the business profile block.
  - `handle_update_practitioner_profile_field` registered and taught.

## Files modified
- `kmj_intake_automation.py` (router registration)
- `chief_of_staff.py` (JIT extension, action handler, prompt teaching, context loading)

## Pre-flight before merge to main
- `/practitioner-profile/health` returns 200 after Railway redeploy.
- All four files compile (`python -m py_compile`).
- `practitioner_profile_router` registered before `public_site_router` (router order check).
- Brace escaping verified: practitioner directive uses plain-string concat, not f-strings.
