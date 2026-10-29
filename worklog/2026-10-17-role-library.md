---
title: The role library — every role is the church's own title on a job Chief understands; the Intercessor leader and prayer shared with the prayer team
date: 2026-10-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "build functions with definitions and details that helps chief know the role and what information each role should get. every church and their catagory … and also a way for people to create thier own roles and the wiring is the same"; on design canvas BKNqVVNiyxfAGAa7UAVWUC: "perfect. build it"'
status: shipped
prs: [kmj-intake-server#1477, solutionist-studio#1247]
migrations: [supabase/APPLY-2026-10-17-church-role-library.sql]
left_undone:
  - "Shepherding (every household gets an elder or deacon) is phase 3, as Kevin chose"
  - "The website leadership page and role terms beyond the term-end alert are phase 4"
  - "Care needs reach a care role only when a connect card (or a card with no kind) says so in words; there is no care-needs card of its own yet"
  - "Teachers, Kids & youth workers and Office roles are shown and described but not routed: classes, Kids check-in and office logins keep their own doors"
decisions:
  - "A role is a TITLE on one of ten fixed JOBS (senior, pastoral, prayer, care, ministry, team, welcome, teach, kids, office); the job is the wiring (what it may be handed, what it sees, what it never sees); a church's own roles use the same jobs"
  - "Eight church types (non-denominational, Baptist, COGIC & Pentecostal, AME & Methodist, Presbyterian, Church of Christ, liturgical, something else) with their titles on jobs; Chief guesses the type from the church's name, then its website only if the name says nothing and the site says so twice"
  - "The library fills the first time the office opens Leaders & roles; a card or Chief's read never fills it (before then the first version's four roles route as they did)"
  - "Kevin's prayer rule: prayer stays under the pastoral roles; an Intercessor leader (prayer job) is handed only requests the person chose to share with the prayer team; youth requests and anything about danger, abuse or a death always stay with the pastor (a trigger refuses the hand-off too)"
  - "A leader sees a first name and the words; how to reach them only when the person asked for a call and the role may see that; emails never carry the request's words"
  - "Kevin's chain: a late step goes to the role the leader answers to a day late and one more step up three days late; an empty role is passed over; a team answers to the role that has it under it"
  - "Chief reads the library (church_people section=leaders, read-only) and drafts a role on request (draft_church_role, class A); a draft hands nobody anything until the owner saves it"
related: [2026-10-17-church-leaders.md, 2026-10-17-church-leaders-trigger-fix.md]
---
Kevin wanted Chief to know each role and what it gets, for every kind of
church, with roles a church makes itself wired the same, and an Intercessor
leader for Love City now. The first version had four roles fixed in code,
five separate kinds of leader that didn't know about each other, no church
type anywhere, and Chief told about none of it.

- **Library** (`church_roles.py`): JOBS (allowed and default streams,
  sees, never, a definition template), STREAMS, TYPES (8 catalogs, titles
  on jobs, each with its place in the chain and the teams it takes),
  `guess_type`, `ensure_library` (fills once; keeps the first version's
  keys), create/update/archive with a no-loop chain, `set_type`,
  `chain_above`, `library()` for the page, `chief_lines`, `chief_draft`.
- **Routing** (`church_follow_up.choose`): by stream on the church's roles,
  the role made for a card before a broader one; a team's sign-up to its
  leader, else the role it's under, else up the chain. The sweep climbs
  each leader's own chain; term ends alert the office once.
- **Prayer** (`church_prayer.py`): consent and crisis columns on every new
  care request (member page radios, website "Who prays with you?", private
  care forms with a prayer_team field), hand-off load-balanced among prayer
  roles, the Lead tab's Prayer list (I prayed, Send a note, Pass it on), the
  office's Prayer & care fields, and its own late chain.
- **Routes**: `/church/leaders` returns the whole library; `/church/roles`
  POST/PATCH/DELETE; `/church/type`. The member Lead tab gains People |
  Prayer and an invitation that carries the role's definition.
- Applied the migration first (additive) after a rollback probe on Love
  City's rows; `__tests__/church_role_library_db.mjs` runs rows through every
  trigger (rehearsed: removing the consent rule turns it red).
- Tests: `test_church_roles.py` (39), `test_church_prayer.py` (25),
  `test_church_follow_up.py` updated (40).
