---
title: A tap on a notification's action runs as whoever tapped it
date: 2026-11-24
agent: Claude Code (Claude Fable 5.2)
asked: 'Fix needs no slot. Found by the independent review of the saved-conversations change (kmj-intake-server #2078), which Kevin asked for on 2026-11-23 ("check out a conversation Jessica was having with Chief")'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "The tap still calls the handler directly, not Chief's action door (_execute_actions): no undo row, no held-write confirmation. Unchanged here"
  - "A seat can still write its own chief_notifications row (the tenant write policy); what it can then have run is now only what its own chat could do"
  - "No live Chief eval was run; nobody's real notification was tapped"
decisions:
  - "The hole: POST /agents/notifications/{id}/act ran Chief's handler with no login in the turn. Every handler reads that as the server acting for the owner: reads went out as the server (no row rules), no lane was checked, and 'who is asking' was nobody. A member seat could write its own notification row with any action in it and tap it"
  - "A tap by anyone but the owner now runs under their own sign-in, with them as the person in the turn and their lane set (chief_areas.turn_for), bound the way chief_chat binds them and unbound in a finally. A verb outside the lane is refused (403) in the words chat uses, before anything runs"
  - "The owner's tap is unchanged on purpose: it has always run as the server, and some of its writes land only that way (the row-rule trap in docs/RLS_MODEL.md)"
  - "Fails closed: no token to run under is a 401, a lane that can't be read is a 503, and neither runs the handler"
related: [2026-11-24-chief-turns-saved-by-login.md]
---
`notification_engine.execute_notification_action` takes the request's own
Authorization header beside the verified user, and `_run_as` binds
`sb_clients.set_user_jwt`, `chief_of_staff._TURN_USER_ID`, `chief_areas.TURN`
and `chief_areas.WHO` around the handler for any caller who isn't the owner.

Tests: `__tests__/test_notification_act_as_who_tapped.py` (the owner's tap as
before; a seat's bound and unbound, also when the handler raises; the lane
refusal; no token; a lane that can't be read; a login with no lane).
