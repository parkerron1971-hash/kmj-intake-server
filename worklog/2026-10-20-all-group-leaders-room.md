---
title: All group leaders — one chat for everyone who leads a group and the church's pastors
date: 2026-10-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-20: "yes all group leaders room would be great"; part 2 of the approved canvas "Church Groups, Together"'
status: shipped
prs: [kmj-intake-server#1523, solutionist-studio#1297]
migrations: [supabase/APPLY-2026-10-20-leaders-room.sql (applied)]
left_undone: ["part 3: the group prayer wall, gatherings (RSVP, I'm here, the roll from the phone, bring-a-dish), study questions", "part 4: quiet hours and the after-hours alert, email for group news, the evening summary, the office's health page and a word to every group, the leader's desk, groups on the Lead tab"]
decisions: ["the room is a messaging thread of a new kind ('leaders'), not a group: it never shows in Groups, Find a group, counts or the export as a group", "who's in it is read live, never copied: leaders of ACTIVE groups plus ACTIVE senior/pastoral church roles (the same pastoral rule as safety officers); an invited pastor or a non-pastoral role isn't in it", "every message is still checked (msg_screen), reportable, and visible to the safety officers' logged reviews like any chat; no take-down in the room (pastors use Report)", "doors only for the people in it and only once messaging is on: Connect gets a 'For leaders' row, the Lead page a card; Messages lists it and opens its page", "being in the room doesn't make two people 'share a group' for direct messages"]
related: [2026-10-20-group-chat-inside-the-group.md, 2026-10-20-safety-officers-from-pastors.md]
---
`member_portal_messaging.py`: `leaders_room_people` / `in_leaders_room` (who's in it, live), `ensure_leaders_thread` (one per church), `chat_access` reads the room's people for a `leaders` thread, the inbox lists it as "All group leaders", opening it in Messages goes to its page, and a `back` to /my/groups/leaders is allowed. `member_portal_groups.py`: /my/groups/leaders (`room_view`, `render_room`) reuses the group Chat tab (reactions, replies, report, live refresh); anyone else sees "This room is for...". `member_portal_church.py` + `member_portal.py`: the Connect door. `member_portal_lead.py`: the Lead page card. `member_push.py`: "New message in All group leaders", opening the room.

Checks: 13 tests in `test_member_leaders_room.py` (12 sabotages caught: archived groups counted, any role counted, invited counted, a failed read as empty, the page for anyone, access ignoring the room, the inbox missing it, the wrong redirect, a door with messaging off, no Lead door, the push link, the way back); `leaders_room_db.mjs` 13 checks on PGlite, in CI (sabotaging the shape rule or the one-per-church index goes red); 1304 tests across every file touching these modules; the room, its "not for you" page, the Connect door and the Lead card rendered and looked at at 390 (and the room at 1280). Rollback probe on the live database before applying.
