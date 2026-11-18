---
title: The standard start, a church's structure draft from five questions or from its planning course
date: 2026-11-18
agent: Claude Code (Claude Fable 5.2)
asked: 'Kevin, 2026-11-18: "now with these upgrades, will the system know what to do with other churches? I want to make sure that other churches would have the right type of setup when it comes to setting up there structure and that is will be easy and chief would know what to do without there being any issues", then "standard start first, then giving also consider adding the setup with the church planning strategy. this area would be a huge help in the process because it would make it easy for churches to communicate that and get what is needed if they choose to go that route."'
status: in progress
prs: []
migrations: [supabase/APPLY-2026-11-18-church-structure-key.sql]
left_undone:
  - "Not pushed: one local commit on the branch church-standard-start, for the parent session to open as a PR beside the app's half."
  - "The app's half (the review on Logins & areas, the setup flag, applying a draft through the job, invite and sheet writes) is built by a sibling session against the same contract."
  - "NOT RUN LOCALLY: __tests__/settings_server_keys_db.mjs (PGlite needs its side-install here). It gained three checks for the new key and runs in CI."
  - "No model was run: Chief's five questions, the read-back and the coach's one offer are instructions that no eval has exercised."
  - "A draft is readable by anyone who can read the church's settings row (it sits in businesses.settings). It holds names, emails the church already keeps, and proposed logins. If that is too open, the draft moves to its own server-only table."
  - "A person with no job is drafted as a Viewer with nothing on, but the team invite cannot carry areas without a job: invited as they are, they would open the whole church (read-only) until their sheet is saved. The note on the person says to pick a job first. The app should not offer Invite for someone with no job."
  - "A ready-made job picked from what someone does (no title given) opens more than they described; the person's note says so. A narrower start needs the pastor to give a title, which makes a job of the church's own."
  - "FOUND, NOT CHANGED: a login on one of the church's own jobs whose areas are exactly a starting job's areas holds that starting job's duties (church_duties._seat_lane falls back to the lane its areas are). A Minister of Music with only Worship & media holds Sunday & Serving's duties until the sheet moves them."
  - "Step three (Giving as its own switch) replaces the money notes here: a treasurer will no longer need an Admin login, and a counter can be given the count sheet."
decisions:
  - "ONE engine (church_structure.make) fed two ways: Chief's five questions, or the planning course's saved Leaders, Ministries and Stewardship pages (from_plan, no model). Either way a proposal: the engine makes no login, invitation, job or sheet change."
  - "Kept as ONE draft a church at businesses.settings.church_structure, a server key (business_settings.SERVER_KEYS), with a one-function migration that adds the key to the database's guard. No new table. It works before the migration: until then an owner's or Admin's own login could write the key, which opens nothing, and the draft is cleaned again on every read (money never on anything but an Admin, every field against the real lists)."
  - "Four shapes: Pastor and helpers, Pastor and a board, Elders with the pastor, Pastor and a staff team. Each starts from ready-made jobs where one truly fits and proposes a church job where none does (Board member, Elder, Deacon, Trustee, Executive Pastor), in the tradition's words where church_roles has them (Ruling Elder, Vestry member, Steward; Church Clerk, Financial Secretary as what a ready-made job is also called)."
  - "Money, honestly, until step three: whoever keeps the books (named so, or titled Treasurer, Financial Secretary or Bookkeeper) is drafted as an Admin with two notes (an Admin sees the whole church and giving becomes its own switch soon; only the owner makes one). Whoever only counts or deposits gets no money access, a note, and no_login true. Giving & money and the money duties are stripped from anyone who is not an Admin, with a note, whatever Chief passed. Leading a finance team in the plan is not an Admin login."
  - "Someone with nothing to switch on is drafted as a Viewer (the least a login can be), never the default Manager."
  - "Matching is by email, then full name, then a first name only among logins, and only when exactly one fits; two is a note, never a pick. A member's email is taken from their record, and said."
  - "State and the gaps are worked out on every read from the church as it is, so a draft keeps up as people are invited and sheets are saved."
  - "Chief's draft verb is a READ in the registry (it reads the proposal back mid-turn) that also keeps the draft, said in its description; its handler holds it on a turn that read someone else's words. Both verbs are placed for every login and kept by the handler to the owner, an Admin and whoever sets up jobs and sheets (not chief_areas.OWNERS)."
  - "The planning coach may offer once, only after the Leaders part is written, and is told not to when a draft is already waiting. It is handed who already does what (the logins and the draft) for the owner or an Admin only. Writing or finishing the plan still changes nothing by itself."
  - "A board the church named by its own bodies is those bodies: no generic Board member beside Deacons. A Presbyterian board is its Session, so it is the elders' job."
related: [2026-11-17-church-person-sheet.md, 2026-11-18-sheet-login-level.md, 2026-11-17-settings-server-keys.md]
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
GET    /church/structure?business_id=B   -> { ok, draft|null, status, can_draft, plan: { leaders_written, can_use } }
DELETE /church/structure?business_id=B   -> { ok }
POST   /church/structure/person  { business_id, ref, email }  -> { ok, draft }
```

`POST /church/structure/person` (asked for by the app's session the same
day): an email typed or corrected on review is put on that ONE drafted
person, right before the app invites them, so the waiting invitation and the
login that follows are tied to them. The same people who may draft. 400 for
something that isn't an email, the owner's own email, or one another person
in the draft already has; 404 with no draft or no such ref. None of these
doors asks for the password: a draft grants nothing. The invite and the
sheet save still do.

Every gap carries `tone`: `warn` for `no_giving` and `counts_and_deposits`,
`note` for the rest. The keys: `pastor_only`, `no_giving`,
`counts_and_deposits`, `sees_everything`, `nothing_on`, `no_guests`,
`job_unheld` (`church_structure.GAP_KEYS`).

A person's state, pinned through the real job, invite row and sheet save:
- Accepted with one of the church's own jobs: `login` while the draft holds
  more than the job gave (an area or a duty), `done` once the sheet is saved.
- Made an Admin: `login` until the Treasurer job is on their sheet too. The
  sheet takes no separate duty for an Admin (an Admin does every duty), so
  the money duties come with the job: `done` is the level AND the job.

Who: the owner, an active Admin, or a holder of "Sets up jobs and people's
sheets" (`church_job_defs.editor`). `from_plan` is the owner's and the
Admins' (the course is theirs). Any other login's GET answers
`can_draft: false`, no draft, an empty status. Everything is behind
`church_areas._gate` (CHURCH_AREAS), a UUID check, `assert_access` and the
church check, as the sheet's routes are.

Optional fields beyond the contract, all additive:
- `draft.notes: string[]` what was left out of the answers as a whole (a
  person with no name, the owner named as a helper, a counter who is not one
  of the people, what the plan did not say).
- `draft.answers` the cleaned leads, money, bodies, staff and guests.
- `draft.jobs[].also_called` the tradition's word for a ready-made job.
- `draft.people[].does`, `.title` what was said; `.no_login: bool` true for
  someone who only counts or deposits (nothing to invite them to).
- With `from_plan: true`, `answers` may be sent too and is laid over the
  plan's (leads, money, staff, guests replace; bodies and people add).

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

`supabase/APPLY-2026-11-18-church-structure-key.sql` replaces
`business_settings_server_keys()` with the same 43 keys plus
`church_structure`. Apply after
`APPLY-2026-11-17-settings-server-keys.sql`. The code does not wait for it.

## Tests

`__tests__/test_church_structure.py` (51). Changed: `test_tool_loop.py`,
`test_settings_server_keys.py`, `settings_server_keys_db.mjs`.
