---
title: Leaders & follow-up — every church card becomes someone's job; leaders work it from a Lead tab in the member app
date: 2026-10-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "assign them to a person … chief assigned them properly … inserted into a workflow so no person gets left behind" and "assigning leadership roles to members … a login that allows them to have a special view"; on design canvas LG4Q97HqtEM4ByyXmmSrCP: "build it"'
status: shipped
prs: [kmj-intake-server#1473]
migrations: [supabase/APPLY-2026-10-17-church-leaders.sql]
left_undone:
  - "The office's pages (Operate → Follow-up board, Leaders & roles) are the solutionist-studio PR that follows; until then roles are added through POST /church/leaders"
  - "Care team and class teacher roles are in the table's check but not offered: prayer handed to member-app leaders and classes told who finished a path come next"
  - "Leaders are told by email (from the platform address; Love City has no verified sender). Texts wait on the texting registration; a push to the leader's phone is not wired"
decisions:
  - "Leaders are contacts (members), not seats: Kevin picked the member app over a seat in the full app"
  - "Chief assigns on its own (Kevin's pick): deterministic rules from the roles and the answers, with the reason written for the leader and the office; no AI reads the card"
  - "One follow-up per person per card while one is open: a second card adds a note"
  - "A logged conversation that reached them (Talked, Left a message), or an email/text from the church after the hand-off, finishes Reach out"
  - "Late ladder: on the day the leader is nudged, a day late the pastors are emailed and the office alerted, three days late the office is asked to hand them on; one message per rung"
  - "On a screen 1100px and wider the member app's tab bar is a rail down the left (all member pages)"
related: [2026-10-17-lcc-site-cards.md, 2026-10-16-church-cards.md]
---
Kevin wanted every card to reach a named person, with Chief doing the
assigning and nobody left behind, and a leader login that shows only their
part. Love City had 0 team seats, tasks had no assignee, and no card ever
reached Chief.

- **Tables** (server-only, `church_follow_up.py` is the one door):
  `church_leader_roles` (a member holds pastor / baptism minister / Welcome
  Team lead / a team's leader), `church_follow_ups` (one person, one card:
  the leader, why, the path's steps, the clock, the late level),
  `church_follow_up_notes` (conversations, Chief's assignment and nudges).
- **A card comes in**: `intake_endpoint` (after `form_submit`) and the
  website connect card (`public_site._capture_contact_from_form`) call
  `on_intake_form` / `on_connect_card`. The card's path comes from the card
  (baptism, serve, visit, connect, general; event and permission forms start
  none). `choose()` picks the leader: "talk with a pastor" or pastoral care →
  the pastor; baptism → the baptism minister; serve → the leader of the team
  they picked; visit / connect → the Welcome Team lead; no holder → the
  pastor, with the reason saying so; no pastor → the office.
- **The office**: `/church/follow-ups` (board, reassign, note, step, close)
  and `/church/leaders` (list with the Serve card's teams, ask a member to
  lead — they get an email — remove), manager+ like the care numbers.
- **The leader**: `/my/lead` in the member app (`member_portal_lead.py`).
  The Lead tab appears for a member with a role or an invitation. They say
  yes, then see only the people handed to them: why them, the card's
  answers, the path, Call/Text/Email, log a conversation (with "pastors
  only"), mark a step, hand back. On a computer the list and the person sit
  side by side, and the tab bar becomes a left rail.
- **The sweep** (`church_follow_up.sweep`, every 10 minutes, scheduler-gated)
  tells a leader once, alerts the office when there is no one, moves "Reach
  out" on when the church's email or text reached them, and climbs the late
  ladder.

Tests: `test_church_follow_up.py` (33, on an in-memory PostgREST) and
`test_member_portal_lead.py` (16). Rehearsed: making a leader read every
note, and breaking team matching, fail 8 tests. Migration applied to
production 10/17 after a rollback probe; the tables have RLS on and no
browser role can read them.
