---
title: ChurchSavvy Planning, step 6 — who's on today, for the booth (server)
date: 2026-10-24
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-23: "when they are building live, all the data they gathered can be transferred into churchsavvy"; "This is a good build. i agree with your plan."; "let''s keep building as planas well." (canvas board 11)'
status: in progress
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone: ["the booth's Today tab that draws it (solutionist-studio, next)", "what changed in the plan since you looked Friday (board 11's Sunday Planning card): needs a record of the plan's changes", "the band's own words beside a name (vocals, leads song 2, first time)"]
decisions: ["Today reads the same service the booth has open, or the next one: each Sunday team, each place in its order, and who holds it", "a place is here (they tapped I'm here in the Sunday pack, with the time), yes and not here yet, asked and no answer, or open (nobody, offered to the team, or a no)", "the plan's clock is when the service starts, its longest item of fifteen minutes or more inside the service (the sermon), and when it ends; what comes before and after doesn't count"]
related: [2026-10-24-sunday-planning-pack.md, 2026-10-24-sunday-planning-order.md]
---
`GET /planning/today` in `sunday_order.py`, read by anyone on the team or with a seat (the same as the schedule), behind the same SUNDAY_PLANNING switch. Checks: `test_the_booths_today` in `test_sunday_order.py` (6 sabotages caught: an arrival not shown, waiting shown as a yes, an open place showing someone, the clock missing the sermon, a long rehearsal before the service taken for the sermon, anyone reading who's on).
