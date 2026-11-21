---
title: Sunday's tells - the sermon draft, the missing count, the flyer
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: "yes go with the plan and make those small fixes as well (the missing tells on Love City's connection map)"
status: in progress
prs: [kmj-intake-server#2040]
migrations: []
left_undone:
  - "CHURCH_TELLS is owner (Love City only) by default; switch on for every church after Love City has a Sunday of these"
decisions:
  - "sermon_draft tells only for a draft made from a recording (its video_url is our watch link, stream_relay_router.watch_session); a sermon saved unpublished by hand is that person's own"
  - "count_missing uses the weekly attendance job's own rule (church_work_checks.sunday_counted) so the tell and My week agree; a service today is a Sunday plan or a Services & Events occasion that is a service; a read that fails or a headcount with no day tells nothing"
  - "flyer_needed: public events only (a service, a church-only or invite-only occasion needs none), flyer_of is the one flyer reader; already-told events are skipped before the cap of 3 so the 4th gets its turn"
related: [2026-11-21-church-tells.md, 2026-11-21-event-volunteers.md]
---
`church_tells_sunday.py` holds three of church_tells' finders: a sermon
draft from the stream relay is ready (sermons), Sunday's count isn't in by
1 PM on the church's clock (attendance), and a public event in the next 14
days has no flyer (flyers, the soonest 3 a sweep). Each reads as the server,
only this church's rows, and gives nothing when a read fails.
