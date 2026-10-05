---
title: Plain words for the problems Chief keeps an eye on, in every trade's own vocabulary
date: 2026-10-05
agent: Claude Code (Claude Opus 5.5)
asked: 'yes do the wording pass for all the businesses'
status: shipped
prs: []
migrations: []
left_undone: []
decisions: ["the owner never reads case, forecast, baseline or the records show", "counts use vertical_terminology: barber appointments, coach sessions, lawyer consultations, church meetings/members, contractor visits", "the trade word is stored on the case at opening (measure.unit) so no later line needs a lookup", "API keys before/forecast/result unchanged so the deployed card keeps working"]
related: [2026-10-05-chief-cases.md]
---
Kevin asked whether the SI layer reads right to a barber. Chief's spoken line did;
the chips, alerts and card did not ("Case opened", "short of the forecast", "the
records show 6 bookings"). Every owner-facing string in chief_cases.py now says
keeping an eye on / hoping for / before / now, in the business's own word, and Chief's
prompt and context say the same so it does not parrot the code's words. The weekly
advice eval gains a barbershop (Fade Street Barbers) asked about dead Tuesdays and a
plain_words check on every reply, now part of the SI score line.
