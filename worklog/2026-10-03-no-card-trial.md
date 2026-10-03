---
title: The free trial starts without a card, with 500 credits
date: 2026-10-03
agent: Claude Code (Claude Opus 5.5)
asked: "ok build the no card 500 credit version" / "make sure the cost aligns right with the usage. we saying 500 tokens can build a site and still talk with chief. make sure that is true."
status: in progress
prs: [solutionist-studio#1110]
migrations: []
left_undone: ["marketing site copy (marketing_pages.py, marketing_home_v2.html + scripts/build_home_v2_template.py) still says the card is not charged until the trial ends; follow-up PR once this merges, behind no_card_trial_enabled()"]
decisions: ["no-card tank 500 (PRICE_TRIAL_CREDITS_NO_CARD); a card keeps the trial end date and lifts it to 1,000", "the first site build stays free; a second build, texts, phone numbers and bulk email wait for a card", "one no-card trial per person, never for grandfathered or comped accounts, only while BILLING_ENFORCE is on", "the no-card trial shows the Professional plan (NO_CARD_TRIAL_PLAN)"]
related: [2026-10-03-trial-row-reads-the-trial.md, 2026-10-02-agent-operations-wave-3-and-more.md]
---
A new business starts a 7-day trial with no card and a 500-credit tank, the
same row shape Platform Chief's extend_trial writes, so trial_expiry, the
trial emails and access_state already understood it. Adding a card is the
existing Checkout, keeping the trial's end date. Measured before sizing
(2026-10-03, production): builds are charged 1,000-1,300 credits and cost
$1.69-3.25; a Chief turn is 12 credits and ~8.2c; so 500 credits is the free
first build plus ~41 Chief turns, ~$6-7 worst case per signup. That only
holds because the first build is free, which never applied in production
until #1215. Check no_card_trial.py before building more trial or paywall
behaviour.
