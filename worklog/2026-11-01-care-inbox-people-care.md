---
title: The People & Care login sees the care requests people shared with the prayer team
date: 2026-11-01
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-01: "go through each admin that is connected and make sure that there access point have everything that is connected to there role" … "every area that is block setup or partly. lets make sure we build"'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "PrivateCarePanel's copy still says only the owner's hand-offs appear for a teammate; a small FE PR reads the new scope 'shared' and says what the People & Care login sees"
  - "The rest of the office checkup (artifact MhVzFwJHS2ks85EWkoeezK): the treasurer's money week, the admins in the leadership loop, menus, first sign-in alerts, then the duties layer"
decisions:
  - "A church login whose OWN areas name People & care (picked, or Chief's guess) also sees requests with prayer_team true and needs_pastor false, plus what was handed to it. Scope 'shared'."
  - "A request kept private, or one that needs a pastor, stays with the owner or the People & care keeper. They can still hand it over; hand-off stays owner/keeper only."
  - "Admins don't count: an Admin's 'whole church' menu isn't People & care's inbox. The treasurer's Admin seat sees only what was handed to it."
  - "A failed read of the shared rows falls back to what was handed, never more. Off the church switch, nothing counts as shared."
  - "With a People & care keeper named, the shared ones stay visible (sharing is the person's consent, not the guarded part)."
related: [2026-10-27-church-key-doors-care.md]
---
`private_care.py`: `CareCaller(shared=)`, scope `shared`, `SHARED` filter,
`_works_care`, `_may_touch`. Love City on 11-01 had 2 care requests, none
shared, so nothing changes on screen today. The rule is what matters as
requests come in. Tests: `__tests__/test_care_inbox_people_care.py` (11);
`test_care_inbox_actions.py`, `test_church_key_doors_care.py` and
`test_church_prayer.py` still pass.
