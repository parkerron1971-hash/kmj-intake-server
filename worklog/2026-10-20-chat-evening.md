---
title: How you hear about a group's chat — every message, an evening summary at 7 PM, or only replies
date: 2026-10-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-20: "you can continue to work on things." Next from the approved canvas "Church Groups, Together" (board Notify: "Group chat: Every message · Evening summary · Off")'
status: shipped
prs: [kmj-intake-server#1535, solutionist-studio#1312]
migrations: [supabase/APPLY-2026-10-20-chat-evening.sql (applied)]
left_undone: ["mentions (the canvas's 'anything that mentions you'): the chat has no @mentions yet, so Off and the evening note count replies to you"]
decisions: ["per person per chat on msg_participants.notify: every (the default, what was live), evening, replies (shown as Off, like the canvas)", "evening = one note at 7 PM on the church's clock: how many new messages and who wrote them (first names only, a lock screen), and how many replied to you; only what's new since you read the chat or the last evening note (summed_at), within 24 hours; never your own; once a day (ref_id); only people still in the chat, with messaging on, who didn't decline or mute it", "Off still hears a reply to one of their own messages, right away", "an after-hours alert rings whatever was chosen here, for anyone who lets alerts ring: it's the one note that can't wait", "direct messages always note; notes never say what a message says", "the choice sits under each chat (Notes: …) and in Notifications under Group chats; a choice is saved only when it reads back that way"]
related: [2026-10-20-quiet-hours-after-hours-alert.md, 2026-10-20-group-chat-inside-the-group.md]
---
`group_chat_notify.py` (new): the levels, `hears_each`, `choose` / `mine` / `my_chats`, the control and the Notifications section + CSS, `reply_note`, `evening` (the 7 PM sweep). `member_push`: `chat_recipients(ring=, everyone=)`, `tell_chat(replied_to=)`, the evening note in `sweep_tick` for churches with "New messages" on, the Group chats section on Notifications. `member_portal_messaging`: participants read their choice; a send passes what it replies to. `member_portal_groups`: the control under the chat, the route /my/groups/chat/notify. `member_portal`: Notifications loads the chats. `member_portal_church`: the words; /my/notifications is a place to come back to.

Checks: 14 tests in `test_group_chat_notify.py` (20 sabotages, 17 caught; the 3 that weren't are each held a second way: a reply to yourself is never a recipient, a bad level fails the read-back, and the participants read is now asserted on the query itself); `chat_evening_db.mjs` 7 checks on PGlite, in CI (3 sabotages of the migration caught). The chat's control and Notifications rendered and looked at at 390. Rollback probe on the live database before applying.
