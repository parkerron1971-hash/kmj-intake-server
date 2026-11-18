---
title: An event's volunteer list in Services & Events, and a room request for whoever runs events
date: 2026-11-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "Laquesha couldn''t make event volunteer list. can we make sure that she has access and ability to make list and or make volunteers list." Then (approved): say the events page when people can sign up there; point Sunday places at Who serves when, not a text'
status: in review
prs: [kmj-intake-server (this PR), solutionist-studio (the Rooms & spaces menu PR)]
migrations: []
left_undone:
  - "Who serves when (sunday_planning, worship_services) schedules Sundays only: an event's or an outreach night's volunteers can't be scheduled or asked there. A later feature"
  - "Chief has no verb to file a room request (church_spaces); Laquesha asks on Rooms & spaces"
  - "Chief can't take a role off an event: roles named again change their number, others stay; removing one is done in the room, where its people show"
  - "events_url_for_site names the platform subdomain, never a custom domain (as every caller does today)"
decisions:
  - "No new room for it: an event's volunteers live on the event in the church's events room (event_roster), which every office login already adds to; a new list stays the owner's and admins' (chief_areas.OWNERS unchanged)"
  - "Chief never writes a role by hand: create_module_entry/update_module_entry take roles and volunteers and chief_roster gives each role the app's own id (newRoleId), because both readers drop a role without one"
  - "A new event's roles are the ones asked for; on an event already there a role named again keeps its id (nobody falls off it) and takes its number, the others stay"
  - "A lane's refused new list for an event's volunteers or sign-ups says where it goes (the events room by name) and that Chief can add it there; any other refused new list reads as before"
  - "The room request: a Manager without rooms that holds events or outreach_nights acts as an office Member in church_spaces (role 'member', asks true): it asks, never approves (told whose job the rooms are), keeps no spaces, reads no Rentals list, no amounts, and no outside renter's email or phone"
  - "The events page is named only when the page's own rules put the event on it with an open role (switched on, public, dated within 90 days) and no paid sign-up is in the way"
related: [2026-11-02-duty-split.md, 2026-11-01-office-gates-duties.md]
---
Found in prod (read for the ask, not by this session): Laquesha is a Manager
(Sunday & Serving, Worship & media alone) holding `events` and
`outreach_nights`. Her Chief emitted `propose_module_from_intake` and
`chief_areas` refused it, while Love City's "Services & Events" room already
existed.

- `chief_roster.py` (new): the roles and people in the room's shape.
- `chief_of_staff.py`: `handle_create_module_entry` / `handle_update_module_entry`
  shape an event_roster entry, check linked people are the church's, and say
  the room, its roles and (when people can sign up there) the events page;
  `_execute_actions` swaps a lane's refused new list for `chief_areas.room_hint`.
- `mcp_server.py`: the two write tools carry `roles` and `volunteers`.
- `chief_prompt.py`: ROUTING 0b and EVENTS' VOLUNTEERS line (both kept by the
  short brief).
- `church_spaces.py`: the room request for `events` / `outreach_nights`.
- Tests: `__tests__/test_chief_roster.py` (new), `__tests__/test_church_spaces.py`.
  `docs/CHURCH_DUTIES.md`: "An event's room request and volunteer list".
