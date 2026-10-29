---
title: Chief says who's talking — an office login is greeted by its own name, and what it sends is signed by it, never as the owner
date: 2026-10-28
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-28 (through kmj-intake-server-60): Love City''s new office logins sign in and get greeted as Kevin, and an email Minnie had Chief send signed off as him; "lets build the board tab and so we can add the lanes for chief"'
status: shipped
prs: [kmj-intake-server#1641]
migrations: []
left_undone:
  - "A draft approved from the Approval Queue page (outside a Chief turn) still signs as the church's signature, whoever taps it"
  - "The strategy and business coaches still name the owner (they're the owner's)"
  - "The draft writers' inner prompts (draft_nurture, draft_email, rewrite_draft) use the seat's name but aren't covered by a test: they call the model"
decisions:
  - "Who: any login that isn't the owner's, admins included (business_users_router.seat_person, from #1638). A seat nothing names is no one by name: Chief uses no name and signs from the church, never the owner's practitioner_name"
  - "The owner's prompt and sends are byte-for-byte as before (chief_areas.speaker returns settings.practitioner_name exactly)"
  - "A TALKING WITH line rides the turn's tail beside the lane block; the greeting and persona name the seat in _build_system_prompt, so a seat's prompt caches on its own"
  - "Emails a seat sends through Chief (queued email, batch email, invoice, revenue report): from the seat's name; the church's signature with the seat's name and without the owner's title; {practitioner_name} is the seat"
  - "A failed read keeps today's Chief (it may be the owner); a cached minute a replica, like the lane"
related: [2026-10-28-chief-areas.md]
---
chief_areas.py gains who_for (the seat's person), WHO (the turn's speaker, set beside the lane scope in chief_chat), speaker / sender / signature, and the TALKING WITH line in block(). chief_prompt greets and names the seat (first name; none when nothing names them), and chief_of_staff's senders and draft writers use it. Tests in __tests__/test_chief_areas.py.
