---
title: Chief prepares during speech and checks appointment capacity directly
date: 2026-10-03
agent: Codex (GPT-6)
asked: "ok great. this will work."
status: shipped
prs: [kmj-intake-server#1217, solutionist-studio#1111]
migrations: []
left_undone: ["Owner microphone retest for end-to-end acoustic timing"]
decisions: ["Partial speech only permits scoped read preparation", "Final availability uses fresh authoritative capacity", "Checked scheduling prose avoids repeated model repair", "No recurring invoice or autopilot writes on the dedicated availability route"]
related: [2026-10-02-chief-conversation-gaps.md, 2026-10-02-chief-context-flow-release.md]
---
Both repositories' existing voice worklogs were reviewed before implementation. The observed appointment turn preserved the full transcript, but failed a lookup and spent about eighteen seconds reviewing, repairing and rechecking its answer. This change adds a dedicated read-only scheduling calculation and revisioned voice preparation. Final answers retain owner checks, admission gates, checked speech boundaries and retry recovery. Unsupported requests retain the general path rather than silently dropping constraints.

Release validation covered 154 focused backend checks and independent review. GET-only rehearsals against the owner's scheduling data took 411 ms for service disambiguation, 471 ms for the named-service calculation, 427 ms using preparation, and 242 ms for a service-choice continuation. These are checker timings, not full microphone-to-audio measurements. The rehearsal caught and removed a nonexistent booking-duration column before release. Full CI also exposed an existing quality-monitor test whose fixed October 2 data was compared with the real current clock; its clock is now pinned to the fixture date without changing production monitoring. Worklog files use BOM-free UTF-8.
