# Pass 4.0i — Hero Creative Expression Layer: Design Document

**Branch:** `pass-4-0i-hero-creative-expression` (mirrored on `kmj-intake-server` + `solutionist-studio`)
**Author:** Pass 4.0i Phase A
**Status:** DESIGN — Phase A. Phase B-E implementation pending Phase A checkpoint approval.

---

## 1. Purpose

Pass 4.0g shipped two design modules. Pass 4.0h wired the multi-module pipeline into production and activated the first practitioner (RoyalTeez Designz, Studio Brut module). Pass 4.0h.x/y/z hardened the Builder pipeline.

Hero sections still feel uniform within a module — two Studio Brut businesses get the same font stack, same ornament vocabulary, same intensity. Practitioners can express creative identity through brand kit colors but nothing beyond.

Pass 4.0i adds three coordinated creative-expression dimensions to the Composer Hero pipeline so that the same module DNA produces visibly different brand-specific Heros:

1. **Font selection** from a module-curated set (different typographic voices within the same aesthetic)
2. **Optional decorative accent** (signature moment or restrained absence)
3. **Statement intensity** (how dramatically the Hero declares)

## 2. Scope

**IN scope for Pass 4.0i:**

- Studio Brut module only (Composer pipeline, active in production via RoyalTeez)
- 5 Studio Brut font options, Google Fonts only
- 6 Studio Brut accent options (5 accents + `no_accent` default)
- 3 intensity levels (`restrained` / `confident` / `bold`), module-agnostic
- Composer prompt + output schema extension to consume creative expression choices
- Render layer changes to apply font / accent / intensity in served HTML
- Brand Kit panel UI in Studio Studio frontend (Phase D, cross-repo)
- JSONB schema convention on `business_sites.brand_kit.creative_expression` — no DDL

**OUT of scope for Pass 4.0i — explicitly deferred:**

- **Cathedral creative expression vocabulary.** Cathedral exists as a Composer module in code (Pass 4.0g cherry-picked variants/treatments/primitives, Module Router can route to it, Composer can compose with it) but no practitioner runs Cathedral-through-Composer today. KMJ uses `cinematic_authority` via the Builder pipeline (`use_composer=false`), not Composer. Shipping Cathedral creative expression vocabulary without a verification target is dormant scaffolding — deferred to **Pass 4.0i.x** when a Cathedral-through-Composer practitioner activates.
- **Adobe Fonts integration.** Multi-tenant Adobe Fonts licensing is murky enough to require legal review. All Pass 4.0i font options are Google Fonts. If practitioners specifically request premium faces (Druk, Söhne, PP fonts, Saol, Recoleta), they become a Pass 4.0i.x or 4.0k follow-on.
- **Builder pipeline creative expression.** KMJ, ETS, Director Loop Test (all `use_composer=false`) get nothing from Pass 4.0i. The Builder Agent prompt has absorbed Pass 4.0d, 4.0h.x, 4.0h.y, and 4.0h.z tuning; piling creative expression vocabulary on top would bloat the prompt past LLM context-effectiveness AND require the same render-layer scaffolding to be wired into the Builder serve path. Both are scope creep.

## 3. Three creative-expression components

### 3.1 Studio Brut font vocabulary (FINALIZED Phase B)

**Ownership rule** (locked Phase B finalize, after a visual review of the original 5-sans vocabulary showed convergence):

| Layer | Owns |
|---|---|
| **Font choice** (`font_id`) | typeface (font-family), text-transform (case), base letter-spacing character |
| **Intensity** (`intensity`) | final h1 size + weight TIER (800 vs 900) via the two-sided clamp |
| **Treatments** (`treatments.*`) | color, emphasis span style, layout, everything else |

Precedence is expressed in CSS via var-with-fallback chains in the primitives (`heading.py` reads `var(--hero-text-transform, var(--sb-heading-case, none))`), NOT via dict-merge ordering. The Pass 4.0h.x lesson — cascade-order fragility for `:root { --brand-* }` collisions — is the reason we keep the namespaces distinct and precedence CSS-level-explicit.

#### Vocabulary change from the original Phase A spec

Original Phase A vocabulary (5 sans-serifs, uniform uppercase-heavy treatment) caused visual convergence in the first review — the variant's hardcoded uppercase + 900-weight + tight tracking flattened font personality across all 5. Path B prototype validated a spread across font categories WITH per-font case/weight/tracking signatures. The finalized vocabulary below replaces the original:

| Original (Phase A) | → | Finalized (Phase B post-prototype) |
|---|---|---|
| `brutalist_default` (Bebas Neue) | kept (retained, signature explicit) | `brutalist_default` |
| `brutalist_wide` (Oswald) | **DROPPED** (too sibling-similar to default) | — |
| `brutalist_geometric` (Bricolage Grotesque) | kept, signature explicit | `brutalist_geometric` |
| `brutalist_display` (DM Serif Display) | **RENAMED** to clearer label | `brutalist_editorial` |
| — | **ADDED** (technical voice / mono category) | `brutalist_mono` (Space Mono) |
| `brutalist_sharp` (Inter) | kept, signature explicit | `brutalist_sharp` |

#### `brutalist_default`

- **Display:** `'Bebas Neue', Impact, sans-serif` · **Body:** `'Space Grotesk', system-ui, sans-serif`
- **Signature:** case `UPPERCASE` · base-weight 800 · tracking `-1.6px`
- **Character:** condensed poster, urban streetwear, narrow stacked-display authority
- **Best for:** streetwear, custom apparel, design studios with edge

#### `brutalist_geometric`

- **Display:** `'Bricolage Grotesque', 'Helvetica Neue', sans-serif` · **Body:** `'Inter', system-ui, sans-serif` · **Code accent:** `'JetBrains Mono', ui-monospace, monospace`
- **Signature:** case `UPPERCASE` · base-weight 700 · tracking `-0.5px`
- **Character:** engineered precision, architectural, machined geometric
- **Best for:** tech-adjacent creative, design firms, makers with precision aesthetic

#### `brutalist_editorial`

- **Display:** `'DM Serif Display', Georgia, serif` · **Body:** `'Space Grotesk', system-ui, sans-serif`
- **Signature:** case **`MIXED`** · base-weight 400 · tracking `-0.5px` · `weight_locked=True`
- **Character:** serif display, editorial-maker dialect, mixed-case authority
- **Best for:** writers, publishers, narrative-driven brands, design-aware editorial voices
- **Key role:** the serif that breaks the uppercase mold. Validates the spread-across-categories thesis.
- **Weight-lock note:** DM Serif Display ships single-weight at 400. `font_resolver` emits `--hero-font-fixed-weight: 400`; primitive's chain `var(--hero-font-fixed-weight, var(--hero-display-weight, ...))` resolves to 400 regardless of intensity, so bold-intensity editorial Heros render with size + scale drama, not synthesized faux-bold on serif display type.

#### `brutalist_mono`

- **Display:** `'Space Mono', 'JetBrains Mono', ui-monospace, monospace` · **Body:** `'Space Grotesk', system-ui, sans-serif` · **Code accent:** `'Space Mono', 'JetBrains Mono', ...` (mono itself doubles as code accent)
- **Signature:** case `UPPERCASE` · base-weight 700 · tracking `0.05em` (wide)
- **Character:** technical voice, code aesthetic, wide-tracked monospace
- **Best for:** developer tools, technical creative, software studios, makers with code-native aesthetic

#### `brutalist_sharp`

- **Display:** `'Inter', system-ui, sans-serif` · **Body:** `'Manrope', system-ui, sans-serif`
- **Signature:** case **`MIXED`** · base-weight 900 · tracking `-0.5px`
- **Character:** refined-heavy, considered-fashion, mixed-case minimal
- **Best for:** premium streetwear, design-aware fashion, considered urban brands

#### Intensity-vs-font weight resolution (the editorial special case)

Intensity emits `--hero-display-weight` (800 for restrained/confident, 900 for bold). Font emits `--hero-font-fixed-weight` **only when `weight_locked=True`** (currently brutalist_editorial only). Primitive's chain:

```css
font-weight: var(--hero-font-fixed-weight, var(--hero-display-weight, var(--sb-heading-weight, 800)));
```

- **Most fonts** (unlocked): `--hero-font-fixed-weight` unset → chain falls through to intensity's `--hero-display-weight` → bold intensity = 900 weight rendered.
- **Editorial** (locked at 400): `--hero-font-fixed-weight` = 400 → chain stops there → bold intensity does NOT synthesize faux-bold on DM Serif Display. The serif renders at its authentic 400. Bold intensity still increases size via `--hero-h1-font-size`, just not weight.

Decision rationale: faux-bold synthesis on single-weight serif display faces produces visually-rough fake-bold characters (browsers algorithmically thicken glyph outlines), which undermines the editorial signature. Better to let intensity drive size and let the font's authentic weight stand.

Module-compatibility check: practitioner's `font_id` must be a Studio Brut option. Cross-module picks (e.g., Cathedral font on Studio Brut business) are rejected at save and default applied at render.

### 3.2 Studio Brut accent vocabulary

Six options including `no_accent` default. Each accent is a small graphic element the variant template conditionally renders. All use `--brand-signal` primarily, `--brand-authority` for contrast situations.

Module-compatibility check: practitioner's `accent_id` must be a Studio Brut option OR `no_accent` (universal). Cross-module picks rejected.

#### `no_accent` (default)

- Clean Hero without decorative additions.
- Variant template renders unchanged.
- Use case: practitioner wants the variant + treatment + font to carry the brand alone.

#### `oversized_punctuation`

- Single oversized punctuation mark as a graphic element (large open quote, oversized ampersand, dramatic exclamation, em-dash).
- Render: large display-font character at ~3x the heading size, positioned absolutely relative to heading.
- Color: `var(--brand-signal)`.
- Composer reasoning section recommends which mark based on brand voice.

#### `geometric_stamp`

- Geometric shape (circle, square, hexagon) with short text inside.
- Text content example: business initials, "EST. YYYY", category label.
- Render: SVG inline, sized ~80-120px, positioned per variant.
- Color: `--brand-authority` background, `--brand-text-on-authority` text.

#### `type_initial`

- First letter of heading at massive scale, treated as a graphic element. **Distinct from Cathedral's future `manuscript_drop_cap`** — type_initial is brutalist (sans-serif, full-bleed, often positioned overlapping image or background), drop cap is editorial (serif, illuminated, smaller scale, in-line with text).
- Render: pseudo-element or sibling span, font-size ~6-10rem, positioned absolutely or with negative margin.
- Color: `--brand-signal` with optional `mix-blend-mode: difference` for layered effect.

#### `code_label`

- Vertical or horizontal monospace text mark, brand-specific.
- Content examples: `VOL.II`, `SVC.04`, `EST.2026`, `NO.001`.
- Render: `<span>` with `font-family: 'JetBrains Mono'`, `letter-spacing: 0.2em`, `text-transform: uppercase`.
- Color: `--brand-signal`.
- Composer generates the content text from business context (year founded, service line number, etc.).

#### `color_block_accent`

- Small colored geometric shape (rectangle, parallelogram, dot cluster) positioned for visual interest.
- Render: pure CSS (no SVG needed).
- Color: `--brand-signal` background, optional `--brand-authority` border or shadow.
- Often used as visual punctuation near heading start.

### 3.3 Intensity treatment

Three levels. Module-agnostic — same three levels apply to any Composer module.

Intensity adjusts the **magnitude** of design choices within a variant's layout; it does not change variant shape. A `restrained` `edge_bleed_portrait` is the same structural composition as a `bold` `edge_bleed_portrait` — just with conservative vs. maximum scale/contrast/treatment-amplitude.

| Level | Multiplier | Display character (Studio Brut) | Selected font-weight for h1 |
|---|---|---|---|
| `restrained` | 1.0× | graphic-considered, breathing room, single dominant element | 800 |
| `confident` | 1.15× | graphic-confident, present, layered visual cues | 800 |
| `bold` | 1.3× | graphic-loud, poster-energy, maximum drama within module DNA | 900 |

#### How multipliers apply

A variant template defines base CSS variable values. The render layer multiplies those bases by the intensity multiplier and applies a two-sided clamp against the rubric floor and a sanity ceiling:

```
effective_size = max(min(base × multiplier, rubric_max_or_sanity_ceiling), rubric_min)
```

For example, a variant with `--hero-h1-min-rem: 4.0` (base, restrained) at `bold` intensity:

```
base       = 4.0 rem
multiplier = 1.3
candidate  = 5.2 rem
clamped    = max(min(5.2, sanity_ceiling=10), rubric_min=3.0) = 5.2 rem ✓
```

A poorly-authored variant with `--hero-h1-min-rem: 2.5` (below rubric floor at restrained):

```
base       = 2.5 rem
multiplier = 1.0 (restrained)
candidate  = 2.5 rem
clamped    = max(min(2.5, 10), 3.0) = 3.0 rem  → forced up to floor
```

The two-sided clamp prevents rubric violations *regardless of variant author error*. Phase B will additionally ship a smoke test that fails CI if any variant × intensity combination would have been clamped — variant authors should pick base values that pass restrained without clamp intervention, but if they don't, render is still safe.

#### What intensity scales

- `--hero-h1-min-rem` and `--hero-h1-max-rem` (clamp values for hero h1 font-size)
- `--hero-h2-min-rem` and `--hero-h2-max-rem` (clamp values for section h2)
- `--hero-element-spacing` (gap between Hero stacked elements)
- `--hero-treatment-amplitude` (intensity of background_treatment, color_depth_treatment, ornament_treatment — multiplies opacity/scale/offset within each treatment's render)
- `--hero-letter-spacing-em` (negative letter-spacing on display headings; tighter at bold)
- Font weight selection per the table above

## 4. Rubric thresholds (Phase B inputs)

From `agents/design_intelligence/rubrics/cinematic_authority_rubric.json` (`rubric_version: 4.0d.3`). The cinematic_authority rubric is currently the only rubric on disk; until a Studio Brut-specific rubric ships, Studio Brut variants will be checked against these floors. They are conservative for Studio Brut's poster aesthetic — most Studio Brut variants will naturally exceed them.

| Rule ID | Selector | Threshold | Pass paths |
|---|---|---|---|
| `hero_h1_size` (HIGH) | `h1, .hero h1, [data-section='hero'] h1, header h1` | font-size ≥ 76px OR clamp min ≥ 3rem | parsed_px ≥ 76 OR clamp-min-rem ≥ 3.0 |
| `hero_h1_weight` (HIGH) | same | font-weight ∈ {800, 900} | exact string match |
| `hero_h1_letter_spacing` (MEDIUM) | same | between -3px and -1px | negative letter-spacing in range |
| `section_h2_size` (HIGH) | `h2, section h2` | font-size ≥ 48px OR clamp min ≥ 2rem | parsed_px ≥ 48 OR clamp-min-rem ≥ 2.0 |
| `section_h2_weight` (HIGH) | same | font-weight ∈ {800, 900} | exact string match |

No explicit ceilings on h1/h2 size in the rubric. Pass 4.0i adopts a **sanity ceiling** of `10rem` for h1, `6rem` for h2, applied in the two-sided clamp. These ceilings are not rubric-driven — they are layout-sanity-driven (prevents bold-intensity Heros from line-breaking pathologically at extreme viewports). Adjustable in `intensity_translator.py` if Phase B testing surfaces issues.

Letter-spacing intensity progression:
- restrained: `-1.6px` (within MEDIUM bracket, mid-conservative)
- confident: `-2.4px` (rubric `fix_hint` recommendation)
- bold: `-3px` (max tight, edge of MEDIUM bracket)

## 5. Brand kit schema extension

`business_sites.brand_kit` JSONB column. Extends in place — no DDL, no new columns. See `agents/composer/PASS_4_0I_MIGRATIONS.md` for the convention and the production verification query.

```json
{
  "brand_kit": {
    "colors": { ... existing ... },
    "fonts": { ... existing typography fields ... },
    "creative_expression": {
      "font_id": "brutalist_default" | "brutalist_geometric" | "brutalist_editorial" | "brutalist_mono" | "brutalist_sharp",
      "accent_id": "no_accent" | "oversized_punctuation" | "geometric_stamp" | "type_initial" | "code_label" | "color_block_accent",
      "intensity": "restrained" | "confident" | "bold"
    }
  }
}
```

All three fields under `creative_expression` are optional. Composer applies defaults per Section 6 when missing.

Module-compatibility validation lives in application code (Composer agent + Brand Kit UI save handler), not the schema. The JSONB column accepts arbitrary shape; the application layer enforces validity.

## 6. Composer agent extensions

### 6.1 Output schema

`HeroComposition` model gains a `creative_expression` field:

```python
class CreativeExpression(BaseModel):
    font_id: str
    accent_id: str
    intensity: Literal['restrained', 'confident', 'bold']

class HeroComposition(BaseModel):
    section: Literal['hero']
    variant: str
    module: str
    treatments: dict  # existing 8 fields
    content: dict     # existing fields
    creative_expression: CreativeExpression  # NEW
    reasoning: str
```

### 6.2 Composer prompt additions

The Studio Brut Composer prompt gains three sections:

**FONT SELECTION GUIDANCE.** Lists the 5 Studio Brut font options with character + best-for description (Section 3.1 above, condensed). The Composer's contract:

> If `brand_kit.creative_expression.font_id` is provided AND valid for this module, USE IT. Honor practitioner choice.
> If not provided OR not valid for this module, select the font_id that best fits the brand archetype inferred from the enriched brief. Explain the choice in the reasoning section.

**ACCENT SELECTION GUIDANCE.** Lists the 6 Studio Brut accent options with description and visual character.

> If `brand_kit.creative_expression.accent_id` is provided, USE IT — including `no_accent` as an explicit practitioner choice.
> If not provided, default to `no_accent` unless the brand archetype strongly suggests a specific accent (e.g., founded-year businesses → `code_label` with EST.YYYY; design-firm businesses → `geometric_stamp`). When defaulting to an accent, explain in reasoning; conservative default is always `no_accent`.

**INTENSITY SELECTION GUIDANCE.** Lists the 3 intensity levels with character description.

> If `brand_kit.creative_expression.intensity` is provided, USE IT.
> If not provided, infer from brand archetype:
> - authority/established/professional brands → `restrained`
> - creative/personality-led/maker brands → `confident`
> - statement-making/identity-forward/loud brands → `bold`
> When inferring, explain in reasoning.

### 6.3 Cost forecast (recalibrated)

Composer prompt grows by ~400 input tokens (font vocabulary ~100, accent vocabulary ~180, intensity guidance ~120). Output grows by ~50 tokens (`creative_expression` JSON object + extended reasoning).

At Sonnet 4.6 pricing, per-Composer-call cost moves from ~$0.05 → ~$0.06 (≈25-30% increase, not the 10-15% claimed in the original planning doc). Negligible in absolute terms at expected build volume.

## 7. Render layer integration

### 7.1 Module structure

New subdirectory: `agents/design_modules/studio_brut/hero/creative_expression/`:

```
agents/design_modules/studio_brut/hero/creative_expression/
├── __init__.py
├── font_resolver.py        # font_id → CSS variables + Google Fonts <link> tags
├── accent_renderer.py      # accent_id → accent HTML fragment (or empty for no_accent)
└── intensity_translator.py # intensity → CSS variable multiplier dict + clamped values
```

### 7.2 Font loading

`font_resolver.resolve(font_id) -> dict` returns:

```python
{
    "css_vars": {
        "--hero-font-display": "'Bebas Neue', 'Anton', Impact, sans-serif",
        "--hero-font-body": "'Space Grotesk', sans-serif",
        "--hero-font-code": None,  # set for brutalist_geometric only
    },
    "google_fonts_link": (
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Space+Grotesk:wght@400;500;700&display=swap" rel="stylesheet">'
    ),
}
```

CSS variables scoped to `<section data-section="hero">` — does NOT leak to Builder's rest-of-site styles. Builder section h2/body keep their existing typography per Builder prompt.

Google Fonts URL uses `display=swap` to avoid FOUT-blocking. `preconnect` minimizes connection setup. Per-business font load is two Google Font requests at most (display + body), weight-subset per Section 3.1.

### 7.3 Accent rendering

`accent_renderer.render(accent_id, brand_kit, business_context) -> str` returns either an empty string (for `no_accent`) or an accent HTML fragment.

Variant templates check the composition and conditionally include the fragment:

```python
def render_hero_variant(composition, brand_kit, business_context, ...):
    ce = composition.creative_expression
    accent_html = accent_renderer.render(ce.accent_id, brand_kit, business_context)
    # Variant decides WHERE to position the accent — varies by variant
    return f"""
      <section data-section="hero">
        {render_eyebrow(...)}
        {accent_html}
        {render_heading(...)}
        ...
      </section>
    """
```

Accent positioning is variant-specific. `edge_bleed_portrait` might position accent in left margin; `color_block_split` might position accent overlapping the color block. Each variant decides the slot.

`accent_renderer` for `code_label` accepts business_context to derive the label text (year founded, service line number, etc.). Other accents are content-free (pure decorative).

### 7.4 Intensity translation with two-sided clamp

`intensity_translator.translate(intensity, variant_base) -> dict` returns the final CSS variable values after multiplier + clamp:

```python
RUBRIC_FLOORS = {"hero_h1_rem": 3.0, "hero_h2_rem": 2.0}
SANITY_CEILINGS = {"hero_h1_rem": 10.0, "hero_h2_rem": 6.0}
MULTIPLIERS = {"restrained": 1.0, "confident": 1.15, "bold": 1.3}
H1_WEIGHTS = {"restrained": "800", "confident": "800", "bold": "900"}
LETTER_SPACING = {"restrained": "-1.6px", "confident": "-2.4px", "bold": "-3px"}

def translate(intensity: str, variant_base: dict) -> dict:
    m = MULTIPLIERS[intensity]
    h1_min_raw = variant_base["h1_min_rem"] * m
    h1_max_raw = variant_base["h1_max_rem"] * m
    h2_min_raw = variant_base["h2_min_rem"] * m
    h2_max_raw = variant_base["h2_max_rem"] * m

    h1_min = max(min(h1_min_raw, SANITY_CEILINGS["hero_h1_rem"]), RUBRIC_FLOORS["hero_h1_rem"])
    h1_max = max(min(h1_max_raw, SANITY_CEILINGS["hero_h1_rem"]), RUBRIC_FLOORS["hero_h1_rem"])
    h2_min = max(min(h2_min_raw, SANITY_CEILINGS["hero_h2_rem"]), RUBRIC_FLOORS["hero_h2_rem"])
    h2_max = max(min(h2_max_raw, SANITY_CEILINGS["hero_h2_rem"]), RUBRIC_FLOORS["hero_h2_rem"])

    h1_vw = variant_base["h1_vw"] * m
    h2_vw = variant_base["h2_vw"] * m

    return {
        "--hero-h1-font-size": f"clamp({h1_min:.2f}rem, {h1_vw:.1f}vw, {h1_max:.2f}rem)",
        "--hero-h1-font-weight": H1_WEIGHTS[intensity],
        "--hero-h1-letter-spacing": LETTER_SPACING[intensity],
        "--hero-h2-font-size": f"clamp({h2_min:.2f}rem, {h2_vw:.1f}vw, {h2_max:.2f}rem)",
        "--hero-h2-font-weight": H1_WEIGHTS[intensity],
        "--hero-element-spacing-multiplier": str(m),
        "--hero-treatment-amplitude": str(m),
    }
```

The two-sided clamp at lines `h1_min = max(min(...))` and `h2_min = max(min(...))` is the safety net: a variant author who picks `h1_min_rem: 2.5` (below rubric floor at restrained) will silently get `3.0rem` instead. Rubric never fails because of intensity math.

### 7.5 Where the render layer wires in

`post_process_hero` already replaces the Builder's Hero with a Composer-generated one. Pass 4.0i adds creative-expression application as the last step before returning replaced HTML:

```
Composer composition JSON → render variant template → render_hero_fragment →
  → apply font_resolver (inject <link> + CSS vars in <style> block at top of fragment)
  → apply accent_renderer (already included in variant template via conditional)
  → apply intensity_translator (inject computed CSS vars in same <style> block)
  → return final fragment
```

The `<style>` block for Pass 4.0i creative expression sits INSIDE the Hero `<section>` so its CSS variables are scoped only to the Hero. Builder's rest-of-site styles are unaffected.

## 8. Cross-repo coordination

| Phase | Repo | Branch | Files |
|---|---|---|---|
| A (this) | kmj-intake-server | `pass-4-0i-hero-creative-expression` | `agents/composer/PASS_4_0I_DESIGN.md`, `agents/composer/PASS_4_0I_MIGRATIONS.md` |
| A (this) | solutionist-studio | `pass-4-0i-hero-creative-expression` | empty (frontend has no Phase A work) |
| B | kmj-intake-server | same | `agents/design_modules/studio_brut/hero/creative_expression/` (new dir + 3 modules); ~10 variant files updated |
| C | kmj-intake-server | same | Studio Brut Composer prompt extension; Pydantic schema extension; tests |
| D | solutionist-studio | same | Brand Kit panel new sections in `src/features/brand-kit/` (or equivalent); save handler |
| E | kmj-intake-server | same | RoyalTeez integration verification — single Composer-pipeline build trigger |
| F | both | same | Decision record at `agents/composer/PASS_4_0I_DECISION_RECORD.md`; both branches merge to respective main branches |

### 8.1 Hard dependency: A → D

Phase A defines the JSONB shape. Phase D writes to that shape from the UI. If Phase D ships to the frontend repo before Phase A's JSONB convention is established in backend code that READS the shape, the UI writes succeed but Composer ignores them. Order: Phase A → B → C (backend consumers in place) → D (frontend writers) → E (integration verification).

### 8.2 Branch mirroring

Both repos use the same branch name `pass-4-0i-hero-creative-expression`. Frontend branch sits empty (no commits) until Phase D. Backend branch accumulates Phase A → C → E commits.

### 8.3 Merge cadence

Per Phase F, both branches merge to their respective `main` branches on the same checkpoint. Standard isolation: no incremental merges, no opt-in flag. If anything wrong surfaces in Phase E, both branches revert.

## 9. Failure modes + rollback

### Failure Mode 1 — Font load adds significant page weight

Per Section 7.2, each font_id resolves to two Google Font HTTP requests (display + body), weights subset to 1-3 weights each. Estimated payload: 30-80KB total per font_id (varies by face — Bebas Neue is tiny, Bricolage Grotesque variable font is heavier).

Combined with Builder's existing Google Fonts load (Playfair Display + Inter + JetBrains Mono on KMJ-style Builder output), Pass 4.0i additions to a Composer-rendered Hero add roughly 30-80KB. Acceptable.

Mitigation: `preconnect` + `display=swap` per Section 7.2. If Phase E surfaces a perf regression on RoyalTeez, swap to subset-only weights (e.g., `Bebas+Neue:400` plus `Space+Grotesk:wght@500;700` only).

### Failure Mode 2 — Composer over-defaults on creative expression

Symptom: Composer ignores `brand_kit.creative_expression` and uses module defaults regardless of practitioner choice.

Mitigation: Strong prompt enforcement (Section 6.2 "USE IT" language). Phase C validation step: after Composer returns composition, verify `composition.creative_expression == brand_kit.creative_expression` for any field where brand_kit has a value. If mismatch, retry once with explicit "PRACTITIONER CHOICE OVERRIDE" punch list. If still mismatched, log and ship Composer's choice (best-effort).

### Failure Mode 3 — Variant rendering breaks at certain intensity values

Symptom: bold intensity pushes clamp() values past readability or layout-breaking thresholds at extreme viewports.

Mitigation: Two-sided clamp in `intensity_translator.py` (Section 7.4) — `effective = max(min(base × multiplier, sanity_ceiling), rubric_floor)`. Rubric violations impossible. Sanity ceilings (h1 10rem, h2 6rem) cap maximum at readable level. Phase B smoke test verifies every variant × every intensity combination satisfies rubric without forced-clamp intervention (catches variants that would be silently clamped — that's an author error worth surfacing).

### Failure Mode 4 — Cross-repo branch drift

Symptom: backend branch ships Phase A-C, frontend branch ships Phase D, but the JSONB shape Phase D writes doesn't match what Phase A defined.

Mitigation: Phase A design doc (this file) is the contract. Phase D consumes the contract verbatim. Phase E integration verification confirms the round-trip works on a real Composer build. If shape drift detected in Phase E, fix in either repo before Phase F merge.

### Rollback path

Pass 4.0i feature-isolated to the Composer pipeline. If Pass 4.0i breaks production after Phase F merge:

1. Revert merge commit on `kmj-intake-server/main`.
2. Revert merge commit on `solutionist-studio/main`.
3. `brand_kit.creative_expression` JSONB fields remain in the schema but unused — application code ignores them.
4. RoyalTeez serves Composer Hero per pre-Pass-4.0i behavior (Studio Brut defaults).
5. No data loss; no Supabase rollback needed.

## 10. Phase B → E sequence

### Phase B — Render layer (~3-4 hours, $0 LLM)

Implement `creative_expression/` directory with three modules. Update ~10 Studio Brut variant files to consume new CSS variables and conditionally render accent fragments. Smoke tests for every variant × every (font, accent, intensity) combination — verifies rubric satisfaction at restrained without clamp intervention.

### Phase C — Composer agent updates (~2 hours, ~$0.30 LLM)

Studio Brut Composer prompt extension. Pydantic `HeroComposition` schema extension. Phase C smoke: trigger Composer (mocked or live) on a synthetic Studio Brut brief without `brand_kit.creative_expression`; verify Composer returns valid defaults inferred from archetype. Validation step that compares Composer output to brand_kit input.

### Phase D — Brand Kit UI (~3-4 hours, $0 LLM)

`solutionist-studio` frontend. Brand Kit panel gains three new sections (font selector, accent selector, intensity selector). Module-compatible filtering (only Studio Brut options shown for Studio Brut businesses, hidden otherwise). Save handler writes to `brand_kit.creative_expression`. UI default state: first option pre-selected (matches Composer's `brutalist_default` / `no_accent` / archetype-inferred-intensity defaults).

### Phase E — Integration verification (~1 hour, ~$0.30 LLM)

Single Composer-pipeline build trigger against RoyalTeez (or a designated test Studio Brut business). Verify end-to-end:
- Brand kit choices persist via UI
- Composer reads + honors them
- Render layer applies font / accent / intensity
- Live site reflects all three choices visually
- No regression on Pass 4.0h.x/y/z fixes (still 0 inline event handlers, still 1 `:root` block defining `--brand-*`, brand kit colors still flow)

Note: per parked item L15, observability of the Composer rebuild may be limited from this Windows host (connection RST mid-request). Verification falls back to live-HTML inspection. Triggering the rebuild from Studio Studio frontend (Tauri shell) may avoid the RST and surface the structured audit payload.

### Phase F — Decision record + merge (~30 min, $0 LLM)

Decision record at `agents/composer/PASS_4_0I_DECISION_RECORD.md`. Cross-repo merge to main on both repos. Branch cleanup. Memory entry.

## 11. Cost forecast (Phase A → F total)

| Phase | Engineering | LLM |
|---|---|---|
| A (this) | ~1.5-2 hrs | $0 |
| B | ~3-4 hrs | $0 |
| C | ~2 hrs | ~$0.30 |
| D | ~3-4 hrs | $0 |
| E | ~1 hr | ~$0.30 |
| F | ~30 min | $0 |
| **Total** | **~10-13 hrs** | **~$0.60** |

Recalibrated down from the original ~12-15 hour estimate because Cathedral scope deletion removed ~2-3 hours of doc + variant work.

## 12. What ships after Phase F

A Studio Brut practitioner (RoyalTeez or future) can pick:

- **Font:** one of 5 Google Fonts pairings (display + body)
- **Accent:** one of 6 options including `no_accent`
- **Intensity:** restrained / confident / bold (or let Composer infer from archetype)

Their Hero composition reflects all three choices visibly. Two Studio Brut practitioners with the same variant (`edge_bleed_portrait`) but different creative-expression choices will produce visibly distinct Heros — same module DNA, different brand identity expression.

Cathedral-through-Composer practitioners (when they ship): inherit dormant the Pass 4.0i architecture, get a `cathedral_*` font vocabulary + accent vocabulary in **Pass 4.0i.x** (separate scope), use the same intensity treatment.

Builder pipeline businesses (KMJ, ETS, Director Loop Test): unaffected by Pass 4.0i. Their Heros continue to be Builder-generated with the Pass 4.0d/h.x/h.y/h.z prompt rules in effect.
