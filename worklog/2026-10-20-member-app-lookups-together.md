---
title: Faster member app tabs — each tab reads what it can at once
date: 2026-10-20
agent: Claude Code (Claude Opus 5.5)
asked: '"can we figure out how to speed the app response up … when I click through tabs, the responses are slow in changing" … "this is the members app to be clear" … "no loading bar for the app. push the update for merge" (Kevin, 2026-10-20)'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Connect still waits on two chains of four reads each (member_portal_church.groups_for, member_portal_messaging.in_leaders_room); both files are another session's, so they were left as they are"
decisions:
  - "Kevin: no loading bar or tap indicator in the member app; the fix is the server"
  - "The church and its site come back in one read (business_sites with businesses embedded), not two"
  - "The Lead tab's two reads (a church role, a group they lead) run alongside the member's space; led_groups is now read even for someone with a role (one more cheap read) so neither waits on the other. Who gets the tab is unchanged"
related: [2026-10-20-member-app-speed.md]
---
Second half of the member-app speed work (the first, kmj-intake-server#1542, keeps database
connections open). Every tab read the church, the church again, the member, their space and
their roles one after another before its own reads; Home, Connect and Watch then read their parts
mostly one after another too. Now each tab makes those waits at once. Reads one after another, a
member's view of live Love City data (page code run locally, writes blocked): Home 12 → 7,
Connect 16 → 8, Watch 10 → 5, Bible 8 → 4, Me 9 → 5. Each of those costs ~85 ms from the server
(see the correction in 2026-10-20-member-app-speed.md), so a tab should lose roughly 0.3-0.7 s.
`__tests__/test_member_portal_speed.py` proves "at once" with barriers (a sequential read breaks
them; each case rehearsed red) and pins who gets the Lead tab.
