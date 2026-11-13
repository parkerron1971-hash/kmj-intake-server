---
title: A failed AI call costs no credits (a Chief reply was charged twice on failover)
date: 2026-11-13
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-13: "making sure the ai credits are priced good as well"'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone: []
decisions: ["a row logged ok=False with no units of its own costs 0 credits; explicit units still win (the code that wrote them knew what was delivered); a row read without ok is priced as before", "the meter (weighted_usage_since) and Mission Control's month total (launch_access) now select ok"]
related: [2026-11-13-ai-credits-pricing-check.md]
---
Found in the 2026-11-13 credits check: a failed `/chief/backend` attempt was
still charged the chat price (12), because the meter priced rows by endpoint
and never read `ok`. When Chief's main model failed and the backup brain
answered (`/chief/backend-fallback`, also 12), one reply cost 24 credits.
Four failed attempts, 48 credits, in the 30 days to 2026-11-13. Now a failed
row with no price of its own costs nothing. A test holds the meter's queries
to selecting `ok`, since the test fake returns every column regardless.
