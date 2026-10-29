---
title: ChurchSavvy Planning, step 7 — a Sunday team's leader schedules their team (member app)
date: 2026-10-24
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-23, call 4: "TEAM LEADERS schedule their own team (admins anyone)"; "This is a good build. i agree with your plan."; "let''s keep building as planas well." (canvas board 4: "Marcus leads Production, so he sees and fills Production")'
status: in progress
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone: ["a swap that needs the leader's OK (board 5's turns: Swaps need my OK): today a cover moves on the other person's yes", "the leader taking someone off a Sunday they said yes to: the office does that today", "the office's Who serves when page for a leader on a computer (board 4's view as Marcus): today a leader schedules from the member app"]
decisions: ["a team's leader is the church's leader of the team's group (group_members.role = leader); they're a member, never a seat, and schedule from the member app's Lead tab, Sundays, beside My group", "they see their team only, one Sunday at a time, every place and who holds it; someone on their team serving on another team that hour shows as on that place, never as free", "they ask someone on the team (trained or learning), offer a place to the whole team, take back an ask nobody said yes to, and fill the next five Sundays the office's fair way, then take that fill back before it goes out; every write checks the place is their team's", "an ask from the leader goes out under their name, on the sweep, like the office's", "the office's ask, offer, take back, fill and unfill became plain functions both use (sunday_planning do_*); the office's routes check as before"]
related: [2026-10-23-sunday-planning-teams.md, 2026-10-24-sunday-planning-alerts.md]
---
`sunday_leading.py` (who leads which team; their team's view and candidates; ask, offer, take back, fill, unfill on their team only) and `member_portal_leading.py` (`/my/lead/sundays`, its forms, in the Lead tab's style with My serving's rows). The Lead tab's section switcher offers Sundays to a team's leader (`member_portal_lead.SUNDAYS`, read once per request).

There's no phone board on the canvas for this; it follows board 4's matrix the way the office's own phone view does (one Sunday at a time) and the member app's My serving rows and sub panel. Looked at in the real member frame at 390 (Marcus leading Production): no horizontal scroll, the spot panel lists who could take Lights with why the others can't. Checks: 6 tests in `test_sunday_leading.py` (10 sabotages caught: anyone in the group leading it, asking or offering another team's place, taking back a yes or another team's ask, a fill or its take-back reaching other teams, seeing another team, Sundays for everyone in the Lead tab, the preview saving); the office's Planning tests stay green through the refactor.
