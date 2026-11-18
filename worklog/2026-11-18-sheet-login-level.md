---
title: A person's sheet changes the login's level, and the two older routes ask for the password when they give more
date: 2026-11-18
agent: Claude Code (Claude Fable 5.2)
asked: 'Kevin, 2026-11-18, on the follow-ups to one sheet per person: "the giving for delegation one is i am unsure about so explain that one. but everything else, I agree."'
status: in progress
prs: []
migrations: []
left_undone:
  - "Not pushed: one local commit on the branch sheet-login-level, for the parent session to open as a PR."
  - "The app's side: the level picker on the sheet (GET /church/sheet level_options), and the password prompt on PUT /church/areas/login and PUT /church/duties/{duty} (both now answer 403 ledger_locked, scope access, when the write gives more)."
  - "POST /church/duties/{duty}/undo and Chief's move_duty and undo_duty still give a duty back with no password (Chief has no request to carry one). Kevin to decide whether they should refuse a move that gives more."
  - "The id guard is a shape (letters, digits, hyphen, underscore, at most 64) plus quoting, not a strict UUID: about 25 test files pass short ids such as b1. Strict UUID would mean changing those fixtures."
  - "Giving is unchanged, by Kevin's word: who gave and how much stays the owner's and an Admin's."
decisions:
  - "Who sets a level: the owner any level on any login; an Admin or whoever sets up jobs and sheets sets Viewer, Member or Manager on a Manager login or below, never Admin; nobody their own."
  - "A higher level is more, so it asks for the password, by the same by-result reckoning as areas and duties (church_sheet.effect). A lower one asks nothing."
  - "Made an Admin: the stored areas and job stay on the row, unused while Admin and there again if moved back; areas and duties sent in the same save are ignored; the summary says they now see the whole church, giving included."
  - "Moved down from Admin: refused (400) unless the login ends with picked areas, sent in the save or already stored. A login with none would see the whole church."
  - "A login that stops being a Manager loses the jobs-and-sheets grant in the same save, and it does not come back with the level. A holder cannot lower another holder (403)."
  - "Duty rows that name a lowered login are left as they are: the duties module answers by level, so the duty shows as needing someone, the same as for a removed login."
  - "Seats: billing counts a seat whatever its level, so a level change touches no limit."
  - "Whoever is over the office's lanes can answer the access password (ledger_unlock), because the Duties tab lets her move her team's duties. The token is for the login and the scope, not the route, so it also answers an invite's, which a Manager could already send."
related: [2026-11-17-church-person-sheet.md]
---
Step two of one sheet per person. `PUT /church/sheet` takes `level`, and
`GET /church/sheet` lists the four levels with which ones this editor may
set and why not. `PUT /church/areas/login` and `PUT /church/duties/{duty}`
gave a login more with no password, so the sheet's question could be walked
around there; both now ask when the result is more and never when it is
less. `business_access`, `assert_access`, `role_of` and the accountant
check no longer put an id into a PostgREST path as it arrived: an id that
isn't shaped like one answers the same 404 as a business that doesn't
exist, with nothing read. Before building more here, read `church_sheet.py`
(`effect`, `change`) and `__tests__/test_access_asks_by_result.py`.
