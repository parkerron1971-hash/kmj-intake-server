---
title: Church plans by size (Small, Growing, Established, Large)
date: 2026-11-03
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03, after the church-pricing review (artifact Pdg8hF4pB5n6efoFQmzd8d): "this is perfect. I agree with the plan. make the fixes and upgrade to site or whatever you need to upgrade or fix."'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Switch-on: run POST /billing/bootstrap-prices (owner) to create the 8 church prices in Stripe, paste the STRIPE_PRICE_ID_CHURCH_* block into Railway, then PLAN_CHURCH_OFFERED=1 (a Thursday, per Lanes)"
  - "Text allowance: texts_monthly is on the plan, but nothing holds a church to it yet; it waits on the SMS metering fix (texts counted per business), then a follow-up PR enforces it with $20 per 1,000 past it"
  - "One more office login ($15) and the move fee (3 months of the plan, free for the first 5 churches): follow-up PR"
  - "The app's billing screen and paywall ask /billing/plans without for_type, so no audience plan has ever shown in the app; the frontend PR adds it"
  - "The /churches page's pricing section and the stale FAQ seat line: follow-up PR"
  - "Lanes: this is a Build item; Kevin asked for it directly on 11-03, the Plan slot is his click"
decisions:
  - "Four audience plans on the barber machinery (AUDIENCE_PLANS, PLAN_AUDIENCE, AUDIENCE_PLAN_FEATURES), sold to canonical vertical 'ministry' (church, faith, religious, ministry); not nonprofits, since the plans are sized by people on a Sunday"
  - "Every church feature on every plan. Small and Growing = Professional's features + vertical_reports (the donors report) + ai_clips; Established and Large = everything (adds audit trail, outside accountant, marketing autopilot)"
  - "Limits: seats 3/8/15/35, credits 3,000/7,500/17,500/30,000, texts_monthly 500/1,500/3,000/8,000 (a new limit key, None on every other plan), clip_hours_monthly 2/5/10/20 (clip_finder.included_seconds; 10 elsewhere); Large allows 3 businesses"
  - "Chief's deep lane follows the price: Small Standard (Sonnet), Growing Advanced (Opus), Established and Large Maximum"
  - "PLAN_CHURCH_OFFERED=1 opens all four at once (per-plan PLAN_<KEY>_OFFERED still works); hidden until then"
  - "No discount codes on church plans: the checkout box is off and a promotion_code is a 409. MINISTRY20 stays for the public ladder"
  - "upgrade_plan_for walks only the plan's own audience ladder, so a barber on Boss is never pointed at a church plan now that the church plans follow Boss in AUDIENCE_PLANS"
  - "bootstrap-prices asks Stripe for lookup keys ten at a time (Stripe's limit; the catalog is now 25)"
related: [2026-11-03-broadcast-every-number.md]
---
Before building I read both repos' `worklog/`: the church site (10-23), ChurchSavvy billing (10-24) and the texting entries touch nearby code; none prices churches by size.

The review found today's 1 / 3 / 7 logins push a 50-person church onto $149 (Planning Center: about $85) and leave nothing for a 600-person church (8 to 10 staff; Planning Center about $540). The ladder prices by size instead, at or under Planning Center for the same church.

/billing/plans?for_type=church now returns the four plans (once offered), `plan_details` with `texts_monthly`, `clip_hours_monthly` and `people_on_sunday`, and a `church_offer` block (extra texts, extra login, move months, founding moves, Multi-site floor, names).

Tests: `__tests__/test_church_plans.py` (new, 39 cases); test_audience_plans, test_clip_finder and test_marketing_open_to_all updated where they pinned the barber-only list. 149 passed across the four files; 968 passed across every billing/plan/stripe/clip file.
