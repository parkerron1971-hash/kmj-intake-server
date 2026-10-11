---
title: Square one-way trial calendar sync and production gate
date: 2026-10-11
agent: Codex (GPT-6)
asked: "set those up; businesses can try our flow before major changes"
status: waiting on Kevin
prs: [kmj-intake-server#1375, solutionist-studio#1200]
migrations: ["APPLY-2026-10-11-square-booking-sync.sql (applied)"]
left_undone: ["specific sandbox worker credential-reference approval", "scheduled copy/stop/restart acceptance", "consenting real-business production pilot (Kevin recruiting)"]
decisions: ["explicit owner opt-in; Square remains the booking system", "separate calendar copies, no native booking/reminder/payment writes", "15-minute reconciliation; no webhooks or new scopes", "production remains gated"]
related: [2026-10-10-square-rollout.md]
---
Read existing Square rollout/acceptance logs and overlapping calendar/booking work in both repos; inspected the open Acuity migration PR. Added a service-only atomic snapshot/lease table, bounded complete reconciliation, owner/connection/selection fences, stale/error status, removal on disconnect/location/ownership changes, and explicit production approval gate. Frontend reuses the approved Square panel and existing calendar layouts; adds opt-in/stop and read-only calendar details. General access is not opened. The real seller pilot remains Kevin's next step.

Review follow-up excludes actively leased accounts from the due batch and tests tick filtering/failure isolation. The old frontend never consumed booking_sync_enabled; both old and new panels tolerate the additive rollout flag, so backend-first deployment is safe.

Backend #1375 and frontend #1200 merged and deployed. 104 Python checks, 99 database checks and 32 browser checks; complete CI passed in both repos. RLS/no browser grants, five service-only routines, two cleanup triggers verified live; GET/PUT/POST without auth all 401. Sandbox opt-in works, but the live scheduled-job check found worker configuration absent. Automatic approval review blocked giving kmj-intake-worker the web service’s sandbox credentials/encryption-key references pending specific approval. The approval question is open; no worker secrets were shared. Production approval remains false.
