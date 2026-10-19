---
title: Member app round three, part 3 - the Bible rebuilt (Old Testament first book picker, highlights, private notes, search)
date: 2026-10-19
agent: Claude Code (Claude Opus 5.5)
asked: '"the choice of what book of bible needs a better flow a mixed of how the bible app looks when selecting book of the bible . also old testament comes before new testment. and the ability to highlight and take notes."'
status: shipped
prs: [kmj-intake-server#1504]
migrations: [supabase/APPLY-2026-10-19-bible-marks.sql (applied to production 2026-10-19 before this PR; rollback probe upserted, merged and refused a bad colour)]
left_undone: ["the frontend What's New entry for the Bible (its own small PR)", "part 4: the church's own devotionals (written in Solutionist), a member starting a plan of their own, the devotional day page, and the devotional row on Home's Today card", "a Listen button on a devotional costs voice minutes: ask Kevin before building it"]
decisions: ["notes are private to the member: server-only table, no staff read anywhere, and the page says so", "a member's marks never go in the church's business export (account_lifecycle.EXPORT_EXCLUDED), since a downloaded export would let staff read private notes; they cascade away with the member and with the business", "a mark belongs to the verse, not the translation (KJV and WEB number verses the same), so switching translation keeps it", "five fixed highlight colours (gold, pink, teal, violet, coral) that never take the church's colour, so a member's colours mean the same thing in every church", "a preview never reads or writes a member's marks; it says marks are private instead", "search covers the whole translation and lists the first 50 verses in the Bible's order; a reference typed into the same box still opens the passage", "the last five chapters read live in the sol_bible cookie (no table): Home's chips and Keep reading"]
related: [kmj-intake-server worklog/2026-10-19-member-app-colour-family.md, kmj-intake-server worklog/2026-10-19-member-app-pictures.md, canvas https://claude.ai/artifact/WzjBoY73aPBUkwy1PsEArU (boards 6-9)]
---
The member app's Bible, rebuilt to the approved canvas.

- `/my/bible` has one box that takes a passage or a word, chips for the last chapters read, Keep reading, the church's reading plan, the member's Highlights & notes, and two book cards (Old Testament first).
- `/my/bible/books?t=ot|nt` is the book picker. It has Old/New Testament tabs, a filter box, and the books in their groups (`bible_text.GROUPS`: The Law, History, Poetry & Wisdom, Major and Minor Prophets, The Gospels, The early church, Paul's letters, Letters to everyone, Prophecy), each with its own colour. A book opens to its chapter grid. `/my/bible/<book>` is the picker, open at that book.
- `/my/bible/<book>/<ch>` is the reader:
  - the chapter's name opens the picker
  - the Aa panel sets text size and font, remembered on the phone
  - tapping a verse opens a dock: five highlight colours, a private note, copy, share, save
- `/my/bible/notes` lists highlights, notes and saved verses (Today, This week, Earlier), filtered by kind and by colour.
- `POST /my/bible/mark` (`member_bible_marks.py`) saves a change:
  - it checks the verse exists in the translation
  - it merges into the member's row and drops the row when nothing is left
  - it refuses a preview (403), a signed-out request (401), another origin, and more than its rate limit

Checks:
- `__tests__/test_member_bible_marks.py` and the updated `__tests__/test_member_portal_bible.py`: 18 tests, 390 with the rest of the member and Bible tests.
- `__tests__/bible_marks_db.mjs` (in CI) runs the migration on a real Postgres: 17 checks. Rehearsed by taking the colour rule out: it went red.
- The dock was driven in a browser at phone width with the save route faked: 24 checks.
  - This found the tab bar sitting over the dock's buttons. The dock was inside the page's stacking layer; it now moves to the page's top level.
  - It also found a verse low on the screen hidden under the dock; the page now scrolls it clear.
