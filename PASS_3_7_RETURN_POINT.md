# Pass 3.7 — Visual Richness Foundation — Return Point (Backend)

## Pre-flight

- **Tag (backend)**: `pre-pass-3-7-20260505-1745` (pushed to origin)
- **Tag (frontend)**: `pre-pass-3-7-20260505-1745` (pushed; frontend not modified in this pass, tagged for safety)
- **Branch**: `pass-3-7` (created from `main` @ `d46532c`)
- **Base commit**: `d46532c` (Fix contact-submit target email — prefer site_config sections.contact.email)

## Scope

Pure backend rendering polish. Renders the design intelligence already ported in Studio Sessions 1-2 (`ACCENT_LIBRARY`, `IMAGE_COMPOSITION`, `CRAFT_TECHNIQUES` data structures) which Sessions 2-3 didn't actually emit. Smart Sites pages become genuinely beautiful per vocabulary instead of structurally-correct-but-plain.

**No new sections. No new schema. No frontend UI changes.** Pure visual additions: vocabulary-driven decorations, CSS-only motion (scroll reveals + hover lifts + marquee), gradient depth on hero/section/card backgrounds, and typography craft helpers (pull quotes, drop caps, eyebrow text).

## Files this pass adds or modifies

### Backend
| File | Change |
|------|--------|
| `studio_decoration.py` | NEW — central vocab-driven decoration helpers (accent-set lookup, section dividers, decorative corners, gradient generators, slot-based dispatcher) |
| `studio_layouts/shared.py` | Adds `render_motion_styles()` + `render_motion_script()`; existing `render_head()` includes the motion CSS |
| `studio_layouts/sections/typography.py` | NEW — `render_pull_quote`, `render_drop_cap_paragraph`, `render_eyebrow`, `render_label` |
| `studio_layouts/{magazine,throne,community_hub,gallery,authority,story_arc,movement,experience,clean_launch,celebration,studio_portfolio,empire_platform}.py` | Each: hero gradient overlay + decorative corners (per layout character), section dividers between major sections, `class="reveal"` on sections, `class="hover-lift"` on cards, motion script before `</body>`, vocab_id threaded |
| `studio_layouts/sections/{testimonials,gallery,resources,contact}.py` | `vocab_id` parameter added; hover-lift + reveal classes on cards/items; gradient backgrounds where appropriate |

### Files NOT touched

- `studio_data.py`, `studio_composite.py`, `studio_design_system.py`, `studio_vocab_detect.py` — Sessions 1+2 work, untouched (decoration READS from studio_data; doesn't modify it)
- `studio_layouts/dispatch.py` — unchanged
- `smart_sites.py`, `public_site.py`, `brand_engine.py`, `chief_of_staff.py` — production code unchanged
- All schema (no SQL migration; pure rendering)
- All frontend code (CSS variables only convention preserved — frontend untouched anyway)

## Backups

- `studio_design_system.py.pre-3-7.bak` (15,166 bytes)
- `studio_layouts/shared.py.pre-3-7.bak` (14,426 bytes)
- `studio_layouts.pre-3-7.bak/` directory containing all 15 files in `studio_layouts/` + 5 in `studio_layouts/sections/`

## Architectural invariants

- **Try/except every decoration call.** Single decoration's failure must NEVER break the page; falls through to undecorated section silently.
- **CSS-only motion.** No JS animation libraries. Scroll reveals via Intersection Observer (~30 lines vanilla JS, single inline script). Hover/marquee via CSS transitions/animation.
- **`prefers-reduced-motion: reduce` honored throughout.** Users with motion sensitivity see zero animation.
- **Mobile responsive.** Heavy decoration suppressed below 640px viewport via `@media` queries.
- **Deterministic.** Same vocab_id + design_system → same decoration output. No randomness.
- **Vocabulary drives decoration character.** Sovereign Authority gets thin gold lines; Faith Ministry gets soft glows + ornamental dividers; Expressive Vibrancy gets geometric shapes. Per-layout judgment in scope.
- **Decoration is purely additive.** Zero schema changes; existing sites become richer automatically on next render.
- **Public site router stays last** in registration.

## Rollback

### Symptom 1 — decoration breaks a layout

Try/except wrapping should catch this. If a layout IS broken, restore selectively:

```bash
cp studio_layouts.pre-3-7.bak/<layout>.py studio_layouts/<layout>.py
```

### Symptom 2 — motion not rendering

Verify `render_motion_script()` is included near `</body>` in each layout; check `<style>` block in head contains `.reveal` and `.hover-lift` classes.

### Symptom 3 — site looks worse not better for a specific vocabulary

Tune `get_vocab_accent_set()` mapping in `studio_decoration.py` for the affected vocabulary. Common tuning: change `divider_style` / `corner_treatment` / `gradient_intensity` for that specific vocab.

### Symptom 4 — full revert

```bash
git reset --hard pre-pass-3-7-20260505-1745
git push --force-with-lease origin main
```

Or selectively restore decoration files:

```bash
cp studio_design_system.py.pre-3-7.bak studio_design_system.py
cp studio_layouts/shared.py.pre-3-7.bak studio_layouts/shared.py
cp -r studio_layouts.pre-3-7.bak/* studio_layouts/
rm studio_decoration.py
rm studio_layouts/sections/typography.py
```

## Pre-build verification checklist

- [x] Backend on `main` clean (only untracked layout_previews/, not source)
- [x] Tag created and pushed (both repos)
- [x] `pass-3-7` branch created (backend only)
- [x] `.pre-3-7.bak` backups in place (12 layouts + 4 sections + shared + design system)
- [x] Return-point doc written
- [ ] User confirms Supabase backups healthy
- [ ] User confirms ready to proceed past PART 0
