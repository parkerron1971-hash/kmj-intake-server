---
title: The marketing suite's plan gates, dormant and unannounced, and the build plan
date: 2026-10-07
agent: Claude Code (Claude Opus 5.5)
asked: "This will work. let's build this."
status: done
prs: [kmj-intake-server marketing-plan-gates]
migrations: []
left_undone: ["The rest of the marketing suite: docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md, PRs B1 and B3 to B16, F1 to F8"]
decisions: ["Three keys: marketing_suggestion (every plan), marketing_week (Professional, and Boss barber-sized), marketing_autopilot (Solutionist)", "Posting what the owner asks needs no key: the pricing page promises it to every plan", "plan_includes() reads the real plan whatever BILLING_ENFORCE says, for anything that spends money unasked", "All three unannounced and off the compare table until the desk ships"]
related: [2026-10-02-marketing-desk.md]
---
Kevin approved the marketing suite design (one desk for every business; the
plan decides how much of the work Chief does) and asked to build it. This PR
adds the build plan (docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md) and the
three plan gates. Nothing changes at runtime: no screen or job reads the keys
yet, and they stay off the plan cards and the pricing table until launch.
