---
title: A layout picked before this ask is offered again, against what fits the ask
date: 2026-11-10
agent: Claude Code (Claude Opus 5.5)
asked: "go, fix the two gaps first and make it happen"
status: shipped
prs: [kmj-intake-server#1786]
migrations: []
left_undone:
  - "Picks saved before today carry no date, so every one of them counts as earlier than the next ask. That is the point (they were made under the old ranking), but it means one extra gallery for owners who pick again."
decisions:
  - "The old pick still binds the build until the owner chooses: the Director keeps reading THE OWNER PICKED. Only the Coach's cards rank without it."
  - "The Coach offers the switch once, with the new best fit first and the old pick second, and never switches it for them."
  - "Only taste.layout is dated. The other gallery picks don't compete with the ask."
related: [2026-11-09-layouts-follow-the-ask.md, 2026-11-09-coach-reads-the-ask.md]
---
The live retest on the test shop: a day earlier, as the owner, I tapped the
Long-scroll story when the old ranking recommended it. Today the owner asked for a
site "so people can find me and book, nothing fancy", and the saved pick kept
leading, because an owner's pick always leads. The Coach's summary said "a
long-scroll story" until the owner objected; then it switched to the Booking desk.

A layout pick is now dated when it's saved (`apply_practitioner_patch`, which the
Coach and the blueprint card's layout button both go through).
`discovery.layout_picked_before_ask` finds a pick older than the current ask, and
`design_coach._layout_rank` then ranks the cards without it: the new best fit
leads, is marked Recommended, and the old pick's card says "You picked it last
time". A note tells the Coach to show that gallery once before the summary.
