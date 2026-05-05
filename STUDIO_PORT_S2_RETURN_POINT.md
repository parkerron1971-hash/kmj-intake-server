# Studio Port — Session 2 — Return Point (Backend)

## Pre-flight

- **Tag**: `pre-studio-port-s2-20260504-2301` (pushed to origin)
- **Branch**: `studio-port-s2` (created from `studio-port-s1`)
- **Base commit**: `b7f8cb6` (Studio Port Session 1 — deterministic design intelligence)

## Scope

Two patches + 12 layout HTML/CSS renderers + a static preview generator.
**No production code touched.** `main` is at `ff36242` (Smart Sites v1) and untouched.

## Files this session adds or modifies

| File | Change |
|------|--------|
| `studio_design_system.py` | PATCH — add `_pick_contrast_text` + `_pick_accent_contrast`, apply throughout CSS generators |
| `studio_composite.py` | PATCH — wire `blend_palettes()` into `build_composite()` so secondary/aesthetic actually blend |
| `studio_layouts/__init__.py` | NEW — package init |
| `studio_layouts/shared.py` | NEW — head, footer, badge, archetype touches, disclaimers helpers |
| `studio_layouts/magazine.py` | NEW — reference layout (full detail) |
| `studio_layouts/{throne,community_hub,gallery,authority,story_arc,movement,experience,clean_launch,celebration,studio_portfolio,empire_platform}.py` | NEW — 11 additional layouts |
| `studio_layouts/dispatch.py` | NEW — `render_layout(layout_id, ...)` single entry point |
| `studio_preview.py` | NEW — generates 36 static HTML preview files in `layout_previews/` |
| `studio_data_test.py` | UPDATE — add Tests 6-8 (patches verified, layouts render, preview generated) |
| `STUDIO_PORT_S2_RETURN_POINT.md` | This doc |

## Files NOT touched

- `studio_data.py` — Session 1 data is canonical
- `studio_vocab_detect.py` — Session 1 detection is unchanged
- `public_site.py`, `smart_sites.py`, `brand_engine.py`, `chief_of_staff.py` — production code untouched
- All TypeScript in solutionist-studio repo
- All schema (no SQL migration)

## Backups

- `studio_design_system.py.pre-s2.bak`
- `studio_composite.py.pre-s2.bak`

## Architectural invariants

- **Patches before layouts.** The contrast + blending patches must work BEFORE 12 layout files inherit them.
- **Magazine is the reference.** All 11 additional layouts adopt its `render(...)` signature exactly.
- **Self-contained layouts.** Each `<style>` block is embedded; no external stylesheets.
- **Shared helpers eliminate duplication.** Header, footer, badge, archetype touches written once in `shared.py`.
- **Layout × Vocabulary independence.** Every layout works with every vocabulary.
- **Three checkpoints.** PART 0, PARTs 1–4, PART 5–6. User confirmation required between each.

## Rollback

### Symptom 1 — patches break Test 4 or 5

```bash
cp studio_design_system.py.pre-s2.bak studio_design_system.py
cp studio_composite.py.pre-s2.bak studio_composite.py
```

### Symptom 2 — a single layout crashes

The other 11 still work. The preview generator already wraps `render_layout` in try/except. Fix the offending layout file in isolation.

### Symptom 3 — full revert

```bash
git reset --hard pre-studio-port-s2-20260504-2301
git push --force-with-lease origin studio-port-s2
```

Or just delete the new files (nothing in production reads them):

```bash
rm -rf studio_layouts/ studio_preview.py layout_previews/
cp studio_design_system.py.pre-s2.bak studio_design_system.py
cp studio_composite.py.pre-s2.bak studio_composite.py
```

## What Session 3 will build on top

- Wire `render_layout()` into `smart_sites.render_smart_site_page()` so Smart Sites uses the 12 layouts instead of the 3 vibe families
- MySite UI: vocabulary picker (top-3 from detection), layout picker (top-3 from composite), manual override for both
- Optional new endpoints to expose vocabularies/layouts/detection results to the frontend
- Possibly merge studio-port-s2 + studio-port-s3 to main once integration is verified

## Pre-build verification checklist

- [x] Backend on `studio-port-s1` clean
- [x] Tag created and pushed
- [x] `studio-port-s2` branch created from `studio-port-s1`
- [x] `.pre-s2.bak` backups in place
- [x] Return-point doc written
- [ ] User confirms ready to proceed past PART 0
