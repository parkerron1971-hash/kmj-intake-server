---
title: Chief plans an event's volunteers and flyer (event volunteers S5, Chief)
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-20: "when a event is made there should be questions asked normal service volunteers or special volunteers ... and also a way to inser flyer for like a thumbnail to this event", then "go" on the proposal; S5 of docs/EVENT_VOLUNTEERS.md'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: [supabase/APPLY-2026-11-21-event-volunteers.sql (NOT APPLIED: until then Chief saves events exactly as today)]
left_undone:
  - "Switch-on PR on a Thursday (EVENT_VOLUNTEERS=on and CHURCH_EVENT_VOLUNTEERS=on), with What's New and the Help Center: not in this PR"
  - "Changing a waiting ask's numbers from a chat (the PATCH route): Chief says the server's words and points at the event's page"
  - "No live Chief eval was run (they bill production): the turn line and the look's wording are pinned by tests only"
decisions:
  - "Chief calls the office's own code as the signed-in login: status (gate + places), ask_blocks (factored out of the POST route), clean_needs, the note, gallery_reader/_artwork, then attach_flyer (factored out of the PUT route), ask (the POST route) and changed; event_volunteers.enabled() is the status route's own condition, factored out"
  - "Show before saving is code: the first send saves nothing and returns the look, a second send in the same turn doesn't count, a confirmed send on a tainted turn is held; make alone has no look"
  - "Whatever would stop the ask is said before saving, in the server's words; a refusal only possible after the save keeps the event and says what didn't go"
  - "Closed switch, no migration, nobody signed in (unattended, an outside agent), a Viewer, a non-office login: the event saves as today and the result says why"
  - "A role Chief makes writes kids and open outright (false unless said) only where asking is open for the church; untouched roles keep their keys; closed churches get no tick, because public_role honours open:false regardless of the switch"
  - "make: the only server path is the Light Table (owner-only, STUDIO_LIGHT_TABLE, class C and paid, drawn in the background, attached only on Use as the flyer); Chief never starts it from a save and hands over the office's way"
  - "event_volunteers (how full is my event) is Chief's alone (needs the login, like serving_week), gated like asking, the picture's own name rules; notes fenced and tainting"
  - "The availability line rides the turn's tail beside the leaders schedule's (owner mode opens it by login; a Viewer's line differs); the universal and per-business segments are unchanged"
related: [2026-11-21-event-volunteers.md, 2026-11-18-church-schedule.md]
---
Before building I read both repos' work logs. The backend's
`2026-11-21-event-volunteers.md` (S1-S3) and the frontend's two S4 logs
(`2026-11-21-event-volunteers-new-event.md`, `-event-page.md`) are the pieces
this connects. The S4a log settled what "Ask Chief" means in the office: the
Light Table on the saved event. The Light Table logs (11-09, 11-11) settled
what making a flyer costs. The only open PR on these files, #1465 (booking
calendar copies), doesn't touch the event code.

New: `chief_event_volunteers.py`, and its tests in
`__tests__/test_chief_event_volunteers.py` (60 tests).

Changed:
- `chief_of_staff.py`: create and update_module_entry, the handler, and the
  turn's line.
- `chief_roster.py`: the two ticks.
- `event_volunteers.py`: `enabled`, `ask_blocks` and `attach_flyer` factored
  out, with no change in behaviour.
- `mcp_server.py`: the write tools' keys.
- `chief_tool_loop.py`, `action_registry.py` and `chief_areas.py`: the read
  wired in.
- `__tests__/test_tool_loop.py`: the Chief-only reads' review list.

Each rule was broken once on purpose, and its test went red (20 sabotages,
listed in the PR). The decisions beyond the spec are in
`docs/EVENT_VOLUNTEERS.md` section 11, S5.
