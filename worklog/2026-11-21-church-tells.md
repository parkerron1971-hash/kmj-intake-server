---
title: The office's missing tells (the sweep)
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: "yes go with the plan and make those small fixes as well" (the seven missing tells on Love City's connection map)
status: in progress
prs: [kmj-intake-server (this PR: the sweep and its rules)]
migrations: []
left_undone:
  - "The finders: church_tells_money (count closed, pay-back asked), church_tells_rooms (room asked, room answered, leader said yes), church_tells_sunday (sermon draft, count missing, flyer needed) each come in their own PR; until then the sweep finds nothing"
  - "CHURCH_TELLS defaults to owner (Love City only); switch on for every church on a Thursday, on BOTH services"
  - "church_tells isn't a business_settings.SERVER_KEYS key (that list is pinned to SQL the owner applies), so a stale whole-settings write could drop the stamps and repeat a tell once"
decisions:
  - "A sweep (every 30 minutes on the worker), not new code in each request path: the busy screens stay untouched, quiet hours hold tells, and a tell is claimed once for good in businesses.settings.church_tells"
  - "Who hears a duty's item: its Manager holders; else the Admin logins; else the owner; never the login who did it. Several items for one login in a sweep are one notice"
related: [2026-11-12-church-assignments.md]
---
Love City's connection map (artifact FRHUeETPMVkpQHs24yFs4W) found hand-offs
that work but never tell the next person. `church_tells.py` is the one sweep
that tells them: each finder module returns Items (a duty or logins, a key,
the words) and the sweep sends one push + email a login through
church_schedule_tell.to_login. FINDERS lists the eight finders; a module
that isn't there yet is skipped.
