---
title: Kids check-in can start this week's service itself
date: 2026-11-06
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-06: "fix the issues that we have ran into ... make those changes that you list so thing can offically work"'
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio kids-this-sunday (the button)]
migrations: []
left_undone:
  - "The Sunday page's plan (ChurchSavvy) is still not a check-in occasion; the button makes a Services & Events service instead"
  - "A church with no Services & Events room gets a 409 that says to open Services & Events (every church template has one)"
decisions:
  - "POST /kids/this-week: any kids team member (require member), the same gate as checking a child in"
  - "It calls church_checkin.ensure_occasion for the next service window, so it is the same once-only occasion the hourly sweep makes when member check-in is on, at the church's saved service time (Sunday 11:00 until set)"
  - "The hourly sweep is unchanged: it still only makes a service for churches with member check-in on, so no church gets weekly entries it didn't ask for"
related: [2026-11-06-church-import-families.md]
---
In the 2026-11-05 run-through, Kids check-in said "Nothing to check in to yet" and sent the pastor to Services & Events to create a service by hand. The Sample Sunday on the Sunday page didn't count. A new church never gets the week's service made for it, because church_checkin's sweep only runs for churches that switched members' Sunday check-in on.
