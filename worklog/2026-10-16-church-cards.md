---
title: A church's cards — the website's own connect card and prayer request, and what came in on each (GET /church/cards)
date: 2026-10-16
agent: Claude Code (Claude Opus 5.5)
asked: 'On the Forms & classes redesign canvas (Love City Church): "redesign is good. give an easy way for people to function and make things happen. awesome build this."'
status: shipped
prs: [kmj-intake-server#1467, solutionist-studio#1241]
migrations: []
left_undone: []
decisions:
  - "Website cards are read from the published pages (html_content + site_config.generated_pages), never stored twice: a <form data-church-form> is the card, its labels and legends are its questions"
  - "Counts come from the rows each door already writes (events contact_note/form_submit, ministry_care_requests); no new table"
  - "Prayer and private forms are numbers only; who filled in a public card is owner and staff (business_access manager), the care numbers' seats"
  - "90-day window, the same as the care numbers"
related: [2026-10-15-church-care-counts.md]
---
The church Forms page listed only intake_forms, so Love City — whose
website takes connect cards and prayer requests through contact-submit —
was told it had no forms. `church_cards.py` finds the cards in the
church's own site HTML (questions in order, choices, required marks, the
send button; the honeypot left out) and counts what came in on each card
and each intake form, with who filled in the public ones (distinct people,
most recent first). The app's Next steps road draws "moved on" from those
people. Also adds `build/next-steps` to the shared destinations.
