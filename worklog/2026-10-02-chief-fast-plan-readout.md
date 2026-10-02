---
title: Chief reads useful proposed plan steps without duplicate narration and review
date: 2026-10-02
agent: Codex (GPT-6)
asked: "Fix the gaps after retesting Chief's short suggested plan"
status: shipped
prs: [kmj-intake-server#1210]
migrations: []
left_undone: []
decisions: ["Normalize the card and speech together", "Amounts, dates, and factual premises do not become proposal facts", "Direct delivery applies only to explicit single plan displays"]
related: [2026-10-02-chief-plan-recovery.md]
---
Rich plan steps now retain useful task intent without repeating unsupported counts, dates, quoted messages, or rationale. Specific invoice references require matching current open-invoice records. A successful single display-only plan shares the normalized card and spoken readout before the duplicate composer and general-review model calls; mixed requests remain on the normal path. The shared helpers also support the coordinating session's bounded quick-plan route.
