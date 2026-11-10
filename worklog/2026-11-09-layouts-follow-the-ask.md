---
title: The layout the Coach recommends follows what the owner asked for
date: 2026-11-09
agent: Claude Code (Claude Opus 5.5)
asked: "make sure chief can interpret what everyone is asking like you can so the design could be good"
status: shipped
prs: [kmj-intake-server#1783]
migrations: []
left_undone:
  - "Not measured on the owner bench (scripts/coach_ask_bench.py): the run was stopped for low memory and saved nothing. The six held-out owners are the honest measure."
  - "Not yet tried live: repeat the test-shop conversation once #1781 and this are deployed."
decisions:
  - "Only the owner's own words steer the ranking, and the owner's own pick still leads it."
  - "A beat of story is at least four words, and the room and the signature moment count once each. An essay layout claims your story carries the site only at four beats."
  - "An ask for prices to be seen lifts the grid and the Booking desk and lowers the essay and the huge-words opening."
  - "A by-appointment trade with booking off loses one point on the Booking desk, not four: it hasn't refused online booking, Chief can switch it on."
related: [2026-11-09-coach-reads-the-ask.md, 2026-11-09-website-ask-goes-to-coach.md]
---
Talking to Chief as a test shop: an owner who asked to be found and booked was
recommended the Long-scroll story, "your story has enough beats", on almost no story.
The Booking desk wasn't offered, with booking live, because the Coach's ranking was
never told booking was on and said "visitors do not book with you online".

The ranking now knows whether booking is live, reads what they asked for, and counts
a story only when one was told.
