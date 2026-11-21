---
title: "Member app new look (Look 5.1): Search on Watch"
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: "The mock's Watch top bar has a search icon at the right, and a 'Search' link next to 'Every message'. Add a simple search: /my/sermons?q=... filters the library Watch already reads (member_portal_sermons, up to 500 rows) by title, speaker, scripture and series name, with no new database read (filter in Python). The icon opens a search field (no script needed: a GET form). Results use the Every message rows, with a plain 'No messages match' state and a way back. Put the icon into #2033's own top bar for Watch."
status: shipped
prs: ["kmj-intake-server (this PR)"]
migrations: []
left_undone:
  - "No search as you type: the field is a plain GET form (press Search on the keyboard), as asked. It could later filter the rows already on the page with a small script."
  - "A book of the Bible matches only as written in the scripture field ('john' finds John 3:16; 'jn' doesn't), and words match anywhere ('love' also finds 'beloved'). Simple on purpose."
  - "Today's look (MEMBER_LUMEN off) has no search; ?q= is ignored there and Watch is drawn as it is."
decisions:
  - "Watch's own top bar (member_lumen_watch.top) is the title and, at its right, the search button: a link to /my/sermons?q= (lm-icb, the same round button as the Bible's search), marked aria-current while the search is open. 'Search' sits beside Every message's heading, in the church colour, as the mock draws it. Both are links, so no script is needed."
  - "/my/sermons?q= (the query asked for, even empty) is the search: the field (type=search, autofocus while empty, at most 80 characters) and Cancel back to Watch; empty, a line saying what it searches; then '<n> messages' and Every message's own rows (_mrow: the picture, how long once played, title, speaker, scripture, date, the progress line), newest first, at most 60 with a line to add a word; or 'No messages match “<words>”', a hint, and Back to Watch."
  - "member_lumen_watch.search: every word must appear in the title, speaker, scripture or series name, compared in lower case with accents and apostrophes set aside (God’s finds Gods; Jose finds José). Pure: it filters the library the page already read."
  - "member_portal passes ?q only under the new look, and skips the weekly service time's read for it (the search doesn't show Watch live); the library, live and next-gathering reads are Watch's own, unchanged."
  - "CSS in Watch's block (member_lumen_watch.CSS, part of member_lumen_ui.templates(), order unchanged), every rule under .lm, tokens only."
related: [2026-11-21-lumen-tab-tops.md, 2026-11-20-lumen-watch.md]
---
Watch has a search in the new look: the button at the right of its top bar and "Search" beside Every message open
/my/sermons?q=, which filters the library Watch already read. No route, no read of its own, no migration.

Checked: switch off and MEMBER_LUMEN=preview for a non-owner, 951 page x scene dumps each (Home harness 656, Bible
harness 295): same 951, differ 0 in both modes against main. Reads with the switch on, per page and table, in four
looks: Home harness 1984 / 1984 over 328 page-looks, no page differs; Bible harness every page that answers 200 the
same, 1132 / 1132 over 224; the search pages read nothing Watch doesn't (pinned in the tests; warm, 0 reads each in
the harness). Member suites: 1592 passed (test_member_lumen_watch_search: 17 new; Watch's bar test now expects the
button). Shots before and after (Chromium and WebKit, light and dark, 390x844 @2x) in the session scratchpad's
watch-fix-shots/ (before-*, find-*).
