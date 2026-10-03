---
title: Correct credentials for Chief outside-calendar availability reads
date: 2026-10-03
agent: Codex (GPT-6)
asked: "Fix the signed-in appointment check failure after release"
status: shipped
prs: [kmj-intake-server#1224]
migrations: []
left_undone: ["Owner microphone retest after the release; typed playback timing does not measure speech capture"]
decisions: ["Only server-owned busy blocks use service credentials", "Fresh business and exact owner checks precede that read", "All other scheduling data retains the user JWT"]
related: [2026-10-03-chief-listening-availability.md]
---
A signed-in appointment check failed although a service-side rehearsal succeeded. The calendar-feeds migration intentionally denies authenticated users direct reads of calendar_busy_blocks. The checker now uses the existing server-owned table contract for that one scoped GET, after its fresh business/owner verification. Business, service-catalog and booking reads remain under the user's JWT. The adapter cannot read feed URLs or other tables and cannot write. Failed or cross-business busy data still returns unavailable rather than free capacity.

Validation: 111 availability, authentication, pagination, readout and listening tests passed, with independent review of the authenticated transport and ownership gates. New httpx transport tests reproduce permission denial for user-JWT busy reads, verify each table's actual credential selection, and cover denied or changed ownership, server-read failures, cross-business data and mutation rejection. Existing generic mocks were adjusted so they cannot accidentally use a real service transport. The integrating session will merge only after protected CI passes, verify the deployed commit and readiness, and report the signed-in browser conversation and playback results through the Dev Desk.
