# Voice Depth (Pass 2.5b) Return Point

**Tag:** `pre-voice-depth-20260503-0700`
**Branch:** `voice-depth` (off `main` HEAD)
**Created:** 2026-05-03

## Repos

| Repo | Origin | Branch |
|---|---|---|
| Backend (this repo) | github.com/parkerron1971-hash/kmj-intake-server | `voice-depth` |
| Frontend | github.com/parkerron1971-hash/solutionist-studio | `voice-depth` |

## Rollback procedures

### Roll back the backend (code)
```
git checkout main
git reset --hard pre-voice-depth-20260503-0700
git push --force-with-lease origin main
```

### Restore live files from .bak (no git ops, no Railway redeploy)
Files live at the repo root (not under `railway/`):
```
cp chief_of_staff.py.pre-voice.bak chief_of_staff.py
cp brand_engine.py.pre-voice.bak brand_engine.py
cp business_profile_agent.py.pre-voice.bak business_profile_agent.py
cp kmj_intake_automation.py.pre-voice.bak kmj_intake_automation.py
```

### Roll back the database
```
psql <SUPABASE_URL> -f ../solutionist-studio/supabase/voice-depth-rollback.sql
```

## What this branch will add
- `voice_depth_agent.py` (new) — httpx + Supabase REST helper pattern
  (matches business_profile_agent / practitioner_profile_agent — NOT
  supabase-py per established codebase convention). Public API:
  `get_voice_depth`, `update_voice_sample`, `update_voice_style`,
  `add_voice_rule`, `remove_voice_rule`, `record_edit_observation`,
  `get_observations_for_proposal`, `clear_observations_after_rule`,
  `chief_voice_context_block` (rich, for outer Chief),
  `voice_depth_payload_for_inner_call` (compact, for `_draft_short`).
- `voice_depth_router.py` (new) — `/voice/*` endpoints.
- `kmj_intake_automation.py` registers `voice_depth_router` between the
  brand and practitioner routers, before `public_site_router` (still last).
- `brand_engine.py`:
  - `_compose_voice` signature extended to take `practitioner` and surface
    `voice_samples`, `voice_dos`, `voice_donts`, `greeting_style`,
    `signoff_style`, `audience`, `tone_original` in the bundle.
  - `chief_context_block` adds `personality` and `audience` lines to the
    surfaced voice info.
- `chief_of_staff.py`:
  - Imports `voice_depth_agent` + alias for the chief context block.
  - `_gather_context` adds a fourth `asyncio.to_thread` parallel task for
    the voice block.
  - `_format_voice_block` formatter; injected after the brand block,
    before the practitioner block.
  - `_draft_short(...)` accepts an optional `voice_payload` parameter
    (default empty string) prepended to its system prompt. All callers
    inside chief_of_staff.py now read voice via
    `voice_depth_agent.voice_depth_payload_for_inner_call(owner_id)` and
    pass it through.
  - Six new action handlers registered: `update_voice_sample`,
    `add_voice_rule`, `remove_voice_rule`, `update_voice_style`,
    `record_edit_pattern` (silent), `propose_voice_rule` (frontend event).
  - System prompt's ACTIONS block teaches all six.
  - JIT directive injector extended with voice topic detection
    (`_JIT_VOICE_TRIGGERS` + `_detect_voice_topics`); anti-repeat namespace
    `jit_asked_voice:` so business / practitioner / voice asks don't collide.

DB schema changes (in solutionist-studio/supabase/voice-depth-migration.sql):
- 6 new columns on `practitioner_profiles`.
- `voice_profile.tone_original` audit field on `businesses`.
- One-shot enum remap: `professional → corporate`, `inspirational → warm`,
  `educational → casual`, `bold → direct`. Original preserved.
- `business_profiles.brand_voice` backfilled where null and canonical
  `voice_profile.tone` is set.

## Pre-flight before merge to main
- All four Python files plus the two new modules compile (`python -m py_compile`).
- `/voice/health` returns 200 after Railway redeploy.
- `/voice/depth/{owner_id}` returns the full voice depth shape on existing
  practitioner_profiles rows; empty defaults on rows that don't exist yet.
- `_draft_short` callers all pass voice_payload.
- F-string brace escaping verified for any new directive lands inside the
  Chief system prompt's f-string.
