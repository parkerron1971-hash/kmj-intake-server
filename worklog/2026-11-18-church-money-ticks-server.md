---
title: Giving as its own tick, the server piece. The owner gives it with the password, an Admin asks, and one switch turns it on
date: 2026-11-18
agent: Claude Code (Claude Fable 5.2)
asked: 'Kevin, 2026-11-18: "yes build with C." Then, on the bank: "stripe and payout would stick with treasurer and fall back to Pastor if there is no treasurer", and "yes to the split, let them refund freely for now".'
status: in progress
prs: []
migrations: []
left_undone:
  - "Not pushed: local commits on church-money-ticks-server, for the parent session to have reviewed and open as a PR."
  - "CHURCH_MONEY_TICKS ships off. It is not safe to switch on until supabase/APPLY-2026-11-18-church-money-holders.sql is applied (before that every login reads 'no tick', so on behaves as off) and the old gift thank-you events are moved (the block at the bottom of this file)."
  - "STILL NOT SAFE TO SWITCH ON without a second review of the fixes made after the first one (the section 'After the independent review' below), the migration applied, and the old gift thank-you events moved."
  - "A giving tick's Chief runs FIVE money verbs only (the giving counts and statements; chief_areas.TICK_VERBS). Bills, the bank, the books, expenses, funds, products and stock through Chief stay the owner's and the Admins'. Each one is added only with a handler that asks the money gate."
  - "The audit for giver names was done by reading each door's gate and what its module returns, not by running every route with a See login. The bank's own lines (a deposit's memo can name a payer) are what the bank tick opens, by design."
  - "A login that only Sees giving WITHOUT the 'who gave' tick reads the books, the bills, rentals, check requests and help amounts, but none of the gift records, statements, pledges, counts or giving reports: every one of those names a giver, and no route hides the names yet. Totals without names for such a login are not built."
  - "Money duties (the duties marked money in church_duties.CATALOG) still go only to an Admin login. A Work holder is not given them, so 'whose job is this' does not yet route money work to a treasurer who is not an Admin."
  - "No payout alert exists in the server today, so there is nothing to send to the bank-and-payouts holder yet. church_money_ticks.bank_holders() is there for when one is built."
  - "Chief's send_report (the revenue report by email) was not changed: it is not on a tick's short list, so only the owner's or an Admin's Chief, or the owner's own scheduled instruction (which runs with no login, as the owner), sends it, to the address that instruction names or the accountant's address in settings."
  - "Charges, booking checkout and no-show charges (stripe_payments_router) keep their seat ladders. Only the refund and the Stripe reads changed."
  - "A Viewer login still cannot mark any alert read (a Member and up, as the database always had it)."
decisions:
  - "ONE SWITCH, off by default, read from the environment alone when off: no door reads anything new, and RULES decides exactly as before (test_one_money_gate's old-against-new comparison passes unchanged)."
  - "The tick's standings come LAST in every row, so the owner, an Admin and the accountant pass as before and the holders table is never read for them."
  - "GIVING (gift records, statements, pledges, counts, giving reports) takes the 'who gave' tick, as the database does (a gift row is hidden without it). Any tick reads the books, bills, store orders, rentals, My week's money lines, check requests and the amounts side of help. Work or Lead changes them. The bank takes 'bank and payouts'. Reopening a closed count takes Lead."
  - "The LEGACY 'works Giving & money by Chief's guess' row is replaced by the tick when the switch is on (it admitted nobody in production on 2026-11-18) and kept when off."
  - "An Admin may LOWER or take away someone's giving (told to nobody extra, recorded); a holder of 'sets up jobs and sheets' may not. Some up and some down from an Admin is a request for the whole of it: nothing moves until the owner answers."
  - "An Admin login has giving already. The one thing the owner adds to one is 'bank and payouts' (so an Admin treasurer reads payouts and refunds). ONLY that is stored (a row at See with the bank, never an implied Lead or who gave); the gate reads work and who gave from the Admin seat itself. Moved down from Admin, the row is CLEARED before the level is written."
  - "A key not sent in `money` is UNCHANGED (level, who_gave, bank each); an explicit false is off; `level: null` takes giving away."
  - "Chief's scope is kept a minute a replica: a tick given or taken reaches that login's Chief within the minute. The doors themselves read the tick live."
  - "A refund by the bank-and-payouts holder asks for NO password: a danger password can only be confirmed by the owner. The owner is still asked. Every refund, whoever makes it, now writes a payment_refund_issued event (charge, refund, amount, who)."
  - "The payouts and refunds lists open to the bank tick; charges and customers need the bank tick AND 'who gave', because a charge names its giver."
  - "A raise or a request is written LAST in a sheet's save (the level it rides on is saved first); a change that only takes away is written FIRST. If the last write fails the rest is saved and recorded and the refusal says so."
  - "A login made a Viewer has its tick lowered to See BEFORE the level is written, and a lowering that fails stops the save, so moving it back up never brings Work back without the owner."
related: [2026-11-18-one-money-gate.md, 2026-11-18-church-money-holders.md]
---
## The contract, for the app

Everything below answers as today while `CHURCH_MONEY_TICKS` is off for the
church: `money` is `null` on the sheet, and the three request routes answer 404.

**`GET /church/sheet?business_id=&user_id=`** adds

    money: null | {
      level: null | "see" | "work" | "lead",
      who_gave: bool, bank: bool,
      words: "Work, with who gave and the bank and payouts" | "off" | "everything",
      pending: null | { id, asked_by, asked_by_name, asked_at, expires_at,
                        wants: {level, who_gave, bank}, wants_words },
      can: "grant" | "ask" | null,      // what THIS viewer may do here
      why: "",                          // the sentence when can is "ask" or null
      levels: [{key, label, means, allowed, why}]   // empty for the owner and an Admin
    }

- the owner's own sheet: level "lead", everything on, `can: null`.
- an Admin's sheet: level "lead", who_gave true, `bank` as ticked; only the owner (`can: "grant"`) changes `bank`.
- a Viewer login: only `see` is `allowed`.

**`PUT /church/sheet`** takes `money: {level: null|"see"|"work"|"lead", who_gave: bool, bank: bool}`
(`level: null` takes giving away). The answer is the sheet, with `money_asked: true` when a request was sent.

| Who saves | What happens |
|---|---|
| the owner, a raise (higher level, or a tick added) | saved; asks for the password (403 `ledger_locked`, as any widening) |
| the owner, a lowering | saved; no password |
| an Admin or a "sets up jobs and sheets" holder, a raise | a request to the owner; no password; nothing opens; `money_asked: true`, `owner_told: true` |
| an Admin, a lowering | saved; no password |
| a holder, a lowering | 403 "Only the owner or an Admin lowers someone's giving access." |

Refusals: 400 "Giving as its own switch isn't on for this church yet." · 400 "Pick Off, See, Work or Lead for giving." ·
400 "Send who gave and the bank as yes or no." · 400 "A Viewer login can only see giving. Make them a Member or Manager
login to let them work it." · 409 "There is already a request waiting for the owner about {name}." ·
503 "That request didn't send. Nothing changed. Try again." · 503 "Giving didn't save. Try that part again." (with
" Everything else on the sheet saved." when other parts of the same save went through).

**`GET /church/money-asks?business_id=`** → `{ok, can_answer, asks: [{id, user_id, name, asked_by, asked_by_name,
wants, wants_words, asked_at, expires_at}]}`. The owner reads every request waiting; anyone else, the ones they sent.

**`POST /church/money-asks/{id}/answer`** `{yes: true|false}`, the owner alone. A yes asks for the password
(403 `ledger_locked`, scope access, this church). → `{ok, status: "approved"|"declined", user_id}`.
403 "Only the owner answers a request for giving access." · 409 "That request isn't waiting any more." ·
409 "That request ran out before it was answered. Ask them to send it again." · 404 "That request isn't here."

**`POST /church/money-asks/{id}/withdraw`** (no body), whoever asked or the owner → `{ok, status: "withdrawn"}`.
403 "Only whoever asked, or the owner, takes a request back." · 409 "That request isn't waiting any more."

**`POST /church/alerts/read`** `{business_id, ids?: [uuid]}` → `{ok, read: n}`. Marks this business's unread alerts
read for the login signed in: a Member login and up, and only the alerts that login may see (a gift alert needs
"who gave"; a paid-invoice alert needs any giving tick, an Admin or the owner). **The app must switch to it** in
`src/core/components/notifications/notifications.ts` (`markRead`, `markAllRead`) and
`src/core/components/NotificationCenter.tsx` (the mark-all PATCH near line 125): since the money-holders migration a
login that only Sees giving cannot change an alert row from the browser.

A request waits 7 days. The owner is reminded once, 48 hours in (an hourly job, `church_money_asks`).

## The rules with the switch on (`church_money_gate.RULES_ON`)

| Part | See | Work |
|---|---|---|
| giving (gift records, statements, pledges, counts, giving reports) | owner, Admin, accountant, **who gave** | owner, Admin, accountant, **who gave + Work** |
| books | church: owner, Admin, accountant, **any tick** | owner, Admin, **Work** |
| bank | church: owner, Admin, accountant, **bank** | owner, Admin, **bank + Work** |
| bills | owner, accountant, Admin, **any tick** | owner, Admin, **Work** |
| store | owner, Admin, **any tick** | owner, Admin, **Work** |
| checks (the treasurer's desk) | owner, Admin, accountant with no seat, **any tick** | the same, **Work** |
| help (the amounts side) | **any tick** | **Work** |
| rentals, My week's money lines | owner, Admin, **any tick** | owner, Admin, **Work** |
| reopen a closed count | | owner, Admin, **Lead** |
| setup (link a bank, Stripe, payout account, giving setup, housing) | the owner | the owner |
| payouts and refunds lists (Stripe) | the owner, **bank** | a refund: the owner, **bank + Work** |
| charges and customers (Stripe) | the owner, **bank + who gave** | |

Work is never a Viewer seat's. A tick counts only on the active seat it was given to.

## What the two reviews said this piece must do

1. **Stop the gift thank-you event leaking a giver and an amount.** `payment_agent` now writes
   `giving_thankyou_created` for a gift (the events policy's giving class: who gave) and keeps
   `payment_thankyou_created` for a payment. Nothing reads either. The old rows are below.
2. **`p_by` from the verified login; the asker's standing checked on the server.** A request is only ever made inside a
   sheet's save, after `church_sheet.standing()` said this login edits that sheet (the owner, an Admin, or a holder of
   the grant; never their own); `p_by` is the session's user id. The answer route reads the request's church and
   refuses anyone but its `owner_id`.
3. **Read `ok` on answer; a second open request.** An answer with `ok: false` is the 409 "ran out". A second request
   is refused before the write (409), and a race that reaches the database's one-open index (23505) is the same 409.
4. **Delete on revoke; lower to See on Viewer.** `business_users_router.hand_back_login` clears the tick and withdraws
   any request about the login. `church_areas.set_login` lowers the tick before it writes a Viewer level.
5. **Mark money alerts read on the server.** `POST /church/alerts/read`.
6. **Split Chief's two shared giving gates.** `chief_giving_counts._chief(.., need)` (record and undo ask "work") and
   `chief_giving_actions._authorize(.., need)`. Chief's scope carries the tick: a login that only Sees giving has a
   Chief that reads money and refuses every money verb that changes it (`chief_areas.MONEY_READS`).

## For the owner to run, once, before the first tick is given (NOT run by this change)

    -- How many old gift thank-you events sit in the payments class (read only):
    --   select count(*) from public.events
    --    where event_type = 'payment_thankyou_created' and data->>'trigger_event' ~ '^(giving|donation)';
    --
    -- Move them to the giving class (one statement; safe to run twice):
    --   update public.events set event_type = 'giving_thankyou_created'
    --    where event_type = 'payment_thankyou_created' and data->>'trigger_event' ~ '^(giving|donation)';

## Tests

`__tests__/test_church_money_ticks.py` (40): the switch off, owner and before the tables; the gate person by part by
need; the sheet; the requests; the sweep; a login that leaves or is lowered; Chief; the Stripe doors; the thank-you
event; marking alerts read. `test_one_money_gate.py` passes unchanged with the switch off.

## After the independent review (2026-11-18)

The review: safe to merge with the switch off, NOT safe to turn on. What changed in answer:

1. **Who gave no longer leaks to a tick that only Sees.** One seam, `church_money_gate.sees_givers()`: with the switch
   off it is always yes and reads nothing; on, in a church, it is the giving rule (the owner, an Admin, the accountant,
   or the "who gave" tick). `reports_router._giving_wall` and `_givers_hidden` (the two places the reports already
   decided whether to name people, for the keeper) ask it; `_names_wall` refuses the three reports that have no
   nameless form.
2. **A tick that only Sees changes no money.** `church_money_gate.require_church_wall(.., need)`: a door with its own
   seat ladder behind the church wall asks at "work" when it is about to change something, and a login let in only by
   its tick must then hold Work. `church_help.pays()` asks "work". Chief: `TICK_VERBS`, above.
3. **A demoted Admin keeps nothing.** See the decisions; `church_money_ticks.role_lowered()` runs before the level is
   written and a cap that can't be saved stops the save.
4. **On before the SQL is exactly off.** The hooks and the sweep act only when `tables_ready()` (a kept, quiet probe).
5. **The refund**: `amount_cents` of zero or less is refused (it used to become a FULL refund, reachable on main by
   the owner, the only caller); an idempotency key goes to Stripe (the app's `request_id`, else the minute); the record
   is checked, and a refund made with no record is shouted in the log, told to the owner, and `recorded: false` in the
   answer.
6. **A lowering only lowers** (`_lower`: the level moves only from a higher one; who gave and the bank are only ever
   switched off there).
7. **A revoke clears only the tick tied to the seat row revoked**; asks about or by the person are withdrawn only when
   no active seat is left.
8. **The bank's report** (`/reports/bank-reconciliation`, and its export) takes the bank tick (`_bank_wall`).

Also: the Chief READ verb `list_money_asks`; the asker hears the owner's answer (a phone alert); a reminder is sent,
then marked.

### What a login with See and NO "who gave" gets, door by door (switch on, a church)

| Door | After |
|---|---|
| /reports/pl, cash-flow, balance-sheet, trial-balance, trends, budgets, budget-vs-actual, cash-forecast, expenses-detail, ap-aging, ar-aging, 990-prep, 1099-summary | open: totals, vendors and what is owed; no gift is listed by giver |
| /reports/revenue, /reports/profitability (and their exports) | totals kept, `by_customer` emptied, `givers_locked: true` |
| /reports/general-ledger, /journal, /audit-trail-report (and the two exports) | refused: "Who gave is kept for the owner, an admin, the accountant, or a login the owner ticked who gave for." |
| /reports/donors, /funds, /givers, /giver-history, /statement-customers, /customer-statement (and exports) | refused (the same sentence) |
| /reports/bank-reconciliation (and export) | refused without the bank tick |
| giving records, statements, pledges, counts, giving by service, church reports' giving, the roll's giving column | refused (the giving rule: who gave) |
| /giving-deposits (gifts matched to deposits) | refused without who gave, whatever the bank tick |
| the bank's reads (Plaid) | refused without the bank tick |
| bills, check requests, rentals, store orders, the amounts side of help, My week's money lines | open to See; they hold vendors, payees, renters and buyers, not gifts |
| the ledger's own doors (/gl trial balance, status, alarms, verify, admin log), payroll, contractors, the periods | open to See (totals and staff pay; a write needs Work) |
| Stripe payouts and refunds lists | the bank tick |
| Stripe charges and customers | the bank tick AND who gave |
| Chief | the giving counts and statements only, each behind the giving rule |

### The write doors swept (each asks "work", or is the owner's alone)

- Behind the church wall with a seat ladder, now at "work" for anything above reading: `gl_router._access` (backfill,
  reverse, process-queue), `payroll_router._access` (employees, runs, approve, mark paid, housing, cancel),
  `contractors_router._access` (create, onboard, refresh, pay), `accounting_periods_router._access` and
  `bookkeeping_close` through it (generate, close, reopen), `reports_router.put_budgets`.
- Already at "work" on their own row: every giving write (`require_finance(.., need="work")`: gifts, pledges, counts,
  statement mail, sheets), bills (`_writer`), the bank's writes (`_require_money_writer`: categorize, match, sync,
  rules, categories, Sunday's deposit, Chief's file-bank and reconcile), the store (`require_money_writer`), check
  requests (`treasurer`: "work"), rentals billing ("work"), reopening a count (Lead), paying help ("work", new).
- The owner's alone, unchanged: every other non-GET in `reports_router` (`_owner`), linking a bank, Stripe connect,
  giving setup, housing, funds.
- Refund: the owner, or the bank tick at Work.
- NOT swept by running them: `expense_categories`, `giving_deposits` writes and `funds` were read at their gate only.

