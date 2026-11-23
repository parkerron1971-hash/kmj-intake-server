---
title: Chief knows who it is talking with, and a church's own job reaches it (step 2 of 5)
date: 2026-11-22
agent: Claude Code (Claude Fable 5.2)
asked: 'Kevin, 2026-11-22: "any person that we add in, it seems like Chief doesn''t get the information about the church, the role, responsibilities"; then "Start on step 2"'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "A treasurer who is NOT an Admin still can't ask Chief about giving: that takes the giving tick (CHURCH_MONEY_TICKS), which is still off and is Kevin's switch (2026-11-20-church-money-ticks-follow-up.md lists what it waits on). Until then their card tells Chief to say the owner opens it, and to offer a note to the owner"
  - "What is theirs THIS WEEK is not on the card: it points at my_work, and the assignments line already rides the tail. A day-by-day line from My week (church_my_week) is not built"
  - "A job shows what it does only when the owner made it and nobody else has ever saved it; otherwise its title shows and the card and the roster point at list_church_jobs. Kevin can widen this to an Admin's words if he wants; it is the same rule THE OFFICE already keeps for job descriptions"
  - "church_jobs keeps who made a job and who saved it last, not who wrote each line. 'The owner's own words' is worked out from those two and the record of changes (church_sheet_changes), which is written best effort: a column for who wrote `does` would make it exact (a migration, not in this PR)"
  - "A Member's or a Viewer's card names nobody else and carries no description; job_of and my_work are not offered to them (the tools refuse them)"
  - "Whether a Member or a Viewer login is really kept to its areas by Chief was not looked into: the review noted chief_areas.scope_for can answer None for them (everything), which is older than this work"
  - "No live Chief eval was run (they bill production): the card's text, who gets it and that it reaches the prompt are tested; that Chief answers 'what's my job' from it is not"
  - "Steps 3 to 5 of the plan (2026-11-22-chief-church-lookups.md): the church fact sheet, the every-room-has-a-lookup test, the per-role question set"
decisions:
  - "The gap, read in code: a job of the church's own is not a lane (church_duties._seat_lane), so THE OFFICE titled its holder 'Admin' or 'Office' and said nothing of the job, and an Admin's turn carried only their name (chief_duties.jobs_line is None for an Admin). Every church but the one the five starting jobs were written from is on its own jobs since 2026-11-21"
  - "THE OFFICE: a login on one of the church's own jobs is titled by that job, and gets what the church says it does when the owner last wrote the job"
  - "WHO YOU ARE TALKING WITH (chief_office.card_for): one block in the turn's tail for every church login that isn't the owner's, an Admin's, a Member's and a Viewer's too: level, job and what it does, the written description's first line, who they answer to (a Manager: whom they are over), where they work, an Admin's own duties, and whether Giving & money is open to them. Kept a minute a replica; a read that fails leaves the card out, never the turn; recorded for the answer check as context:talking_with"
  - "Whose words: a job's title is a name, fenced and in quotes (one instruction-shaped word anywhere in the job and none of its words are shown). What a job does reaches the prompt only when the owner made the job, saved it last, it is still there and the record names nobody else for it: the owner re-saving a job someone else wrote, or removing it, never makes its words the owner's. A written description only in the owner's own words. Names on the card are fenced and an instruction-shaped one is left off"
  - "An office login's card is written from the facts the roster build keeps (chief_office._FACTS), so it reads the office once, with the roster: an ordinary Manager's card read the database 41 times on its own before this, about 3 after. One roster is built at a time a process, so the card waits for the build in flight"
  - "The card is kept per login AND per scope (areas, giving tick), and a job made, changed or removed, or a giving tick given or taken, drops the church's roster and cards at once"
  - "An independent review ran before the PR and found the two things above (whose words, the 41 reads) plus: a job title could pass itself off as a seat in the roster (now in quotes), a contact's instruction-shaped name could reach the tail, duties switched off said 'no job is set', a keeper that couldn't be read was said as open, and a refused money verb still said 'the treasurer handles it'. All fixed here, each with a test"
  - "Chief no longer sends anyone to 'the treasurer' for money (chief_areas.block): the one asking may be the treasurer on a login the owner hasn't opened money to. A login whose job is about money, with money shut, is told the owner opens it"
  - "An Admin's card does not list everyone under them (an Admin is over the whole office by level; THE OFFICE names them). Whoever is over the lanes sees the Managers under them, as the roster names them"
  - "A Manager's, a Member's and a Viewer's duties stay in 'Their jobs here' (chief_duties.jobs_line), not repeated on the card; an Admin's own duties are on the card because an Admin had no such line"
related: [2026-11-22-chief-church-lookups.md, 2026-11-17-chief-office-roster-exec.md, 2026-11-17-church-person-sheet.md, 2026-11-12-church-job-descriptions.md, 2026-11-20-church-money-ticks-follow-up.md]
---
Before building I read both repos' work logs: the office roster (11-17), the
person sheet and the church's own jobs (11-17), the starting jobs shown only
where they are used (11-21, BE #2056), and the giving tick's follow-up (11-20).
No open PR touches `chief_office.py`.

`chief_office.py` gains `own_job`, `card_for`, `build_card`; `church_job_defs.py`
gains `own_with_writer` (a job with who last wrote it); `chief_of_staff.py` adds
the card after the login's block. Tests: `__tests__/test_chief_talking_with.py`,
and the whole-turn test in `test_chief_areas.py` now checks the card reaches the
prompt for a login and is not asked for on the owner's turn.

What the treasurer of 2026-11-22 (an Admin on the church's own job) gets now:
"Dee Walker: an Admin login. Their job here is “Church Treasurer”, a job this
church made. What the church says that job does: “Counts and records every
offering …”. Giving & money: open to them as an Admin …".
