---
title: Chief keeps proposed plan steps when narration fails verification
date: 2026-10-02
agent: Codex (GPT-6)
asked: "Improve Chief conversation flow after a short two-day plan became a records warning"
status: shipped
prs: []
migrations: []
left_undone: ["Owner retest of the new reply recovery"]
decisions: ["Plans prove display and step count, not their authored factual premises", "Recovery uses closed generic proposals or independently matched open-invoice targets"]
related: []
---
Added plan-specific recovery so safe proposed steps survive rejected narration without a generic records warning. Titles, dates, and rationale authored by the model cannot become evidence for their own claims. Named invoice reminders require a matching current open-invoice record; embedded instructions and unsupported factual premises are excluded. Suggested scheduling stays relative to the request, and no plan step executes during recovery.
