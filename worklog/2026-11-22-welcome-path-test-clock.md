---
title: The Welcome Path test's lunch was today (a test bound to the real clock)
date: 2026-11-22
agent: Claude Code (Claude Fable 5.2)
asked: "Found while building Chief's church lookups: every PR's tests began failing the afternoon of 2026-11-22"
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone: []
decisions:
  - "A test fix only: the fixture holds guest_path_weeks' own clock as it already held new_here's. No product code changed"
related: [2026-11-20-guest-path-weeks-two-to-six.md]
---
`__tests__/test_guest_path_weeks.py::test_the_room_round_trip_and_an_old_clients_put`
makes a Newcomers Lunch at 2026-11-22 12:30 and reads the room's coming events.
The fixture held `new_here._now` but not `guest_path_weeks._now`, which the
events list reads, so the test passed until that lunch was in the past on the
real clock and has failed for every branch since. The fixture now holds both
clocks. 43 of 43 pass.
