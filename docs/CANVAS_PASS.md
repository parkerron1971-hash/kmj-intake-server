# The Canvas Pass — whole-page authoring under platform contracts

Status: approved direction, pre-build. Phase 1 of 2.
Author: build-session 2026-07-20, after the Kimi.com reference experiment and the
Fable floor audit. Companion spec: `docs/CHIEF_GUIDED_INTERVIEW.md` (intake).

## 0. One-paragraph version

The reference experiment proved it: Kimi.com took one rich brief and produced a
551KB page our whole pipeline can't match — constrained generation has a ceiling
and the reference is above it. The canvas pass moves the authoring boundary from
armored per-section fragments up to the whole page: the model authors the creative
sections in 2–3 chunks, around **pre-rendered, immutable data sections** it can
position but never rewrite, under four hard contracts (truth, tokens, slots,
required sections). Everything downstream — slot population, overrides, quality
gate, invariants, vision grader, persistence — is unchanged, because the canvas
emits the same section anatomy the machinery already understands. Modules and the
atelier are not deleted: they become the floor the canvas falls back to.

## 1. Evidence and principles

Measured floor (Fable audit, same yardstick both sides):

| Metric | Reference (hand prompt → Kimi) | Our builds | Gap driver |
|---|---|---|---|
| Visible words | 867 | 292–352 | copy caps + module skeleton |
| Real images | 7 | 0 | imagery not load-bearing |
| Keyframes | 1 (the marquee) | 11–14 | motion spent on entrance, not signature |
| Marquee / portfolio filters | yes / yes | none / none | no authoring freedom for interactions |
| Sections | 6 | 6–8 | structure is fine |

Principles:

1. **The brief carries the design intelligence; the model carries the craft;
   the contracts carry the platform.** Quality must stop depending on which API
   answers — but weak models still exist, so verification catches variance and
   the floor catches failure. Never pretend otherwise.
2. **Truth is pre-rendered, not instructed.** "Never invent facts" as a prompt
   rule is a hope. Data sections rendered deterministically from real rows and
   handed to the canvas as immutable blocks is a guarantee.
3. **The canvas emits platform anatomy.** Section markers, DOM ids,
   `data-override-target`, `data-slot`, scoped CSS — so every downstream system
   (edit mode, slots, gate, invariants, grader) works untouched.
4. **Freedom where craft lives, determinism where facts live.** Creative
   sections (hero, about, interstitials, CTA) are authored; data sections
   (offerings, testimonials, statband, process, FAQ, store, showcase, gallery,
   contact) are module-rendered in Phase 1.

## 2. Non-negotiables

1. `chief_of_staff.py` stays untouched (per the interview arc's rule).
2. The deterministic path (compose_spec → render_page → atelier) remains intact
   and selectable by env — it IS the fallback. Rollback = one env flip.
3. Data sections are never rewritten by the model in Phase 1: no invented
   offerings, testimonials, stats, prices, FAQ answers, store items, contact rows.
4. Edit Mode keeps working: every presentation string carries
   `data-override-target="{module}/{field}"`; business data stays edit-at-source.
5. The judge stays independently pinned; a model never grades its own work.
6. The palette/type/rhythm token system (`--sx-*`) remains the only color/font
   source — no hex, no external fonts, no external assets of any kind.
7. Brand kit with a real secondary color is never mono-accident-ed away
   (companion fix, §10).

## 3. Architecture

```
compose_site (unchanged through spec finalization)
  ├─ sanitize/persist prefs → gather_context → references → signals → DRO
  ├─ apply_dro_design → compose_spec_llm → sanitize_spec → _ensure_connections
  │     … (today's path, unchanged)
  │
  ├─ NEW SITE_CANVAS=on branch (full recompose + DRO only):
  │    1. canvas_brief = compile_canvas_brief(ctx, dro, spec)   deterministic, no LLM
  │    2. plan = canvas_plan(spec)        section order, data-vs-authored split
  │    3. blocks = prerender_data_sections(plan, ctx)           module render, immutable
  │    4. chunks = author_canvas_chunks(brief, plan, blocks)    2–3 LLM calls
  │    5. html = assemble_canvas(plan, chunks, blocks)          markers/ids/css/shell
  │    6. fact_check(html, ctx, plan)                           new verifier (§7)
  │    7. render_and_persist(..., _canvas_html=html)            joins today's flow at
  │       slot population → overrides → quality gate → invariants → grader → persist
  │
  └─ fallback ladder (§9): any canvas stage failure → today's module+atelier path
```

### 3.1 The canvas brief (deterministic compile, no LLM)

The artifact Kimi.com effectively received, compiled from data we already have —
shaped like the owner's hand prompt: overview (offer, audience, verbs), brand
(tokens summary: palette direction + pairing + accent hexes named by role),
section plan with per-section intent, interactions budget (the ONE loud moment
from `creative.loud_where`), do/don't rules (avoid list, `inspiration_notes`,
DRO rule_break + tension + first_impression, doctrine one-liner). Compiled by a
pure function from `ctx` + `dro` + `spec` — no LLM call, no new failure mode.

### 3.2 The plan (deterministic)

From the finalized spec: section order; each section marked `authored` or
`block`. `authored`: hero, about, interstitial, cta (plus gallery only in its
awaiting-frames form). `block`: offerings, testimonials, statband, process,
faq, store, showcase, contact, gallery-with-photos. `_ensure_connections`
guarantees keep applying — blocks required by data are in the plan regardless
of what any model says.

### 3.3 Pre-rendered blocks (truth, immutable)

Each `block` section renders via the existing module registry
(`MODULES[id].render(variant, content, ctx)`), producing `(html, css)` with real
data and `ov()` targets already stamped. In the authoring prompt each block is
represented as a placement token `<!--SX_BLOCK:offerings-->` etc. (the
`<!--CONTACT_FORM-->` substitution pattern at `atelier.py:816-824`, generalized).
The canvas positions the token inside its layout; assembly splices the real
markup back. The model never sees writable access to facts.

### 3.4 Authoring chunks (2–3 LLM calls)

Full-page single-shot is 30–60K output tokens — beyond every provider ceiling
in the ladder (atelier 8K, spec 4K; moonshot adds +3K reasoning headroom). So
the canvas authors in chunks, each a complete run of consecutive `authored`
sections plus the block tokens that sit between them:

- Chunk A: header-adjacent creative — hero + first interstitial.
- Chunk B: about/story + second interstitial + cta.
- Chunk C (only when the plan is long): overflow sections + the page script.

Each call: `site_llm.create_message`, `max_tokens` 8000–12000 (provider-laddered
like atelier), system prompt = DOCTRINE + CREATIVE_CONTRACT + the canvas
contract (§4) + the canvas brief + prior-chunk summary (one paragraph: what
was built, which motifs were established — coherence without re-sending full
markup). Validation + ONE repair attempt per chunk (atelier's
`_attempt`/repair-prompt pattern). Chunk failure → that chunk's sections render
from modules (per-chunk degradation), breadcrumbed.

### 3.5 Assembly (`assemble_canvas`, new)

- Splice authored sections and pre-rendered blocks in plan order; stamp the
  section markers `<!--sx:{module}:{i}-->` and stable DOM ids (the conventions
  `render_page`/`replace_sections` already use), `sxm-stage` on authored
  sections so the shell's IntersectionObserver releases entrances.
- CSS: authored CSS scoped per section (same `.atl-{uid}` discipline) +
  block CSS deduped per `module:variant`, injected as
  `<style id="sx-canvas">` before `</head>`, after the shell style (same
  cascade position as `sx-atelier`).
- The page script (if any) goes through §6's JS armor, then appends before
  `</body>`.
- Then the SAME `page_shell` (fonts link, `--sx-*` :root block, base CSS,
  reveal script, meta) wraps everything — unchanged.
- `render_and_persist` gains an entry parameter `_canvas_html` that skips
  `render_page`/`run_atelier` and joins at slot population
  (`site_composer.py:2157`). Everything after is today's flow, untouched.

## 4. The canvas contract (authored sections)

Extends the atelier's 11 clauses (`atelier.py:564-584`), deltas only:

1. Section anatomy identical: one root `<section>` per authored section,
   `.atl-{uid}` scope on root only, keyframes prefixed, `@media ≤760px`,
   `prefers-reduced-motion` respected.
2. Colors only `var(--sx-*)`/`transparent`/`currentColor`/the two rgba pairs;
   fonts only the three `--sx-font-*` vars. (Unchanged.)
3. Images only `<img data-slot="…" src="" alt="…">`, platform fills src.
   (Unchanged.)
4. Every presentation string carries `data-override-target` exactly once;
   invented text uses `custom_N`. (Unchanged — "total editability".)
5. **NEW — block tokens**: `<!--SX_BLOCK:{module}-->` placed exactly once per
   planned block, never nested inside an authored section, never altered.
6. **NEW — interactions**: permitted (marquee, filter tabs, modal, accordion)
   under the §6 JS contract. This is the clause that finally allows the
   reference's signature moves.
7. **NEW — substance floor**: authored sections must carry real paragraphs —
   the brief specifies per-section minimums (hero ≤ 9-word headline but a real
   subhead; about ≥ 60 words; no caption-only sections). Checked by §7.
8. Size caps per chunk: HTML ≤ 18KB, CSS ≤ 14KB (atelier's 14/10 scaled for
   multi-section chunks).

## 5. The truth contract (unchanged, now load-bearing)

`ctx` from `gather_context` is the only fact source. The fact-checker (§7)
traces every rendered digit-run, price, proper name, and quote in authored
sections back to `ctx` (extending `atelier_validator`'s DATA FIDELITY check,
`atelier_validator.py:499-512`, page-wide). Block sections need no check —
they're deterministic by construction.

## 6. The JS contract (new)

Page interactions need JS; today's pages have none beyond the shell's reveal
script. Canvas-authored JS is allowed under armor:

- Exactly ONE `<script>` per page, appended before `</body>`, IIFE-wrapped,
  ≤ 6KB, plain string (no src).
- Banned: inline event handlers anywhere in markup, `eval`/`new Function`,
  `fetch`/`XMLHttpRequest`/`import`/`WebSocket`, `document.write`,
  `localStorage`/`sessionStorage` reads of platform keys, any `http` literal.
- DOM only: class toggling, attribute flips, `IntersectionObserver`,
  `addEventListener` on elements the canvas itself rendered.
- Enforced by a static scan in the armor (regex + token ban list), one repair
  attempt, then the script is dropped (page must remain coherent without it —
  the contract requires no-JS functional defaults, e.g. filters fall back to
  showing everything, modals to inline content).

## 7. The fact-checker + floor verifier (new stage)

Runs on the assembled page before slot population. Returns `(ok, problems)`:

1. **Fact trace** (§5): every digit-run/price/name/quote in authored sections
   must exist in the ctx data JSON. Invented "40+ clients" fails the build.
2. **Block integrity**: every planned `<!--SX_BLOCK-->` placed exactly once;
   block markup byte-identical to the pre-render (no model edits).
3. **Substance floor** (deterministic, from the audit's table): visible words
   ≥ `CANVAS_FLOOR_WORDS` (default 450); ≥1 real `data-slot` image populated
   when `media.gallery` is non-empty; keyframe count ≤ `CANVAS_KEYFRAME_CAP`
   (default 8 — the reference has 1; ours averaged 11–14).
4. **Required anatomy**: section markers, DOM ids, override-target census,
   single script block, no banned constructs.

Failure → one corrective retry with the problems pasted into the repair prompt
→ persistent failure drops to the module path for the offending sections (or
the whole page). Findings persist to `site_config.canvas_report` alongside the
existing `quality_report`.

## 8. Provider + cost budget

- 2–3 chunks × ~8–12K max_tokens out + brief/plan input ≈ 25–35K output tokens
  per full recompose. Owner-triggered recomposes only; refine reuses the stored
  canvas (same `stored` semantics as atelier fragments — shuffle/override
  re-renders never re-author).
- Ladder: same `model_ladder` discipline (moonshot fail-open → Claude ladder;
  timeout → 0.65× tokens retry → Sonnet rung). Timeouts: new `canvas` task
  family, 120/240s by model family.
- The composer provider switch (`SITE_BUILDER_PROVIDER`) routes canvas like the
  other five stages; the judge stays pinned independently.

## 9. Degradation ladder (updated)

Canvas stage failure → per-chunk module render for that chunk → whole-canvas
failure → today's module+atelier path → (unchanged) deterministic default spec.
Fact-check failure → corrective retry → module path. Every fallback logged and
persisted (`canvas_report.fallbacks`). A plain page is never a mystery; a
failed canvas is never a blank page.

## 10. Companion fixes in this arc (small, same theme)

1. **Mono-accent guard**: the mono-accent class may never neutralize
   `--sx-secondary` when the brand kit carries a genuinely chromatic secondary
   (sat > 0.18, hue gap > 30° — the P2 activation rule). Owner brand beats
   stance, same principle as the B4 anti-convergence exemption.
2. **Marquee wiring**: the interstitial `marquee` variant becomes
   owner-directable — selectable in the canvas plan when the DRO's
   `loud_where`/`signature_move` calls for it (today only the ceremony pass can
   insert it).
3. **Substance invariants**: WORDS-1 / IMAGERY-1 / MOTION-CEILING-1 register in
   `design_invariants.py` (the fixed tuple at `:215-217`) — advisory by default,
   feeding the bounded regen's HIGH-finding trigger when enforced. These check
   the final document regardless of authoring path, so they serve module builds
   too.
4. Judge env back to the pinned Anthropic default (ops, not code).

## 11. Phases

**Phase 1 (this spec)**: hybrid canvas — authored creative sections around
immutable data blocks; canvas brief compile; 2–3 chunks; JS contract;
fact-checker; substance floor; companion fixes; `SITE_CANVAS=off` default,
enabled per-business for the KMJ business first.

**Phase 2 (later spec)**: data sections authored too (fact-checker graduates to
sole guardian); reference corpus (gold builds stored as artifacts); relative
grading (judge sees reference screenshots); instinct loop (verdicts +
decisions accumulate into positive examples — quality attributes only, never
surface sameness).

## 12. What happens to the atelier and modules

Nothing is deleted. Modules: the truth renderer (blocks) and the whole fallback
path. Atelier: downgraded from "the bespoke layer" to a per-section repair tool
— when a canvas chunk fails, its sections can still be atelier-upgraded from
the module render rather than shipped plain. The atelier contract and armor
(`atelier_validator`) are reused wholesale by the canvas chunk validator —
that code is the reason this arc is weeks, not months.

## 13. Acceptance criteria

On the KMJ business (real data, real prefs), `SITE_CANVAS=on`:

1. Floor metrics: visible words ≥ 450; sections ≥ 6; ≥ 2 real images (given
   gallery photos exist); keyframes ≤ 8; ≥ 1 signature interaction (marquee,
   filter, or modal) when the DRO calls for it.
2. Truth: fact-check 100% trace; block sections byte-identical to module
   renders; zero invented facts in the grader's notes.
3. Platform intact: override-target census 100% on presentation strings;
   edit-mode text edit + gallery slot + color override all apply on the served
   page; quality gate / invariants / grader all run and persist as today.
4. Grader: impact ≥ 8, smell ≤ 3, broken=n (with the animation-settle fix).
5. Fallback: `SITE_CANVAS=off` reproduces today's build exactly; chunk-kill
   test (forced chunk failure) degrades to module sections with the breadcrumb.
6. Build wall-clock ≤ 10 minutes on the Kimi provider path.
7. Side-by-side with the reference: different, not lesser (the owner's manual
   check — the one no script settles).

## 14. Risks, honestly

- **Variance**: some canvas runs will be worse than the module floor; the
  fact-checker + grader + keep-better regen guard exist for exactly this.
  Watch the first 10 real builds before widening the rollout.
- **Cost/latency**: ~3x today's token spend per recompose. Acceptable
  owner-triggered; not acceptable as a cron.
- **JS armor is new territory**: the ban list will miss something on day one;
  the no-JS-default clause is the mitigation.
- **Coherence across chunks**: the prior-chunk summary is a bet; if seams show
  (repeated motifs, contradicting copy), the fix is a shared "page motifs"
  section in the brief, not more armor.
