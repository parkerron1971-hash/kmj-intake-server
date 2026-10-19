---
title: ChurchSavvy song library — songs, words into slides, the Proclaim import, scripture lookup
date: 2026-10-19
agent: Claude Code (Claude Opus 5.5)
asked: '"add 1-4 to the canvas, then start step 2 from the new adds ... you can begin" (Kevin, 2026-10-19, ChurchSavvy canvas TXrKfJhDkPsXfSsQjhdeoq approved)'
status: in progress
prs: [kmj-intake-server#1508, solutionist-studio#1283, kmj-intake-server#TBD]
migrations: [supabase/APPLY-2026-10-19-worship-songs.sql (applied)]
left_undone: ["the song finder: public-domain hymns, read words from a photo, a SongSelect file", "the Look editor (slide themes for the screens)", "the booth/show app (step 3) — the scripture lookup here has no screen until then", "WORSHIP_SONGS stays owner until Kevin turns it on (a Thursday switch); ChurchSavvy has no Build-lane slot yet"]
decisions: ["words never come from lyric websites: typed, pasted, a SongSelect file, a photo, a hymnal or the church's own Proclaim", "no CCLI SongSelect partner program (Kevin: go without it)", "no kids/nursery alerts on the screens — those go out from the church app only (Kevin)", "a song taken out is archived, not deleted, so a second Proclaim import knows it came over", "WORSHIP_SONGS off|owner|on, default owner, like CHIEF_TONE_NOTES"]
related: [kmj-intake-server academy_slides_router.py (the class-slides engine the screens reuse), solutionist-studio worklog/2026-10-19-churchsavvy-songs.md]
---
Step 2 of ChurchSavvy, the church presentation add-on (Kevin's replacement for Faithlife Proclaim). This PR is the song library under it.

- `worship_lyrics.py` reads a song's words, from pasted text, a SongSelect file or Proclaim's stored words. It turns them into parts (Verse 1, Chorus, Bridge …). It also turns a part into slides at 1-6 lines each, and a blank line always starts a new slide. It strips chord lines and SongSelect's footer, and keeps the title, CCLI number, authors and copyright.
- `worship_proclaim.py` reads a church's own Proclaim files (`FaithlifeMusicManager.db`, `PresentationManager.db`), read-only. It merges the library's words with the words saved on past service items: at Love City, the library alone has words for 11 of 89 songs, and the merge finds 86. It keeps each song's order and how often it was sung each year.
- `worship_scripture.py` turns what a booth volunteer types ("rom 8 28", "ps 23") into verses from `bible_text`. It offers three choices — the verse asked for, one more, the whole chapter — each already broken into slides between verses.
- `worship_router.py` covers status, parse, list/read/add/change/archive a song, a Proclaim import (up to 8 files of 64 MB; running it twice never duplicates; it fills in words for songs that had none), and scripture. Owner, admin or manager changes songs; any seat reads.

Against Love City's real Proclaim data, the import finds 100 songs: 87 with words, 13 without, from 48 services. Before building more here, read the canvas's notes (Round 2/3 boards) and the Proclaim teardown.

Songs are in the account export (`account_lifecycle`, beside devotionals). Checks: 89 pytest (lyrics 27, scripture 20, Proclaim, router), `__tests__/worship_songs_db.mjs` 22 checks on PGlite, the dashboard wiring + setup brief tests (68).

**Fix (after #1508 went live):** the Proclaim import saved each batch of 50 but called it a failure. A `return=minimal` insert answers with an empty body, and `sb_clients` hands that back as `None`, the same value as a refusal. So every import stopped with "Some songs didn't save" after the first 50. The test fake returned `[]` and hid it; the fake now returns what the real helper returns, and that test went red before the fix. The import now asks for the new ids (`?select=id`, `return=representation`) and counts them; a live check against production confirmed both replies. Love City's songs are in its library (100 songs, 87 with words, 13 without, 1 untitled, 81 times sung in 2026), brought over from its own Proclaim copy by the same `_import_rows`.
