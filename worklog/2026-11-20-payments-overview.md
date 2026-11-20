---
title: The church's Payments page, the new Overview, server half. The money path from given to the church's bank, the next payout, Needs you, the feed and its download, by fund, how people gave, money going out
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-19: "also upgrade the payments section as well. this needs to be top tier. make this experience awesome! show me the mock for this as well." He saw the mock and on 2026-11-20 chose "Build it". Contract: payments_overview_contract.md (the app is built against it in parallel; the differences are written under its "Changes").'
status: in progress
prs: [kmj-intake-server#2003, solutionist-studio#1657]
migrations: []
left_undone:
  - "Switched on for the platform owner's own church only (PAYMENTS_OVERVIEW unset = owner). Kevin sees it in the preview before it goes to every church (on)."
  - "The independent security review found no must-fix; its six should-fixes are made (below). Not merged yet."
  - "A store row says 'Store', not the items bought ('Store: 2 Advent devotionals' in the mock): order_items aren't read."
  - "Fee coverage counts one-time gifts only. A repeating gift's 'cover the fee' rides the subscription's metadata, which Stripe doesn't copy onto each charge, and the church's own gift row doesn't store it."
  - "On Stripe's newer API (Basil and later) a charge no longer names its Stripe invoice, so a repeating gift's charge can't be tied to its gift row: it shows the card holder's name and 'A repeating gift'. One-time gifts, store orders and event sign-ups always tie to their rows."
  - "A period with more than 1,000 card payments (a big church's year): fees, how people gave and the covered-fee count are from the newest 1,000 (counted.complete false). Given and by fund always count every gift (the church's own records)."
  - "Answering a dispute in the app is piece 2; 'Answer the bank' opens Stripe."
decisions:
  - "Who sees what asks only doors that already exist: the page is the church wall at the books (owner, Admin, accountant; with the giving tick on, any tick) and the Giving keeper, as the Stripe proxy; everything read from Stripe (fees, methods, what's on the way, the bank, the next payout, disputes, the feed and its download) is the Payouts tab's door (the owner, or the 'bank and payouts' tick); names follow church_money_gate.sees_givers; refund mirrors the refund route; disconnect is the owner (part setup); each going-out card asks its own page's door."
  - "The feed is Stripe's charges (the one list of every card payment, with fee, method and payout), tied to the church's own rows for names and funds; totals and funds come from the church's own records for any period, so a year never means Stripe paging."
  - "A tick with the bank but not 'who gave' sees the feed without names AND without a card's last four (it points at the giver). The Stripe proxy's charges door would refuse that login outright; the refunds door it already opens shows more than this does."
  - "Where a gift is: Stripe's automatic payouts sweep everything available when the payout is made, so a charge rides the first payout made at or after its money became available (balance_transaction.available_on). Exact for automatic payouts."
  - "A week starts on Monday, on the church's clock. 'vs the period before' is the same stretch of it ('by this date'), never past the end of a shorter month."
  - "Stripe reads are kept 60 seconds per church, its connected account and the period, in each replica's memory; a read that failed isn't kept. Every read and write drops what has run out, and the whole cache is held under 200 entries and 10,000 rows, oldest out first. Stripe reads are free and the existing proxies don't meter them, so this doesn't either."
  - "After the security review: rate_limit per login (fail-open, as every practitioner screen): the feed 60 a minute, the download 6 every 10 minutes, and any read that has to go to Stripe 30 every 10 minutes; a refusal is a 429 with a plain sentence and Retry-After. The switch and 'is it a church' are asked before any door, so off or not a church is a 404 for everyone. A login that may not see who gave gets each row's day, never its time (and no Time column in the download). CSV cells are trimmed and collapsed before the formula check. Ids are fullmatched."
related: [2026-11-18-one-money-gate.md, 2026-11-19-payroll-free-version.md]
---
Before building, both repos' work logs were read: nothing had started a new
Payments Overview. It builds on the one money gate and the giving tick
(11-18) and reads the payroll calendar (11-19).

New: `payments_overview.py` (three read-only routes: `GET /payments/overview`,
`/payments/feed`, `/payments/feed.csv`), mounted before the public-site
catch-all, `PAYMENTS_OVERVIEW` in `.env.example`, and
`__tests__/test_payments_overview.py` (shapes, period edges, the switch, every
door, the cache, the paging cap, Stripe and records failures as holes, where
each gift is, the feed's filters, search, paging past the kept charges, and
the download).
