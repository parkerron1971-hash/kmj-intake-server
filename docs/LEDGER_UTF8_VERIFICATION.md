# Ledger UTF-8 correction

Gift corrections append a newline to invoice notes. The legacy audit hash cast JSON text to bytea, interpreting JSON escapes and raising SQLSTATE 22P02. The fail-closed audit trigger correctly rejected the entire correction.

The migration keeps legacy canonicalization and hashes unchanged. Existing rows use hash_version 1; all new tenant ledger entries force version 2, hashing a fixed JSON array as explicit UTF-8. Verification dispatches by row version. Export metadata includes the version. Append-only capture, tenant serialization, tips, anchors, redaction and browser restrictions remain enforced.

## Validation

- PGlite regression reproduces the original failure, preserves legacy hashes including backslash encoding, checks new multiline/Unicode/control-character hashes independently with Node SHA-256, and covers repeat application, forced v2, gift history, mixed chains, tamper detection, redaction and grants. Added to CI.
- 98 targeted Python tests passed, including export privacy/version metadata, ministry readiness and audit protections.
- Production rollback rehearsal preserved all 565 existing hashes and verification results across 19 businesses; synthetic invoice correction, refund history and mixed-chain verification passed. No rehearsal fixture remained.
- Applied through Supabase Management API at 2026-09-29 04:36 UTC under the user's backend-fix authorization. Confirmed 565 v1 rows, Church chain intact, service helper access and browser-role denial.
- Latest completed backup verified: 2026-09-28 06:57 UTC.

## Deployment

Migration is already applied; deploy the backend export change afterwards. Do not restore the old writer/verifier over a ledger containing v2 rows. Forward fixes must preserve both frozen canonical versions. No frontend files are part of this change.
