---
title: Help requests — the pastor says yes, the treasurer pays the provider
date: 2026-11-18
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-18, on the Prayer & care desk mock: "requesting help shouldn''t be directly tied to treasurer. shouldn''t the pastor handle that and submit approval to treasurer? what is often the best flow for that?" … "build it"'
status: in review
prs: [kmj-intake-server (this PR), solutionist-studio (help-treasurer-pays)]
migrations: [supabase/APPLY-2026-11-18-help-treasurer-pays.sql (not applied)]
left_undone:
  - "Apply supabase/APPLY-2026-11-18-help-treasurer-pays.sql. Until then sending and paying answer 503 and the page works as before."
  - "The treasurer's My week doesn't count help payments yet; the phone alert and email are the heads-up, and the count is on Help requests."
decisions:
  - "The care side (pastor, People & care staff) says yes, under the existing limit and keeper; then it sends money help to the treasurer with a payee (the provider, never the person), a reference and a due day."
  - "The treasurer is a login that sees amounts only (works Giving & money). It pays only what was sent to it, up to what's left of the yes, by check, a bank payment or a gift card. Paying more is a new yes and stays with the care side."
  - "The treasurer never sees who asked or the story; neither does the alert. The books get one expense under the fund, vendor = the payee."
  - "Told when sent: keepers of Giving & money, a login on the treasurer's lane, logins whose areas include Giving & money; never the sender; the owner when nobody else. Told when paid: whoever sent it. Channel: the phone alert + email the church keys use."
  - "Approve-and-send is one call (decide with send_to_pay); the send is checked before the yes, so a refused send never leaves a yes behind."
  - "A youth's ask is never sent; a send can be taken back until something is paid on it."
related: [2026-10-27-church-help.md]
---
`church_help.py`: `send_to_pay`, `unsend`, `pay_sent`, `treasurers`,
`tell_treasurers`, `tell_sender`, `pay_ready` (every read leaves the new
columns out until the migration is in), plus `to_pay` on each request,
`reference`/`by` on each payment, and `to_pay`/`to_pay_cents` on the fund.
The page's `me` gains `send` and `pay`; `/status` is unchanged. Seat names now
prefer `business_users.name`. Tests: `__tests__/test_help_treasurer_pays.py`
(10), `test_church_help.py` (13), `church_help_db.mjs` (54 with the new
migration's checks).
