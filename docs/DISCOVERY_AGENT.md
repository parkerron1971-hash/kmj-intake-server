# THE DISCOVERY AGENT — the intake that makes the prompt

*Drafted 2026-07-24 for Kevin's sign-off. Companion to REVAMP_TARGET.md
(Layer 1). This is the complete script: principles, flow, the question
bank with branching, the reference-study protocol, and the agent's
system-prompt core. Built from claude.ai's 31-question framework, cut to
12 asks and reordered by a rule we proved live: artifacts beat answers.*

---

## 1. Principles (each one earned this week)

1. **Artifacts outrank answers.** Five drafts of adjective-driven specs
   produced invented amber; one *seen* logo produced "gold script,
   chartreuse CREATIVE" immediately. Collect things to LOOK at first;
   ask questions only to fill what artifacts can't show.
2. **Recon before asking.** Never ask for what the system already holds
   (mark, gallery, prefs, interview answers, vertical). Prefill and
   confirm: "I've got your logo and 9 pieces of work — still current?"
3. **Either/or beats open-ended.** People answer forced choices honestly
   and fast (the Taste Walk proved this in production). Open questions
   are reserved for the four that genuinely earn it.
4. **Weight what they point at over what they say.** A loved reference
   site is studied (screenshotted, rules extracted), not stored as text.
5. **Always ask why on avoids.** "No red" always has a story; the story
   is the design signal.
6. **Branch by vertical.** A barber, a coach, and a church need 2-3
   different questions — not the same script. Vertical intelligence
   already knows the practitioner's type; use it.
7. **Reflect back before handing off.** The agent synthesizes a 5-line
   mini-brief and confirms it — catching contradictions ("minimal" +
   twelve sections) BEFORE the Director spends a call. The full-fidelity
   confirmation remains the Blueprint itself.
8. **One dossier.** Everything lands in `discovery_dossier` — a single
   JSON object. The Director reads one place. No more hunting across
   seven surfaces (the brand-mark bug was exactly that hunt failing).

---

## 2. The flow

```
STEP 0  RECON      inventory what exists → confirm stale items only
STEP 1  ARTIFACTS  mark · work/photos · references (→ study) · portrait
STEP 2  IDENTITY   4 open questions (the only open ones)
STEP 3  TASTE WALK 7 either/or pairs (extends the existing 5-pair walk)
STEP 4  TRUTH      provable numbers · color musts/avoids + the why
STEP 5  VERTICAL   2-3 branched questions by business type
STEP 6  REFLECT    5-line mini-brief → confirm/correct → write dossier
                   → hand to the Director
```

Session shape: conversational (Chief voice), one step at a time, skippable
("I'll add photos later" is a valid answer — the dossier records the gap
and the Director designs with a declared placeholder, never an invention).

---

## 3. The question bank

### Step 1 — ARTIFACTS (the spine)
| Ask | Unlocks |
|---|---|
| A1. "Upload your logo / brand mark." | Color authority (Brand Color Law binds to it) |
| A2. "Give me 3–8 pieces of your work, or photos of your business/space." | Archaeology: palette-in-practice, type personality, energy |
| A3. "Name 2–3 sites you love — one word each on why. And one site that turns you off — why?" | Reference study (§4); the hate answer is a ban list |
| A4. "A photo of you (or whoever fronts the business)?" | About section; portrait treatment |

### Step 2 — IDENTITY (the only open questions)
| Ask | Unlocks |
|---|---|
| I1. "What do you do, in one sentence?" | Hero subhead; selling-law who/what |
| I2. "The ONE thing a visitor should do — book, buy, call, sign up?" | CTA + page architecture; the breakout's terminus |
| I3. "Your brand as a person — three words." | The single highest-leverage adjective question |
| I4. "First three seconds on your site: what should someone FEEL?" | The emotional target the judge's bar anchors to |

### Step 3 — TASTE WALK (either/or; extends the shipped 5-pair walk)
| Pair | |
|---|---|
| T1. Light & airy — or dark & dramatic | |
| T2. Minimal & spacious — or rich & full | |
| T3. Type carries it — or photos carry it | |
| T4. Sharp edges — or soft rounded | |
| T5. Modern/tech — or classic/timeless | |
| T6. Playful — or serious | |
| T7. Motion: one signature moment — gentle throughout — completely still | *(three-way; Kevin's live animation experiment is this question)* |

### Step 4 — TRUTH
| Ask | Unlocks |
|---|---|
| N1. "Numbers you can PROVE — years in, clients served, launches, five-star counts?" | Stats row; anything unproven renders confirm-then-publish |
| N2. "Colors you must have? Must avoid? Tell me why on the avoids." | Palette constraints + the story behind them |

### Step 5 — VERTICAL BRANCHES (2-3 each; via vertical intelligence)
- **Coach/consultant**: credibility artifacts (certs, results, media)? ·
  session/booking flow? · signature framework with a name?
- **Salon/barbershop**: photos of the space and finished work (→ A2) ·
  price-list on site or by consult? · walk-ins or bookings?
- **Church/ministry**: service times & location prominence · sermon/media
  archive? · giving link?
- **Retail/product**: hero products (3-5) with real prices · fulfillment
  (ship/pickup)?
- **Restaurant/food**: menu on-page or PDF · reservations/ordering ·
  food photography (→ A2)?

### Step 6 — REFLECT-BACK (verbatim template)
> "Here's what I'm hearing: **[dark, warm, type-led]**, built around
> **[your gold-and-green mark]**, one clear action — **[book a call]** —
> and it should feel like **[someone already sees the mess and isn't
> rattled]**. Sound right, or should I bend anything before the Director
> writes your blueprint?"

Contradiction check runs here: minimal-vs-density, still-vs-motion,
avoid-color-vs-mark-color. Conflicts are surfaced as one question, never
silently resolved.

---

## 4. The reference-study protocol (automated)

For each loved/hated URL: Playwright screenshots at 390/900/1440 → a
vision call extracts **transferable rules only, never identity**
(the design-languages extraction protocol, per practitioner):
- loved: palette temperature, type posture, density, motion budget,
  one signature move worth learning from — as RULES ("hairline dividers,
  one accent doing one job"), never "copy this site"
- hated: named bans ("no parallax, no neon, no clutter") — these join
  the Director's judge-lessons ban list
Artifacts stored: screenshot refs + extracted rules in the dossier; the
Director SEES the loved-site screenshots alongside the owner's own work.

---

## 5. The dossier (the single output)

```json
discovery_dossier: {
  "version": 1,
  "artifacts": {
    "brand_mark_url": "...", "work": [{"url","note"}], "portrait_url": "...",
    "references": [{"url","verdict":"love|hate","why","rules":[...],"shots":[...]}]
  },
  "identity": {"one_liner","primary_action","brand_persona":[3],"first_3s_feel"},
  "taste": {"ground","density","carrier","edges","era","tone","motion"},
  "truth": {"proven_stats":[{"label","value","proof"}],
             "colors_must":[], "colors_avoid":[{"color","why"}]},
  "vertical": {"type", "answers": {...}},
  "gaps": ["portrait_pending", ...],
  "confirmed_brief": "the 5-line reflect-back, as confirmed",
  "confirmed_at": "..."
}
```

Rules: one home (`site_config.discovery_dossier`). Existing data migrates
in at Step 0 (brand kit, gallery, site_prefs, interview answers). `gaps`
is honest — the Director designs around a declared gap; it never invents
across one.

---

## 6. The agent's system-prompt core (drop-in)

> You are Chief running DESIGN DISCOVERY for a practitioner's website.
> Your job is not to ask questions — it is to gather the raw material a
> creative director needs to write a fully-decided design specification.
> Artifacts outrank answers: get things you can SEE first (logo, work,
> reference sites, portrait); ask questions only for what artifacts
> cannot show. Never ask for anything the system already holds — recon
> first, confirm staleness only. Prefer either/or choices over open
> questions; the only open questions are the four identity questions.
> When they name a color to avoid, always ask why — the story is the
> signal. Branch your last questions by their business type. A skipped
> item is a recorded GAP, never a blocker and never something to invent
> around. End by reflecting back a five-line brief in their own words
> and getting a yes — surface any contradiction as one plain question.
> Write everything to the discovery dossier. You are warm, fast, and
> concrete; this should feel like ten minutes with someone who already
> sees what they're carrying and isn't rattled by it.

---

*Sign-off: Kevin approves both docs → Phase 1 builds this agent (Studio +
Chief chat entry), the dossier, and the reference-study pipeline — with
the existing spec author reading the dossier from day one.*
