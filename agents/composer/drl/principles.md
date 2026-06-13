# DRL Translation Principles (the reasoning engine)

These are designer *moves*, written for an LLM to apply to novel signal combinations — not if-then rules (rules converge). Format: **principle → applies when → toward → away from → example.** Weighted guidance, not gates: when two principles collide, the DRO's `because` must NAME the collision and the winner. This file is included verbatim in the DRO-authoring prompt (PR2) and is versioned in git; the feedback loop (§6) appends empirical notes over time.

1. **Meet the emotion, then move it.** *Applies:* always; keyed by S4. *Toward:* first screen matches the visitor's arriving state (overwhelmed → calm; skeptical → proof). *Away from:* opening with the practitioner's energy instead of the audience's. *Example:* overwhelmed bookkeeping clients get ONE sentence and air — energy can come two scrolls later.

2. **Whitespace is a confidence claim.** *Applies:* S6 includes legit/premium/serious. *Toward:* generous negative space, restrained element count. *Away from:* filling space to prove effort. *Example:* a premium consultant's hero holds 9 elements max, counted.

3. **One accent, carrying meaning.** *Applies:* `single_semantic` accent strategy; default for overwhelmed/skeptical audiences. *Toward:* accent color appears only where meaning lives (transformation words, the one CTA). *Away from:* decorative accent scatter. *Example:* ember orange on exactly "solutions" and the button — the eye learns the color = the point.

4. **Dark is a stage, light is a room.** *Applies:* palette base choice. *Toward:* dark bases when the content performs (gravitas, premium, focus); light bases when the visitor should feel *inside* something (welcome, clarity, daylight honesty). *Away from:* dark-as-default-cool. *Example:* estate attorney = warm paper room, not nightclub.

5. **Type contrast mirrors authority geometry.** *Applies:* S5. *Toward:* expert_above → high formal contrast (display serif vs. quiet body); guide_alongside → kindred pairing (warm display + warm body). *Away from:* pairing by trendiness. *Example:* co-pilot brands pair Fraunces-class warmth with Manrope-class warmth — contrast in size, kinship in temperature.

6. **Asymmetry implies motion; symmetry implies verdict.** *Applies:* layout symmetry. *Toward:* asymmetric tension for transformation arcs and alongside-energy; centered formality for verdict-givers and moment-of-need. *Away from:* asymmetry on trust-critical verticals where it reads as instability. *Example:* probate page = centered; growth-coach page = diagonal.

7. **Density is literacy-priced.** *Applies:* S3. *Toward:* expert audiences get dense_intentional (information as respect); novices get guided_descent with progressive disclosure. *Away from:* one density default. *Example:* CFO-facing site shows the table on screen one; bookkeeping-novice site shows one number.

8. **Motion needs a thesis or silence.** *Applies:* motion temperature. *Toward:* one named signature move that restates the brand idea (staggered rise = intentionality; pulse = aliveness). *Away from:* parallax-everything; motion as garnish. *Example:* KMJ's staggered rise IS "step-by-step literacy" rendered in time.

9. **Honor the convention's job, not its costume.** *Applies:* S7 = honor or no_stance. *Toward:* keep what the convention does (navy/serif = stability signal) while differentiating in craft. *Away from:* template-matching the vertical's median site. *Example:* attorney keeps serif gravitas but in Freight-class warmth on paper-cream, not Times-on-white.

10. **Break exactly one convention, loudly.** *Applies:* S7 = break_deliberately. *Toward:* a single inverted expectation (palette OR type OR imagery), the rest conventionally trustworthy. *Away from:* breaking everything (reads amateur). *Example:* youth coach in a sea of red-energy sites goes electric-lime — but on disciplined grids.

11. **Metaphor beats photography when the offer is invisible.** *Applies:* S2 `analogical` + intangible services. *Toward:* constructed visual metaphors (arcs, nodes, paths) over stock humans. *Away from:* laptop-and-latte stock. *Example:* People/Tech/Finance as three orbiting nodes around the client's pulsing center.

12. **The practitioner's pace sets the page's pace.** *Applies:* S10. *Toward:* deliberate speakers get slower reveals, longer line-lengths; quick-playful speakers get tighter rhythms. *Away from:* energy mismatch between transcript and motion. *Example:* a measured estate attorney's site never bounces.

13. **Make the visitor the subject when authority is 'behind'.** *Applies:* S5 = enabler_behind. *Toward:* audience-outcome imagery dominant, practitioner subordinate, second-person visual focus. *Away from:* founder-portrait heroes. *Example:* the client on the stage; the practitioner in the program notes.

14. **Shame-adjacent audiences get zero-judgment surfaces.** *Applies:* S4 includes overwhelmed+shame or vulnerable. *Toward:* warm temperature, soft contrast edges, no red, no countdown urgency. *Away from:* alarm aesthetics, gamified pressure. *Example:* books-in-shoeboxes clients see calm sage and cream, never warning-red KPIs.

15. **Proof placement follows skepticism.** *Applies:* S4 includes skeptical, or S1 = credential_first. *Toward:* verifiable artifacts (numbers, names, logos) inside the first viewport; claims restrained. *Away from:* superlative headlines before evidence. *Example:* "217 estates settled" above the fold beats "The BEST probate firm".

16. **Inherited assets are constraints to honor visibly.** *Applies:* S8 = established_attached. *Toward:* derive the palette FROM the asset (truck-green becomes the tonal anchor), and say so. *Away from:* fighting the asset or quarantining it to the logo corner. *Example:* the non-negotiable green drives a tonal-monochrome strategy.

17. **First-five-seconds feeling is the tiebreaker.** *Applies:* any principle collision. *Toward:* whichever option better serves S6, with the collision named in `because`. *Away from:* resolving ties by aesthetic preference. *Example:* "dense-as-respect (P7) vs. calm-for-overwhelmed (P1): audience is mixed, S6 says 'instantly calmer' → P1 wins; density moves to /services."

---

## Content-layer policy (ruled 2026-06-13) — believable specifics

The DRO is design-direction only and never writes content. Believable specifics (hours, "EST.", tier names, sample testimonials) are handled in the **content sibling** (enriched brief / composer copy) with:

- **Confirm-then-publish placeholders** — generate on-theme specifics, render them **clearly marked as editable placeholders**, and require the owner to confirm before the site is public.
- **Design around real data when unconfirmed** — tasteful non-numeric framing; **never silently publish an invented fact.** Preserves the "no mocked numbers ever render" principle.
