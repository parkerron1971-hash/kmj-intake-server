---
title: One Visitor flow room (server) — the board leaves guests to it, and every guest call's link opens it
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-21, on Love City: "you see three tabs guest, follow up board, visitor flow.. all of these at once"; he picked "One Visitor flow room: the new room takes the name Visitor flow and its spot, the old chart moves into its Scorecard tab, the Guests row goes away, the Follow-up board stays for baptism, serve and other cards and stops listing guests". Builder 7: the plumbing (the lead does the room''s look and the Scorecard chart)'
status: in review
prs: [kmj-intake-server (this PR), solutionist-studio (the one Visitor flow row, the board's line, Hand to someone else)]
migrations: []
left_undone:
  - "Live only where GUEST_PATH lets it (unset = owner: the platform's own church). Off: the board, the links and My week are exactly as before"
  - "The board no longer lists a guest's follow-up for a login that has Visitor flow, so its notes, Mark step done and Close for guests aren't on any office screen until the room shows them (the lead's room design): the routes (note, step, close) are unchanged and take any follow-up"
  - "Visitor flow's Help Center card is true of both its pages (the room and the counts page): its two answers still describe the counts page (Heard from someone, Coming back bar), so they hold at Love City only once the old chart is in the room's Scorecard (the lead's PR); the room's own answers wait for GUEST_PATH=on for every church"
  - "church_findway.json carries only this PR's two pages (Follow-up board, Visitor flow): the frontend's map also has two Areas answers about giving access that ship with a server switch still off, so they were left out of the export on purpose"
decisions:
  - "GET /church/follow-ups?guests=room leaves first-time guests' welcome follow-ups (guest_path.is_guest_follow_up) off the board, out of its counts and out of each leader's load, and answers guests_in_room {open}, only where church_guests.room_open says this login has the room (the path on, a church, the room's gate; anything unread is a no, so the board keeps its guests). Without the param, today's board for older apps"
  - "GET /church/follow-ups?leaders_only=true is the board's Hand to list alone (everyone holding an active role, each with their open follow-ups), for a guest's sheet in Visitor flow, which hands them on through the board's own POST /church/follow-ups/{id}/reassign (same permissions). An older server ignores it and answers the whole board, which carries the same list"
  - "Visitor flow (church_guests' gate) opens for People & care's areas as before and now also for a login that makes the welcome calls: whoever does First-time guests (church_duties.holds), or the caller of a guest whose welcome follow-up is open or handed back (church_over login_person). Every guest call's link opens the room, so whoever gets one must be able to open it. guest_brief.may_read uses the same gate. A read that fails is a 503 in the room"
  - "Links: guest_calls NAV operate:guests (the room's own id; the app aliases it to the Visitor flow row, and an app from before this change opens the room on it too), LABEL Open Visitor flow (tell_login and office_alert defaults), and the words (When you've talked, open them in Visitor flow and press How did it go?; hand them to someone else in Visitor flow). Replies keep operate:sms:<id> (guest_replies)"
  - "The sweep (church_follow_up._alert_on): every office alert about a guest's follow-up while the path is on says Open Visitor flow (the generic path too, for guests the path didn't route); the senior pastor's email and the role-chain email say hand them on in Visitor flow (where_worked). Every other card is unchanged; church_prayer keeps its own"
  - "My week: First-time guests' door, a guest handed to this login, and the whole church's lines for guests with no one / late welcome calls open Visitor flow (ROOM_DOOR, door_of) where the path is on; other cards keep the board. DOOR stays static (every church's)"
  - "Chief: chief_office.place(duty, business) says People › New and in need › Visitor flow for First-time guests where the path is on (THE OFFICE, job_of, list_duties); church_findway reads operate:guests as grow:funnel; system_destinations aliases operate/guests to grow/funnel"
  - "The room's next move points at the guest's sheet: a late call's action is Open <first name>, and a guest with no one says Open them and hand them to someone"
related: [2026-11-20-guest-welcome-path.md, 2026-11-20-guests-room.md, 2026-11-20-who-calls-our-guests.md, 2026-11-20-guest-call-brief.md, 2026-11-20-guest-replies.md]
---
Before building I read both repos' worklogs: the Welcome Path umbrella and
every entry it links (the Guests room, Who calls our guests, the call brief,
replies, weeks two to six, every door). Nothing had merged the rooms.

`church_follow_up.py`: board's skip_guests / leaders_only, `_leader_load`,
`in_room`, `_alert_on`, `where_worked`, the sweep's alerts and emails.
`church_router.py`: the guests and leaders_only params. `church_guests.py`:
`room_ok`, `room_open`, `_calls_guests`, the 403's name, the next move's
words. `guest_calls.py`: NAV, LABEL, the words. `guest_brief.py`: may_read,
People & Care's note. `church_my_week.py`: ROOM_DOOR, door_of, the lines.
`chief_office.py` / `chief_duties.py` / `chief_church_jobs.py`: place with
the business. `church_findway.py` / `.json`, `system_destinations.json`.

Tests: `__tests__/test_visitor_flow_one_room.py` (25), and the guests room,
guest calls, replies and Chief's places updated. 4,019 passed across the 97
test files that import what changed.
