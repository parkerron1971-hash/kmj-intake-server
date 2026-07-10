# Smart Sites — Design Gap Analysis & Build Plan

**Status:** RULING DOC (2026-07-10) · Companion to `design_rationale_layer.md`, the Smart Sites arc history (arcs 1–12), and `future_architecture.md`
**Method:** field research (published critiques of AI-generated design + how Lovable/Framer/Relume/Durable/v0 actually work, 12 sources) crossed with a live-page autopsy of kmj-creative-solutions.mysolutionist.app
**Handbook copy:** `Documents\THE SOLUTIONIST HANDBOOK\02 - Site Design Gap Analysis.md`

---

## 1. The verdict: the engine works; the problem moved

Twelve arcs built a genuinely differentiated engine — DRO concept reasoning, bespoke Atelier sections on Opus, ceremony rhythm, craft floor, three-direction compose, persisted design spec. The live page proves it: a real concept ("Scattered pieces. One clear solution.") threaded through every heading, custom CTA voice, art-directed concept imagery, 156 bespoke markers firing.

**The remaining gap is NOT the engine. It sits in three places:**

| # | Gap | Live-page evidence | Field confirmation |
|---|---|---|---|
| 1 | **Materials poverty** | Display+body = Montserrat + Open Sans (the two most generic web fonts); accent = #00ff59 max-saturation terminal green | Rule 2: "typography is the fastest escape from AI slop"; Open Sans/Lato/Inter banned as display. Rule 1's mechanism (median-of-the-web defaults) applies to our thin font/accent library exactly as it does to Tailwind's indigo |
| 2 | **Substance thinness** | 393 words, 6 sections, 4 images, no testimonials rendered, no credentials/FAQ/team/gallery, one Unsplash service image | Rules 11–14: real photography, named practitioner profiles, price+duration menus, uncuratable third-party proof. July-4 audit finding #5 ("data unpulled: bio, credentials, team, FAQ, socials, hours") was never built — concept got 12 arcs, substance got 0 |
| 3 | **Poetry outranks the offer** | Hero + all H2s are metaphor; nowhere in the 5-second read does the page say what KMJ does, for whom, and what to do next | Rule 9 (NN/g): 74% abandon if they can't find what they need in 5s; only ~14% of pages pass. Arc 10's offer_clear intent exists but the ceremony voice wins the fight |

**The strategic insight from the field study:** the leaders (Relume, Framer, Lovable) win by *selection from taste-vetted libraries + enforced global coherence*, not by generation. And they ALL share a ceiling — nobody does vertical-specific trust stacks (live reviews, named practitioners, price+duration menus) as an enforced default. For local service businesses those conversion features matter more than another gradient. **That ceiling is our opening, and it happens to be the same work as the agent-readable layer** (structured services with prices/durations/availability are machine-legible by construction).

Mechanism note for all prompt work: models revert to the statistical median; **explicit ban-lists measurably shift output, adjective prompts do not.** Encode every rule below as BOTH a prompt constraint AND a post-render gate check (we already have the 134-check gate — extend it).

---

## 2. The 19 field rules (encodable), mapped to our state

Legend: ✅ already have · 🟡 partial · ❌ missing

1. ❌→n/a **Accent taste governor** — we don't do indigo, but #00ff59 is our equivalent tell. Rule: accent saturation cap + hue-family sanity per vertical unless brand-supplied; extend Arc 9's band governor to the accent family itself.
2. ❌ **Characterful display face; generic fonts banned as display** (Fraunces, Space Grotesk, Playfair, Clash Display, Satoshi, Bricolage Grotesque, Newsreader class). Body may stay quiet.
3. 🟡 **Extreme type contrast** — craft floor has w900 h1 clamp ✓; enforce weight-gap ≥500 and hero:body ≥3× as gate checks.
4. 🟡 **Never the canonical section order** (hero→3-cards→proof→pricing→FAQ) — ceremony varies rhythm; add explicit linter + vertical-specific sequence archetypes.
5. 🟡 **No icon-trio / three-uniform-cards** — add gate check: no section of exactly 3 equal cards.
6. ✅ **Section rhythm variation** — ceremony pass does this; add adjacent-tuple gate check to lock it.
7. 🟡 **≥1 asymmetric composition above mid-page** — atelier sometimes; make it a gate requirement.
8. ✅ **One radius vocabulary, restrained shadows** — craft floor (radius 28, tuned depths).
9. ❌ **Five-second hero test** — what/who/next above the fold. THE conversion gate.
10. ❌ **Vague-headline grammar ban** ("Empower/Unlock/Transform", abstract two-noun features) + ≥1 concrete specific per page — regex + judge in gate.
11. 🟡 **Real photography typed slots** {real_work, real_space, real_person}; prompt owner for photos before stock fallback (Story Walkthrough photo rungs exist — enforce at gate).
12. 🟡 **Booking-forward**: booking CTA in header, flow stays on-site — we own the rails; make header CTA structural.
13. ❌ **Transparent pricing with durations** in services sections — data exists in products (price, duration_minutes); render it.
14. ❌ **Trust stack**: named practitioner profile section; third-party review count when available; real testimonials rendered.
15. ✅ **One orchestrated entrance** — craft floor reveal system.
16. ❌ **Secondary tell bans** (badge-pill above headline, default 1-2-3 steps, gradient-on-white hero) — cheap gate regexes.
17. ✅ **Lock spec → 3 directions → pin** — DRO persistence + compose_directions. (Field-validated architecture; keep.)
18. 🟡 **Optical discipline** — tracking rules partially in craft floor; add caps-tracking + base-unit rhythm checks.
19. 🟡 **Differentiation hook drives design** — DRO concept ✓; add explicit differentiator intake question + dedicated section.

---

## 3. Build plan — three single PRs, in order

**Arc M "Materials" (backend, single PR):**
Curated display-font library (10–12 characterful faces mapped to personality axes/verticals, quiet body partners; Montserrat/Open Sans/Inter/Lato/Roboto banned as display), accent taste governor v2 (saturation cap, hue sanity, brand-color override honored), slop-lint pack added to the existing gate (rules 1, 2, 5, 10, 16 as regex/deterministic checks; fail = named violation, one regen with the violation quoted in the prompt — ban-lists work).

**Arc S "Substance & Trust" (backend + small FE, single PR):**
Close audit finding #5 at last: pull bio/credentials/team/hours/FAQ/socials into the intake; render the trust stack — testimonials with named attribution, practitioner profile section (name, photo, specialty), services menu with price + duration from products, booking-forward header CTA on our own rails. Minimum-substance gate: a page under N words / without proof section prompts the owner for what's missing instead of shipping thin. This arc double-counts as the agent-readable foundation (structured offer data).

**Arc F "Five-Second Gate" (backend, single PR):**
Hero legibility check (what/who/next above fold — deterministic field presence + LLM-judge fallback), atelier prompt hierarchy rebalance (offer clarity is law; metaphor is the *seasoning*, enforced order: clear line first, poetic line second), differentiator intake question surfaced in hero + one dedicated section.

Order rationale: Materials is highest visible-impact-per-line and pure backend; Substance is the biggest gap vs field and feeds the agent-readable arc; Five-Second locks conversion last so it judges pages that already have substance to point at.

**Standing lesson applied:** single PRs, never stacked (the #46–48 incident); autopsy the live page after each arc's first recompose; when raising an LLM output budget, raise the timeout with it.

---

## 4. Sources (field research)

dev.to/alanwest (×2: indigo-500 tell + fix guide w/ lint regexes) · prg.sh (median-of-the-web mechanism, ban-lists over adjectives) · superdesign.dev (slop starter pack) · 925studios (slop checklist) · shuffle.dev (canonical-order origin) · nanoglobals 20-barbershop study (booking-forward, price+duration, live reviews, named barbers, differentiation hooks) · glossgenius · lovable.dev design-systems · relume.io (curated-library model) · koji.so + uxarmy (5-second/NN/g) · nineblaess.de (optical typography) · rationalgo (Durable review).
