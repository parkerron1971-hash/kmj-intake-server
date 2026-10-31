---
title: Text's person panel (groups, last visit, said yes) and Draft with Chief
date: 2026-10-31
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-31, on the two Text pieces still not built: "yes. work on those as well" (earlier: "On as they ship")'
status: in review
prs: [kmj-intake-server#1659]
migrations: []
left_undone:
  - "The frontend for both endpoints is a separate solutionist-studio PR"
  - "There is no 'member since' line: contacts carry no join date, and created_at is when the record was made (an import makes everyone 'since' the same day)"
decisions:
  - "GET /sms/person (viewer, like the conversation): groups and serving teams apart (kind 'team', or a serve_teams row), leaders marked; the last check-in (attendance); said yes by the announcement's own rule (sms_alerts.said_yes_to_texts) plus how (consent source, keyword, texted since own registration, or STOP). Any part that can't be read is null and the panel leaves it out"
  - "POST /sms/draft (member, the people who answer texts): the latest 16 texts of this conversation and public facts only: site_concierge.assemble_knowledge (the website helper's public-only set), saved replies, a church's next public occasions; at a church also their groups and last check-in. Nothing else about the business reaches the model"
  - "A fact it doesn't have is a [blank] (the response lists them so the box can hold the send until they're filled); it promises no call, visit or time unless the texts already did"
  - "No draft when their unanswered texts are about danger, abuse or a death (church_prayer.needs_pastor, which includes msg_screen.CRISIS_RE): held=true and a person answers"
  - "Metered as one AI action (llm_call.apost units=1, billing_limits.require_units first), spend_guard before the call, a fail-open per-person bucket text_draft (60/hour)"
  - "The draft comes back with straight quotes and dashes: one curly apostrophe makes every text in it 70 characters instead of 160"
  - "Model: chief_models.model_for('draft') with model_ladder.thinking_off_kwargs, so thinking can't eat the reply"
  - "Ships on (Kevin: 'On as they ship')"
related: [2026-10-30-text-room-people, 2026-10-30-text-room-announcements]
---
Before building I read both repos' `worklog/`: the only overlap is this
arc's own entries (10-29 mark-read, 10-30 people and announcements) and the
10-28 bulletin consent entry, whose `said_yes_to_texts` the panel reuses so
the panel and an announcement can't disagree.

`text_room.py`: GET /sms/person, POST /sms/draft (async: they share the
httpx reads with sms_alerts). `rate_limit.py`: the `text_draft` bucket.
Tests: `__tests__/test_text_room_person_draft.py` (35).
