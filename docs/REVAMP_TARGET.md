# THE REVAMP TARGET — the site generator, stripped and rebuilt

*Drafted 2026-07-24 for Kevin's sign-off. This is the goal-state document:
what the generator becomes, what dies, in what order, and what may never
break while we operate. Nothing in this doc is code; nothing gets stripped
until Kevin signs off on this page.*

*Amended same-day (signed): repair economics + annotator, promotion gate
with vertical spread, front-matter validation at approval, token-bleed
check on all paths, mobile verification, drain-and-queue footnote,
reference-study loud degradation, model-portable builder prompt.*

---

## 1. The lesson that drives the whole revamp

Every bug found in the 7/23–7/24 sprint was a **seam bug** — a failure at
the boundary between two layers, where neither layer could see the other:

| Bug | The seam it lived in |
|---|---|
| Prefill 400 silently killed the brain on every build | DRO ↔ model API |
| Approved spec never reached any author | spec ↔ canvas gate (required a DRO) |
| Spec's hexes got every chunk executed by the validator | spec ↔ canvas contract |
| Old accent/Anton/underline resurfaced on every fallback | tokens ↔ brand DNA |
| Canvas silently fell back to templates with no forensics | canvas ↔ module path |
| The Director invented amber while gold/green sat in the logo | author ↔ artifacts it never saw |

The current backend is a year of layers, each added to compensate for the
layer below being blind. The fix is not another layer. It is **fewer
layers, each one sighted**:

> **Artifacts over answers. One mind builds. Verify hard. Decide cheap,
> build once.**

The quality bar is concrete and already rendered: Kevin's reference page
(`kmjcreate-demo.html`) and the approved-blueprint renders. "Would this
page hang beside those?" is the acceptance question for every build.

---

## 2. The target: five layers

```
1. DISCOVER   Chief's intake — artifacts first, 12 asks, vertical branching
              → ONE dossier (single JSON home; no more scattered surfaces)
2. DIRECT     The Spec Author (sighted): sees mark + work + reference
              screenshots + dossier → writes the fully-DECIDED blueprint
3. APPROVE    The Blueprint panel: read, revise for pennies, approve.
              No build ever runs from an unapproved design.
4. BUILD      ONE mind, ONE call, the whole page. Contract armor validates
              after (truth / coverage / editability / token bridge).
              Templates survive ONLY as the emergency fallback — and even
              the fallback wears the spec's tokens via the bridge.
5. VERIFY     The easel step (author reviews its own screenshots) +
              the fair judge (same-bar, static-only) + the ratchet
              (never downgrade the live site).
```

### Layer 1 — DISCOVER (mostly new; consolidation)
Today discovery is scattered: Style Interview, Taste Walk, color words,
Brand Kit, Media Library, site_prefs, practitioner profile — seven homes,
none complete, and the Director had to be taught to hunt through them
(the brand-mark bug was exactly this). Target: **one Discovery flow, one
dossier**. Full script in `docs/DISCOVERY_AGENT.md`. Key properties:
- **Recon first**: never ask for what the system already holds; prefill
  and confirm instead.
- **Artifacts outrank answers**: mark, work, references (screenshotted),
  portrait. Questions only fill what artifacts can't show.
- **Reference-site study**: Playwright screenshots the practitioner's
  loved/hated sites; the Director SEES them (transferable rules only,
  never identity — the languages-extraction protocol, per practitioner).
  Screenshot failures (bot-blocked sites, dead links, timeouts)
  degrade to skip-and-record: the dossier notes WHICH reference could
  not be captured and why, discovery continues, and the Director is
  told what it couldn't see. Per Invariant 8, a missing reference is a
  recorded fact, never a silent gap and never a stalled intake.
- Output: `site_config.discovery_dossier` — one JSON object, the single
  source the Director reads.

### Layer 2 — DIRECT (exists; keep and finish)
`spec_author.py` with everything learned this week: archaeology (sighted),
imagination (no-portfolio rung), generosity + coverage laws, brand-color
law, atmosphere rule, declaration rule, labeled eyes, room to finish.
Additions in the revamp: reads the ONE dossier instead of hunting; sees
reference-site screenshots; spec gains a small **machine-readable header**
(tokens + fonts + section list as JSON front-matter) so downstream code
never regex-parses prose again (the token bridge's regex becomes a
fallback, not the mechanism).

### Layer 3 — APPROVE (exists; keep)
The Studio Blueprint panel. Cost model stays inverted: deciding is
pennies; the build fee only ever renders an approved document.
The blueprint's machine-readable header is validated AT APPROVAL,
not at build. The Blueprint panel refuses approval — loudly, with
the exact missing fields — if the JSON front-matter lacks any of:
complete token set, font stack, or section list. The deterministic
spec→module translator downstream is itself a seam; it stays safe
only if the header is a complete contract. Per Invariant 6, an
incomplete spec must fail at the pennies stage, never at the
build-fee stage. Regex-parsing the prose body is a diagnostic
fallback for humans, never a mechanism.

### Layer 4 — BUILD (the big change)
Replace the chunked canvas + module assembly + atelier fragments + AD
layer + language CSS floors + framework skeletons with:
- **Builder v2**: one LLM call, whole page (HTML+CSS+≤6KB JS), from the
  approved spec + real data + token system. 24–32K output budget. This is
  the claude.ai/Emergent mechanism, proven five times in local renders.
- **The contract armor, applied AFTER authorship** (never fighting it):
  - TRUTH: every fact/number/price traces to the dossier (fact-check
    stays; taste floors stay advisory)
  - COVERAGE: every real image present by url; nav/contact-form/footer
    present; every service present
  - EDITABILITY: data-override-target on all copy, data-slot on images,
    zone stamps — Edit Mode and the Studio keep working. Editability is
    NOT the model's job to get perfect: a deterministic ANNOTATOR
    post-pass walks the DOM after authorship and injects any missing
    override targets, slots, and zone stamps. The model is asked to
    stamp them; the annotator guarantees them. An editability gap never
    costs a model call and never triggers repair or fallback.
  - TOKEN BRIDGE: spec tokens installed last on every path
  - SAFETY: JS armor, no external calls, size caps
  - REPAIR ECONOMICS: violations are triaged before any repair runs.
    * Mechanical violations (editability, token installation, size/JS
      armor trims) → fixed deterministically, zero model calls.
    * Authorship violations (truth, coverage) → ONE surgical repair
      call scoped to the violating sections only — the exact violations
      plus the minimum surrounding HTML, never a whole-page regenerate.
      A full 24–32K re-roll can reintroduce new violations elsewhere;
      the repair call is a scalpel, not a second surgery.
    * Repair fails validation again → fallback. One repair, ever.
- **Fallback**: the deterministic module path, unchanged, wearing spec
  tokens. It is the floor, never the ceiling.

### Layer 5 — VERIFY (exists; keep)
The easel step screenshots BOTH viewports — desktop and mobile
(390px) — and the author reviews both. The judge scores both; a page
that sings on desktop and breaks on mobile fails, full stop.
Invariant 4 (mobile parity ships in the same pass) is a build rule;
this is its verification twin. What isn't screenshotted isn't real.
Easel step → judge (arcD-2 rubric, same-bar rule, static-only law) →
ratchet with margin. Rejected candidates keep their HTML.

---

## 3. The kill list (and the bug each one caused)

Retired **from the build path** once Builder v2 proves itself (§5 gate):

| Component | Why it dies |
|---|---|
| DRO as middleman | Prefill kill; thin-mode saga; its `signature_move` mapper is where the recurring gold underline was born (`sx-sig-*`). The Director's spec replaces its job end-to-end. |
| Atelier fragments | Chunk-seam failures; per-section authorship is the opposite of one-mind. |
| Art-direction layer | A patch for template pages; a one-mind page art-directs itself. |
| Language CSS floors | The spec declares the language now; floors fought authored pages. |
| Framework skeletons | The spec decides section architecture. |
| Canvas chunking | Replaced by the single-call Builder v2 (chunks passed summaries, not sight). |
| compose_spec_llm (LLM section planning) | The blueprint's section list is the plan; a deterministic translator maps spec → data-module needs. |

**Not killed** (the trust layer — permanent):
model_ladder (+ sampling/prefill guards) · slot & media systems ·
Edit Mode / override system · fact-checker (truth-hard/taste-advisory) ·
judge + ratchet + easel · token bridge · terminology · vertical
intelligence · booking/store/contact wiring · the module registry (as
data-truth renderers and emergency fallback only).

---

## 4. Invariants — never break, at any phase

1. **Real or removed.** No invented facts, stats, testimonials, prices.
2. **Coverage.** Every real asset has a home; nav/contact/footer always.
3. **Editability.** Every visible word override-targetable; every image
   slot-addressable. A redesign never breaks Edit Mode.
4. **Mobile parity** ships in the same pass, always.
5. **The judge gates every ship; the ratchet never downgrades.**
6. **Decide cheap, build once.** No paid build without an approved spec.
7. **No deploys during builds.** Merges wait for `running = 0`.
   (Known limit: this works at current volume. As builds become
   continuous, it becomes an indefinite deploy blocker; the successor
   is a drain-and-queue — stop accepting new builds, finish in-flight
   ones, deploy, reopen. Noted now so future-us treats this as a
   scaling milestone, not a violated law.)
8. **Loud failures.** Any stage that skips/falls back writes WHY to the
   config. Silent fallback is the enemy that ate this month.

---

## 5. The cut order (surgery plan)

- **Phase 0 — freeze & flag.** Nothing is deleted. Builder v2 ships
  behind `SITE_BUILDER_V2=on`. The old path keeps running as default.
- **Phase 1 — Discovery consolidation.** The Discovery agent + the ONE
  dossier; existing data migrated in (mark, gallery, prefs, interview).
  Reference-site screenshot study. *(No old code dies; new intake feeds
  the existing spec author immediately.)*
- **Phase 2 — Builder v2.** Single-call whole-page builder + armor +
  repair pass, behind the flag. A/B against the old path on the same
  approved spec — judge scores both, Kevin eyeballs both.
- **Phase 3 — promotion.** V2 becomes default when it beats the old
  path on real builds at EITHER of these bars, whichever is met first:
  (a) 3 consecutive wins spanning at least 2 distinct verticals, or
  (b) 4 wins out of any 5 builds, spanning at least 2 distinct
  verticals. A "win" = judge composite ≥ the old path's on the same
  approved spec AND Kevin-score ≥ 8. The vertical-spread requirement
  exists because three coaching sites in a row prove nothing about a
  restaurant or a storefront; the 4-of-5 alternative exists because one
  fluky loss should not reset a real winner. RIDER (current scale):
  seeded demo businesses with real-shaped data COUNT toward the
  vertical spread — judged builds on them are cheap, and the spread
  must be satisfiable before there are two live customers. Old path
  demoted to emergency fallback.
- **Phase 4 — the strip.** Kill-list components removed from the build
  path; code deleted only after two clean weeks. Every removal is its own
  PR with the invariant checklist in the description.

**Success metrics:** judge composite ≥ 30 sustained · Kevin-score ≥ 8 ·
zero old-token bleed on EVERY served page regardless of which path
built it — v2 output, repair output, AND the fallback module path (the
fallback is where fossilized tokens live and where this bug
historically resurfaced). Formulation: when a spec governs, the served
page's tokens must MATCH the spec's declared set; a blacklist of
retired hexes/fonts is only the bootstrap check for pre-spec pages ·
one paid build per accepted design · a failed build is always
diagnosable from the DB alone.

---

**Strategic note:** Builder v2 concentrates page quality in one large
model call. The model_ladder surviving the kill list is the hedge —
keep the v2 builder prompt portable (no model-specific syntax,
capabilities declared in config) so laddering to a different model is
a config change, not a rewrite.

*SIGNED OFF 2026-07-24 (Kevin), amendments folded. Phase 1 is live.*
