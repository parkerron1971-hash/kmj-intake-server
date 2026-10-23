---
title: Chief drafts a note to each person who's been missing from a group
date: 2026-10-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-20: "let''s continue so we can finish up". From the approved canvas "Church Groups, Together" (board Lead: "Haven''t been in 3 weeks · Send the 3 notes / Read them first · Sent from you. Replies come to your messages.")'
status: shipped
prs: [kmj-intake-server#1544]
migrations: []
left_undone: []
decisions: ["on My group, a leader with an adult who missed the last three gatherings presses Draft a note to each: Chief (Haiku 5.5, never billed) writes one short note per person from first names only; when Chief can't, a plain note to start from, and the page says which", "Send opens the leader's own private chat with that person with the note written in; the leader changes anything and sends it through messaging's own rules and screen; nothing is sent for them", "a teen gets no Send and no Message link (an adult who isn't their parent can't message a teen privately), and a teen's name never goes to the model; when only teens are missing there's no Draft button", "only a group's own leader, only with messaging on, six drafts an hour per leader", "the wide Lead pages' top bar starts after the computer rail too (the back link sat under it)"]
related: [2026-10-20-group-lead.md]
---
`group_care.py` (new): `draft`, `parse`, `plain`, `render`, CARE_CSS. `member_portal_lead`: POST /my/lead/groups/notes; `_go` accepts My group; the top bar clears the rail. `group_lead`: the Draft button; no Message link for a teen. `member_portal_messaging`: /my/messages/to/<id>?say= carries the note into the chat box (escaped). `rate_limit`: care_notes. `member_portal_church`: the words.

Checks: 20 tests in `test_group_care.py` (16 sabotages caught). Rendered at 390 and 1280.
