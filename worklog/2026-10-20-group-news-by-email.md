---
title: A church group's news by email — "Email the rest" on a leader's post, and "Email me if my phone misses it"
date: 2026-10-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-20 (decision 4): phone alerts AND email for group news ("yes this would be great"); the approved canvas "Church Groups, Together", boards Post and Notify'
status: shipped
prs: [kmj-intake-server#1525, solutionist-studio#1299]
migrations: [supabase/APPLY-2026-10-20-group-email.sql (applied)]
left_undone: ["the evening chat summary (Every message / Evening summary / Off per group)", "Send later on a leader's post", "part 3: prayer wall, gatherings, study questions"]
decisions: ["'Email the rest' is the leader's choice per post, off by default: the group's people with NO phone set up for the member app (no member_push_subscriptions row)", "'Email me if my phone misses it' is the member's choice, off by default: a leader's post they haven't opened (group_post_seen) an hour after it went up; checked once per post (missed_checked_at claimed first) within 6 hours", "never to a known minor (a birthdate under 18), never to the author, only a valid address; one email per post per person (Resend idempotency key group-post-<post>-<person>)", "from the church's name, branded layout, one-click unsubscribe (email_sender); the button opens the post in the church's own member app (its domain first)", "the post's words go out: they were checked (msg_screen) before it went up", "the leader's card counts it ('4 by email')"]
related: [2026-10-20-quiet-hours-after-hours-alert.md, 2026-10-20-church-group-space.md]
---
`group_email.py` (new): `email_rest` (off the request via `spawn`), `sweep_tick` (every 15 minutes, scheduled in kmj_intake_automation), `app_url`, the message. `member_portal_groups`: the Board form's "Email the people who haven't set the app up on a phone", `create_post(email_rest=)`, the leader's card "N by email". `member_push`: `quiet_prefs` / `save_quiet` carry `email_missed`; /my/notifications gets "By email" where group news is on; the page's checkboxes no longer shrink when a label wraps.

Checks: 9 tests in `test_group_email.py` (13 sabotages caught: phones emailed, the author emailed, teens emailed, the birthday math, one failure stopping all, no idempotency, the church's domain ignored, not counted, emailing who opened it, twice, too early, always emailing, the box shown without group news); `group_email_db.mjs` 6 checks on PGlite, in CI; 3846 tests across every file touching these modules; the Board form, the notifications page and the email itself rendered and looked at at 390. Rollback probe on the live database before applying.
