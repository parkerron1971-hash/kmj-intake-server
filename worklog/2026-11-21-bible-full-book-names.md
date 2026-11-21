---
title: "Member app new look (Look 5.1): the Bible reader names the book in full under the chapter number"
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: "Under the big chapter number the mock reads 'THE GOSPEL OF JOHN'; live reads 'JOHN' because bible_text.BOOKS has only short names. Add a static map of the 66 books' conventional titles ('The Book of Genesis', 'The Book of Psalms', 'The Gospel of John', 'The Acts of the Apostles', 'The Letter to the Romans', 'The First Letter to the Corinthians', 'The Revelation to John'), short and plain, and use it in the new-look reader's chapter label only."
status: shipped
prs: ["kmj-intake-server (this PR)"]
migrations: []
left_undone:
  - "Only the line under the big number changed. The chapter pill ('John 3'), the previous and next links, the page title and the label a screen reader hears ('John 3') keep the short names, as the mock does."
decisions:
  - "bible_text.TITLES: one static title per book, in the BOOKS order. Letters are 'The Letter to the Romans' / 'The First Letter to Timothy' for Paul's and 'The Letter of James' / 'The First Letter of Peter' for the general letters; the Old Testament's histories are 'The First Book of Samuel' and so on; 'The Song of Solomon' follows the KJV's name, which is the reader's default text; 'The Revelation to John'. The longest is 38 characters, which fits on one line at the label's 11px capitals on a phone."
  - "member_lumen_bible.render_chapter reads it for the h1's visible line only (it falls back to the short name if a code were ever missing). Today's reader (member_portal_bible) is untouched."
related: [2026-11-21-lumen-tab-tops.md, 2026-11-20-lumen-bible-tabs.md]
---
The new look's reader reads "THE GOSPEL OF JOHN" under the chapter's big number, as the mock does. No route, no
read, no migration.

Checked: switch off and MEMBER_LUMEN=preview for a non-owner, 951 page x scene dumps each (Home harness 656, Bible
harness 295): same 951, differ 0 in both modes against main. Reads with the switch on, per page and table, in four looks: Home harness 1984 / 1984 over 328 page-looks, no page differs; Bible harness every page that answers 200 the same, 1132 / 1132 over 224 (its Home is a harness crash on main and here alike, whose parallel reads vary run to run). Member
suites: 1591 passed (test_member_lumen_bible_titles: 16 new; two Bible reader tests now read the full title). Shots before and after (Chromium and WebKit, light and dark, 390x844 @2x) in the session
scratchpad's watch-fix-shots/ (before-*, titles-*: John 3, Psalm 23, Acts 2, 1 Corinthians 13).
