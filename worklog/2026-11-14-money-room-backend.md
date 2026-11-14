---
title: Mission Control's Money room, the backend (bills, due dates, live usage, income, the pay-yourself split)
date: 2026-11-14
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-14: "build a system that literally can track all of this for my business. when everything is due and cost and savings and a plan so i can see how much money I should pay myself"'
status: in review
prs: [kmj-intake-server (this PR), solutionist-studio (the Money screen built in parallel against the same contract)]
migrations: [supabase/APPLY-2026-11-14-platform-money.sql (NOT applied)]
left_undone:
  - "Apply supabase/APPLY-2026-11-14-platform-money.sql. Until then the room reads the seed from the code (setup_needed true) and saving answers 503"
  - "RAILWAY_API_TOKEN (an account token) and DIGITALOCEAN_TOKEN are not set: Railway and DigitalOcean show their entered amounts until they are"
  - "LiveKit and Cloudflare R2 have no live reader: entered amounts only"
  - "The reserve is a goal (reserve_goal_months x the month's costs), not a balance: nothing tracks what has been set aside yet"
  - "Extra office logins ($15 each) and other subscription add-ons aren't in income: businesses rows carry only the plan's price id"
decisions:
  - "Every live reader fails soft: not set up (no token) is source entered with live_error false; set up and unreadable is entered with live_error true. Never a 500. Live reads cached 10 minutes (a failure 1 minute); ?refresh=true reads again. A closed month's api_usage totals are read once a process"
  - "api_usage: every page of the UTC calendar month (sb_get_all_as_service strict), id,model,endpoint,cost_cents only, texts left out (Twilio is read from Twilio), classified by api_usage_logger.provider_for and then the endpoint (/ai/tts-el is ElevenLabs). Platform rows with no business count: it is all Kevin's bill"
  - "On pace = so far / days elapsed x days in the period, never projected from under a day and never below what's spent; Railway is paced over its own billing period"
  - "Due dates are Kevin's calendar day (US Eastern), held to the month's last day (31 in November is the 30th)"
  - "Income: active and past_due subscriptions whose price id reads as a plan, at the real price (a church founding price id pays the founding price, the Founder seat its own, an annual price a twelfth of ten months). Comped businesses are counted and never priced; the platform owner's own are left out; one whose owner can't be checked is left out too (an info alert says how many), so income is never overstated. Aggregates only"
  - "Alerts: at most one a bill, keyed by the bill. A live bill on pace for over 1.5x last month and over $10 is running high (warn); a watched bill shows its note (warn, as in the contract's LiveKit example). Unread income is its own alert"
  - "The split always adds up to the cent: tax and reserve round down, pay takes the rest. plan_model.base_steps starts at the month's real costs rounded up to the next $50 when that's above $500, and the later steps never fall below it"
related: [2026-11-14-founding-deal-cards.md]
---
`platform_money.py` (new): `GET /platform/money/summary`, bills
`GET/POST /platform/money/bills`, `PATCH/DELETE /platform/money/bills/{key}`
(delete is soft: active false), `GET/PUT /platform/money/config` (the three
percentages 0..100 adding up to 100, reserve goal 0..24 months). Router-level
`require_owner`; service-role reads and writes only. Registered after
`platform_today` in `kmj_intake_automation.py`, well before the catch-all.

Live readers: Twilio Usage Records (ThisMonth and LastMonth, totalprice),
Railway GraphQL `me.workspaces.customer.currentUsage` with its billing period,
DigitalOcean `customers/my/balance` month_to_date_usage, and the api_usage
ledger by provider. Logs name the reader and the kind of failure only: no
URL, token, body or account id.

`.env.example`: RAILWAY_API_TOKEN, DIGITALOCEAN_TOKEN, with what each fills.

Tests: `__tests__/test_platform_money.py` (29): the owner gate on all seven
routes, the summary's contract shape with every reader faked, fail-soft
fallbacks with every reader failing (and no secret in the logs), the cache,
on-pace math, due-date clamping and roll-over, income pricing (founding,
regular, annual, past due, trial, comped, the owner's own, unchecked), the
split's rounding, base steps, alerts, bill and config validation, the
pre-migration seed and its 503s.
