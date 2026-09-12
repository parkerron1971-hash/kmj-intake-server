# Chief's computer — backend arc

PR1 implements the database foundation and server-side encryption primitives.
PR2 adds the browser controller, independently testable before any route or job
can start an errand. The existing `browser_hand.py` remains operational until PR6.
Sections 7 and 9 of `CHIEF_COMPUTER_ARC_SPEC.md` in the frontend repo remain the
integration contract and delivery order.

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

PR1 merged as #935 and deployed successfully on 2026-09-12 (UTC), commit
`e13dd6c9c4a8f84dec2e67775abd0fa68a730e33`. The production migration is applied;
the transactional role probe passed, denying both authenticated and anonymous
vault SELECT. All three tables respond through the service API and health is 200.
The vault key has not yet been configured; do so before enabling Secure Entry.
Do not deploy while `chief_jobs` contains queued/running paid work.

## PR2 controller

`browser_controller.py` implements the 27 default members of
`browser_toolset_20260801`, with the four optional members disabled and refused.
Its callbacks are mandatory: the driver checks current authority before every
member, creates a Secure Entry hold, and records sanitized private frames.
No HTTP endpoint or model can invoke `fill_secret` directly. It is a same-thread
primitive for an authenticated mailbox command, with an expiring, exact-host,
live-element-bound hold. Missing or ambiguous field mappings fail closed.

The Chromium backend pins each approved host to public DNS addresses at launch,
blocks other network requests, denies Amazon and all non-HTTPS navigation, closes
popups, refuses uploads/downloads, blocks service workers and WebSockets, and
does not pass server keys into the child process. Approved hosts are exact DNS
names, including `www` or payment/CDN origins when needed. There is no automatic
expansion of an allowlist based on a page's requests. A site needing additional
origins requires a revised plan. Browser shortcuts that access clipboard,
developer tools, address bars or native dialogs are refused.

References are server-side handles, scoped to a tab and invalidated on navigation,
new reads and material changes to the target. Page reads return rendered text,
not HTML source or field values. Known filled values (including card last four)
are scrubbed from text, tab titles and URL paths; query strings and fragments are
always omitted. Screenshot output is 1280x800 PNG; private recorded frames are
JPEG quality 55 under `{business}/errand/{id}/{n:03d}.jpg` in `proposals`.

**Privacy limitation and deliberate v1 behavior:** before filling, all editable
fields are masked navy. After any Secure Entry fill, screenshots for that run
use a full navy privacy curtain. A site can render a secret in canvas, CSS or
an image, so field rectangles alone cannot guarantee screenshot privacy. Chief
continues from scrubbed DOM text. This means the user cannot watch checkout
pixels after a secret is entered. Do not describe it as unrestricted live viewing
or claim arbitrary transformed/encoded secret echoes are covered by text matching.
Never use raw `page.pdf()` or raw screenshots for receipts.

Rehearsal candidate: Office Depot guest checkout, one box of paper clips (item
222056). Its official checkout guide supports guest orders. This is a proposal,
not an approved purchase or account; final item, shipping/tax total, and owner
presence remain prerequisites. A guest purchase does not exercise saved-login
reuse, which needs a separate account rehearsal.

## Verification

PR3 adds the section 7 HTTP routes and `chief_jobs` errand kind. Apply
`supabase/APPLY-2026-09-12-chief-computer-runtime.sql` after merge. Browser execution
stays off behind `ERRANDS_ENABLED=off` until PR4. Planning and metadata can be
used independently. POST planning includes `business_id`; an email-only supplier
returns the existing purchase-order action with `errand:null, door:"email"`.

Approvals are one service-only database transaction with job creation. Other
enqueue paths cannot start an errand. Plans also serialize per business to refuse
overlapping same-day item orders. Event numbers and state changes share row locks;
old statuses or hold IDs cannot release newer holds. Pause preserves pending
Secure Entry/checkout approval. Stop and saved-login revoke require the appropriate
role, with no step-up. Settings writes require owner danger step-up and preserve
unrelated settings. Metadata reads use named columns; only the future worker can
read a saved cipher for an authenticated fill. Secure Entry has bounded raw JSON
parsing, six attempts/minute per user/errand/process, no body-bearing validation
errors, and whole-event log/Sentry suppression. Worker mailboxes are process-local;
a missing worker never silently launches a replacement.

The production deployment currently uses one replica. A future multi-replica
upgrade needs owner-worker routing for mailboxes and a shared Secure Entry rate
limiter. Restart reconciliation marks errands interrupted without retrying or
claiming the supplier did not receive an order.

Existing auth limitation: `/auth/step-up` currently issues danger tokens only to
business owners. Managers may plan, stop, fill transient values and approve priced
errands within their limit; an owner must handle cases requiring a new danger
token (over-limit/unpriced approval and saving/reusing logins). This arc does not
broaden the existing danger-token gate used by other destructive operations.

```text
python -m pytest __tests__/test_secret_vault.py __tests__/test_export_import.py -q
python -m pytest __tests__/test_browser_controller.py -q
python scripts/chief_computer_sabotage.py
node scripts/chief-computer-db-check.mjs
node scripts/chief-computer-runtime-db-check.mjs
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

2. Controller implemented; 116 focused controller/vault/legacy-hand tests passed
   locally. All three independent sabotage mutations were detected. CI installs
   Chromium and runs the fixture suite plus sabotage checks with no service keys.
3. Errands, endpoints, holds, settings and job interruption handling implemented.
   This is the frontend integration milestone; announce when PR3 merges.
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
