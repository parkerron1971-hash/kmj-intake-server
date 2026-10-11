---
title: Square one-way trial calendar sync and production gate
date: 2026-10-11
agent: Codex (GPT-6)
asked: "set those up; businesses can try our flow before major changes"
status: waiting on Kevin
prs: [kmj-intake-server#1375, solutionist-studio#1200]
migrations: ["APPLY-2026-10-11-square-booking-sync.sql (applied)"]
left_undone: ["consenting real-business production pilot (Kevin recruiting)"]
decisions: ["explicit owner opt-in; Square remains the booking system", "separate calendar copies, no native booking/reminder/payment writes", "15-minute reconciliation; no webhooks or new scopes", "production remains gated"]
related: [2026-10-10-square-rollout.md]
---
Read existing Square rollout/acceptance logs and overlapping calendar/booking work in both repos; inspected the open Acuity migration PR. Added a service-only atomic snapshot/lease table, bounded complete reconciliation, owner/connection/selection fences, stale/error status, removal on disconnect/location/ownership changes, and explicit production approval gate. Frontend reuses the approved Square panel and existing calendar layouts; adds opt-in/stop and read-only calendar details. General access is not opened. The real seller pilot remains Kevin's next step.

Review follow-up excludes actively leased accounts from the due batch and tests tick filtering/failure isolation. The old frontend never consumed booking_sync_enabled; both old and new panels tolerate the additive rollout flag, so backend-first deployment is safe.

Backend #1375 and frontend #1200 merged and deployed. Full CI passed in both repositories; targeted validation covered 104 Python checks, 99 database checks and 32 browser checks. Live schema permissions and unauthenticated 401 responses verified.

Kevin explicitly approved the worker setup and stop/restart test. Configured the existing kmj-intake-worker with references to the web service's sandbox Square variables and encryption key; no keys were rotated. Deployment 3588fc61-93e8-4c7f-ad0d-784813b98c02 succeeded. The background job copied the cancelled synthetic appointment at 2026-10-11 13:04:58 UTC with no error. Live calendar showed Oct 12 at 10:00 AM America/New_York, cancelled status, read-only details and the correct Square sandbox management link. Stop sync removed the database row and calendar copy while leaving Square connected. Re-enabling restored one copy automatically at 13:11:15 UTC, again without error; verified it returned in the calendar. Sandbox opt-in remains enabled for the existing owner only. Production approval remains false; Kevin is recruiting the consenting real-business pilot.
