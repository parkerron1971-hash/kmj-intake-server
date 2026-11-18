---
title: One sheet per person, a church's own jobs, and who may set them up (server, step one)
date: 2026-11-17
agent: Claude Code (Claude Fable 5.2)
asked: 'Kevin, 2026-11-17, on the artifact "One sheet per person": "yes to all and build it. also allow for custom roles to be set that way, it becomes easy for other churches to set there own leadership flow. and allow for chief to assist and help create description roles and responsibility for ones that are not preset in the system", then "also allow for permission to be given to a person to create roles like how my wife over administration team, she should be able to alter roles and or things if needed."'
status: in review
prs: ["kmj-intake-server (this change, branch church-person-sheet)", "solutionist-studio (the app's half, branch church-person-sheet)"]
migrations: ["supabase/APPLY-2026-11-17-church-jobs.sql (NOT APPLIED: church_jobs, church_sheet_changes; the code works before it)"]
left_undone:
  - "The older Logins & areas route (PUT /church/areas/login) and the Duties tab move a login's areas and duties for the owner and Admins with no password asked, as they did before this change. Only the sheet asks. The areas route is the owner's and Admins'; the Duties tab is theirs and whoever is over the lanes, so a holder gets nothing from either by holding the grant."
  - "business_access puts the business id into a PostgREST path as it came. The sheet's two reads check it is a UUID first; every other route that depends on business_access does not."
  - "Steps two to five of the artifact: the rulebook (every page, server door and Chief action names its tick), the levels See / Work / Lead and the guarded ticks, giving as its own tick without an Admin login, the standard start, Chief everywhere."
  - "The sheet does not change a login's level (Viewer, Member, Manager, Admin): that is still the invite's. A job that is a different level from the login is only a label."
  - "A duty a login does by its job alone can't be taken off on the sheet when nobody else does it: the Duties tab names who does it instead."
  - "GET /church/jobs was already the job descriptions' roster. It now carries the jobs too, but only where that page opens (CHURCH_ASSIGNMENTS, its table). GET /church/sheet/jobs is the read that always answers."
  - "system_destinations.json and church_findway.json are not touched here: the parent session exports them after the app's half lands."
  - "No production read or write, no live Chief turn. The step-up on the PUT was exercised through the route with no unlock header (403 ledger_locked), not with a real password."
decisions:
  - "No rule changes: the sheet reads level, job, areas, duties, keys and the job description together and writes job, areas and duties through the writes they already had (church_areas.set_login, church_duties.move). Giving & money is still an Admin login's alone."
  - "A custom job lives in a new server-only table (church_jobs) and its key rides business_users.lane, where a lane's key already rode. Every reader of that column that only knows the five lanes falls back as before; the label is resolved in my-role, the invite's welcome, Logins & areas and Chief's reads."
  - "A job is a label and a starting point. Picking one fills areas and duties only when the caller sends them; changing or removing a job never changes a login that holds it. Removing is a soft delete so the login still reads as its title."
  - "The grant (Sets up jobs and people's sheets) is NOT one of the duties: a duty is a weekly job in My week, the Executive Pastor's lane holds every non-money duty by default, and a dozen tests pin the catalog's shape. It is a row in the duties' own holder table (church_duty_holders) under the key jobs_and_sheets, written by the duties' own RPC, so who gave it, when, and every change are in church_duty_changes with no new table; church_duties._moved leaves non-catalog keys out of every duty reading."
  - "A holder is a Manager login the owner or an Admin gave the grant to. The owner and the Admins are never holders. A holder moved down to Member or Viewer stops being one."
  - "What a holder changes is recorded (church_sheet_changes, best effort) and told to the owner by a phone alert and an email, off the request. The owner's and an Admin's changes are recorded and not told."
  - "Chief has no verb that changes a person's sheet. It reads one (sheet_of), drafts and saves job definitions (save_church_job, remove_church_job) for the owner, an Admin or a holder, and opens the sheet for the person to save with their password (navigate operate/areas with sheet: the login's id)."
  - "The five Chief verbs are placed for every office login in chief_areas.VERBS, not OWNERS, because a holder is a Manager: each handler asks church_job_defs.editor and church_sheet.standing, the routes' own checks."
related: []
---
The sheet is one read and one write over what a church already had.

`GET /church/sheet` composes a login's level, job, areas (picked, shown, Chief's
guess and why), every duty as a tick with who else does it, what is guarded and
whether it is open to them, their job description, and what Chief does for them
and sends elsewhere, in plain sentences built from the same areas Chief keeps
to. It also says what this editor may not toggle (`locked_areas`,
`locked_duties`, `locked_why`) and, for a holder, the limits in sentences.

`PUT /church/sheet` checks everything first, then writes each part through its
own write. A change that leaves someone with more asks for the password again,
as an invite does; one that leaves them with less never does. "More" is judged
by the result: the areas the login is shown and the duties it holds are worked
out before and after the planned write, so taking an area off (which can spell
a different lane), clearing a job, or sending a login back to Chief's guess
asks too when it gives. A holder's ceiling is held on the result as well, and a
holder never sends a login back to Chief's guess.

`POST /auth/step-up` (ledger_unlock) now lets the owner, an active Admin, or an
active Manager holding the grant re-prove their own password for `access`;
`danger` stays the owner's. Before this only the owner could, so an Admin could
never confirm an invite and a holder could never give anything.

A login taken off the team loses the grant (hand_back_login), and a login that
has just joined holds none left from before. `church_jobs` is exported with the
church and not restored on import, as its job descriptions are;
`church_sheet_changes` is not exported, as the duties' and descriptions' logs
aren't.

`church_jobs` holds the jobs a church makes beside the five starting ones.
`POST /church/jobs`, `PUT /church/jobs/{key}` and `DELETE /church/jobs/{key}`
are for the owner, an Admin or a holder; an Admin job is the owner's.

Tests: `__tests__/test_church_sheet.py` (125). The related files around what was
touched were run by name, never the whole suite.
