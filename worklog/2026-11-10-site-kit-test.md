---
title: The kit test, pages assembled from finished sections
date: 2026-11-10
agent: Claude Code (Claude Opus 5.5)
asked: "go, fix the two gaps first and make it happen"
status: shipped
prs: [kmj-intake-server#1788]
migrations: []
left_undone:
  - "SITE_KIT defaults to owner: only the platform owner's businesses build from the kit. Turning it on for everyone (SITE_KIT=on) is Kevin's call, on a Thursday."
  - "A kit page has no builder-only extras yet: the one-section rework and the revision round answer 'this page wasn't made by the site builder', the World offer page and the photo list are skipped. Re-assembling a kit page for free after an edit is the obvious next step."
  - "Owners are charged the same credits for a kit build as a builder build; the platform's cost drops from about $2.70 to a few cents. Pricing is Kevin's call."
  - "Five of 17 layouts are in the kit (Booking desk, Poster, Bulletin, Leader, Magazine). Kevin: do all; the other 12 are next."
  - "Ministries and events render and are tested, but no graded page has had them: Love City's data has neither, and the only freely licensed church photos found showed identifiable public figures, so no made-up church got photos."
  - "Pages with no photos are the weak spot: the food truck's first screen scored 7 of 10 every round, and the grader's first note was always 'add real photography'."
  - "The custom section path works (safe every time, about 8 cents, about 20 seconds) but its layouts came out lopsided twice. A menu card is common enough to be a kit section instead."
  - "The grader moves a point or two between runs of the same kind of page: the barber scored 27, 29, 28, 30, 30 across the rounds."
decisions:
  - "Facts are filled by code only. The words step can choose what the letterboard shows, but every row is checked against one record of the data at a time (fact_records)."
  - "The page wears the blueprint's own palette, type and words, so the Director's decisions survive; this is what the June module path lacked."
  - "The kit owns its phone dock: it rises only once the hero is gone and drops again at the visit section."
related: [2026-11-09-scenes-survive-the-builder.md, 2026-11-10-old-pick-meets-new-ask.md]
---
Kevin asked whether a Wix-style builder would cut the cost of a site. My answer was a
hybrid: keep the Coach and the Director's blueprint, replace the builder writing every
page's code with finished sections filled by code, and let the AI write only the
words, plus one custom section where the kit has nothing.

History first: the system had an assembler in June (site_modules, Arc 26). The July
review (docs/site_design_gap_analysis.md) found its pages generic, and the revamp
(docs/REVAMP_TARGET.md) made "one mind builds" the path and the modules the fallback.
The kit is a second try that differs where the first failed: it wears the blueprint's
own palette, type and words, and the library's finished objects carry the craft.

The test (scripts/site_kit_bench.py), graded by the product's own vision_grader:

| Page | Grade | Broken | Build cost |
|---|---|---|---|
| Builder, Marrow & Steel (11-09 test) | 27/40 | yes | $2.63 |
| Kit, Marrow & Steel, same blueprint | 30/40 | no | 4 cents (words) |
| Kit, Smoke Signal BBQ, no photos, one custom section | 26/40 | no | 12 cents |

Assembly takes 1 to 4 milliseconds; the words take 9 to 23 seconds. The whole test cost
$1.15, including the food truck's blueprint (34 cents) and six rounds of grading at 3
cents a page.

What the rounds fixed, all in the kit, once, for every page: a light look's dark
chapters kept dark text; three-line headlines ran seven deep; the library dock rose over
a tall phone hero; the letterboard clipped long rows; and the blueprint's own board
(this week's stops) lost to a hard-coded price list. My own eyes caught one the grader
didn't: a 40-character cap cut "1200 E 6TH ST" to "1200 E 6".

## The church layouts (same day)

Kevin: "do all but start on these ones" (Bulletin, Magazine, Leader, Poster). The kit
became layouts made of shared sections (site_kit_church.py): poster, bulletin, magazine
cover and leader openings; the gatherings strip; the owner's phrases band; album;
leaders; story with polaroids; ministries; events; topics; a closing ceremony band; the
visit section with first-time steps; the sign-off. The layout comes from the
blueprint's LAYOUT line (kit_layout); the words sheet is shaped per layout.

Tested on Love City's public facts and photos (the builder test's fixture), the owner's
layout pick set per run, so the Director wrote a fresh blueprint in each layout:

| Layout | Grade | Broken | Notes |
|---|---|---|---|
| Poster | 30/40 | no | the builder's Love City page, same blueprint: 30/40 |
| Bulletin | 30/40 | no | 23 on the first try |
| Leader | 29/40 | no | one grade at 18 was the grader failing to load the photos |
| Magazine | 28/40 | no | 24 before the cover line moved onto the photo |

New facts rules: a gathering shows only when one record of the data holds its day and
hour together; a leader's photo must show them (its description names them or their
role). Labels and secondary ink are forced readable whatever colour the words pick, and
a colour the words leave out is worked out from the page's ground and ink.

Spend for the church layouts: $2.29 (three blueprints at 46 to 53 cents, words and
grading). The test's total is $3.44.

## Wired in (same day)

Kevin: "lets stop on the list and pick back up later. right now make the kit available
for it to be used." `site_composer._run_builder_v2` asks the kit first:
`site_kit.build(ctx, business_id)` reads the real build's context (`fx_from_ctx`),
picks the layout from the approved blueprint, writes the words, assembles, then runs the
builder's own armor (scripts, external links, editability targets) and the page laws
(nav, footer, h1, a working inquiry form posting to the contact endpoint). Any miss, a
layout the kit lacks, or any exception, and it stands down: the builder writes the page
exactly as before. The stored page joins the same seam as a builder page, so overrides,
the judge and the ratchet all apply.

The inquiry form is new to the kit: a JSON post to the platform's contact endpoint, the
one network call a page's script may make, so it passes `builder_v2.armor_scripts`.

`SITE_KIT` = off | owner | on, default owner (the business's owner must be the platform
owner, read the way church_checks does). The kit's files compile on Python 3.11 (the
nested f-strings that needed 3.12 are gone).
