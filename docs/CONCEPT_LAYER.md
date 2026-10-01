# The concept layer

How the site builder decides what a site is *about*, how far that idea
goes, and what holds it on the page. Built 2026-10-01 from the
liaisongraphics.com study ("The Concept Layer" plan artifact:
https://claude.ai/artifact/8PNdhnMp1g3z1Tx4AQ3V6P).

## The idea

A design language (`design_languages.py`) decides how a site **looks**.
A concept decides what it is **about**: one sentence the whole page obeys,
taken from the business's own world and grounded in true facts ("the
course is a college semester" for a real five-week cohort; "the shop is a
take-a-number counter" for a walk-in barbershop). The concept sets the
words, the objects and the photo list. The language still owns colour,
type and layout. Any language can carry any concept.

## The dial (Kevin's rulings, 2026-10-01)

| Setting | What it means | Default for |
|---|---|---|
| plain | No concept. Nothing renamed, no objects. | Health, legal, finance, therapy (`site_concept.default_intensity`) |
| signature | One object carries one moment; two renamed labels at most. | Everyone else |
| world | The idea runs the page: vocabulary, objects, a living detail. | Only when the owner picks it |

World lives on **one offer page** by default (a course, a cohort, a
launch) and across the whole site only on request. The owner sees the
settings as four cards in the Design Coach (`plain`, `signature`,
`world-offer`, `world-site`), each with a one-line pitch written for their
business, and chooses. Their tap is saved as `taste.concept` (plus
`concept_idea`, `concept_offer`) and binds the build, owner first.

Off switch: `SITE_CONCEPT=off` (every site builds plain).

## The pieces

- `site_concept.py` resolves the dial (`resolve`, `attach`), writes THE
  CONCEPT block for the Director (`brief_block`), carries THE CONCEPT LAW
  (`DIRECTOR_LAW`), reads the blueprint's section 0 (`parse_sheet`,
  `vocabulary_pairs`) and holds the built page to it (`check_page`).
- `site_objects.py` is the object library: sixteen hand-built objects
  (letter, seal, ID card, ticket, receipt, session card, frame, marker,
  letterboard, certificate, index card, instant photo, boarding pass,
  typed caption, installments, shaped edge). The Director sees the
  catalog (`director_block`); the builder receives exactly the objects a
  blueprint's `OBJECTS:` line names (`object_names_in`, `builder_block`).
  Every object reads seven `--obj-*` tokens, carries a phone version and a
  reduced-motion state, and keeps its text real.
- `spec_author.py` teaches the law and the catalog, and the blueprint
  anatomy gains `0. THE CONCEPT` (always) and `6. THE OFFER PAGE` (when
  SCOPE is offer).
- `builder_v2.py` rule 17 teaches the page to obey section 0; the concept
  checks ride the soft tier (a repair round, never the fallback).
- `craft_laws.py` is the craft floor every site gets, concept or not.

## The sheet (section 0 of every blueprint)

```
INTENSITY: plain | signature | world
SCOPE: site | offer (and the offer's name)
IDEA: the one sentence
GROUNDED IN: the true facts it rests on
VOCABULARY: plain word -> in-world word | ...
OBJECTS: library keys with a finish, e.g. ticket (paper), seal (metal)
MARKS: two or three recurring marks
LIVING DETAIL: the one thing that moves
PHOTO LIST: what the owner should photograph, one shot per item
STAYS PLAIN: what deliberately does not wear the concept
```

The plain-word rule: every in-world label keeps its plain word beside it
(visible beneath, or in the link's aria-label). A concept never hides what
a thing is or what it costs, and the generosity rule still holds: a World
page renames and reorders, it never leaves a function out.

## Reviewing it for free

```
python scripts/site_bench.py director --fixture scripts/fixtures/marrow_and_steel.json
python scripts/site_bench.py objects --shoot --out bench_out
python scripts/site_bench.py validate --fixture ... --spec blueprint.txt page.html
```
