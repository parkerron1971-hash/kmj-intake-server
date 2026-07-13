# Beta gate — live-database verification

Run these against the **production** Supabase (SQL Editor → new query).
They answer the questions the code can't: what's actually applied and
whether tenant isolation is real. Nothing here writes data.

The RLS check (Query 1) is the single highest-leverage thing in the
whole beta-readiness audit — roughly half the critical/high security
findings resolve on its answer.

---

## Query 1 — Is row-level security ON for the core tables?

The core operational tables have no `ENABLE ROW LEVEL SECURITY` in any
migration; only the newer accounting/SMS tables do. The whole Chief
surface trusts RLS to isolate tenants. This tells the truth.

```sql
SELECT relname AS table_name, relrowsecurity AS rls_enabled
FROM pg_class
WHERE relname IN (
  'businesses','contacts','invoices','custom_modules','module_entries',
  'sessions','tasks','support_tickets','products','social_accounts',
  'business_profiles','practitioner_profiles','user_profiles',
  'chief_memories','chief_conversations','sms_messages','email_replies'
)
ORDER BY relrowsecurity, relname;
```

**Reading it:** every row should show `rls_enabled = true`.
- **All true** → tenant isolation is real; the Chief-surface findings drop from "open now" to "add defense-in-depth." Good.
- **Any false** → that table is cross-tenant readable/writable **right now** by anyone with the public anon key (it's in the shipped frontend bundle). Those tables need RLS enabled + an owner policy before any tester logs in. Send me the list of `false` rows.

## Query 2 — Are the policies actually owner-scoped (not "allow all")?

RLS being *on* isn't enough — a `USING (true)` policy is on-but-open.

```sql
SELECT tablename, policyname, cmd, qual
FROM pg_policies
WHERE tablename IN (
  'businesses','contacts','invoices','chief_memories','chief_conversations',
  'sms_messages','email_replies','social_accounts','business_profiles'
)
ORDER BY tablename, policyname;
```

**Reading it:** each policy's `qual` (the USING expression) should scope
to the owner — e.g. `owner_id = auth.uid()` or `business_id IN (SELECT
id FROM businesses WHERE owner_id = auth.uid())`. If any `qual` is
literally `true` (an "Allow all for anon" leftover from the base
migrations), that table is open even with RLS on. Flag those to me.

## Query 3 — Which recent feature migrations are actually applied?

The audit flagged several as "pending Kevin." A missing table doesn't
error loudly — the feature just 500s or silently no-ops. Confirm the
tables exist:

```sql
SELECT table_name,
       (to_regclass('public.'||table_name) IS NOT NULL) AS exists
FROM (VALUES
  ('invite_tokens'),          -- launch-access: invite gate (testers dead-end without it)
  ('launch_grants'),          -- launch-access: grandfathering
  ('credit_ledger'),          -- Phase C prepaid credits
  ('support_tickets'),        -- Help & Support (feedback silently lost without it)
  ('chief_scheduled_actions'),-- Chief "schedule anything"
  ('chief_activity'),         -- "while you were away" recap
  ('chief_jobs'),             -- queued desk jobs
  ('sms_messages'),           -- SMS rail
  ('sms_consents'),           -- SMS opt-in/STOP records
  ('push_subscriptions')      -- Web Push
) AS t(table_name);
```

**Reading it:** every `exists` should be `true`. Any `false` = apply
that migration before beta. `invite_tokens` false is a hard blocker —
valid testers get "invite no longer valid" and hit the waitlist wall.

## Query 4 — Confirm the insight-category fix landed

After applying `supabase/APPLY-2026-07-13-insight-category.sql`:

```sql
SELECT category, count(*)
FROM chief_memories
WHERE content LIKE '[Weekly insight %'
GROUP BY category;
```

**Reading it:** all rows under `insight`, zero under `pattern`. If any
remain `pattern`, the backfill didn't run — re-apply step 2 of the
migration.

---

## Environment checklist (Railway → Variables)

The audit found only three env vars crash on boot; the rest fail *soft*
(the feature just goes quiet), which is harder to debug. Confirm these
are set for beta:

| Var | Without it |
|-----|-----------|
| `ANTHROPIC_API_KEY` | Chief + all AI (backend no longer boot-crashes after Arc 0, but AI is dead) |
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` / `SUPABASE_ANON` | every authenticated endpoint 500s |
| `PLATFORM_OWNER_EMAIL` | must exactly match your sign-in email or you can't mint a single invite |
| `RESEND_API_KEY` | invite + all email sends fail **silently** (copy invite links manually as a stopgap) |
| `TWILIO_AUTH_TOKEN` | inbound SMS is processed **unvalidated** (signature check fails open) |
| `STRIPE_WEBHOOK_SECRET` / `STRIPE_PAYMENTS_WEBHOOK_SECRET` | payment webhooks fail open — see the Arc 2 webhook fix |
| `PLAID_ENCRYPTION_KEY` | bank-token encryption |

Plus, in the Supabase dashboard: **Auth → URL Configuration → Redirect
URLs** must include the app origin, or email-verification links bounce;
and consider custom SMTP — Supabase's built-in sender is rate-limited to
a few emails/hour, which 15 testers signing up in one evening will blow
through.
