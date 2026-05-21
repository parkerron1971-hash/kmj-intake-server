# Pass 4.0i — Schema Migration Notes

**Status:** No DDL required. This document records the JSONB shape convention introduced by Pass 4.0i.

---

## Why no SQL file

Pass 4.0h added physical columns (`businesses.use_composer`, `business_sites.hero_composer_module`) and shipped them as `PASS_4_0H_MIGRATIONS.sql` for reproducibility. Those needed `ALTER TABLE` statements because they were new top-level columns.

Pass 4.0i extends `business_sites.brand_kit` — already a `JSONB` column. JSONB columns accept arbitrary nested shape without DDL. The "migration" is purely a **schema convention** that application code (Composer agent + render layer + Brand Kit UI) reads and writes against. Existing brand_kit reads/writes continue unchanged.

If a future pass wants to enforce the shape at the database level (e.g., via a `CHECK` constraint with `jsonb_typeof` / `jsonb_path_exists`), that becomes its own DDL-bearing migration. Pass 4.0i deliberately keeps validation at the application layer for flexibility — the vocabulary (font_id values, accent_id values, intensity values) is expected to evolve as additional modules ship.

## The new JSONB shape

`business_sites.brand_kit` (existing `JSONB` column) gains a nested `creative_expression` object:

```json
{
  "brand_kit": {
    "colors": { ... existing ... },
    "fonts":  { ... existing typography fields ... },
    "tagline": "...",
    "elevator_pitch": "...",
    "tone_words": [...],
    "visual_style": "...",
    "creative_expression": {
      "font_id": "brutalist_default",
      "accent_id": "no_accent",
      "intensity": "restrained"
    }
  }
}
```

### Field reference

| Field | Type | Required | Valid values (Pass 4.0i — Studio Brut only) | Default behavior when missing |
|---|---|---|---|---|
| `creative_expression.font_id` | `string` | No | `brutalist_default` \| `brutalist_geometric` \| `brutalist_editorial` \| `brutalist_mono` \| `brutalist_sharp` | Composer defaults to `brutalist_default` |
| `creative_expression.accent_id` | `string` | No | `no_accent` \| `oversized_punctuation` \| `geometric_stamp` \| `type_initial` \| `code_label` \| `color_block_accent` | Composer defaults to `no_accent` unless brand archetype strongly suggests an accent (see PASS_4_0I_DESIGN.md §6.2) |
| `creative_expression.intensity` | `string` | No | `restrained` \| `confident` \| `bold` | Composer infers from brand archetype (authority → restrained, creative → confident, statement-making → bold) |

All three fields are optional. The entire `creative_expression` object is optional. A `brand_kit` with no `creative_expression` key behaves identically to pre-Pass-4.0i — Composer applies defaults across the board.

### Module compatibility

The `font_id` and `accent_id` valid-values lists above are **Studio Brut module only**. Pass 4.0i does not ship Cathedral or other modules' vocabularies — those land in Pass 4.0i.x and beyond.

If a business routes to Studio Brut via Module Router and the practitioner's brand_kit has `font_id: "editorial_classic"` (a future Cathedral value, not valid for Studio Brut), the Composer agent treats the field as if missing and applies the Studio Brut default. The Brand Kit UI (Phase D) prevents this at the source by only showing module-compatible options.

## Application-layer enforcement

Validation responsibilities, by component:

| Component | Responsibility |
|---|---|
| Brand Kit UI save handler (Phase D, `solutionist-studio`) | Only shows + writes values from the business's module's vocabulary. Strips unknown fields before save. |
| Composer agent (Phase C, `kmj-intake-server`) | Reads `brand_kit.creative_expression` if present. Validates each field is in this module's vocabulary; falls back to default per the table above on invalid or missing values. Output composition always contains a complete `creative_expression` object (no nulls). |
| Render layer (Phase B, `kmj-intake-server`) | Consumes the composition's `creative_expression` (always populated by Composer); does not re-read brand_kit. Applies font / accent / intensity per `agents/design_modules/studio_brut/hero/creative_expression/` modules. |

This pattern means the database never sees an invalid `creative_expression` — UI filters at write, Composer normalizes at read, render layer trusts Composer's normalized output.

## Canonical brand_kit storage location

The practitioner-facing Brand Kit panel writes via `POST /brand/save/{business_id}` → `brand_engine_router.py:43` → `brand_engine.save_brand_kit()`, which PATCHes **`businesses.settings.brand_kit`** (per Pass 4.0h.x diagnostic — `brand_engine.py:849-855`). This is the canonical brand_kit storage location.

Phase D's save handler MUST go through this canonical path. Phase C's Composer agent MUST read from this location (consistent with how `brand_kit_renderer.py:343-348` reads `businesses` → `settings` → `brand_kit` today). Do NOT write to `business_sites.brand_kit` — that column exists for legacy compatibility but is not the source of truth.

## Production verification query

Run via Supabase SQL Editor (or `psql`) to confirm shape adoption. Targets `businesses.settings.brand_kit` per the canonical location above.

```sql
SELECT
  b.id            AS business_id,
  b.business_name,
  b.settings -> 'brand_kit' ? 'creative_expression'                                AS has_ce,
  b.settings -> 'brand_kit' -> 'creative_expression' ->> 'font_id'                 AS font_id,
  b.settings -> 'brand_kit' -> 'creative_expression' ->> 'accent_id'               AS accent_id,
  b.settings -> 'brand_kit' -> 'creative_expression' ->> 'intensity'               AS intensity,
  b.updated_at
FROM businesses b
WHERE b.settings -> 'brand_kit' IS NOT NULL
ORDER BY b.updated_at DESC
LIMIT 20;
```

Expected results immediately post-Phase-A: **zero** rows with `has_ce = true`. No application code yet writes the field. Phase D's first save (or Phase C if Composer persists inferred values back to brand_kit) will be the first row to flip `has_ce = true`.

If `has_ce = true` rows appear with `font_id` / `accent_id` / `intensity` values not in the Pass 4.0i Studio Brut vocabulary, investigate — that indicates either UI bypass or schema drift. Application layers should be the only writers.

## Rollback

Per `PASS_4_0I_DESIGN.md` §9, rollback is application-only: revert merge commits, application code stops reading `creative_expression`, the JSONB field becomes dormant. No DDL to roll back; no data to migrate; no Supabase backup-restore required. The field lives in the JSONB indefinitely until a future cleanup pass chooses to strip it (low priority — JSONB cost is negligible).

## Cross-reference

- Authoritative design: `agents/composer/PASS_4_0I_DESIGN.md`
- Phase 4.0h precedent (last DDL-bearing migration): `agents/composer/PASS_4_0H_MIGRATIONS.sql`
- Brand kit save path: `brand_engine.py::save_brand_kit` (line 827) — Phase D save handler routes through `/brand/save/{business_id}` which calls this function.
- Brand kit read path during render: `agents/design_intelligence/brand_kit_renderer.py:343-348` — Phase B's `font_resolver` / `accent_renderer` / `intensity_translator` consume the same source (`businesses.settings.brand_kit`) at render time, mediated by Composer's normalized output.
