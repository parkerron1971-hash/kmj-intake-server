---
title: Text's people pieces (save a guest with a welcome follow-up, the prayer list, saved replies)
date: 2026-10-30
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-30: "let''s work on the list you gave for not built..." and "On as they ship"'
status: in review
prs: []
migrations: []
left_undone:
  - "Batch 2: announcements to one group, and sending later"
  - "The frontend for these endpoints is a separate solutionist-studio PR"
decisions:
  - "Save as guest names the keyword's number-named contact instead of creating a second one; a contact with a real name keeps it"
  - "The welcome follow-up never carries what they texted (a first text can be a prayer request); routed like a first check-in (route_answers=[])"
  - "A text on the prayer list is the pastors' unless the office shares it; consent_columns keeps danger words with the pastors; on_new hands a shared one to the Intercessor leader"
  - "Saved replies live in businesses.settings.sms_replies (no migration), 12 at most"
  - "Ships on (Kevin: 'On as they ship')"
related: [2026-10-29-texting-staff-mark-read]
---
`text_room.py`: POST /sms/guest, GET+POST /sms/prayer, GET+PUT /sms/replies.
Reads at viewer, writes at member; each handler checks whose business before
any read. Tests: `__tests__/test_text_room.py` (20).
