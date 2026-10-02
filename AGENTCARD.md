# Agentcard Vault rollout

This integration uses Agentcard.sh customer-connected Vault and the Purchase API. It does not issue cards or store PAN/CVC. Cards are entered in a separate Agentcard tab, where the customer creates a passkey. Chief can prepare carts; owner confirmation requires the existing Solutionist step-up authorization. Returning after a matching provider approval resumes only that previously confirmed cart.

## Configuration

Apply `supabase/APPLY-2026-09-30-agentcard-wallet.sql` before enabling. Tables and lease/CAS functions are service-role-only. Wallet records bind business, owner, environment and OAuth application; encrypted state includes that same identity.

Set Railway secrets `AGENTCARD_CLIENT_ID`, `AGENTCARD_CLIENT_SECRET`, `AGENTCARD_ORGANIZATION_ID`, `AGENTCARD_ENCRYPTION_KEY` (Fernet), and `AGENTCARD_WEBHOOK_SECRET`. Never commit them. Keep the encryption key backed up in the platform secret store; changing it without re-encryption makes saved connections unreadable.

Set `AGENTCARD_MODE=production` or `sandbox`, `AGENTCARD_ENABLED=true`, and an initial comma-separated `AGENTCARD_ALLOWED_USER_IDS` owner pilot list. `AGENTCARD_CHECKOUT_ENABLED` defaults off. The default per-purchase limit is USD 150 (`AGENTCARD_MAX_PURCHASE_CENTS=15000`). Provider fees are included in the reviewed quote. Only one merchant/cart is supported per purchase.

Register `/agentcard/webhooks` for `vault.*`, `checkout_authorization.*`, `order.*`. The endpoint checks the raw-body HMAC and a five-minute timestamp tolerance, rejects the wrong mode, and stores encrypted deduplicated events. Events never authorize payments. Status reconciliation uses authoritative provider APIs.

## Acceptance and activation

1. Verify OAuth credentials and mode, migration permissions, signed webhook delivery, and production routes.
2. In sandbox, connect with code `111111`, save test card `4242 4242 4242 4242` with a future expiry, and complete Windows Hello/passkey personally. Prepare a cart and confirm its expected sandbox decline. Sandbox Purchase API intentionally does not complete live purchases.
3. Connect the production owner using their actual email verification, add their card/passkey, and verify displayed last four digits. Enable checkout only when the owner is ready for a real purchase. A live smoke purchase requires a specific item, merchant, delivery details and total approval; general installation authorization does not supply these.
4. Expand the allowlist after the owner pilot is verified. Check provider commercial limits and throughput before enabling all customers.

## Recovery

Never repeat an ambiguous money-moving request. A durable submitting marker survives process restarts and lease expiry. Every resumed approval ID is consumed before its network call, so a stale provider approval cannot replay it. Keep the purchase locked until the provider returns a matching settled order or an authoritative no-charge outcome. Escalate unresolved cases to Agentcard with conversation/order IDs, never tokens or card details. Read-only preparation can be dismissed safely.

Rotating refresh tokens are marked uncertain before exchange. A lost refresh response requires reconnection; do not reuse the previous token. If a financial operation is pending, reconcile with provider support before reconnecting. To stop new and resumed checkouts, set `AGENTCARD_CHECKOUT_ENABLED=false`; leave status and webhook handling available. Do not delete purchase state to clear uncertainty.

## Validation

Run `python -m pytest __tests__/test_agentcard_wallet.py`. The database check uses `node scripts/agentcard-db-check.mjs` with `@electric-sql/pglite` installed or `PGLITE_MODULE` pointing to its module file URL. It verifies migration replay, tenant/client isolation, lease expiry, stale writes, durable claims and service-only permissions.
