---
title: The free trial starts without a card, with 500 credits; the free build is earned
date: 2026-10-03
agent: Claude Code (Claude Opus 5.5)
asked: 'build the no card 500 credit version; make sure 500 credits can build a site and still talk with Chief; protect my own money but give them something to test; check against best business practice'
status: in progress
prs: [kmj-intake-server#1216, kmj-intake-server#1215, solutionist-studio#1110]
migrations: []
left_undone: ["marketing site copy (marketing_pages.py, marketing_home_v2.html + scripts/build_home_v2_template.py) still says the card is not charged until the trial ends; follow-up PR once this merges, behind no_card_trial_enabled()", "the un-authed editor preview /public/site/{slug} on the API host still shows a no-card site; only the public address shows coming soon", "a reverse trial (workspace stays usable without AI after the trial) was recommended, not built"]
decisions: ["no-card tank 500 (PRICE_TRIAL_CREDITS_NO_CARD); a card keeps the trial end date and lifts it to 1,000", "the free site build is earned: a verified US/Canada phone (stateless signed code, one phone per platform), at most LIMIT_NO_CARD_FREE_BUILDS_PER_DAY (10) a day platform-wide, no offer page", "a no-card site is a preview: its public address shows coming soon until a card (AI site builders generate free and charge to publish)", "texts, phone numbers, bulk email and a second build wait for a card", "one no-card trial per person; never grandfathered, comped, throwaway-email, or while BILLING_ENFORCE is off"]
related: [2026-10-03-trial-row-reads-the-trial.md, 2026-10-02-agent-operations-wave-3-and-more.md]
---
A new business starts a 7-day trial with no card and a 500-credit tank, the
row shape Platform Chief's extend_trial writes, so trial_expiry, the trial
emails and access_state already understood it. Adding a card is the existing
Checkout, keeping the trial's end date.

Measured in production (2026-10-03, last 30 days): a Chief turn costs ~11.4c
all-in (the answer check is ~2.4c of it) for ~13-14 credits; builds are
charged 1,000-1,300 credits and cost $1.69-3.25 (before the Oct 1 offer page,
which adds a whole builder pass). Worst case per verified no-card signup is
~$6-7, typical well under $1; the daily ceiling bounds the free builds at
~$30 a day. Kevin first asked for the free build to wait for a card; checked
against practice (AI site builders build free and charge to publish), it
became phone-verified instead, with publishing behind the card.
Check no_card_trial.py before building more trial or paywall behaviour.
