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
- **One person can be erased without destroying a practice's record.**
  `ledger_redact_subject()` clears `payload`/`result` on every row that
  touched one subject and leaves the FACT of each action standing: when,
  who, which verb, which sequence. `row_hash` is deliberately NOT
  recomputed — so the chain still links (the next row's `prev_hash` is
  untouched), the removal is reported as *declared* rather than as
  tampering, and the erased content stays **committed to**: anyone holding
  a copy can prove it hashed to the recorded value, while the system no
  longer stores it. Redaction is the only permitted UPDATE, and the trigger
  verifies every other column is byte-identical so it cannot become an edit
  hatch.
- **Verification reports; it does not reassure.** No summary of a result set
  into a claim. Show the rows; let the reader conclude. `ledger_verify`
  refuses to answer `intact` when nothing was hashed — "there was nothing to
  verify" must never be rendered as a green tick.

---

## Closed since (2026-08-03)

All three items previously listed here are fixed.

- **The provable tier no longer skips in silence.** `audit_row_change` used
  to wrap its body in `exception when others then null`, so a held advisory
  lock plus a timeout produced unlogged writes with no gap, no tombstone and
  no alert — a ledger that can silently skip is not a ledger. It now **fails
  closed**: if the ledger row cannot be written, the business write is rolled
  back with it, which makes "a row exists for every write" true by
  construction rather than by hope. The underlying error goes to the Postgres
  log (it survives the rollback); the caller gets a message saying nothing
  was written, and that message deliberately carries no internal detail
  because it crosses a tenant boundary. The unreachable "no `business_id` →
  skip" branch became a raise for the same reason: all eight audited tables
  declare the column NOT NULL, so the only way to reach it was to attach a
  ninth table with a nullable tenant — and that mistake should announce
  itself rather than produce an invisible gap.

  **The cost, stated plainly:** `audit_log` is now on the critical path for
  writes to those eight tables. That is deliberate. A ledger with holes still
  gets shown to auditors, so it is worth less than no ledger at all; loud
  failure is recoverable, silent omission is not. Nothing here is expected to
  throw in normal operation — lock contention *waits*, it does not error.
  Verified live against a sentinel tenant: with the ledger write blocked the
  business write was refused, and four successful writes produced exactly
  four ledger rows.

- **URL credentials are redacted from the logs.** `access_log_redaction.py`
  rewrites `uvicorn.access` records before they are formatted, so
  `/public/audit/<token>` and `/public/store/download/<order>/<token>/<id>`
  keep their useful prefix and lose the secret. The path is an *arg* at
  filter time, not the message, so every string arg is scanned rather than
  the index uvicorn happens to use today. The same scrubber is wired into
  Sentry's `before_send`: `send_default_pii=False` withholds headers and
  cookies but *not* the request URL, and for these routes the URL is the
  whole credential. Installed twice on purpose (import time and app startup)
  because uvicorn's logging `dictConfig` replaces a logger's filter list, and
  a control whose failure mode is silence should not depend on start order.
  **This does not make a token-in-a-URL safe** — it is still in the auditor's
  browser history and in any intermediary that logs paths for us. It closes
  the copy we are responsible for.

- **`/account/export` no longer returns record contents.** It was the last
  surface doing `select=*` on `audit_log`, which handed back `payload` and
  `result`. It now reads through `LEDGER_EXPORT_SELECT` (= `LEDGER_SELECT`
  plus `prev_hash`, `row_hash`, `redacted_at`). Scoped rather than excused:
  the invariant is only worth having if it has no quiet exceptions, and the
  owner loses nothing, because the tables those copies were made *from*
  travel in the same document under their own names. The hash columns are
  the point of an export — the practitioner can hand the file to someone who
  verifies the chain without us.

## Still open

- **`AUDITOR_LINK_SECRET` is not set on Railway.** It falls back to
  `MCP_TOKEN_SECRET`, so rotating agent credentials would silently
  invalidate every live audit link. Kevin's to set.
- **The auditor token still lives in the URL.** Log redaction is mitigation;
  moving the credential off the path is the real fix.

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
