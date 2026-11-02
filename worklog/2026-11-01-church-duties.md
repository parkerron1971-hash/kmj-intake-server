---
title: A church's office jobs are duties a login holds, moved one at a time
date: 2026-11-01
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-01: "a general structure plan and customize roles as well" ... "yes the duties part would be great, but you would make the changes for love city directly but chief would do other churches"'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: [supabase/APPLY-2026-11-01-church-duties.sql (not applied)]
left_undone:
  - "Apply supabase/APPLY-2026-11-01-church-duties.sql, then set Love City's rows (docs/CHURCH_DUTIES.md, Love City's structure: naming Jessica on a duty moves it, so each covered duty names its lane's person too)"
  - "Step 2: the job gates read duties (the weekly text, boards, chat rules, rooms, event sign-ups, the marketing desk, clips, the site and the events page, ChurchSavvy parts) through church_duties.require; decide what a Manager with no lane keeps"
  - "Step 3: Chief's list_duties and move_duty (a proposal the owner approves), for other churches"
  - "Step 4: FE Settings → Logins & areas gains Duties per login; buttons follow my-role.duties; ChurchSavvy's team list shows lanes"
  - "Step 5: the member app's Request a pay-back goes to the treasurer's queue"
  - "Step 6: Jessica's view: See as, the roll-up, Tasks by person, and the monthly report"
  - "Step 7: Your week: each duty's day and training line make the week band and the walkthrough"
decisions:
  - "The owner and Admins hold every duty; a Manager its lane's defaults until a duty moves, then only rows decide that duty; a money duty is never a Manager's, whatever a row says"
  - "A Manager's lane is business_users.lane, else the lane its picked areas are exactly; Chief's guess at areas never makes a lane"
  - "The Executive Pastor is a pseudo-lane: the login whose person holds the role (key or catalog_key, said yes to); a login tied to a contact is only that contact; else one email naming exactly one person"
  - "A move is one RPC (church_duty_set): holders, the log row and an undo mark in one transaction"
  - "PUT takes the duty's whole list; [] or null puts it back to the lanes; Members and Viewers can't be given a duty; undo steps back one change at a time and won't hand a duty to someone who can't hold it now (409)"
  - "CHURCH_DUTIES gates the routes only; holds() works whatever it says. my-role carries duties for any church login and leaves them out on any error"
  - "Both tables are EXPORT_EXCLUDED: sign-in user ids, like church_keepers"
related: [2026-10-26-who-sees-what.md, 2026-10-28-church-office-lanes.md, 2026-11-01-care-inbox-people-care.md]
---
`church_duties.py` (CATALOG of 24 duties, STARTER, holds/require/duties_of,
GET/PUT/undo under /church/duties), `/team/my-role` gains `duties`, the
migration and its PGlite check (`__tests__/church_duties_db.mjs`), tests in
`__tests__/test_church_duties.py`. Nothing calls `require()` yet. The plan is
`docs/CHURCH_DUTIES.md`, with what this step changed from it at the bottom.
