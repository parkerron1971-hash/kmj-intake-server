---
title: Church tier fences - Small without the weekly plan, clips paid from credits, a storage allowance per church
date: 2026-11-17
agent: Claude Code (Claude Opus 5.5)
asked: '"the 79/99 dollar tier for churches have access to do many tools ... I dont want to loose money because these are not accounted for", then storage instead of time ("we allocate storage amount to each church and if storage become full they would have to delete it"), then "build"'
status: waiting on Kevin
prs: [kmj-intake-server#1900, kmj-intake-server#1903, kmj-intake-server#1910, kmj-intake-server#1909, solutionist-studio#1614, solutionist-studio#1615, solutionist-studio#1618]
migrations: [supabase/APPLY-2026-11-17-church-storage.sql (not applied), supabase/APPLY-2026-11-17-recording-small-copy.sql (not applied)]
left_undone:
  - "Kevin: apply APPLY-2026-11-17-church-storage.sql, then APPLY-2026-11-17-recording-small-copy.sql (the first was staged in the SQL editor on 11-17; the Run click is his)"
  - "Kevin: CLIPPER_COPY_HOSTS on solutionist-clipper = the R2 endpoint's hostname (the clipper's /health says copies:false until then)"
  - "Kevin: create the three extra-storage Stripe prices (stripe_billing.bootstrap_prices narrowed to STRIPE_PRICE_ID_EXTRA_STORAGE*, via railway run; the run was refused to the agent) and set the three STRIPE_PRICE_ID_EXTRA_STORAGE* ids on kmj-intake-server and kmj-intake-worker"
  - "Thursday 2026-11-19: CHURCH_STORAGE=owner then on, CHURCH_STORAGE_SMALL_COPY=owner then on (both services); a What's New entry for the storage card and extra storage the same day"
  - "Small Church's founding/regular prices were not changed; the fences are features only"
decisions:
  - "Small = Growing minus marketing_week: the weekly plan's five flyers are included work no credit pays for (creative_director billing='included'); Small keeps marketing_suggestion, and any post or flyer the church asks for is charged from its credits"
  - "Small includes 0 clip hours (CHURCH_SMALL_CLIP_HOURS default 0): clip_finder charges 75 credits an hour from the first second; a plan-lookup error still falls back to the ten free hours, as before"
  - "Posting stays on Small: sending a post costs about a penny, and what Chief writes or designs for it is charged from credits"
  - "Nobody was on church_small when this shipped (one church on church_growing), and the founding promise is the price, not the feature list"
related: [2026-11-03-church-plans-by-size.md, 2026-11-13-ai-credits-pricing-check.md, 2026-10-29-church-stream-relay-service.md]
---
Kevin's tier review (artifact TQh5DcQHroy1LN9UGgfZQV) measured 60 days of
production cost: a Chief credit about 0.95c, an AI flyer about 12c, clips
about 56c per recorded hour, a text part 1.26c. Small carried all of
Growing's toolkit, so the costs no credit covers (the weekly flyer plan,
free clip hours, recordings kept forever) all sat on the cheapest plan,
and a bigger church had little reason to move up.

This PR is the first fence: Small loses Chief's weekly plan (it gets the
one suggested post a week) and its clip hours (each hour is paid from
credits). The church pages follow feature_gates on their own; two
hand-written sentences (PRICING_LEDE, SITE_PLANS_LEDE) now say the weekly
plan and included clip hours start at Growing. NOT_WEEK no longer names
the Professional plan to a church. With these fences and a capped storage
allowance, a fully used plan keeps about 43% / 42% / 44% / 38% at the
founding prices and 51-55% at the regular prices.

Built the same day (Kevin: "build"): #1903 the storage allowance (meter in
Sundays, Delete, the 14-day rule with three delivered warnings, the 80%
heads-up, CHURCH_STORAGE off); #1910 the smaller copy per recording, made
by the clip service and also the download, the full recording removed at
day 14, never counted twice against a church (CHURCH_STORAGE_SMALL_COPY
off); #1909 + FE #1618 more room at $5 per 100 GB a month on the
church's subscription, like extra logins; FE #1614 Small's clip wording,
FE #1615 the storage card on the Live page. Each has its own worklog.

2026-11-18, later: the R2 write key is set on kmj-intake-server and kmj-intake-worker (a Cloudflare account token, Object Read & Write on solutionist-media only); a read-only listing signed with it answered 200 on both services.
