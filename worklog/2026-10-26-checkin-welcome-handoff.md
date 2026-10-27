---
title: A first-time check-in starts a welcome follow-up (kids desk + the office's First time)
date: 2026-10-26
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-26, his "who sees what" plan for churches: "yes, a first-time check-in starts a welcome follow-up"'
status: shipped
prs: [kmj-intake-server#1594]
migrations: []
left_undone:
  - "A name-only first-time guest (checked in without a Members record) can't be followed up: church_follow_ups needs a contact. They stay on the First-time guests list"
  - "Someone already in follow-up (a Plan your visit card, say) gets no note that they came; their open follow-up is left as it is"
  - "Leaders & roles still describes the welcome job as Plan your visit cards and Connect cards; first check-ins ride the connect stream, so a church whose roles take connect cards gets them"
  - "The kids desk counts the children checked in with the first tap; a sibling checked in a minute later isn't added to the line"
decisions:
  - "Two writers: the kids desk (kids_checkin.do_checkin, every way in: team seat, station, self kiosk) hands on inline, in a background thread; the office's First time in Attendance is written from the app straight to attendance, so the follow-up sweep (every 10 minutes) picks up the last 24 hours of first_time rows"
  - "A member's phone check-in and online 'I'm here' never start one: the member page makes no contacts, so those are people the church already has"
  - "New, at the kids desk (nobody marks it): the family and the adult who brought them were both added in the last 7 days, no child of theirs was checked in at another occasion, and none of its adults was at another occasion. A family typed in from old records is not new on its first Sunday in the app"
  - "New, from the office: the office said First time; skipped when the family was at another occasion"
  - "One per family per first visit, for the adult (whoever dropped the children off, else a parent or guardian before a grandparent, the first added): receipt first-visit:h:<household> or first-visit:c:<contact> on church_follow_ups.source_event, which the existing unique index keeps once. Anyone in the family with an open or handed-back follow-up, or one finished (done or closed) in the last 2 days, keeps that one: the sweep re-reads a First time row for 24 hours, so a card's follow-up finished meanwhile must not open a second for the same visit (review fix)"
  - "Routed like a connect card through church_follow_up.start (kind connect: Reach out, then Invite to a next step), so the welcome role gets it, else the senior role, else the office, and the late ladder climbs as for any card. The reason reads 'First check-ins go to the Welcome Team lead.' The occasion's name is shown to the leader but never routes (a 'Community Meal' is not a care need)"
  - "Best effort: a failure prints and never blocks, slows or fails the check-in; every read that decides 'new' stops the welcome when it fails"
related: [2026-10-17-church-leaders.md, 2026-10-17-sunday-checkin.md, 2026-10-23-church-areas-map.md]
---
First-timers never reached a follow-up: follow-ups started only from cards
and forms (`on_intake_form`, `on_connect_card`), while first visits sat on
the First-time guests list (`church_reads.first_time_guests`).

- **`church_first_visit.py`** (new): `after_kids_checkin` (the kids desk's
  hook, switched, in the background), `welcome_kids` (is this family new;
  their adult), and `sweep` (the office's First time rows, batched: a quiet
  sweep is three reads).
- **`church_follow_up.py`**: `on_first_check_in` beside the card hooks
  (open or recently finished check across the family, the family receipt, card "First check-in",
  the line "First time at Sunday Worship · 2 kids checked in"); `choose`
  and `start` take `what` (the words in the reason) and `start` takes
  `route_answers`; the sweep runs the first-visit pass first so the leader
  is told in the same pass.
- **`kids_checkin.py`**: `do_checkin` calls the hook after new children are
  saved, wrapped so nothing reaches the check-in.

Tests: `__tests__/test_church_first_visit.py` (30), on an in-memory
PostgREST through the real kids check-in route. 19 sabotages each fail at
least one (no switch, no open check, no family or guardian age, no receipt,
a blocking hook, an unguarded hook, earlier visits ignored, a failed read
read as new, one per child, grandparent first, not a church let through,
the occasion routing, the sweep without the family key, finished
follow-ups ignored, a quiet window too short or endless, ...).

Shipped: merged and switched on 2026-10-26 evening (Kevin set CHURCH_AREAS=on on kmj-intake-server and kmj-intake-worker; checked both read exactly on; the worker redeployed 20:09 EDT).
