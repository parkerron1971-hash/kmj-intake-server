---
title: QuickBooks comes off the setup list ("Final touches")
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: "the final touch list. it has quickbooks connection. can we remove that from the list because everyone might not have that setup because they might not have quickbooks setup either."
status: shipped
prs: [kmj-intake-server#1983]
migrations: []
left_undone: []
decisions:
  - "Kept the catalog entry with `listed: False` instead of deleting it: its probe is how Chief's knowledge (business_knowledge, money area) knows the books are connected, and the closed-catalog test forbids a probe with no entry."
  - "`plugins_for_vertical` skips unlisted steps (every vertical's list, the coach's menu, needs_for); `resolve_plugins` also drops one from a coach plan written before the change."
  - "Left in place: QuickBooks on Integrations, and the Strategy Session's setup plan, which already offers it as 'Optional' and never turns it into a follow-up. setup_brief's NEVER_LEADS guard stays as a backstop."
related: []
---
The Home setup checklist (its heading reads "Final touches" past three quarters done)
listed "Connect QuickBooks" for every business, where nobody without QuickBooks could
ever tick it. It is now off every setup list. Files: business_track_actions.py
(`listed: False`, `is_listed`), business_track_router.py (`resolve_plugins`),
__tests__/test_business_track.py (`test_quickbooks_is_off_every_setup_list`).
