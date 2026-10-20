---
title: ChurchSavvy at hand — song and passage slots in templates, a song or typed words up on the spot
date: 2026-10-20
agent: Claude Code (Claude Opus 5.5)
asked: '"accessing church savvy should already have everything at the hands of those using … create an area called build your sunday … there needs to be direct connections as well … hdmi to projector" (Kevin, 2026-10-20)'
status: in progress
prs: [kmj-intake-server#1518, solutionist-studio#1290]
migrations: []
left_undone: []
decisions: ["a song item, and a scripture item, may be an empty slot (missing: pick); starter templates and drafts hold them until one is picked", "on the spot is a passage, a song from the library, or words typed in the booth; each slide must be the kind the screens draw for it"]
related: [kmj-intake-server worklog/2026-10-19-churchsavvy-show.md]
---
Two server rules change, so ChurchSavvy can be picked up and played with:

- A song item's `song_id` may be empty. It compiles as "Pick a song" with `missing: pick`, so starter templates and half-built Sundays can hold song slots. A scripture item's `ref` may be empty the same way ("Pick a passage"); a passage that is typed must still be found.
- `/worship/live`'s on-the-spot slot (`adhoc`) takes a song (lyric slides) or typed words (text slides), as well as a passage. Each slide must be the kind its type draws.

Checks: the show tests, 38 passed (3 new, 1 updated so a verse slide carries its kind, which the real booth always sent); the passage-slot test was red before the change.
