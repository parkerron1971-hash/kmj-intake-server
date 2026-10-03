---
title: An ended no-card trial keeps a free workspace (the reverse trial)
date: 2026-10-03
agent: Claude Code (Claude Opus 5.5)
asked: 'build these (the reverse trial, owner-only previews, preview-only site cards)'
status: shipped
prs: [kmj-intake-server#1228, solutionist-studio#1114]
migrations: []
left_undone: []
decisions: ["access_state returns free (not locked) for a no-card trial whose credits or days are over; card trials and paid subscriptions are unchanged", "AI is held at the meter: an ended no-card trial's allowance is 0, measured from the trial's end, so bought credit packs still work and never pay for trial usage", "building and blueprint drafts wait for a card once the trial is over", "switch: PRICE_NO_CARD_FREE_WORKSPACE=0 puts the wall back"]
related: [2026-10-03-no-card-trial.md]
---
A no-card trial that ran out used to meet the full-screen wall a cancelled
subscription gets. Now the workspace keeps working (contacts, bookings,
invoices, books) and only what costs money waits for a card: Chief and the
other AI, held at usage_metering's one gate (can_interact), and the live
site (already a preview). The trial-ended email says so. Mission Control and
the billing rehearsal show the new state as "free".
