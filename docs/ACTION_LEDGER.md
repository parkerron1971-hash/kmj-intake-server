# The Action Ledger

**Status:** Stages 0–4 shipped 2026-08-03. Stage 5 (anchoring) is designed, not built.

Chief acts autonomously inside real businesses. The system stored *state* —
what is true right now. The ledger stores *history*: what happened, who
allowed it, and proof it hasn't been altered since.

---

## The discipline

> **Append-only. Nothing is ever updated. Nothing is ever deleted.**

This is enforced by the database, not by convention. `audit_log` carries
`BEFORE UPDATE`/`BEFORE DELETE` triggers that raise. It matters that it is
in Postgres: `service_role` — which the entire backend writes as — has
`rolbypassrls = true`, so an application-layer promise binds nobody, and 24
database triggers now write ledger rows with no Python involved at all.

The single sanctioned exception is `ledger_erase_business()` (GDPR), which
writes a tombstone **before** removing anything.

---

## Where things live

| Thing | Where |
|---|---|
| The ledger | `audit_log` — evolved, not replaced. It already had the writers, the endpoint and the UI. |
| Per-tenant chain tip | `ledger_chain_state` — **no FK to businesses**, so it survives erasure and a gap stays provable |
| Erasure record | `ledger_tombstones` — same, outlives the business it describes |
| Vocabulary | `action_types`, 204 verbs, synced at boot from `action_registry` + the event catalog |
| The evaluator | `policy_engine.py` — produces `authorized_by` |
| Write helper | `audit_log.record()` — never sets `sequence`/`prev_hash`/`row_hash`; the database does |
| Verification | `ledger_verify()` + `GET /audit/verify` + `LedgerVerifyBanner.tsx` |

### The six fields
`created_at` (UTC, ms) · `business_id` (never null) · `actor_id` + `actor_type`
· `verb` (controlled vocabulary) · `subject_refs` (`[{type,id}]`, GIN-indexed)
· `authorized_by` (the rule, not the actor).

---

## Two tiers, one table

Both are necessary; neither is sufficient.

- **`source='db_trigger'` — the provable tier.** Transactional with the write
  by construction, unbypassable, carries `before`/`after`. Catches the ~200
  direct PostgREST writes from React that no application code ever sees.
  Cannot know intent: it records `authorized_by='rls'` because row-level
  security is genuinely what permitted it.
- **application rows — the intent tier.** Who, why, and under which rule.
  A trigger structurally cannot know these.

A Chief-created invoice produces one of each. They correlate through
`subject_refs`. `GET /audit` hides the db tier by default (`include_db=true`
reveals it) so a practitioner's history stays readable while the provable
tier stays complete underneath.

**Why not "the ledger write is transactional with the action", as originally
specified?** There is no database driver in this backend — every write is an
individual PostgREST HTTP call, and every logger is deliberately
best-effort. There is no `BEGIN`/`COMMIT` seam to attach anything to. The
trigger tier *is* the transactional answer; claiming it for the application
tier would be a guarantee the architecture cannot honour.

---

## The hash chain

`row_hash = sha256(prev_hash ‖ 0x1E ‖ ledger_canonical_v1(row))`, assigned by
a `BEFORE INSERT` trigger holding `pg_advisory_xact_lock` on the tenant.

The lock is the point. Computing `prev_hash` in the application means
read-the-tip-then-insert; two concurrent actions read the same tip, both
claim it, and the chain forks. Under load that is not hypothetical.

### `ledger_canonical_v1` is frozen

The byte recipe is versioned and **the version is hashed into the material**,
so a future `v2` can never collide with a `v1`. Changing the recipe means a
new function and a documented chain break — never a quiet redefinition.
This is what keeps Stage 5 reachable (below).

---

## Stage 5 — anchoring (designed, not built)

The honest gap in a private hash chain: a determined skeptic can argue we
control the whole database and could have rebuilt the chain wholesale.
Irrelevant for a salon. Material for legal evidence.

The fix is publishing a single fingerprint to an independent public network
so nobody — including us — can backdate history.

**What is already in place, and why nothing here is painful any more:**

1. **Rows are immutable and totally ordered** per tenant (`sequence`).
2. **Canonical serialization exists and is frozen**, so any leaf's bytes are
   reproducible from stored rows.

Because of (1) and (2), a Merkle tree over any batch is **recomputable**, and
the proof path never had to be stored. The spec correctly identified the
proof path as the one thing painful to retrofit; freezing the canonical form
in Stage 2 is what closed it.

**What remains to build, when it is worth it:**

- **Batching.** A deterministic window — `(business_id, date)` or a sequence
  range — rolled into one Merkle root. Deterministic so the same window
  always yields the same root.
- **Anchor record.** `ledger_anchors (business_id, window_start, window_end,
  first_sequence, last_sequence, merkle_root, provider, provider_ref,
  anchored_at)`. The receipt lives with us; the root lives publicly.
- **Proof endpoint.** Given a row: recompute the leaf, walk siblings to the
  root, return the path plus the public reference. The client can verify
  without trusting us.
- **Provider-agnostic interface.** Same discipline as `payments_core`: an
  `anchor(root) -> receipt` seam with Hedera as the first adapter, not a
  hard-wired dependency.

**Never publish business data — only a fingerprint.** The public network
holds proof of non-alteration and nothing else.

Positioning: opt-in premium for practices whose stakes justify it. Not base
layer.

---

## What the product must say plainly

- **The chain starts 2026-08-03.** Rows before it carry no hash. They are
  reported as unverifiable, never as intact. Nothing about the platform's
  first four months is provable, and the UI says so.
- **Erasure leaves a visible gap.** GDPR beats append-only. The tombstone
  records what range vanished and why; `ledger_chain_state` is not reset, so
  the sequence continues past the gap. A gap is deliberate, not evidence of
  tampering — and not hidden either.
- **Verification reports; it does not reassure.** No summary of a result set
  into a claim. Show the rows; let the reader conclude. `ledger_verify`
  refuses to answer `intact` when nothing was hashed — "there was nothing to
  verify" must never be rendered as a green tick.

---

## Open rulings

- **Recurring class-C runs unattended.** A `send_invoice` scheduled once
  fires forever on its recurrence. Recurring invoices are a real feature, so
  the policy engine *records* this (`scheduled:C:unattended`) rather than
  blocking it. Whether it should keep running is a product decision.
- **Viewer seats and writes.** A viewer's write is refused by RLS as a bare
  "insert failed". The policy engine computes the role but does not block, to
  avoid a behaviour change beyond its remit.
- **Conversational portal entry.** "Show me every time Chief touched this
  client's invoices in July" → a filter. The filter mechanics exist and work;
  the Chief binding does not.
