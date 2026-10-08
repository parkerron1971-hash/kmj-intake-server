---
title: B15 — Solutionist's own marketing desk runs on the suite (MC_MARKETING_SUITE, off)
date: 2026-10-08
agent: Claude Code (Claude Opus 5.5)
asked: "This will work. let's build this."
status: waiting on Kevin
prs: [kmj-intake-server#1342]
migrations: []
left_undone: ["F7: Mission Control's frontend mounts BusinessMarketingDesk on /platform/marketing/suite (GET /suite/status picks the desk)", "Platform Chief's marketing verbs through B10's desk verbs for the platform business (today they refuse anything new while the suite is on)", "MC Today and the Mission Control Chief digest still read the Buffer desk", "signups (businesses.attribution) in the suite's results for the platform business", "Kevin: connect Solutionist's accounts in Post for Me, set PLATFORM_BUSINESS_ID (+ pilot list, MARKETING_DESK_PUBLISHING=on), MC_MARKETING_SUITE=on, plan_enabled on the suite desk, watch /platform/marketing/drain reach 0, then BUFFER_PUBLISHING=off"]
decisions: ["the platform business is named by new env PLATFORM_BUSINESS_ID and validated by one predicate everywhere (platform_suite.state): platform_books true AND its owner is the platform owner's auth user; the suite is active only with the switch on AND a valid id", "switch on with the id unset or invalid: the Buffer desk and its Thursday job keep working, a loud error is logged, /suite/status and /drain say so; a failed read fails closed (neither desk takes anything new, neither loop plans that hour)", "review fix: the news page and the Buffer desk's flyers/numbers no longer take the first platform_books row; they read platform_suite.books_business (owner-checked)", "review fix: Platform Chief's dispatch turns a refusal while preparing a card (propose) into that action's {ok: false, label}, not a failed reply", "autopilot level for that id only, whatever its billing row (in-memory comp_tier practice, also in B13's standing eligibility), never from a request", "the platform business is in the suite's fan-out while the switch is on whatever MARKETING_DESK says, and out of it while off", "one loop a week: off = the old Thursday job, on = the suite; neither plans a week the other has a post approved or out for; a failed read plans nothing that hour", "Mission Control's routes mirror the business desk's paths and answers under /platform/marketing/suite so F7 is one request prop", "Platform Chief: the smaller safe change, its verbs stay on the Buffer path for managing the drain and refuse anything new", "never pause Buffer to drain it (a paused desk holds approved posts); nothing in Buffer is cancelled automatically", "links on mysolutionist.app/go/ resolve suite posts by PLATFORM_BUSINESS_ID, not the switch, so links already out survive a rollback"]
related: [2026-10-07-marketing-suite-storage.md, 2026-10-08-chief-marketing-desk.md, 2026-10-08-marketing-clips.md]
---
Mission Control's Marketing desk on the marketing suite (B15 of
docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md), behind MC_MARKETING_SUITE
(off: the Buffer desk exactly as before). `platform_suite.py` holds the
switches and the one-loop checks; `platform_marketing_suite.py` the owner-only
routes (/platform/marketing/suite/* mirroring /marketing/{id}/*, and
/platform/marketing/drain). For the platform business only: the autopilot
level, the platform profile (marketing_profile.platform_profile), the
platform's numbers plus the suite's posts (marketing_signals.platform_signals),
the platform's plays and caption rules (business_marketing_engine's platform
half), mysolutionist.app as its site and /go/ host, Eastern time. While on,
the Buffer desk and Platform Chief take nothing new; approved posts drain.
No migration. Docs: docs/MARKETING_DESK.md, "Solutionist's own desk on the
suite (B15)". Tests: __tests__/test_platform_marketing_suite.py.
