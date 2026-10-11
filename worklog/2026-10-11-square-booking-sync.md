---
title: Square one-way trial calendar sync and production gate
date: 2026-10-11
agent: Codex (GPT-6)
asked: "set those up; businesses can try our flow before major changes"
status: in progress
prs: [kmj-intake-server#1375, solutionist-studio#1200]
migrations: ["APPLY-2026-10-11-square-booking-sync.sql (pending)"]
left_undone: ["CI review and deployment", "sandbox sync acceptance", "consenting real-business production pilot (Kevin recruiting)"]
decisions: ["explicit owner opt-in; Square remains the booking system", "separate calendar copies, no native booking/reminder/payment writes", "15-minute reconciliation; no webhooks or new scopes", "production remains gated"]
related: [2026-10-10-square-rollout.md]
---
Read existing Square rollout/acceptance logs and overlapping calendar/booking work in both repos; inspected the open Acuity migration PR. Added a service-only atomic snapshot/lease table, bounded complete reconciliation, owner/connection/selection fences, stale/error status, removal on disconnect/location/ownership changes, and explicit production approval gate. Frontend reuses the approved Square panel and existing calendar layouts; adds opt-in/stop and read-only calendar details. General access is not opened. The real seller pilot remains Kevin's next step.

Review follow-up excludes actively leased accounts from the due batch and tests tick filtering/failure isolation. The old frontend never consumed booking_sync_enabled; both old and new panels tolerate the additive rollout flag, so backend-first deployment is safe.
