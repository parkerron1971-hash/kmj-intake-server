---
title: Member app round three, part 4 - plans and devotionals (a church's own devotionals, a member's own plans, the devotional day, Listen)
date: 2026-10-19
agent: Claude Code (Claude Opus 5.5)
asked: '"the bible section needs major upgrade. ie reading plans plus church made personal devotionals" (round three); "Yes continue" (Kevin, 2026-10-19, to Listen on devotionals, which costs voice minutes)'
status: shipped
prs: [kmj-intake-server#1505]
migrations: [supabase/APPLY-2026-10-19-devotionals.sql (applied to production 2026-10-19 before this PR; rollback probe published a one-day devotional, added a member day and start, refused a bad voice, and deleting the devotional took the member day with it)]
left_undone: ["the Solutionist side: writing, pasting in, publishing and dating a devotional, and choosing its voice (a frontend PR on /church/devotionals)", "the What's New entry (with that frontend PR)", "a devotional for a class (\"The Making: week by week\" on the canvas) needs the classes to point at one; not built", "push notifications for a devotional's day; not built"]
decisions: ["a devotional is one row with its days in a JSON array, so it saves, exports and restores whole; members' days are their own rows", "a dated devotional opens a day a day for everyone from its start (the church on the same page, like the reading plan); an undated one opens a day a day from the day a member taps Start; a day that isn't open shows its name and when it opens, and nothing to tap", "a member's journal is private like their Bible notes: no staff route reads it, and devotional_progress is never in the church's export", "Listen reads a day once per version of its words and voice and keeps the MP3 in the church's public business-assets storage; every later Listen plays that file, so the cost is one reading per day per edit (about 4 cents a day on Inworld Flash), never one per listen", "Listen uses the voice the church picks from Kevin's featured voices, at no faster than normal speed; a piece Inworld can't read is read by Nova; with no voice key or no ffmpeg, Listen isn't shown", "Listen also works in the owner's preview (the owner hears what members will), and a preview sees every day; nothing else saves in a preview", "a devotional's picture is a member-app picture spot (devotional:<id>), so only the owner and the people they named change it", "a reading plan of a member's own uses the same reading_progress ticks keyed by its own start date; Home shows it when the church has no plan running"]
related: [kmj-intake-server worklog/2026-10-19-member-app-bible.md, canvas https://claude.ai/artifact/WzjBoY73aPBUkwy1PsEArU (boards 1, 6, 10, 11)]
---
The plans and devotionals in the member app, built to the approved canvas.

- `/my/bible/plans` is Plans & devotionals (board 10), with filters All, From <church>, Reading plans and Yours:
  - "This week at <church>": the devotional the church dated and is reading now, with today's verse and a bar of its days
  - the church's other devotionals, each with where the member is ("Day 3 of 7", "Starts Mon, Oct 26", "You finished it", "Start")
  - the church's reading plan, and the four plans to start on your own day
- `/my/bible/plans/<id>` is a devotional: its picture, welcome, Start (when undated), its daily practices and its days.
- `/my/bible/plans/<id>/<n>` is a day (board 11): the scripture from the app's Bible, the words, the line to hold on to, Pray / Do today / Together, the daily checklist, a private journal, Listen, Mark done (and Not done yet), and the next day.
- `/my/bible/plans/<key>` is a reading plan the member started, with Stop.
- Home's Today card gets today's devotional row, and its link is now Plans. The Bible tab gets "From <church>" and "Reading plans".
- Staff write devotionals through `/church/devotionals` (`devotionals.py`). Writing is owner, admin or manager only; any seat can read. It includes `read-paste`, which reads a whole devotional pasted in the way Kevin's "Consecrate Your Focus" is set out.

Checks:
- `__tests__/test_member_devotionals.py`: 27 tests, 353 with the rest of the member and Bible tests.
  - Rehearsed by opening every day to a member's saves, and by taking out the Listen lock: each went red.
- `__tests__/devotionals_db.mjs` (in CI) runs the migration on a real Postgres: 24 checks.
  - Rehearsed by letting a member's day point at another church's devotional: it went red.
- The day page was driven in a browser at phone width with the saves and Listen faked: 21 checks. These cover the checklist (rapid taps send one save), the journal saving itself, Mark done and Not done yet, the tab bar never covering Mark done, Listen and pause, and a failed save saying so.
- The Inworld and Nova reads were tried with the production keys on one sentence. Both gave 7.5 seconds of speech, and the Inworld file read back word for word.
