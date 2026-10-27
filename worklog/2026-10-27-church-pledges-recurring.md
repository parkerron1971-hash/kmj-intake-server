---
title: Giving door's office pages — recurring gifts list, pledges and campaigns (server; switched to the owner)
date: 2026-10-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-27: "lets start building this" (gap check of a church staff menu, https://claude.ai/artifact/4oXF1Be46RddJxXnKAHodn, "The other doors", Giving card: no office list of recurring gifts; no pledges or campaigns)'
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio (the pages, next PR)]
migrations: ["supabase/APPLY-2026-10-27-church-pledges.sql (NOT APPLIED; Kevin applies by hand)"]
left_undone:
  - "Apply supabase/APPLY-2026-10-27-church-pledges.sql. Until then status says pledges false and the Pledges page stays off the menu; the Recurring gifts page works without it"
  - "Members seeing their own pledge progress on /my/gifts: left out. The member app is a public surface and CHURCH_PLEDGES=owner can't scope it to the platform owner (members aren't him), so it would go live for every church at once"
  - "A campaign can be edited but not deleted or archived; it ends by its dates"
  - "No Chief verbs (record a pledge, read a campaign's progress) and no pledge reminders"
  - "Two campaigns on one fund with overlapping dates both count the same gift: a gift says only its fund"
  - "Switch CHURCH_PLEDGES to on (a Thursday) once Kevin has lived in it"
  - "The campaigns list reads every paid gift in each campaign's days so far (merged stretches, nothing after today). A church with years of old campaigns still reads each one's period; store ended campaigns' totals if that gets slow"
decisions:
  - "Lane: Build, the Build item \"Love City leaves Subsplash (M-1)\""
  - "Recurring gifts live only in Stripe (subscriptions on the church's connected account, metadata source_type=gift + business_id); read server-side with the customer expanded for name/email, each row built field by field so no card data passes; cached 2 minutes per replica; a failed read is a 503, never an empty list"
  - "Office list is read-only; changing a gift stays the giver's, on /my/gifts"
  - "Monthly figure: active gifts only, weekly x 52/12, every two weeks x 26/12, monthly x 1, by fund"
  - "Money is owner, admins and the accountant (giving_records.require_finance); who gave what (the recurring list, the pledges) also sits behind church_keys.wall giving_money; campaign totals stay open"
  - "Progress is never stored: paid gifts to the campaign's fund (normalized, so Building = Building Fund) on the church's own calendar days inside the dates, net of refunds"
  - "One pledge per giver per campaign; a pledge is a total or per week / two weeks / month x periods (the server works out the total); request_id makes a retried save land once"
  - "Switch CHURCH_PLEDGES = off | owner | on, default owner"
  - "Review fixes: Refresh (fresh=true) reads Stripe at most once per 15 seconds per church, since checkout shares the platform Stripe key's rate limit; gifts are read only for the stretches campaigns have run (merged, up to today), never the gaps between them"
related: [2026-10-27-church-keys.md]
---
Before building I read both repos' `worklog/`: nothing on pledges,
campaigns or an office list of recurring gifts. The nearest work is
`member_portal_gifts.py` (#1424: a giver's own gifts) and church keys.

- `church_recurring_gifts.py` (new): reads every subscription on the
  church's connected account, keeps gifts to this church, and shapes a row
  (giver, email, contact id when one matches, amount, fee, how often,
  fund, next date, state, late). Totals for the top of the page.
- `church_pledges.py` (new): the switch, status, and the routes under
  `/church/giving/` (status, recurring, campaigns GET/POST/PATCH, pledges
  GET/POST/DELETE). Progress math is pure (`progress`, `counted`).
- `supabase/APPLY-2026-10-27-church-pledges.sql` (new): `church_campaigns`
  and `church_pledges`, server-only. A composite key keeps a pledge on a
  campaign of the same church.
- `account_lifecycle.py`: both tables exported and deleted with the
  church; pledges are skipped on import (they cite contacts and campaigns
  by id), campaigns restore.
- `kmj_intake_automation.py` mounts the router after church keys.
- `docs/MIGRATIONS.md` row; `ci.yml` runs `church_pledges_db.mjs`.

Checks:
- `__tests__/test_church_pledges.py` (14) and
  `__tests__/test_church_recurring_gifts.py` (10).
- I broke nine rules on purpose and the tests caught every one: the fund
  filter, the date filter, refund netting, the keys wall, the finance
  gate, the church's calendar day, this church only, a never-started gift,
  a missing table.
- `__tests__/church_pledges_db.mjs`: 21 checks on PGlite.
- Export/import, the access ratchet, keys, route type hints, seat access
  and member gifts all pass.
- Fix carried here: `test_church_news.py`'s office-page test read the real
  clock against a fake that stamps every row 2026-10-20, so it started
  failing on main at 13:00 UTC on 2026-10-27. Its clock is now frozen to that week.
