---
title: Safety officers from a church's Pastors and Elders, working the Safety room from their member app's Lead tab
date: 2026-10-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-20: yes to safety officers picked "from the Pastors and Elders you''ve already named" ("option two is good and is the start choice"); part 2 of the approved canvas "Church Groups, Together"'
status: shipped
prs: [kmj-intake-server#1521, solutionist-studio#1294]
migrations: [supabase/APPLY-2026-10-20-member-safety-officers.sql (applied)]
left_undone: ["part 2 continues: the chat inside the group page (reactions, replies, a leader hides a message, chat on/off and who writes), the all-group-leaders room", "a member officer isn't told when they're named (no push or email yet); the owner tells them"]
decisions: ["eligible = an ACTIVE role whose job is senior or pastoral (Pastors, Elders, Associate/Executive Pastors, Ministers); an invited role doesn't count until they say yes", "someone with a team login, or the owner, isn't offered as a pastoral officer: one person never counts twice toward the two", "an officer stays one only while named AND holding an active pastoral role; a role that ends shuts the Safety room and the owner sees 'No pastoral role now' to stand them down", "the whole-chat page opens only within 30 minutes of a look logged by that officer"]
related: [2026-10-20-church-group-space.md, 2026-10-02 messaging (BE#1196)]
---
`msg_member_officers` holds the church members the owner named officers; `messaging_router` offers the church's active pastoral leaders (GET /messaging/settings `leaders`), takes `contact_id` on POST /messaging/officers, and counts both kinds toward the two officers. The Safety room's work (the held/reported queue, release/remove, close a report, pause someone, open a whole chat with a logged reason) moved into shared functions that the team endpoints and the new member page both call. `member_portal_safety.py` is the member page: /my/lead/safety (a door on the Lead page shows how many wait) and /my/lead/safety/chat/<thread> after a logged look; `msg_staff_views` now takes a contact_id (a check makes it name someone).

Checks: 15 tests in `test_member_safety_officers.py` (6 sabotages caught: invited counted, a login offered, enabling with team officers only, no role check, the chat page without a logged look, acting without the officer check); `member_safety_officers_db.mjs` 7 checks on PGlite; the Safety room rendered and looked at at 390 wide.
