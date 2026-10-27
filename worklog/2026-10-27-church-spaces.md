---
title: Rooms & spaces, with Rentals — a church books its building (server)
date: 2026-10-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Church Menu Gaps (https://claude.ai/artifact/4oXF1Be46RddJxXnKAHodn), "Office, filled in" and the 9:10 AM beat (a family calls for the fellowship hall for a funeral meal on Saturday, and there is no list of rooms and no booking) → Kevin, 2026-10-27: "lets start building this"'
status: shipped, switched off (platform owner only until a Thursday); migration waiting on Kevin
prs: [kmj-intake-server (this PR), solutionist-studio (the pages, its own PR)]
migrations: ["supabase/APPLY-2026-10-27-church-spaces.sql (NOT APPLIED: Kevin applies by hand)"]
left_undone:
  - "Apply supabase/APPLY-2026-10-27-church-spaces.sql. Until then /church/spaces/status says enabled false and the other routes answer 503"
  - "Switch-on: CHURCH_SPACES=on on Railway on a Thursday (it defaults to owner), with the app's What's New entry"
  - "Members booking from their app (a request from /my): not in this version"
  - "An accountant collaborator has no business_users role, so Rentals (owner and admins) doesn't open for them, though ministry_finance_access lets them read invoices"
  - "Rooms per Sunday service, setup/teardown buffers, and resources attached to a room (the projector that lives in the hall): Planning Center has them; not here yet"
  - "Chief can't book a room yet (no action handler)"
decisions:
  - "Lane: Build, under the Build item 'Love City leaves Subsplash (M-1)'"
  - "One row per booking; a weekly repeat is one row a week sharing series_id, expanded in the church's clock (the app sends the person's own zone), a year at most, all or none"
  - "A clash is two BOOKED bookings of one space that overlap (half-open: back to back is fine). The server refuses the second and names it (409 {code: clash, message, clashes}); an exclusion constraint (btree_gist) backs it up when two people press Book at once. A request over a booked time is refused too; requests may overlap each other, and approving the second is refused"
  - "Who: the owner and admins, and office logins whose areas are the whole church or include the Office (church_areas.my_areas; any login while CHURCH_AREAS isn't on). Owner, admin and manager book straight away, approve and keep the spaces; a member-level login asks; a viewer only looks"
  - "A rental's money (fee, deposit, bill) is the owner's and admins', as invoices are for a church (ministry_finance_access); everyone else sees a rental without amounts, and can take one without them"
  - "The bill is a draft invoice made by the server in the invoices' own shape and numbering (INV-YYYY-NNN, as InvoiceComposer and Chief), its id fixed by the booking so two presses make one bill; the app then sends it through its existing send path. The renter becomes one of the church's people (a guest, source room_rental) when they aren't already, so the bill has an email"
  - "Spaces are retired (active false), never deleted, so old bookings keep their room"
related: [2026-10-27-church-keys.md, 2026-10-23-church-areas-map.md]
---
- `church_spaces.py` (new): the switch (`CHURCH_SPACES` off | owner | on,
  owner by default, like `church_keys.py`), who may do what, spaces,
  bookings with clashes and weekly repeats, approvals, the rental bill and
  twelve routes under `/church/spaces` (the module docstring lists them).
  `/church/spaces/status` answers `{enabled, book, approve, rentals}` and is
  quietly false for a closed switch, a business that isn't a church, a login
  that doesn't work the office, or tables not made yet.
- `supabase/APPLY-2026-10-27-church-spaces.sql` (new, NOT applied):
  `church_spaces` and `church_space_bookings`, both server-only, with
  `btree_gist` for the no-clash constraint. Ledger row in `docs/MIGRATIONS.md`.
- `account_lifecycle.py`: both tables exported (bookings first); bookings
  skipped on import (they cite spaces, people and bills by id).
- `kmj_intake_automation.py`: mounts the router after the keys router.
- `.github/workflows/ci.yml`: adds `church_spaces_db.mjs`.

Checks:
- `__tests__/test_church_spaces.py`: 14 tests (the clash refused and named,
  two presses at once, requests and approvals, weekly repeats across the
  clock change, a login outside the office refused, another church's spaces
  invisible, the switch and missing tables, the bill made once and linked,
  rental money kept to the owner and admins, the spaces list).
- `__tests__/church_spaces_db.mjs`: 32 checks on PGlite with btree_gist.
- Export/import, the access ratchet, route type hints, seat access, areas
  and keys pass.
