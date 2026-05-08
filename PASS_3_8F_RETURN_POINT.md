# Pass 3.8f (Quality Ceiling) — Return Point

## Purpose

Pass 3.8d shipped the Builder Agent. Output is structurally good but
quality is inconsistent and tends toward conventional layouts. Pass 3.8f
raises the quality ceiling without adding new pipeline steps:

1. **Design primitives library** — 10 strands × 3-5 reference patterns
   each. Builder reads them as inspiration, not templates.
2. **Creative anchors** — Designer Agent picks `signature_moment`,
   `pacing_rhythm`, and `voice_proof_quote`. These flow Designer →
   Brief Expander → Builder as non-negotiable creative directives.
3. **Stronger Builder prompt** — adds great-vs-mediocre examples,
   anti-patterns, strand-specific primitives reference, and the three
   creative anchors.
4. **Quality validator** — six heuristics check Builder output
   (hierarchy, palette discipline, signature moment, voice quote,
   banned section labels, banned CTAs).
5. **One auto-retry** — quality fail triggers a retry with corrective
   guidance. Second-pass quality fail ships the HTML anyway with
   `_quality_warnings` flagged in `site_config`.

## Pre-pass safety

- Branch: `pass-3-8f` (off `main` at `7de5be8`)
- Safety tag: `pre-pass-3-8f-20260507-215451` (pushed to origin)
- Backups in place (.bak files):
  - `studio_designer_agent.py.pre-3-8f.bak`
  - `studio_brief_expander.py.pre-3-8f.bak`
  - `studio_design_brief.py.pre-3-8f.bak`
  - `studio_builder_agent.py.pre-3-8f.bak`
  - `public_site.py.pre-3-8f.bak`

## Files added

- `studio_design_primitives.py` — `HERO_PRIMITIVES_BY_STRAND` (10 strands),
  `SECTION_PACING_PATTERNS` (7 rhythms), accessor helpers.
- `studio_quality_validator.py` — `validate_quality(html, brief)` returns
  `(passes, warnings)`.

## Files modified

- `studio_designer_agent.py`
  - `build_director_prompt()` — JSON deliverable schema gains
    `signature_moment`, `pacing_rhythm`, `voice_proof_quote`. Decision
    rules expanded.
  - `_validate_recommendation()` — accepts new fields; pacing_rhythm
    must be one of the 7 known IDs.
  - `cold_start_recommendation()` — populates the 3 fields with
    deterministic defaults (`voice_proof_quote=""` since cold-start
    has no voice signal).
- `studio_design_brief.py`
  - `DesignBrief` TypedDict — adds 4 optional fields
    (`signature_moment`, `pacing_rhythm`, `voice_proof_quote`,
    `_quality_warnings`).
  - `validate_design_brief()` — soft-warns on bad new field shapes;
    never fails because of them.
  - `get_default_brief()` — pulls new fields from recommendation with
    safe fallbacks.
- `studio_brief_expander.py`
  - `_build_expander_prompt()` — adds CREATIVE ANCHORS section that
    threads the 3 fields into the LLM prompt.
  - `_post_process_brief()` — backfills the 3 fields onto the brief
    from the recommendation if the LLM omitted them.
- `studio_builder_agent.py`
  - `_build_builder_prompt()` — adds great-vs-mediocre examples,
    anti-patterns, strand-specific primitives reference block, and a
    creative-anchors directive block. New RULES + design step 0.
  - `build_html()` — restructured as a 2-attempt loop. Quality fail on
    first attempt triggers a retry with appended corrective guidance.
    Second-pass fail ships HTML with `quality_warnings` populated.
- `public_site.py`
  - `_run_builder_job()` — persists `quality_warnings` to site_config
    on success-with-warnings path; pops it on clean success.
  - `/decoration-status` — surfaces `quality_warnings`.

## Cooldown

Existing 60 s cooldown unchanged. Retry happens inside one Builder
invocation, so it doesn't bypass the cooldown.

## Out of scope (deferred)

- New endpoints
- Frontend UI changes
- Builder model change (still Claude Opus)
- Per-page generation (still home only)

## Rollback

```bash
git checkout main
git reset --hard pre-pass-3-8f-20260507-215451
```
