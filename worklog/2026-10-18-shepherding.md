---
title: Shepherding (server) — Chief suggests families, proposes a shepherd for each, elders log their touches
date: 2026-10-18
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-17: "yes you can start design and do as what we planned and those that can shepherd are elders and pastors. visitors should go under welcome for now", then "everything else is good" (Ministers off, 12 per shepherd and 10 for the Lead Pastor, monthly). Round 1 of the build from canvas 31su6kdYmYecH5b2NxjBJN (boards 1-3, 6-8)'
status: in progress
prs: [kmj-intake-server#1485]
migrations: [supabase/APPLY-2026-10-18-shepherding.sql]
left_undone:
  - "Round 2: drifting (missed three Sundays, with the 2-of-6 pattern guard), due-a-touch, care-need notices, birthdays, the new-member proposal, the late chain up the roles, and the Chief section with the Monday brief. Round 1 copy promises none of it"
  - "The office screens (Operate, Follow-up, Shepherding; the suggestions on Families) are the frontend PR built against the same contract"
  - "A shepherd's \"they were there\" for someone who forgot to check in comes with round 2's drift"
decisions:
  - "Shepherds are the senior role and pastoral roles titled pastor, elder, bishop, overseer or shepherd; roles titled minister follow the Ministers switch (off). Stewards, Missionaries, Deacons and the Care team are not shepherds. Only holders who said yes"
  - "A unit is a recorded family with a member in it, or a member in no family (a family of one, made a household when the pastor approves). Children are never units. Visitors (status lead) stay with Welcome"
  - "Families are guessed by last name (Jr/Sr/III dropped, case ignored), split by street; sure = a shared street, phone or email; likely = 2-6 with nothing against it; a question = 7 or more, people with no address beside two addresses of that name, or two last names at one street (never merged)"
  - "A member under 18 joins as a children row linked to their record (children.contact_id), never as a household adult: household adults may pick children up at the Kids kiosk. Accepting re-checks every age on the server"
  - "The proposal: someone who knows them (leads a group one of them is in, or took one of their cards), then the same ZIP, then the emptiest list; never their own family; never over the cap (Lead Pastor 10). The pastor's moves are kept when Chief proposes again; over the cap only by the pastor's choice, and shown"
  - "Approve writes every family the proposal places and sends each shepherd one email; a failed row stays in the draft. Moving one family later emails the new shepherd"
  - "A shepherd's family page shows adults by name with call/text/email, children by first name and age; never giving, prayer kept for the pastors, or a child's care notes. Touches are visible to the family's shepherd (the next one too) and the office. Needs a pastor emails the senior role's holders only"
  - "Reached = a touch in the last 30 days (the rhythm), labelled that way on the Lead tab rather than \"this month\""
related: [2026-10-17-sunday-checkin.md, 2026-10-17-role-library.md]
---
Round 1 of shepherding: the families, who shepherds whom, and the
shepherd's own page. Love City had 148 members and no families, so the
first thing Chief does is guess who lives together. On the real rows that
is 22 suggestions (2 sure, 15 likely, 5 to check) covering 67 people, and
81 members on their own (9 of them children); 35 members have a usable
address, 32 are under 18.

The migration was rehearsed whole and rolled back, applied, and probed
again: every trigger took a real row and ten cross-church or malformed rows
were refused both times.

Love City has one active shepherd today (Pastor KMJ, Lead Pastor, 10 at
most), so a proposal now places 10 families and the rest wait, which is
what the page says until elders say yes to their roles.
