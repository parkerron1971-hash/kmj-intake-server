---
title: Church areas, step 2, part 4 — the money levels for check requests (the treasurer, the pastor from $500, a board member over $2,500)
date: 2026-10-28
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-23: approval levels by amount for money going out; 2026-10-26: "go with your picks" (under $500 the treasurer alone; $500 to $2,500 plus the pastor; over $2,500 plus a board member); 2026-10-28: "merge 1626 and change check requests yourself"'
status: in progress
prs: ["kmj-intake-server (this PR)", "solutionist-studio (the Check requests page shows the steps, its own PR)"]
migrations: ["supabase/APPLY-2026-10-28-church-money-levels.sql (applied 2026-10-28 before the code, verified)"]
left_undone:
  - "The levels are Kevin's amounts for every church, in code: a church can't set its own yet (the proposal's rule that raising them takes the top level needs a settings yes of its own)"
  - "Nothing expires or nudges: a request waits for its yeses until someone declines it (the proposal's 3 days to the second step and 7 to expire need a worker)"
  - "No monthly list of what was approved goes to the board yet"
  - "Money paid outside the system (a check written by hand, the bank's site) isn't matched to bank lines against the levels yet: step 5"
  - "Chief can't read or act on check requests yet (no action handler), so it can't route around the levels either"
decisions:
  - "One ladder for every amount (with kmj-intake-server-60, 10-28): the levels replace the $250 limit and the Giving keeper's yes above it, which left a treasurer who keeps Giving approving $3,000 alone. CHURCH_MONEY_LEVELS=off brings that back; any other value, a typo too, keeps the levels"
  - "On by default, not practice first: check requests is still the platform owner's alone (CHURCH_CHECKS=owner) and no church has used it, so there's no habit to change. Whoever turns it on for churches gets the levels from the first request"
  - "The pastor is the senior job in church_roles (the Lead or Senior Pastor), matched to a login by the email of the person who holds it; the executive pastor isn't one (Kevin, 10-27). A board member is a login on a board in Board & minutes that isn't archived. The pastor and a board member open Check requests to say yes or no, whatever their login's level, and add, change and pay nothing"
  - "Each yes is a row in church_check_approvals with its step; the database keeps one a step and one a person. A login that can give two steps gives the scarcer one (pastor, then board, then treasurer), so an owner who is the pastor doesn't use up the only pastor's yes on the treasurer's step. The request is approved by the yes that completes it"
  - "Whoever asked never counts: the office login that added it, or the person whose request it is (their email matches the login's). They aren't told to approve it either"
  - "Splits: a request counts as itself plus every other request (not declined) to the same payee within 7 days either side. The same payee is the name paid, or the person when the request pays them, so Dana's own request and the office's on her behalf add up"
  - "Past the budget: a request that takes its ministry over this year's budget (spent in the books, approved and not paid, and this) needs a board member, whatever its size. A line with no budget is never over"
  - "Changing the amount, the ministry or the payee takes the yeses back (before the change and again after it); changing only the words keeps them"
  - "Whoever can give a step still missing hears it once a yes is in: a phone alert and an email, linking to Operate → Check requests"
  - "A failed read of the pastor or the board is a 503, never a yes or a no; the page lists what keeps a step from being given at all (no one holds the pastor's role, the pastor has no login, no board member has one)"
related: [2026-10-27-church-checks.md, 2026-10-27-church-keys-gift-rows.md]
---
Changes:
- `church_money_levels.py` (new): the levels, who can give each step, what a request counts as, the yes, and who's told.
- `church_checks.py`:
  - `_access` lets in the pastor and board members.
  - `_can` gains `pay`.
  - `decide` gives a yes at this login's step.
  - `edit` takes the yeses back.
  - The keeper, the limit, the keeper's ask and its code apply only with the levels off.
  - The page carries `levels`, and so does each request.
- `supabase/APPLY-2026-10-28-church-money-levels.sql` (new): `church_check_approvals`.
- `__tests__/church_money_levels_db.mjs` (new, added to CI): 18 checks.
- `__tests__/test_church_checks.py`:
  - 15 new tests for the levels;
  - the three keeper tests now run with the levels off;
  - the paid test uses $450 and someone else's yes.
- `.env.example` (`CHURCH_MONEY_LEVELS`) and `docs/MIGRATIONS.md` (ledger row).
- `account_lifecycle.py`: the yeses aren't exported (sign-in user ids; the export keeps the requests), and they cascade with their request.

Checked:
- `pytest __tests__/test_church_checks.py`: 31 pass, with the levels on.
- Ten one-line breaks were each caught by at least one test: the asker rule, the fill order, $500 counting as "and up", the budget rule, the splits, one step a person, a viewer giving the treasurer's step, archived boards, telling someone who already said yes, and the payee's person.
- The PGlite test fails with the one-a-person rule or the same-church trigger removed.
