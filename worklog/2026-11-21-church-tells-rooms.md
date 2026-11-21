---
title: Office tells for room requests, their answers and a leader's yes
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: "fix the missing tells on the connection map"
status: shipped
prs: [kmj-intake-server#2038]
migrations: []
left_undone: ["CHURCH_TELLS switch-on for every church (church_tells.py, default owner)"]
decisions: ["a member-app room ask is left to member_asks, which already phones the rooms holders: only rows an office login booked (booked_by not null) are told", "a weekly repeat is one tell, keyed by its series", "an expired background check counts as on file; only none on file is told", "under-18s are skipped: checks are for adults (church_serving's teen)", "no booking notes or decider's reason in any line"]
related: [2026-11-21-church-tells.md]
---
`church_tells_rooms.py` adds the three finders `church_tells` already lists:
`room_asked` (an office login's request from the last 3 days, still waiting,
to whoever does the rooms; never the asker), `room_answered` (a request booked
or declined by someone else in the last 3 days, to the login who asked) and
`leader_said_yes` (a yes to a leader role in the last 7 days with no
background check on file, to whoever does background checks). A read the
words or the decision depend on that fails stops the finder, so a tell sent
once for good is never wrong. Tests: `__tests__/test_church_tells_rooms.py`.
