---
title: Find my best clips is offered by plan, not by a pilot list
date: 2026-10-08
agent: Claude Code (Claude Opus 5.5)
asked: "push so this can be accesible for the offer. make sure things are added so we can close this out asap."
status: in progress
prs: [kmj-intake-server#1351, solutionist-studio#1175]
migrations: []
left_undone: ["After merge: CLIP_FINDER_BUSINESSES=* on kmj-intake-server (web) and kmj-intake-worker", "Kevin: a first real clip post to a test account; a spending limit on the clip service's OpenRouter key", "Speed: ~18 min per recording hour on Railway"]
decisions: ["available = enabled AND plan_allows (the same require_feature rule that gates starting a run; fails open on billing lookup errors)", "locked = enabled but not on the plan, so the app can say what it comes with", "Uploads that nothing could use are refused: 402 feature_locked when the switch is on but the plan is missing (the app shows its upgrade answer), 403 when nothing is switched on (web has ffmpeg + MEDIA_PROCESSING=on, so hand cutting keeps every plan uploading)", "required_plan is read from FEATURE_MIN_PLAN through PLAN_DISPLAY so the note names the plan the gate requires"]
related: [2026-10-05-find-best-clips-backend.md, 2026-10-05-announce-find-my-best-clips.md]
---
Find my best clips is sold on the Solutionist plan (announced 10/05), but the
pilot switch still named only KMJ. Opening the switch to `*` alone would have
offered every business a button that 402s, so `configuration()` now reports
`available` only when the business's plan includes `ai_clips`, plus `locked`
and `required_plan` for the app's "comes with the Solutionist plan" note.
`start_upload` refuses when nothing could use the recording: the standard 402
upgrade answer for a business on the wrong plan, a 403 when nothing is switched
on. 344 tests across the clip, cover, posting, Chief-post, marketing-clips,
media, feature-gate and no-plan suites pass.
