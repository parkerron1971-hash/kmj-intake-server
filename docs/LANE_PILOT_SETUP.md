# Lane private pilot setup

Status: implemented locally and tested with provider fixtures. Kevin created his
Lane wallet and reported adding a card. A read-only MCP connection check on
2026-09-24 verified the personal key and all required buyer tools. No purchase
or payment tool was called. Deployment and live draft acceptance remain pending.

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
enabling purchase drafting. All tables and functions are service-role only.
The migration is repeatable; the local database test runs it twice.

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
- Owner-bound draft creation, clarification questions with every choice, secure
  approval popup plus a fallback link, saved purchase list and order status.
- Chief lane_wallet tool: draft/status only through the authenticated chat action door.
  Model output cannot approve or execute checkout. Identical Chief draft text for
  the same owner/business reuses its deterministic request ID; use the Wallet form
  for an intentional repeat purchase.
- Exact financial terms and funding choice are reviewed in Lane's hosted approval
  flow. No iframe/embedded approval claim; provider support for that is unconfirmed.
- Starting checkout requires the owner, current revision, account step-up, explicit
  UI confirmation, and a freshly checked matching Lane approval.
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
- Frontend: npm run typecheck; npm run build
- With the local Vite fixture on port 8799:
  python -B scripts/lane-wallet-ui-check.py
  python -B scripts/wallet-ui-check.py

All browser fixture traffic to external HTTPS hosts is blocked. Fixture approval
and checkout responses are synthetic; passing these checks is not a live payment test.
