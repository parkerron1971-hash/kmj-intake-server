# THE REVAMP TARGET — the site generator, stripped and rebuilt

*Drafted 2026-07-24 for Kevin's sign-off. This is the goal-state document:
what the generator becomes, what dies, in what order, and what may never
break while we operate. Nothing in this doc is code; nothing gets stripped
until Kevin signs off on this page.*

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
    zone stamps — Edit Mode and the Studio keep working
  - TOKEN BRIDGE: spec tokens installed last on every path
  - SAFETY: JS armor, no external calls, size caps
  - One repair pass with the exact violations; then fallback.
- **Fallback**: the deterministic module path, unchanged, wearing spec
  tokens. It is the floor, never the ceiling.

### Layer 5 — VERIFY (exists; keep)
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
- **Phase 3 — promotion.** V2 becomes default when it beats the old path
  on **3 consecutive real builds** (judge composite ≥ the old path's AND
  Kevin-score ≥ 8). Old path demoted to emergency fallback.
- **Phase 4 — the strip.** Kill-list components removed from the build
  path; code deleted only after two clean weeks. Every removal is its own
  PR with the invariant checklist in the description.

**Success metrics:** judge composite ≥ 30 sustained · Kevin-score ≥ 8 ·
zero old-token bleed (automated check: retired hexes/fonts absent from
served HTML) · one paid build per accepted design · a failed build is
always diagnosable from the DB alone.

---

*Sign-off: Kevin approves this doc → Phase 1 begins. Edits welcome — this
page is the contract for the revamp.*
