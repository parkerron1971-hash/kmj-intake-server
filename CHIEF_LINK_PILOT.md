# Private Chief Link pilot

This release adds a single-owner test path through Chief chat. It does not enable
customer onboarding, live payments, a wallet balance, funding, or merchant checkout.
The existing Stripe Payments/Connect and virtual-card connector are unchanged.

Protocol references (reviewed September 12, 2026):
- https://docs.stripe.com/agentic-commerce/link-cli
- https://docs.stripe.com/agentic-commerce/link-cli/oauth
- https://github.com/stripe/link-cli/tree/main/packages/sdk
- https://github.com/stripe/link-cli/blob/main/packages/cli/src/auth/auth-resource.ts

The CLI's public device client is used for this private technical rehearsal.
Whether a hosted commercial product may use it for customer accounts still needs
Stripe confirmation. The published hosted guide calls for a registered OAuth client.
A passing personal test does not settle provider approval, limits, or pricing.

## Release

Apply `supabase/APPLY-2026-09-12-chief-link-pilot.sql` before enabling the feature.
Configure on the API service only:

- `CHIEF_LINK_PILOT_ENABLED=true` (everything is disabled when absent)
- `CHIEF_LINK_PILOT_USER_ID` (one authenticated owner UUID)
- `CHIEF_LINK_PILOT_BUSINESS_ID` (one business UUID, owner checked on every action)
- `CHIEF_LINK_PILOT_ENCRYPTION_KEY` (dedicated Fernet key, never in source/chat)

The model receives only the operation enum. Identity comes from the authenticated
turn. Background jobs, external agents, direct handler calls, and other users or
businesses are denied. Sessions are encrypted and bound to both identities, stored
in a service-only table. Leases serialize token refresh and state changes across
workers; a journaled idempotency key recovers an ambiguous create safely.

## Rehearsal through Chief

1. Ask **Connect my Link account for the private test.** Chief returns a Link URL.
2. Complete authorization at Link yourself. Only payment methods and account
   information are requested; no financial-insights permission.
3. Ask **Check my Link connection.** This completes the device-token exchange.
4. Ask **Run the Link test rehearsal.** Chief requests a fixed simulated $1 USD
   approval for Stripe Press. The owner approves at the returned Link URL.
5. Ask **Check my Link test.** The server validates the documented fake credential
   in memory, returns only a boolean, and cancels the request. No merchant is visited.
6. **Disconnect my Link test account** cancels a pending request, revokes this
   connection, and removes its stored tokens. **Cancel my Link test** preserves
   the connection. A completed test is reused rather than creating duplicate requests.

Do not paste credentials or verification codes into Chief. Payment values never
enter the model, browser hand, receipts, logs, or database. Only opaque auth tokens
are retained encrypted. Temporary fake test credentials are discarded immediately.
The old local CLI session is separate and must not be copied into this deployment.

## Recovery and limits

The pilot is interactive: no unattended polling, automatic approval, or live-mode
override exists. A deploy interruption releases the lease after 120 seconds.
Repeat status/check/rehearse to recover the same journaled test, not a new charge.
If a refresh token rotates but storage fails, reauthorization may be needed.
Provider errors are sanitized. Unknown response shapes fail closed. Revocation or
cancellation failures retain the connection so the user can retry, rather than
claiming cleanup succeeded. Disable the feature flag to stop new operations;
re-enable for the allowlisted owner to disconnect, or revoke in Link's settings.

Validation: `pytest -q __tests__/test_chief_link_pilot.py`; real PostgreSQL invariants
in `node scripts/chief-link-pilot-db-check.mjs` (also run in CI).
