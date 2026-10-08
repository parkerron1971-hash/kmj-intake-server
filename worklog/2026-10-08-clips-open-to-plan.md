---
title: Find my best clips is offered by plan, not by a pilot list
date: 2026-10-08
agent: Claude Code (Claude Opus 5.5)
asked: "push so this can be accesible for the offer. make sure things are added so we can close this out asap."
status: in progress
prs: [kmj-intake-server clips-open-to-plan, solutionist-studio clips-open-to-plan]
migrations: []
left_undone: ["After merge: CLIP_FINDER_BUSINESSES=* on kmj-intake-server (web) and kmj-intake-worker", "Kevin: a first real clip post to a test account; a spending limit on the clip service's OpenRouter key", "Speed: ~18 min per recording hour on Railway"]
decisions: ["available = enabled AND plan_allows (the same require_feature rule that gates starting a run; fails open on billing lookup errors)", "locked = enabled but not on the plan, so the app can say what it comes with", "Uploads are refused (403) when neither the hand cutter nor Find my best clips could use the recording"]
related: [2026-10-05-find-best-clips-backend.md, 2026-10-05-announce-find-my-best-clips.md]
---
Find my best clips is sold on the Solutionist plan (announced 10/05), but the
pilot switch still named only KMJ. Opening the switch to `*` alone would have
offered every business a button that 402s, so `configuration()` now reports
`available` only when the business's plan includes `ai_clips`, plus `locked`
and `required_plan` for the app's "comes with the Solutionist plan" note.
`start_upload` refuses when nothing could use the recording. 341 tests across
the clip, cover, posting, marketing-clips, media and pricing suites pass.
