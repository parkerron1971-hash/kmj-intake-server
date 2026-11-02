---
title: A church's office logins are in the leaders room and get the Monday leaders note
date: 2026-11-01
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-01: "go through each admin that is connected and make sure that there access point have everything that is connected to there role" … "every area that is block setup or partly. lets make sure we build"'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Tasks handed to an office login (tasks.assigned_to) still send nothing, and a late one goes to no one: the next PR (a migration for who handed it plus told stamps on the seat side, and the hourly sweep telling the seat, with late ones going to whoever handed it and the Executive Pastor)"
  - "The admins still hold no church role in Leaders & roles. That comes with the duties layer (Kevin, 11-01: I set Love City up directly; Chief does other churches)"
decisions:
  - "An office login is an active Admin or Manager seat. Member and viewer seats, and invited or removed ones, are not."
  - "As one of the church's people: the record the seat is tied to (business_users.contact_id), else the one its email names (match_contact, which names no one for a family address it can't tell apart)."
  - "A failed read of the logins leaves the room as the leaders alone, never empty or None (the room gates the leaders chat, the leaders note and the Hand to list)."
  - "The Hand to list keeps office logins as logins, so a task for one lands in their office My week, not a Lead tab they don't use."
  - "seat_person keeps an email-matched record on the seat (only where nothing is tied yet). On 11-01, three of Love City's five logins were tied by email alone."
related: [2026-10-27-leaders-room-departments.md, 2026-10-28-seat-person.md]
---
`member_portal_messaging.py`: `office_contacts`, used by
`leaders_room_people`. `church_leader_tasks.leaders` drops office logins
from the Hand to leaders. `business_users_router.py`: `_keep_contact`,
plus `seat_person` keeps the match. Leaders room membership opens only the
leaders chat (`member_portal_groups.room_view`, `group_chat_notify`).
Because the Monday note goes to the room (`church_leaders_note.recipients`),
the admins get it too. Tests: `__tests__/test_office_logins_in_the_loop.py`
(8). The leaders room, leaders note, leader tasks, messaging, safety, seat
person, office door and area tests still pass (618 across 28 files).
