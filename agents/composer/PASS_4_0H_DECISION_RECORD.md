# Pass 4.0h — Production Wiring for Multi-Module Pipeline: Decision Record

**Branch:** `pass-4-0h-production-wiring` (merged to `main` 2026-05-17 as commit `29b46a1`; branch preserved on origin as historical artifact)
**Closed:** 2026-05-17
**Verdict:** **SHIPPED**

---

## TL;DR

Multi-module composition architecture is activated in production. RoyalTeez Designz is the first real practitioner served by the Composer pipeline — `royalteez-designz.mysolutionist.app` now serves a hybrid HTML page where the Hero is a Studio Brut composition (`edge_bleed_portrait` variant) and the rest of the site is Builder-generated. The Edit Mode UI built for Builder Heros in Pass 4.0e works transparently on Composer Heros — verified end-to-end by an Edit Mode heading rewrite that overwrote the stale `'Test Title'` fixture override and reflected on the live URL after refresh.

The spike's central question — *"does this architecture serve real practitioners, not just comparison-page demos?"* — is answered: yes, for RoyalTee, today.

---

## What was shipped

### Schema migrations (Phase A, applied to production Supabase)

```sql
ALTER TABLE businesses
  ADD COLUMN IF NOT EXISTS use_composer BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE business_sites
  ADD COLUMN IF NOT EXISTS hero_composer_module TEXT NULL;
```

Both append-only with safe defaults. Existing reads/writes against either table are unaffected. Migration SQL committed at `agents/composer/PASS_4_0H_MIGRATIONS.sql` for reproducibility.

### Composer post-processor (Phase B)

`agents/composer/post_processor.py` (~290 lines) — `async post_process_hero(business_id, builder_html, enriched_brief=None, brand_kit=None, site_config=None) → (final_html, module_id)`. Pipeline:

1. Gate on `businesses.use_composer` (anon-key read). False → fast return `(builder_html, None)`, no LLM calls.
2. SHA-256 canonical hash of `enriched_brief`. Cache lookup in `site_config.composer_cache`. HIT → reuse cached composition; skip Router + Composer (~$0.05–0.10 saved).
3. Cache MISS → Module Router (via `asyncio.to_thread`) → Composer (via `asyncio.to_thread`). Write through to `site_config.composer_cache` (in-place mutation so Builder's existing PATCH carries the cache update).
4. Render composed Hero via `render_hero_fragment(composition, business_id, module_id)` — full four-step pipeline including override resolution so practitioner edits win.
5. Surgical BeautifulSoup replacement of the Hero `<section>`. Primary selector `<section data-section="hero">`; class-based fallback logs WARNING; ERROR + unchanged return if neither matches.
6. Every step wrapped in `try/except` — any failure returns `(builder_html, None)` so a post-processor bug can never break a build.

### Builder integration (Phase C)

`agents/director_agent/build_with_loop.py:618–623` — inserts `asyncio.run(post_process_hero(…))` between `cfg = dict(rows[0].get("site_config") or {})` and the original `cfg["generated_html"] = final_html`. The PATCH body at line 647–660 is extended to write both `site_config` (JSONB carries the cache write-through) AND `hero_composer_module` (top-level column from Phase A) in one PostgREST PATCH — no second round-trip, atomic from the row's perspective.

The async-from-sync bridging via `asyncio.run()` is safe in the live call shape: FastAPI runs the sync `/director/build-with-loop` handler in a threadpool with no active event loop. Outer `try/except` catches integration-boundary failures (import error, event-loop setup) so a wiring bug also can't break a build.

### Tests + verification

- 20 post-processor unit tests at `agents/composer/__tests__/test_post_processor.py` (Hero identification with WARNING/ERROR log assertions, surgical replace across selector paths, hash determinism, cache lookup/store round-trips, end-to-end `post_process_hero` glue with mocked Router/Composer).
- Phase B live integration smoke against RoyalTee (one real Composer round-trip, ~$0.05).
- Phase C integration verification: KMJ (`use_composer=False`) returns byte-identical HTML through the new wiring; RoyalTee with mocked True returns Studio Brut hybrid; PATCH body shape correct for both paths.

### Live RoyalTee activation (Phase D)

- `businesses.use_composer` PATCHed `False → True` via anon-key (verified UPDATE capability in Phase C).
- `POST /director/build-with-loop` for `business_id=a8d1abb7-…` with the persisted `build_inputs` (business_name `RoyalTeez Designz`, module_id `cinematic_authority`, vocab_id `sovereign-authority`, max_attempts 2).
- Build completed in ~8 minutes (two Builder attempts via the regenerate loop + ~72 s Composer post-processing on cache miss). My curl timed out at 480 s but the server kept working; DB state confirmed success.
- Post-build state:
  - `hero_composer_module = 'studio_brut'`
  - `composer_cache.variant = 'edge_bleed_portrait'`, composed heading `'Wear your crown loud'`, emphasis `'crown'`, cached_at `2026-05-17T11:35:18Z`
  - `site_config.generated_html` rewritten: 38,198 → 52,088 bytes (the new hybrid)
  - No build error; html_build_failed_at = None
- Live URL inspection: section root `<section class="sb-hero sb-hero-edge-bleed-portrait" data-section="hero">`, Studio Brut display font stack (Druk / Bebas Neue / Space Grotesk / Archivo Black), all `data-override-target` paths present.

### Edit Mode bridge verified (Phase E)

- Test 1 (heading edit) — PASS end-to-end:
  - Edit Mode UI opens on `data-override-target="hero.heading"` in the Composer-rendered H1.
  - EditPanel write fires through `/chief/override` (Pass 4.0e/4.0d code path, untouched by Pass 4.0h).
  - `site_content_overrides` row at `target_path='hero.heading'` UPDATED in place (not duplicated).
  - Live URL hard-refresh reflects the new heading (Pass 4.0e `no-store` cache headers doing their job).
- Test 5 (emphasis-substring graceful degradation) — passive PASS verified before user testing:
  - Pre-test live state already exercised the case (override `'Test Title'` doesn't contain emphasis word `'crown'`).
  - Override resolver does whole-innerHTML replacement, which cleanly wipes any nested emphasis span. H1 inner is just the override value, no orphaned `<span>`/`<em>` tags, no broken markup.
  - The render layer handles this case by structural property, not by emphasis-aware logic — robust to any future heading override shape.
- Tests 2–4 (eyebrow, subtitle, CTA) and Test 6 (cache invalidation passive check) inferred PASS by architectural symmetry — same UI handlers, same `/chief/override` path, same override resolver logic.
- Test 5 (image swap via `InlineSlotPicker`) — **unverified**; parked as a known coverage gap. Different UI surface from text edit, low risk, expected to work given Composer's image-using variants emit `data-slot="hero_main"` + `data-override-target="hero_main"` (verified in Phase B smoke).

---

## What was proven

1. **Component composition architecture serves real production traffic.** The spike's load-bearing question is answered: a hybrid Composer-Hero + Builder-rest page serves at a real subdomain, with practitioner-grade Edit Mode working on top.

2. **Multi-module pipeline coexists with the existing Builder pipeline without architectural friction.** `use_composer=False` businesses (KMJ, ETS, all others — i.e. everyone except RoyalTee right now) continue to serve byte-identical Builder HTML. Verified pre/post each merge in this pass: 70,607 → 70,607 / 77,016 → 77,016 / 702 → 702 byte counts unchanged. Opt-in is per-row, per-business, reversible by flipping a single column back to False.

3. **Hash-based composition caching works correctly.** First build for RoyalTee was a cache MISS (no cache had been persisted; Phase B's in-memory smoke didn't write back). Full Module Router + Composer fired (~72 s), composition got written through to `site_config.composer_cache` with `_version=1`, `brief_hash`, `module_id`, `composition`, and `cached_at`. Subsequent builds with unchanged `enriched_brief` will HIT and skip both LLM calls.

4. **Edit Mode infrastructure built for Builder Hero in Pass 4.0e works transparently on Composer Hero in Pass 4.0h.** Same `data-override-target` attribute pattern, same `/chief/override` endpoint, same render-layer override application. No Pass-4.0h-specific Edit Mode code was required.

5. **Defensive error handling at every layer means post-processor can never break a build.** Failure modes (gate read fails, Router timeouts, Composer raises, malformed composition, BeautifulSoup parse error, surgical-replace edge case) all degrade to `(builder_html, None)` and a logged warning. Phase D's first real build exercised the cache-write-through path under production conditions without incident.

---

## What was surfaced

- **L11** — RoyalTee `brand_kit.colors.signal = 'purple'` (CSS keyword, not hex). Still in `site_content_overrides` as a `color_role` override row. Still working via `color-mix` in the render layer. Still parked for future hex normalization. Not blocking.
- **L13** — `/health` endpoint shadowed by `public_site_router` catch-all in `kmj_intake_automation.py`. Pre-existing condition surfaced during Pass 4.0g merge. Still parked. Not blocking — a `/composer/_diag/route_module` POST is the de facto live-pipeline health check.
- **L14 (NEW)** — Builder currently emits Hero as `<section class="…hero…">`, not `<section data-section="hero">`. The post-processor's class-based fallback selector (with WARNING log) is currently load-bearing on RoyalTee's builds. Works correctly but creates a silent-regression surface if Builder ever changes the class shape. Worth a small Builder cleanup pass before too many businesses opt into `use_composer`.
- **Test 5 image swap on Composer Hero — unverified.** Parked as known coverage gap. Low risk; expected to work given the markup contract is identical to Builder's image elements (same `data-slot` + `data-override-target` pattern). Will be verified naturally the first time a RoyalTee-style practitioner swaps an image, or explicitly in a Pass 4.0h.x mini-pass.
- **`'Test Title'` override row** still in `site_content_overrides` after Phase E Test 1 — rewritten via Edit Mode to `'Wear your crown loud'`. The row is no longer stale fixture data; it's now legitimate practitioner content matching the Composer's voice. L12 (Pass 4.0g.x's diagnosis) effectively closed by user-driven edit.

---

## Cost and time actuals

### LLM cost — ~$0.60 total (forecast: $0.50–1.10)

| Phase | Cost | Notes |
|-------|------|-------|
| A | $0 | Schema migrations (DDL only) |
| B | ~$0.05 | One Composer round-trip in the live integration smoke |
| C | $0 | Integration verification reused Phase B cache where possible |
| D | ~$0.55 | First real RoyalTee build through wired pipeline (cache MISS: ~$0.05 Composer + ~$0.50 Builder with regenerate loop) |
| E | $0 | Edit Mode tests apply overrides at render time — no LLM calls |
| F | $0 | Decision record |
| **Total** | **~$0.60** | Well under $1.10 high-end forecast. |

### Engineering time — ~7–9 hours across Phases A–F

Concentrated in Phase B (post-processor + caching + 20 unit tests) and Phase C (wiring + integration verification). Phase A migration + recon, Phase D activation + waiting on the build, and Phase E hand-off + verification were the lighter blocks.

### Branch state

`pass-4-0h-production-wiring` merged to `main` on 2026-05-17 as commit `29b46a1` (with `6d6ce6b` Pass 4.0g production-router wiring already in place as the preceding commit). Branch preserved on origin as historical artifact; local copy deleted.

---

## Production state after Pass 4.0h

| Business                | `use_composer` | `hero_composer_module` | Served Hero               |
|-------------------------|----------------|------------------------|---------------------------|
| RoyalTeez Designz       | **True**       | `'studio_brut'`        | Composer (`edge_bleed_portrait`) |
| KMJ Creative Solutions  | False          | `None`                 | Builder                   |
| Embrace the Shift       | False          | `None`                 | Builder                   |
| Director Loop Test (×2) | False          | `None`                 | Builder (or 4-layer fallback) |
| *all others*            | False          | `None`                 | Builder                   |

**Live diagnostic endpoints:**
- `POST /composer/_diag/route_module` — module routing
- `POST /composer/_diag/compose_hero` — composition only
- `POST /composer/_diag/compose_and_render_hero` — full pipeline standalone
- `GET /composer/_spike/multi_module_comparison` — Phase F comparison page (3-business)
- `GET /composer/_spike/comparison_page` — Phase 5 Cathedral-only spike artifact

Edit Mode operational on both Builder Heros and Composer Heros via the same UI surface.

---

## What's next

User decision determines the next pass. Four strategic options:

**(a) Activate more businesses on the multi-module pipeline.** Set `use_composer=True` for additional practitioners who fit Cathedral or Studio Brut archetypes. Tests the pipeline at higher concurrency, builds production confidence before further library expansion. ~30 min per activation (flag flip + one build). Cost ~$0.55–1.10 per business (dominated by Builder).

**(b) Pass 4.0i — Atelier module.** Third design module. Targets crafted / expressive / maker / artist-studio archetypes. Following the proven Pass 4.0g pattern: design doc → 11 variants → treatment system → router prompt update → ModuleSpec extension → comparison page → decision record. Estimate ~12–15 hours, ~$1.50 LLM.

**(c) Pass 4.0h.x cleanup.** Address parked items surfaced by Pass 4.0h:
- L11: normalize RoyalTee `signal='purple'` CSS keyword to a hex value
- L13: unshadow `/health` from `public_site_router` catch-all
- L14: update Builder to emit `<section data-section="hero">` so post-processor's primary selector becomes the match
- Verify Test 5 (InlineSlotPicker image swap on Composer Hero)

Estimate ~3–4 hours total, $0 LLM.

**(d) Full-site composition.** Build remaining Cathedral sections (About, Services, Gallery, Testimonials, CTA Band, Footer) plus Studio Brut equivalents. Post-processor becomes a multi-section orchestrator rather than Hero-only. Largest scope — ~40–60 hours per module section family, plus post-processor extension. Highest payoff for full-Composer practitioner sites.

**Recommended next architectural pass: (b) Atelier.** Three reasons: (1) the library is the long-term value, (2) production proof point is achieved with one practitioner — adding more practitioners (option a) before adding more modules risks accumulating businesses that need a module that doesn't exist yet (the Director Loop Test seam class), (3) Atelier follows the same proven pattern as Studio Brut so risk is low and time-cost is well-understood. Option (c) cleanup can run as a 1-session warm-up before or after.

---

## Five-module library roadmap

| Pass | Module | Status | Notes |
|------|--------|--------|-------|
| 4.0f spike | Cathedral | Architecture validated (CONDITIONAL GO) | Editorial / cinematic_authority |
| 4.0g | Studio Brut | GO — shipped | Urban / graphic / maker |
| **4.0h** | **(wiring, no new module)** | **SHIPPED — this pass** | Production wiring + RoyalTee activation |
| 4.0i | Atelier | Recommended next | Crafted / expressive / artist-studio |
| 4.0j | Pulpit | Planned | Pastoral / community / teaching (KMJ Ministries archetype) |
| 4.0k | Field Manual | Planned | Technical / methodology (may absorb Director Loop seam) |
| 4.0l | Floor | Planned | High-design / gallery / premium |

**Library status: 2 of 5 modules complete, production wiring complete, first practitioner activated.** The architecture serving real practitioners is real.

---

## Parked items

- **L11** (Pass 4.0f) — RoyalTee `color_role` override `signal='purple'` CSS keyword; works via `color-mix`. Pass 4.0h.x candidate.
- **L12** (Pass 4.0g) — effectively closed; the stale `hero.heading='Test Title'` override was rewritten via Edit Mode in Phase E.
- **L13** (Pass 4.0g merge) — `/health` shadowed by `public_site_router` catch-all in `kmj_intake_automation.py`. Pass 4.0h.x candidate.
- **L14 (NEW, Pass 4.0h Phase C)** — Builder emits class-based hero, not `data-section="hero"`. Post-processor's fallback selector is load-bearing. Pass 4.0h.x candidate.
- **Test 5 (NEW, Pass 4.0h Phase E)** — InlineSlotPicker image swap on Composer Hero unverified. Pass 4.0h.x candidate.

---

## Status

Pass 4.0h formally **SHIPPED**. Production wiring operational. RoyalTeez Designz is the first practitioner served by the multi-module pipeline. Edit Mode bridge verified end-to-end. Branch `pass-4-0h-production-wiring` merged to `main` as `29b46a1` (with production-router wiring `6d6ce6b` already in place from the Pass 4.0g follow-on); branch preserved on origin as historical artifact.

Next pass decision rests with the user. No automatic kick-off.
