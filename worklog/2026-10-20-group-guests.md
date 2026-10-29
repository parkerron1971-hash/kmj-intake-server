---
title: First-time guests by name on a leader's roll
date: 2026-10-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-20: "let''s continue so we can finish up". From the approved canvas "Church Groups, Together" (board Roll: "First name · The office welcomes them as a first-time guest. Add a phone only if they said yes to hearing from us.")'
status: shipped
prs: [kmj-intake-server#1541, solutionist-studio#1318]
migrations: [supabase/APPLY-2026-10-20-group-guests.sql (applied)]
left_undone: []
decisions: ["a leader names a guest on the day only (the roll's window): a first name, a phone only with their yes (digits and + ( ) - . kept)", "the gathering's guest count keeps up with the named guests and never drops below them; more who didn't give a name still count", "a leader takes a guest off today's list; members never see the list", "the office reads them and links who they became (UPDATE only on contact_id); the office's Groups page welcomes them in the frontend PR", "exported, never re-imported"]
related: [2026-10-20-group-gatherings.md]
---
`group_gatherings`: `guests`, `add_guest`, `remove_guest`, `_today_meeting`, the roll's count, the roll card's First-time guests (Add guest). `member_portal_groups`: POST /my/groups/meet/guest and /guest/remove. `member_portal_church`: the words. `account_lifecycle`: group_meeting_guests exported, never re-imported. Also carries the quiet-hours test's clock fix.

Checks: 9 tests in `test_group_guests.py` (8 sabotages caught); `group_guests_db.mjs` 10 checks on PGlite, in CI. Rollback probe on the live database before applying.
