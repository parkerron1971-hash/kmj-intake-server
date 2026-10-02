# The concept layer

How the site builder decides what a site is *about*, how far that idea
goes, what holds it on the page, and how the page is checked. Built
2026-10-01 from the liaisongraphics.com study ("The Concept Layer" plan
and its "What shipped" record:
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

## The pieces

| Module | What it does |
|---|---|
| `site_concept.py` | Resolves the dial, writes THE CONCEPT block and THE CONCEPT LAW for the Director, parses section 0, holds the built page to it (`check_page`), and feeds the Director the platform's recent concepts so none repeats (`recent_concepts`). |
| `site_objects.py` | Sixteen hand-built objects (letter, seal, ID card, ticket, receipt, session card, frame, marker, letterboard, certificate, index card, instant photo, boarding pass, typed caption, installments, shaped edge). The Director sees the catalog; the builder gets exactly the objects a blueprint's `OBJECTS:` line names. Seven `--obj-*` tokens, four finishes, a phone version and a still state each. |
| `design_languages.OBJECT_FINISH` | Each language's default finish (paper, inverse, glow, metal) and how its objects should feel; the Director reads it in THE DESIGN LANGUAGE block. Inverse belongs on a light ground only. |
| `craft_laws.py` | The craft floor every site gets: one h1, alt text, three type families at most, likely typos, a typographer pass, and render checks (phone text, centered paragraphs, control fonts, a visible headline). |
| `site_pages.py` | Cuts About / Services / Contact from the builder's own home page; names, links and checks the World offer page. |
| `site_photo_list.py` | Turns empty photo slots plus the concept's photo list into one "Photos for your site" task. |
| `spec_author.py` | Teaches the law and the catalog; the blueprint opens with `0. THE CONCEPT` and adds `6. THE OFFER PAGE` when the scope is an offer. |
| `builder_v2.py` | Rules 16 (type floor) and 17 (concept); named moves and objects arrive with their source; measures its own render; the designer's review rebuilds only the sections that need it (`plan_vision_repair`, `splice_section`); `page="offer"` builds the offer page. |

Every check above rides the **soft tier**: it earns a repair round and
never sends a build to the fallback engine.

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
a thing is or what it costs, and the generosity rule still holds.
Decorative numbers (ticket serials, card numbers) stay one or two digits,
because the truth law reads any longer number as a claim.

## The offer page

When the approved blueprint says `INTENSITY: world` with `SCOPE: offer`:

1. `compose_site` names the page before the home is built
   (`site_pages.offer_path`, never a path the platform serves); the home's
   real data tells it to link there.
2. After the home is live, `build_offer_page` runs `builder_v2` once more
   with `page="offer"`, wearing the home's house style, and saves it as
   `generated_pages["offer"]` with `site_config.offer_page` `{path, name,
   built_at, html_base}`.
3. Its edit keys are `v2o/…` (the home's are `v2/…`), so an Edit Mode change
   on one page never lands on the other. Edits are applied over
   `html_base` at build and on every refresh (`refresh_offer_page`).
4. `public_site` serves it at its path, lists it in the sitemap and
   previews it at `/public/site/{slug}/offer`; the Studio names it for the
   offer; `site_check` looks at it.
5. A later blueprint without an offer scope removes it. It costs one extra
   builder run, only for owners who pick it.

## Switches

- `SITE_CONCEPT=off`: every site builds plain.
- `SITE_OFFER_PAGE=off`: no offer pages are built.

## Reviewing it for free

```
python scripts/site_bench.py director --fixture scripts/fixtures/marrow_and_steel.json   # Signature
python scripts/site_bench.py director --fixture scripts/fixtures/calm_counsel.json        # Plain
python scripts/site_bench.py director --fixture scripts/fixtures/wheelhouse_course.json   # World, offer page
python scripts/site_bench.py objects --shoot --out bench_out                              # all objects, all eleven languages
python scripts/site_bench.py validate --fixture ... --spec blueprint.txt page.html        # laws + craft + concept
```

The first zero-spend proof (Marrow & Steel at World) found two places the
library tripped the builder's own laws: a `*-slot` class reads as a photo
stand-in, and a 3+ digit serial reads as a claim. Tests now pin both for
every object.
