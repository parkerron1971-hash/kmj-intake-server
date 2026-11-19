---
title: Member app new look (Lumen) — the Bible, its reader and plans, and Classes
date: 2026-11-18
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin on the member app Bible: it "seems all over the place and doesn''t feel like a bible app ... needs more organization and feel of a top tier bible app"; on Classes: it "doesn''t feel like an academy feel". He approved the "clean Lumen" mock (version 29, accent level 2): its BIBLE, READER and CLASSES views.'
status: shipped
prs: [kmj-intake-server#1960]
migrations: []
left_undone:
  - "A devotional's page and its day keep today's markup under Lumen, made quieter by CSS only (lists instead of cards, the ivory scripture card); the mock has no view for them."
  - "Not checked on a real phone: Playwright Chromium and WebKit at 390x844 with reduced motion, and one 1280 wide check (scratchpad lumen-shots/bible)."
  - "The rest of the foundation's follow-ups (Give, Watch and Live, Messages, Prayer, Events, a group, Me, News) are other sessions."
decisions:
  - "Same switch as the foundation (member_lumen.page()); off, every Bible and Classes page is today's byte for byte: 96 pages (three scenes) dumped from main and this branch with MEMBER_LUMEN=off, all identical."
  - "Same reads off and on, counted per page (Bible tab 8, reader 1, plans 7, notes 1, a reading plan 1-2, a devotional day 2, books and search 0). The Bible tab's devotionals and plans are read by member_portal_devotionals.bible_home_data (bible_home is now that plus today's markup) and laid out from the data."
  - "The Bible tab: 'The Word' with KJV · WEB · BSB · ASV beside the heading; find a passage or a word; pick up where you left off (the book as a spine, the chapter large, soft gold behind); Today (the ivory verse card, which today's tab didn't have); From <church> (the devotionals as cards with progress dots, running ones first; a long one is seven dots filled in proportion); Reading plans (the church's plan and the member's own as rows with today's chapters, then the four plans as panes, a started one saying 'Yours · day N'); Your highlights & notes (counts only); Books."
  - "A devotional's cover: the church's picture for it, or a photo named for it, with the title on it; with neither, one of the mock's three flat covers (peach, lavender, mint). Never a made-up picture."
  - "The reader has no tab bar (as the mock): Bible · the chapter (opens the book picker) · Aa in the bar (member_portal._shell's new lumen_bar, used only under Lumen); the chapter's number large in gold; the chapters before and after float at the foot. Aa holds text size, font and translation; where there is no Aa (a preview, or marks that didn't load) the translation sits at the foot. Same reader script, highlighter and dock."
  - "'Listen to this chapter' (NEW in the mock) is not built: Kevin never approved it."
  - "The Bible tab's plan rows have no tick: the tick's POST returns only to Home or the plan page. Recently-read chips are left off the Bible tab (still on the book picker)."
  - "A reading plan (/my/reading) is pushed under the Bible with a way back to it (today's sits under Home with no way back)."
  - "Classes: the crest says Classes (no academy name a church hasn't chosen); the next class as 'Next class · Tuesday at 7 PM' on a soft gold pane; Your path from the program's tracks with their real actions (Open, Join) and the night it ends with; Your classes lists only classes on no path; classes to join keep their program and about."
  - "A main tab no longer slides its title in over the logo and name at the top (seen on the Bible tab; it was every main tab)."
  - "CSS in its own blocks, member_lumen_bible.CSS and member_lumen_classes.CSS, joined by member_lumen_ui.templates(), which member_app_ui.sheet('lumen') now serves (css() alone never reached the served file). Every rule under body.lm."
related: [2026-11-18-member-lumen.md]
---
`member_lumen_bible.py` draws the Bible tab, the reader, the book picker,
search, highlights & notes, plans & devotionals and a reading plan in the new
look; `member_lumen_classes.py` draws Classes. Each page's old function asks
`member_lumen.page()` first and hands over; nothing else changes off.

Measured locally (the foundation's harness over the test fake, so database
time is ~0; median Server-Timing total of 30 warm requests, off / on): Bible
4.2 / 5.3 ms (the verse of the day is new on this page), reader 2.7 / 2.8,
plans 4.0 / 4.5, books 3.7 / 4.1, notes 2.6 / 2.5, a reading plan 2.5 / 2.6,
a devotional day 3.7 / 2.7, Classes 3.0 / 2.1. Tests:
`__tests__/test_member_lumen_bible.py`.
