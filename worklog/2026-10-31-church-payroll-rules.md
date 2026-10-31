---
title: Only a church has ministers (with how they are one), and a church owes no FUTA
date: 2026-10-31
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-31: "go lock the contractor payouts and fix the three"'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: [supabase/APPLY-2026-10-31-minister-credential.sql (applied 2026-10-31, verified)]
left_undone:
  - "The Pay your team screens (solutionist-studio) still don't show the Minister switch; when they do, it asks how the person is a minister (ordained, licensed or commissioned) and is shown only to a church's owner"
  - "W-2s: none are made yet. They're due February 1, 2027 for 2026 pay, before any church runs a real paycheck here"
  - "State unemployment stays typed in. Most states exempt a church's staff too, but that is the state's rule, so nothing here zeroes it"
decisions:
  - "Only a church (businesses.type resolving to ministry, church_follow_up.is_church) may mark someone a minister. A barbershop that ticked it would stop withholding Social Security and Medicare and owe them with penalties. payroll_calc ignores a minister flag outside a church, so a flag set some other way still can't change the tax"
  - "Turning minister on needs minister_credential: ordained, licensed or commissioned (Publication 517's test). The owner's alone, like the rest of the setting. Turning it off clears the credential and the housing part"
  - "A church owes no FUTA on anyone (IRC 3306(c)(8): a 501(c)(3), which a church is without applying). statutory(church=True) zeroes it for every line; Social Security and Medicare stay for non-ministers (a church that elected out with Form 8274 isn't handled)"
  - "The pay math counts a minister only with the credential too (payroll_calc.is_minister): a flag set before this, with no credential, is taxed like anyone's pay until the owner says how they're a minister (review bot)"
  - "A failed read of the business type is a 503, never \"not a church\": recomputing a draft line on a guessed no would put Social Security on a minister and drop their housing part (review bot). Adding or changing a person whose save fails is a 503 too, not ok"
related: [2026-10-31-minister-payroll.md, 2026-10-30-housing-allowance.md]
---
`payroll_calc.statutory(..., church=)` and `compute_item(..., church=)`;
`payroll_router._is_church`, `_church_of`, `MINISTER_CREDENTIALS`,
`minister_credential` on the employee bodies, and the church check in
`_minister_fields` and on a line's housing part. Tests:
`__tests__/test_payroll_minister.py` (three new, the rest now at a church).
