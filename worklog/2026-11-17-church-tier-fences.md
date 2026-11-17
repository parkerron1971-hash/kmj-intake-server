---
title: Church tier fences - Small without the weekly plan, clips paid from credits, a storage allowance per church
date: 2026-11-17
agent: Claude Code (Claude Opus 5.5)
asked: '"the 79/99 dollar tier for churches have access to do many tools ... I dont want to loose money because these are not accounted for", then storage instead of time ("we allocate storage amount to each church and if storage become full they would have to delete it"), then "build"'
status: in progress
prs: [kmj-intake-server (this PR) - Small plan fences]
migrations: []
left_undone:
  - "Storage allowance per church: 100 GB / 250 GB / 500 GB / 1 TB covering every file (recordings, sermons, clips, uploads; records never count), the meter shown in Sundays, a recording made while full kept 14 days then removed after three warnings, nothing published ever deleted by us"
  - "Delete and Download for a recording; R2 deletes need a write-capable credential on Railway (today Railway holds the read-only R2 token)"
  - "A smaller copy of each recording two weeks after the service (about 1.3 GB instead of 6)"
  - "Extra storage: +100 GB for $5 a month (a Stripe price, like the extra login)"
  - "Frontend: the clip lines say '0 hours' for Small (BillingPanel, ClipStudio, MediaLibrary, audiencePlans.ts) and should say clips are paid from AI actions"
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
