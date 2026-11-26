---
title: Chief carries each church's fact sheet, and every church room says whether Chief can read it
date: 2026-11-26
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-26, on my recommendation (the church fact sheet first, then two giving skills behind a switch): "build in the recommended order". Step 3 of the awareness plan of 2026-11-22'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "45 of the menu's rooms have no Chief lookup (church_room_lookups.NO_LOOKUP): the order of service, kids check-in, check requests, pledges, recurring gifts, the board and others. Chief is now told which; each one stays a gap until a lookup is built"
  - "A room in LOOKUPS is read in part where its lookup is narrower than the page (Members through church_people). The map says what Chief can say, not that it sees all of the page"
  - "No production church's sheet was read: what it says at Love City or Elevation of Grace has not been seen"
  - "No live Chief eval was run"
  - "Next, as agreed: two giving skills behind a switch that starts off (Sunday count, year-end statements)"
decisions:
  - "church_facts.text_for: a short sheet from the church's own tables (its clock, services and their times, ministries and departments, worship ministries, groups and when they meet, classes, rooms, and what is switched on: online giving, texting, kids check-in stations, the stream relay, church email). About 430 tokens for a small church, at most 4,000 characters"
  - "In the per-church cached segment beside the church's menu, so it is the same for every login of a church and caches. So it carries no money figure, no fund and no person's name: every login reads that segment, and Giving & money isn't everyone's. Who does what stays THE OFFICE, shown only where it may be"
  - "Nothing that moves by the day (this week's numbers): text that changed every turn would rewrite the cached segment every turn"
  - "Kept ten minutes a church a replica (a minute after a failed read), read beside THE OFFICE before the prompt, off the event loop. A section that couldn't be read is named and never written as none"
  - "Names are as the church typed them: quoted, cut to 60, tag syntax stripped, and left out when untrusted_text.detect_injection matches. Here a dropped name costs one word in a list, unlike a summary, and the text sits in Chief's own instructions"
  - "church_room_lookups: every page on a church's menu (church_findway.json) is in exactly one of LOOKUPS (the read actions that answer it), NO_LOOKUP (a gap, named) or NOT_A_ROOM. __tests__/test_church_room_lookups.py fails for a page in none of them, in two, or a lookup that isn't one of Chief's reads: a new church room can't ship with nobody deciding whether Chief can see it"
  - "Chief is told the NO_LOOKUP rooms by their menu names: use only what the prompt already shows of one, then say what the room is for and offer to open it; never guess what is in it or say it is empty"
  - "CHIEF_CHURCH_FACTS=off turns it off"
  - "After an independent review, which found the first version not safe to merge. (1) 'Online giving is connected' came from a Stripe account alone; it now uses the giving page's own rule (giving_router.giving_is_active), and says when Stripe is connected but the page is off. (2) A draft texting registration read as sent; every status now says where it stands. (3) Over 4,000 characters the cut dropped the couldn't-read and can't-read lines; those now come first and the lists shrink instead. (4) Approvals, notifications and the calendar are in Chief's context every turn, so they are no longer called rooms it can't read (IN_CONTEXT). (5) Two wrong mappings fixed: Bills on a church's menu is what it sends, not what it owes, and the giving page is not the budget funds. (6) Invite-only and youth groups are not listed for joining; a group's time is the one its leader set; 'coming once' services use the church's own day; counts say 'at least' when a read hit its limit. (7) Any writing seat, a Member's included, can name a group, so a name with words an instruction would use (chief, ignore, always, never, rule, system, treat, reply) is left out as well"
related: [2026-11-22-chief-church-lookups.md, 2026-11-22-chief-who-im-talking-with.md]
---
Read both repos' work logs first; nothing open touches the per-church segment.

`church_facts.py` and `church_room_lookups.py` are new; `chief_of_staff.chief_chat`
reads the sheet beside THE OFFICE and passes it to `chief_prompt._build_system_prompt`,
which places it after the church's menu. Tests: `__tests__/test_church_facts.py`,
`__tests__/test_church_room_lookups.py`.
