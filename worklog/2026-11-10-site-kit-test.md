---
title: The kit test, pages assembled from finished sections
date: 2026-11-10
agent: Claude Code (Claude Opus 5.5)
asked: "go, fix the two gaps first and make it happen"
status: waiting on Kevin
prs: [kmj-intake-server#1788]
migrations: []
left_undone:
  - "Nothing is wired in: no owner's build uses the kit. Wiring it means the builder's ladder trying the kit first for the Booking desk, behind a switch, off by default."
  - "One layout so far (the Booking desk). The other 16 need their own finished sections; each one is design work, not model spend."
  - "Pages with no photos are the weak spot: the food truck's first screen scored 7 of 10 every round, and the grader's first note was always 'add real photography'."
  - "The custom section path works (safe every time, about 8 cents, about 20 seconds) but its layouts came out lopsided twice. A menu card is common enough to be a kit section instead."
  - "Seven nested f-strings in site_kit.py need Python 3.12 (CI is 3.12); tidy them before production imports it."
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
