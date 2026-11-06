---
title: A church's setup list speaks church
date: 2026-11-06
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-06: "fix the issues that we have ran into ... make those changes that you list so thing can offically work"'
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio church-words-after-setup (Home, Payments, Chief, the plan card, search)]
migrations: []
left_undone:
  - "The AI disclosure (How Chief uses AI) is versioned, hash-pinned consent text; a church version is a legal-text change, not made here"
decisions:
  - "business_track_actions.VERTICAL_WORDS overrides only title / why / chief per vertical; the step, its door and its done-probe stay the catalog's"
  - "A church: 'Bring your people over' (members, guests and families from Subsplash, Planning Center or a spreadsheet) and 'Connect Stripe for giving' (gifts reach the church's bank). The site and brand whys drop selling and invoices"
  - "Chief's own menu of steps (_plugin_menu_for_prompt) and the payments how-line use the same words"
related: [2026-11-06-church-import-families.md]
---
The run-through's new church saw its first steps in business words: "Bring your client list over" because "history, campaigns, invoices ... read from your contacts", and "Connect how you get paid" because it "turns an invoice from a PDF into money that actually arrives". __tests__/test_church_setup_words.py checks that no step a church is shown carries client, invoice or customer.
