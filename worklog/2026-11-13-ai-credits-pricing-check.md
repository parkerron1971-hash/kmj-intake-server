---
title: AI credits pricing check (30 days measured); ChurchSavvy alone carries no AI tank
date: 2026-11-13
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-13: "go ahead and making sure the ai credits are priced good as well"'
status: shipped
prs: [kmj-intake-server#1823 (ChurchSavvy plans 0 credits), kmj-intake-server#1822 (a failed Chief reply costs nothing), kmj-intake-server (business tanks + packs re-priced, this update)]
migrations: []
left_undone: ["the answer check (llm:chief_truth) is the leak: 24% of all AI spend; a separate session is working to cut wrong first-review rejections (each costs a repair + a re-check), with the replay bench, as a draft PR", "video caption timing (video_narration.word_timings) charges 1 credit per second of narration (60 a minute) against 0.6c a minute of cost; no use in 30 days; intent unknown", "extra texts: the 11-03 note that they lose 0.4c each is STALE. Since #1733 (same evening) a text is counted per 160-character part, so an extra part earns 2c against ~1.26c of cost; $30 per 1,000 is not needed for cost and was held for Kevin to decide", "claude-fable-5-2 has no row in api_usage_logger's price table (unused today)"]
decisions: ["business tanks re-sized against the re-measured cost (MEASURED_CHAT_COST_CENTS 7.37 -> 10.78, i.e. 0.898c a credit on Chief turns): Professional 7,500 -> 6,000 (36%), The Solutionist 17,500 -> 12,500 (38%), Founder 6,000 -> 4,200 (38%, still the cheapest credit at 2.357c); nobody paid for any of them (24 comped at practice, the heaviest using ~3,000)", "credit packs $13/740, $25/1,440, $50/2,880 (about 1.75c, 54% of price spent on AI) -> $18/740, $35/1,450, $70/2,920 (2.43c / 2.41c / 2.40c, about 40%), so no pack undercuts the cheapest subscription credit (Kevin's rule); zero packs ever sold", "ChurchSavvy-alone plans (cs_screens / cs_planning / cs_both) grant 0 credits, not Starter's 3,000: ChurchSavvy makes no AI calls and its app never reaches Chief; 0 is an allowance of nothing, None would be unlimited"]
related: [2026-11-03-church-plans-by-size.md, 2026-11-13-churchsavvy-included.md]
---
Measured 2026-11-13 from api_usage, 30 days, texts left out, every row priced
the way the meter prices it (`usage_metering.weight_for_row`): 4,135 rows,
16 businesses, $66.67 of AI ($63.32 with a business). 6,680 credits charged,
so a charged credit cost **0.95c** (0.62c on 11-03). A Chief turn averaged
20.3c (median 12c, p95 64c) and 22.6 credits, which matches
CREDITS_PER_MESSAGE=22. Rows charged nothing but costing money: $5.57
(keep-warm $2.83, site specs $1.31, standard voice $0.98).

At 0.95c a church plan's fully spent tank costs about 36% of its price
(Small $28 of $79, Growing $71 of $199, Established $142 of $399, Large $261
of $699), under the codebase's 40% line; real use is far lower. Credit packs
($13 / $25 / $50 at about 1.75c a credit) keep about 45% before Stripe's fee.

The ChurchSavvy-alone plans granted 3,000 credits each, a tank costing about
$28 if spent, on plans of $15 to $29. They now grant none.

**Update, the same day** (Kevin: "yes do all three credit fixes but my ask
was about the price of ai usage in the solutionist system"). What a credit
sells for, against 0.95c of cost: church plans 2.54-2.66c and Starter 2.63c
(fine); Professional 1.99c, The Solutionist 1.71c, Founder 1.65c and the
packs about 1.75c (too cheap). The three business tanks and the three packs
are re-sized above. The code's measured chat cost moved from 7.37c (July)
to 10.78c per 12 credits. Every pricing, plan, pack, site and founder test
passes (364).
