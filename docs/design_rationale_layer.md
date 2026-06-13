# Design Rationale Layer (DRL) — Specification v1

**Status:** APPROVED FOR BUILD — Kevin ruled 2026-06-13. Implementation arc (§9) is live; PR1 first.
**Author:** Claude Code (lead architect role), 2026-06-10. Rulings + reconciliation added 2026-06-13.
**Repo home:** `kmj-intake-server` (the composer pipeline lives here; frontend consumes via existing routers).

---

## 0. Rulings — locked 2026-06-13 (read with §7/§8)

Folded in after a full Builder design-quality audit (the "Royal Palace" bespoke-bar brief). These supersede the v1 assumptions where they differ:

1. **Canonical engine = the Module Composer.** The DRO is consumed by the **Composer**, not the Director. The Director `build-with-loop` (60–240s, 4–7 Claude calls → client timeouts) and the legacy `generateSite()` (LLM hand-writes full HTML → timeouts) are **retired as live builders**; the Director's critique loop is *harvested* into the composer. The composer runs as the Feature-2 `rebuild_site` background job, so a richer (slower) compose can never time out. ⇒ §7's "Director loop consumes DRO" path is **superseded**: DRO → Composer only.
2. **Fabrication policy lives on the CONTENT sibling, not the DRO.** The DRO is design-direction only. Believable specifics (hours, "EST.", tier names, sample testimonials) are handled in the enriched-brief/composer copy layer with: **confirm-then-publish placeholders** (generated on-theme, clearly marked editable, owner must confirm before public) **and, when unconfirmed, design around real data** (tasteful non-numeric framing — never silently publish invented facts). Preserves the "no mocked numbers ever render" principle.
3. **Fork F1 = RULED:** new `design_rationales` table (auditable history + feedback joins). See §8 F1.
4. **Fork F4 = RULED:** distinctiveness check = platform-wide last-10, per-business double weight. See §8 F4.
5. **Sequence:** DRL core (PR1–PR3) is the **first build** — highest leverage (lever 1+2+5 at once; most inputs already inferred-then-discarded today). Composer library depth (cinematic hero, icon+price cards, stat-split, palette scarcity/alternation, rendered image treatments + themed icons), verticalization packs, and contact-form wiring (today contact is `mailto:` only) follow.

---

## 0. Implementation Reality Check (read first)

Per the stop condition, the existing pipeline was audited before writing this spec. **It is substantially real** — this spec builds on what ships today, not on memory:

| Component | Reality |
|---|---|
| Composer Agent | `agents/composer/hero_composer.py::compose_hero` — real. Module dispatch via `ModuleSpec` registry (`cathedral`, `studio_brut`), per-module system prompts, Pydantic composition types, one Sonnet call + validation + retry discipline, structured soft-fallback. |
| Hero Creative Expression Layer | `agents/composer/creative_expression.py` (Pass 4.0i Phase C) — real. Per-field font/accent/intensity inference with **sticky-with-source** persistence (`practitioner` pins beat `inferred`) into `businesses.settings.brand_kit.creative_expression`. |
| Module Router | `agents/composer/module_router.py::route_module` — real archetype dispatch. |
| Director Agent | `agents/director_agent/build_with_loop.py::run_build_loop` — real: enrichment (sparse intake → `enriched_brief`) → designer → build → critique (`llm_judge` + `deterministic_checker`) → refine. |
| Brand kits | `brand_engine.py` — real; `businesses.settings.brand_kit` (nested + flat), history capped at 2, onboarding tones → `brand_voice` mapping. |
| Intake tone signals | `businesses.voice_profile` (onboarding transcript + tones) — real, and **confirmed used only for copy** (emails, invoices, Chief voice) except the thin `_tones_to_brand_voice` mapping. The premise of the four gaps holds. |

**Three reality nuances that shape this spec (flagged, not blockers):**

1. **An intermediate artifact already exists — but it's the wrong kind.** `enriched_brief` sits between intake and generation today. It is *content*-focused (archetype, slots, mood phrases for image clients). The DRL's Design Rationale object is its **design-reasoning sibling**, not a replacement. The two travel together (see §7).
2. **The Composer is hero-scoped; pages go through the Director loop.** The Rationale object must be consumed at BOTH altitudes: the Director/Designer (page-level layout, density, motion) and the hero Composer (variant, treatments, creative_expression). §7 maps each field to its consumer.
3. **A `reasoning` free-text field already exists per composition.** The DRL doesn't invent "why" — it **structures and front-loads** it: today reasoning is narrated *after* choices; under DRL the rationale is authored *first* and generation is constrained to honor it. The existing field becomes the per-section echo of the upstream rationale.

**Surfaced for ruling (recommended calls made; see §8):** storage location for rationale objects (recommend: new table, not settings blob), and consolidation with `vertical_intelligence.py` (recommend: DRL *consumes* it as a prior, doesn't duplicate it).

---

## 1. Signal Taxonomy

Signals are what Chief *detects* during conversational intake. They are *descriptive* (what is true about this practitioner and audience), never *prescriptive* (they don't name fonts or hex codes). Every signal record stores the **conversational evidence verbatim** — that's the trust-layer answer to "why did Chief think this?"

Detection contract: each detected signal is stored as `{ signal_id, value, confidence (0–1), evidence: [verbatim quotes], source: "intake" | "inferred" | "practitioner_set" }`. Signals below `confidence 0.5` are recorded but **not consumed** by translation (they show as "heard but not acted on" in the audit view).

### S1. Opening Posture
- **Definition:** How the practitioner instinctively opens the conversation about their work — what they lead with reveals what the site should lead with.
- **Evidence examples:** *"Most of my clients come to me drowning in spreadsheets"* (problem-first) · *"I've been a licensed attorney for 22 years"* (credential-first) · *"I started this after my own burnout in corporate"* (story-first) · *"Imagine waking up and your business ran itself yesterday"* (vision-first).
- **Values:** `problem_first` · `credential_first` · `story_first` · `vision_first` · `craft_first` (leads with the work itself — portfolios, before/afters).
- **Design implication (directional):** Drives hero hierarchy — what the first headline *is about* — and whether proof elements (credentials, logos, numbers) sit above or below the fold.

### S2. Communication Temperature
- **Definition:** Where the practitioner sits on direct ↔ relational. Not friendliness — *information delivery style*.
- **Evidence:** *"I tell people exactly what's broken, that's why they hire me"* (direct) · *"I never give the answer first — we find it together"* (relational) · analogy density in the transcript is itself evidence (high analogy use → relational-translator).
- **Values:** spectrum `direct (0.0) ↔ relational (1.0)`, plus modifier flags: `analogical` (translates via pictures), `data_led` (translates via numbers).
- **Design implication:** Direct → tighter copy blocks, higher contrast, fewer decorative moves. Relational → warmer palette temperature, more generous line-height, transitional elements between sections. `analogical` → strong candidate for a visual-metaphor hero instead of photography.

### S3. Audience Sophistication
- **Definition:** How fluent the *audience* is in the practitioner's domain — the site speaks to them, not to peers.
- **Evidence:** *"My clients don't know what a P&L is and that's fine"* (novice) · *"I work with CFOs who've seen every deck"* (expert) · *"Some get it, some need hand-holding"* (mixed).
- **Values:** `novice` · `practicing` · `expert` · `mixed`.
- **Design implication:** Novice → progressive disclosure, fewer simultaneous choices, explanatory micro-copy welcome. Expert → density is RESPECT (sparse hand-holding reads as condescension), restrained ornamentation, proof over promise.

### S4. Audience Emotional State
- **Definition:** The dominant feeling the visitor arrives with. The first screen either meets it or fights it.
- **Evidence:** *"They come to me overwhelmed, honestly ashamed of their books"* (overwhelmed + shame) · *"They're hungry — they want the next level"* (ambitious) · *"They've been burned by two agencies already"* (skeptical) · *"They're grieving and have to settle an estate"* (vulnerable).
- **Values (multi-select, max 2 primary):** `overwhelmed` · `ambitious` · `skeptical` · `vulnerable` · `curious` · `urgent` · `proud`.
- **Design implication:** Overwhelmed → radical reduction (ONE message, one CTA, whitespace as oxygen). Skeptical → proof-forward layout, restrained claims, no hype motion. Ambitious → momentum cues (diagonals, motion, forward-leaning type). Vulnerable → soft contrast, warm temperature, zero aggression.

### S5. Authority Style
- **Definition:** The relationship geometry the practitioner builds: above (expert prescribes), alongside (guide co-pilots), behind (enabler who makes the client the hero).
- **Evidence:** *"They drive, the system comes alongside"* (alongside — KMJ verbatim) · *"People pay me to tell them what to do"* (above) · *"My job is to make THEM look brilliant in the boardroom"* (behind).
- **Values:** `expert_above` · `guide_alongside` · `enabler_behind`.
- **Design implication:** Above → symmetric composition, centered hero, formal type contrast. Alongside → asymmetric layouts (two presences sharing space), conversational subheads, visual metaphors of accompaniment. Behind → audience imagery/outcomes dominate; the practitioner is visually subordinate.

### S6. Desired First-Five-Seconds Feeling
- **Definition:** What the practitioner wants a stranger to *feel* before reading anything. Captured as close to verbatim as possible.
- **Evidence:** *"Wow, this is actually legit"* (KMJ verbatim) · *"Instantly calmer"* · *"Like they found the serious one"* · *"Energy — like a locker room before the game."*
- **Values:** free text + normalized tags: `legit/intentional` · `calm/safe` · `serious/gravitas` · `energizing` · `warm/welcomed` · `exclusive/premium` · `playful`.
- **Design implication:** This is the **acceptance test** for the whole rationale — every choice must be defensible as serving this feeling. It is the first field shown in the practitioner-facing "why" view.

### S7. Vertical Conventions — Honor vs. Break
- **Definition:** The visual conventions of the practitioner's industry, and the practitioner's stance toward them. Conventions exist because they carry trust; breaking them is a *move*, not a default.
- **Evidence:** *"Every lawyer site is navy and serif and I actually like that"* (honor) · *"I refuse to look like every other coach with a beach photo"* (break) · silence on the topic (no stance → honor structure, vary surface).
- **Values:** `honor` · `break_deliberately` · `no_stance` + the named conventions in play (sourced from `vertical_intelligence.py` — see §8 consolidation call).
- **Design implication:** Honor → keep the structural trust cues (e.g., attorney: restrained palette, serif gravitas) and differentiate via craft. Break → invert ONE convention loudly, keep the rest (breaking everything reads as amateur, not bold).

### S8. Brand Maturity
- **Definition:** How much identity already exists and how attached the practitioner is to it.
- **Evidence:** *"Our green is non-negotiable, it's on the trucks"* (established-attached) · *"I have a logo my cousin made, I hate it"* (existing-disposable) · *"Blank page, that's why I'm here"* (blank slate).
- **Values:** `established_attached` · `established_flexible` · `existing_disposable` · `blank_slate`.
- **Design implication:** Attached → rationale works WITHIN given assets (palette derives from them; this constrains S-driven choices and the rationale must say so). Blank slate → full freedom, but also full responsibility for distinctiveness (anti-convergence weighs heavier).

### S9. Offering Texture *(added — matters and wasn't listed)*
- **Definition:** The sensory/temporal character of what's actually sold: one big transformation vs. ongoing rhythm vs. discrete deliverables.
- **Evidence:** *"It's a 12-week intensive, life looks different at the end"* (transformation arc) · *"I'm their bookkeeper forever, boring is good"* (steady rhythm) · *"They get the brand kit, the site, the assets"* (artifacts).
- **Values:** `transformation_arc` · `steady_rhythm` · `discrete_artifacts` · `moment_of_need` (e.g., estate settlement, emergency repair).
- **Design implication:** Transformation → before/after narrative layout, progress metaphors. Rhythm → stability cues (grids, repetition, calm motion). Artifacts → show the work (gallery density). Moment-of-need → zero friction to contact; everything else is secondary.

### S10. Practitioner Energy Signature *(added)*
- **Definition:** The pace and intensity of the practitioner's own speech — detectable from the transcript itself (sentence length, exclamation density, hedging frequency). The site should feel like *meeting them*.
- **Evidence:** Short declaratives + zero hedging → high-conviction. Long winding sentences with qualifiers → deliberate/considered. Frequent jokes → levity is brand-true.
- **Values:** `high_conviction` · `deliberate` · `warm_steady` · `playful_quick`.
- **Design implication:** Motion temperature and type personality should rhyme with it — a deliberate speaker with expressive bouncing animations is a lie the visitor feels.

---

## 2. Design Rationale Object (DRO) — Schema

The artifact Chief authors **before** any HTML exists. Stored per generation, auditable forever, renderable to the practitioner in plain language. Every design field carries a one-line `because` tracing to signal ids — that is the trust-layer contract: "why did Chief choose this?" is answered by reading the object, not by re-asking the model.

```json
{
  "$schema": "https://mysolutionist.app/schemas/design-rationale-v1.json",
  "type": "object",
  "required": ["dro_version", "business_id", "signals", "decisions",
               "anti_convergence", "summary_for_practitioner"],
  "properties": {
    "dro_version": { "const": 1 },
    "id": { "type": "string", "description": "uuid" },
    "business_id": { "type": "string" },
    "created_at": { "type": "string", "format": "date-time" },
    "intake_source": {
      "type": "object",
      "description": "Traceability to the conversation that produced the signals.",
      "properties": {
        "transcript_ref": { "type": "string" },
        "enriched_brief_hash": { "type": "string",
          "description": "post_processor.hash_brief of the sibling content brief" }
      }
    },

    "signals": {
      "type": "array",
      "description": "Detected intake signals (taxonomy §1). The evidence quotes ARE the audit trail.",
      "items": {
        "type": "object",
        "required": ["signal_id", "value", "confidence", "evidence"],
        "properties": {
          "signal_id": { "enum": ["opening_posture", "communication_temperature",
            "audience_sophistication", "audience_emotional_state", "authority_style",
            "first_five_seconds", "vertical_conventions", "brand_maturity",
            "offering_texture", "energy_signature"] },
          "value": {},
          "confidence": { "type": "number", "minimum": 0, "maximum": 1 },
          "evidence": { "type": "array", "items": { "type": "string" },
            "description": "verbatim practitioner quotes" },
          "source": { "enum": ["intake", "inferred", "practitioner_set"] }
        }
      }
    },

    "decisions": {
      "type": "object",
      "description": "Every member requires `because` (one line) + `from_signals` (ids). Directional vocabulary — never hex codes or font files here; resolution to concrete assets happens downstream in brand_kit/creative_expression.",
      "required": ["palette", "typography", "layout", "motion", "hero_concept",
                   "whitespace", "voice_to_visual"],
      "properties": {
        "palette": {
          "type": "object",
          "required": ["base", "accent_strategy", "temperature", "because", "from_signals"],
          "properties": {
            "base": { "enum": ["deep_dark", "soft_dark", "warm_light", "cool_light", "paper_neutral"] },
            "accent_strategy": { "enum": ["single_semantic", "dual_complement", "tonal_monochrome", "vivid_block"],
              "description": "single_semantic = one accent reserved for meaning-bearing words/CTAs" },
            "temperature": { "enum": ["warm", "cool", "neutral_warm", "neutral_cool"] },
            "inherits_brand_assets": { "type": "boolean" },
            "because": { "type": "string", "maxLength": 240 },
            "from_signals": { "type": "array", "items": { "type": "string" } }
          }
        },
        "typography": {
          "type": "object",
          "required": ["display_personality", "body_personality", "pairing_logic", "because", "from_signals"],
          "properties": {
            "display_personality": { "enum": ["editorial_serif", "grotesque_bold", "humanist_warm",
              "geometric_precise", "expressive_display", "condensed_impact"] },
            "body_personality": { "enum": ["warm_sans", "neutral_sans", "readable_serif", "mono_technical"] },
            "pairing_logic": { "type": "string",
              "description": "WHY these two personalities together — contrast or kinship, and where each appears" },
            "scale_contrast": { "enum": ["dramatic", "confident", "quiet"] },
            "because": { "type": "string", "maxLength": 240 },
            "from_signals": { "type": "array", "items": { "type": "string" } }
          }
        },
        "layout": {
          "type": "object",
          "required": ["symmetry", "density", "hierarchy_approach", "because", "from_signals"],
          "properties": {
            "symmetry": { "enum": ["asymmetric_tension", "centered_formal", "grid_modular", "editorial_columns"] },
            "density": { "enum": ["airy", "balanced", "dense_intentional"] },
            "hierarchy_approach": { "enum": ["single_message_dominant", "guided_descent", "parallel_panels"] },
            "because": { "type": "string", "maxLength": 240 },
            "from_signals": { "type": "array", "items": { "type": "string" } }
          }
        },
        "motion": {
          "type": "object",
          "required": ["temperature", "because", "from_signals"],
          "properties": {
            "temperature": { "enum": ["none", "subtle_entrance", "ambient_breathing", "expressive"] },
            "signature_move": { "type": "string",
              "description": "ONE named motion idea max (e.g. 'staggered rise', 'pulse at center') — motion has a thesis or it doesn't exist" },
            "because": { "type": "string", "maxLength": 240 },
            "from_signals": { "type": "array", "items": { "type": "string" } }
          }
        },
        "hero_concept": {
          "type": "object",
          "required": ["direction", "concept_statement", "because", "from_signals"],
          "properties": {
            "direction": { "enum": ["visual_metaphor", "typographic_statement", "portrait_presence",
              "artifact_showcase", "environment_mood"] },
            "concept_statement": { "type": "string", "maxLength": 400,
              "description": "The idea in one breath — e.g. 'concentric arcs converging on a pulsing dot; the practitioner's business at the center, the system alongside'" },
            "metaphor_elements": { "type": "array", "items": { "type": "string" } },
            "because": { "type": "string", "maxLength": 240 },
            "from_signals": { "type": "array", "items": { "type": "string" } }
          }
        },
        "whitespace": {
          "type": "object",
          "required": ["philosophy", "because", "from_signals"],
          "properties": {
            "philosophy": { "enum": ["confidence_air", "warm_close", "editorial_rhythm", "dense_energy"] },
            "because": { "type": "string", "maxLength": 240 },
            "from_signals": { "type": "array", "items": { "type": "string" } }
          }
        },
        "voice_to_visual": {
          "type": "object",
          "required": ["notes", "because", "from_signals"],
          "properties": {
            "notes": { "type": "array", "items": { "type": "string" },
              "description": "Specific copy↔design couplings: e.g. 'accent color appears ONLY on transformation words', 'subhead uses alongside-language; layout echoes with two co-present elements'" },
            "because": { "type": "string", "maxLength": 240 },
            "from_signals": { "type": "array", "items": { "type": "string" } }
          }
        }
      }
    },

    "anti_convergence": {
      "type": "object",
      "description": "Proof the distinctiveness check ran (§5).",
      "required": ["distinctiveness_check"],
      "properties": {
        "distinctiveness_check": {
          "type": "object",
          "properties": {
            "compared_against": { "type": "array", "items": { "type": "string" },
              "description": "DRO ids of recent generations compared against" },
            "axes_shared_with_nearest": { "type": "integer" },
            "verdict": { "enum": ["distinct", "regenerated_once", "flagged"] },
            "notes": { "type": "string" }
          }
        },
        "banned_defaults_avoided": { "type": "array", "items": { "type": "string" } }
      }
    },

    "summary_for_practitioner": {
      "type": "string", "maxLength": 1200,
      "description": "Plain-language 'here's why your site looks this way' — generated WITH the DRO, not on demand, so the audit answer is frozen at decision time."
    },

    "exemplars_consulted": {
      "type": "array",
      "items": { "type": "object", "properties": {
        "exemplar_id": { "type": "string" },
        "borrowed": { "type": "string", "description": "which MOVE was borrowed (never the surface)" } } }
    }
  }
}
```

**Trust-layer answer for this component:** "Why did Chief choose X?" → read `decisions.X.because` + follow `from_signals` to verbatim quotes. The practitioner-facing view renders `summary_for_practitioner` with expandable per-decision lines. Nothing is reconstructed after the fact.

---

## 3. Translation Principles (the reasoning engine)

These are designer *moves*, written for an LLM to apply to novel signal combinations. Format: **principle → applies when → pushes toward → pushes away from → example.** They are weighted guidance, not gates; when two principles collide, the DRO's `because` must name the collision and the winner (that's reasoning, not lookup).

1. **Meet the emotion, then move it.** *Applies:* always; keyed by S4. *Toward:* first screen matches the visitor's arriving state (overwhelmed → calm; skeptical → proof). *Away from:* opening with the practitioner's energy instead of the audience's. *Example:* overwhelmed bookkeeping clients get ONE sentence and air — the energy can come two scrolls later.
2. **Whitespace is a confidence claim.** *Applies:* S6 includes legit/premium/serious. *Toward:* generous negative space, restrained element count. *Away from:* filling space to prove effort ("we're not desperate, we're confident" — KMJ). *Example:* a premium consultant's hero holds 9 elements max, counted.
3. **One accent, carrying meaning.** *Applies:* `single_semantic` accent strategy; default for overwhelmed/skeptical audiences. *Toward:* accent color appears only where meaning lives (transformation words, the one CTA). *Away from:* decorative accent scatter. *Example:* ember orange on exactly "solutions" and the button — the eye learns the color = the point.
4. **Dark is a stage, light is a room.** *Applies:* palette base choice. *Toward:* dark bases when the content performs (gravitas, premium, focus); light bases when the visitor should feel *inside* something (welcome, clarity, daylight honesty). *Away from:* dark-as-default-cool. *Example:* estate attorney = warm paper room, not nightclub.
5. **Type contrast mirrors authority geometry.** *Applies:* S5. *Toward:* expert_above → high formal contrast (display serif vs. quiet body); guide_alongside → kindred pairing (warm display + warm body — same family of feeling, different volume). *Away from:* pairing by trendiness. *Example:* co-pilot brands pair Fraunces-class warmth with Manrope-class warmth — contrast in size, kinship in temperature.
6. **Asymmetry implies motion; symmetry implies verdict.** *Applies:* layout symmetry. *Toward:* asymmetric tension for transformation arcs and alongside-energy; centered formality for verdict-givers and moment-of-need. *Away from:* asymmetry on trust-critical verticals where it reads as instability. *Example:* probate page = centered; growth-coach page = diagonal.
7. **Density is literacy-priced.** *Applies:* S3. *Toward:* expert audiences get dense_intentional (information as respect); novices get guided_descent with progressive disclosure. *Away from:* one density default. *Example:* CFO-facing site shows the table on screen one; bookkeeping-novice site shows one number.
8. **Motion needs a thesis or silence.** *Applies:* motion temperature. *Toward:* one named signature move that restates the brand idea (staggered rise = intentionality; pulse = aliveness at the center). *Away from:* parallax-everything; motion as garnish. *Example:* KMJ's staggered rise IS "step-by-step literacy" rendered in time.
9. **Honor the convention's job, not its costume.** *Applies:* S7 = honor or no_stance. *Toward:* keep what the convention does (navy/serif = stability signal) while differentiating in craft (spacing, pairing, metaphor). *Away from:* template-matching the vertical's median site. *Example:* attorney keeps serif gravitas but in Freight-class warmth on paper-cream, not Times-on-white.
10. **Break exactly one convention, loudly.** *Applies:* S7 = break_deliberately. *Toward:* a single inverted expectation (palette OR type OR imagery), with the rest conventionally trustworthy. *Away from:* breaking everything (reads amateur, not bold). *Example:* youth coach in a sea of red-energy sites goes electric-lime — but on disciplined grids.
11. **Metaphor beats photography when the offer is invisible.** *Applies:* S2 `analogical` + intangible services (systems, strategy, finance). *Toward:* constructed visual metaphors (arcs, nodes, paths) over stock humans. *Away from:* laptop-and-latte stock. *Example:* People/Tech/Finance as three orbiting nodes around the client's pulsing center.
12. **The practitioner's pace sets the page's pace.** *Applies:* S10. *Toward:* deliberate speakers get slower reveals, longer line-lengths; quick-playful speakers get tighter rhythms, snappier transitions. *Away from:* energy mismatch between transcript and motion. *Example:* a measured estate attorney's site never bounces.
13. **Make the visitor the subject when authority is 'behind'.** *Applies:* S5 = enabler_behind. *Toward:* audience-outcome imagery dominant, practitioner visually subordinate, "you" voice mirrored by second-person visual focus. *Away from:* founder-portrait heroes. *Example:* the client on the stage; the practitioner in the program notes.
14. **Shame-adjacent audiences get zero-judgment surfaces.** *Applies:* S4 includes overwhelmed+shame or vulnerable. *Toward:* warm temperature, soft contrast edges, no red, no countdown urgency, copy-visual pairing that says "normal, fixable". *Away from:* alarm aesthetics and gamified pressure. *Example:* books-in-shoeboxes clients see calm sage and cream, never warning-red KPIs.
15. **Proof placement follows skepticism.** *Applies:* S4 includes skeptical, or S1 = credential_first. *Toward:* verifiable artifacts (numbers, names, logos) inside the first viewport; claims restrained. *Away from:* superlative headlines before evidence. *Example:* "217 estates settled" above the fold beats "The BEST probate firm".
16. **Inherited assets are constraints to honor visibly.** *Applies:* S8 = established_attached. *Toward:* derive the palette FROM the asset (truck-green becomes the tonal anchor), and say so in the rationale. *Away from:* fighting the asset or quarantining it to the logo corner. *Example:* the non-negotiable green drives a tonal-monochrome strategy instead of clashing accents.
17. **First-five-seconds feeling is the tiebreaker.** *Applies:* any principle collision. *Toward:* whichever option better serves S6, with the collision named in `because`. *Away from:* resolving ties by aesthetic preference. *Example:* "dense-as-respect (P7) vs. calm-for-overwhelmed (P1): audience is mixed, S6 says 'instantly calmer' → P1 wins; density moves to /services."

---

## 4. Annotated Exemplar Library (starter set of 4)

Exemplars teach the *translation move*, never the surface. The library is consulted by similarity of **signals**, not of vertical — a skeptical-audience lawyer can borrow from a skeptical-audience consultant. Each exemplar = context → signals → DRO summary → resulting direction. Stored as structured records (same shape as live DROs + a `narrative` field) so generation prompts can include 1–2 *contrasting* exemplars (§5 forces contrast).

### E1 — KMJ Creative Solutions *(captured, real — the seed)*
- **Context:** People-developer solving business problems through strategy, systems, financial intelligence. Serves coaches, consultants, pastors, service providers — overwhelmed, inconsistent, needing capability AND reassurance.
- **Signals:** opening_posture=`problem_first` (.9, "if I solve their problem, that reveals who I am") · communication_temperature=.75 relational + `analogical` · audience_sophistication=`novice→practicing` · audience_emotional_state=`overwhelmed` (+wants ownership) · authority_style=`guide_alongside` (.95, "they drive, the system comes alongside") · first_five_seconds=`legit/intentional` ("wow, this is actually legit") · vertical_conventions=`break_deliberately` (anti-generic explicit) · brand_maturity=`existing_flexible` · offering_texture=`steady_rhythm`+`transformation_arc` · energy_signature=`warm_steady`.
- **DRO (summary):** palette `deep_dark`/`single_semantic`/`warm` — *because* premium-legit (S6) + warm-human for overwhelmed (S4); ember accent only on transformation words (P3). Typography `editorial_serif` display + `warm_sans` body, kindred-warmth pairing (P5, alongside-authority). Layout `asymmetric_tension`/`airy`/`single_message_dominant` — *because* P1+P2: one message, air as confidence. Motion `subtle_entrance`, signature "staggered rise" — *because* P8: step-by-step literacy in time. Hero `visual_metaphor`: concentric arcs converging on pulsing dot + three nodes (People/Tech/Finance) — *because* P11: invisible offer + analogical speaker; co-pilot energy visualized. Whitespace `confidence_air`. Voice-to-visual: outcome-first headline; alongside-language subhead echoed by co-present visual elements.
- **Resulting direction:** Dark editorial stage, one ember of meaning, a living diagram instead of stock photography; feels like a firm that *built something*, warm enough to hand you the keys.

### E2 — Hartwell & Vance, Estate Law *(constructed; maximal contrast: light, formal, still, paper-warm)*
- **Context:** Third-generation estate/probate attorney, 25 years. Clients arrive after a death — grieving, executors by surprise, afraid of mistakes. She is precise, unhurried, quietly kind. Wants families to feel "you're in careful hands; nothing will be dropped."
- **Signals:** opening_posture=`credential_first` (.85, "twenty-five years, twelve hundred estates — that's what calms people") · communication_temperature=.35 direct-leaning, zero analogies, `deliberate` cadence · audience_sophistication=`novice` (one-time need) · audience_emotional_state=`vulnerable`+`urgent` · authority_style=`expert_above` (gently — "people need someone to just handle it") · first_five_seconds=`calm/safe`+`serious/gravitas` · vertical_conventions=`honor` ("lawyers should look like lawyers; I just don't want to look dated") · brand_maturity=`established_flexible` (firm name carries weight, visuals dated) · offering_texture=`moment_of_need` · energy_signature=`deliberate`.
- **DRO (summary):** palette `paper_neutral`/`tonal_monochrome`/`neutral_warm` — warm cream + deep walnut ink, *because* P4 (a room, not a stage — grieving people need daylight honesty) + P14 (zero-judgment surface; no red anywhere). Typography `editorial_serif` display + `readable_serif` body, high formal contrast — *because* P5 (expert_above) + P9 (serif = the convention's trust job, executed in warm Freight-class, not dated Times). Layout `centered_formal`/`balanced`/`guided_descent` — *because* P6 (symmetry = verdict, steadiness for the vulnerable) + P15 (proof in first viewport: years, estates, county courts). Motion `none` — *because* P8+P12: a deliberate counselor does not animate; stillness IS the signature move. Hero `typographic_statement`: "Your family's affairs, handled with care." — *because* metaphors would feel evasive here; the promise is the picture. Whitespace `editorial_rhythm`. Voice-to-visual: numbers set in the display serif (credentials as typography); "handled" is the only emphasized word.
- **Resulting direction:** Warm paper, walnut ink, engraved-letterhead gravity, totally still. The visual opposite of E1 on five axes (light/dark, centered/asymmetric, serif-body/sans-body, none/subtle motion, statement/metaphor) — and *derived from signals*, not from "lawyer template".

### E3 — Coach Dre, Youth Athletic Performance *(constructed; maximal contrast: loud, kinetic, dense, vivid)*
- **Context:** Former D1 sprinter training 13–18-year-olds; sells to two audiences at once — parents (trust) and athletes (belonging). Gym-floor energy, short sentences, calls everyone "fam". Wants kids to feel "this is THE program" and parents to feel structure.
- **Signals:** opening_posture=`vision_first` (.8, "I see the athlete they haven't met yet") · communication_temperature=.8 relational, `playful_quick` · audience_sophistication=`mixed` (athletes novice-emotional, parents evaluating) · audience_emotional_state=`ambitious`+`proud` · authority_style=`guide_alongside` (locker-room older-brother) · first_five_seconds=`energizing` ("locker room before the game") · vertical_conventions=`break_deliberately` ("every gym is red-and-black aggression; we're not angry, we're ALIVE") · brand_maturity=`blank_slate` · offering_texture=`transformation_arc` (seasons, PRs) · energy_signature=`playful_quick`.
- **DRO (summary):** palette `deep_dark`/`vivid_block`/`cool` — charcoal court + **electric lime** blocks, *because* P10 (break ONE convention loudly: the red-aggression default → alive-green) on P4's stage-dark (performance under lights). Typography `condensed_impact` display + `neutral_sans` body, dramatic scale — *because* S10+S6: jersey-number energy; body stays neutral so parents can actually read the schedule. Layout `grid_modular`/`dense_intentional`/`parallel_panels` — *because* P7 inverted deliberately: density here IS the energy (stats, clips, season boards), and the parallel panels serve the dual audience (athlete track / parent track). Motion `expressive`, signature "stat-counter sprint" (numbers race up on entry) — *because* P8: the thesis is measurable progress. Hero `environment_mood`: real training footage tone, low-angle, lime light-streaks — *because* P13 partially: the ATHLETES are the subject; Dre appears mid-coaching, never posed. Whitespace `dense_energy`. Voice-to-visual: PR numbers get the lime; "fam" voice echoed by team-grid imagery; parent strip switches to calm neutral band (P1 applied to the secondary audience).
- **Resulting direction:** A stadium scoreboard crossed with a mixtape — vivid, kinetic, statistically proud — with one calm lane for parents. Opposite of E2 on every axis and of E1 on accent strategy, density, motion, and type personality.

### E4 — Stillpoint, Somatic Wellness *(constructed; maximal contrast: pale, organic, slow, anti-grid)*
- **Context:** Breathwork + somatic therapy practitioner for high-achievers in burnout. Speaks slowly, almost whispered; skeptical OF marketing ("if my site shouts, I've already lied"). Clients are skeptical of woo — engineers, surgeons, founders — bodies in fight-or-flight.
- **Signals:** opening_posture=`story_first` (.7, her own burnout) · communication_temperature=.9 relational, low-analogy, sensory language · audience_sophistication=`expert` (in THEIR domains — analytical skeptics) · audience_emotional_state=`overwhelmed`+`skeptical` (the hard pair) · authority_style=`enabler_behind` ("your nervous system does the work; I hold the room") · first_five_seconds=`calm/safe` — *physiologically* ("their shoulders should drop one centimeter") · vertical_conventions=`break_deliberately` (anti-lotus, anti-purple-gradient: "wellness clichés trigger my skeptics") · brand_maturity=`blank_slate` · offering_texture=`steady_rhythm` · energy_signature=`deliberate` (whisper-paced).
- **DRO (summary):** palette `warm_light`/`tonal_monochrome`/`warm` — bone, fog, river-stone, *because* P1 (meet overwhelm with quiet) + P10 (the broken convention is the wellness-purple cliché; the loud move here is radical quietness) + P14. Typography `humanist_warm` display at LOW scale contrast + `readable_serif` body — *because* P5 (enabler_behind = nothing towers) + skeptic-respect (P15: no display theatrics to distrust). Layout `editorial_columns`/`airy`/`guided_descent` with organic image masses breaking the grid edge — *because* the body is not a grid; structure stays legible for analytical minds (S3) while edges soften. Motion `ambient_breathing`, signature "4-second breathe" (hero background scales 1.00→1.02 on a breath cycle) — *because* P8: the ONE motion is literally the method; nothing else moves. Hero `environment_mood`: light through linen, no faces — *because* P13 (client is the subject, and the subject is their own body; faces would make it about someone else). Whitespace `warm_close` shading to `confidence_air` — held, not empty. Voice-to-visual: skeptic strip = plain-language physiology with citations in mono-technical (P15: proof for engineers); no superlatives anywhere.
- **Resulting direction:** A site that lowers your heart rate: bone-and-fog stillness, one breathing image, serif calm, evidence in the footnotes. Opposite of E3 entirely; differs from E2 in formality geometry (organic vs. engraved) and from E1 in light/dark + metaphor strategy.

**Variation audit across the four:** light/dark = 2/2 · temperature warm/cool/neutral spread · motion none→subtle→breathing→expressive (full spectrum) · density airy→balanced→dense · symmetry all four values used · hero direction four different values · accent strategy three different values. This is the floor the anti-convergence layer (§5) maintains as the library grows.

---

## 5. Anti-Convergence Constraints

Convergence is the failure mode of *every* generative design system. These constraints are enforced both in-prompt (Chief sees them) and in-code (the distinctiveness check is deterministic, not vibes).

**5.1 Banned defaults (hard, in-prompt + post-validation lint):**
- Fonts: no Inter, Roboto, Open Sans, Lato, Montserrat as *display* faces (body use of a neutral sans is allowed when the rationale justifies it — by personality class, since the DRO never names fonts).
- No purple-gradient-on-white SaaS aesthetic; no `#7C3AED`-class hero gradients, period.
- No centered-hero + three-feature-cards + testimonial-strip + CTA-band default skeleton unless the DRO's `because` explicitly defends each block from signals.
- No stock-photo clichés (laptop-latte, handshake, skyline) when `hero_concept.direction = visual_metaphor` is available and S2 is analogical.
- No accent color used decoratively when `accent_strategy = single_semantic`.

**5.2 Distinctiveness check (deterministic, per tenant cohort):**
On every DRO, before generation proceeds:
1. Fetch the last **N=10** DROs across the tenant cohort (all businesses on the platform, most recent first; per-business history weighs double).
2. Compute the **8-axis signature**: `(palette.base, palette.accent_strategy, palette.temperature, typography.display_personality, layout.symmetry, layout.density, motion.temperature, hero_concept.direction)`.
3. If the new DRO shares **≥6 of 8 axes** with any of the last 10 → Chief must regenerate the DRO once, told *which* axes collided and instructed to vary at least 2 of them **only where signals permit** (signal-fit always beats variety — if signals genuinely pin 7 axes, record `verdict: "flagged"` with the justification instead of forcing a worse design).
4. Persist the comparison into `anti_convergence.distinctiveness_check` (audit: "did Chief check itself?" is answerable).

**5.3 Rotation pressure (soft, in-prompt):** the generation prompt always includes the axis-signatures of the 5 most recent platform outputs labeled "recently used — justify any repetition from signals." Exemplars included in the prompt are chosen to **contrast** with the current signal profile's nearest neighbor (one similar exemplar for the move, one contrasting exemplar to stretch the space).

**5.4 Same-practitioner regeneration:** when a practitioner regenerates, the new DRO must differ on ≥3 axes from the rejected one *unless* feedback pinned specific axes ("keep the colors" → palette axes locked, variation forced elsewhere).

**Trust-layer answer:** "Why doesn't my site look like other Solutionist sites?" → the distinctiveness_check block in the DRO, with the compared ids and verdict.

---

## 6. Feedback Loop (v1 — structured logging, no ML)

**Capture points (one table, `design_feedback`):**

```
design_feedback (
  id uuid PK,
  business_id uuid,
  dro_id uuid,                -- the rationale that produced the design
  verdict text CHECK (verdict IN ('accepted_as_is','accepted_with_edits','regenerated','abandoned')),
  edited_axes text[],         -- subset of: palette, typography, layout, motion, hero_concept, whitespace, copy
  edit_detail jsonb,          -- structured diff: {"palette": {"from": "deep_dark", "to": "warm_light"}, ...}
  practitioner_note text,     -- optional verbatim ("too dark", "love the arcs")
  created_at timestamptz
)
```

- **accepted_as_is** — recorded automatically when a generated site is published with no design-axis edits.
- **accepted_with_edits** — Edit-Mode changes are already structured (creative_expression pins, brand-kit edits); map each edit to its DRO axis and log the from→to diff. A practitioner pin (sticky-with-source `practitioner`) **is itself feedback** — log it.
- **regenerated** — the regeneration request logs which axes the practitioner asked to change (free text classified into axes by Chief — one cheap classification call, evidence kept).

**How the signal flows back (v1, deterministic):**
1. **Exemplar weighting:** each exemplar carries `wins` / `losses` counters per signal-cluster. When a DRO that consulted exemplar E is `accepted_as_is` → E.wins++ for that signal-cluster; `regenerated` with edits on the axis E informed → E.losses++. Exemplar selection orders by win-rate within the matched cluster. No gradient descent — a sort.
2. **Principle annotations:** monthly (manual for v1), principles whose associated axes are repeatedly edited in the same direction get a note appended (e.g., "P4 dark-stage: practitioners in wellness verticals flipped to light 4/5 times — bias toward light when S4=overwhelmed AND vertical=wellness"). The library is versioned in git; edits are commits with reasoning.
3. **Per-practitioner memory:** the latest accepted DRO's axes become that practitioner's `prior` — future regenerations start from it unless signals changed (re-intake) or the practitioner asks to explore.

**Explicitly out of v1:** embeddings, automated principle re-writing, cross-tenant taste transfer. The schema captures enough that any of those can be added without re-instrumenting.

---

## 7. Pipeline Integration Map

```
TODAY:   intake conversation ──► enriched_brief ──► Designer/Builder loop ──► HTML
                                  (content-only)        ▲
         brand_kit + creative_expression ───────────────┘ (hero Composer path: module_router → compose_hero)

WITH DRL:
  intake conversation
      │
      ├─► enriched_brief                    (unchanged — content sibling)
      │
      ├─► [NEW] Signal Detection pass       (one structured-output call over the
      │         transcript → signals[] with evidence; runs alongside enrichment)
      │
      ├─► [NEW] DRO Authoring pass          (signals + principles + 2 exemplars +
      │         recent-output signatures → Design Rationale Object;
      │         distinctiveness check; one regeneration max)
      │
      ├─► persist DRO                       ([NEW] design_rationales table — see fork F1)
      │
      ├─► Director loop (CHANGED prompts):  enriched_brief + DRO travel together;
      │         designer consumes layout/whitespace/motion/typography decisions
      │         as BRIEF CONSTRAINTS, not suggestions; critique loop
      │         (llm_judge + deterministic_checker) gains DRO-conformance checks
      │         ("does the output honor decisions.* ?")
      │
      ├─► hero Composer (CHANGED prompt):   compose_hero receives the DRO;
      │         module_router uses hero_concept.direction + layout.symmetry as
      │         routing inputs; treatments + creative_expression resolve FROM the
      │         DRO's directional vocabulary (sticky-with-source unchanged —
      │         practitioner pins still beat the DRO; the DRO records the pin
      │         as an inherited constraint with source noted);
      │         the existing per-composition `reasoning` field becomes the
      │         section-level echo of the upstream DRO (cites dro_id + axes)
      │
      ├─► output (HTML)
      │
      └─► [NEW] feedback capture            (design_feedback table; Edit-Mode +
                regeneration hooks; exemplar win/loss counters)
```

**Net-new components:** signal-detection pass · DRO authoring pass (+ JSON schema validation, same retry discipline as compose_hero) · `design_rationales` table · `design_feedback` table · principles + exemplar library files (versioned in-repo: `agents/composer/drl/{principles.md,exemplars/*.json,signals.py,schema.json}`) · practitioner-facing "Why your site looks this way" view (frontend, reads `summary_for_practitioner` + per-decision expansion).

**Changed (not rewritten):** Director designer prompt (consumes DRO as constraints) · critique checklist (DRO conformance) · compose_hero user prompt (DRO section) · module_router inputs · Edit-Mode hooks (log feedback) · brand_engine (DRO palette/typography directions resolve into brand_kit's concrete values — resolution stays where it lives today).

**Unchanged:** module system-prompts' design-DNA, Pydantic composition types, sticky-with-source semantics, slot/image system, render pipeline, fallback discipline.

## 8. Open forks (recommended calls made — Kevin can overrule)

- **F1 — DRO storage.** *Recommended:* new `design_rationales` table (id, business_id, dro jsonb, created_at, superseded_by) — auditable history, feedback FK joins, RLS owner-read via the existing helper pattern. *Alternative:* `businesses.settings.brand_kit.design_rationale` blob — fewer moving parts but loses history and makes feedback joins ugly. Documented because multi-tenant storage was a surfaced ruling.
- **F2 — taxonomy overlap with `vertical_intelligence.py`.** *Recommended:* DRL **consumes** vertical_intelligence as the source of the S7 conventions list and voice priors — single source of truth, no duplication; DRL adds the *design* semantics on top. *Alternative:* fold DRL signals into vertical_intelligence — rejected because verticals are priors while DRL signals are per-practitioner observations; merging them would re-create the n=1→template problem at the vertical level.
- **F3 — signal detection timing.** *Recommended:* batch pass over the completed intake transcript (simple, auditable, one call). *Alternative:* live detection during conversation (richer, lets Chief ask design-relevant follow-ups) — defer to v2; the taxonomy is forward-compatible (add `source: "live"`).
- **F4 — cohort scope of the distinctiveness check.** *Recommended:* platform-wide last-10 with per-business double weight (small platform today; cross-tenant convergence is the actual reputational risk: two practitioners comparing sites). *Alternative:* per-vertical cohorts once volume grows; the check's input is a parameter, not a rewrite.
- **F5 — where the "why" view lives.** *Recommended:* MySite/Builder surface ("Why your site looks this way" panel) + Chief can answer conversationally by reading the stored DRO. *Alternative:* Chief-only — rejected; a visible artifact is the stronger trust signal.

### Trust-layer ledger (per component)
| Component | "Why did Chief choose this?" is answered by |
|---|---|
| Signal detection | `signals[].evidence` — verbatim practitioner quotes |
| Each design decision | `decisions.*.because` + `from_signals` chain |
| Exemplar influence | `exemplars_consulted[].borrowed` (the move, named) |
| Non-convergence | `anti_convergence.distinctiveness_check` (ids compared, verdict) |
| Practitioner pins | sticky-with-source meta (existing) + DRO notes the inherited constraint |
| Post-hoc edits | `design_feedback.edit_detail` from→to diffs |

---

## 9. Implementation arc sketch (for the future build session — not now)

1. **PR 1:** `agents/composer/drl/` — schema.json, signals.py (taxonomy constants), principles.md, exemplars/ (the 4 from §4); `design_rationales` + `design_feedback` migrations.
2. **PR 2:** signal-detection + DRO-authoring passes with compose_hero-style retry/fallback discipline + distinctiveness check; wire into run_build_loop ahead of the designer.
3. **PR 3:** prompt surgery — Director designer + critique + compose_hero consume the DRO; module_router inputs.
4. **PR 4:** feedback capture hooks + exemplar counters; frontend "Why your site looks this way" panel.
5. Tests throughout via the FakeSB pattern + golden-DRO fixtures for the distinctiveness check.

*End of spec.*
