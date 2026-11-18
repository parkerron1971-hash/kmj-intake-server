---
title: The standard start, a church's structure draft from five questions or from its planning course
date: 2026-11-18
agent: Claude Code (Claude Fable 5.2)
asked: 'Kevin, 2026-11-18: "now with these upgrades, will the system know what to do with other churches? I want to make sure that other churches would have the right type of setup when it comes to setting up there structure and that is will be easy and chief would know what to do without there being any issues", then "standard start first, then giving also consider adding the setup with the church planning strategy. this area would be a huge help in the process because it would make it easy for churches to communicate that and get what is needed if they choose to go that route."'
status: in progress
prs: []
migrations: [supabase/APPLY-2026-11-18-church-structure-drafts.sql]
left_undone:
  - "Not pushed: two local commits on the branch church-standard-start, for the parent session to open as a PR beside the app's half."
  - "The app's half (the review on Logins & areas, the setup flag, applying a draft through the job, invite and sheet writes) is built by a sibling session against the same contract."
  - "The migration is NOT applied. Until it is, no draft can be made (ready false, a write is a 503); the standing check works."
  - "No database test for the new table (the PGlite checks need a side-install here): a Python test pins the file's shape instead."
  - "No model was run: Chief's five questions, the read-back and the coach's one offer are instructions that no eval has exercised."
  - "EXISTING LOGINS, at deploy: a login already on one of a church's own jobs stops holding the duties its areas gave it (and a starting job's duties its areas happened to spell) until those duties are given on its sheet. No production read was made, so how many there are is not known. To list them before deploying: select business_id, user_id, lane, areas from business_users where status = 'active' and role = 'manager' and lane is not null and lane not in ('office_leadership','people_care','sunday_serving','media_comms','treasurer');"
  - "A person with nothing to switch on (no job, or a job with no areas) is drafted as a Viewer, but the team invite cannot carry areas without a job that has them: invited as they are, they would open the whole church (read-only) until their sheet is saved. The note on the person says so and the gap flags it. The app should not offer Invite for them."
  - "A title that reads as the office's (Secretary, Clerk, Administrator) still gets the ready-made Office & Leadership job: that is the title, not a guess from the work."
  - "Step three (Giving as its own switch) replaces the money notes here: a treasurer will no longer need an Admin login, and a counter can be given the count sheet."
decisions:
  - "ONE engine (church_structure.make) fed two ways: Chief's five questions, or the planning course's saved Leaders, Ministries and Stewardship pages (from_plan, no model). Either way a proposal: the engine makes no login, invitation, job or sheet change."
  - "Kept as ONE draft a church in its own server-only table, church_structure_drafts (Kevin's decision the same day, in place of a settings key: every login that can read the church's row reads its settings, and a draft names people and the logins proposed for them). Nothing about a draft is ever in businesses.settings. The code runs before the migration: GET answers ready false with no draft, the standing check works, and the writes and Chief's draft answer 503 Team setup is being switched on. What is kept is cleaned again on every read."
  - "Exported with the church and skipped on import, as church_jobs is: it ties people to logins by sign-in user id and to members by contact id."
  - "Four shapes: Pastor and helpers, Pastor and a board, Elders with the pastor, Pastor and a staff team. Each starts from the ready-made jobs and proposes a church job where none fits (Board member, Elder, Deacon, Trustee, Executive Pastor), in the tradition's words where church_roles has them (Ruling Elder, Vestry member, Steward; Church Clerk, Financial Secretary as what a ready-made job is also called)."
  - "LEAST ACCESS when no title is given (Kevin's decision the same day): a person with no title is never handed a ready-made job that opens more than they described. They get a job the church would make, named in two or three plain words from the work (Guest follow-up and prayer; Kids & youth helper when no duty is matched), carrying only that work's areas and duties. A ready-made job only when their areas and duties are exactly that job's, or their title is the job's. Chief is told to always ask each person's title, or to name the job itself. From the plan, a job is called by what they lead (Welcome Team leader)."
  - "A ready-made job nobody holds is no longer a gap; a job the draft proposes that nobody holds is."
  - "Money, honestly, until step three: whoever keeps the books (named so, or titled Treasurer, Financial Secretary or Bookkeeper) is drafted as an Admin with two notes (an Admin sees the whole church and giving becomes its own switch soon; only the owner makes one). Whoever only counts or deposits gets no money access, a note, and no_login true. Giving & money and the money duties are stripped from anyone who is not an Admin, with a note, whatever Chief passed. Leading a finance team in the plan is not an Admin login."
  - "Someone with nothing to switch on is drafted as a Viewer (the least a login can be), never the default Manager (Kevin agreed the same day). A job with no areas is nothing on too."
  - "Matching is by email, then full name, then a first name only among logins, and only when exactly one fits; two is a note, never a pick. A member's email is taken from their record, and said."
  - "State and the gaps are worked out on every read from the church as it is. Every gap carries a tone: warn for nobody on giving and for one person counting and depositing, note for the rest."
  - "A CHURCH JOB BRINGS ONLY THE DUTIES GIVEN ON THE SHEET (Kevin's decision the same day, on what this work found): church_duties._seat_lane no longer gives a login on a church job the starting job its areas happen to spell, and such a login holds no duty by its areas either: only the duties named for it (church_duties.own_job_seat; standing, the duties page, holds(), church_over.held and the sheet's own reckoning all ask it). A login with NO job whose picked areas spell a starting job keeps that job's duties, and one whose areas spell none keeps its areas' duties, as before."
  - "So that the sheet never quietly takes duties away: a save that leaves a Manager on a church job gives them, by name, every duty they did and weren't asked to drop (church_sheet.change), with everyone who does it now. A job alone is still a label: nothing is given, nothing is taken, no password."
  - "Chief's draft verb is a READ in the registry (it reads the proposal back mid-turn) that also keeps the draft, said in its description; its handler holds it on a turn that read someone else's words. Both verbs are placed for every login and kept by the handler to the owner, an Admin and whoever sets up jobs and sheets (not chief_areas.OWNERS)."
  - "The planning coach may offer once, only after the Leaders part is written, and is told not to when a draft is already waiting. It is handed who already does what (the logins and the draft) for the owner or an Admin only. Writing or finishing the plan still changes nothing by itself."
  - "A board the church named by its own bodies is those bodies: no generic Board member beside Deacons. A Presbyterian board is its Session, so it is the elders' job."
related: [2026-11-17-church-person-sheet.md, 2026-11-18-sheet-login-level.md]
---

# The standard start

## What it is

A new church does not know the five lanes this system grew up with. The
standard start lets its pastor say, in their own words, who leads, who
handles the offering and who helps, and get back a proposal: the church's
shape, the jobs it would use, each person with the login they would get, and
what is still missing. The pastor reviews each person on Logins & areas and
saves there, behind the password. The engine grants nothing.

## The contract

```
POST   /church/structure/draft   { business_id, answers?, from_plan? }  -> { ok, draft }
GET    /church/structure?business_id=B   -> { ok, draft|null, status, can_draft, ready, plan: { leaders_written, can_use } }
DELETE /church/structure?business_id=B   -> { ok }
POST   /church/structure/person  { business_id, ref, email }  -> { ok, draft }
```

Who: the owner, an active Admin, or a holder of "Sets up jobs and people's
sheets" (`church_job_defs.editor`). `from_plan` is the owner's and the
Admins' (the course is theirs). Any other login's GET answers
`can_draft: false`, no draft, an empty status. Everything is behind
`church_areas._gate` (CHURCH_AREAS), a UUID check, `assert_access` and the
church check, as the sheet's routes are. None of these doors asks for the
password: a draft grants nothing. The invite and the sheet save still do.

`ready` (boolean, on GET): whether the drafts' table could be read. `false`
before the migration is applied (or on a failed read): `draft` is null,
`can_draft` stays true, the status still answers, and `POST /draft`,
`POST /person`, `DELETE` and Chief's draft answer 503 "Team setup is being
switched on. Try again shortly."

`POST /church/structure/person`: an email typed or corrected on review is
put on that ONE drafted person, right before the app invites them, so the
waiting invitation and the login that follows are tied to them. 400 for
something that isn't an email, the owner's own email, or one another person
in the draft already has; 404 with no draft or no such ref.

Every gap carries `tone`: `warn` for `no_giving` and `counts_and_deposits`,
`note` for the rest. The keys: `pastor_only`, `no_giving`,
`counts_and_deposits`, `sees_everything`, `nothing_on`, `no_guests`,
`job_unheld` (`church_structure.GAP_KEYS`).

Optional fields beyond the first contract, all additive: `draft.notes`,
`draft.answers`, `jobs[].also_called`, `people[].does`, `.title`,
`.no_login`; with `from_plan: true`, `answers` may be sent too and is laid
over the plan's.

## A person's state, pinned through the real job, invite row and sheet save

- Accepted with a ready-made job, held as it is: `done` straight away (the
  job's duties follow the job).
- Accepted with one of the church's own jobs: `done` straight away only when
  the draft gives them no duties (a church job brings none by itself);
  `login` while a drafted duty or area is still to be saved on their sheet.
- Made an Admin: `login` until the Treasurer job is on their sheet too. The
  sheet takes no separate duty for an Admin (an Admin does every duty), so
  the money duties come with the job: `done` is the level AND the job.

## Chief

- `draft_church_structure` (mid-turn tool, and a tag for the planning coach)
  and `church_structure_status` (mid-turn tool), in
  `chief_church_structure.py`.
- `navigate` passes `setup: 1` through for `operate` / `areas` only:
  `{ tab: 'operate', sub: 'areas', setup: 1 }`.
- Instructions: `SETTING UP THE TEAM` and `THE DRAFT CHANGES NOTHING` in the
  universal manual's CHURCH SHEETS AND JOBS section; one line in THE OFFICE
  when a church has no office login; the coach's `THE OFFICE TEAM` block.

## The migration

`supabase/APPLY-2026-11-18-church-structure-drafts.sql`: one new server-only
table, `church_structure_drafts` (RLS on, no policies, browser roles
revoked). One transaction, safe twice, nothing else touched. The code does
not wait for it.

## Tests

`__tests__/test_church_structure.py` (58). Changed: `test_tool_loop.py`.
