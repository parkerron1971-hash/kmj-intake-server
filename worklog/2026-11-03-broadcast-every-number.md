---
title: Whole-church texts reach every number, not the first 500
date: 2026-11-03
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03, after the church-pricing review found the cap: "I agree with the plan. make the fixes and upgrade to site or whatever you need to upgrade or fix."'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Texts still aren't counted or costed anywhere (no api_usage row per SMS); that's the next fix in the church-plans arc"
decisions:
  - "sms_routing._read_every pages by a unique key (id for contacts, contact_id within one group) at sb_clients.PAGE_ROWS, PostgREST's real ceiling; None when any page fails, so a broadcast sends to nobody (503) rather than part of the list"
  - "/sms/groups reads each group's members on its own (contact_id is only unique inside a group) and answers 503 when a member or contact read fails, where it used to count a failed read as nobody"
related: [2026-10-28-bulletin-said-yes.md, 2026-10-30-text-room-announcements.md]
---
Before building I read both repos' `worklog/`. 2026-10-28-bulletin-said-yes
left "Still at most 500 contacts per press (unchanged)" undone; nothing else
touched it.

The whole-church announcement read `contacts … limit=500` with no order, so a
church past 500 numbers texted an arbitrary 500 and nobody else, and the
Text screen's reach count said 500. That starts around 250 people on a Sunday.
A group's member read asked for 5,000 and the group counts for 50,000, but
PostgREST stops at 1,000 either way.

Tests: `__tests__/test_sms_announcements.py` +4 (1,300 numbers come back from
two pages; a failed second page sends to no one; a 1,200-member group; group
counts that can't be read are a 503). Ran it with test_bulletin_said_yes and
test_sms_tenant_isolation: 82 passed.
