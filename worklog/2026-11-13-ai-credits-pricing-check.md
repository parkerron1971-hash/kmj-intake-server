---
title: AI credits pricing check (30 days measured); ChurchSavvy alone carries no AI tank
date: 2026-11-13
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-13: "go ahead and making sure the ai credits are priced good as well"'
status: shipped
prs: [kmj-intake-server (this PR: ChurchSavvy plans 0 credits), kmj-intake-server (a failed Chief reply costs nothing)]
migrations: []
left_undone: ["the answer check (llm:chief_truth) is the leak: 24% of all AI spend ($16.21 of $66.67), charged 1 credit at about 3c each; make it cheaper rather than charge churches more (Kevin to choose)", "Professional $149 / The Solutionist $299 / Founder $99 business plans: a fully spent tank now costs 48% / 55% / 57% of the price at 0.95c a credit, over the 40% line; church plans are about 36%", "video caption timing (video_narration.word_timings) charges 1 credit per second of narration (60 a minute) against 0.6c a minute of cost; no use in 30 days; intent unknown", "extra texts at $20 per 1,000 still lose about 0.4c each ($30 recommended 11-03, waiting on Kevin)", "pricing_config comment says practice is 1.596c a credit; the code gives 1.71c", "claude-fable-5-2 has no row in api_usage_logger's price table (unused today)"]
decisions: ["ChurchSavvy-alone plans (cs_screens / cs_planning / cs_both) grant 0 credits, not Starter's 3,000: ChurchSavvy makes no AI calls and its app never reaches Chief; 0 is an allowance of nothing, None would be unlimited"]
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
