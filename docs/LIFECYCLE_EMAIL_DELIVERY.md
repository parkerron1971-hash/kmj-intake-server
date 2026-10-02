# Signup and lifecycle email delivery

Apply supabase/APPLY-2026-09-29-lifecycle-delivery.sql before deploying this backend. It adds private service-role-only delivery and signup-intent tables plus atomic claim/finish/retry functions. It is idempotent and does not enroll historical accounts.

The first-business welcome still sends immediately. Missing welcome stamps are recovered every 15 minutes for businesses created within 72 hours. Trial notices run hourly at :30; first-week messages at :45. First-week encouragement stops when enforced billing access is locked or in payment grace. Existing business send stamps prevent resending historical messages.

New password signups carry solutionist_signup_intent=business in user metadata. Entering business onboarding also calls POST /access/onboarding-started with the authenticated identity, covering Google accounts. Enrollment is insert-once and never resets the clock. Only confirmed accounts expressing business intent are considered. Owning a business, a staff/collaborator record, invitation, grandfathered status, deletion, anonymous identity, or active ban excludes the account. No student-only accounts are enrolled.

Setup reminders run hourly at :05. The first is eligible at ages 1–3 days; the final at ages 3–7 days. At most one of each and at least 24 hours between successful reminders. Eligibility is checked again immediately before sending. No reminder is sent to an unverified email address.

Each lifecycle send obtains an atomic ten-minute lease and freezes its recipient and content. Resend receives a stable Idempotency-Key. Acknowledged sends are recorded before updating legacy business stamps. A failed stamp can therefore be repaired without a duplicate email. Pending sends back off 15 minutes. Recipient changes hold an existing frozen send. Unresolved sends enter review after 23 hours, before Resend's 24-hour idempotency guarantee expires. These require operator investigation; do not clear the ledger and blindly resend. See https://resend.com/docs/dashboard/emails/idempotency-keys.

Read-only monitoring:

```sql
select state, count(*) from public.lifecycle_email_deliveries group by state;
select delivery_key, state, attempts, first_attempt_at, sent_at, last_error
from public.lifecycle_email_deliveries where state <> 'sent' order by first_attempt_at;
select count(*) from public.lifecycle_signup_candidates();
```

LIFECYCLE_EMAILS=off stops lifecycle sending. Trial mail also respects BILLING_ENFORCE. The shared email sender continues to enforce suppressions. Sender: The Solutionist System <noreply@mysolutionist.app>; reply-to uses the public contact helper (production info@mysolutionist.app).

The canonical app is https://system.mysolutionist.app. APP_BASE_URL overrides it for alternate environments; the retired Vercel alias is normalized to the branded origin. Lifecycle and inquiry copy use ordinary sentences without em/en dash separators. The live Supabase authentication templates were inspected and already satisfy that punctuation requirement.

Validation: focused Python email tests plus scripts/lifecycle-email-db-check.mjs against PGlite (also included in CI). No real email is sent by these tests.

Rollback: set LIFECYCLE_EMAILS=off before reverting the application release. Keep the delivery ledger to preserve deduplication history. Do not drop these tables while any deployed version calls them.
