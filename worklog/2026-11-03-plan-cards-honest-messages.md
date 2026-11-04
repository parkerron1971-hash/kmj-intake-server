---
title: Plan cards say how many messages to Chief a plan holds, at what a message really charges
date: 2026-11-03
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03: "go on all" (one of the four: fix the message counts on the plan cards)'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "22 is a measurement over 171 messages, most of them Love City's. Re-measure (credits charged per turn_id over 30 days) once paying churches have a month of use, and move CREDITS_PER_MESSAGE if it differs"
decisions:
  - "Every 'about N conversations' line divided a plan's credits by the chat price (12). A message is often two or three model calls, each charged 12, plus the answer check: measured over 30 days of production api_usage, a message charges about 22 credits. So the cards promised about twice what a plan holds (Small: 'about 250', really about 135)"
  - "One divisor, pricing_config.credits_per_message() (CREDITS_PER_MESSAGE, default 22), used by marketing_pages._credits_in_words (the main site's cards) and church_site (the church and coach plan cards, the meters and the line under 'Chief comes with every plan')"
  - "The word is 'messages to Chief', not 'conversations': a conversation sounds like several messages, and the count is per message"
  - "Metering is unchanged. Charging 12 per message would put a full Small tank at about 90% of its price (a message costs ~29c all in, ~59c cold, ~10c warm)"
related: [2026-11-03-church-established-large-prices.md, 2026-11-03-church-plans-by-size.md]
---
Before changing it I read `worklog/` in both repos. Nothing else touches
these lines. The app's plan cards draw no conversation count, so the
frontend is unchanged.

The main site's three cards now read about 125 / 325 / 775 messages to Chief
(were 250 / 625 / 1,450). The church cards read about 125 / 325 / 675 / 1,250
messages a month on Small, Growing, Established and Large.

Checked: 183 tests pass across the church, coach, Meet Chief, pricing, home
and plan files.
