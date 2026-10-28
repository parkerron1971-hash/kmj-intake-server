---
title: ChurchSavvy — loops and a church's own quick screens (server)
date: 2026-10-20
agent: Claude Code (Claude Opus 5.5)
asked: '"include pre/post-service loops and own quick screens in the rebuild" ("yes to all", Kevin 2026-10-20) then "these are a go" (canvas board 29)'
status: in progress
prs: [kmj-intake-server#1531]
migrations: []
left_undone: ["the loop's player on every screen and the quick screens in the booth (solutionist-studio, next PR)", "a loop slide for the church's logo (the booth's Logo already shows it)", "\"Add this week's events\" to a loop: needs events to read from"]
decisions: ["a loop is an item of its own kind: pictures, videos or a few words, each with its own seconds (3 to 120), ended by a press or by a time; each screen plays it on its own clock from when it went up, so every screen shows the same slide", "a church's quick screens live in its look (up to 8): a few words or a picture, with its own key; C, L and B stay the booth's Clear, Logo and Black", "a quick screen goes up on the spot, so a picture can now go up on the spot too (https only)"]
related: [kmj-intake-server worklog/2026-10-20-churchsavvy-confidence-server.md]
---
Step 6 of the approved round-4 ChurchSavvy build (canvas board 29), server side.

**Loops:** a new item kind, `loop` (`_clean_loop`).
- Up to 40 slides: pictures, videos or a few words, each with its own seconds (3 to 120) and a default for the rest.
- It plays until a press, or until a time on the clock, and can shuffle.
- Compiled, each slide carries its `seconds` and the item carries `loop {seconds, until, until_at, shuffle}`.

**Quick screens:** the look keeps the church's own (`clean_quick`), up to 8.
- Each is a few words or a picture, with a name and its own key. C, L and B are taken by Clear, Logo and Black.
- A picture can now go up on the spot (`adhoc.kind = "image"`), with https links only.

**Checks:** the four worship suites pass (98). The new pins cover a loop compiled with its seconds, eight loop refusals, quick screens kept and refused, and a picture on the spot with a bad link refused.
