---
title: The church site's Start buttons say church (/start?for=church)
date: 2026-11-05
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-05, before pushing to pastors: "yes do the run-through"'
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio#1476]
migrations: []
left_undone:
  - "The run-through's other findings are in the frontend worklog 2026-11-05-church-start-path.md and the report to Kevin"
decisions:
  - "church_site.render points every Start button at START_PATH (/start?for=church) on the finished page, so plan cards, the picker and every room's buttons all carry it"
  - "/start carries for=church only (whitelisted like plan); anything else is dropped"
  - "The business home (/business) keeps plain /start"
related: [2026-11-04-business-home-path.md]
---
The run-through signed up from the church home page's Start button and got the business version of every first screen, because nothing told the app it was a church. Now the church pages send /start?for=church, /start carries it to the app (?for=church&signup=1), and the app's signup, Meet Chief and setup speak church (solutionist-studio#1476).
