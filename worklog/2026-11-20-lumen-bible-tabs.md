---
title: Member app Look 5.1 — the Bible tab opens straight into reading, Read · Devotional · Plans · Saved on top
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin approved Look 5.1 ("this is awesome. much better design. lets build this including the new still to build!") and, on the Bible: "when someone click bible the bible should open directly with devotional tabs at the top or a nice home page." Helper F of seven: the Bible tab.'
status: shipped
prs: [kmj-intake-server — Look 5.1 Bible tabs]
migrations: []
left_undone:
  - "The mock's 'Listen to this chapter' had no server voice to reuse (only a devotional's day has one, devotional_voice). Listen here is the phone's own voice (speechSynthesis, as the kids' space already does): verse by verse from the verse you tapped, the one being read underlined, stopped when you leave; free, nothing sent anywhere, and the button shows only on a phone that can speak (headless WebKit can't, so it hides there). It isn't a media element, so the mini-player doesn't carry it."
  - "The mock's book heading 'THE GOSPEL OF JOHN' needs long book titles the Bible data doesn't have; the heading is the book's name ('JOHN', 'PSALMS') rather than invented titles."
  - "The mock's Saved row 'from Sunday's message' needs to know where a highlight was made; marks don't keep that, so a row says when ('highlighted Tuesday') and shows the member's own note."
  - "No church setting picks a first chapter. Someone who has read nothing yet starts at today's reading of the church's plan (settings.reading_plan, with a line saying so), else John 1."
  - "The Devotional dot on a chapter page (prev/next, a sermon's link) comes from a cookie the Bible tab keeps for the day, so it reads nothing. Opening a devotional's day clears it and the next tab asks again; a day read on another phone shows here once a tab is opened. A chapter page opened before any tab that day shows no dot."
  - "The plan rows' 'about N minutes' are the words of the day's reading at 170 a minute (the devotional's own pace, devotionals.minutes), worked out from the Bible text on the server; nothing is stored."
  - "Not checked on a real phone: Playwright Chromium and WebKit, 390x844 @2x, light and dark. Headless Chromium stops painting after any link tap from a Lumen page with motion on (main's view transitions, on main too), so the browser flows run with reduced motion."
decisions:
  - "Real addresses, no script needed: /my/bible is Read (the reader at the chapter read last, from the sol_bible cookie), /my/bible?tab=devotional|plans|saved|search the others; every old address works (/my/bible/<book>/<n> is Read at that chapter; /books, /notes, /plans, /reading, ?q= as they were). With script, switching tabs replaces the page in the history, so Back leaves the Bible instead of walking back through its tabs; tapping the tab you're on goes to the top."
  - "The segmented control is the page's (helper A owns the bars): sticky right under whatever top bar the shell draws (its height measured on the phone; a CSS place before that), with the search button beside it and, on Read, the reader's line of how far you've read along its lower edge. The tab bar stays while reading."
  - "Read keeps every reader feature: highlights (five colours), notes, Save, Copy, Make a card, versions, Aa (size and font; the translation is its own pill now, a <details> that opens without script), night via lm_night on top of the member's Look (#1981), the line of how far, the ink sweep. The chapter's number is in the church's colour, the book in small capitals, verse numbers quiet. The previous and next chapters are two buttons at the end (no longer floating, since the tab bar is there)."
  - "The verse bar: the verse, Share (the shared sheet's .lm-share, kind=verse, data-share-from=reader so the sheet reads the tapped verse; data-share-id BOOK.CH.V, -text and -tr kept on it too), close; the five highlighters; Note, Copy, Save, Make a card. It sits just above the tab bar (measured). Without the sheet's script, Share falls back to the phone's own share, as the old dock did."
  - "Devotional: member_lumen_devotional's green card with its fallbacks; This week, Monday to Sunday, a circle a day from real progress (read filled, today ringed, ahead plain, a day outside the devotional an empty place; open days are links); the verse of the day on the ivory card with Share (kind=verse, href '/', id like LAM.3.22-23); More devotionals: the church's others you can read now (not the one on top, not one still to come), the church's picture for each or a flat cover."
  - "Plans: the plans running for this member as 64px rings ('With your church · day 12' / 'The Gospels · day 5', Today: the reading, about N minutes, Read), a finished own plan quietly; then the plans not started, each a one-tap Start through today's POST /my/bible/plans/start (its letter square in a family colour)."
  - "Saved: highlights, notes and saved verses, newest first (the newest 40; all of them on /my/bible/notes): the colour bar, the verse, the note, 'John 1:14 · highlighted Tuesday', each opening the reader at that verse. Empty, preview and failed states are said."
  - "Reads: each tab reads only what it shows, every read one today's Bible tab already makes: Read the chapter's marks (plus the devotionals' catalog, starts and days for the dot only when its cookie holds nothing for today); Devotional the catalog, starts, days, and one devotional's days (the one on top, when running); Plans starts and the church plan's ticks; Saved the marks; Search nothing. A chapter page reads what today's reader reads. No migrations; the dot is a cookie (lm_dv, path /my, HttpOnly, Secure, Lax, two days), written only under the new look."
  - "Off is today's: with MEMBER_LUMEN=off every page × scene dump is identical to main's (Bible 325, Home 656), also with Ana's look Dark; ?tab= addresses are today's Bible tab byte for byte and write no cookie."
  - "CSS in the Bible's own block (member_lumen_bible.CSS, already in member_lumen_ui.templates() before the type block): tokens only (the devotional's green/mint and the highlighters are fixed colours with dark twins), every rule under body.lm, transitions only when the phone allows motion."
related: [2026-11-19-lumen-next-devotional.md, 2026-11-19-lumen-next-bible-classes.md, 2026-11-20-lumen-dark-light.md]
---
`member_portal_bible.serve` hands /my/bible to `_lumen_tab` under the new
look (Read, Devotional, Plans, Saved, Search; each gathers only its own
reads) and `member_lumen_bible` draws them: `seg()`, `render_chapter()` (Read),
`render_devotional()`, `render_plans_tab()`, `render_saved()`, `render_find()`.
The old "The Word" page (`render_home` and its rail, plan grid and marks
strip) is gone; `/my/bible/plans` keeps the full plans & devotionals library.

**Reads per page** (the Bible harness over the test fake, warm, switch on):

| Page | Main | Branch, dot asked | Branch, dot kept today |
|---|---|---|---|
| /my/bible | 8 | 4 | 1 |
| ?tab=devotional | 8 (same page) | 3 (+1 in production: the day's text) | 3 |
| ?tab=plans | 8 | 4 | 2 |
| ?tab=saved | 8 | 4 | 1 |
| ?tab=search, ?q= miss | 8 | 0 | 0 |
| /my/bible/john/1 | 1 | 1 | 1 |

**Server-Timing** (median of 30 warm requests, switch on, main / branch):
Bible tab 9.2 / 7.0 ms (5.7 with the dot kept), Devotional 8.8 / 6.3,
Plans 8.1 / 6.8, Saved 9.5 / 6.3, Search 8.0 / 4.0, Reader 6.0 / 5.1, a
devotional's day 5.2 / 4.9. The plans' minutes a day are worked out once per
server copy and translation (27 ms).

**Tests.** `__tests__/test_member_lumen_bible_tabs.py` (30) and the Bible,
devotional and dark tests moved to the tabs. Rehearsed: the dot on the
Devotional tab itself, the Read tab ignoring its kept dot, a day not
clearing it, tabs pushing the history, More devotionals keeping one to
come, off mode reading ?tab=, a verse share losing its story id: each went
red.
