---
title: The leaders schedule, step 3 — meetings and one calendar (the tables)
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'The pastor approved the mock and its five calls on 2026-11-20, each as recommended: one home for every meeting (Board & minutes becomes Meetings & minutes); a meeting for every leader follows the leaders list, and so does one for the office; "I can''t" needs no yes, with a short note only whoever set the meeting, the owner and the office overseer read; a reminder the day before, in the app, never in quiet hours, email only without the app, no texts; a private link for a phone''s calendar that can be made again, the old one stopping. Also: setting a meeting books the room when it is free. S3-1 is the spec and the database change only.'
status: in progress
prs: [kmj-intake-server#2001]
migrations: [supabase/APPLY-2026-11-21-church-meetings.sql (not applied)]
left_undone:
  - "The migration is NOT APPLIED. The owner applies it by hand in the SQL editor; its Check block says what to read back (seven tables, the four new and the three board tables, with RLS on, 0 policies and no browser or anon read or write; 11 new columns; 11 constraints validated; 7 unique indexes, three of them partial; 8 triggers enabled; 4 functions no browser runs; 0 meeting groups, 0 list seats, 0 meetings with any of the new columns). It needs only Board & minutes' and Rooms & spaces' files, both applied in October."
  - "No Python reads or writes any of it. S3-2 (groups and answers) must, in the same PR that first writes a kind = 'meeting' row, make every reader that means a board read kind: church_money_levels._open_boards, church_map._THINGS['board'], member_portal_board.boards_of, housing_allowance._check_links, the decisions log, send_minutes, the quorum lines, carry_forward, church_board._access/_boards/_board/may_write (a list seat reads, never writes) and add_member/edit_member (refused on a group for the list), with a lint over every board, seat and meeting read (church_board.py included) and a checklist test for church_board.py; and teach the old code about called-off and series meetings (docs/CHURCH_SCHEDULE.md 10.2, 'What the old code must learn'). Otherwise a huddle's people would give the board's yes on a check request."
  - "Open questions for the pastor (docs/CHURCH_SCHEDULE.md 10.11): does every leader include the office staff who lead nothing (built yes); does an Admin read an I can't note (built yes, Admins being the meetings' keepers today); do the people at a meeting see by name who else can't come in the member app (built no); does the calendar link carry only meetings (built yes)."
  - "docs/CHURCH_SCHEDULE.md section 10 sits after #1995's section 9 at the end of the file: whichever of the two merges second takes both, 9 before 10."
decisions:
  - "Decided while writing S3-1 (docs/CHURCH_SCHEDULE.md 10.10 lists every one, none the pastor's): a group that meets is a church_boards row, with kind (board or meeting) beside audience (members, leaders, office); seats for the list are member rows the server keeps in step (from_list), so attendance, quorum, motions, follow-ups, the minutes email and the Board tab work unchanged; a group for the list is always a meeting, keeps its audience and is the one open group of its name, enforced in the database; leaders is both of the list's groups and office its office group plus its leaders with an office login; a series is its own table with the commitments' rule column for column, made 91 days ahead, one meeting a day, a skipped one kept as a row, a new rule splitting the series; an answer records the start it was given for; yes or cant, no maybe; the note 200 characters, cant only, cleared at 90 days; reminders one ledger of two kinds claimed by insert, never a text; one working calendar link a person, only its hash kept, a stopped link stays stopped; the room booked or requested by Rooms & spaces' own rules, a taken room never blocking the meeting; same-church checks are triggers that check only what a write names; the board tables' constraints validated as they go in; the Rollback closes meeting groups and takes out empty called-off meetings first."
  - "From the review of #2001 (docs/CHURCH_SCHEDULE.md 10.10, items 20 to 26): the unique index PostgREST names is plain (one meeting a day of a series, and one a booking), and the partial ones (one list seat a person, one open list group a name, one working link a person) are written by insert and a 409, never on_conflict (42P10); a list seat stays its person's and a series stays with its group and church; a meeting's booking is checked again when its room changes, and Rooms & spaces can't move a meeting's booking to another room (a trigger on its table) while S3-3 refuses a change of its times there; the Rollback lets rooms and list seats go and takes out empty series meetings ahead; a moved reminder kind; the Check block reads browser and anon writes as well as reads, on the board tables too, and reads back the unique indexes and triggers; series splits on or before the first day are made in place and a shared day is re-pointed; closing a group calls off its meetings; the calendar key in the address is in the host's logs (long, stoppable); a login with no person has no link."
related: [2026-11-18-church-schedule.md, 2026-10-27-church-board.md]
---
**Step 3, S3-1: the tables for meetings and one calendar.** `supabase/APPLY-2026-11-21-church-meetings.sql`
adds to Board & minutes' tables, which stay the one home of every meeting: `church_boards` gets
`kind` (a board governs; a meeting only meets) and `audience` (its own members, every leader on
the leaders list, or the office); `church_board_members` gets `from_list` (a seat the server keeps
in step with the list); `church_board_meetings` gets a series and its day, a length, a room and its
booking, called off, and changed by itself. Four new server-only tables: `church_meeting_series`
(a meeting that repeats, by the commitments' rule), `church_meeting_answers` (I'll be there or I
can't, keyed by the seat as attendance is, with the start it was given for and a private note with
I can't only), `church_meeting_notices` (the reminders' claim-before-send ledger: the day before,
and Remind the ones who haven't answered) and `church_calendar_links` (a person's private calendar
link: only a hash of its key, one working link a person). Every existing board, seat, meeting,
item, attendance mark and decision reads and writes as it did; nothing writes a meeting group
before S3-2. One transaction, safe twice, additive, ends with `NOTIFY pgrst`; Check and Rollback
blocks at the end. PGlite check `__tests__/church_meetings_db.mjs` (332), in CI's database
job: twice is a no-op with rows in use; the deployed code's reads and writes still work; every
constraint and trigger refused by a bad row and accepted by a good one; another church's group,
room, booking, series, person or seat refused; every delete takes what it should, a church both
ways round; server-only under Supabase's default grants; the Check block answers as it says and
the Rollback block puts the catalog back. Each rule was broken once in a scratch copy to see the
check go red (75). The four tables are in `EXPORT_EXCLUDED`; `docs/MIGRATIONS.md` has
the row (NOT APPLIED); `docs/CHURCH_SCHEDULE.md` section 10 is the design and the PR split (S3-2
groups and answers, S3-3 series, rooms and the date check, S3-4 the office, S3-5 the phone, S3-6
reminders and the link).

**The review of #2001.** One meeting a day of a series is now a plain unique index, so the sweep
can make meetings ahead with PostgREST's `on_conflict=series_id,series_day`; the partial ones are
written one row at a time with a 409 read as "already there". New rules in the database: a list
seat stays its person's, a series stays with its group, a meeting's booking is checked again when
its room changes, and a booking a meeting names keeps its room in Rooms & spaces (one trigger on
that table). A `moved` reminder kind. The Rollback lets rooms and list seats go and takes out
empty series meetings ahead before it drops anything. The Check block grew to seven queries
(writes too, the board tables too, the unique indexes, the triggers). Section 10 now names every
old reader and function S3-2 and S3-3 must change, the series split on or before the first day,
closing a group, the calendar key in the host's logs, and that a login with no person has no
link. The check (388) runs "twice" again with every new kind of row in place; each rule
was broken once and it went red (103, the review's 30 new ones among them).
