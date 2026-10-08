---
title: Solutionist's own business never gets a tenant marketing week while it runs on Buffer
date: 2026-10-08
agent: Claude Code (Claude Opus 5.5)
asked: "Buffer is for me and post for me is for platform. is the wiring correct in the backend?"
status: waiting on Kevin
prs: [kmj-intake-server#1345]
migrations: []
left_undone: []
decisions: ["while the suite is not active, Solutionist's own business is the validated PLATFORM_BUSINESS_ID, else the row platform_suite.books_business finds (platform_books AND the platform owner's), so a tenant that flags its own row is still planned", "a failed lookup keeps out only rows whose own settings say platform_books, that hour (logged); it never stops every tenant", "manual runs of that business on the tenant desk (engine/run, Chief's replan and the other desk verbs) are refused after the owner check in plain words: Solutionist's own marketing runs on the Mission Control desk", "the flag lookup is asked only while MARKETING_DESK names anyone, and ready() reads it off the event loop, so a desk that is off still costs no read", "suite active (switch on, id valid): unchanged"]
related: [2026-10-08-marketing-platform-suite.md, 2026-10-08-marketing-platform-chief.md]
---
Kevin's rule: Buffer is for Solutionist's own marketing (Mission Control's
desk), Post for Me for the businesses on the platform (the tenant suite). On
main the tenant fan-out left Solutionist's own business out only once
PLATFORM_BUSINESS_ID validated; with it unset (today) or invalid, setting
MARKETING_DESK=* with plan_enabled and connected accounts on that business's
tenant desk would have planned a second week through Post for Me beside the
Buffer week. `platform_suite.kept_out` now finds the business by the
validated id or the owner-checked flag lookup, `desk_on_for` / `desk_scope`
leave it out of every tenant tick and run, and its manual runs are refused
in plain words. No migration. Docs: docs/MARKETING_DESK.md (B15, "Out of the
tenant suite while it runs on Buffer"). Tests:
__tests__/test_platform_out_of_tenant_fanout.py.
