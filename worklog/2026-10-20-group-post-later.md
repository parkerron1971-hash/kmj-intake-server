---
title: A group leader's Board post can go out later
date: 2026-10-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-20: "let''s continue so we can finish up". From the approved canvas "Church Groups, Together" (board Post: "Send later · Thursday at 9:00 AM")'
status: shipped
prs: [kmj-intake-server#1539]
migrations: [supabase/APPLY-2026-10-20-group-post-later.sql (applied)]
left_undone: ["changing a scheduled post's time (today: Send now, or take it down and write it again)"]
decisions: ["a time on the church's clock, 5 minutes to 30 days ahead, kept in UTC; checked by msg_screen when written", "until then only the group's leaders see it (Scheduled, Goes out …, Send now, Take it down); no note, no Got it, no email", "an after-hours alert is for now, so a scheduled post never rings; a pin waits until it goes out, then takes the top", "the job group_post_later (every 5 minutes) claims each due post once (told_at), sends the 'groups' note and the email to the rest; a post taken down before then never goes out", "fixed: the 7 PM chat note's sweep now reaches a church with only New messages on (it read only sermons, events or groups)"]
related: [2026-10-20-church-group-space.md, 2026-10-20-group-news-by-email.md, 2026-10-20-chat-evening.md]
---
`group_post_later.py` (new): `when_from`, `is_waiting`, `label`, `_go_out`, `sweep_tick`, `send_now`, the compose fold + CSS. `member_portal_groups`: `create_post(send_at=)`, the Board hides a waiting post from members and marks it for leaders, the card (Scheduled, Send now), the compose, POST /my/groups/post/now. `member_push`: the sweep's church list includes New messages. `kmj_intake_automation`: the job. The test fake learned `neq`.

Checks: 14 tests in `test_group_post_later.py` (13 sabotages, 12 caught; the other, the job's query not filtering taken-down posts, is held by the claim's own filter, tested); `group_post_later_db.mjs` 3 checks on PGlite, in CI; 183 tests across the group files. The Board with a scheduled post and the Send later fold rendered and looked at at 390. Rollback probe on the live database before applying.
