# Pass 3.6 — Smart Sites Section Completion — Return Point (Backend)

## Pre-flight

- **Tag**: `pre-pass-3-6-20260505-1209` (pushed to origin)
- **Branch**: `pass-3-6` (created from `main`)
- **Base commit**: `a5d57e7` (Fix archetype source in Studio layout dispatch)

## Scope

Adds testimonials, gallery, resources, and contact sections to all 12 Smart Sites layouts via a hybrid pattern (shared vocabulary-aware components by default + bespoke overrides where the section IS the layout's character). Wires Stripe checkout for products with `stripe_payment_url`. Adds backend contact form submission via Resend with per-IP rate limiting. Extends MySite UI to edit all new section content.

## Files this session adds or modifies

### Backend
| File | Change |
|------|--------|
| `studio_layouts/sections/__init__.py` | NEW — empty package marker |
| `studio_layouts/sections/testimonials.py` | NEW — shared testimonials renderer |
| `studio_layouts/sections/gallery.py` | NEW — shared gallery renderer |
| `studio_layouts/sections/resources.py` | NEW — shared resources / lead-magnets renderer |
| `studio_layouts/sections/contact.py` | NEW — shared contact-info + form renderer (with inline JS for submit) |
| `studio_layouts/community_hub.py` | Adds bespoke `render_testimonials` + wires 4 new sections |
| `studio_layouts/studio_portfolio.py` | Adds bespoke `render_gallery` + wires 4 new sections |
| `studio_layouts/gallery.py` | Adds bespoke `render_gallery` (image-first masonry) + wires 4 new sections |
| `studio_layouts/movement.py` | Adds bespoke `render_contact` + wires 4 new sections |
| `studio_layouts/{magazine,throne,authority,story_arc,experience,clean_launch,celebration,empire_platform}.py` | Wires 4 new sections (shared renderers only) + Stripe button in services |
| `smart_sites.py` | Extends `DEFAULT_SITE_CONFIG` with testimonials/gallery/resources/contact section keys |
| `public_site.py` | NEW endpoint `POST /sites/{business_id}/contact-submit` with Resend integration + 5-req/min/IP rate limit |

### Files NOT touched

- `studio_data.py`, `studio_composite.py`, `studio_design_system.py`, `studio_vocab_detect.py` — Sessions 1+2 work, unchanged
- `studio_layouts/shared.py`, `studio_layouts/dispatch.py` — unchanged
- `brand_engine.py`, `chief_of_staff.py` — production code unchanged
- All schema (no SQL migration; new keys land in JSONB site_config as users opt in)

## Backups

- `smart_sites.py.pre-3-6.bak` (52,682 bytes)
- `public_site.py.pre-3-6.bak` (103,788 bytes)
- `studio_layouts.pre-3-6.bak/` directory containing all 15 files in `studio_layouts/`

## site_config schema additions (no migration; JSONB)

```json
{
  "sections": {
    "testimonials": {
      "enabled": false,
      "heading": "What clients say",
      "items": [{ "quote": "...", "author": "...", "role": "...", "date": "..." }]
    },
    "gallery": {
      "enabled": false,
      "heading": "Gallery",
      "items": [{ "image_url": "...", "caption": "...", "order": 0 }]
    },
    "resources": {
      "enabled": false,
      "heading": "Free Resources",
      "subtext": null,
      "items": [{ "title": "...", "description": "...", "link": "...", "type": "pdf|video|audio|link|doc" }]
    },
    "contact": {
      "enabled": false,
      "heading": "Get in touch",
      "subtext": null,
      "email": null,
      "phone": null,
      "address": null,
      "show_form": true
    }
  }
}
```

All four sections default to `enabled: false` so no site suddenly grows new content from this deploy. Users opt in via the MySite editor or directly via `/sites/{id}/smart-config`.

## Architectural invariants

- **Try/except per section.** Every section render call in every layout is wrapped — a single section's failure must NEVER break the page.
- **Hybrid section architecture.** Shared vocabulary-aware components by default. Bespoke overrides only where a section IS the layout's identity (community_hub testimonials, studio_portfolio gallery, gallery layout's gallery, movement contact).
- **No new schema.** site_config is JSONB; new keys are additive.
- **CSS variables only on new frontend code.** Zero hex codes on MySite additions.
- **Public site router stays last.** Catch-all in `kmj_intake_automation.py`.
- **Resend reuses existing pattern.** RESEND_API_KEY env var must be set on Railway (it already is from earlier email infrastructure).
- **Stripe URLs are passed verbatim** through `safe_html` (no normalization); detection is purely `if product.stripe_payment_url`.

## Rollback

### Symptom 1 — a section breaks the page

The try/except wrapping should prevent this. If a section IS breaking, check that the wrapping is in place around its render call.

### Symptom 2 — contact form 500s

Check Railway logs. Likely RESEND_API_KEY missing (already set from earlier email infrastructure but verify) or invalid.

### Symptom 3 — Stripe URL not rendering

Verify `products.stripe_payment_url` is populated. If empty, no button shows by design.

### Symptom 4 — full revert

```bash
git reset --hard pre-pass-3-6-20260505-1209
git push --force-with-lease origin main
```

Or selectively restore:

```bash
cp smart_sites.py.pre-3-6.bak smart_sites.py
cp public_site.py.pre-3-6.bak public_site.py
cp studio_layouts.pre-3-6.bak/* studio_layouts/
rm -rf studio_layouts/sections/
```

## Pre-build verification checklist

- [x] Backend on `main` clean (only untracked layout_previews/, not source)
- [x] Tag created and pushed (both repos)
- [x] `pass-3-6` branch created (both repos)
- [x] `.pre-3-6.bak` backups in place (both repos, incl. all 12 layouts)
- [x] Return-point docs written
- [ ] User confirms Supabase backups healthy
- [ ] User confirms ready to proceed past PART 0
