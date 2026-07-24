# THE DISCOVERY AGENT — the intake that makes the prompt

*Drafted 2026-07-24 for Kevin's sign-off. Companion to REVAMP_TARGET.md
(Layer 1). This is the complete script: principles, flow, the question
bank with branching, the reference-study protocol, and the agent's
system-prompt core. Built from claude.ai's 31-question framework, cut to
12 asks and reordered by a rule we proved live: artifacts beat answers.*

*REVISION 2 folded (signed 2026-07-24): infer-before-asking everywhere it
reaches — typical run 6-7 asks, floor of 5 on rich system data. Every
inference is shown for a yes; nothing derived is silently written.*

---

## 1. Principles (each one earned this week)

1. **Artifacts outrank answers.** Five drafts of adjective-driven specs
   produced invented amber; one *seen* logo produced "gold script,
   chartreuse CREATIVE" immediately. Collect things to LOOK at first;
   ask questions only to fill what artifacts can't show.
2. **Recon before asking.** Never ask for what the system already holds
   (mark, gallery, prefs, interview answers, vertical). Prefill and
   confirm: "I've got your logo and 9 pieces of work — still current?"
2b. **Infer before asking.** Recon covers what the SYSTEM holds; this
   covers what the ARTIFACTS show. Never ask a question the mark, the
   work, or the studied references can already answer. Derive the
   reading, then show it for a one-word confirm. The line between
   this and invented-amber: the Director invented UNSEEN — the
   Discovery agent infers AND SHOWS ITS INFERENCE for a yes. Nothing
   derived lands in the dossier unconfirmed.
3. **Either/or beats open-ended.** People answer forced choices honestly
   and fast (the Taste Walk proved this in production). Open questions
   are reserved for the four that genuinely earn it.
3b. **The half-answer rule (rider).** Compressed asks are multi-part,
   and people reliably answer only the LAST part of a multi-part
   message. If only half was answered, follow up on the missing half
   ONLY — never re-ask the answered part. Without this rule,
   compression backfires into re-asking, spending the exact attention
   it was designed to save.
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
STEP 0  RECON      inventory system data → confirm stale items only
                   (now also covers vertical facts: bookings config,
                   store config, prices, hours, site_prefs)
STEP 1  ARTIFACTS  2 asks: [mark + work + portrait, one drop] ·
                   [references: 2-3 loved, 1 hated, one word why each]
                   → reference study runs (§4, extended)
STEP 2  IDENTITY   2 asks: [one-liner + primary action] ·
                   [3 words + first-3-seconds feel]
STEP 3  TASTE      1 derived confirm (all 7 pairs prefilled from
                   artifacts) + 0-2 residual pairs asked the old way
                   where artifacts conflict or are silent
STEP 4  TRUTH      1 ask: provable numbers. Color musts come from the
                   mark (Brand Color Law); only the AVOIDS are asked,
                   folded into the taste confirm with their why.
STEP 5  VERTICAL   0-1 asks — whatever recon could not prefill
STEP 6  REFLECT    unchanged — 5-line mini-brief → confirm → dossier
                   → hand to the Director

The count, honestly: rich system data + clean signals = 5 asks
(A1, A2, I1, I2, N1). Typical = 6-7. Cold practitioner with thin
artifacts = 8-9 (residual pairs revert to asked form — never 12).
The floor set is the set no artifact and no database can answer.
```

Session promise: **five minutes** with someone who already sees what
they are carrying and is not rattled by it.
Session shape: conversational (Chief voice), one step at a time, skippable
("I'll add photos later" is a valid answer — the dossier records the gap
and the Director designs with a declared placeholder, never an invention).

---

## 3. The question bank

### Step 1 — ARTIFACTS (the spine)
| Ask | Unlocks |
|---|---|
| A1. "Drop me three things: your logo, 3-8 pieces of your work or photos of your space, and a photo of you (or whoever fronts the business). Skip any — I'll note it." | Color authority · archaeology · portrait, one message |
| A2. "Name 2-3 sites you love — one word each on why. And one that turns you off — why?" | Reference study (§4); the hate answer is a ban list |

### Step 2 — IDENTITY (the only open questions)
| Ask | Unlocks |
|---|---|
| I1. "What do you do, in one sentence — and what's the ONE thing a visitor should do: book, buy, call, sign up?" | Hero subhead + CTA/terminus |
| I2. "Your brand as a person — three words. And in their first three seconds on the site, what should someone FEEL?" | Persona + emotional target |

*(All four dossier fields survive; the half-answer rule governs both.)*

### Step 3 — TASTE (1 derived confirm + 0-2 residuals)

**The derived-taste confirm (verbatim template):**

> "From your mark, your work, and the sites you love, here's how I'd
> read your taste: **[dark & dramatic · spacious · type carries it ·
> sharp edges · modern · serious · one signature motion moment]** —
> and I'll keep **[red]** out entirely. Flip any of those, or does
> that read right?"

Rules: all 7 pair-readings come from the extended reference study (§4)
plus mark/work archaeology, each with a confidence score. A pair is
ASKED (old either/or form) only when confidence is low or sources
conflict — residuals in practice: 0-2, asked BEFORE the confirm so the
confirm is complete. A flip costs one word; flips overwrite the derived
reading and are tagged `flipped`. Color avoids ride this confirm; a
newly named avoid still gets its why (Principle 5 untouched).

The seven pairs (asked directly only as residuals):
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

*(N2 dissolves: musts derive from the mark under the Brand Color Law;
avoids fold into the taste confirm. The why-on-avoids rule survives.)*

### Step 5 — VERTICAL BRANCHES (0-1 asks; recon prefills first)
Recon prefills from platform data: bookings config answers the booking
question, store config answers hero products and prices, site_prefs
answers hours/location. Ask only what recon cannot see (e.g. "signature
framework with a name?" — that lives in their head, not the database).
Prefilled facts surface in the Step 6 reflect-back as confirms.
Branch banks (asked only when recon is silent):
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

**Extended extraction (Revision 2):** the vision call's output contract
widens — alongside transferable rules and named bans, it returns a
TASTE READING: a verdict per Taste pair (ground/density/carrier/edges/
era/tone/motion) with a confidence score, synthesized across the loved
references AND the practitioner's own mark and work. Low-confidence or
conflicting pairs are flagged; those become the 0-2 residual questions.
One slightly bigger vision prompt — model effort is pennies,
practitioner attention is the scarce resource.

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
  "taste": {
    "ground":  {"value","source","confidence"},
    "density": {"value","source","confidence"},
    "carrier": {"value","source"},  "edges": {"value","source"},
    "era": {"value","source"},      "tone": {"value","source"},
    "motion": {"value","source"}
  },
  "truth": {"proven_stats":[{"label","value","proof"}],
             "colors_must":[{"value","source":"recon-mark"}],
             "colors_avoid":[{"color","why","source"}]},
  "vertical": {"type", "answers": {"...": {"value","source"}}},
  "gaps": ["portrait_pending", ...],
  "confirmed_brief": "the 5-line reflect-back, as confirmed",
  "confirmed_at": "..."
}
```

Rules: one home (`site_config.discovery_dossier`). Existing data migrates
in at Step 0 (brand kit, gallery, site_prefs, interview answers). `gaps`
is honest — the Director designs around a declared gap; it never invents
across one.

Source vocabulary: `recon` (system data, staleness-confirmed) ·
`recon-mark` (derived from the mark under the Brand Color Law) ·
`inferred-confirmed` (agent derived, practitioner approved) ·
`flipped` (agent derived, practitioner overrode) · `asked` (answered
directly). Invariant: **no field ships with a bare inferred value** —
everything derived is `inferred-confirmed` or `flipped` by write time;
an unconfirmed inference is a GAP, not a value. The Director weights
`asked`/`flipped` above `inferred-confirmed` when signals conflict:
what they corrected or said outranks what we read.

---

## 6. The agent's system-prompt core (drop-in)

> You are Chief running DESIGN DISCOVERY for a practitioner's website.
> Your job is not to ask questions — it is to gather the raw material a
> creative director needs to write a fully-decided design specification,
> while spending as little of the practitioner's attention as possible.
> Artifacts outrank answers: get things you can SEE first (logo, work,
> reference sites, portrait). Recon before asking: never request what
> the system already holds — prefill and confirm staleness only. Infer
> before asking: never ask a question the artifacts can already answer —
> derive the reading and show it for a one-word confirm; a flip costs
> them one word. Nothing you infer is ever silently written: every
> derived value is confirmed by the practitioner or recorded as a gap.
> Multi-part asks obey the half-answer rule: if only half was answered,
> follow up on the missing half only — never re-ask the answered part.
> The only open questions are the two identity questions. When they name
> a color to avoid, always ask why — the story is the signal. Branch
> any final questions by business type, but only for what recon cannot
> see. A skipped item is a recorded GAP, never a blocker and never
> something to invent around. End by reflecting back a five-line brief
> in their own words and getting a yes — surface any contradiction as
> one plain question. Write everything to the discovery dossier with its
> source. You are warm, fast, and concrete; this should feel like five
> minutes with someone who already sees what they're carrying and isn't
> rattled by it.

---

*Sign-off: Kevin approves both docs → Phase 1 builds this agent (Studio +
Chief chat entry), the dossier, and the reference-study pipeline — with
the existing spec author reading the dossier from day one.*
