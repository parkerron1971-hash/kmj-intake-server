---
title: The church pages show the church plans by size once they're on sale
date: 2026-11-03
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03, after the church-pricing review: "this is perfect. I agree with the plan. make the fixes and upgrade to site or whatever you need to upgrade or fix."'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Switch-on is #1704's: PLAN_CHURCH_OFFERED=1 (a Thursday, per Lanes) flips checkout and these pages together"
  - "The 'Good to know' line promises one more office login at $15 and extra texts at $20 per 1,000; #1704's log says neither is charged or held yet (texts wait on per-business SMS metering, the extra login and the move fee are a follow-up PR). Build those before the switch goes on, or the line says more than the system does"
  - "Bank connections still differ by church plan (2 / 5 / unlimited) but the cards don't list them, per the brief; add a line if Kevin wants it"
  - "The Start free buttons go to /start with no plan in the link, as the three cards did"
decisions:
  - "One switch: church_site.plans_by_size() is pricing_config.church_plans_offered(), so the pages change the moment checkout opens, never before"
  - "The parts of a page that describe the public ladder are sections in the templates, {{#NAME}}...{{/NAME}}. Off, the markers drop and the HTML is byte for byte what it was (checked by diffing all eight pages; the only change is the new, unused .plans.four and .planrow.four CSS rules). On, church_site._by_size() replaces each one"
  - "Overview: four cards in the three cards' markup (.pc/.pz/.mtr/.dep/.pinc, the data-m/data-y switch), Growing lit, meters measured against the four church plans, names from billing_limits.PLAN_DISPLAY, Chief's depth from chief_models.deep_analysis_label, the Includes list from plan_limits and plan_features. The founding seat strip gives way to a 'Good to know' line from pricing_config.church_offer() (Multi-site from $999, extra texts, one more login, the move)"
  - "Product pages: one generated four-plan strip (.planrow.four) replaces each page's three-plan strip, plus the plan prose that named Professional or Solutionist (restricted funds, the close, 990 prep, budgets, Chief's sorting, website visitors, the login counts, the accountant's seat, three ledes). Where a feature is on every church plan the words say so; the rest name the plans that carry it, read from feature_gates"
  - "Clip hours are worded 'Clips from N hours of sermons a month': the allowance is hours of recordings, not hours of clips"
  - "FAQ: 'The Solutionist plan adds staff seats' became 'Office logins come with every plan: one on Starter, three on Professional and seven on Solutionist', from plan_limits; with the church plans on sale it names 3 / 8 / 15 / 35"
related: [2026-11-03-church-plans-by-size.md, 2026-10-23-church-site.md, 2026-10-23-church-site-on-and-linked.md, 2026-10-24-coach-site.md]
---
Before building I read both repos' `worklog/`. The church site entries (10-23 build, 10-23 on and linked) and the coach site (10-24, which reuses church_site's `_plan_tokens`, `_trial_tokens` and `_founder_strip`) touch this code; #1704 (church plans by size) left "the /churches page's pricing section and the stale FAQ seat line" for this PR. Nothing in the frontend log overlaps. The shared token helpers are unchanged, so the coach pages render exactly as before.

With PLAN_CHURCH_OFFERED off nothing a visitor sees changes, except the FAQ's church answer, which now tells the truth about logins. With it on, /churches is "Priced by your church's size." with Small $79, Growing $149, Established $299 and Large $599 (yearly ten months), and each product page's plan strip shows the same four.

Checked:
- `__tests__/test_church_site.py`: 30 tests (10 new: off keeps the ladder and the template, every section has church words, four cards from the dials, the move replaces the founding seat, moved dials move the page, the strips, the prose held to feature_gates, voice and links with the switch on, the FAQ both ways).
- 624 passed across the church, coach, home, marketing, brand voice, plans, clip and FAQ test files.
- One screenshot of the /churches pricing section with the switch on, at 1400 wide.
