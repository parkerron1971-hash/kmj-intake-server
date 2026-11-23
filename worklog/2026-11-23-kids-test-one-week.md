---
title: The Kids space tests hold one week (they broke for the week of Nov 23)
date: 2026-11-23
agent: Claude Code (Claude Fable 5.2)
asked: "Found while merging Chief's step 2 (#2073): its tests failed on a file it never touched"
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "The page itself, not changed here: when a leader's lesson and the week's built-in story share a title, the family home shows one card and says both children learned it ('This week Ava and Eli learned'), though one child's room posted no lesson. Small and rare (one week in eight, only with a same-titled lesson); Kevin's call whether it matters"
decisions:
  - "A test fix only: an autouse fixture holds member_spaces_kids.story_of_week at the week the tests were written in. No product code changed"
related: [2026-11-22-welcome-path-test-clock.md]
---
`__tests__/test_member_spaces_kids.py::test_the_sunday_pass_shows_the_live_code_while_a_child_is_in`
expects "This week Ava learned". The story a child with no lesson gets follows
the calendar's week (`story_of_week`, eight stories in turn), and in 2026's
48th week (from Mon Nov 23, by the server's UTC date) it is "David and
Goliath": the title of the test file's own lesson. The page then reads "This
week Ava and Eli learned", so the test failed on every branch from 00:00 UTC
Nov 23 and would have for seven days. It passed on a machine still on Sunday's
date, which is why it looked random.

Second test bound to the real clock found in two days (the Welcome Path's lunch
was the first, #2071).
