---
title: Church mail alerts when new mail comes, and archive, delete and Trash
date: 2026-11-14
agent: Claude Code (Claude Opus 5.5)
asked: "yes do the mock for 1 and 2 (new-mail alerts; archive and delete) ... I love the design. lets build it"
status: in progress
prs: ["kmj-intake-server#1845"]
migrations: [supabase/APPLY-2026-11-14-church-mail-tidy-alerts.sql (applied 2026-11-14)]
left_undone: []
decisions:
  - "Built from the mock 1fGHqCVMe9fxwceAbjbaJZ. Alerts: church_mail.deliver marks an inbox row alert_at and church_mail_alerts.on_new sends at once (a thread off the webhook) unless it's the church's quiet hours (member_push.quiet_hour, the hours set under Text); the worker's sweep (2 min) sends what waited, several from one box as one ('Office · 3 new'), and anything a day late never alerts. Claiming alerted_at is null first means never twice."
  - "Who hears: whoever the box reaches now (church_mail.reach), each by church_mail_people.alerts (all | mine | off, null = all) and alert_push. Nobody hears of a message they already opened or archived, or that was deleted. Held mail, prayer@ and replies that went out as the box never alert; rows from before (alert_at null) never do."
  - "Push nav is operate:email with data {tray, mail}; the frontend opens that message."
  - "The bell does NOT write chief_notifications: that table is business-wide (every login sees it), and a person's own box is private. GET /church-mail/alerts lists the login's new mail of the week straight from church_mail, so an answer on a shared box clears it for everyone with who answered, and nothing can drift."
  - "Archive is per person (archived_by, like read_by): out of my lists and counts, in my Archive. Delete is for the whole box (deleted_at/by/name): out for everyone, in the box's Trash for 30 days, anyone on the box can restore; Empty Trash deletes for good what's in the boxes I read; the worker's trash sweep (6 h) deletes anything 30 days gone. Held mail keeps its own delete; Sent can't be archived or deleted yet."
related: [2026-11-13-church-mail-room.md, 2026-11-14-church-mail-signature.md]
---
Kevin approved the mock for new-mail alerts and archive/delete. The server now
alerts each person's phone when church mail comes (by their choice, honouring
quiet hours), feeds the bell from the mail itself, and keeps archive per person
and a 30-day Trash per box.
