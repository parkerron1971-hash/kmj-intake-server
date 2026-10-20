---
title: ChurchSavvy — the confidence screen's notes and settings (server)
date: 2026-10-20
agent: Claude Code (Claude Opus 5.5)
asked: '"also confidence screen. make sure that that is function as well" and "have where people put the notes down the timer is still showing on confidence screen" then "these are a go" (Kevin, 2026-10-20; canvas board 33)'
status: in progress
prs: [kmj-intake-server#1529]
migrations: [supabase/APPLY-2026-10-20-worship-stage.sql]
left_undone: ["the confidence screen itself and its setup (solutionist-studio, next PR)"]
decisions: ["notes for the stage live on each item (`stage`) and on each point of a sermon's slides (`notes`); the booth's own notes stay separate and never reach a screen", "only a stage screen's link gets the stage notes; the room, stream, LED wall and lobby never do", "a stage screen's settings sit in their own column (jsonb, at most 1000 bytes), filled with defaults on the way out so an older screen reads like a new one", "the column goes in before the code that selects it deploys"]
related: [kmj-intake-server worklog/2026-10-20-churchsavvy-passage-editor-server.md]
---
Step 4 of the approved round-4 ChurchSavvy build, server side: what the confidence screen (canvas board 33) needs.

- **Every item** can carry a note **for the stage** (`stage`, up to 500 characters): "key change into verse 4". **Each point** of a sermon's slides can carry the pastor's **notes** (up to 1000). Both are compiled into the show.
- **A screen's link** (`/worship/screen/{token}/show`) never gets the booth's notes. Only a **stage** screen gets the stage notes and the points' notes; every other screen loses them on the way out.
- **A stage screen keeps its settings** (`worship_show.clean_stage`, the new `worship_screens.stage` column):
  - its layout: auto, band, pastor, notes or countdown;
  - what it shows: the words now, next, notes, clock, timer, booth message, the song's parts, key and position, a picture of the big screen;
  - how big the words are.
  Defaults fill anything left out, and every refusal is in plain words.

**Migration:** `supabase/APPLY-2026-10-20-worship-stage.sql` adds one jsonb column with a default and a shape check. It's additive and safe to run twice, and it is applied before this code deploys.

**Checks:**
- `test_worship_show.py`, `test_worship_show_router.py`, `test_worship_scripture.py` and `test_worship_router.py` pass (90). They now cover stage notes on items and points, the settings and their refusals, a stage screen getting the notes, and other screens not getting them.
- `worship_show_db.mjs` passes (36 checks): the migration runs twice, an existing screen gets `{}`, and an array or an oversized object is refused.
