---
title: The roll's writes never call a failed save saved
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'The review of #2004 (the roll edits in place): four places a failed write could read as saved or leave a record half-moved'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone: []
decisions:
  - "A family move writes the new family first (join_family / make_family) and only then takes the old household row out (household_id=neq.new); every delete is checked. A failure never leaves someone in no family."
  - "A child's grade that didn't save is a 503, never in saved."
  - "A child's allergies that didn't save on a new family come back as the response's warning, never silent."
  - "A merge marks and hides the other record before any row moves; rows that couldn't move are listed in left and stay on the hidden record, and a retry is refused (409) rather than merging a half-moved record again."
related: [2026-11-20-roll-edit-in-place.md]
---
Follow-up to #2004 from its review. Tests: five new failure-path tests in
`__tests__/test_church_roll_edit.py` (20 pass), with the fake answering the way Supabase
does on a failed write (None, False).
