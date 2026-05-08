# Design Intelligence Modules

This directory holds the **Design Intelligence Modules** — the "design
brains" that the Director Agent (Pass 4.0b) consults when critiquing
or refining a generated site.

Each module is **one markdown file** containing the full design narrative
for a particular strand combination at a particular ratio band. The
modules are deliberately verbose: their narrative depth is the value
the Director Agent reads as LLM context, and their explicit measurable
rules are what the rubric-based critique scores against.

## How modules are matched to a site

The Designer Agent picks a strand pair + ratio (e.g. `editorial 60% /
bold 40%`). `__init__.find_module_for_strands(strand_a, strand_b,
ratio_a)` walks the `MODULE_REGISTRY` and returns the first module
whose `matches_strands` band covers that pick. The Director Agent
loads that module's full markdown into its critique context.

When no module matches, the Director Agent skips module-driven
critique for that site (Builder output is shipped as-is — no
regression vs. pre-4.0a behavior).

## Adding a new module

1. Drop a new `<id>_intelligence.md` file in this directory.
2. Add a registry entry in `__init__.py` with:
   - `filename`
   - `name` (human-readable)
   - `tagline` (one-line elevator pitch)
   - `matches_strands` (list of `(strand_a, strand_b, min_ratio_a, max_ratio_a)` tuples)
   - `canonical_example` (URL or business slug of the reference build)

Modules planned for future passes (placeholders, not yet implemented):
`cathedral`, `pulpit`, `atelier`, `trader_floor`, `field_manual`,
`studio_brut`.

## Pass 4.0a status

- `cinematic_authority_intelligence.md` — Module #1, sourced from
  the Embrace the Shift case-study document. Matches `editorial+bold`
  at 50–70% ratio (and adjacent `editorial+luxury` / `editorial+dark`
  bands as close-enough fallbacks).
