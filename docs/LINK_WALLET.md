# Solutionist Wallet v1

Version 1 connects a customer's existing Link account. It does not hold a balance,
issue cards, implement delegated approval, retrieve live payment credentials, or
execute merchant checkout. Live spending is hard-disabled, independent of env flags.

## Two separate connections

- The existing private pilot remains limited to CHIEF_LINK_PILOT_USER_ID and
  CHIEF_LINK_PILOT_BUSINESS_ID. Its device client and encrypted sessions are unchanged.
  The new owner-authenticated API exposes only that pilot's existing connect,
  status, simulated $1 rehearsal, check, cancel and disconnect operations.
- Customer connections use the registered confidential OAuth client. They never
  use the private device client. Credentials are encrypted with a different key
  and stored in a separate service-only table keyed by business and initiating owner.

Official protocol checked September 23, 2026:
https://docs.stripe.com/agentic-commerce/link-cli/oauth

The application is submitted, not approved. Do not enable customer connections
until Stripe has delivered the registered credentials securely and the flow has
passed a real owner-controlled integration rehearsal.

## Activation order

1. Deploy the backend and apply supabase/APPLY-2026-09-23-link-wallet.sql after merge.
   It is idempotent. Existing public.businesses and auth.users are its only dependencies.
2. In the server's secret store, set a new Fernet LINK_WALLET_ENCRYPTION_KEY.
   Back it up securely; losing it requires reconnecting all customer accounts.
   Do not reuse CHIEF_LINK_PILOT_ENCRYPTION_KEY.
3. Set LINK_WALLET_CLIENT_ID, LINK_WALLET_CLIENT_SECRET and
   LINK_WALLET_PUBLISHABLE_KEY from the approved registration and matching account.
   Never expose the secret/key for encryption to the browser, logs, AI, Git or docs.
4. Confirm the registered callback is exactly:
   https://kmj-intake-server-production.up.railway.app/link/oauth/callback
5. Set LINK_WALLET_ENABLED=true only for the authorized connection rehearsal.
   This allows customer connections, never live spending.
6. Verify the supported Link-hosted flow in desktop, mobile and installed PWA.
   Link may require a top-level browser tab. Never embed or proxy its login to
   bypass its frame protections. The standard flow does not provide custom,
   delegated approval inside Chief.
7. Test connect, callback, completion, refresh, reload, canceled authorization,
   disconnect and cross-business switching. Confirm no purchase occurred.

Deploying with all new env vars absent leaves private pilot access intact and
reports customer connections unavailable. Setting the enable flag false stops
new connections and completion/refresh; stored connections remain visible and
revocable while their encryption key and client credentials are retained.

## HTTP contract

All /link/wallet/{business_id} endpoints require a verified JWT and business-owner
access. Tenant identity is never accepted in action bodies. All successes and
sanitized operational failures are no-store.

- GET /link/wallet/{business_id}: safe snapshot; never polls Link or returns tokens.
- POST .../connect: danger-scope step-up; starts PKCE/state; returns authorization_url,
  state, a separate browser verifier, and expires_in=600.
- GET /link/oauth/callback: public provider callback. State hash finds a tenant,
  the encrypted pending state verifies expiry/binding, and the first callback
  saves a code (or denial). It never exchanges tokens or changes ownership.
- POST .../complete with state/verifier: the same authenticated owner polls.
  202 means awaiting callback; 200 means connected. A code is consumed before
  exchange. Ambiguous exchange failure requires a fresh connect; no blind replay.
- POST .../refresh: verifies /userinfo, discards personal fields, rotates expiring
  tokens under the lease, and persists the replacement before using it.
- POST .../disconnect: revokes at Link before clearing state. Failure retains
  the connection so revocation can be retried.
- POST .../pilot with operation: configured private owner only; connect/rehearse
  additionally require danger-scope step-up. Amount, credentials and live flags
  cannot be supplied by the caller.

The original browser holds only state + verifier temporarily. It polls authenticated
completion, so COOP or a mobile browser severing window.opener does not break return.
No authorization code or access/refresh token is sent to the app. PKCE verifier is
server-held. Callback HTML reflects no query fields and sends no-referrer, no-store,
CSP default-src none and frame denial headers.

## Security and operational boundaries

- Encryption authenticates a binding containing both business ID and owner ID.
  Swapped ciphertext fails closed.
- Database lease/CAS serializes writes and refresh rotation across workers.
  Browser roles cannot read ciphertext or call any wallet RPC.
- The state lookup contains only SHA-256 of 256-bit random state, not raw state/code.
  Pending state and browser verifier expire in ten minutes. First callback wins;
  completing consumes the state and makes callback replays fail.
- Provider hosts are fixed, redirects disabled, timeouts bounded. Errors never
  echo provider bodies, credentials or exception details.
- Restrict infrastructure access logs for /link/oauth/callback: application scope
  query strings are redacted, but an upstream proxy can log before the application.
  No third-party assets or analytics load on the callback page.
- The existing password step-up is reauthentication, not MFA.
- No transaction history is invented: private activity includes only existing
  current/previous pilot requests with a clear simulated amount.
- The UI must validate Link URLs, offer a popup-blocked fallback, stop polling
  on business changes/unmount, bound automatic retries, and never imply an approval
  is a completed/paid merchant order.
- Confidential OAuth provider calls are tested with fixtures until credentials arrive;
  local tests are not proof that registration or production checkout works.

## Checks

python -m pytest __tests__/test_link_wallet.py __tests__/test_chief_link_pilot.py -q

Set PGLITE_MODULE to the installed @electric-sql/pglite/dist/index.js path, then:
node scripts/link-wallet-db-check.mjs

The database test runs PostgreSQL locally with synthetic data only. It checks
migration reruns, lease contention/expiry, stale writers, tenant separation,
callback-state lookup/consumption and service-only permissions.
