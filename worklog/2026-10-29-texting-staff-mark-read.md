---
title: The team's reading clears a text (POST /sms/read)
date: 2026-10-29
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-29: "yes do small fix" (office logins could read texts, but only the owner could mark them read)'
status: in review
prs: [kmj-intake-server#1645]
migrations: []
left_undone:
  - "The frontend's Text room switches its mark-read to this endpoint in a separate solutionist-studio PR"
decisions:
  - "A server endpoint, not a seat UPDATE policy: RLS can't narrow a write to the read column, so a policy would let a seat rewrite message bodies"
  - "Member and above, not viewer: the people who can answer a text are the ones whose reading should clear it"
  - "/sms/conversation now returns sent_by (and contact_id), so a person's thread can label Chief's and automatic texts"
related: []
---
Every active seat can read `sms_messages` (APPLY-2026-07-31-seat-access-data-plane.sql),
but its UPDATE policy is the owner's alone, so the Text room's browser PATCH
matched nothing for an office login and the texts stayed unread for everyone.
`POST /sms/read {business_id, contact_id?, phone?}` writes `read: true` as the
server on inbound unread texts: by contact, and by number for texts tied to no
one (`contact_id is null`, phone `%2B`-encoded). It answers `{ok, marked}`, or
503 when the write fails. Tests: `__tests__/test_sms_mark_read.py`; the
handler is in the tenant-isolation guard list at "member".
