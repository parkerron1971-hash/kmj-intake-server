# Pass 4.0g — Studio Brut Module + Module Router: Decision Record

**Branch:** `pass-4-0g-studio-brut-module` (ready to merge to `main` after this record commits)
**Closed:** 2026-05-16
**Verdict:** **GO**

---

## TL;DR

Multi-module composition architecture is validated end-to-end. Two design modules with deliberately different aesthetic DNA — Cathedral (cinematic_authority) and Studio Brut — coexist in the codebase without architectural friction. A Module Router (Sonnet 4.5 @ temp 0.3) routes businesses to the right module before within-module composition begins, with 100% accuracy on known cases and honest confidence calibration on seam cases. Module-specific Composer prompts produce module-appropriate **voice** in compositions, not just module-appropriate layout — Studio Brut produced "Wear your crown loud" for RoyalTeez Designz, copy the Cathedral prompt would never produce.

The Pass 4.0f spike's CONDITIONAL GO upgrades to full GO. The five-module library investment is justified. Pass 4.0h begins Atelier as the third module using the proven pattern.

---

## What was proven

1. **Two modules with different DNA coexist without architectural friction.** Cathedral and Studio Brut share the same composition primitives (variants × treatments × content × brand kit), the same Composer call pattern, the same render pipeline shape — but emit aesthetically incompatible output by design. No cross-module leakage. No shared-code compromises that pull either module toward the other's center of gravity.

2. **Module Router routes accurately with honest confidence.** The Sonnet 4.5 router at temperature 0.3 hit 3/3 routing accuracy across 9 convergence runs (Phase D). Confidence calibration is honest, not inflated:
   - RoyalTeez Designz (custom apparel) → `studio_brut @ 0.95`, no alternative. Clean archetypal match.
   - KMJ Creative Solutions (strategic creative consultancy) → `cathedral @ 0.80`, alt `studio_brut`. Clear primary fit; the consultancy framing wins but the personality-led read has a foothold.
   - Director Loop Test (technical methodology service) → `cathedral @ 0.75`, alt `studio_brut`. Real ambiguity surfaced honestly (see *What was surfaced* below).

3. **Composer can be generalized via ModuleSpec dispatch.** A single `hero_composer.py` (640 lines) handles both modules through a per-module dispatch table:

   ```python
   ModuleSpec(
       module_id,
       system_prompt,            # module-specific
       composition_type,         # Pydantic, module-specific
       image_using_variants,     # frozenset, module-specific
       safe_fallback_variant,    # module-specific
   )
   ```

   Same logic shape across modules — fetch context, build user prompt, LLM call, JSON parse + retry, depth-field completeness check, image-slot consistency enforcement, Pydantic validation, soft-fail. Only the spec table differs. Cleaner than dispatcher/subclass patterns. Adding a third module is a spec-table addition plus the new system prompt; no logic rewrite.

4. **Module-specific Composer prompts produce module-appropriate VOICE, not just layout.** This is the load-bearing finding for the whole architecture. The Studio Brut Composer prompt explicitly authors for shorter sentences, direct address, imperative verbs, and action-led CTAs as DNA discipline. The result for RoyalTeez Designz: heading "Wear your crown loud", CTA "Start your design". The Cathedral Composer prompt — which the spike showed cannot deliver urban-creative-royal energy through treatment variation alone — would have produced something like "Where your crown finds its form" with a softer CTA. Voice is now a first-class output of the architecture, not a side-effect of layout choice.

5. **Treatment system architecture transfers across modules.** Same 8 dimensions (3 structural + 5 depth) across both modules, with module-specific values per dimension. Studio Brut's typography emphasis modes (color / weight / scale / scale+color) replace Cathedral's italic-emphasis pattern — same dimensional shape, different values. The treatment system is a transferable architecture, not a per-module bespoke.

6. **DNA gates as smoke test enforcement prevents cross-module aesthetic leakage.** Studio Brut compositions hard-reject diamond ornaments. Studio Brut compositions hard-reject italic emphasis. The render pipeline does not leak Cathedral CSS variables (`--ca-*`) into Studio Brut documents. The gates surfaced one real coupling bug in Phase C (see *What was surfaced* below) and have held since.

7. **Backward compatibility preserved through the refactor.** Cathedral compositions through the generalized `hero_composer.py` produce fingerprints structurally indistinguishable from Pass 4.0f Phase 3 output (within normal Composer stochastic variance at temperature 0.4). Phase E backward-compat test: 3/3 variant matches, 3/3 semantically-stable heading emphasis, structural-treatment drift within the Phase 4-bis convergence pattern. The `cathedral_hero_composer.py` thin shim preserves the legacy import surface so all existing spike scripts continue to work without modification.

### The visual proof

Phase F's multi-module comparison page makes the architectural claim concrete. KMJ and Director Loop are routed to Cathedral; their forced-Cathedral comparison columns produce structurally matching output (backward compat ✓). RoyalTee is routed to Studio Brut and produces an `edge_bleed_portrait` Studio Brut composition with the "Wear your crown loud" copy; its forced-Cathedral comparison column produces an `asymmetric_right` Cathedral composition — the spike's failed case rendered directly beside the multi-module fix.

The visual evidence confirms what the convergence tests and end-to-end pipeline verification suggested: **aesthetic DNA matters more than treatment variation**. Cathedral with all 8 treatment dimensions cannot deliver urban-creative-royal energy. Studio Brut with its different DNA delivers it naturally.

---

## What changed from original Pass 4.0g scope

**Variant count and naming.** The planning document proposed 11 Studio Brut variants matching Cathedral's count exactly. Final output: 11 Studio Brut variants — but built from Studio Brut DNA, not mirrored from Cathedral structure. The final variant set:

```
color_block_split    oversize_statement    diagonal_band         stacked_blocks
edge_bleed_portrait  type_collage          layered_card          stat_strip
massive_letterform   double_split          rotated_anchor
```

These are 11 Studio Brut answers to "what does a hero look like in this module?", not 11 Cathedral-shaped slots refilled with Studio Brut treatment values.

**Treatment system: same 8 dimensions, module-specific values.** Studio Brut typography mode-switching (color / weight / scale / scale+color emphasis modes) replaces Cathedral's italic-emphasis pattern. This is a richer architectural pattern than originally planned — emphasis is no longer a fixed primitive (italic) but a module-specified dimensional value. The pattern generalizes cleanly to future modules: Atelier's emphasis modes can be different again without rewriting the treatment system.

---

## What was surfaced

1. **Director Loop Test routes Cathedral at 0.75 with consistent Studio Brut alternative.** This is a genuine seam class — technical-methodology brands that could legitimately fit either module. The router is doing the right thing (picking the closer fit, surfacing real ambiguity, honest confidence below 0.9). Worth tracking forward: **Pass 4.0j (Field Manual module) may eventually serve this archetype better than Cathedral.** The Director Loop seam is the leading indicator that Pass 4.0j is needed in the roadmap.

2. **TEST TITLE rendering caveat observed in Phase F comparison page.** The `edge_bleed_portrait` variant's massive letterform area appears to render placeholder content in some configurations rather than the composed heading. Not blocking — the rest of the variant renders correctly and the composition is sound — but worth investigating in a **Pass 4.0g.x cleanup pass** before Pass 4.0h architectural work expands the variant surface further.

3. **Real coupling bug found and fixed in Phase C: `heading.py` emphasis modes were silently coupling typography with `color_depth`.** The fix extracted `color_depth` overlay vars into all four Studio Brut emphasis modes so typography mode-switching no longer drags `color_depth` with it. **The per-dimension coverage assertions Phase C added are the discipline that caught this bug.** That assertion pattern is now a transferable Pass 4.0h+ tool.

---

## Cost and time actuals

### LLM cost — ~$1.40 total (forecast: $2–3)

| Phase | Cost     | Notes                                                                     |
| ----- | -------- | ------------------------------------------------------------------------- |
| A     | $0.00    | Design document only (no LLM)                                             |
| B     | ~$0.10   | 11 variant smoke tests                                                    |
| C     | ~$0.05   | Treatment audit + per-dimension coverage assertions                       |
| D     | ~$0.25   | Module Router + convergence diagnostic + edge-case tests                  |
| E     | ~$0.35   | Composer refactor + backward-compat verification + end-to-end pipeline    |
| F     | ~$0.45   | Multi-module comparison page (9 Sonnet calls: 3 router + 3 composer + 3 force-Cathedral composer) |
| Other | ~$0.20   | Ad-hoc test runs, convergence re-runs, voice spot-checks                  |
| **Total** | **~$1.40** | Under $2–3 forecast.                                                    |

### Engineering time — ~15–18 hours across Phase A through Phase F

Comparable to Pass 4.0f spike (~14 hours), with Phase F slightly faster than Phase 4.0f Phase 5 because the comparison page pattern was already proven and the new page mostly mirrored it.

### Branch state

`pass-4-0g-studio-brut-module` — ready to merge to `main` after this decision record commits. The merge is the formal Pass 4.0g close; per the planning document's success path, the branch graduates from spike-adjacent artifact to production trunk addition.

---

## Artifacts preserved

- 11 Cathedral Hero variants (from spike, now living on `pass-4-0g-studio-brut-module`)
- 11 Studio Brut Hero variants (Phase B)
- 8-dimension treatment system with module-specific values for both modules
- Cathedral Composer prompt (~11k chars) + Studio Brut Composer prompt (~16k chars)
- Module Router agent (~370 lines) — `agents/composer/module_router.py`
- Generalized hero composer with ModuleSpec dispatch (~640 lines) — `agents/composer/hero_composer.py`
- Module-aware render pipeline with `compose_and_render_hero` end-to-end function — `agents/composer/render_pipeline.py`
- Multi-module comparison page with process-local pipeline caching — `agents/composer/multi_module_comparison_page.py`
- `TREATMENT_AUDIT.md` cross-module delta reference (Phase C artifact)
- `STUDIO_BRUT_DESIGN.md` canonical design document (Phase A artifact)
- Verification harnesses: `_spike_phase_e_verify.py`, `_spike_phase_f_verify.py`
- `cathedral_hero_composer.py` thin backward-compat shim preserving all spike-era imports

---

## Pass 4.0h scope — Atelier module

Following the proven Pass 4.0g pattern:

| Phase | Scope                                                                                                 | Estimate    |
| ----- | ----------------------------------------------------------------------------------------------------- | ----------- |
| A     | Atelier design document                                                                               | ~2 hours    |
| B     | 11 Atelier Hero variants built from Atelier DNA                                                       | ~5–6 hours  |
| C     | Atelier treatment system with module-specific values                                                  | ~2 hours    |
| D     | Module Router prompt update to three-way routing (cathedral / studio_brut / atelier) + new convergence + edge-case tests | ~2 hours    |
| E     | Composer ModuleSpec table extension for Atelier (minimal refactor — architecture in place)            | ~1 hour     |
| F     | Three-business comparison with potential fourth Atelier-appropriate business                          | ~1 hour     |
| G     | Pass 4.0h decision record                                                                             | —           |

**Total: ~12–15 hours, ~$1.50 LLM cost** (similar to Pass 4.0g).

**Atelier target archetypes** per Pass 4.0g planning document: crafted, expressive, artist-studio brands. Handmade jewelry makers, craft makers, artist portfolios, small-batch product brands, creative service providers with personal touch. The seam against Studio Brut is "expressive but not loud" — refined personality rather than brutalist personality.

---

## Five-module library roadmap

| Pass   | Module        | Status                                  | Target archetype                                                              |
| ------ | ------------- | --------------------------------------- | ----------------------------------------------------------------------------- |
| 4.0f spike | Cathedral     | Architecture validated (CONDITIONAL GO) | Editorial, cinematic_authority, premium-by-restraint                          |
| **4.0g**   | **Studio Brut** | **GO — this pass**                      | **Urban, graphic, expressive, maker-aesthetic**                               |
| 4.0h       | Atelier       | Next                                    | Crafted, expressive, artist-studio                                            |
| 4.0i       | Pulpit        | Planned                                 | Pastoral, community, teaching (targets KMJ Ministries archetype)              |
| 4.0j       | Field Manual  | Planned                                 | Technical, methodology, practical service (may absorb the Director Loop "seam class") |
| 4.0k       | Floor         | Planned                                 | High-design, gallery, premium                                                 |

Five modules total when complete. Each one solves a class of brands the others can't.

---

## Parked items

- **L11** (RoyalTee `brand_kit.colors.accent` as CSS keyword `'purple'` instead of hex) — still parked, accidental win in Pass 4.0f Phase 2.6 because `color-mix` handles it gracefully. Not blocking Pass 4.0h.
- **L12 (NEW)** — TEST TITLE rendering caveat in `edge_bleed_portrait` variant. Parked for **Pass 4.0g.x cleanup pass**. Worth investigating but not blocking Pass 4.0h architectural work.

L1–L10 remain parked from prior passes; none are blocking.

---

## Status

Pass 4.0g formally closed. Multi-module composition architecture validated. Branch `pass-4-0g-studio-brut-module` ready to merge to `main`. Pass 4.0h scope locked: Atelier as third module following the proven pattern.
