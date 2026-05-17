# Studio Brut — Treatment System Audit

**Phase:** Pass 4.0g Phase C
**Authored:** 2026-05-16
**Status:** Authoritative reference for Studio Brut treatment dimensions

This document captures, dimension by dimension, how Studio Brut's treatment translators interpret each of the 8 shared dimensions differently from Cathedral's. Every dimension MUST produce visibly different output between modules when given the same brand_kit + content; if it doesn't, the dimension's Studio Brut translator needs strengthening.

Reading order: Pair with `STUDIO_BRUT_DESIGN.md` for aesthetic principles. Pair with `hero/treatments/*.py` for the actual translator code. This audit is the bridge between principle and implementation.

---

## 1. `color_emphasis` — same purpose, sharper outputs

| Option | Cathedral | Studio Brut | Distinctness driver |
|---|---|---|---|
| `signal_dominant` | heading text-primary, emphasis signal, eyebrow signal, CTA bg signal | heading text-primary, emphasis signal, eyebrow signal, CTA bg signal | **Distinctness lives in the CTA primitive** — Cathedral pill (999px radius, soft drop-shadow); Studio Brut sharp rect (4px radius, hard-offset 4-4-0 shadow). Same role mapping, dramatically different rendered button. |
| `authority_dominant` | heading authority, emphasis signal, eyebrow authority, CTA bg authority | heading authority, emphasis signal, eyebrow authority, CTA bg authority | Same as above — primitive shape carries the visual difference. |
| `dual_emphasis` | heading authority, eyebrow signal, **CTA bg signal** | heading authority, eyebrow signal, **CTA bg authority** | Studio Brut keeps authority CTA so signal energy concentrates in eyebrow + emphasis word, not on the action. Cathedral's dual_emphasis spreads signal across more surfaces. |

**Why outputs look different anyway:** Studio Brut's CTA primitive emits a sharp rectangular button with hard-offset shadow, regardless of color emphasis. Cathedral's CTA primitive emits a 999px-radius pill with soft drop-shadow. The color values may be the same, but the shape carrying the color is brutalist where Cathedral's is editorial.

---

## 2. `spacing_density` — denser at every step

| Option | Cathedral padding-y | Studio Brut padding-y | Cathedral gap | Studio Brut gap |
|---|---|---|---|---|
| `generous` | `clamp(80px, 12vw, 160px)` | `clamp(60px, 9vw, 140px)` | 32px | 28px |
| `standard` | `clamp(60px, 9vw, 100px)` | `clamp(40px, 6vw, 90px)` | 24px | 20px |
| `compact` | `clamp(40px, 6vw, 60px)` | `clamp(28px, 4.5vw, 48px)` | 16px | 12px |

**Why:** Per STUDIO_BRUT_DESIGN.md Section 5 ("Density over breathing room"), every Studio Brut spacing tier runs tighter than Cathedral's equivalent. Studio Brut max-content-width also runs tighter (1180px / 1120px / 1080px vs Cathedral's 1240px / 1180px / 1120px).

---

## 3. `emphasis_weight` — supplementary scales, dimension consumed in primitives

Both modules consume `emphasis_weight` primarily inside primitives (`heading.py` / `subtitle.py` / `eyebrow.py`) via `treatments.emphasis_weight` reads — the translator emits supplementary rhythm/scale vars but doesn't carry the headline differentiation.

| Effect | Cathedral | Studio Brut |
|---|---|---|
| `heading_dominant` heading clamp | `clamp(3rem, 8vw, 6rem)` | `clamp(3.5rem, 12vw, 11rem)` |
| `balanced` heading clamp | `clamp(2.5rem, 6vw, 4rem)` | `clamp(2.75rem, 8vw, 6rem)` |
| `eyebrow_dominant` heading clamp | `clamp(2.25rem, 5vw, 3.5rem)` | `clamp(2.25rem, 6vw, 4.5rem)` |
| Heading baseline weight | 900 | 800 (reserves 900 for emphasis modes) |
| Heading default line-height | 1.05 | 0.95 (tighter, more dense) |

**Why:** Studio Brut leans into type-as-graphic (Section 3 of the design doc). `heading_dominant` Studio Brut headings can reach 176px (clamp 11rem) — near-room-scale. Cathedral's max is 96px (6rem) — display scale, not poster scale.

---

## 4. `background_treatment` — bold commitments, no soft fades

| Option | Cathedral | Studio Brut |
|---|---|---|
| `flat` | warm-neutral solid (`#F8F6F1` editorial cream default) | warm-neutral solid (`#F4F4F0` graphic-poster off-white default) |
| `soft_gradient` | **subtle** — 135deg from warm-neutral to 9% signal-tint to 6% authority-tint mixed in | **bold** — 135deg from authority 0% → authority 50% → signal 100% at FULL SATURATION (no tint mixing) |
| `textured` | fractal-noise SVG at **180px tile, 18% opacity**, multiply blend | halftone-dot SVG at **24px tile, 22% opacity dots**, multiply blend (screen-print aesthetic) |
| `vignette` | radial transparent 38% → authority 18% edge tint | radial transparent 30% → authority 35% edge tint (nearly 2× the edge darkness) |

**Why:** Cathedral's `soft_gradient` is editorial restraint ("you should sense the depth"). Studio Brut's `soft_gradient` is poster commitment ("you should see the gradient from across the room"). Same dimension name, opposite intent. Per STUDIO_BRUT_DESIGN.md Section 5 ("Sharp commits, not soft fades") — if Studio Brut uses a gradient, it reads from 20 feet away.

The textured option differs in pattern character (fractal noise reads as paper grain; halftone dots read as screen-print) AND tile size (Cathedral's 180px barely repeats; Studio Brut's 24px is visibly tiled).

---

## 5. `color_depth_treatment` — brutalist hard-offset shadows replace editorial drop-shadows

| Option | Cathedral CTA shadow | Studio Brut CTA shadow |
|---|---|---|
| `flat` | `0 8px 24px rgba(0, 0, 0, 0.12)` (soft drop-shadow) | `4px 4px 0 var(--brand-text-primary, #09090B)` (hard-offset, no blur) |
| `gradient_accents` | `0 12px 28px rgba(0,0,0,0.18), 0 4px 10px (signal-tinted blur)` | `5px 5px 0 var(--brand-text-primary, #09090B)` (hard-offset, larger) |
| `radial_glows` | `0 0 36px (signal-tinted glow), 0 8px 24px (deep blur)` | `0 0 40px (signal-tinted glow), 0 10px 28px (deep blur)` (only tier where SB drops the hard-offset for glow) |

| Option | Cathedral emphasis gradient | Studio Brut emphasis gradient |
|---|---|---|
| `gradient_accents` | signal → signal mixed 50% with deep-secondary (signal → muted darker signal) | signal → authority (signal → bold contrasting authority — pure 2-stop, no mixing) |

| Option | Cathedral emphasis glow | Studio Brut emphasis glow |
|---|---|---|
| `radial_glows` | 24px + 8px signal blur halos at 45% / 60% mix | 32px + 12px signal blur halos at 55% / 80% mix |

**Why:** Studio Brut commits to brutalist-web aesthetic — the hard-offset shadow on the CTA is the module's signature button move. It reads as physical, declarative, intentionally low-fi. Cathedral's soft drop-shadows read as editorial polish. Per Section 4 of the design doc ("Sharp edges, never softened... when shadows appear, they're hard offset shadows").

The gradient values differ too — Cathedral mixes the gradient endpoints toward darker tones for refinement; Studio Brut keeps them at full saturation for poster impact.

---

## 6. `ornament_treatment` — hotter multipliers, more satellites, NO diamonds

| Option | Cathedral opacity / size | Studio Brut opacity / size |
|---|---|---|
| `minimal` | 0.55 / 0.8 | 0.7 / 0.85 |
| `signature` | 0.9 / 1.0 | 0.95 / 1.0 |
| `heavy` | 1.0 / 1.4 + **4 satellite diamonds** | 1.0 / 1.55 + **6 satellite mixed shapes** (squares + circles + small color blocks) |

**Shape vocabulary** — the most fundamental difference:

| Cathedral ornament | Studio Brut ornament |
|---|---|
| `render_diamond_motif` — rotated square (the Cathedral signature) | `render_square_marker` (upright square), `render_circle_marker`, `render_bar` (thick architectural divider), `render_color_block` (arbitrarily-sized solid rectangle) |
| Diamond-rule variants (vertical_manifesto, etc.) | Bar dividers + color block dividers |
| 4 satellite diamonds on `heavy` | 6 satellites mixing squares, circles, and a color block |

**Why:** STUDIO_BRUT_DESIGN.md Section 4 ANTI-PATTERN explicitly bans diamonds across the module. Studio Brut's ornament vocabulary is squares, rectangles, circles, bars, and color blocks. Multipliers run slightly hotter than Cathedral at every tier — Studio Brut at `minimal` is more visible than Cathedral at `minimal`, matching the "density over breathing room" principle.

---

## 7. `typography_personality` — fundamentally different font world + emphasis-mode switching

| Option | Cathedral (Playfair Display variants) | Studio Brut (display sans / condensed / brutalist) |
|---|---|---|
| `editorial` | Playfair 900, line-height 1.05, tracking -0.025em — editorial classic | Druk / Bebas Neue / Space Grotesk 800, line-height 0.95, tracking -0.02em — Cathedral's "editorial" is romantic-serif; Studio Brut's is graphic-poster-sans |
| `bold` | Playfair 900, line-height 0.95, tracking -0.04em | Sans-stack 900, line-height 0.9, tracking -0.04em, **UPPERCASE** |
| `refined` | Playfair 500, line-height 1.15, tracking -0.005em — quiet poetic | Sans-stack 600, line-height 1.0, tracking 0em — lighter weight but still graphic, never romantic |
| `playful` | Playfair italic 600, italic subtitle, eyebrow 0.32em — italic-led whimsy | Sans-stack 700, subtitle italic, eyebrow italic, eyebrow 0.36em, **CTA also italic** — playful via tracking + italic on supporting elements while heading stays upright |

**Heading emphasis-mode switching** (Studio Brut only):

Cathedral's heading emphasis is ALWAYS italic + signal-color. Same pattern across every typography setting. Studio Brut switches the emphasis mode based on typography:

| Studio Brut typography | Emphasis mode | Visual result |
|---|---|---|
| `editorial` | COLOR contrast | signal-colored word inside text-primary heading |
| `bold` | WEIGHT contrast | weight 900 word among weight 900 neighbors (the WORD is larger weight than the heading-level weight); intra-line bump |
| `refined` | SCALE contrast | 1.4em-larger oversized word among smaller |
| `playful` | SCALE + COLOR combined | 1.45em-larger AND signal-colored word — most graphic |

Cathedral has ONE emphasis pattern; Studio Brut has FOUR. This is the single largest architectural difference between the modules' treatment systems.

---

## 8. `image_treatment` — duotone overlays, more aggressive filters

| Option | Cathedral filter | Studio Brut filter | Studio Brut adds |
|---|---|---|---|
| `clean` | none | none | (no overlay) |
| `filtered` | `saturate(0.88) contrast(0.96)` (subtle desaturate) | `saturate(0.85) contrast(1.05)` (more contrast) | **signal-color duotone overlay** at 12% opacity |
| `dramatic` | `saturate(1.15) contrast(1.18) brightness(0.96)` | `saturate(1.2) contrast(1.25) brightness(0.92)` (more impact at each axis) | **authority-color duotone overlay** at 22% opacity |
| `soft` | `saturate(0.95) contrast(0.98)` + radial mask | `saturate(1.0) contrast(1.0)` (no desaturate) + radial mask | (no overlay) |

**Why:** Per STUDIO_BRUT_DESIGN.md Section 6 — Studio Brut treats images as graphic statements, not contemplative photography. The duotone overlays (applied via a `<div>` sibling to the `<img>` reading `var(--sb-image-overlay)`) push photos toward brand-color editorial fashion grade without needing GPU duotone processing.

Cathedral's `filtered` reduces the photo's intensity for editorial restraint. Studio Brut's `filtered` boosts contrast AND adds a signal-tint overlay — the photo still feels like graphic-design material, not unfiltered reportage.

---

## Cross-module CSS variable isolation

| Module | CSS var prefix |
|---|---|
| Cathedral | `--ca-*` (e.g., `--ca-bg-color`, `--ca-emphasis-bg`) |
| Studio Brut | `--sb-*` (e.g., `--sb-bg-color`, `--sb-emphasis-bg`) |

Shared (cross-module) vars:
- `--brand-*` (authority, signal, warm-neutral, deep-secondary, text-primary, text-on-authority, text-on-signal) — set by the brand-kit renderer regardless of module
- `--cta-bg`, `--cta-text` — set by both modules' color_emphasis translators; consumed by both modules' CTA primitives
- `--heading-color`, `--emphasis-color`, `--eyebrow-color`, `--subtitle-color` — Cathedral-side names retained for primitive compatibility

Smoke tests in `studio_brut/hero/__tests__/test_variants.py` assert NO `--ca-*` var leaks into Studio Brut output. This is enforced at render time, not just by convention.

---

## Test coverage

The Phase B smoke pass already validated 99 renders (11 variants × 3 treatment tiers × 3 content fixtures) all pass:

- `<section data-section="hero">` root present
- ≥5 `data-override-target` attrs (eyebrow / heading / heading_emphasis / subtitle / cta_primary)
- `var(--brand-*)` reference present (proves brand-kit infrastructure is exercised)
- **No `diamond` class** anywhere (Cathedral signature gate)
- **No `font-style: italic` on `<h1>`** (Cathedral pattern gate)
- **No `--ca-*` var leakage** (cross-module isolation gate)

Phase C expands coverage with per-dimension assertions — for each treatment option, the corresponding CSS var must appear in the rendered output (e.g., when `background=textured` fires, `data:image/svg+xml` must appear in the section's style; when `color_depth=gradient_accents` fires, `background-clip: text` must appear on the heading-emphasis span).

---

## Appendix — what Phase C did NOT change

Phase C's audit found Phase B's treatment translators already deliberately distinct from Cathedral across all 8 dimensions. **No translator values were modified during Phase C** — the work was:

1. Formal documentation of the cross-module deltas (this file)
2. Per-dimension smoke test coverage expansion
3. 3-tier overview spot-check pages for visual confirmation

If a future module audit finds a dimension where the Studio Brut translator drifts toward Cathedral's interpretation, the fix is to strengthen the values here AND update this audit to reflect the new delta — both together, never separately.
