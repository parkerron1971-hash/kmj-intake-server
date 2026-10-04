# Acuity migration — first release under review

Status: backend draft; not deployed, schema not applied, customer UI not built.

Import belongs to the shared platform and is available across business types.
People-only imports do not depend on the business's scheduling complexity.
The Acuity appointment adapter currently supports one provider with individual
appointments. It does not yet establish Acuity feature parity or readiness for
every industry's full operating workflow.

## Supported workflow

The owner uploads client and/or appointment CSV exports, chooses the date order
and IANA time zone, maps Acuity services to active Solutionist offerings, and
confirms canceled appointments were excluded. Each file is limited to 500 rows
and 2 MB. A client email is required for matching; ambiguous identities, missing
times, daylight-saving ambiguity, overlaps and unsupported dependencies block
the review. Unknown source columns are retained.

The preview checks current business records and saves an immutable server-owned
plan for 24 hours. It does not create clients or appointments. Commit uses one
transaction, verifies ownership again, and creates contacts, booking entries,
session mirrors and a durable receipt. Repeating a commit returns the receipt;
re-exporting the same source IDs does not duplicate appointments. Changed or
deleted imported appointments require review rather than being overwritten.

Imported financial values remain Acuity source records. The import creates no
charges, invoices, payment timestamps, subscriptions, or marketing consent.
Historical dates do not establish attendance. Import code sends no messages.
Session reminders are paused until the owner confirms the booking flow is tested
and duplicate Acuity reminders are disabled. Existing SMS consent checks still
apply after reminders are enabled.

## API

All routes require a verified JWT and ownership of the business UUID.

| Route under `/acuity-migration/{business}` | Purpose |
| --- | --- |
| `GET /config` | Active service catalog, saved time zone, file limits |
| `POST /inspect` | File inventory without storing a plan |
| `POST /preview` | Validate, match and save a ready review |
| `POST /commit` | Import the reviewed batch atomically |
| `GET /receipts` | Recover the latest completed import receipts |
| `POST /reminders` | Enable or pause reminders for a completed batch |

## Verification and release gates

199 focused migration, booking, series, confirmation and SMS tests pass. A live
database rehearsal at 2026-10-04 10:52 UTC applied the schema and imported a test
fixture entirely inside a rolled-back transaction. It verified schema
compatibility, owner isolation, retry receipts, deduplication, reminder cutover,
payment provenance, overlap rejection, partial-failure rollback and browser-role
denial. No fixture contacts remained. Reproduce with
`python scripts/verify_acuity_migration.py` using the existing management credential.

Do not merge or apply the schema until the review UI is connected and a complete
booking/payment/reschedule/cancel rehearsal passes. Also review concurrent writes
from standalone sessions, source/customer identity conflicts, and retention of
expired prepared plans. The current database guard serializes booking-entry
writes and imports; it does not yet serialize standalone session writes.

UI design approved by Kevin on 2026-10-04; implementation remains next:
https://p.superdesign.dev/draft/ce180ae5-1598-4c3e-bc87-ccfb5f00d7fb

The next UI work belongs inside the existing Bring a file over flow, using the
app theme and terminology. Reset files/previews when switching businesses and
invalidate a review whenever its input changes. Display unsupported dependencies,
row issues, new/existing counts, source payment labels, the receipt and explicit
reminder cutover. Apply `supabase/APPLY-2026-10-04-acuity-migration.sql` after merge
as part of the coordinated release, before opening the import flow.

## Vertical product direction

Kevin proposed separate Solutionist experiences for churches, barbers and lawyers:
industry websites, branded login experiences, onboarding and packages. The
proposed architecture is one maintained platform with configurable vertical
presets, not separate forks. Business membership and permissions continue to
control data access; a vertical theme must never become an authorization boundary.

Each preset should declare vocabulary, brand, onboarding, module defaults,
workflows, Chief context and connector/migration readiness. Paid packages should
declare entitlements independently of the vertical. Chief actions remain bounded
by the business's enabled capabilities, permissions and configured integrations.
These are design proposals, not implemented product claims.

Kevin clarified that import must serve every vertical, including churches,
barbers and lawyers. Scope readiness by record type and source capability, never
by the business label. Use the vertical's terminology in the UI, while preserving
canonical contacts/appointments underneath. Map other records through the
existing structure importer where supported; matters, donations, staff calendars
and financial balances each need explicit destination and validation rules.

Chief-assisted import is proposed, not yet implemented. After Solutionist login,
Chief should identify the source, open file selection or the source's authorized
connection, prepare a review through the same migration service, explain issues,
and execute the exact reviewed batch after owner approval. Acuity OAuth can supply
the connected-account path without putting source passwords in Chief chat.
Login alone does not authorize a source connection or transfer. Preserve tenant
scoping, source permissions, duplicate checks, durable receipts and separate
reminder cutover. Never ask a model to fabricate missing operational records.

Deliver each vertical when its core workflows are proven. Church/member and
ministry workflows, barber/client and appointment workflows, and legal/client and
matter workflows need different acceptance criteria. Staff calendars, classes,
package redemption, gift balances, recurring memberships, Acuity forms and
automations remain outside this migration release. Brand pages alone do not
establish readiness for those needs.
