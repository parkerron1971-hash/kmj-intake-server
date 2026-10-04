---
title: Chief's CPU booking rehearsal layer is available as a tool
date: 2026-10-04
agent: Codex (GPT-6)
asked: "deploy it"
status: shipped
prs: [kmj-intake-server#1255]
migrations: []
left_undone: ["Measure natural model selection and production cost savings separately"]
decisions: ["Preserve the shipped deterministic appointment route", "Read-only joint preview; never reserve or book", "Reuse current outside-calendar read authority and strict scheduling validation"]
related: [2026-10-03-chief-readonly-appointment-checks.md, 2026-10-03-chief-busy-calendar-read.md]
---
Reviewed scheduling and listening worklogs in both repositories. The earlier
local booking rehearsal was absent from the running Railway commit. Integrated
only this capability into a clean checkout of current main, retaining all newer
booking setup, ownership and calendar fixes and leaving unrelated local work intact.

Chief and MCP now expose `rehearse_booking_plan` for up to eight new appointments.
It checks a joint plan on CPU, reports conflicts and alternatives, and fingerprints
the evidence. Fresh reads, a six-second deadline, strict ownership checks and
bounded calendar pagination fail closed on unavailable evidence. It uses the
deployed booking-duration column and checks outside calendars with the existing
server-owned adapter. Rehearsal read failures are marked unsuccessful in MCP;
existing tools retain their prior failure/handoff behavior after review.
Content-free execution logs make future live usage verifiable.

Validation: focused regression runs of 275 and 333 checks passed (overlapping
capability cases), including a real HTTP mock of user/service credential selection.
All five offline scenarios passed. Deployment verification and model-selection
measurement are distinct: the existing direct appointment route may answer
supported wording without invoking this tool. No migration or new infrastructure.
Review retained the documented full-calendar ceiling rather than filtering out
unknown historical durations, and narrowed the MCP failure change to this tool.
All 147 capability/MCP regressions passed after that adjustment. The release PR
records CI and post-merge Railway verification separately from the local tests.
CI exposed a local-only pytest-asyncio dependency in the new tests. They now use
the standard-library event-loop runner; all 147 checks also pass with that plugin
disabled. Production dependencies are unchanged.
