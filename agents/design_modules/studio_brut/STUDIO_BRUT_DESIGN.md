# Studio Brut — Module Design Document

**Module ID:** `studio_brut`
**Status:** Phase A authored 2026-05-16 (Pass 4.0g)
**Sister modules:** `cinematic_authority` (Cathedral)
**Authoritative reference for:** Phase B (variants), Phase C (treatments), Phase D (Module Router), and all subsequent Studio Brut work

This document is the design brain for Studio Brut. Every variant, every treatment value, every Composer prompt instruction, every layout decision in Studio Brut should be answerable from this document. If a future implementation choice can't be defended against what's written here, the implementation is wrong or this document needs to evolve — never both at once.

---

## 1. Studio Brut Identity

### What Studio Brut is

Studio Brut is the **bold-urban-graphic-expressive** design module. It serves brands whose visual register is high-energy, attitude-forward, color-confident, and typographically expressive — brands that want their work to be the loudest object in the room. Where Cathedral whispers with editorial confidence, Studio Brut shouts with designed intent. Both are disciplined; the discipline is just different.

### Aesthetic principles

There are five core tenets. Every Studio Brut variant must answer to all five.

1. **Color is architecture, not accent.** Studio Brut builds layouts FROM color blocks rather than placing color WITHIN white space. A section can be entirely authority-colored. A column can be entirely signal-colored. Color does structural work; it isn't an afterthought applied on top of neutral.

2. **Type is graphic material.** Headlines aren't just text content — they're visual statements with weight, scale, and spatial presence. Oversized type that fills 70-80% of viewport width is normal. Type can rotate, layer, bleed past edges, and overlap other elements. Letters and words function as designed objects.

3. **Asymmetry is the baseline.** Symmetric centered compositions are exceptions, not defaults. 70/30 and 80/20 splits, off-axis placement, intentional weight imbalance — these are how Studio Brut composes space. The eye is meant to travel, not rest centered.

4. **Sharp commits, not soft fades.** Boundaries are crisp. Color transitions are abrupt and intentional. Edges are sharp. When gradients appear, they're bold full-bleed authority-to-signal transitions, never soft atmospheric fades. Studio Brut doesn't apologize for itself with softness.

5. **Density over breathing room.** Studio Brut's "generous" is denser than Cathedral's "generous." Even spacious Studio Brut layouts have more content packed per screen. Negative space, when it appears, is carved out by surrounding color blocks — it's a deliberate architectural choice, not a default.

### What Studio Brut IS

- bold
- urban
- graphic
- expressive
- color-block-driven
- type-as-decoration
- attitude-forward
- asymmetric
- high-contrast
- dense
- declarative
- layered
- sharp-edged
- confident
- street-aware
- maker-oriented
- visually loud (when warranted)
- intentionally rule-breaking
- editorial in a graphic-design sense (not a magazine-text sense)

### What Studio Brut IS NOT

These are explicitly Cathedral's territory or other modules' territory. Studio Brut should never drift toward any of them:

- restrained
- editorial-quiet (in the contemplative-text sense)
- refined-elegant
- classical-serif-driven
- gold-and-navy authority
- generous-whitespace contemplative
- pastoral
- ceremonial
- subtle
- softly-atmospheric
- symmetric-by-default
- italic-emphasis-signature (Cathedral's pattern)
- diamond-motif-ornamented (Cathedral's pattern)
- gentle
- traditional-professional
- corporate-restrained

### Archetypal businesses

Studio Brut is the correct module for:

- **Custom apparel designers / streetwear brands** — RoyalTeez Designz is the canonical Studio Brut business. Visual portfolio brands where the work IS the brand and the brand IS attitude.
- **Design studios with edge** — branding agencies that lead with personality rather than process, illustration studios, lettering studios, type foundries.
- **Urban photographers** — street, fashion, editorial, documentary. Photographers whose work has grit and composition, not just competence.
- **Independent makers** — print shops, ceramicists with bold visual identities, leather workers with attitude, custom furniture builders whose work is visibly handmade.
- **Creative agencies that lead with personality** — small shops where the founder's voice is the differentiator, not a process diagram.
- **Lifestyle brands with attitude** — apparel-adjacent, accessories, urban culture products, anything where the customer is buying identity.
- **Music / culture / nightlife brands** — venues, labels, promoters, DJ collectives, anything tied to subculture.
- **Skate / surf / streetwear-adjacent** — board shops, custom builders, anyone whose audience reads visual culture fluently.
- **Independent restaurants and bars with strong visual identity** — taco shops with great signage, third-wave coffee with character, neighborhood bars with art-on-the-wall energy.

### Anti-archetypes

Studio Brut should NEVER serve these. The Module Router (Phase D) routes these to Cathedral or future modules instead:

- **Traditional law firms** — Cathedral or future Pulpit module
- **Financial advisors, wealth managers** — Cathedral
- **Established medical practices** — Cathedral
- **Ceremonial pastoral leadership** — Cathedral
- **Classical luxury brands** (jewelry, watches, white-glove services) — Cathedral
- **Government-adjacent businesses, public sector** — Cathedral
- **Academic institutions, research organizations** — Cathedral or future Field Manual module
- **Insurance, banking, anything where trust = restraint** — Cathedral
- **B2B SaaS with corporate buyers** — Cathedral
- **Real estate (residential)** — Cathedral

The test: if the brand's success depends on signaling *restraint, credibility-through-quietness, or institutional gravity*, it's not Studio Brut. Studio Brut serves brands whose success depends on signaling *attitude, character, and visible craft*.

---

## 2. Color Philosophy

Studio Brut's relationship to color is the single most important differentiator from Cathedral. Get this section wrong and Studio Brut becomes "Cathedral with brighter colors." Get it right and every Studio Brut composition feels structurally distinct.

### The role of brand-authority (primary color)

In Cathedral, `--brand-authority` is the section bg on dark hero variants and the heading color when `color_emphasis=authority_dominant` — used architecturally but rarely as a full color block.

**In Studio Brut, `--brand-authority` is used as full color blocks across whole sections.** A hero can be 100% authority-colored. A column in a two-column layout can be entirely authority. Authority isn't restrained to text — it's structural paint.

When Studio Brut variants use authority as a section bg, the contrast against the next section is INTENTIONAL — not softened with transitions. Authority-colored sections are architectural anchors.

### The role of brand-signal (accent color)

In Cathedral, `--brand-signal` is the italic-emphasis-word color, the diamond color, the CTA color, the eyebrow color — used as restraint accent.

**In Studio Brut, `--brand-signal` is used boldly as architectural color too.** It can be a full bg for callout sections. It can be a 30%-width vertical color block stripe down a hero. It can fill the entire CTA region as a saturated rectangle. The signal color is a co-star with authority, not a quiet accent.

Studio Brut accepts signal-on-authority compositions (high-contrast color-on-color), which Cathedral generally avoids.

### The role of brand-warm-neutral and brand-background

Cathedral uses warm-neutral (`#F8F6F1`) as the primary section bg most of the time — sections are warm-cream with content on top.

**Studio Brut uses warm-neutral less.** When Studio Brut uses neutral, it's as a quiet relief between two color-dense sections — not as a default. A typical Studio Brut hero never bottoms out on neutral; it commits to a color (authority, signal, or secondary).

When neutral DOES appear in Studio Brut, it's slightly cooler / less warm than Cathedral's warm-cream. Studio Brut's neutral has a graphic-poster off-white quality (slight gray tint) rather than Cathedral's editorial cream.

### The role of brand-secondary and brand-text-primary

Cathedral's secondary (`--brand-deep-secondary`) is typically a darker navy used for image-wrapper backgrounds and rare second-anchor moments.

**In Studio Brut, secondary often becomes a third active color**, not subordinate. Compositions with three active colors (authority + signal + secondary) are normal. Secondary can carry full sections, headline weight, or geometric ornament.

Text-primary in Studio Brut needs to handle color-block bg contexts. Variants must compute (or the brand_kit must provide) a `--brand-text-on-authority` and `--brand-text-on-signal` — already handled by the existing `brand_kit_renderer.derive_text_on` infrastructure. Studio Brut uses these aggressively because text frequently sits on colored bg, not just neutral.

### Color combinations Studio Brut embraces

- **High-contrast pairings** — signal-on-authority, authority-on-signal, text-primary on authority, secondary on signal.
- **Color-on-color** — signal-colored heading on an authority-colored section bg. Cathedral avoids this; Studio Brut leans into it.
- **Saturated palettes** — when the brand_kit colors are saturated, Studio Brut uses them at full saturation. No desaturation for "tastefulness."
- **Three-active-color compositions** — authority hero, signal callout, secondary footer band. Three colors all carrying structural weight.
- **Inverse compositions** — entire dark sections with light-colored type (signal text on near-black secondary).

### Gradient philosophy

- **Bold gradients YES.** Authority-to-signal full-bleed gradients used as section bg. Diagonal gradients with strong angle (135deg, 45deg). Saturated, confident, declarative.
- **Subtle gradients NO.** Cathedral's 9% signal-mix soft_gradient backgrounds are wrong for Studio Brut. If Studio Brut uses a gradient, you should be able to read it as a designed choice from 20 feet away.
- **Sharp boundaries, not soft transitions.** Studio Brut prefers a hard line between two color blocks over a gradient transition between them. Gradient transitions, when used, are dramatic — full color shifts, not tonal washes.

### Color treatment on imagery

- **Duotone treatments** using brand-authority and brand-signal. Cathedral uses unfiltered editorial photography; Studio Brut readily applies brand-color duotones.
- **High saturation.** Studio Brut images often have boosted saturation and contrast as deliberate aesthetic choices, not just "natural with a filter."
- **Dramatic filters welcome.** High contrast, deep shadows, blown highlights when the brand calls for it. Editorial fashion / street photography references.
- **Color-block layering on images.** A solid signal-colored rectangle can overlap the corner of an image. A diagonal authority-colored band can cross an image. Image and color block are layered compositions, not separate elements.

---

## 3. Typography Philosophy

Cathedral uses Playfair Display (display serif), weight 900 default, italic-emphasis-word as the signature pattern. **Studio Brut typography is fundamentally different in every dimension.**

### Weight philosophy

- **Heavier baseline weights.** Headlines: weight 700-900. Subtitles and body: weight 500-700. Studio Brut never uses 400-weight headlines. Heavy is the default; light is the exception.
- **Weight contrast within single headings** — a heading can pair a 900-weight word with a 300-weight word in the same line. This is Studio Brut's replacement for Cathedral's italic-emphasis pattern. Weight contrast carries semantic emphasis where Cathedral uses italic + signal color.

### Font character

- **Display fonts permitted and encouraged.** Condensed sans (Druk, Bebas Neue style), expanded display, geometric (Futura-derivatives, Space Grotesk), slab-serif (Roboto Slab, Recoleta), brutalist sans (Neue Haas Grotesk, Inter Display weights). Studio Brut typeface selection carries personality.
- **Less reliance on classical serif.** Playfair Display is Cathedral's signature; Studio Brut should NEVER default to Playfair. When Studio Brut uses serif, it's slab-serif or brutalist-serif (sharp serifs, condensed proportions), not the classical-romantic serif tradition.
- **Suggested default stack for Studio Brut headlines:** `Druk`, `Bebas Neue`, `Space Grotesk`, `Archivo Black`, `Inter` (extreme weights only — 800-900). Phase B will lock the canonical font stack — these are the strong candidates.

### Type as graphic

- **Oversized type as visual statement.** Headlines can fill 70-80% of viewport width — `clamp(4rem, 14vw, 12rem)` ranges are not extreme for Studio Brut. They're normal for hero variants.
- **Type that breaks the grid.** A headline can overflow its container by 10-15%, intentionally bleeding past the column it lives in. This is Studio Brut design language, not a bug.
- **Type that rotates, layers, overlaps.** A 90deg-rotated vertical word as ornament. A semitransparent oversized letterform layered behind the heading. Word stacks layered over color blocks. These are Studio Brut's compositional tools.

### Letter-spacing approach

Cathedral uses tight `-0.025em` tracking on headlines as default. Studio Brut is variable:

- Eyebrow labels still get wide tracking (0.2em-0.32em) — small-caps with breathing room. This convention crosses both modules.
- **Headlines have tight or normal spacing** (`-0.02em` to `0em`). When using condensed display fonts, tracking can be `0` because the font's intrinsic width handles density.
- **No universal "all caps tracked widely" rule.** Studio Brut uses all-caps freely but doesn't always track them wide. A 900-weight condensed sans-serif headline in all caps with `0em` tracking is normal Studio Brut.

### Italic role

- **Less reliance on italic.** Studio Brut uses weight and scale contrast for emphasis more than italic. Italic still permitted but never as the signature emphasis pattern.
- The Cathedral italic-emphasis-word pattern in the heading is REPLACED in Studio Brut by either weight contrast (one heavy word + one light word) or scale contrast (one word much bigger than its neighbors) or color contrast (one word in signal, rest in authority/text).

### Numerals and codes

- **Monospace numerals for stat displays.** When Studio Brut variants surface numbers (years, counts, case numbers, edition numbers), they use monospace. Inter Mono, JetBrains Mono, Space Mono are good candidates.
- **Codes as design elements.** Patterns like `CASE 23.041`, `VOL. II`, `SVC.04`, `EDITION 03` are Studio Brut design vocabulary. Numbers function as graphic ornament.

### Type-as-ornament

- **Oversized single letters.** A 30vw-tall letter "R" sitting in a section corner. A massive number "01" anchoring a list. Letterforms function as decorative shapes.
- **Repeated text patterns.** A word repeated three times at decreasing size. A subtitle that says "STUDIO STUDIO STUDIO" as graphic statement. Word stacks as compositional element.
- **Type compositions as graphic art.** Headlines arranged across multiple lines with intentional baseline shifts, mixed weights, mixed scales. The headline IS the visual.

---

## 4. Ornamentation Style

Cathedral's diamond motif is its single most identifiable ornament. **Studio Brut doesn't use diamonds — ever.** Studio Brut's ornament vocabulary is different.

### Geometric shape vocabulary

- **Squares and rectangles.** Solid color blocks of various sizes. Architectural building blocks of the layout.
- **Circles.** Used sparingly but powerfully — as oversized framing devices, as eyebrow markers, as stat-disc backgrounds. Not as soft decoration.
- **Lines and bars.** Thick horizontal or vertical bars (4-12px stroke) as section dividers — different from Cathedral's thin gold rules. Studio Brut bars are architectural, not delicate.
- **Asymmetric quadrilaterals.** Parallelograms, trapezoids, intentionally off-square shapes. These add visual energy without being random.

### Color blocks as ornament

- **Solid colored rectangles** as decorative elements. A signal-colored square in the corner of a section. An authority-colored stripe across the top of a card.
- **Asymmetric color compositions.** A 30/70 horizontal split of authority-color over signal-color as a section divider.
- **Intentional negative space carved by colored shapes.** A neutral-colored hexagonal "window" carved out of a surrounding authority-colored block. Negative space is shaped by what's around it.

### Type as ornament

- Already documented in Section 3. Worth repeating: oversized letterforms, repeated word patterns, type compositions as decorative graphic.

### Numbers and codes as visual interest

- `01/03`, `CASE — 23`, `SVC.04`, `VOL. II`, `EDITION 03`
- `EST. 2024`, `MADE IN BROOKLYN`, `LOT 47`
- Codes function as design vocabulary — they signal craft + intentionality + the maker-aesthetic Studio Brut serves.

### Lines and bars

- **Thick horizontal bars** (6-12px) as section dividers — full-bleed or contained.
- **Vertical color bars** as architectural elements within columns (e.g., a 12px signal-colored vertical stripe between two text columns).
- **Bar-and-label patterns** — a horizontal bar with a small uppercase label hanging off one end ("SECTION 01" / "—————————").

### Sharp edges

- **Ornaments never soften.** No rounded corners on Studio Brut ornaments unless the brand-kit specifically signals a rounded aesthetic. Even then, rounded is the exception.
- **Sharp, intentional, declarative.** Every ornament is a deliberate design statement, not soft decoration.

### Layering

- **Ornaments can overlap content.** A color block behind a heading. A geometric shape over an image edge. A massive letterform sitting behind a stat display.
- **Z-depth is a real design tool.** Studio Brut uses absolute positioning, transforms, and z-index aggressively. Cathedral mostly stacks linearly; Studio Brut layers.

### Anti-ornaments

Studio Brut should never use:

- **Diamonds** — Cathedral's signature, off-limits in Studio Brut
- **Soft floral or botanical elements** — wrong register
- **Script flourishes or calligraphic decoration** — wrong typographic family
- **Soft gradients as primary atmosphere** — Studio Brut commits to bold
- **Subtle textures as primary ornament** (delicate noise overlays) — textures, when used, are bold and graphic (halftone dot patterns at scale, screen-print misregistration aesthetics)
- **Drop shadows used "softly" for depth** — when shadows appear, they're hard offset shadows (think early-90s graphic design, brutalist web)

---

## 5. Layout Philosophy

Cathedral favors editorial proportions, centered manifestos, and generous whitespace. **Studio Brut's layout DNA is different along every axis.**

### Asymmetry pushed further

- **70/30 and 80/20 splits are normal**, not extreme. Cathedral uses 60/40 and 50/50 as its asymmetric variants; Studio Brut goes further.
- **Symmetric centered layouts are rare.** A centered manifesto hero might appear once in a Studio Brut variant set, but it's the exception — and even then, the centering is broken by an off-axis ornament or asymmetric color block behind.

### Grid violations as intentional

- **Content can break out of expected containers.** Headlines overflow column widths. Images bleed past margins. Color blocks extend beyond section boundaries.
- **Negative grid use.** Sometimes the most powerful Studio Brut move is to push a single element off-grid against a strong grid context — the violation IS the design.

### Color block architecture

- **Layouts built FROM color blocks**, not just placed within them. A Studio Brut hero might be three vertical color stripes (authority / neutral / signal at 30/50/20 widths) with content positioned across them, rather than a single neutral bg with content centered.
- **Sections defined by color rectangles, not white space.** Where Cathedral signals section boundaries with whitespace + ornament, Studio Brut signals them with abrupt color changes.

### Density variation

- **Studio Brut "generous" is denser than Cathedral "generous."** Even the most spacious Studio Brut layouts have more content density and visual incident per screen than Cathedral's standard.
- **"Compact" in Studio Brut packs aggressively.** Multiple stat blocks, image strips, and CTAs can coexist in a single dense composition. This isn't crowding — it's intentional editorial density.

### Vertical motion

- **Stronger vertical rhythm.** Sections can stack tightly. Visual journey down the page has more energy than Cathedral's contemplative scroll.
- Cathedral wants the reader to slow down. Studio Brut wants the reader to feel motion.

### Negative space used aggressively

- **When negative space appears, it's a deliberate architectural choice.** Not breathing room. The negative space is defined and shaped by the surrounding color blocks — it's an active design element, not the absence of design.
- A 200px-tall band of pure neutral between two color-dense sections is a *statement* in Studio Brut. It draws attention because of the surrounding density.

### Image bleed

- **Dramatic, never half-measure.** If an image bleeds in Studio Brut, it goes to the viewport edge. No 16px gutter on the bleed side. No "partial bleed."
- **Asymmetric bleed.** Image bleeds on one side, contained on the other. The bleed direction is a deliberate compositional choice.

### Stacking and layering

- **Vertical color stacks.** Multiple full-width color bands stacked vertically. The page becomes a series of architectural color layers.
- **Layered cards and elements.** Cards can overlap. Images can overlap color blocks. Type can sit on top of imagery. Z-axis composition.
- **Overlapping compositions welcome.** Studio Brut accepts visual complexity where Cathedral prefers clarity.

---

## 6. Image Philosophy

Cathedral treats images as integrated, framed, contemplative. **Studio Brut images are graphic elements that participate in the composition as visual co-stars.**

### Image as graphic statement

- **Photography selected for visual impact**, not just business representation. A photo isn't proof-of-work; it's a designed element.
- **Strong compositions, deliberate moments, attitude.** Photos with clear focal points, unusual angles, expressive content.

### Filter and treatment

- **Duotone treatments** using brand-authority and brand-signal. CSS `filter: grayscale(1)` + a brand-color overlay with `mix-blend-mode: multiply` or `screen` — produces a duotone effect entirely in CSS, no image processing required.
- **High contrast and saturated highlights** when the photo can carry it.
- **Dramatic shadows.** Deep blacks, blown highlights — not naturalistic photography but designed photography.
- **Editorial fashion / street photography aesthetic.** Reference vocabulary: i-D Magazine, Dazed, Fader, Highsnobiety, Vogue Italia editorial work, William Klein's street work, Daido Moriyama high-contrast.

### Scale and bleed

- **Images often oversized.** Hero images can be 100vw × 80vh. The image dominates the section physically.
- **Full-bleed sections.** Image-only sections that fill the viewport are normal Studio Brut moves.
- **Edge-bleeding asymmetric compositions.** Image bleeds on one or two sides, contained on the others, with content overlapping the contained edge.

### Photography style preferences

- **Editorial fashion** — model-led, garment-focused, dynamic composition.
- **Street photography** — candid energy, urban context, environmental storytelling.
- **Product photography with attitude** — products positioned in environments, dramatic lighting, conceptual rather than catalog-style.
- **Lifestyle with grit** — real settings, working light, character.
- **Less corporate portraiture, more character-driven imagery.** A founder portrait in Studio Brut is shot in the studio environment with working light, not in front of a backdrop with rim lights.

### Layered composition

- **Images layered with color blocks.** A signal-colored rectangle overlapping the corner of an image. An authority-colored bar crossing the bottom third.
- **Images layered with type.** Heading text sitting on top of the image (with proper contrast handling). The image isn't a separate decorative element — it's part of the typographic composition.
- **Images layered with graphic elements.** Geometric shapes overlapping image edges. Lines drawn across image surfaces.

### Crop and framing

- **Tighter crops, dramatic framing choices.** Less safe centered composition.
- **Dynamic compositions.** Subjects placed in corners, on diagonals, with intentional negative space.
- **Cinematic aspect ratios.** 16:10, 21:9, 4:5 portrait — not just 4:3 / 16:9.

### Image-content relationship

- **Image and content can compete for attention** rather than image supporting content. Studio Brut layouts accept this tension and use it as design energy.
- **The image isn't always subservient.** Sometimes the image is the hero and the text is the caption. Sometimes the text is the hero and the image is the texture. Studio Brut variants explore both arrangements.

---

## 7. Voice and Copy

Cathedral copy is declarative, restrained, authority-claiming. **Studio Brut voice is direct, energetic, and personality-forward.**

### Sentence rhythm

- **Shorter sentences.** Punchier cadence. Less qualification, more declaration.
- **Phrase-based delivery permitted.** "Bold work. Done right. No filler." reads as Studio Brut. Cathedral would write a full sentence.

### Direct address

- **Speaking TO the reader, not ABOUT the practice.** "Your style." "Your work." "Your statement."
- **Imperative voice frequent.** Commands and invitations carry the brand energy.

### Energy in language

- **Confident verbs.** Active voice. Words that sound spoken, not written.
- **Exclamation-adjacent without actual exclamation marks.** The energy is in the word choice and rhythm, not the punctuation. Studio Brut almost never uses `!` — the language carries the energy.

### Wordplay and personality

- **Puns, double meanings, brand-specific vocabulary** that signals personality. Cathedral avoids wordplay; Studio Brut embraces it when the brand calls for it.
- **Brand-specific vocabulary.** A custom apparel brand can use clothing language ("Crown your closet"). A skate shop can use board language. A coffee roaster can use bean-and-grind language. Studio Brut copy speaks the brand's domain dialect.

### Specificity over abstraction

- **Concrete nouns and verbs.** "Crown your closet" not "elevate your wardrobe." "Your story stitched" not "personalized apparel solutions." Concrete language carries Studio Brut energy; abstraction kills it.

### Imperative voice

- **Commands and invitations.** "Start your design." "Find your voice." "Wear your story." "Cut the noise." "Make it loud."
- Cathedral CTAs lean toward stately verbs ("Begin", "Reserve", "Schedule"). Studio Brut CTAs lean toward action verbs ("Start", "Wear", "Cut", "Make", "Drop").

### Brevity

- **Cathedral manifestos give way to tighter taglines.** A Cathedral heading might be 8-12 words; a Studio Brut heading is often 4-7.
- **Studio Brut says more with less.** A 4-word heading + a 6-word subtitle can carry more brand identity than a 14-word Cathedral manifesto for the right brand.

### Heading patterns

- **Shorter, more declarative.** Often noun phrases or imperatives, less often complete sentences.
- **Subtitle can amplify OR counterpoint heading.** Cathedral subtitles tend to clarify; Studio Brut subtitles can punch back, contradict, extend, or pivot.
- **CTA verbs are action-oriented.** See Imperative voice above.

---

## 8. Defaults When Brand Kit Is Missing

When `businesses.settings.brand_kit` is empty or partial, the render layer falls back to module defaults. Cathedral falls back to navy / gold / cream. **Studio Brut needs a fundamentally different fallback palette that signals the module's DNA at first glance.**

### Canonical Studio Brut defaults

| Role | Variable | Hex | Notes |
|---|---|---|---|
| Authority | `--brand-authority` | `#DC2626` | Deep urban red (Tailwind red-600). Carries graphic-poster energy without skewing toward kitsch (orange/yellow can feel playground-y). Pairs cleanly with both yellow and black. |
| Signal | `--brand-signal` | `#FACC15` | Bright punch yellow (Tailwind yellow-400). Maximum contrast against red and against near-black secondary. The graphic-design canonical high-impact pairing. |
| Warm-neutral | `--brand-warm-neutral` | `#F4F4F0` | Off-white with slight cream tint. Less warm than Cathedral's `#F8F6F1` — leans graphic-poster off-white rather than editorial cream. Provides relief between dense color sections without going sterile-pure-white. |
| Secondary | `--brand-deep-secondary` | `#18181B` | Near-black (Tailwind zinc-900). Architectural anchor for inverse compositions. Red and yellow read at full intensity against this. |
| Text-primary | `--brand-text-primary` | `#09090B` | Near-pure black (Tailwind zinc-950). Maximum legibility on warm-neutral. Studio Brut text is uncompromising. |
| Text-on-authority | `--brand-text-on-authority` | `#FFFFFF` (derived) | White text on red authority bg. The `derive_text_on` helper resolves this from the contrast computation. |
| Text-on-signal | `--brand-text-on-signal` | `#09090B` (derived) | Near-black on yellow signal bg. Resolves via the same contrast helper. |

### Why these defaults

The combination of `#DC2626` red + `#FACC15` yellow + `#18181B` near-black + `#F4F4F0` off-white is the canonical Studio Brut DNA palette: the brutalist graphic-design / Soviet poster / Swiss-school-meets-streetwear lineage. Red carries urban-edge attitude without skewing kitsch (orange skews playground; deep-blue skews corporate). Yellow as signal because it produces the highest-impact contrast against both red and the near-black secondary — every Studio Brut hero needs that signal-on-deep-anchor pairing to read as bold. Off-white not pure white because Studio Brut isn't sterile minimalist; it's textured-graphic and warm-leaning. Near-black secondary becomes the architectural anchor that lets red and yellow pop at full saturation.

These defaults exist for the case when a brand_kit is genuinely empty (early-stage business, demo, fallback render). Practitioners who pick their own bold brand_kit (purple, magenta, electric blue, lime green, etc.) replace these defaults entirely — the module's DNA is independent of the canonical default palette.

---

## 9. Studio Brut Anti-patterns

Documented to keep the aesthetic disciplined. If a Studio Brut variant or composition slides toward any of these, the implementation has drifted toward Cathedral or generic modernism.

- **No diamond motifs.** Cathedral's territory. Studio Brut uses squares, rectangles, circles, bars, and asymmetric quadrilaterals.
- **No classical serif headlines as default.** Playfair Display and its romantic-serif siblings are Cathedral's signature. Studio Brut uses display sans, condensed sans, slab-serif, or brutalist-serif.
- **No 400-weight headlines.** Heavy is the baseline. 700-900 for headlines, 500-700 for body. Light weights appear only as deliberate contrast within heavier compositions.
- **No soft gradient backgrounds as primary atmosphere.** Bold gradients yes (authority-to-signal full-bleed). Soft 5-10% tinted fades NO. If Studio Brut uses a gradient, it should read from 20 feet away.
- **No script or decorative cursive fonts.** Studio Brut is graphic-design-forward, not romantic-handwritten.
- **No corporate stock photography styling.** No "team of professionals around a conference table." No "diverse customer using laptop in modern office." Studio Brut imagery is editorial or street or product-with-attitude or lifestyle-with-grit.
- **No "elevate your brand" generic copy patterns.** No "we deliver world-class solutions." No "your trusted partner." Studio Brut copy is specific, concrete, and personality-forward.
- **No symmetrical centered layouts as default.** Asymmetry is baseline; centered is exception.
- **No restrained color use when brand kit has bold colors available.** If the brand_kit gives Studio Brut saturated colors, the variants USE them at full intensity. Studio Brut doesn't desaturate for "tastefulness."
- **No italic-emphasis-word as signature pattern.** Cathedral's italic + signal-color emphasis is a fingerprint pattern. Studio Brut achieves emphasis through weight contrast, scale contrast, or color block — never through italic as signature.
- **No "professional" tone.** Studio Brut isn't unprofessional — it's *personable*. The voice is direct and human, not corporate-formal.
- **No safe centered manifesto without ornament.** Cathedral's `manifesto_center` variant pattern (centered text with corner diamonds, no image) does not transfer directly to Studio Brut. Even Studio Brut's most text-led hero must include color block architecture, off-axis ornament, or bold type-as-graphic to read as Studio Brut and not as generic centered text.

---

## 10. Relationship to Cathedral

Studio Brut and Cathedral are sister modules in the same library system. They share infrastructure but interpret it differently.

### What both modules share

- **The 8-dimension treatment system.** `color_emphasis × spacing_density × emphasis_weight × background × color_depth × ornament × typography × image_treatment`. Same dimension names, same translator pattern. Each module interprets the value sets through its own DNA — Cathedral's `typography=bold` is heavier Playfair; Studio Brut's `typography=bold` is condensed-sans at 900 weight.
- **The brand_kit color contract.** Both modules consume `--brand-authority`, `--brand-signal`, `--brand-warm-neutral`, `--brand-deep-secondary`, `--brand-text-primary`. Both rely on `derive_text_on` for contrast text colors. Brand_kit rendering is module-agnostic; the colors themselves just resolve through whichever module's variants are active.
- **The render pipeline.** `variant render → brand_kit_renderer → slot_resolver → override_resolver`. Same four-step canonical pipeline. Studio Brut variants are drop-in compatible with the existing infrastructure.
- **The Composer Agent pattern.** Sonnet 4.5 picks variant + 8-dimension treatments + content, returns validated JSON, retries on missing fields, defaults to safe values on failure. Studio Brut has its own composer (`studio_brut_hero_composer.py` — built in Phase B / C) but follows the same pattern.
- **The slot_image + override_target conventions.** Variants emit `data-slot="hero_main"` for images and `data-override-target="hero.heading"` for editable text. Both modules use the same naming conventions.

### What's module-specific

- **Aesthetic DNA** — typography choices, ornament vocabulary, color philosophy, layout proportions, image treatment, voice. Documented in each module's design doc (this document for Studio Brut; `cinematic_authority_intelligence.md` for Cathedral).
- **Default fallback palette** when brand_kit is empty — navy/gold/cream for Cathedral, red/yellow/near-black for Studio Brut.
- **Variant library** — each module has its own 10-15 variants per section. A Cathedral variant ID like `manifesto_center` does NOT exist in Studio Brut; Studio Brut's variants have their own IDs (Phase B will lock the canonical names).
- **Composer system prompt** — each module's composer prompt encodes the module's DNA, archetypal businesses, and treatment guidance. Different prompts produce different variant/treatment selections from the same business input.

### Module routing

- **A business is assigned to ONE module per build.** Cathedral and Studio Brut don't mix within a single site — a site is fully Cathedral or fully Studio Brut, not a hybrid.
- **Module Router (Phase D of Pass 4.0g)** runs as the first composition step. It takes the enriched brief + business archetype + brand_kit and outputs a module ID. Then the module-specific composer runs to pick variant + treatments. Two LLM calls instead of one (router classifier + module composer), but the router is a cheap classifier.
- **The router's decision criteria are archetypal**, not stylistic. It reads the business's *type* (custom apparel brand, financial advisor, pastoral leader, design studio) and routes to the module whose archetype list matches. It does NOT look at the brand_kit colors to decide — a custom apparel brand with navy/gold colors still routes to Studio Brut, then Studio Brut uses those colors through its DNA.

### Future modules

- Pass 4.0g delivers two modules (Cathedral + Studio Brut). Future passes will add more:
  - **Atelier** — handcrafted, artisan, refined-but-warm. For ceramicists, leather workers, specialty food producers, craft jewelers. Distinct from both Cathedral (less editorial-formal) and Studio Brut (less graphic-aggressive).
  - **Pulpit** — institutional, civic, traditional-religious, academic. For law firms with deep history, churches, universities, government-adjacent. Adjacent to Cathedral but more institutional and less editorial.
  - **Field Manual** — technical, schematic, blueprint-aesthetic. For engineering firms, technical consultancies, research labs, B2B technical SaaS. Adjacent to Cathedral's `annotated_hero` direction but as a full module.
  - **Floor** — service-led, hospitality, restaurant, retail. For restaurants, bars, retail shops, hospitality brands. Warmer than Studio Brut, more service-oriented than Cathedral.

- Each future module follows the same architectural pattern: design document → variant library → treatment translators → composer → router integration.
- **Each module has its own aesthetic DNA and shouldn't try to be flexible toward others' territory.** This is the spike's key learning. A module that tries to serve all archetypes serves none of them well.

---

## Appendix — Document version + change history

| Date | Author | Change |
|---|---|---|
| 2026-05-16 | Pass 4.0g Phase A | Initial authoring. Sections 1–10 + defaults + anti-patterns + relationship to Cathedral. |

Subsequent phases must update this document when implementation decisions deviate from or extend what's written here. The document is the design brain; the variants are its handwriting. They evolve together.
