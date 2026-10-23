---
title: The leader's desk on a computer
date: 2026-10-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-20: "let''s continue so we can finish up". From the approved canvas "Church Groups, Together" (board Desk: "The leader''s desk": You lead · You''re in · For leaders; the group''s chat with Open video and Post to the board; Thursday · Take attendance · 11 going · 2 maybe · 1 can''t · 4 no answer; Needs you; Pinned)'
status: shipped
prs: [kmj-intake-server#1549]
migrations: []
left_undone: ["the canvas's Search messages and people and the Remind the ones who haven't answered button aren't built, so they aren't shown"]
decisions: ["My group (/my/lead/groups/<id>) from 1240px wide is three columns: the leader's chats, the group's chat, and My group; the phone keeps My group as it was, with the next gathering card now on top for both", "the chats and the chat come from GET /my/lead/groups/<id>/desk (JSON) only on a wide screen, so a phone never pays for them and a chat is marked read only when it's shown; without the script the middle points to the group chat", "the left column groups the leader's chats as You lead (that group's desk), You're in (the group's chat), For leaders (the room) and Messages (up to six), with unread counts except for the open one", "the middle is the group's own chat with its tabs, Open video (or Join) and Post to the board; anything sent, voted, reacted or posted there comes back to the desk", "the next gathering card: the day, the place, the time, going/maybe/can't/no answer, and Take attendance on the day"]
related: [2026-10-20-group-lead.md, 2026-10-20-chat-polls.md, 2026-10-20-chat-photos.md]
---
`group_desk.py` (new): `side`, `middle`, `gathering`, `script`, `shell`, DESK_CSS. `member_portal_lead`: GET /my/lead/groups/{id}/desk; My group wrapped in the desk with the gathering card. `member_portal_messaging`: inbox rows carry their group; a desk address is a way back. `member_portal_church`: `_back` allows a desk address. `member_portal_groups`: the chat scrolls its own box when it has one.

Checks: 10 tests in `test_group_desk.py` (14 sabotages caught). Rendered at 1440, 1280 and 390.
