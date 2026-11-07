---
title: Credit packs say what they buy in flyers
date: 2026-11-07
agent: Claude Code (Claude Opus 5.5)
asked: "change the credit packs to say flyers"
status: shipped
prs: [solutionist-studio#pack-flyers]
migrations: []
left_undone: ["MoneyWebsitePanel in Mission Control still quotes the old pack numbers ($12·740 / $25·1,555 / $50·3,120)"]
decisions: ["Packs still sell credits and flyers stay in every plan: the count is a way to picture a pack, so credits stay beside it", "Stripe's page and the receipt use the same words as the app's button", "No add-on: Kevin floated $10 for 30 flyers; 33c a flyer undercuts the pack's 53c and the rule that nothing sells below a plan credit, and $10 tops out near 18 flyers"]
related: []
---
GET /billing/credits/{id} now sends `flyer_credits`, read live from the price
of a High image, so the card's "about 24 flyers" moves with the dial
(`credit_ledger.flyer_credits`). `credit_ledger.pack_name` names the pack on
Stripe's page: "740 Solutionist credits, about 24 flyers", where it used to say
"Solutionist credits — 740 units". An unreadable dial drops the count and never
stops the card or the sale. Nothing about what a pack costs or grants changed.

Cost behind the decision, measured from production on 2026-11-07 across 23
designs: 15c median, 16c mean, 25c p90, 40c highest. `image_artworks.cost_usd`
adds up renders only; the Claude plan and review calls are metered as
`llm:creative_director`, so read both before quoting what a flyer costs.
