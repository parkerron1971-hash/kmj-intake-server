# Studio Port — Session 3 — Return Point (Backend)

## Pre-flight

- **Tag**: `pre-studio-port-s3-20260505-0546` (pushed to origin)
- **Branch**: `studio-port-s3` (created from `studio-port-s2`)
- **Base commit**: `8e38d57` (Studio Port Session 2 — 12 layout renderers + critical patches)

## Scope

Final Studio integration session. Wires the 12 layouts and vocabulary detection into Smart Sites' live page rendering, adds two new endpoints for the override UI, and ships to production at the end. **Backwards compatible** — existing Smart Sites configs (3 vibe families) keep working as the fallback path.

## Files this session adds or modifies

### Backend
| File | Change |
|------|--------|
| `smart_sites.py` | NEW helper `resolve_layout_and_vocabulary(...)`, modified `render_smart_site_page` and `render_smart_site_preview` to try layout system first with try/except fallback to legacy 3-vibe-family rendering |
| `public_site.py` | NEW endpoints — `GET /sites/{business_id}/layout-options` and `POST /sites/{business_id}/layout-override` |
| `kmj_intake_automation.py` | (no change planned — both new endpoints live on the existing public_site router) |

### Files NOT touched

- `studio_data.py`, `studio_composite.py`, `studio_design_system.py`, `studio_vocab_detect.py` — Sessions 1+2 work, untouched
- `studio_layouts/` — all 12 layouts + dispatch + shared, untouched
- `studio_preview.py` — kept as standalone debugging tool
- `brand_engine.py`, `chief_of_staff.py` — production code unchanged
- All schema (no SQL migration; new keys land in JSONB site_config as users opt in)

## Backups

- `smart_sites.py.pre-s3.bak`
- `public_site.py.pre-s3.bak`
- `kmj_intake_automation.py.pre-s3.bak` (defensive — no plan to modify)

## site_config schema additions (no migration)

```json
{
  "use_smart_sites": true,
  "vibe_family_override": "warm" | "formal" | "bold" | null,    // legacy, still respected
  "vocabulary_override": "<vocab-id>" | null,                    // NEW: overrides auto-detection
  "layout_id": "<layout-id>" | null,                             // NEW: overrides auto-pick
  "sections": { ... },                                            // existing
  "footer_extra_text": "...",                                     // existing
  "custom_domain": "..."                                          // existing
}
```

When `vocabulary_override` and/or `layout_id` are absent: auto-detect runs.
When set: user choice overrides detection, stays sticky until reset.

## Architectural invariants

- **Try/except is non-negotiable.** Every layout dispatch in production handlers is wrapped — layout failure NEVER breaks a live site, falls through to legacy 3-vibe-family rendering.
- **Public site router stays last.** Catch-all in `kmj_intake_automation.py`.
- **Auto-detection by default.** No user action required for the new layout system.
- **Top-3 with confidence + reasons surfaced** to the UI so users can override when detection misses.
- **Layout × vocabulary pairing.** Vocabulary determines the palette/typography character; layout determines structure. Any combination produces deterministic output.

## Rollback

### Symptom 1 — live sites broken after deploy

```bash
cp smart_sites.py.pre-s3.bak smart_sites.py
cp public_site.py.pre-s3.bak public_site.py
git add smart_sites.py public_site.py && git commit -m "Restore from pre-s3 backup" && git push
```

### Symptom 2 — layout-options endpoint errors

Likely a vocab detection issue (Session 1 affinity tables). Endpoint returns gracefully — doesn't break /public/site/* paths.

### Symptom 3 — full revert

```bash
git reset --hard pre-studio-port-s3-20260505-0546
git push --force-with-lease origin main
```

## What ships at the end of Session 3

This is the FINAL session — the studio-port-s3 branch merges to `main` and Railway redeploys. After that:
- Every Smart Sites public page renders through Studio's design intelligence
- Vocabularies auto-detect from existing business data
- Users can override via MySite Design System section
- Production = full 23 vocabularies × 12 layouts × archetype-aware touches × brand bundle

## Pre-build verification checklist

- [x] Backend on `studio-port-s2` clean (only untracked layout_previews/, not source)
- [x] Tag created and pushed (both repos)
- [x] `studio-port-s3` branch created (both repos)
- [x] `.pre-s3.bak` backups in place (both repos)
- [x] Return-point docs written
- [ ] User confirms Supabase backups healthy
- [ ] User confirms ready to proceed past PART 0
