---
title: ChurchSavvy song finder — SongSelect .usr and ChordPro files read into parts
date: 2026-10-20
agent: Claude Code (Claude Opus 5.5)
asked: '"keep going with step 2 I want the entire thing built" (Kevin, 2026-10-19); then "I believe you are getting block … Output blocked by content filtering policy so you have to figure something else out" (2026-10-20)'
status: in progress
prs: [kmj-intake-server#TBD]
migrations: []
left_undone: ["the Find a song page in the app (solutionist-studio): the library first, then a photo, a file or pasting", "ChurchSavvy on its own (standalone front door)"]
decisions: ["NO built-in hymnal: an agent typing out song words, public domain or not, gets its output blocked; old hymns come in like every song does (a photo of the church's own hymnal page, a file, pasting) with Public domain ticked", "photos are read in the browser (Tesseract), not by an AI model: nothing generates the words, so nothing blocks them, and a photo costs nothing", "tests carry placeholder lines only, never a real song's words"]
related: [kmj-intake-server worklog/2026-10-19-churchsavvy-songs.md, solutionist-studio worklog/2026-10-19-churchsavvy-songs.md]
---
`worship_lyrics.parse_lyrics` now also reads two file formats churches already have, so `/worship/parse` and Add a song take them as they come:

- **SongSelect `.usr`**: key=value lines, where Fields and Words split their parts on `/t` and lines on `/n`. The title, the CCLI number (from `[S A…]`), the authors and the copyright become the song's facts.
- **ChordPro**: `{title}` / `{artist}` / `{ccli}` / `{copyright}` directives; start/end of verse, chorus and bridge; `{comment: Bridge}`; and `[G]` chords stripped from inside the lines.

A chart is recognized only by ChordPro's own directives, so a pasted `{Chorus}` marker still reads as plain words.

Checks: 4 new tests (placeholder words only), plus the parser and Proclaim tests, 37 passed.
