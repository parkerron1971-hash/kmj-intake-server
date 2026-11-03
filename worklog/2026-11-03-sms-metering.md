---
title: Every text is counted and costed against the church that sent it
date: 2026-11-03
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03: "make the fixes" (texts cost money at Twilio and none of it was recorded; church plans will carry a monthly text allowance of 500 / 1,500 / 3,000 / 8,000)'
status: in review
prs: ["kmj-intake-server (this PR)"]
migrations: []
left_undone:
  - "Frontend: the Costs panel (CostsPanel.tsx) shows only the totals, which now include texts; /platform/costs/summary also returns sms_30d {texts, segments, cost_cents} and ai_cost_cents for a line of its own"
  - "The text allowance itself: nothing shows or enforces it yet. sms_usage.texts_this_month(business_id) is the count to build on; None means unknown, never 0"
  - "Inbound texts and Twilio's own STOP confirmations are billed by Twilio too and are not recorded (we never send them)"
  - "Check the 1.25-cent dial (COST_SMS_SEGMENT_CENTS) against a real Twilio invoice"
  - "Not new, not fixed here: spend_guard, usage_metering.weighted_usage_since, billing_limits.chief_messages_this_month, launch_access and margin read api_usage with a limit above 1,000 and so see at most PostgREST's 1,000 rows (the class #1701 fixed for the reports). Texts are now left out of the AI reads so they can't make it worse"
decisions:
  - "Home: api_usage, one row per text Twilio accepts, written inside twilio_sms.send_sms (the one send) after the message id comes back; a send that raises writes nothing. endpoint 'sms', model 'twilio-sms', provider 'twilio', input_tokens = billable segments, units 0, cost = segments x pricing_config.sms_segment_cost_cents() (default 1.25), task_type 'sms_<kind>', response_id = the Twilio id"
  - "A text is not AI: spend_guard, usage_metering (weighted usage, low-credit nudge, weight_for), billing_limits.chief_messages_this_month, launch_access, ops_desk's AI spend and chief_quality's spend all read endpoint=neq.sms, in the query (so texts never crowd AI rows out of the 1,000-row window) and, where rows are summed, in memory too"
  - "The Costs view and margin's COGS keep texts: they are what the platform pays to serve a business"
  - "The TwiML auto-reply on the inbound webhook writes a row too (Twilio bills it), against the business routing found"
  - "The no-card trial's phone check and the operator test send are the platform's (business None); the row never borrows the request's billing tenant (billing_context.unattributed)"
  - "Kids pickup codes and member sign-in codes count against the church; task_type tells the kinds apart if an allowance should skip some"
  - "No migration: idx_api_usage_business_created (business_id, created_at DESC) shipped in APPLY-2026-08-08-credit-config-dials.sql, whose units column production already writes"
related: [2026-11-03-reports-read-every-row.md, 2026-10-11-meter-prices-loud.md]
---
`sms_usage.py` (the row, `texts_this_month`, `segments_this_month`, `cost_since`),
`twilio_sms.send_sms(..., business_id=, kind=)` and every caller (sms_service,
sms_routing, kids_checkin, member_portal, no_card_trial), `sb_clients.sb_count_as_service`
(a HEAD count), `pricing_config.sms_segment_cost_cents`, the AI readers listed above,
`platform_console.costs_summary` (`sms_30d`), `__tests__/test_sms_metering.py`.
Before building the allowance, read `sms_usage.py`'s header. Overlap checked:
no earlier worklog in either repo records texting cost or a text allowance;
`2026-10-11-meter-prices-loud.md` is the precedent for non-AI cost rows at units=0.
