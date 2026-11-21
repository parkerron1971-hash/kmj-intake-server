---
title: "Member app new look (Look 5.1): the Bible reader sets a verse to a line, as the mock does"
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin compared the live member app with the approved Look 5.1 mock and saw cut corners. The new look's Bible reader runs verses together in paragraphs; in the mock each verse starts on its own line (the number, its words, the next verse on a new line). The chapter label under the big number is the book's full title in the mock ('THE GOSPEL OF JOHN'); use a fuller title only if the Bible data carries one, never invent titles."
status: shipped
prs: ["kmj-intake-server (this PR)"]
migrations: []
left_undone:
  - "The chapter label stays the book's name ('JOHN', 'PSALMS'): the Bible data (bible_data/*.tsv.gz, eBible.org's verse-per-line files) carries only book codes, and bible_text.BOOKS only the short names. No title was invented."
decisions:
  - "member_portal_bible.chapter_html takes lines=True: every translation a verse to a line (each verse its own <p>, class bb-lines), KJV included. The default is unchanged, so today's reader keeps KJV's ¶ paragraphs, and the passages on a sermon, the verse cards and the slides are as they were."
  - "Only the new look's reader (member_lumen_bible.render_chapter) passes it. The verse stays an inline span in its line (.bb-v), so tapping, the highlighter colours, the ink sweep, notes, Listen and Make a card work as before; the owner's preview (no marks to tap) and a passage with verses marked (?v=1-3) are a verse to a line too."
  - "CSS: body.lm .lm-read .bb-text p{margin:0}: verses follow one another with no gap, as the mock's do (its verses carry no gap). It also drops today's 8px between WEB, BSB and ASV verse lines in the new look's reader. Under .lm, in member_lumen_bible's block; templates() order unchanged."
related: [2026-11-20-lumen-bible-tabs.md, 2026-11-21-lumen-tab-tops.md]
---
The new look's Bible reader sets a verse to a line. No new read, no route, no migration.

Checked: switch off and MEMBER_LUMEN=preview for a non-owner, 951 page x scene dumps each (Home harness 656,
Bible harness 295): same 951, differ 0 against main. Reads with the switch on, per page and table, in four
looks: Home harness 1984 / 1984 over 328 page-looks, Bible harness 1288 / 1288 over 236, no page differs.
Member suites and the Bible versions' tests: 1580 passed. Shots before and after (Chromium and WebKit, light
and dark, 390x844 @2x: John 1 in KJV and WEB, Psalm 23, the Bible tab) in the session scratchpad's
tabs-fix-shots/ (verse-before-*, verse-after-*).
