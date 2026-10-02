# Lane private pilot setup

Status: merchant-review workflow implemented and covered by offline tests.
LANE_CHECKOUT_ENABLED was switched on 2026-09-25, with Kevin's approval, for the
agreed small pilot purchase (step 4 of the live acceptance below). Set it back to
false to stop checkout. Passing fixtures or a connection check does not establish
successful payment; only that bounded live test does.

## Account setup (Kevin)

1. Open https://wallet.getonlane.com and sign up/sign in yourself.
2. Add your card through Lane's own secure interface.
3. Open Settings > API and create/copy your personal key.
4. Put it directly in the backend platform's secret variables as LANE_PILOT_API_KEY.
   Do not paste it into Chief chat, browser settings, source, or an issue.

Lane's documentation currently says a personal wallet needs no plan or business
verification. That does not establish a zero cost for every purchase. An organization
key is a separate product requiring business verification and a subscription.
Do not use Kevin's key for customer purchases.

Official account guide: https://docs.getonlane.com/buy/keys-and-wallet

## Operator configuration

Apply supabase/APPLY-2026-09-24-lane-wallet.sql to the intended database before
enabling purchase drafting, and supabase/APPLY-2026-09-25-lane-saved-links.sql
before saved merchant links. All tables and functions are service-role only.
The migrations are repeatable; the local database tests run each twice.

Backend secret variables:
- LANE_PILOT_ENABLED=true
- LANE_PILOT_BUSINESS_ID=<authorized business UUID>
- LANE_PILOT_USER_ID=<its owner's user UUID>
- LANE_PILOT_API_KEY=<personal wallet key from Lane>
- LANE_WALLET_ENCRYPTION_KEY=<Fernet key, generated and stored privately>
- LANE_PURCHASES_ENABLED=true (only after migration and secret configuration)
- LANE_CHECKOUT_ENABLED=false (keep off until the live-provider acceptance checks)

Do not expose these variables through VITE_, client JavaScript, or .env committed to Git.
Keep the encryption key backed up in the platform's secret store. Changing the API
key changes the wallet binding; old records fail closed until intentionally migrated
by an operator. Do not silently rebind past approvals to a new key.

## What is implemented

- Wallet connection check, private pilot availability and setup link.
- Chief finds the merchant product or billing page from a fitting saved link or web
  search, then looks at it (read-only; nothing saved) and tells the owner what it
  found, or that the page needs their sign-in. A DNS-pinned public fetch records
  source text without account cookies. Public text is untrusted evidence and never
  a verified final checkout quote. Chief never signs in to a merchant page.
- Chief's proposal (and a saved link) is HELD through chief_holds: Chief reads back
  the merchant, page, USD limit and account, and nothing is saved until the owner's
  own next message is a go-ahead ("save it", "go ahead", "go ahead and remember
  it"; a bare "yes" does not count). The go-ahead releases only that page, account
  and limit; a changed limit is held and read back again.
- Saved merchant links (lane_links.py): page, merchant name and account only, never
  a limit, password or code; encrypted like purchases, keyed-hash deduplicated per
  page and account, 20 per owner, listed and removable in Wallet. A saved link is a
  starting point: every look and proposal reads the page again.
- Wallet shows the source, limit and account before the owner explicitly prepares
  the request in Lane. Unsent proposals can be dismissed without provider calls.
- Provider drafts exceeding the total ceiling or changing merchants are blocked.
  Known provider identifiers survive unsupported draft responses for reconciliation.
- Clarification questions preserve every choice. Hosted approval has a popup and
  fallback link. Saved purchases distinguish approval from confirmed order status.
- Chief lane_wallet tool: look/draft/remember/forget/status only through the authenticated chat action door.
  Model output cannot submit to Lane, approve or execute checkout. Identical Chief
  requests and purchase details for the same owner/business reuse a deterministic ID; use the Wallet form
  for an intentional repeat purchase.
- Exact financial terms and funding choice are reviewed in Lane's hosted approval
  flow. No iframe/embedded approval claim; provider support for that is unconfirmed.
- Starting checkout requires the owner, current revision, account step-up, explicit
  UI confirmation, and a freshly checked matching Lane approval.
- Immediately before execution, read Lane's current intent amount, currency and
  merchant and enforce the saved limit. Missing or unmatched terms block checkout.
  Product resolution must return the exact reviewed URL; changed links block.
  The merchant must match the owner-reviewed name or domain. Unsupported currencies and unrecognized provider
  schemas fail closed. This private pilot currently supports one merchant per request.
- Product resolution precedes execution. A permanent database checkout claim is
  written before start_session. It is not an expiring lock and is never cleared
  by a timeout, restart, failed poll or a browser refresh.
- Purchase records are encrypted and bound to business, user, wallet key fingerprint
  and purchase ID. Cross-worker leases and revision checks protect updates.
- Immediate order poll, then visible-tab polling every three seconds. An open wallet
  page is required for ongoing prompts; background unattended checkout is not supported.
- Merchant sign-in/password/code/address prompts open Lane's secure ask_url.
  There is no credential/code input endpoint and no inline intent_approve call.
- Only a complete Lane order receipt produces "Order placed." Approved is a separate
  status. Unknown outcomes remain locked for reconciliation, never automatic retries.

## Live acceptance before activation

1. Deploy the reviewed backend/frontend and migration; configure the owner pilot.
2. Run Check Lane connection. Confirm the advertised tools with the real account.
3. With checkout still off, prepare one real draft and verify returned schema,
   merchant, limit, currency, funding rail and hosted approval/passkey behavior.
   Draft creation is not a simulated purchase; the intent_submit test flag has no
   effect in production. Do not approve a draft that should not be purchased.
4. Activate checkout only for a specifically agreed small pilot purchase, with the
   user present. Verify questions, receipt, actual charged amount and merchant order.
5. Confirm provider fees, eligible cards, shipping/merchant coverage and support
   before customer rollout. Customer credential provisioning is not implemented.

## Recovery and current limits

A submitting draft without a returned provider ID is ambiguous. An uncertain
checkout may already have charged. Inspect Lane and the merchant; do not create a
replacement order or reset checkout_claimed as a retry mechanism. One unfinished
purchase per owner/business blocks a second purchase until reconciled.

Cancel approvals, stop a running purchase, and request refunds in Lane/the merchant
for now. There is no Solutionist cancel/refund endpoint. Approval links are not
payments, and stopping a browser is not proof of a refund.

No prepaid-credit loading, automatic budget increase, raw-card vault, merchant
password vault, regular-card enrollment in Solutionist, customer onboarding, or
PayPal integration is added here.

## Local verification

- python -B -m pytest __tests__/test_lane_purchases.py __tests__/test_lane_wallet.py
  __tests__/test_link_wallet.py __tests__/test_chief_link_pilot.py
  __tests__/test_action_registry.py __tests__/test_tool_loop.py
  __tests__/test_policy_engine.py -q -p no:cacheprovider
- PGLITE_MODULE=<local PGlite module URL> node scripts/lane-wallet-db-check.mjs
- PGLITE_MODULE=<local PGlite module URL> node scripts/lane-saved-links-db-check.mjs
- Frontend: npm run typecheck; npm run build
- With the local Vite fixture on port 8799:
  python -B scripts/lane-wallet-ui-check.py
  python -B scripts/wallet-ui-check.py

All browser fixture traffic to external HTTPS hosts is blocked. Fixture approval
and checkout responses are synthetic; passing these checks is not a live payment test.
