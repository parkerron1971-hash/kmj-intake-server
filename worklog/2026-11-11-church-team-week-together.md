---
title: The office team page reads its logins side by side
date: 2026-11-11
agent: Claude Code (Claude Fable 5.2)
asked: "make the fix" (to: the pastor's band on a church's Home took about 30 seconds to fill in on a fresh load, mostly waiting on the office team)
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone: ["Not timed on production: I have no sign-in to call it with. Seen from the browser before this change: 9 to 14 seconds for five logins, on a computer that was itself short of memory", "Each login is still a dozen reads of its own (its standing, its name, its tasks, its follow-ups, its care); fewer reads per login is its own change"]
decisions: ["Up to six logins at a time (TEAM_WORKERS), the way church_reports reads its sections", "The rows keep the seats' order, then the page's own sort; a refusal that isn't a 503 still raises; a 503 is still that login's unread row", "The Monday roll-up reads through the same function, so it is faster too"]
related: [2026-11-02-exec-pastor-oversight.md]
---
`GET /church/my-week/team` read each Manager login one after another. A login is about a
dozen reads, so Love City's five took ten seconds and more. A church's Home asks this page
for the pastor's band (solutionist-studio #1515), so Home's last card waited on it.

`church_team_week.team` now reads the logins in a small pool. Nothing in what the page says
changed.

Checks: `python -m pytest __tests__/test_church_team_week.py __tests__/test_church_my_week.py`
(56 pass). The new test holds every login's read at a barrier until all are in flight; with
one worker it fails.
