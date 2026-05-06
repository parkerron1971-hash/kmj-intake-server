# Pass 3.8a — Backend Return Point

Created: 2026-05-06 18:46 local
Tag: `pre-pass-3-8a-20260506-1846`
Branch: `pass-3-8a` (off `main` @ `dd761ce`)
Base: Pass 3.7c Phase 2 merged to main

## Scope — foundation only

This sub-pass ports Studio's constraint-and-choice pattern to Smart Sites. **No layout changes ship in 3.8a.** The Designer Agent endpoint exists, persists its output to `site_config.design_recommendation`, but the rendering pipeline does not yet consume it. Sites must render exactly as before.

## Files added (new)

- `studio_strands.py` — 10 STYLE_STRANDS, DNA + spatialDNA verbatim from Studio's `src/lib/strandConstants.ts`
- `studio_substrands.py` — 30 SUB_STRANDS verbatim from `src/lib/design/subStrands.ts`
- `studio_strand_fonts.py` — STRAND_FONT_MAP + resolve_font_pair
- `studio_design_constants.py` — LAYOUT_ARCHETYPE_IDS / ACCENT_STYLE_IDS / SITE_TYPE_IDS + descriptions
- `studio_designer_agent.py` — LLM #1 orchestration (Claude Opus) + deterministic cold-start branch

## Files modified

- `brand_engine.py` — `get_bundle()` now composes `bundle.practitioner_intelligence` (about_me + about_business + strategy_track + signal_words). All reads defensive — missing tables/columns fall back to None.
- `studio_vocab_detect.py` — `_has_meaningful_voice_signal` threshold raised from 2-of-6 to **2-of-9** (added 3 new signals from practitioner_intelligence). Vocabulary detection now consumes intelligence signal_words.
- `public_site.py` — cooldown tracker + 2 new endpoints:
  - `POST /sites/{id}/generate-design-recommendation` — runs Designer Agent, persists to `site_config.design_recommendation`
  - `GET /sites/{id}/design-signals` — diagnostic, returns which signals fired

## Backwards compatibility

- `bundle.practitioner_intelligence` is additive — existing bundle consumers ignore unknown keys.
- Vocabulary detection threshold change is a single integer; no signal collected previously becomes invalid.
- Designer Agent endpoint is brand new — nothing currently calls it.
- `site_config.design_recommendation` is a new key in existing JSONB; layouts in Pass 3.8a do NOT read it.
- Rendering pipeline (Pass 3.7c) untouched.

## Env var dependencies

- `ANTHROPIC_API_KEY` — already used by Pass 3.7c. No new key.
- No `OPENAI_API_KEY` requirement in 3.8a (Brief Expander in 3.8b will need it again).

## Backups

- `brand_engine.py.pre-3-8a.bak`
- `studio_vocab_detect.py.pre-3-8a.bak`
- `public_site.py.pre-3-8a.bak`

## Rollback

### Soft (revert this branch only)
```bash
git checkout main
git branch -D pass-3-8a
# Restore .bak files if any local edits leaked outside branch:
cp brand_engine.py.pre-3-8a.bak brand_engine.py
cp studio_vocab_detect.py.pre-3-8a.bak studio_vocab_detect.py
cp public_site.py.pre-3-8a.bak public_site.py
```

### Hard (after merge to main)
```bash
git checkout main
git reset --hard pre-pass-3-8a-20260506-1846
git push --force-with-lease origin main
```
Railway auto-deploys main; rollback completes on next deploy. Confirm `/public/health` 200 and `/sites/{id}/design-signals` 404 (endpoint gone) after rollback.

### Database
No SQL migration. `design_recommendation` is a new key inside existing JSONB `business_sites.site_config`. To strip on rollback (only if recommendations are somehow polluting downstream rendering — they shouldn't in 3.8a):
```sql
UPDATE business_sites SET site_config = site_config - 'design_recommendation' WHERE site_config ? 'design_recommendation';
```

## Verification commands

```bash
# Health
curl https://kmj-intake-server-production.up.railway.app/public/health

# Diagnostic — does NOT call Claude, free probe
curl https://kmj-intake-server-production.up.railway.app/sites/12773842-3cc6-41a7-9094-b8606e3f7549/design-signals
curl https://kmj-intake-server-production.up.railway.app/sites/1593d297-b2cd-4ac6-a003-301aac59e687/design-signals
curl https://kmj-intake-server-production.up.railway.app/sites/19a4eaac-2625-4e81-910b-a059334c45fd/design-signals

# Generate recommendations (60s cooldown per business; ~$0.05 per Claude call when rich-data)
curl -X POST https://kmj-intake-server-production.up.railway.app/sites/12773842-3cc6-41a7-9094-b8606e3f7549/generate-design-recommendation
# wait 60s before next:
curl -X POST https://kmj-intake-server-production.up.railway.app/sites/1593d297-b2cd-4ac6-a003-301aac59e687/generate-design-recommendation
curl -X POST https://kmj-intake-server-production.up.railway.app/sites/19a4eaac-2625-4e81-910b-a059334c45fd/generate-design-recommendation

# Rendering parity (must look identical to before)
curl -s https://kmj-creative-solutions.mysolutionist.app | head -100
```

## Cost notes

- Cold-start path: deterministic, no LLM, $0
- Rich-data path: 1 Claude Opus call, ~1500-2000 tokens out, ~$0.03-0.10 per generation
- 60s cooldown / business prevents accidental rapid-fire
- No regen cap during testing

## Known data assumptions to verify in PART 5

The `_read_practitioner_intelligence` helper reads from columns/tables that may or may not exist:
- `practitioners.bio` / `practitioners.about_me_content` (one or the other)
- `business_profiles.about_my_business_content` / `.positioning_statement`
- `strategy_tracks` table (may be empty or named differently)

All reads wrapped in try/except → missing table or column returns None. This is intentional — the helper degrades gracefully on incomplete schemas, surfacing whatever signal exists.

## What 3.8a does NOT include

- Brief Expander LLM #2 (deferred to 3.8b)
- 6 layout archetype renderers (deferred to 3.8c)
- Smart Sites rendering pipeline integration (deferred to 3.8d)
- Frontend MySite Design DNA UI extension for the new strand picker (deferred to 3.8e)
- SQL migrations to add intelligence columns (out of scope; the spec says "reads existing tables")
