---
title: The roll — a church's People page in one read (server)
date: 2026-11-01
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, on the Members Roll Redesign canvas (BF38H75nNDSaxEC1ZJFFoe): "the design works ... the design is good", the person page bigger, then "build this"'
status: shipped
prs: [kmj-intake-server#1685, solutionist-studio#1439, solutionist-studio#1441, solutionist-studio#1444]
migrations: []
left_undone:
  - "Not yet run against Love City's real rows: a read-only production probe was refused by the permission system. The office page will show it the first time Kevin opens People"
  - "Who serves when (serve_positions, serve_trained) has no ledger row in docs/MIGRATIONS.md; the roll reads it softly and goes on without it"
decisions:
  - "Read-only, no migration: every piece already lives somewhere (contacts, attendance, households, groups, Who serves when, leader roles, the register, first-time guests); church_roll.py only gathers it"
  - "Sundays are counted the Monday shepherding sweep's way (church_shepherd_signals.sunday_rule and _entry_days): recorded Sundays only, the church's clock, a class night never one. P in person, O online (in person wins), M missed, N before a first visit (a first_time check-in, else the day the record was made, never for an import)"
  - "Drifting is church_shepherd_signals.drift on the family's Sundays (any of them came), or a person's own with no family; inactive never drifts"
  - "Leader = status vip, an active church_leader_roles row, or leading a group. Serving = a team they belong to or a position they're trained for"
  - "Gate: business_access(manager) like Shepherding and Families; with Who sees what on, a staff login needs People & care or the Office in its areas. Care is a flag only (an open care-stream follow-up card), never its words; giving shows for owner, admin or accountant while Giving & money is open (church_keys)"
  - "Chief's line on a person is a rule over what's on file (drifting, new guest, baptism, birthday, a guest coming back, no group, not serving), not a model call: free, and never says what the record can't back"
  - "A person's page reuses the roll read for 90 seconds per replica; the roll itself always reads fresh"
related: [2026-10-18-shepherding-signals.md, 2026-10-17-sunday-checkin.md]
---
`church_roll.py` serves the new church People page: `GET /church/roll`
(everyone, their last 8 recorded Sundays, families with shepherds, groups,
serving, and This week: new guests nobody reached, drifting families,
birthdays this week, the next Baptism Sunday) and
`GET /church/roll/person/{contact_id}` (family, In the church, Reach,
Lately, Chief's next step, a care flag, giving for money logins).

Tests: `__tests__/test_church_roll.py` (18), alarms rehearsed (in person
over online; an import is never "before a first visit").

Switched on for everyone 2026-11-01 (Kevin: "switch it on for everyone"),
ahead of the usual Thursday at his word: CHURCH_ROLL=on set on
kmj-intake-server and kmj-intake-worker (both redeployed), and the app's
switch with its What's New entry (solutionist-studio#1444).
