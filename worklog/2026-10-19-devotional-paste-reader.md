---
title: Pasting in a devotional reads a real document - its welcome, its checklist and where its last day ends
date: 2026-10-19
agent: Claude Code (Claude Opus 5.5)
asked: '"Paste Consecrate Your Focus in for me", then "yes fix it" (Kevin, 2026-10-19, to fixing the paste reader after it misread his real document)'
status: shipped
prs: [kmj-intake-server#1506]
migrations: []
left_undone: ["the sections a devotional has no field for (Kevin's set-aside table, the prayer-line times, \"Make it yours before Monday\", the closing charge) are still left out; nothing shows the church what was left"]
decisions: ["the welcome is the first section with words of its own, so a byline, the later headings and tables don't pile into it", "a checklist section (\"Your Daily Checklist\", \"Daily practices\"), before or after the days, gives the practices, because it is what a member ticks; with none, the anchors are read, numbered or not, even when their description runs on", "a day ends at a heading only once its Pray/Do today/Together/Journal lines have begun and none still to come is new, so an \"Amen\" on its own line doesn't cut off Do today; a label that comes round again also ends the day instead of overwriting it", "a kind of \"7-Day Devotional\" reads as none, because the page already says \"7-day devotional\"; \"21-Day Fast\" reads as \"Fast\"", "a practice's note keeps its capitals (\"9 PM\"): only its first letter is raised"]
related: [kmj-intake-server worklog/2026-10-19-member-app-devotionals.md]
---
`devotionals.parse`, the reader behind Paste in a devotional (`POST /church/devotionals/read-paste`), was built on a tidied copy of Kevin's "Consecrate Your Focus". On the document as it really copies out, it:
- found no practices, because the anchors run on ("1. First Look (morning, before your phone). Your first look...");
- put the byline, every heading and both tables into the welcome;
- ran Day 7 on through the Daily Checklist and the closing charge. The checklist's "Together: joined the 6 PM prayer line" overwrote Day 7's own Together.

It now reads sections:
- the welcome is the first section;
- the practices come from a checklist section, or else the anchors;
- the last day stops where its own lines stop.

Kevin's devotional was pasted into Love City by hand first, as a draft (8a66fb4a), so he didn't wait on this.

Checks:
- The whole document, run through the new reader, matches the hand-checked copy saved for Love City field for field: the welcome, the 6 practices and all 7 days. Only the kind differs, as decided.
- 3 new tests cover the real layout, anchors with and without numbers, the "Amen" line and a repeated label. All 3 fail on the old reader and pass on this one. The other 27 tests are unchanged and pass.
