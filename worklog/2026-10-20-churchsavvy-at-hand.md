---
title: ChurchSavvy at hand — song slots in templates, a song or typed words up on the spot
date: 2026-10-20
agent: Claude Code (Claude Opus 5.5)
asked: '"accessing church savvy should already have everything at the hands of those using … create an area called build your sunday … there needs to be direct connections as well … hdmi to projector" (Kevin, 2026-10-20)'
status: in progress
prs: [kmj-intake-server#1518, solutionist-studio#TBD]
migrations: []
left_undone: ["the app: Start here, Build your Sunday with starter templates and Save as my template, Project to a plugged-in screen, Show anything in the booth (solutionist-studio)"]
decisions: ["a song item may be an empty slot (missing: pick); templates and drafts hold them until a song is picked", "on the spot is a passage, a song from the library, or words typed in the booth; each slide must be the kind the screens draw for it"]
related: [kmj-intake-server worklog/2026-10-19-churchsavvy-show.md]
---
Two server rules change, so ChurchSavvy can be picked up and played with:

- A song item's `song_id` may be empty. It compiles as "Pick a song" with `missing: pick`, so starter templates and half-built Sundays can hold song slots.
- `/worship/live`'s on-the-spot slot (`adhoc`) takes a song (lyric slides) or typed words (text slides), as well as a passage. Each slide must be the kind its type draws.

Checks: the show tests, 37 passed (2 new, 1 updated so a verse slide carries its kind, which the real booth always sent).
