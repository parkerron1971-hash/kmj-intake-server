# Chief's computer — backend arc

PR1 implements the database foundation and server-side encryption primitives.
It extends the existing browser hand; `browser_hand.py` and its credential refusal
remain unchanged. There are no new routes, model tools, jobs, or browser actions
in this PR. Sections 7 and 9 of `CHIEF_COMPUTER_ARC_SPEC.md` in the frontend repo
remain the integration contract and delivery order.

## PR1 implementation

- `chief_errands`: planned errands, approval records, holds, receipts and budgets.
- `chief_errand_events`: ordered per-errand history. An internal `business_id`
  supports export/erasure and a composite foreign key prevents attaching an event
  to another business's errand. The external section 7 Event shape is unchanged.
- `business_secrets`: service-role-only encrypted logins. RLS has zero policies;
  anonymous/authenticated/PUBLIC table privileges are revoked.
- Owners and active business seats can SELECT their errand history through the
  existing definer helpers. All browser writes are denied. HTTP authorization,
  manager roles and state transitions arrive in PR3.
- Vault ciphertext is excluded from account exports and cascades on business
  deletion. Errand/event history is exported, but not imported: an uploaded
  archive must never resurrect execution authority or private frame paths.

`secret_vault.encrypt(fields, business_id=..., secret_id=..., host=..., kind='login')`
returns randomized Fernet ciphertext. Allocate the secret UUID before encryption.
The encrypted envelope authenticates version, business, row ID, exact normalized
host and kind. Decrypt requires the same context; tampering, key replacement or
cross-tenant/host/row substitution fails with a generic 500 and no value in errors.
Passwords retain whitespace and Unicode. Fields and byte size are bounded.

`METADATA_COLUMNS`, `FILL_COLUMNS`, and `secret_metadata()` define separate read
surfaces. Never select `*` from the vault. The future secret endpoint may return
only `{ok: true}`; `decrypt()` is an internal controller primitive, not an API.
No production decrypt caller exists yet. The future fill path must independently
validate actor, active row, exact live hold/host, step-up and revocation immediately
before decrypting. Encryption does not establish any of those permissions.
Keep decrypted values scoped to the fill operation; Python strings do not provide
a guarantee of physical memory zeroization.

## Card decision and required correction

PR1 allows only login persistence, enforced both in Python and the database.
Cards, arbitrary custom values, session snapshots, OTPs and extra login fields
are rejected. These other storage kinds need a reviewed follow-up validator and
migration. Secure Entry for transient values belongs to PR3/PR4.

The spec's example includes `cvc` in the encrypted saved-card fields. Do not
implement reusable CVC storage: PCI SSC prohibits retaining it after authorization,
including encrypted retention. See [PCI SSC FAQ 1319](https://www.pcisecuritystandards.org/faqs/1319/).
Likewise, OTPs must remain transient. Saved-card support remains disabled pending
the owner's section 11 decision. PR3 must use `save_cards: false` as the default;
an unavailable save operation must fail explicitly, not silently claim to save.
The existing `SecretMeta`/Secure Entry field names are not changed by PR1.

## Configuration and migration

1. Review and merge PR1.
2. Apply `supabase/APPLY-2026-09-12-chief-computer.sql` after merge. Prerequisites
   are `businesses`, `auth.uid()`, `is_business_owner(uuid)` and
   `is_business_member(uuid)`, plus the usual Supabase roles. The migration is
   additive and repeatable. It does not modify business settings or create data.
3. Generate an independent Fernet key in a trusted server-secret workflow and
   configure `VAULT_ENCRYPTION_KEY` only in Railway secret storage before the
   future Secure Entry code is enabled. Never commit or log it. No fallback to
   another credential/key is permitted. Missing/invalid key returns 500 when
   encryption/decryption is called; unrelated service startup remains unaffected.
4. Preserve the key in approved secret backup storage. Replacing it without a
   separately reviewed re-encryption process makes existing logins unreadable.
5. Run the live rollback probe in `supabase/VERIFY-chief-computer-access.sql` and
   record its result in the migration ledger. A local test does not prove a
   production migration was applied.

No production migration or key configuration has been performed for this arc.
Do not deploy while `chief_jobs` contains queued/running paid work.

## Verification

```text
python -m pytest __tests__/test_secret_vault.py __tests__/test_export_import.py -q
node scripts/chief-computer-db-check.mjs
```

The SQL check uses PGlite (`PGLITE_MODULE` can identify its module; CI installs
the pinned dependency used by the existing database checks). It executes the
real migration repeatedly and rolls back fixture rows. It tests owner/active-seat
reads, revoked-seat and foreign-tenant isolation, vault SELECT denial, the RLS
backstop even after an accidental SELECT grant, browser write denial, duplicate
plans/events, event tenant mismatch, invalid budgets/statuses, card persistence
rejection and deletion cascades. The Python suite checks key failure, encryption
round-trip, envelope tampering/substitution, shape and size limits, metadata
redaction, and export/import rules. CI runs both suites.

## Next PRs and integration notes

2. Build `browser_controller.py` on the existing browser hand and the verified
   Anthropic browser toolset contract. Preserve the section 7 wire shapes.
3. Add errands, endpoints, holds, settings and job interruption handling. This is
   the frontend integration milestone; notify the frontend owner when it merges.
4. Add the driver and receipts.
5. Wire Chief's actions, prompt, policy, ledger, inventory and planned cancellation.
6. Fold the old browser hand into the errand path.

Resolve these spec inconsistencies in their owning PRs and record any wire change
in the source spec's Contract changes section:

- Section 7 is authoritative for unpriced step-up; section 5.2 omits that guard.
- A browser crash cannot prove an order was not placed. No automatic purchase
  retry; interrupted receipts must state uncertainty and require reconciliation.
  The schema follows the specified partial idempotency index; removing that index
  block alone must never authorize rerunning a purchase.
- A raw page PDF bypasses screenshot masking. The receipt writer must sanitize
  the PDF itself or build it from already-masked pixels before storage.
- Hold timeout and total errand budget need one explicit clock policy; approval
  cannot silently extend an expired job or reuse an obsolete field reference.
