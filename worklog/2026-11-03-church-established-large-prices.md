---
title: Established Church is $399 a month and Large Church $699, with 15,000 and 27,500 Chief credits
date: 2026-11-03
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03, after the measured cost check: "go on all" (Established $399, Large $699, credits 3,000 / 7,500 / 15,000 / 27,500)'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "PRICE_TIER_CHURCH_ESTABLISHED_CENTS, PRICE_TIER_CHURCH_LARGE_CENTS, CREDITS_CHURCH_ESTABLISHED_CREDITS and CREDITS_CHURCH_LARGE_CREDITS (and PRICE_TIER_CHURCH_GROWING_CENTS from #1730) are set on both Railway services, so the site and checkout agreed while this was in review. They now match the code defaults and can be deleted"
  - "The plan cards' 'About N conversations with Chief' still divides by the chat price (12). A message actually charges about 22 credits; that line is a separate PR"
  - "The app's What's New entry for the church plans still names $299 / $599; updated in a separate frontend PR"
decisions:
  - "Measured, not estimated (30 days to 2026-11-03, production api_usage plus Twilio's own Usage Records): a Chief credit costs ~0.82c overall, ~2.8c on a cold message (the ~121k-token brief rewritten) and ~0.4c warm. At the old prices a full Chief tank was 48% (Established) and 41% (Large) of the price, over the 40% line the public ladder is held to; Small and Growing were 31%"
  - "Raised the price and trimmed the credits so all four plans sit at about 38 credits a dollar and a full tank costs ~31% of the price, leaving room for the deep lanes, which run on the top model on these two plans and charge no credits"
  - "Changed the day the plans went on sale, with no church on either plan. Stripe (live): new $399 / $3,990 and $699 / $6,990 prices on the same products took over the lookup keys (transfer_lookup_key); the old $299 / $2,990 / $599 / $5,990 prices were archived after a check that no subscription used them"
  - "The move fee follows the plan: three months is $1,197 on Established and $2,097 on Large"
related: [2026-11-03-church-plans-by-size.md, 2026-11-03-church-growing-199.md]
---
Before changing it I read `worklog/` in both repos. The plans (#1704), the
site (#1711), the logins and the move (#1710) and the Growing change (#1730)
all read these numbers from `pricing_config`, and the app reads them from
`/billing/plans`. In the frontend, only the What's New line names the prices.

Checked: 261 tests pass across the church, pricing, site and home files.
