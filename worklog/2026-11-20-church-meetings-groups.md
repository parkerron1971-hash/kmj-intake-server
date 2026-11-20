---
title: Meetings & minutes, groups and answers (step 3, S3-2, server)
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'S3-2 of step 3 ("Meetings and one calendar") of the church leaders schedule: groups and answers, server only, exactly as docs/CHURCH_SCHEDULE.md section 10 assigns it. The pastor approved the mock and its five calls on 2026-11-20.'
status: in progress
prs: [kmj-intake-server#2020]
migrations: [supabase/APPLY-2026-11-21-church-meetings.sql (from #2001; NOT applied, nothing new here)]
left_undone:
  - "The migration is still not applied: until it is, every /church/meetings/* route answers 404 and the page stays Board & minutes; once it is, every board reader reads kind=eq.board whatever CHURCH_MEETINGS says."
  - "S3-3: series made ahead, editing one or all, skipping and ending, the room booked and moved, closing a group (calling off its meetings), the date check, the church calendar's route, the hourly sweep that keeps every list group in step, and the rest of 'What the old code must learn' (delete_meeting's booking, the next meeting in church_my_week, briefings and Chief)."
  - "S3-4 (the office frontend), S3-5 (the phone: Coming up and the answer form over church_meetings.person_view / person_answer), S3-6 (reminders, the calendar link, clearing notes at 90 days)."
  - "The S3-2 item in 2026-11-20-church-meetings.md's left_undone is this PR."
decisions:
  - "Every reader that means a board reads kind=eq.board whenever the tables are there, whatever the switch says; before the file every read names no new column (helpers in church_meetings)."
  - "A list seat carries the person's office login (Church.person_login, as the design says) and follows it; a leader on a Member-seat login answers in the member app."
  - "Set a meeting checks every field before a group is made; repeat and space_id are refused in plain words until S3-3; check-ins are boards with kind 'meeting' (keepers)."
  - "Renaming or reopening a list group onto a taken name is a 409 in plain words, here rather than in S3-3."
  - "A meeting group's minutes go to its seats to read and only the keepers approve them; no quorum line unless a count is set."
  - "Nothing carries into a meeting called off; what an earlier one called off still holds open carries on; ending a meeting carries into the next one not called off."
  - "The note's readers include whoever gave the answer; an old-time answer is listed as not answered, without its note. I can't reads as excused at the end of any meeting, boards' too."
  - "docs/CHURCH_SCHEDULE.md 10.12 lists all fourteen."
related: [2026-11-20-church-meetings.md, 2026-11-18-church-schedule.md, 2026-10-27-church-board.md]
---
**Step 3, S3-2: groups and answers.** `church_meetings.py` adds the switch (`CHURCH_MEETINGS`, owner
by default, only where Board & minutes is open), `ready()`, a meeting for every leader or for the
office found or made by name (insert, a 409 read as "made just now"), the list's seats kept in step
with the leaders list (one row a request, a 409 read as "already seated", leaving the list lets
the seat go), Set a meeting for one meeting at a time (`POST /church/meetings`), and "I'll be
there" / "I can't" with a private note of 200 at most (`GET` and `PUT
/church/meetings/{id}/answers`; the member app's side as functions for S3-5). Every reader that
means a board now reads `kind=eq.board` (the board's yes on money, the leaders map, the Board tab,
the board's decisions log and the housing allowance's vote), `church_board.py` learned list seats
(they read and answer, never write; add and edit refused there), meeting groups (no quorum line,
minutes to read, the keepers approve), meetings called off (never the next, no step, no carry, no
approving in one) and "I can't" as excused at the end, and the page is called Meetings & minutes
where step 3 is open. The lint `test_board_readers_name_kind.py` pins every read of the board's
three tables; `test_church_board_meeting_groups.py` is church_board.py's checklist;
`test_church_meetings.py` holds the rest. `church_schedule_fake.build(meetings=True)` is the
database with the file, refusing an `on_conflict` on a partial index as Postgres does.
