---
title: Chief keeps to a church login's lane — refuses other areas' actions and reads, and never sees money, the owner's memories or another lane's inbox
date: 2026-10-28
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-28, on whether office logins have Chief: "lets build the board tab and so we can add the lanes for chief"'
status: shipped
prs: [kmj-intake-server#1637]
migrations: []
left_undone:
  - "Who's talking: built next (2026-10-28-chief-who-is-talking.md), on business_users_router.seat_person (#1638)"
  - "The bell and the morning brief in the app are still church-wide (phone pushes already leave limited logins out)"
  - "A notification's tap runs its action with no login (notification_engine), so it isn't checked by lane"
  - "Admins (Kevin's wife, Minnie) keep everything, by design; a lane is for Manager logins"
  - "Custom modules' entries are everyone's: a church with a money module (pledges) would want it placed"
decisions:
  - "Who: a non-owner, non-admin login of a church whose areas are limited (church_areas.my_areas, picked or guessed, CHURCH_AREAS on). The owner, admins, a login nothing places and every non-church business keep today's Chief"
  - "Every verb is placed: VERBS (by area, or everyone's) or OWNERS; a verb in neither is refused to a lane, and a test lists every handler so a new verb must be placed"
  - "Checked at both doors: chief_of_staff._execute_actions (before the reasoner path) and chief_tool_loop.execute_tool_use (and view_website). A scheduled action is the action it schedules; a proposal the verb it proposes; show_view's invoices and products are money"
  - "Money is Giving's only: no invoices, products, gifts in the events, bank, books or forecast in the context, and a person's deep dive drops what they gave"
  - "The owner's memories are dropped except their standing instructions (those still bind); recall_conversation, catch_up and search_ledger are the owner's"
  - "The inbox, drafts and at-risk list only for lanes that work with people (People & care, Office, Messages & safety)"
  - "Fails open on a failed read (today's Chief), like the menu; CHIEF_AREAS=off turns it all off"
related: [2026-10-28-church-office-lanes.md, 2026-10-26-who-sees-what.md, 2026-10-23-church-areas-map.md]
---
chief_areas.py: the verb map, the gate (refusal), the context trims (trim_context, trim_sources, trim_view, trim_result) and the prompt's THIS LOGIN block in the turn's tail, never a cached segment. Wired into chief_chat (the turn's scope, a contextvar beside _TURN_USER_ID), the action door and the mid-turn reads. Tests: __tests__/test_chief_areas.py, including a whole turn as a People & Care login.
