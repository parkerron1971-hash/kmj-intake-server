# Customer-owned card connector

This is a backend-only Stripe App manifest draft for account authorization and
verified virtual-card selection. It does not issue cards, retrieve PAN/CVC, move
funds, or enable Chief checkout. It does not replace the existing Payments OAuth.

## Stripe registration and testing

Registered September 12, 2026 on independent **Solutionist Developer** account
`acct_1UEsB4ReFdFtXH2I`, with `app_distribution` active. Version 0.1.0 uploaded
successfully and is selected for external testing. This is not Marketplace
publication. The earlier connected account was ineligible for public distribution.

The managed app sandbox is `acct_1UEsXHRjhaFiRwYU`, named
`app.mysolutionist.chief-cards`. Its key and sandbox uninstall webhook secret
are stored only in Railway backend secrets. Customer test accounts use their
own sandboxes, distinct from this developer sandbox.

The dependency-free package manifest and lockfile are required by Stripe's
packager. Put `--project-name` after `apps` so the host CLI forwards it:

```powershell
npm.cmd exec --yes --package=@stripe/cli -- stripe apps upload --project-name chief-cards --live --non-interactive --wait --format json
```

The Apps plugin does not support `STRIPE_API_KEY`; do not assume host CLI
credential options are forwarded. Never paste credentials into documentation,
chat, shell history or source files.

Sources: https://docs.stripe.com/stripe-apps/create-app and
https://docs.stripe.com/stripe-apps/api-authentication/oauth .

## Deployment configuration

Apply `supabase/APPLY-2026-09-12-card-connections.sql`. Generate a separate Fernet
`CARD_CONNECTION_ENCRYPTION_KEY` in server secret storage; do not reuse the login
vault or TIN key. Do not print credentials or commit them to source control.

For each supported environment (`SANDBOX`, `TEST`, `LIVE`) set:

- `STRIPE_CARDS_<ENV>_AUTHORIZE_URL`: exact authorize endpoint from the chosen
  install link, without query parameters. External test links include a
  `/chnlink_.../` release segment. Omit for the public published endpoint. Only
  HTTPS Stripe Marketplace endpoints with the recognized path are accepted.
- `STRIPE_CARDS_<ENV>_CLIENT_ID`: the Stripe App's corresponding OAuth client ID.
- `STRIPE_CARDS_<ENV>_DEVELOPER_KEY`: the matching developer account API key.
  SANDBOX specifically uses Stripe's **managed app sandbox** key, not the test
  customer's sandbox key. Never reuse the ordinary payment connection client ID.
- `STRIPE_CARDS_<ENV>_WEBHOOK_SECRET`: the signature secret for the corresponding
  `/payments/card-connections/stripe/webhook/{sandbox|test|live}` endpoint.
  Subscribe to `account.application.deauthorized` on installing accounts.

Copy exact client IDs from the appropriate external-test/public install links.
Stripe's public links require app publication; external testing is a distinct
release channel. This version enables connection only when the environment's
client ID, correct-mode key, webhook secret and encryption key are present.

## User flow and safety

Owner initiates with danger step-up. The original app tab retains a random
completion verifier in session storage for ten minutes. Stripe sees only a
separate state. The callback verifies account identity and saves an encrypted
pending authorization. The owner returns to the original tab and clicks Finish
connection. Completion checks owner, business, mode, state, browser verifier,
expiry and connection version. Wrong browser/user or repeated completion fails.

Tokens are encrypted and bound to business, row, provider account and environment.
Refresh uses a database compare-and-swap claim. A failed/uncertain refresh or
worker crash requires reconnecting; it cannot blindly replay a rotated token.
Disconnect erases access tokens, card selection and pending authorization and
increments the generation so in-flight refresh/selection cannot restore access.
It does not cancel customer cards or uninstall the app in Stripe; the UI says so.
Uninstall events revoke local access. A late uninstall conservatively disconnects.

Card listing is paginated and allowlists display metadata. Selection retrieves
the card again from the connected account and rejects physical, inactive,
expired, wrong-mode and unknown cards. No endpoint accepts manual PAN/CVC.
`purchasing_enabled` is always false. A selection records a preference, not a
spending approval or a promise of current account eligibility. Future purchasing
must recheck provider state, owner approval and the exact errand immediately
before use; it cannot rely on stored metadata.

## Activation acceptance checks

1. Register an eligible Stripe App, validate this manifest and external-test flow.
2. Confirm independent account Issuing access, app permissions, fees, and allowed
   future agent checkout/card-data handling with Stripe.
3. Rehearse actual OAuth in a customer sandbox; verify account ID and mode without
   exposing tokens. Test refresh, uninstall, selection and disconnect end to end.
4. Complete Marketplace review before enabling public live installation.
5. Keep Chief purchasing disabled until its separate payment integration passes
   issuer and guarded-browser tests. No live purchases are authorized by setup.
