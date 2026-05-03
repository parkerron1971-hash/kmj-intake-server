# Just-In-Time Profile Capture Return Point

**Tag:** `pre-jit-capture-20260503-0100`
**Branch:** `jit-capture` (off `main` HEAD)
**Created:** 2026-05-02

## Repos

| Repo | Origin | Branch |
|---|---|---|
| Backend (this repo) | github.com/parkerron1971-hash/kmj-intake-server | `jit-capture` |
| Frontend | github.com/parkerron1971-hash/solutionist-studio | `jit-capture` |

## Rollback procedures

### Roll back the backend (code)
```
git checkout main
git reset --hard pre-jit-capture-20260503-0100
git push --force-with-lease origin main
```

### Restore live files from .bak (no git ops)
Files live at the repo root (not under `railway/`):
```
cp chief_of_staff.py.pre-jit.bak chief_of_staff.py
cp business_profile_agent.py.pre-jit.bak business_profile_agent.py
cp business_profile_router.py.pre-jit.bak business_profile_router.py
```

### Roll back the database
```
psql <SUPABASE_URL> -f ../solutionist-studio/supabase/jit-capture-rollback.sql
```

## What this branch will add
- `business_profile_agent.py`: PHRASING dict + `get_phrasing`, `update_field` (handles dotted paths), `get_missing_jit_fields`.
- `chief_of_staff.py`:
  - `_JIT_TRIGGERS` keyword sets and `_detect_profile_topics` (deterministic Python scan).
  - `_was_recently_asked` reading `ctx["memories"]` for `jit_asked` markers.
  - JIT directive injector between `_gather_context` and `_build_system_prompt` (lines ~8646).
  - `_gather_context` also stashes `ctx["business_profile_raw"]` so the injector can read `proactive_capture_enabled`.
  - `handle_update_business_profile_field` registered in `ACTION_HANDLERS`.
  - `update_business_profile_field` taught in the system prompt's ACTIONS block.
- `business_profile_router.py`: new POST `/business-profile/profile/{business_id}/proactive-mode`.

## Files modified
- `chief_of_staff.py` (detection, directive injector, action handler, system prompt teaching)
- `business_profile_agent.py` (phrasing, single-field update, missing-fields enumerator)
- `business_profile_router.py` (proactive-mode endpoint)

## Pre-flight before merge
- All three Python files compile (`python -m py_compile`).
- `/business-profile/profile/<biz>/proactive-mode` accepts a body and toggles the column.
- Chief sees JIT directive at the TOP of the system prompt only when a missing field is triggered.
- F-string brace escaping verified (no `KeyError` / `NameError` in Railway logs after first chat).
- Action handler registered before `public_site_router` (router order check).
