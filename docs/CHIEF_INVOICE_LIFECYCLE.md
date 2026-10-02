# Chief invoice lifecycle

Chief accepts `delete_invoice`, `void_invoice`, `archive_invoice`, and `restore_invoice` alongside its existing invoice actions. Resolve an exact invoice UUID or exact invoice number within the authorized business. Ambiguous numbers, missing targets, and generic `latest` identifiers are rejected for these actions.

Deletion is limited to unsent, unpaid drafts. Voiding preserves the row as `cancelled`, pauses a recurring template, and never refunds or deletes payment/ledger records. Paid invoices cannot be voided. Archive/restore only change `archived_at`; they do not stop collections, change status, or remove paid revenue from reports. The frontend adds Archived and Voided filters.

Provider protection: when an invoice carries a Stripe link, verify its connected account and invoice/business metadata, disable every link owned by that invoice, and expire open checkout sessions. A completed checkout blocks the local void/delete. Shared, unverified, or disconnected links require provider cleanup first. Stripe-hosted invoice objects are rejected rather than falsely voided locally. Provider failures and conditional-write conflicts are reported as failures, with any possible partial link deactivation disclosed. Existing `send_invoice` rejects voided rows.

Actions use request-scoped Supabase credentials and business filters on reads and writes. Status, timestamp, and paid/sent checks guard concurrent edits. The existing Chief execution pipeline supplies audit results and data-refresh notifications. Delete and void are class C; archive/restore are reversible class A.

`supabase/APPLY-2026-09-09-invoice-archive.sql` was applied to the connected production project on 2026-09-09. Verified nullable `timestamptz`; no existing invoice values were changed. Apply this additive migration before releasing the frontend/backend elsewhere.

Validation: 67 passing tests, four pre-existing skipped tests across invoice lifecycle, action registry, prompt shape, action remapping, and invoice checkout; frontend typecheck and production build passed. Provider tests use fakes, never actual payments. No customer invoices were modified during verification.

Provider references: [payment links](https://docs.stripe.com/api/payment-link/update), [checkout sessions](https://docs.stripe.com/api/checkout/sessions/list), [expiration](https://docs.stripe.com/api/checkout/sessions/expire).
