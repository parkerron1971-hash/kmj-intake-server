---
title: Church areas, step 2, part 4b — a board member says yes from the member app, with a fresh code on every approval
date: 2026-10-28
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-28: "The 7 office logins are for the office only ... Everyone else uses the member app, by role, on phone or computer ... Please build step 2 (the board member''s yes from the member app, with a fresh code on every approval) and then step 1 (a Board tab, with approvals inside it) ... Board members are matched by their contact in church_board_members, so make sure each one has an email on file"; "yes start step 2"'
status: in progress
prs: ["kmj-intake-server (this PR)"]
migrations: ["supabase/APPLY-2026-10-28-church-board-member-yes.sql (applied 2026-10-28 before the code, verified)"]
left_undone:
  - "Step 1, the Board tab: meetings, minutes and these approvals in one tab of the member app (next PR). Until then the way in is the email's link"
  - "A board member's no: they tell the treasurer, who declines it in the office with the reason the asker reads"
  - "The pastor's yes still comes from the office login (Kevin's); only the board's comes from the member app"
  - "A member's phone isn't alerted (member_push has no kind for it); they hear by email"
decisions:
  - "A board member is their person on a board that isn't archived (church_board_members.contact_id, Kevin's ask), with an email on file: that email is how the member app reaches them and where their code goes. The office page names board members without one"
  - "A yes from the member app is a church_check_approvals row with contact_id (no login); one human gives one step: a person's yes and a login's are the same human when the emails match, both ways"
  - "Every yes takes a fresh 6-digit code, emailed for that request alone: it works for 10 minutes and 5 tries, an hour gives 6 at most, only its hash is kept, and it is used once (marked before the yes is recorded). A code for another request or another person reads as 'ask for a new code'"
  - "Whoever asked never counts, here too: a member's own request doesn't wait on them, and they aren't told to approve it. When a request waits on the board, board members without an office login hear by email, linking to /my/board/approvals; a board member whose login already hears it isn't emailed twice"
  - "/my/board/approvals is built for computers first (the Lead tab's two columns: the list, then the request with its receipt, who has said yes and the yes), and stacks on a phone. Home is untouched (another session builds its computer layout)"
  - "Switched with check requests (CHURCH_CHECKS) and the money levels; every POST refuses another site's form and is rate-limited per person"
related: [2026-10-28-church-money-levels.md]
---
Changes:
- `church_money_levels.py`:
  - `board_people`, `member_me`, `_gave` (one human, one step), and `_names` keyed by login or person;
  - `_give`, shared by the office and the member app;
  - `member_view`, `send_code`, `confirm_code`, `member_receipt`;
  - `tell_next` emails board members, via `_tell_people`;
  - the page's board gaps now ask for an email instead of a login.
- `member_portal_board.py` (new): `/my/board/approvals`, its receipt, and the code and approve posts.
- `member_portal.py`: dispatches `/my/board`.
- `kmj_intake_automation.py`: mounts the board router.
- `account_lifecycle.py`: `church_check_approval_codes` is excluded from export.
- `supabase/APPLY-2026-10-28-church-board-member-yes.sql` (new).
- `__tests__/church_board_member_yes_db.mjs` (new, added to CI): 17 checks.
- `__tests__/test_church_checks.py`: 6 new tests.
- `docs/MIGRATIONS.md`: the ledger row.

Checked:
- `pytest __tests__/test_church_checks.py`: 37 pass.
- Seven breaks are each caught: any code accepted, no try limit, another request's code, one human giving two steps, no expiry, no same-origin check, and (via the email path) the asker's own request.
- The member, church, export, ownership, worklog, routing, portal and money subsets: 2,429 pass.
