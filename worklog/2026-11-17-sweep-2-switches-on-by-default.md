---
title: Sweep 2 - switches that were on only through Railway are on by the code's own default
date: 2026-11-17
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin approved Sweep 2 of the settings cleanup: make 'on' the code's default for the switches Railway turns on, keep each one as an off switch, then delete the Railway entries"
status: in review
prs: [kmj-intake-server#1884, kmj-intake-server#1886, kmj-intake-server#1885, kmj-intake-server#PR_MONEY, "kmj-intake-server#PR_PFM (draft, held for Kevin)"]
migrations: []
left_undone:
  - "Kevin deletes the Railway entries for these switches once the PRs are live (web and worker). Nothing here touched Railway."
  - "POST_FOR_ME_PILOT_BUSINESSES (draft PR, held): the worker has no value for it, so today the worker's marketing sender claims nothing and every tenant's scheduled desk post waits. Making unset mean every business starts those sends on the worker the moment it deploys, and the claim RPC turns approved posts whose six-hour window has closed into failed. That changes behavior, so it waits for Kevin. Until it merges, keep POST_FOR_ME_PILOT_BUSINESSES=* on web."
  - "About 30 one-line comments still call a gate 'dormant behind BILLING_ENFORCE'; only the feature_gates, billing_limits and pricing_config docstrings were corrected here."
decisions:
  - "One rule for every switch: (env or 'on').strip().lower() not in ('off', '0', 'false', 'no'), as CHIEF_KEEP_WARM and CACHE_DIAGNOSTICS already do. An empty value counts as unset."
  - "Business lists (CLIP_FINDER_BUSINESSES, and POST_FOR_ME_PILOT_BUSINESSES in the held PR): unset or empty is '*'; a list still limits; a value that names no business (e.g. 'off') is nobody."
  - "BUILDER_LOOP_MAX_TOOLS defaults to 1 (production's value; was 8)."
  - "Unit tests keep BUILDER_V2_LOOP, CHIEF_BUILDS, CHIEF_DURABLE_EVENTS and BILLING_ENFORCE off through conftest: hundreds of tests fake the tables they were written against, and with these on they failed on a model call, a build-job read, a delivery lease or a 402, not on what they test. Each switch has a test that unsets it and pins the new default. Tests that cleared BILLING_ENFORCE to mean off now set it off (28 places)."
  - "scripts/chief_turn_eval.py runs outside pytest, so its harness gives the fixture business an empty build-job list and runs with billing off (the eval measures Chief's answers, as it did before)."
related: []
---
Sweep 2 of the settings audit (2026-11-16). Each switch below was on in
production only because a Railway variable said so; the code defaulted to off
or to an empty list. These PRs make on the code's default, so the Railway
entries can be deleted with no change in behavior. Every switch still turns
its feature off with `=off`.

- Sites (#1884): SITE_BUILDER_V2, SITE_CANVAS, BUILDER_V2_LOOP, DRO_DIRECTIONS,
  BUILDER_LOOP_MAX_TOOLS=1. DRO_DIRECTIONS_PARALLEL unchanged.
- Chief (#1886): CHIEF_BUILDS, CHIEF_DURABLE_EVENTS.
- Media (#1885): MEDIA_PROCESSING, VIDEO_STUDIO_ENABLED, VIDEO_RENDER_ENABLED,
  CLIP_FINDER, CLIP_FINDER_BUSINESSES (unset = every business; CLIPPER_URL and
  CLIPPER_TOKEN still required).
- Money, marketing, academy (this PR): BILLING_ENFORCE (feature_gates and the
  health dict in kmj_intake_automation), BUFFER_PUBLISHING (BUFFER_API_KEY still
  required), ACADEMY_CLASSROOM_V2.

Worker drift found on the way (railway variables, switch values only): the
worker has no BUILDER_V2_LOOP, DRO_DIRECTIONS, BUILDER_LOOP_MAX_TOOLS,
ACADEMY_CLASSROOM_V2 or POST_FOR_ME_PILOT_BUSINESSES. The first four now match
web by default; the last is the held PR above.
