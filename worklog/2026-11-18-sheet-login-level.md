---
title: A person's sheet changes the login's level, the older routes ask for the password when they give more, and a password is confirmed for one business
date: 2026-11-18
agent: Claude Code (Claude Fable 5.2)
asked: 'Kevin, 2026-11-18, on the follow-ups to one sheet per person: "the giving for delegation one is i am unsure about so explain that one. but everything else, I agree."'
status: in progress
prs: []
migrations: []
left_undone:
  - "Not pushed: two local commits on the branch sheet-login-level, for the parent session to open as a PR."
  - "The app's side: the level picker on the sheet (GET /church/sheet level_options). The app needs no change for the business-bound password: it keeps one token per scope, and a token for another business comes back as ledger_locked, which stepUpFetch and stepUpFetchIfAsked already answer by asking again."
  - "KNOWN, NOT CLOSED: ways a login is still given more with no password. (1) Saying yes to an ask: church_map_asks calls church_duties.move. (2) PUT /church/areas/place: re-placing a role or a team changes Chief's guess for every login placed by guess. (3) Chief's move_duty and undo_duty: Chief has no request to carry a token."
  - "KNOWN LIMIT: a Manager who is over the office's lanes, and is not an Admin or a holder of jobs_and_sheets, is not asked for a password on PUT /church/duties/{duty} or its undo. She cannot confirm one (see decisions), so her moves stay limited to her own team by the route's existing rule, as before."
  - "Danger step-ups are now really the owner's alone. chief_errands (approve, continue, secure entry: Manager and up), stripe_payments_router charge-no-show (Manager and up) and contractors pay (Admin and up) ask for a danger password that only the business's owner can confirm. That was already so for anyone who owned no other business; an Admin or Manager who owned another business could confirm there and act here, and no longer can. Kevin to decide whether any of those should take an access-style rule instead."
  - "The ledger scope is not bound to a business: its pre-check is the read gate every ledger route asks again."
  - "The id guard is a shape (letters, digits, hyphen, underscore, at most 64) plus quoting, not a strict UUID: about 25 test files pass short ids such as b1."
  - "Giving is unchanged, by Kevin's word: who gave and how much stays the owner's and an Admin's."
decisions:
  - "Who sets a level: the owner any level on any login; an Admin or whoever sets up jobs and sheets sets Viewer, Member or Manager on a Manager login or below, never Admin; nobody their own."
  - "A higher level is more, so it asks for the password, by the same by-result reckoning as areas and duties (church_sheet.effect). A lower one asks nothing."
  - "Made an Admin: the stored areas and job stay on the row, unused while Admin and there again if moved back; areas and duties sent in the same save are ignored; the summary says they now see the whole church, giving included."
  - "Moved down from Admin: refused (400) unless the login ends with picked areas, sent in the save or already stored. A job that is an Admin login's (the Treasurer's) comes off them unless the save names another."
  - "The grant never comes back. It is taken away BEFORE the level is written (a save that fails there changes nothing), and any move to Manager clears a jobs_and_sheets row left on the login unless the owner or an Admin gives the grant in that same save. A holder cannot lower another holder (403)."
  - "Nothing is written when any part of a save refuses: every refusal church_duties.move would make (the most logins a duty takes, who can hold it) is asked before the first write, and the level, the areas and the job land in ONE row write (church_areas.set_login), so an Admin moved down is never left with no areas by a save that fails half way."
  - "Duty rows that name a lowered login are left as they are: the duties module answers by level, so the duty shows as needing someone, the same as for a removed login."
  - "Seats: billing counts a seat whatever its level, so a level change touches no limit."
  - "An access or danger step-up is for ONE business: ledger_unlock.mint carries the business the step-up endpoint checked the person against, and every access and danger gate passes the business its action is for. A token for another business, or one naming none, is the standard ledger_locked. Deleting an account takes one confirmed for any business the person owns. This closes a hole older than this work: anyone who owned any business could confirm there and use the token where they were a Manager."
  - "Whoever is over the office's lanes can NOT confirm the access password (reverted the same day it was added: an invite needs only a Manager, so it would have opened every access gate to her)."
  - "POST /church/duties/{duty}/undo asks by the same rule as the move: a put-back that gives a Manager a duty back asks, one that only takes away does not."
related: [2026-11-17-church-person-sheet.md]
---
Step two of one sheet per person. `PUT /church/sheet` takes `level`, and
`GET /church/sheet` lists the four levels with which ones this editor may
set and why not. `PUT /church/areas/login`, `PUT /church/duties/{duty}`
and the duties' undo gave a login more with no password, so the sheet's
question could be walked around there; each now asks when the result is
more and never when it is less. A password confirmed for one business no
longer opens anything at another (`ledger_unlock`: access and danger
tokens name their business). `business_access`, `assert_access`,
`role_of`, the accountant check and the collaborators' routes no longer
put an id into a PostgREST path as it arrived: an id that isn't shaped
like one answers the same 404 as a business that doesn't exist, with
nothing read, and a collaborator is revoked only at its own business.
Before building more here, read `church_sheet.py` (`effect`, `change`),
`ledger_unlock.py` (BOUND_SCOPES) and the tests
`test_access_asks_by_result.py` and `test_step_up_one_business.py`.
