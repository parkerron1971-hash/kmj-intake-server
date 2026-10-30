---
title: Announcements to one group, and sent later
date: 2026-10-30
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-30: "let''s work on the list you gave for not built..." and "On as they ship"'
status: in review
prs: []
migrations: []
left_undone:
  - "The frontend (group picker, a time, what's scheduled) is a separate solutionist-studio PR"
decisions:
  - "A group announcement is that group's members with a number, still only those who said yes (said_yes_to_texts), and only an active group of this business"
  - "Sent later = a chief_scheduled_actions row of type sms_announcement written only by POST /sms/broadcast with send_at (1 minute to 60 days ahead); Chief's schedule_action can't make one (it takes ACTION_HANDLERS verbs only)"
  - "chief_scheduler hands it to sms_routing.run_scheduled_announcement, not the verb registry; at send time the author must still be admin, a card must be on file, and who said yes is read fresh"
  - "broadcast's sending moved into announce(); three source tests now inspect announce"
related: [2026-10-30-text-room-people]
---
New: GET /sms/groups (each active group's with-number and said-yes counts),
GET /sms/scheduled, DELETE /sms/scheduled/{id}; /sms/broadcast and its reach
take group_id; /sms/broadcast takes send_at. All admin, checked before any
read. Tests: `__tests__/test_sms_announcements.py` (19).
