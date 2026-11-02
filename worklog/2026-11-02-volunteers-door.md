---
title: Volunteers, beside ChurchSavvy - Sunday's teams each have an owner, and each person schedules their own
date: 2026-11-02
agent: Claude Code (Claude Opus 5.5)
asked: '"volunteers and roles laquesha is doing is her assignment. so maybe we create a volunteers service thing that is like churchsavvy but with the minus of production part", then "yes churchsavvy for worship team, announcements to shapretta. go"'
status: in progress
prs: [kmj-intake-server#1700, solutionist-studio#1450]
migrations: [supabase/APPLY-2026-11-02-serve-team-owner.sql (applied 2026-11-02)]
left_undone:
  - "Apply supabase/APPLY-2026-11-02-serve-team-owner.sql (Kevin), best before or with the merge: SUNDAY_PLANNING is on, and until the column exists every team reads as Volunteers', so Shapretta (production_schedule, churchsavvy_team) changes none"
  - "Order-of-service notes (sunday_order PUT /planning/order/notes) still follow CAN['serve'] alone, not the team's owner"
decisions:
  - "One schedule (sunday_planning), two doors: serve_teams.owner is churchsavvy (worship and production) or volunteers (every other team)"
  - "In a church (is_church, not ChurchSavvy alone): the owner and Admins change any team; production_schedule or churchsavvy_team, and ChurchSavvy's own team's planners and admins (the worship pastor), change ChurchSavvy's; serve_schedule changes Volunteers'; anyone else is refused with church_duties.refusal"
  - "Reads are whole: every team and every ask for everyone who opens Planning; owner= on /teams and /schedule shows one door"
  - "A new ChurchSavvy part, scheduler, from serve_schedule: CAN['serve'] only, never an invite (worship_team.roles keeps its five parts)"
  - "A new team's owner: the one asked for, else its maker's one door, else its name (the migration's backfill rule)"
  - "Before the migration every team reads as Volunteers' (only a 42703 from PostgREST says the column is missing; a blip is a 503)"
related: [2026-11-01-church-duties.md, 2026-11-01-media-gates-duties.md]
---
`sunday_planning.py`: "whose team it is" (`_scheduler`, `_team_gate`, `_owners_for`, `_serve_rows`); every write on a
team (its turns, places, who's trained, ask, offer, answer, take back, fill and unfill) checks the team's owner.
`worship_team.py`: the scheduler part and PARTS_FROM_DUTIES (serve_schedule is scheduler, production_schedule planner).
Tests: `__tests__/test_volunteers_door.py` (every write by every persona on each kind of team) and
`__tests__/serve_team_owner_db.mjs` (the migration on PGlite).
