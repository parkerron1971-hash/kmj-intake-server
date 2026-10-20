---
title: The shepherding Chief test no longer turns a child 8 at midnight UTC
date: 2026-10-19
agent: Claude Code (Claude Opus 5.5)
asked: '"keep going with step 2 I want the entire thing built" (Kevin, 2026-10-19); this test failed the ChurchSavvy show engine PR (#1510) and would fail every PR from 2026-10-20 UTC on'
status: shipped
prs: [kmj-intake-server#TBD]
migrations: []
left_undone: []
decisions: ["pin Jaylen's birthday in that one test, not change born(): the shared fixture is right for the tests that read the real date; only this file pins NOW"]
related: [kmj-intake-server worklog/2026-10-19-churchsavvy-show.md]
---
`test_church_shepherd_signals.py` pins its clock to NOW = 2026-10-19 13:00 UTC. It shares `test_church_shepherding.py`'s fixture, where `born(9)` counts nine years back from the machine's real date. From 2026-10-20 that makes Jaylen's birthday Oct 20, so on the pinned Oct 19 he is still 8, and `test_chief_answers_who_shepherds_the_carters_never_a_notes_words` failed looking for "Jaylen (9)". CI hit it at 00:04 UTC on #1510. The test now gives him a fixed birthday (2017-03-01), so he is 9 on NOW whatever the date.

Checks: rehearsed. With his birthday set to 2017-10-20 (what born(9) gives on Oct 20) the test fails, and with the fix it passes. The file passes 29/29.
