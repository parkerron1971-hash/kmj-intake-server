# Sending with Moov: a church pays its 1099 people from its own bank

Kevin, 2026-11-27 (Money desk, M-6 step 3). A church can pay guest speakers,
musicians, contractors and reimbursements through Moov. The money comes from
**the church's own bank**, so the church is the payer and Solutionist never is.
It's off by default, and each church opts in.

**This build runs in test mode only.** `moov_client.LIVE_ALLOWED = False`, so
`MOOV_MODE=live` is refused in code, not just left unset. Real money needs a
reviewed change (see "Go live" below).

Code: `moov_client.py` (the one door to Moov), `moov_payouts.py` (routes and
rules). Migration: `supabase/APPLY-2026-11-27-moov-payouts.sql`.
Tests: `__tests__/test_moov_payouts.py` (a fake Moov, no network).

## How it works

| Step | What happens | Who |
|---|---|---|
| Switch | `MOOV_PAYOUTS` = `off` (default), `owner` (platform owner's churches) or `on` | Kevin |
| Opt in | The church turns on "Send with Moov" | Owner |
| Church onboarding | Moov's hosted form: the church proves who it is (KYB) and links its bank (micro-deposits are free) | Owner |
| Payee onboarding | The person gets a Moov link (by email if they have one) and adds their bank or debit card | Owner or Admin |
| W-9 | Moov's form checks who they are. The church still keeps the W-9 in the app (Reports › 1099s, `PUT /contractors/{id}/tax-profile`). This build reads no TIN back from Moov | Owner |
| Quote | Fees per speed, which speeds Moov offers for this person, today's total against the caps | Owner, Admin, accountant |
| Send | Next-day ACH by default; same-day or instant can be chosen, with the fee shown first. Requires a password step-up for this church | Owner or Admin |
| Book it | A bill exists as soon as the payout is sent: either the bill that was picked (marked `scheduled`) or a new one. Moov's `completed` marks it **paid**, with `paid_via='moov'`, `is_1099_eligible` from the contractor, and the contractor linked. The 1099 summary counts it once | automatic |
| Returns | If a payout fails before it lands, the bill goes back (cancelled if this payout made it, otherwise its earlier status). A return after it landed reopens the bill the same way. If the bill's month is closed, the bill is left alone and the payout gets `needs_review` | automatic |

What we store: Moov's account ids, the invite code, statuses, a "bank ready"
flag, and the church's caps. **Never a bank or card number.**

### Safety

- **Solutionist never funds a transfer.** The source is the church's own
  `ach-debit-fund` payment method. It is checked twice: once against the church
  row for this business, then again in `moov_client.create_transfer` against
  Moov's own list of that account's methods. The partner account can never be
  a source, and it can't be claimed as a church or a payee.
- **One Moov account, one row.** A unique index stops a church from claiming
  another church's Moov account.
- **Once.** The client sends an `idempotency_key`. It is unique on the payout,
  and it is the `X-Idempotency-Key` Moov receives. Sending the same request
  again returns the same payout. If Moov's answer couldn't be read, the payout
  stays `created` and the same request can be re-sent safely. A bill can have
  only one payout in flight or paid at a time (a unique index).
- **Caps.** Each church has a per-payment cap (default $1,000) and a per-day
  cap (default $2,500). The owner can change them, up to the platform ceilings
  `MOOV_MAX_PAYMENT_USD` (5,000) and `MOOV_MAX_DAILY_USD` (10,000).
- **Gates.** `church_money_gate` has a new part, `send`. Seeing payouts:
  owner, Admin or accountant. Sending: owner or Admin, and the giving tick adds
  nobody. The church's own account, opt-in and caps are `setup`, the owner
  only. Sending also requires `financial_policy.require_operational_write`, the
  `contractor_payments` feature, and the new step-up scope `pay`
  (`ledger_unlock.SCOPE_PAY`). An Admin can confirm `pay`; `danger` remains
  the owner's alone.
- **Webhook** (`POST /moov/webhook`). Moov signs `timestamp|nonce|webhookID`
  with HMAC-SHA512 (hex). **It does not sign the body.** So a verified
  delivery is treated only as "go and look": every status is read back from
  Moov's API before anything changes. With no `MOOV_WEBHOOK_SECRET`, events are
  dropped (webhook_guard). A bad or stale signature (more than 10 minutes old)
  gets a 400. Event ids are deduplicated in `moov_webhook_events`.
- **Audit.** Every opt-in, invite, cap change, send and status change writes an
  `audit_log` row. Keys, the Authorization header, request bodies and Moov's
  error bodies are never logged, and logged paths have their ids hidden.

## The API contract (for the "Pay people" screen)

All routes need a signed-in user. Each body carries `business_id`; reads
pass `?biz=`. Amounts are dollars with at most two decimals.

| Method and path | Body / query | Answer |
|---|---|---|
| `GET /moov/status?biz=` | | `{switched_on}`. When `false`, draw nothing. When `true`: `mode`, `ready`, `reason`, `church{opted_in,status,bank_ready,has_moov_account,per_payment_cap,daily_cap}`, `platform_caps`, `speeds[{speed,words,fee,default}]`, `may_send`, `may_set_up` |
| `POST /moov/church/opt-in` | `{business_id, on}` | `{church}`. Owner only |
| `POST /moov/church/onboarding` | `{business_id}` | `{link}`: open Moov's form. Or `{already:true}` |
| `POST /moov/church/refresh` | `{business_id}` | `{church}`. Call after the owner returns (`?moov_onboarding=church`) |
| `PATCH /moov/church/caps` | `{business_id, per_payment_cap, daily_cap}` | `{church}`. Owner only |
| `POST /moov/payees/{contractor_id}/invite` | `{business_id}` | `{link, email_sent, w9_on_file, w9_words}` |
| `POST /moov/payees/{contractor_id}/refresh` | `{business_id}` | `{payee{status,bank_ready}}` |
| `POST /moov/quote` | `{business_id, contractor_id, amount}` | `{amount, sent_today, per_payment_cap, daily_cap, church_bank_ok, speeds[{speed,words,fee,available}]}` |
| `POST /moov/pay` | `{business_id, contractor_id, amount, idempotency_key, speed?='next_day', bill_id?, description?, category?}` + header `X-Ledger-Unlock` (step-up scope `pay`) | `{ok, payout, note?}`. A 403 with `detail.code == "ledger_locked"` and `scope == "pay"` means: ask for the password (`POST /auth/step-up {business_id, password, scope:"pay"}`), then retry with the **same** `idempotency_key` |
| `GET /moov/payouts?biz=` | | `{payouts[]}` |
| `POST /moov/payouts/{id}/refresh` | `{business_id}` | `{payout}` |

A `payout` is `{id, contractor_id, bill_id, amount, speed, speed_words,
fee_estimate, status, status_words, return_code, failure_reason,
needs_review, description, mode, created_at, completed_at}`.

The statuses are Moov's: `created`, `queued`, `pending`, `completed`,
`failed`, `canceled`, `reversed`. Show `status_words` as they are.

Refusals come back as plain sentences in `detail`, ready to show:
- 409: not opted in, the church isn't ready, the payee isn't ready, the speed
  isn't available, over a cap, a bill amount mismatch, the bill already has a
  payment on its way
- 503: not set up, or a read failed

The frontend generates the `idempotency_key` once per press of Send (a
UUID), and reuses it for retries of that same press.

## Go live (what Kevin does)

1. **Create the Moov account** at moov.io as Solutionist, the partner or
   facilitator. Sign Moov's agreement and get through their review of
   Solutionist. Confirm with Moov:
   - that a church (its own business account) can be the **source** of an
     ACH debit paying another account's bank (`ach-debit-fund` →
     `ach-credit-standard`), with the church as the payer of record;
   - which capabilities the church needs (this build asks
     `transfers, send-funds.ach, wallet.balance`; change with
     `MOOV_CHURCH_CAPABILITIES`);
   - whether hosted onboarding works for an **individual** payee (it's in the
     schema; the guide only talks about businesses);
   - whether they offer 1099 filing (no product is documented; the app's own
     1099 drafts cover it today).
2. **Test mode first.** Create a test-mode API key and set these on BOTH
   Railway services: `MOOV_PUBLIC_KEY`, `MOOV_PRIVATE_KEY`,
   `MOOV_PARTNER_ACCOUNT_ID`, `MOOV_FEE_PLAN_CODES` (from the fee plan
   endpoint or the Dashboard), `MOOV_WEBHOOK_SECRET`, and `MOOV_PAYOUTS=owner`.
3. **The webhook.** In Moov Dashboard › Developers › Webhooks, add
   `https://kmj-intake-server-production.up.railway.app/moov/webhook`
   subscribed to `transfer.*`, `account.*`, `capability.*`, `bankAccount.*`
   and `paymentMethod.*`. Copy its signing secret into `MOOV_WEBHOOK_SECRET`.
   Each mode has its own secret.
4. **Apply the migration** `supabase/APPLY-2026-11-27-moov-payouts.sql`, then
   run its after-check.
5. **Run one sandbox payout** through Love City: opt in, finish Moov's form
   (test routing number 322271627, micro-deposits `[0,0]`), invite a test
   payee, send $1. If Moov rejects the amount shape, set
   `MOOV_AMOUNT_SHAPE=cents` (the docs disagree with themselves). Also try
   $55.03, which Moov's test mode returns as R03, and watch the bill reopen.
6. **Live.** Once the sandbox run is clean, open a small PR that sets
   `LIVE_ALLOWED = True`. Review it, then set `MOOV_MODE=live` and the live
   keys and webhook secret. Switch `MOOV_PAYOUTS=on` on a Thursday with a
   What's New entry.

## Pricing to weigh

Read from moov.io/pricing, 2026-11-27:

- **$500 a month minimum** on standard pricing, with no flat subscription.
  That is the real cost of turning this on. At 25¢ per next-day payout, the
  minimum covers 2,000 payouts a month. For the first churches it's a fixed
  cost, not a per-use one.
- **KYB: $4.50 per business.** That's each church, and possibly each
  sole-proprietor payee onboarded as a business.
- **Per payout:** next-day ACH 25¢, same-day ACH 40¢, RTP or instant
  push-to-card 0.95% (50¢ minimum, $5 cap). The fee shows before sending. This
  build does **not** charge it back to the church. Charging it would need
  Moov's `facilitatorFee` on the transfer, a pricing decision.
- **Bank checks:** micro-deposits are free; instant verification is 75¢.
- **Wallet:** 50¢ per active month. This build sends bank to bank and doesn't
  use a church wallet.
- **Test mode is free.**
- **Options:** absorb the fees in a church plan tier; pass the per-payout fee
  through `facilitatorFee`; or offer it as a paid add-on. The Android app must
  not sell it if it is priced as a Solutionist product (desk rule).

## Left for later

- No screen yet. The "Pay people" rework (W5) will call this contract.
- No sweep for payouts stuck in `pending`. The webhook and the Refresh button
  cover it; a daily `refresh_payout` pass over `pending` rows older than
  5 days would be the backstop.
- A Moov debit also shows up in the church's bank feed. Match it to the bill
  (Bills › match, `bill_payments`) as with any bill paid from the bank, so the
  cash leaves once. Matching automatically on Moov's trace number is a
  follow-up.
- Instant payouts usually need the church's Moov wallet (bank → wallet → RTP).
  This build offers instant only when Moov lists an instant route from the
  church's bank method. Otherwise it refuses with plain words.
