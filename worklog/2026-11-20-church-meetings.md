---
title: The leaders schedule, step 3 — meetings and one calendar (the tables)
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'The pastor approved the mock and its five calls on 2026-11-20, each as recommended: one home for every meeting (Board & minutes becomes Meetings & minutes); a meeting for every leader follows the leaders list, and so does one for the office; "I can''t" needs no yes, with a short note only whoever set the meeting, the owner and the office overseer read; a reminder the day before, in the app, never in quiet hours, email only without the app, no texts; a private link for a phone''s calendar that can be made again, the old one stopping. Also: setting a meeting books the room when it is free. S3-1 is the spec and the database change only.'
status: in progress
prs: [kmj-intake-server#2001]
migrations: [supabase/APPLY-2026-11-21-church-meetings.sql (not applied)]
left_undone:
  - "The migration is NOT APPLIED. The owner applies it by hand in the SQL editor; its Check block says what to read back (four tables with RLS on, 0 policies and no browser or anon read; 11 new columns; 11 constraints validated; 3 functions no browser runs; 0 meeting groups, 0 list seats, 0 meetings with any of the new columns). It needs only Board & minutes' and Rooms & spaces' files, both applied in October."
  - "No Python reads or writes any of it. S3-2 (groups and answers) must, in the same PR that first writes a kind = 'meeting' row, make church_money_levels._open_boards, church_map._THINGS['board'], member_portal_board.boards_of and housing_allowance._check_links read kind=eq.board, with a lint that pins every board reader (docs/CHURCH_SCHEDULE.md 10.2): otherwise a huddle's people would give the board's yes on a check request."
  - "Open questions for the pastor (docs/CHURCH_SCHEDULE.md 10.11): does every leader include the office staff who lead nothing (built yes); does an Admin read an I can't note (built yes, Admins being the meetings' keepers today); do the people at a meeting see by name who else can't come in the member app (built no); does the calendar link carry only meetings (built yes)."
  - "docs/CHURCH_SCHEDULE.md section 10 sits after #1995's section 9 at the end of the file: whichever of the two merges second takes both, 9 before 10."
decisions:
  - "Decided while writing S3-1 (docs/CHURCH_SCHEDULE.md 10.10 lists every one, none the pastor's): a group that meets is a church_boards row, with kind (board or meeting) beside audience (members, leaders, office); seats for the list are member rows the server keeps in step (from_list), so attendance, quorum, motions, follow-ups, the minutes email and the Board tab work unchanged; a group for the list is always a meeting, keeps its audience and is the one open group of its name, enforced in the database; leaders is both of the list's groups and office its office group plus its leaders with an office login; a series is its own table with the commitments' rule column for column, made 91 days ahead, one meeting a day, a skipped one kept as a row, a new rule splitting the series; an answer records the start it was given for; yes or cant, no maybe; the note 200 characters, cant only, cleared at 90 days; reminders one ledger of two kinds claimed by insert, never a text; one working calendar link a person, only its hash kept, a stopped link stays stopped; the room booked or requested by Rooms & spaces' own rules, a taken room never blocking the meeting; same-church checks are triggers that check only what a write names; the board tables' constraints validated as they go in; the Rollback closes meeting groups and takes out empty called-off meetings first."
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
