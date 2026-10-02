# Ministry readiness fixes — implementation and rollout

Status: code merged and production migration applied 2026-09-29 03:29 UTC. Schema, privacy permissions, archival integrity, and live API checks passed. See [production verification](MINISTRY_MIGRATION_VERIFICATION.md).

## Audit findings addressed

| Finding | Change |
| --- | --- |
| M1: ordinary seats can read giving | Owner/admin/active-accountant gates on giving, donor exports, ministry reports, GL and bank reads; restrictive database policies on financial records and gift activity. Chief statement actions require an authenticated finance actor. Failed frontend role lookup grants no finance role. |
| M2: paid service invoices counted as gifts | Explicit `is_gift` classification; shared gift reader feeds statements, donor reports and ministry desk totals. Online gifts retain their fund and payment date. Migration backfills the established `GIVE-` records only. |
| M3: private prayer enters marketing/AI | Private intake returns before contact creation, scoring, events, module routing or drafting. Service-only care storage with an owner-authorized inbox in Forms. Prayer forms retain their private setting when renamed. Migration preserves identifiable historical contact/event/draft copies in private storage before redaction. |
| M4: same-name donors merged | Group by contact ID; anonymous gifts remain unattributed. |
| M5: wrong ministry templates | Canonical ministry resolves to church visitor, prayer, event and volunteer templates. |
| M6: no manual giving entry | Ministry Bookkeeping opens Giving. Record cash/check/bank/other gifts with giver, date, amount and fund. Idempotent request IDs prevent duplicate retries. Corrections/refunds require a reason and current revision; database retains previous/current values. |
| M7: failed or truncated reads resemble zero giving | Gift reads page until empty, fail explicitly on errors/nonadvancing pages, and use an exclusive next-year boundary. UI displays a retryable error without a zero-giving summary. |
| M8: concurrent signups overwritten | Public RSVP preserves upstream registration-key deduplication, retries revision-based compare-and-swap updates, and rechecks capacity. Roster and generic roster editors reject stale writes. Database revisions advance on every update. |

## Validation

- 136 backend tests passed on the current release branches. Includes 5,201 gifts under a 127-row server cap; duplicate donor names; mixed gifts/service revenue; denied financial roles; private-intake isolation; simultaneous public signups with capacity 1 and 2; manual-gift retries and corrections.
- TypeScript typecheck passed.
- PGlite/PostgreSQL migration checks passed: repeat application, gift backfill, historical care archival, role-based visibility, gift correction audit, and stale roster update rejection.
- Ministry/church template parity check passed.
- Actual GivingLedgerPanel tested in a local browser with synthetic responses: entry, correction/refund, updated totals, and service-error behavior. Desktop layout inspected.
- Both repositories pass `git diff --check`.

Evidence: `output/ministry-readiness-verification/`.

Private care records and gift correction history are included in owner-only account exports and account erasure. Generic imports explicitly skip these archives because their embedded identifiers and audit evidence cannot be safely recreated in a new business.

## Rollout order

1. Use a coordinated intake/giving maintenance window and retain a database backup. Inspect existing `GIVE-` invoice numbers for duplicates before the new unique index; resolve any duplicates by reviewing the source payment, not by deleting financial history blindly.
2. Apply `supabase/APPLY-2026-09-29-ministry-readiness.sql` (identical copy in the backend repository).
3. Release the backend and frontend together. Reapply the idempotent migration after cutover if the old backend accepted intake/gifts during deployment.
4. Smoke-test with designated test users: owner/admin/accountant can use Giving; ordinary ministry seats cannot read financial records; owner can review private requests; one synthetic manual gift and concurrent event signups behave correctly.

Ambiguous historical payments without the established gift marker need operator classification before issuing statements. The migration does not guess from invoice category. Historical private copies outside the identified contact metadata, intake events and intake drafts (for example previously sent emails or unrelated manually created notes/modules) require a separate review. The change cannot retract previously transmitted data.

Do not roll back by reopening private-table access or restoring sensitive text to ordinary CRM records. Keep the privacy migration in place if an application rollback is needed.
