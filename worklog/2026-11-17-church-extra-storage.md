---
title: Churches can add 100 GB of storage for $5 a month (extra storage, like the extra office login)
date: 2026-11-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-17: "build" (sell +100 GB for $5 a month on top of a church plan''s storage allowance)'
status: waiting on Kevin
prs: [kmj-intake-server#1909, solutionist-studio#1618]
migrations: [supabase/APPLY-2026-11-17-settings-server-keys.sql (edited, still NOT applied: extra_storage joins the server keys, 43 now)]
left_undone:
  - "Kevin: create the three Stripe prices (STRIPE_PRICE_ID_EXTRA_STORAGE $5/month, _ANNUAL $50/year, _QUARTERLY $15 every 3 months) with the bootstrap catalog, narrowed to them, and set the three ids on BOTH Railway services (kmj-intake-server: the route and the webhook; kmj-intake-worker: the daily storage job's warning words). Nothing is sold until STRIPE_PRICE_ID_EXTRA_STORAGE is set AND CHURCH_STORAGE is on for the church."
  - "If APPLY-2026-11-17-settings-server-keys.sql was applied before this PR merged, run it again (it is safe twice): the applied copy would have 42 keys and would not guard extra_storage from the app's logins."
  - "Not tried against a live Stripe subscription. It is the extra login's code path with another price, tested against the same stand-ins."
  - "Chief has no verb for buying storage, and the public church pages don't mention it (the plan cards say each plan's storage only once CHURCH_STORAGE is on)."
  - "Pre-existing, not changed here: set_extra_logins passes Stripe's own error text ('Stripe error: ...') to the church on a refusal other than a declined card; the storage route says plain words instead."
decisions:
  - "Built as the extra login is: another item on the church's one subscription, quantity = blocks of 100 GB, a price per billing term (STORAGE_PRICE_ENVS: monthly $5, yearly ten months = $50, every 3 months $15), more paid today (PAID_TODAY, only if the card takes it), fewer leave a credit, owner only, the webhook keeps businesses.settings.extra_storage, a change of plan term takes the blocks along (storage_for_term) or is refused before Stripe is asked."
  - "An unreadable count is never 0 (church_billing.extra_storage_blocks answers None; logins read 0): 0 would make a church look fuller than it is. With a plan's allowance in play, church_storage.measure then marks the meter incomplete, so recording_ended holds nothing and the daily job releases, warns and removes nothing for that church that day. A church that left its plan is still let go of its dates whatever its count says."
  - "church_storage.business_row reads the count as extra_storage:settings->extra_storage (PostgREST JSON path), plus stripe_subscription_id; the daily job's rows already carry settings; any other row is read for it."
  - "GET /church/storage keeps its fields and adds extra_offer {gb, cents, every, blocks, can_buy, trial}: cents and every for the plan's term, read from the plan price's env name (no Stripe call); can_buy = the owner AND the price for that term set AND a church plan in good standing with a subscription AND a readable count; trial so the page can say nothing is charged yet."
  - "POST /billing/church/extra-storage {business_id, blocks}: more needs CHURCH_STORAGE on for the church; fewer is always allowed, even when it puts the church over. Then nothing is deleted, the normal 14-day rule applies to the next recording made while over, and the answer says so (over true + note; over null + an 'if' note when it couldn't be measured)."
  - "A Stripe refusal reads 'Your storage didn't change. Try again in a minute, or write to us.' (the Stripe text is print()ed). A settings write that fails after Stripe changed is not reported as a failure: the webhook writes the count."
  - "The webhook never lowers the count without positive evidence (review round): the count is read off items by env price ids, so a missing or changed STRIPE_PRICE_ID_EXTRA_STORAGE* would read billed blocks as none, the church as over, and the 14-day rule would remove recordings. sync_extra_storage writes nothing when no storage price is configured; never lowers while any item's price isn't a known plan, login or storage price; and lowers only when a recognised storage item shows the lower quantity, or when every item is recognised and the subscription is clearly the church's own (a church plan price, and the subscription id its row held BEFORE the webhook's patch, read by held_subscription only once storage is sold). A cancelled subscription goes to 0 only by that second rule. Raising from a recognised item is always allowed. Every skip is print()ed with why. (sync_extra_logins is unchanged: a lower login count deletes nothing.)"
  - "church_storage.ADD_STORAGE_SOLD is now add_storage_sold(): true once any extra-storage price id is set, and the warnings say 'Make room or add storage to keep it.'"
  - "extra_storage is a server key (business_settings.SERVER_KEYS and the unapplied SQL list): a forged one would be free storage."
related: [2026-11-17-church-storage-allowance.md, 2026-11-17-church-tier-fences.md, 2026-11-16-upgrades-paid-today-yearly-logins.md, 2026-11-03-church-logins-and-move.md, 2026-11-17-settings-server-keys.md]
---
Kevin's +100 GB for $5 a month, on top of each church plan's storage
allowance (#1903). `church_billing.py` gained the price per term, the
count reader, the webhook sync and `POST /billing/church/extra-storage`;
`church_storage.py` adds the blocks to the allowance (`extra_bytes`), makes
an unreadable count incomplete, offers it on the page (`extra_offer`) and
says the 14-day rule when blocks come off (`fewer_blocks_words`).
`stripe_billing.py`: three catalog entries, the webhook sync, and the term
change. Tests mirror the extra-login ones (`test_church_billing.py` 7,
`test_church_storage.py` 10, `test_one_subscription.py` 7b).

Overlap check: both work logs read. #1903 (storage allowance) left exactly
this hook (`extra_bytes`, `ADD_STORAGE_SOLD`, `extra_storage_offer`); the
frontend storage screen (FE 2026-11-17-church-storage-screen) is what the
button joins. Nothing else open touches church_billing or church_storage.
