---
title: Help requests (benevolence) — a fund, a limit, a keeper's yes and a record (server)
date: 2026-10-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Church Office Prototypes (https://claude.ai/artifact/2vGqaUZUynRuiFVKuQEZWo), the "Help requests" tab → Kevin, 2026-10-27: "lets go with your list" (help requests first; "make sure that the design is top tier")'
status: shipped, switched off (platform owner only until a Thursday); migration waiting on Kevin
prs: [kmj-intake-server (this PR), solutionist-studio (the page, its own PR)]
migrations: ["supabase/APPLY-2026-10-27-church-help.sql (NOT APPLIED: Kevin applies by hand)"]
left_undone:
  - "Apply supabase/APPLY-2026-10-27-church-help.sql. Until then /church/help/status says enabled false and the other routes answer 503"
  - "Switch-on: CHURCH_HELP=on on Railway on a Thursday (it defaults to owner), with the app's What's New entry"
  - "The member's ask from the app carries no amount (member_asks.py's help form has no 'How much, if you know' field, though the prototype's phone does): the office types it in. Adding submission.amount (dollars) there is all it takes; church_help.from_ask already reads it"
  - "The books have no fund dimension for expenses: help given is an Operating expense with the fund's name as its subcategory. A restricted fund's release (net assets with donor restrictions → without) isn't posted"
  - "Gifts given INTO the benevolence fund aren't shown beside what's left this month; the page works from the monthly budget"
  - "Chief can't read or act on help requests yet (no action handler)"
  - "A keeper who doesn't work People & care (a treasurer) answers the key ask in Areas; they don't see the request's story, only its need and amount in the ask"
decisions:
  - "Lane: Build, under the Build item 'Love City leaves Subsplash (M-1)'"
  - "Who: the owner, admins and logins whose areas include People & care read who and the story (any login while Who sees what is off, as before); a member-level login or above acts, a viewer reads. A Giving & money login sees needs, amounts and dates, never a name or a story, and can't approve. A private request shows who to the owner and admins only; a youth's ask from the app (the youth way, pastors only) is theirs alone"
  - "The limit is per request: the total approved, and help given past what was approved is approving more. Up to the limit any acting login says yes. Above it: is_open(giving_money) from church_keys — a keeper says yes on this page, or the asker asks (church_keys.ask, reason = the need and amount, never who or the story), and a keeper's tap or code opens it for an hour. The owner is bound too"
  - "No keeper for Giving & money (or CHURCH_KEYS off) means the limit alone governs: nobody gives more than it at once; the answer and the page say so. Raising the limit needs the same keeper yes where there are keepers, or it would be the way around them"
  - "The books: each record with money is one business_expenses row (category operating, subcategory the fund's name, vendor the payee, payment_method cash/check, description 'Help given from the <fund>: <need> (<how>)', no name, no story), the same plain row Chief's log_expense and the Expenses screen write, so the GL triggers post it. A closed period refuses the record; taking a record back (owner and admins) deletes its expense"
  - "An app ask (ministry_care_requests, submission.kind 'help', member_asks.py's contract) is listed as a new request ('care-<id>') and becomes its own row the first time anyone acts on it (care_request_id unique, so two presses make one). Reading writes nothing. Its Prayer & care row follows: reviewed once approved, closed once helped or declined"
  - "What's left this month = the monthly budget − given this month − promised (approved, not given), in the church's clock. Families helped this year = distinct people (or requests with no person) with help given this year"
related: [2026-10-27-church-keys.md, 2026-10-23-church-areas-map.md, 2026-10-27-church-spaces.md]
---
- `church_help.py` (new): the switch (`CHURCH_HELP` off | owner | on, owner by
  default, like `church_keys.py`), who sees what, the fund and its totals,
  requests and the app's asks, the limit and the keepers, help given and the
  books, and ten routes under `/church/help` (the module docstring lists them).
  `/church/help/status` answers `{enabled, view, approve, settings}` and is
  quietly false for a closed switch, a business that isn't a church, a login
  outside People & care and Giving, or tables not made yet.
- `supabase/APPLY-2026-10-27-church-help.sql` (new, NOT applied):
  `church_help_settings`, `church_help_requests`, `church_help_given`, all
  server-only; a trigger keeps a request's person and Prayer & care row its own
  church's. Ledger row in `docs/MIGRATIONS.md`.
- `account_lifecycle.py`: the three tables exported (before Prayer & care and
  contacts); requests and records skipped on import (they cite people, asks and
  expenses by id).
- `kmj_intake_automation.py`: mounts the router after Rooms & spaces.
- `.github/workflows/ci.yml`: adds `church_help_db.mjs`. `.env.example`: `CHURCH_HELP`.

Checks:
- `__tests__/test_church_help.py`: 10 tests (the switch and missing tables,
  what each login may do, confidentiality by area, the limit with no keeper,
  a keeper's yes by ask and by code, a keeper approving here, raising the
  limit, another church unreachable, the books and the fund's totals, closed
  books, taking a record back, declining, the app's asks becoming one row).
  Eight rules broken on purpose (no limit, Giving reading the story, any care
  row as help, another church's id, a youth's ask shown to all, no keeper
  meaning open, a free limit raise, no books): all caught.
- `__tests__/church_help_db.mjs`: 43 checks on PGlite.
- Export/import, the access ratchet, route type hints, seat access, step-up
  routes, keys and spaces pass.
