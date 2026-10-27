---
title: Board & minutes — boards, meetings, attendance with quorum, minutes and a decisions log (server)
date: 2026-10-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Church Office Prototypes (https://claude.ai/artifact/2vGqaUZUynRuiFVKuQEZWo), the "Board & minutes" tab → Kevin, 2026-10-27: "lets go with your list" (the board fifth; "make sure that the design is top tier")'
status: shipped, switched off (platform owner only until a Thursday); migration waiting on Kevin
prs: [kmj-intake-server (this PR), solutionist-studio (the Office › Board page, its own PR)]
migrations: ["supabase/APPLY-2026-10-27-church-board.sql (NOT APPLIED: Kevin applies by hand)"]
left_undone:
  - "Apply supabase/APPLY-2026-10-27-church-board.sql. Until then /church/board/status says enabled false and the other routes answer 503"
  - "Switch-on: CHURCH_BOARD=on on Railway on a Thursday (it defaults to owner), with the app's What's New entry"
  - "Chief can't read or act on the board yet (no action handler)"
  - "No phone alert when minutes go out for approval: email only"
  - "Approved minutes are locked for good; there is no 'correct the approved minutes' path (a correction is a new motion at the next meeting)"
  - "A board member who is one of the church's people but has no login can't open the page; they get the minutes by email"
decisions:
  - "Lane: Build, under the Build item 'Love City leaves Subsplash (M-1)'"
  - "No new area: the menu files Board under Office (church_areas 'office'), and the server's board-member check sits on top. The owner and admins see every board and set boards up; anyone else sees only the boards they sit on (an active member row with their login), a member-level seat or above writes there, a viewer reads. An office manager on no board is refused"
  - "A member is one of the church's people, a login, or both: a person whose email is a login's is linked to that login when added, so a deacon who signs in sees their board. Leaving a board is active = false, so old minutes keep the name"
  - "Quorum: a majority is more than half the members (4 of 7, 4 of 6), a count is that number; excused isn't present; a board with no members has no quorum. Before the minutes are drafted the roster is the board's members now (and anyone marked who has since left); after, whoever was marked"
  - "Ending the meeting (in progress → minutes drafted) marks whoever wasn't marked absent. Sending minutes from a meeting still in progress ends it first"
  - "Carry forward: a new meeting (and 'Bring in open items') takes the board's tabled and follow-up items from its earlier meetings; carried_from is unique, so an item is carried once, ever: twice-pressed or a later meeting finds it already carried, and a tabled copy carries on from where it is"
  - "A decision on an item: motion, moved by and seconded by (two different members of the board), for / against / abstain, carried / failed / tabled, decided on the meeting's own day in the church's clock. A tabled motion tables the item; carried or failed settles an open one. The item's title is kept with the decision for the log's search, and renamed with the item"
  - "Decisions log: every board this login sees (closed boards too), newest first; every word of the search must appear in the motion or the item's title; filter by board and year"
  - "Send minutes for approval: an email (email_layout + email_sender.send_via_resend, the church's identity) to each active member of that board, at their own email as one of the church's people, else their login's; nobody else. Says who had no email. Each send has its own idempotency key"
  - "Approving: only drafted minutes, optionally at a later meeting of the same board (approved_in, shown in that meeting's minutes); approved minutes no longer change (items, decisions, attendance, status, delete)"
  - "Make tasks from follow-ups: one task per follow-up item with none yet (title, a line saying which meeting, the item's minutes, due the follow-up's day), handed to the member's login where they have one (tasks.assigned_to); twice makes each once"
  - "Attachments are Documents: paths in the church's own folder of business-documents ({business_id}/...), never another church's, no new file type"
  - "Minutes never reach the member app; nothing here is read by member_portal"
  - "Review (PR #1617): an item follows its latest decision (tabled carries it, carried or failed settles it, none left reopens it; a follow-up stays one), on adding, changing and taking out a decision, and a move that doesn't save is a 503 that says the decision was kept. A carried follow-up keeps its task, so the next meeting's Make tasks doesn't make it twice. Sending is held to 6 an hour per meeting (rate_limit 'church_board_send'), each send has its own key, and a count that didn't save is reported, never a silent re-send"
related: [2026-10-27-church-help.md, 2026-10-26-task-hand-off.md, 2026-10-23-church-areas-map.md]
---
- `church_board.py` (new): the switch (`CHURCH_BOARD` off | owner | on, owner by
  default, like `church_keys.py`), who sees what, quorum, carrying forward,
  attendance, items, decisions and the log, the minutes as words, send, approve
  and tasks; 23 routes under `/church/board` (the module docstring lists them).
  `/church/board/status` answers `{enabled, manage, member, boards}` and is
  quietly false for a closed switch, a business that isn't a church, a login on
  no board (not the owner or an admin), or tables not made yet.
- `supabase/APPLY-2026-10-27-church-board.sql` (new, NOT applied): six tables,
  all server-only; every child carries `business_id` with a composite foreign
  key to its parent; a trigger keeps a member's person its church's; no drops.
  Ledger row in `docs/MIGRATIONS.md`.
- `account_lifecycle.py`: the six tables exported (first, before the contacts and
  tasks they cite); all but `church_boards` skipped on import (they cite each
  other, people and logins by id).
- `kmj_intake_automation.py`: mounts the router after Check requests.
- `rate_limit.py`: the `church_board_send` bucket (6 an hour per meeting).
- `.github/workflows/ci.yml`: adds `church_board_db.mjs`. `.env.example`: `CHURCH_BOARD`.

Checks:
- `__tests__/test_church_board.py`: 16 tests (a login on no board refused, an
  office manager too; a member sees only their board and a viewer only reads;
  another church unreachable, its people and files too; quorum math; the live
  quorum, excused, ending the meeting, someone leaving; an open item carried
  once; a decision's vote and the log's search across years; approving minutes
  and the lock; send only to the board's members; follow-ups become tasks once;
  the switch; before the migration; a business that isn't a church; an item
  following its latest decision; a carried follow-up keeping its task; sending
  held to a few an hour, each send its own).
- Rules broken on purpose, each caught: anyone seeing every board, half as a
  majority, minutes to people who left, a login on no board getting in,
  decisions on approved minutes. Carrying twice is held by the database's
  unique carried_from as well as the code.
- `__tests__/church_board_db.mjs`: 57 checks on PGlite.
- Export/import, the access ratchet, seat access, route type hints, step-up
  routes and Help requests pass.
