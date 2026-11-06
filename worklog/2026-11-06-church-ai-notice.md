---
title: A church reads How AI works in its own words
date: 2026-11-06
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-06: "make the changes for how chief uses ai notice"'
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio church-ai-notice (the gate)]
migrations: []
left_undone: []
decisions:
  - "A version of the practitioner document ('church-1'), not an edit and not a new audience: V1 and its hash are untouched, and consent_records' audience check needs no migration"
  - "The church text is not a find-and-replace. The regulated-field line is dropped (a church isn't one, policy_engine._REGULATED_HINTS), and 'confirming the list on screen' became 'unless someone asked it to' (policy_engine refuses bulk unattended; on request it runs, Kevin 10-30)"
  - "One line added: Chief does not replace your judgment in pastoral care, money, or the safety of children. A caution, not a product claim"
  - "A church can't accept the business text (409): the record has to hash what was shown"
  - "A church that accepted V1 is asked once more; a business is never held to the church's text"
related: []
---
A church read about "your clients", "your business" and "an invoice" in the one screen that interrupts everyone. Every sentence of the church's version was checked against the code before it was written, because this is consent text.
