# Church job descriptions: Chief knows everyone's job

Kevin, 2026-11-12: "I need to make sure chief is able to learn job descriptions
for everyone. this important because when a job is created and the leader is
unaware, Chief should know Jobs of each person. can we make sure chief knows."

Then: "give more depth to description, define how it looks on Sundays as well."

## The point, in one example

Someone tells Jessica the fire extinguishers need inspecting before December.
She doesn't know whose that is, and no duty in the catalog covers it. She asks
Chief. Chief looks at everyone's job; say one admin's written description says
"the building, keys and safety". Chief answers: "That's hers: her job covers
the building and safety. Want me to give it to her, due Nov 30?" Jessica says
yes; it goes on that admin's list as an assignment. (Illustrative: no one's
description is written yet. That is the point of the build.)

## What Chief knew before (main c1092a25)

- Office duties, who does each, by lane: `list_duties` (church_duties.CATALOG, 47).
- The leaders map: `list_map` (departments, leaders, overseers, answers_to).
- Role definitions: church_roles (generic per role: "{title} leads a ministry…").
- An office login's OWN work: `my_work` (church_map_asks.work(); self only).
- Assignments: people_under / assignments_of / one_on_one (chief_church_assignments).

## What this build adds

1. A person's job **in the church's own words** (a written job description),
   with room for depth: up to 8,000 characters, line breaks kept as written, so
   it can carry sections such as "What she owns", "Her week" and "On Sunday"
   with a timeline.
2. **One read of everyone's jobs** so "whose job is this?" has an answer.
3. **Another person's whole job** (my_work is self only).
4. A way for Chief to **learn** descriptions: said in chat, pasted, or read from
   an uploaded document, and a starting draft built from what the system
   already holds, in sections, so nobody starts from a blank page.

## Data — supabase/APPLY-2026-11-12-church-job-descriptions.sql

Server-only (RLS on, no policies, browser roles revoked), like church_duty_days.
NOT APPLIED until Kevin applies it by hand (docs/MIGRATIONS.md).

`church_job_descriptions`
- id uuid pk default gen_random_uuid()
- business_id uuid not null references businesses(id) on delete cascade
- contact_id uuid null (the person; references contacts(id) on delete cascade;
  a trigger holds it to the description's own church)
- user_id uuid null (a login with no person behind it; kept beside contact_id
  when the person is a login). No foreign key: a row of a login that left
  stays, and no reader shows it once the seat is gone
- title text (1 to 80, or null), title_by uuid (who wrote the title: a save
  that leaves the title out keeps it, and it stays its writer's words),
  description text not null (1 to 8000 after trimming; line breaks kept)
- source text in ('said','pasted','document','drafted'), default 'said'
- written_by uuid, written_at timestamptz default now() (who first wrote one
  for this person), updated_by uuid, updated_at timestamptz default now() (who
  wrote the words saved now); the user columns reference auth.users on delete
  set null
- version integer not null default 1: one more with every write. Every write
  and undo lands only on the version it read (compare-and-set); a miss says
  "changed just now, try again" and changes nothing
- check (contact_id is not null or user_id is not null)
- unique (business_id, contact_id) where contact_id is not null;
  unique (business_id, user_id) where contact_id is null
- The CHECKs and the foreign keys past the church's are added by name, once,
  NOT VALID (the #1801 habit; a new table has nothing old to check).

`church_job_description_changes` (the log, and undo)
- id, business_id, contact_id, user_id, before jsonb null (null = there was
  none), after jsonb null (null = cleared), by uuid, at timestamptz default
  now(), undone_at timestamptz null

Export (account_lifecycle): the descriptions go with the church's export,
before the people they cite, and an import skips them (they cite people by
id; a restored church saves them again). The change log is excluded: its
writers are sign-in user ids and its undo means nothing in another business.

A login's person is church_over.Church.login_person: the seat's tied record,
else the one person its sign-in email names (business_users_router.
seat_person's rule, read once for the whole church instead of once a login;
the owner's person by their sign-in email, which seat_person doesn't give). A
login without one is keyed by user_id. If a login later gets a person, the read
looks up both (the person's row first, then the login's), and the next write
moves the login's row to the person.

## Who

- **Write** (set, clear, undo): the owner, or someone over that person
  (church_over.is_over), the same people who may hand them work. An Admin is
  over every office login and every leader church_over lets an office seat be
  over. By Kevin's rule an office seat is never over a pastor or an elder, so
  an admin can't write a pastor's; the owner or the map's ministry chain can.
  Nobody writes their own but the owner.
- **Read one person's job**: the person, anyone over them, and any office seat
  (Manager and up), as the duties page already shows every duty's holder to a
  Manager. Office seats need it to route work.
- **Read everyone's** (the roster, whose job): the office seats, Manager and up.
  A Member seat reads only its own job and those of anyone it's over; a Viewer
  reads nothing (the routes need a member seat; Chief refuses a viewer).
- **Pay stays out**, decided a sentence at a time. A sentence with a money
  amount is pay when it has a word about a person's pay (salary, wage,
  stipend, honorarium, compensation or comp, earns, paid or pay, an
  allowance) or a pay period (hourly, weekly, monthly, each Sunday, per
  annum, a year, every two weeks, $52k/yr, $25/h), unless it names what the
  money is spent on or for (rent, a bill, an invoice, tuition, support,
  supplies, a hall or room, a fee, a budget, an offering, a deposit, an order,
  a subscription, an expense, money raised or given): then it's the church's
  spending. Salary, wage(s), stipend and pay rate refuse on their own;
  "minimum wage" never does. When it's unclear it's allowed: the message says
  "Pay stays out of job descriptions; office seats can read them.", and a
  church can reword. Fine: "Office Admin/HR", "walks the lot hourly",
  "workers' compensation claims", "housing benefits", "pays the bills",
  "Pastor Payne", "payroll", "the benefit dinner", "manages the $5k youth
  budget", "pay the $1,200 rent", "the $200 monthly supply allowance", "the
  hall at $50 an hour". Allowed on purpose: "a love offering" and "PTO" with
  no amount, since a church's own duties name them ("collects the love
  offering", "approves PTO requests").
- Their words are data: the description and title are written by a person, so
  a read that brings someone else's written words into the turn raises the
  turn's taint (chief_church_assignments._taint pattern), and later writes in
  that turn are held until the person says it again. Someone else's means: the
  description's last writer isn't the asker, or the title's writer (title_by)
  isn't, or the text was pasted in or taken from a document (those words came
  from someone else, whoever saved them), or the writer is no longer known. A
  read of only system-built lines (duties, map, role definitions, a draft)
  doesn't, and neither does a read of the asker's own words.

## The pieces (module church_job_descriptions.py)

- `job(...)`: one person's whole job: name; title (the written one, else their
  role title, else their seat's lane); the whole written description and who
  wrote it when; the duties they do of their own, each with the day it falls
  on (as My week places it, their picked day included); for an office login
  church_map_asks.work() is the reader; departments they lead / oversee / help;
  roles with the role definition filled in; who they answer to; who's over them
  (church_over.above); `written: bool`. Only this read (and a write's answer)
  carries the whole description.
- Duties of their own: the owner and an Admin, what was moved to them by name
  and their stored lane's starter duties nobody moved; a Manager, what it
  holds; the Executive Pastor's login, its own two (the monthly report, over
  the lanes) and "covers any lane's work", never the whole office as its own.
  Money duties count (an Admin's books are part of their job; no amount ever
  appears).
- `roster(...)`: everyone: the owner, every active office login, every person
  with an active or invited leader role or who leads/oversees a department,
  plus anyone with a written description. Cap 80. One compact line each: the
  title and about the first paragraph of the description (300 characters at
  most), never the whole.
- `whose(...)`: rank everyone against the work's words (the first 500
  characters of them, which is also all Chief's answer echoes; lower-case,
  accents folded so "oracion" finds "oración", any script's letters, stop
  words out in English and the commonest Spanish ones, light stemming) across the description and title, duty labels + their
  training lines + areas, department names, role titles and definitions. Top 3
  with the words that matched, the lines of the description that carry them,
  who's over each, and whether the asker may hand them the work. A department
  whose name matches is in its leader's and overseer's words, so they rank.
  Nobody matches: the person who oversees the office (oversee_lanes holder);
  else the owner. Also return the roster lines (title plus first paragraph) so
  the model can judge better than the word match.
- `draft(...)`: a starting description built only from what the system holds,
  in plain sections (a heading on its own line, no marks the app would show
  raw), at every church:
  - Summary: the title, who they answer to, who they support (the departments
    they help as the office, through support_duty), the departments they lead
    or oversee, and each role's definition.
  - What they own: each duty and its training line.
  - Their week: duties grouped by the day they fall on, using church_my_week's
    placement, including the person's picked days from church_duty_days
    (weekdays, then each week, once a month, whenever it comes up).
  - On Sunday: their Sunday duties, and a line that the church fills in the
    times (when they arrive, what they do before, during and after each
    service, and when they leave).
  Never saved by itself.
- `set_description(...)`, `undo(...)`: write, log, undo (the last change only;
  it puts back the earlier writer's words with their name, or null for a
  writer whose login is no longer the church's, since a deleted account's id
  would fail its key). A save that leaves the title out keeps the written one,
  and its writer. Clearing is explicit (`clear: true`), never an empty
  description, so a missing field can't wipe someone's. Undo reads only this
  person's changes (by their person, or by their login while it had no
  person), never another person's that a login was once tied to. A put-back
  that failed and couldn't let its claim go is tried again by the next undo.
  Whether a write landed is asked of its own row: a clear whose row is gone
  did happen and is logged (even when the person still shows a login's
  older row, or a save lands a moment later), and an insert or update whose
  answer was lost is found as it was written and logged.
- Routes (church_job_descriptions router, mounted before public_site_router):
  - GET  /church/jobs?business_id=                       roster
  - GET  /church/jobs/person?business_id=&contact_id=|user_id=   one job (the whole description)
  - GET  /church/jobs/whose?business_id=&q=              whose job
  - GET  /church/jobs/draft?business_id=&contact_id=|user_id=    the draft
  - PUT  /church/jobs/person {business_id, contact_id|user_id, title, description, source} ({…, clear: true} clears)
  - POST /church/jobs/person/undo {business_id, contact_id|user_id}
  Every route: require_user (sb_clients.authed_request) + a member seat or
  above (business_access) + the checks above; a failed read is a 503, never a
  yes. Before the file is applied, every route is a 503 saying it isn't ready;
  the switch closed, a 404. (The screen comes later, after Kevin's yes on the
  mock.)

## Chief (module chief_church_jobs.py, the chief_church_assignments pattern)

- `whose_job` {work}: mid-turn read. "Whose job is …?", and BEFORE handing out
  work when the leader didn't say who, and whenever new work comes up with
  nobody named (a task, a board follow-up, something a member reported).
- `job_of` {who, from_line?}: mid-turn read. "What does Tiara do?", "what's
  Minister Ray's job?", and "what is my job?" for anyone (my_work stays for the
  office check-it flow). The description comes last. It pages by line and,
  inside a line too long for the room left (a one-paragraph description), by
  character, cut at a word: every cut says "(continues: ask job_of for X with
  from_line N [and from_char C] ...)", from_line/from_char read only the
  description from there, and paging forward reaches the end with nothing
  skipped.
- Size: the three reads are on chief_tool_loop's 12,000-character list, and
  each is built to fit RESULT_BUDGET (10,000 characters of the result's JSON),
  so Chief never gets the tool loop's "Incomplete sample" cut. whose_job drops
  a line's excerpt past the budget, then says how many more ("continues"); a
  draft comes once (never twice) and, if it can't fit, leaves out what each
  duty covers and says so.
- Naming: "me" only when they said it. A whole name, or one name word only one
  person has (a first name, never the start of one: "Ann" is never "Annette"),
  with whole words of what they do ("Minister Angela", "Elder Marcus"). Among
  the people the asker may name: everyone's job for an office seat, whoever
  they're over (church_over.under: a group's leader too), themselves by
  their own name, and for the owner any of the church's people: for the owner
  a name is one person's only when it is across all of them (Ann Cole leads a
  team and Ann Lee has no role yet: "Ann" asks which). None, or several,
  change nothing and say who it could be. A write with no name and no key that
  parses asks "Who is this for?"; the same for undo.
- `draft_job_description` {who}: mid-turn read. Chief reads it back, the leader
  changes what's wrong, then set_job_description.
- `set_job_description` {who, description, title?, source, clear?}: [ACTION]
  tag write. Reads back what it saved (its first 1,500 characters, line breaks
  kept), who wrote it, and that undo puts it back. A title kept from another
  writer is read back fenced, named as theirs, and raises the turn's taint.
  Pasted or document text isn't read back (its size and source are): the
  leader approved those words before the save, and reading them back would
  hold every save after it in the turn.
- `undo_job_description` {who}: [ACTION] tag write; its inverse is registered
  in action_inverse so "undo that" works, carrying the change it undoes (a
  later change since means nothing is put back).
- Learning from a document: no new verb. Chief reads the uploaded file with the
  document read it already has, then proposes one set_job_description per
  person, quoting what it will save. The document taints the turn, so each
  save waits for the leader's yes, which is the behavior we want.
- one_on_one and people_under: add the person's job title and whether a job
  description is written ("No written job description yet: Chief can draft one
  from what they already do"). The title there is the one the system holds
  (role, else seat), never the written one, so these reads, which come before
  give_assignment in the same turn, don't start holding writes. Before the
  file is applied the line is left out, never the read.
- Prompt (chief_prompt church section): call whose_job before saying whose job
  something is or before handing out work with no one named; name the person
  and the reason in their job's words; offer give_assignment if the asker may
  hand them work, or send_handover if the asker is an office seat and the
  person is a pastor/elder; never assign without a yes; one person per
  set_job_description; never put pay in a description. The CHURCH ASSIGNMENTS
  turn block says it in one line too.
- Wiring: action_registry (effects, sensitive, chief_only), chief_areas VERBS
  (ALL,), chief_tool_loop read tools + the private-read allow-list,
  chief_of_staff ACTION_HANDLERS + action phrases, every handler returns
  {result, label}.
- Switch: CHURCH_ASSIGNMENTS (same Thursday flip; owner = Love City only).

## General for every church

Nothing names Love City. The draft and the roster come from each church's own
duties, map, roles and logins. A church with no map still gets office logins
and their duties.

## Tests

FakeSB tests like test_chief_church_assignments (__tests__/
test_chief_church_jobs.py, __tests__/test_church_job_descriptions.py) and a
PGlite run of the file (__tests__/church_job_descriptions_db.mjs), and the
#1807 review's findings as regression tests (__tests__/
test_church_job_descriptions_review.py): whose_job
routes "monthly report" to the Executive Pastor's holder, "weekly text" to its
holder, "fire extinguishers" to a facilities description; an office seat
writing a pastor's description is refused; pay words refused; someone else's
written description taints the turn and holds a later write; undo restores the
previous text and removes a new one; a Member/Viewer reads nothing of anyone
else's; a failed read is a 503; the switch off says not on; the draft's four
sections with picked days and Sunday duties; a long description whole only in
job_of.
