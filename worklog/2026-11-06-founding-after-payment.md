---
title: A founding place waits for the first payment
date: 2026-11-06
agent: Claude Code (Claude Opus 5.5)
asked: 'yes. go ahead with all 4'
status: shipped
prs: [kmj-intake-server#PENDING, solutionist-studio#PENDING]
migrations: []
---

A church on a carded trial could claim one of the five free moves with no money
paid, and the place never came back. Now a church on its trial is told a place
takes its first payment and takes it by paying today: `pay_today` ends the trial,
which charges the card it put down, and the place is recorded only if Stripe
answers `active`. A card that fails takes nothing, and no charge is made once the
places are gone. A comped church owes no first payment. A church that has paid
and cancels keeps its place taken; nothing releases one, on purpose, because the
move may already be done. This matches the deck's line that the first month is
paid before the move starts.
