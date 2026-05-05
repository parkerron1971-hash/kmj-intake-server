# Studio Port — Session 1 — Return Point (Backend)

## Pre-flight

- **Tag**: `pre-studio-port-s1-20260504-2208` (pushed to origin)
- **Branch**: `studio-port-s1` (created from `main`)
- **Base commit**: `ff36242` (Merge smart-sites: Pass 3 Smart Sites v1 backend)

## Scope

Pure additive port of Solutionist Studio's deterministic design intelligence into Python. **No existing files modified.** No deploy to main in this session — Session 1 ships intelligence to the branch, Sessions 2 + 3 build renderers and integrate.

## Files this session adds

| File | Purpose |
|------|---------|
| `studio_data.py` | 23 vocabularies, 12 layouts, vocab→layout map, font pairings, style strands, accent libraries, image composition rules, craft techniques, aesthetic presets |
| `studio_composite.py` | Color math (hex↔HSL, blend), palette blending, layout ranking, `build_composite()` |
| `studio_design_system.py` | `build_design_system()` returning CSS tokens + component CSS strings |
| `studio_vocab_detect.py` | Rule-based vocabulary detection from existing business data (no AI, no new intake) |
| `studio_data_test.py` | Runnable smoke test (counts, color math, detection on real businesses, composite, design system) |
| `STUDIO_PORT_S1_RETURN_POINT.md` | This doc |

## Files NOT touched

- `public_site.py`
- `smart_sites.py`
- `brand_engine.py`
- `chief_of_staff.py`
- `kmj_intake_automation.py`
- All TypeScript in solutionist-studio repo
- All schema (no SQL migration)

## Architectural invariants

- **Zero AI calls.** Every Python function in this session is pure or DB-read-only.
- **Zero new intake forms.** Detection reads existing `business_profiles`, `brand_kit`, `voice_profile`.
- **Top-3 with confidence + reasons.** Detection returns multiple candidates; Session 3 will let users override.
- **Counts asserted at import time.** `studio_data.py` runs `assert len(VOCABULARIES) == 23` on import — incomplete ports fail loud.
- **Heuristic, not perfect.** Detection accuracy targeted ~70% on first try; Session 3 ships override UX for the long tail.

## Rollback procedures

### Symptom 1 — module import fails

Likely cause: missing field on a ported vocabulary/layout, or a count assertion failed. The assertions at the bottom of `studio_data.py` pinpoint count mismatches. Specific syntax errors surface on import. Fix the offending entry and re-import.

### Symptom 2 — detection scores are clearly wrong

Tune the affinity tables in `studio_vocab_detect.py`:
- `ARCHETYPE_VOCAB_AFFINITY`
- `BRAND_VOICE_VOCAB_AFFINITY`
- weights inside `_score_vocabulary` (1.0 archetype, 0.8 brand voice, 0.15 per signal word, 0.12 per detection signal)

Re-run `python studio_data_test.py` after each tuning.

### Symptom 3 — color blending produces ugly palettes

Inspect `blend_hex_colors`. Hue wraparound is the usual suspect — test with red+green, blue+yellow.

### Symptom 4 — full revert

```bash
git reset --hard pre-studio-port-s1-20260504-2208
git push --force-with-lease origin main   # only if accidentally merged to main
```

Or just delete the new files (nothing in production uses them yet):

```bash
rm studio_data.py studio_composite.py studio_design_system.py studio_vocab_detect.py studio_data_test.py
```

## What Session 2 will build on top

- 12 layout-specific HTML/CSS renderers, each consuming `DesignSystem` + section data
- Layout-specific image composition application
- Layout-specific accent injection
- Section-order resolution per layout

## What Session 3 will build on top

- Wire Smart Sites' `_render_page` to call `detect_vocabulary_triple()` → `build_composite()` → layout renderer
- Add MySite UI: vocabulary picker (top-3 from detection + manual override), layout picker (top-3 from composite + manual)
- New endpoints to expose vocabularies/layouts/detection results to the frontend

## Pre-build verification checklist

- [x] Backend clean on main
- [x] Tag created and pushed
- [x] `studio-port-s1` branch created from main
- [x] Return-point doc written
- [ ] User confirms ready to proceed past PART 0
