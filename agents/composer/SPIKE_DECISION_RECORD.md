# Pass 4.0f — Cathedral Hero Component Spike: Decision Record

**Branch:** `pass-4-0f-spike-cathedral-hero` (preserved as artifact, never merged to `main`)
**Closed:** 2026-05-16
**Verdict:** **CONDITIONAL GO**

---

## TL;DR

The component composition architecture — variants × treatments × content × brand kit — is **validated** as the right primitive for assembling sites. Composer's variant selection is intentional and convergent. The render pipeline integrates cleanly with the existing brand-kit / slot / override infrastructure. Visual depth treatments are necessary, and they work.

The spike also surfaced an **architectural finding that changes Pass 4.0g scope**: one design module isn't enough. Cathedral's editorial-restraint DNA can't be tuned into urban-creative-royal energy by adding treatment dimensions. The real architecture is "5–8 distinct modules, each with 10–15 variants per section, each with full treatment systems, with module routing as the first composition decision."

GO is conditional on building a second module (Pass 4.0g) and proving multi-module architecture delivers brand-distinct output for businesses Cathedral doesn't serve.

---

## What the spike proved

1. **Component composition produces coherent, structurally-varied output.** Eleven variants × eight-dimension treatment system × content × brand kit yields more than enough structural distinctness for the businesses Cathedral's archetype serves. Three businesses produce three visibly different Heros without bespoke HTML per site.

2. **Composer Agent makes intentional decisions, not arbitrary ones.** Three businesses × three runs each = nine compositions:
   - Variant choice locked 100% within each business (KMJ × 3 → `asymmetric_right`; Director Loop × 3 → `annotated_hero`; RoyalTee × 3 → `asymmetric_right`)
   - Treatment fingerprints stable with minor wobble in low-stakes dimensions
   - Heading-emphasis content semantically stable (KMJ: `breakthrough` × 3; Director Loop: loop / repetition / iteration — same metaphor; RoyalTee: throne / throne / crown — same metaphor)
   - Reasoning text anchors consistently on the same archetypal read each run

3. **Brand kit integration via CSS variables produces accurate per-brand rendering.** The existing `brand_kit_renderer.render_with_brand_kit` infrastructure (Pass 4.0d PART 3) wires straight into the new variant output. Variants reference `var(--brand-signal)` / `var(--brand-authority)` etc. and re-theme per business with zero variant-side changes.

4. **Override system + slot resolution integrate cleanly with component composition.** The full four-step pipeline (variant render → brand kit → slots → overrides) is identical to `smart_sites._try_serve_builder_html`. Variants emit `data-override-target` + `data-slot` attributes; the existing resolvers find and substitute. No infrastructure changes required.

5. **Visual depth treatments are required additions — structural variants alone aren't enough.** Phase 5 surfaced this: variants differentiate structurally but the visual layer was too thin. Phase 2.6 added five depth dimensions (background / color_depth / ornament / typography / image_treatment). The same variant + same brand kit now produces visibly distinct atmosphere per business because the depth treatments do the differentiating work. Even depth-equipped variants stay within their module's aesthetic — Cathedral with depth is still Cathedral. That's a feature, not a bug.

---

## What the spike surfaced

**The Cathedral module is insufficient for brands whose archetypal aesthetic falls outside editorial-restraint.**

RoyalTee — a custom apparel design business with urban-creative-royal personality — got a competent Cathedral render. The variant choice (`asymmetric_right`) was structurally correct; the depth treatments leaned as creative as the module allows (soft_gradient bg, gradient_accents color_depth, dramatic image filter). But the result still reads like an editorial agency, not a streetwear apparel brand. Cathedral's typographic DNA (Playfair Display, restrained tracking, signal-color italic emphasis as the one ornament) is incompatible with the brand's required visual register no matter which treatment combination is selected.

The spike's signal on shipping Cathedral as RoyalTee's site is **structural, not stylistic**. No amount of Cathedral tuning makes it the right module for that brand. Adding more variants or more treatment dimensions within Cathedral wouldn't bridge the gap.

The fix isn't "improve Cathedral." The fix is "build the right module for brands like RoyalTee."

---

## Why CONDITIONAL not full GO

A full GO on the spike thesis would justify investing in the remaining Cathedral sections (About, Services, Gallery, Testimonials, CTA Band, Footer) at ~30–40 hours of work. Doing that before validating multi-module architecture would risk building a deeper library inside a module that can't serve the full target customer base.

The conditional gate is: **Pass 4.0g must prove a second module can be built following the same architecture, and that a Module Router can route businesses to the right module before within-module composition begins.** If 4.0g delivers, the spike thesis upgrades to GO and the full library investment is justified across modules. If 4.0g doesn't deliver, the architecture needs a deeper rethink before further library work.

---

## Cost actuals and time actuals

### LLM cost — ~$0.80 total (forecast: $1.15)

| Phase | Description | Calls | Cost |
|---|---|---|---|
| Phase 3 (CHECKPOINT 3) | Initial 3 Composer compositions | 3 | $0.15 |
| Phase 4 (CHECKPOINT 4) | 3 fresh renders during live verification | 3 | $0.15 |
| Phase 4-bis (convergence diagnostic) | 2 more per business × 3 businesses | 6 | $0.30 |
| Phase 5 (comparison page) | 3 compositions per comparison render | 3 | $0.15 |
| Phase 2.6 verification | 3 depth-aware compositions | 3 | $0.05* |
| **Total** | | **18** | **~$0.80** |

\* Phase 2.6 was unexpectedly cheap — Composer returned all 8 fields valid first try across all 3 businesses; no retry path fired.

### Engineering time — ~14 hours (forecast: 8–10 hours)

| Phase | Scope | Time |
|---|---|---|
| Phase 1 | Foundation (types, primitives, treatments scaffolding) | 1.5 h |
| Phase 2 | 6 initial variant renderers | 2.5 h |
| Phase 2.5 | Library expansion to 11 variants | 2 h |
| Phase 3 | Composer Agent + system prompt | 2 h |
| Phase 4 | Render pipeline + spike FastAPI + endpoints | 2.5 h |
| Phase 5 | Comparison page + convergence diagnostic | 1.5 h |
| Phase 2.6 | Visual depth (5 new dimensions, 11-variant migration) | 2 h |

Variance over forecast came from two scope expansions both initiated by review feedback:
- **Phase 2.5** added 5 variants after Phase 2 visual review surfaced gaps in the original 6
- **Phase 2.6** added 5 depth dimensions after Phase 5 review surfaced the "too thin" finding

Both expansions were the right calls — they strengthened the spike's evidence base — but they pushed time over the original window.

---

## Artifacts preserved

All artifacts live on `pass-4-0f-spike-cathedral-hero` and are reusable for Pass 4.0g regardless of the spike verdict.

### Code

| Path | What it is |
|---|---|
| `agents/design_modules/cinematic_authority/hero/types.py` | Pydantic models — `CathedralHeroComposition`, `Treatments` (8 dims), `RenderContext`, `BrandKitColors`, `VariantId` Literal, `IMAGE_USING_VARIANTS` frozenset |
| `agents/design_modules/cinematic_authority/hero/primitives/` | 5 reusable primitives — heading, eyebrow, subtitle, cta_button, diamond_motif. Depth-aware. |
| `agents/design_modules/cinematic_authority/hero/treatments/` | 8 treatment translators (3 structural + 5 depth) returning CSS-variable dicts |
| `agents/design_modules/cinematic_authority/hero/variants/` | 11 production-quality variant renderers + `_depth_helpers.py` |
| `agents/composer/cathedral_hero_composer.py` | Composer Agent — Sonnet 4.5, archetype-aware variant + 8-dimension treatment selection, JSON-validated, retry + safe-default fallback |
| `agents/composer/render_pipeline.py` | Four-step pipeline mirroring `smart_sites._try_serve_builder_html` |
| `agents/composer/router.py` | FastAPI router — `/composer/_diag/compose_hero`, `/composer/_spike/render_hero/{biz}`, `/composer/_spike/render_hero_html/{biz}`, `/composer/_spike/comparison_page` |
| `agents/composer/_spike_app.py` | Standalone FastAPI mounting only the spike router (never wired into `kmj_intake_automation.py`) |
| `agents/composer/comparison_page.py` | Server-side side-by-side comparison renderer with structural + depth pill groups |
| `agents/composer/_spike_fire_three.py` | Phase 3 test harness |
| `agents/composer/_spike_convergence.py` | Phase 4-bis convergence diagnostic |
| `agents/composer/_spike_phase26_verify.py` | Phase 2.6 verification harness |
| `agents/composer/_phase26_migrate_variants.py` | One-shot migration script that wired depth treatments into all 11 variants (idempotent, kept for audit) |
| `agents/design_modules/cinematic_authority/hero/__tests__/test_variants.py` | 99 smoke renders (11 variants × 3 treatment tiers × 3 content fixtures) |

### Live URLs (while spike server runs)

```
http://127.0.0.1:8765/                                                — index
http://127.0.0.1:8765/composer/_spike/comparison_page                 — Phase 5 side-by-side
http://127.0.0.1:8765/composer/_spike/render_hero_html/{business_id}  — per-business render
```

Start: `railway run uvicorn agents.composer._spike_app:app --port 8765`

### Captured outputs

| Location | Contents |
|---|---|
| `%LOCALAPPDATA%\Temp\spike_variants\` | 11 spot-check HTMLs from Phase 2 / 2.5 smoke runs |
| `%LOCALAPPDATA%\Temp\spike_phase4\` | Phase 4 + Phase 5 + Phase 2.6 captured renders |
| `%LOCALAPPDATA%\Temp\spike_phase3_compositions.txt` | CHECKPOINT 3 verbatim JSONs |
| `%LOCALAPPDATA%\Temp\spike_phase4bis_convergence.txt` | Convergence diagnostic report |
| `%LOCALAPPDATA%\Temp\spike_phase2_6_compositions.txt` | CHECKPOINT 2.6 verbatim JSONs |

---

## What gets carried forward

Even though Cathedral may never ship as a production module in its current form, the spike produced reusable assets:

1. **Variant taxonomy as documented design library.** Eleven variants documenting specific Cathedral patterns — more precise than the prose-only Cinematic Authority module document. Each variant is code that a designer can read.

2. **Treatment system architecture.** The 8-dimension model (3 structural + 5 depth) is the template every future module follows. Same dimension names, same translator pattern, same primitive contract. A new module reuses the dimension framework and varies the value sets.

3. **Composer Agent pattern.** Selecting from a structured palette with reasoning, with archetype-aware guidance, JSON-validated, retry-on-error, safe-default fallback. The pattern is reusable for second-module composition.

4. **Render pipeline.** `variant → brand kit injection → slot resolution → text overrides` mirrors production `smart_sites` flow. Module-agnostic — works for Cathedral, will work for Studio Brut, will work for any future module.

5. **Spike methodology itself.** Three businesses chosen for archetypal spread, side-by-side comparison, multi-run convergence verification, depth dimensions added when first-pass review surfaced gaps. Reusable for testing future modules with the same rigor.

---

## Pass 4.0g — revised scope

**Original plan:** Build remaining Cathedral sections (About, Services, Gallery, Testimonials, CTA Band, Footer). ~30–40 hours.

**Revised plan:** Build a SECOND design module targeting brands Cathedral doesn't serve, plus a Module Router that picks which module first. The most likely candidate based on RoyalTee's needs is **Studio Brut** (or **Atelier**) — bold, urban, expressive, playful typography systems, more graphic ornamentation, less editorial restraint.

### Phases

**Phase A — Second module design document.**
Define aesthetic principles for Studio Brut (or chosen second module): color philosophy, typography systems, ornamentation style, archetypal businesses it serves, what it explicitly does NOT serve. Reference doc parallel to `cinematic_authority_intelligence.md`.

**Phase B — Build 11 Studio Brut Hero variants.**
Same architecture as Cathedral: variants × 8-dimension treatments × primitives × CSS vars. Different aesthetic DNA throughout — different typography (no Playfair Display), different ornament motif (no diamonds), different spacing rhythm. Reuses Composer Agent pattern + render pipeline + treatment-translator structure.

**Phase C — Module Router agent.**
New pre-step before Composer. Inputs: enriched brief + business archetype + brand kit. Output: module ID (`cinematic_authority` | `studio_brut`). Single LLM call (cheap classifier). The Composer Agent becomes module-specific — `cathedral_hero_composer.py` already exists; Phase B produces `studio_brut_hero_composer.py`. Module Router decides which composer fires.

**Phase D — Three-business comparison again.**
Same trio (KMJ, Director Loop Test, RoyalTee), Module Router runs first. Expected routing: KMJ → Cathedral. Director Loop Test → Cathedral. RoyalTee → Studio Brut. Then within-module composition produces the Hero. Comparison page surfaces both the module routing decision + the within-module composition reasoning.

**Phase E — Decision moment.**
Does multi-module architecture deliver brand-distinct output for all three businesses now? If YES → GO on full library across both modules + plan for modules 3–8 over future passes. If NO → deeper architectural rethink before any further library investment.

### Pass 4.0g estimates

- **Engineering time:** ~25–35 hours across multiple sessions
- **LLM cost:** ~$2–3 in API spend (more compositions, plus Module Router calls)

---

## Parked items

L1–L11 cleanup items remain parked. None are blocking. None need addressing before Pass 4.0g begins.

Notable items worth surfacing:

- **L11 — RoyalTee `brand_kit.colors.accent = "purple"`** (CSS keyword, not hex). The render pipeline soft-fails correctly; browsers accept the keyword. Per-element color override picker in Pass 4.0e PART 3 assumes hex inputs and would fail to manipulate this value. Data-cleanse pass before practitioner picker wires against this brand.

- **Typography dimension mono-pick.** Phase 2.6 Composer picked `typography=bold` for all three test businesses despite archetype guidance suggesting editorial/refined for Director Loop and playful for RoyalTee. The other four depth dimensions did the differentiation work, so the comparison still read as three distinct brands — but the typography prompt section may benefit from Pass 4.0g prompt-tuning to broaden selection.

- **No `ornament=heavy` fired in any spike composition.** Heavy adds 4 satellite diamonds beyond the variant's base set. None of the three test businesses pulled it. Smoke tests cover the path; you won't see it in the comparison page until a future Composer call picks it.

- **`anthropic` SDK local upgrade (0.34.2 → 0.102.0).** Done locally only — `requirements.txt` untouched, deployment unaffected. Production server is on whatever version Railway resolved when the last deploy ran. No action required.

---

## Spike formally closes

Pass 4.0f is complete. No further spike work. Pass 4.0g begins from a new branch, drawing on the artifacts and patterns this spike produced.
