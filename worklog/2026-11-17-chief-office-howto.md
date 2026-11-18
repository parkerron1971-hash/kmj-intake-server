---
title: Chief says where each office person does each thing, answers each part once, and knows an event's volunteer roles
date: 2026-11-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-18 01:30 UTC: "make sure that chief is aware of how to do each thing with each person and help them per the list you gave about what chief can do now. I just asked and chief said yes but then said no to certain parts so check that to make sure."'
status: in review
prs: [kmj-intake-server (this PR), solutionist-studio#1624]
migrations: []
left_undone:
  - "The live prompt was not run against the model (no live evals: they bill production); the roster, the map, the module line, the rule and the turn's answers are tested"
  - "THE OFFICE says where a duty is done, not whether that page is on the holder's own menu: a duty moved to a login whose areas lack its page (and that no DUTY_OF/ASKED_BY row opens) is still listed with the page"
  - "Who serves when schedules Sundays only (an outreach night's place is still Who serves when); the weekday event dates are another branch's (event-volunteer-dates)"
  - "Printable guest cards for People & Care are another branch's (guest-print-cards); the New here seat cards answer here is the button New here has today"
  - "Roster size: ~4,900 characters for Love City with one description (~1,230 tokens at four a token; ~2,850 / ~710 before). Past ROSTER_MAX_CHARS the places go before the labels shorten, and job_of (list_duties too, while it fits) says them"
decisions:
  - "A duty's place is derived, never typed: church_my_week.DOOR (duty → page) joined to church_findway.json (page → door › heading › name). INSIDE (the button its work starts from) and ALSO (a second page) are page keys and button words; a test holds each button to a Help Center answer on that page"
  - "The events duty's door is Services & Events (`@roster`); My week opens the church's own events room by its module id (room_door, read once a build; the calendar when there is none). The events page is the website duty's"
  - "The map export carries each page's `duties` (churchStructure DUTY_OF, ASKED_BY; Services & Events is the events duty's). The menu tags them (`[office; +Rooms / Events and sign-ups / Outreach nights]`), and a lane's turn gets the Help Center answers of the pages its duties open (church_findway.duties_of, read only for a where/how question)"
  - "A page the turn names brings its own answers that share the question's words (turn_block): a long question that names Services & Events holds too many words for any one answer to match, which is why Kevin's got none"
  - "The events room's CUSTOM MODULES line says its entries hold roles and volunteers, set with roles/volunteers (ROSTER_ROLES_NOTE): its schema fields never list them"
  - "ONE ANSWER PER PART lives in ADAPTIVE EXECUTION (universal, a rule section the short brief keeps whole); the church's menu says its places, THE OFFICE's and a HELP CENTER ANSWERS block are confirmed"
related: [2026-11-17-chief-office-roster-exec.md, 2026-11-17-chief-church-menu.md, 2026-11-17-events-volunteer-list.md, 2026-11-17-guest-lane-new-here.md, 2026-11-17-leaders-note-text.md]
---
Chief told Kevin "yes to both", then "no to the first", said it had no
confirmed path to Laquesha's volunteer list, and that the roles might go in
the notes. Three causes: nothing said which page each duty is done on (the
menu knows pages, not duties); no Help Center answer matched a long question;
and the events room's line listed its fields, which never include roles.

- `chief_office.py`: `place(duty)`, shown beside each duty in THE OFFICE
  ("Events and sign-ups (Sunday › Plan and look back › Services & Events →
  Roles; Office › Building › Rooms & spaces → Ask for a room)"), and the rule
  that these places are confirmed.
- `chief_duties.py`: list_duties says "Done in:" for each duty while the list
  fits its read; `chief_church_jobs.py`: job_of says it beside a person's duties.
- `church_findway.py`: `page()`, pages a duty opens (`duties`), named-page
  answers, `asks`/`duties_of`; the menu's how-to.
- `church_my_week.py`: the events door, `room_door`.
- `chief_of_staff.py`: `ROSTER_ROLES_NOTE` on an events room's line; the
  turn's Help Center block gets the login's duties.
- `chief_prompt.py`: ONE ANSWER PER PART.
- `church_findway.json`: exported again from solutionist-studio#1624 (11 doors, 106
  pages, 292 answers; it also carries a Small Church clip answer the
  frontend changed earlier and never exported).
- Tests: `__tests__/test_chief_office_howto.py` (new), `test_chief_office.py`.

Checked before building: the worklogs in `related` in both repos. Before
building more here: a new duty needs a My week door on a page the map has, or
a THROUGH_CHIEF line, or `test_chief_office_howto` fails.
