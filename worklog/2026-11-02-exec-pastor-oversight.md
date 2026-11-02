---
title: The Executive Pastor sees her team's weeks, and a Monday roll-up reaches her
date: 2026-11-02
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-01: "Jessica will be over the admin team" (docs/CHURCH_DUTIES.md step 6, her view; approved)'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "FE: the team page (GET /church/my-week/team) and See as for the Executive Pastor (the app's See as bar still offers it to the owner and admins only; seeing_as now names whose week it is)"
  - "The monthly report (oversee_lanes' sibling, monthly_report) is its own PR"
  - "Set CHURCH_TEAM_ROLLUP on both Railway services on a Thursday (owner, the default, is Love City)"
decisions:
  - "See as opens to whoever holds oversee_lanes (church_duties.holds), for another Manager login on the same church only: an Admin's, the owner's or a Member's week is a 403. The owner's and the admins' See as is unchanged and never reads the switch"
  - "GET /church/my-week/people takes no as_user, so nothing changed there"
  - "The team page lists every active Manager login (the overseer's own row left out: that's My week); counts only for follow-ups and care, task titles for tasks, the duty days from the catalog; no money; one login's failed read is a 503 row, never an empty one"
  - "The roll-up goes to the Manager holders of oversee_lanes (church_duties.manager_holders, new), never the owner or an admin; Monday 8 to noon on the church's clock (church_leader_tasks.zone, LATE_FROM to LATE_UNTIL); one claim per church per ISO week in businesses.settings.church_team_rollup, swapped the leaders note's way; a send that reaches no one frees the week; no Manager over the lanes, or no team to report: no claim"
  - "Review: a duty never widens what a login sees. The overseer's See as is cut to her own areas (church_team_week.within: the login's own tasks always; follow-ups, care, area lines and gaps only in areas she works), and the team page's and roll-up's follow-up and care counts go only to an overseer who works People & care. Love City's plan picks every area for Jessica; if nothing is picked, Chief's guess from her role is People & care alone"
  - "Review: a roll-up that reached some holders and not others is `partial` and the next hour tries only the rest; a record that doesn't save is printed and counted (`unrecorded`)"
  - "One switch, CHURCH_TEAM_ROLLUP (off | owner | on; owner is the platform owner's own church, member_asks.platform_church), for the overseer's See as, the team page and the roll-up"
  - "church_duties' area rule stands: a Manager no lane names holds every non-money duty in its areas, oversee_lanes too (with Who sees what off, every Manager no lane names). Love City's Managers all have lanes, so only Jessica"
related: [2026-11-01-church-duties.md, 2026-11-01-office-tasks-reach.md, 2026-10-26-who-sees-what.md]
---
`church_team_week.py` (new): the switch, `overseer()`, the team page
(`GET /church/my-week/team`) and the hourly `rollup_tick` (scheduled in
`kmj_intake_automation.py` as `church_team_rollup`). `church_my_week.my_week`
opens See as to the overseer and adds `seeing_as`. `church_duties` gains
`manager_holders()`. Tests: `__tests__/test_church_team_week.py`; the My week,
duties, office tasks, leader tasks and leaders note suites still pass.
