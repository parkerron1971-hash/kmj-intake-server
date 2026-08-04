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
| Step-up | `ledger_unlock.py` + `POST /audit/unlock`; client half in `ledgerUnlock.ts` + `LedgerLock.tsx` |
| Auditor links | `auditor_links.py` (mint / verify / revoke / session) + `auditor_portal.py` (the pages) |
| The guide | `ledger_navigator.py` (question → filter) + `audit_log.run_navigation()` (the one shared path) |
| Chief's binding | `handle_search_ledger` — returns a count and a filter, never rows |
| Log hygiene | `access_log_redaction.py` — keeps URL credentials out of access logs and Sentry |

### The six fields
`created_at` (UTC, ms) · `business_id` (never null) · `actor_id` + `actor_type`
· `verb` (controlled vocabulary) · `subject_refs` (`[{type,id}]`, GIN-indexed)
· `authorized_by` (the rule, not the actor).

---

## The access point

There are **three doors** into a ledger and they never share a credential.
That is the design: an outsider must never need an account, and an
account must never be the thing an outsider borrows.

| Door | Who | Credential | Where it ends |
|---|---|---|---|
| **The app** | Owner, any active seat (viewer and up), active accountant collaborators | Supabase JWT **plus a fresh password confirmation** | OPERATE → History |
| **The link** | An outside auditor, accountant or regulator with no account and no reason to get one | A signed, scoped, expiring token that becomes a cookie | `/public/audit/view` |
| **The file** | Anyone the practitioner hands it to — a board, an insurer, opposing counsel | None. It is a document. | CSV / PDF / JSON |

### Door 1 — the app, behind step-up

Signing in is not enough. History re-asks for the account password and
holds that for **15 minutes**.

The threat is not a stolen password, it is an **open session**: a laptop
left unlocked, a front-desk machine, a browser someone walked away from.
Every other surface leaks a page at a time; History is who did what, to
which client, across the whole business, at once.

`POST /audit/unlock` re-proves the password against Supabase (never
trusting the browser's word for it) and returns a 15-minute HMAC token.
Every ledger call carries it in `X-Ledger-Unlock`. The refusal is
`403 {code: "ledger_locked"}` — machine-readable on purpose, so the UI
can tell *"confirm your password"* apart from *"you may never read
this"*. Showing a password box to someone who will never be let in is
its own small cruelty; showing "access denied" to someone who just needs
to type their password is worse.

The token lives **in memory, never `localStorage`** — persisting it
would hand the walk-up attacker the very proof they were being asked
for, and would outlive the tab that earned it. A reload re-prompts, and
that is correct rather than a rough edge.

Gated: read, verify, export, navigate, mint, redact. **Not gated:
revocation** — it only ever *reduces* access and it is what you reach
for when a link has leaked. A password prompt between a practice and
cutting off a live auditor is a control that hurts the person it exists
to protect.

Both the unlock **and the failed unlock** are ledger rows. Opening the
record joins the record.

Two things it is not, stated so nobody sells it as more:
* **Not a second factor.** Whoever holds the password can complete it.
  It narrows the window on an unattended session; that is the whole claim.
* **It does not narrow the audience.** Viewers and accountants still
  qualify to read. Step-up puts a prompt in front of that audience.
  Whether the audience should be smaller is a separate, open decision.

### Door 2 — the link, which stops being a URL

The owner mints a link scoped to a **date window** and a lifetime (30
days default, 180 max). The window and the scope ride **inside the
signature**, so a tampered URL cannot widen what it may see.

`/public/audit/{token}` is an **entry** route, not a page. It resolves
the link, sets a cookie and `303`s to `/public/audit/view`. The
token-bearing URL renders no body, loads no asset, and never reaches the
address bar — so what survives in browser history, in a bookmark, in a
screenshot or over a shoulder is a URL that grants nothing.

Cookie: `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/public/audit`, and
never longer-lived than the link itself. Lax rather than Strict because
the auditor arrives by clicking a link in an email client, and Strict
withholds the cookie on exactly that navigation.

**Revocation reaches the cookie.** Every request re-checks the link's
`revoked_at`, because a session that outlived a revoked link would turn
"revoke" into "revoke in twelve hours".

Every view is a ledger row. The auditor's reading is part of the record
they are reading — the Etherscan idea inverted: not public to everyone,
but accountable to the practice.

### Signing, and why the domains matter

Three credential types share one key (`AUDITOR_LINK_SECRET`), separated
by **HMAC domain**:

| Credential | Domain prefix | Lives |
|---|---|---|
| Auditor link | *(none — the original)* | 30–180 days, in the URL once |
| Portal session | `auditor-session-v1\|` | ≤12h, cookie |
| Ledger unlock | `ledger-unlock-v1\|` | 15 min, request header |

Without distinct domains a cookie would verify as a link, or an unlock
as either — one credential type silently becoming another with a
different reach. Pinned by a test that forges a payload satisfying
*both* field shapes at once, because the obvious version of that test
passes on field shape alone and would keep passing with the separation
deleted.

**Changing that key invalidates every outstanding link**, since the
secret is what the signature is checked against.

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

## Stage 5 — anchoring (BUILT 2026-08-04, publishing to Bitcoin)

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

**What is built** (`ledger_anchor.py`, `APPLY-2026-08-04-ledger-anchors.sql`):

- **Batching.** The window is "every hashed row after the previous anchor's
  `last_sequence`". Deterministic by construction, because rows are
  immutable — the same window always yields the same root, and re-running
  with nothing new is a no-op rather than a duplicate receipt. Rows with no
  `row_hash` are excluded by query, not skipped, so first/last sequence stay
  honest about what the root covers.
- **Anchor record.** `ledger_anchors`, append-only like the rest (UPDATE,
  DELETE and TRUNCATE all raise) and with **no FK to businesses**, for the
  same reason `ledger_chain_state` has none: the receipt must outlive an
  erased tenant or erasure would destroy the evidence that the erasure was
  declared.
- **Proof endpoint.** `GET /audit/proof?biz=&sequence=` returns the leaf's
  `row_hash`, the sibling path, the root and the public reference —
  everything needed to rebuild the root independently, nothing that must be
  taken on trust. `root_matches` is *reported, never repaired*: an endpoint
  that quietly re-roots when the rows have moved is not a proof endpoint.
- **Provider seam.** `anchor(root) -> (ref, error)`. A failed publish writes
  **no receipt** — a row here asserts a proof exists, and writing one when
  publication failed would make the table lie in the one direction it must
  not.

**Two decisions that make this a proof rather than a shape:**

*Domain separation.* Leaves hash with a `0x00` prefix, internal nodes with
`0x01`. Without it a Merkle tree admits a second-preimage attack — an
internal node can be presented as a leaf, producing a valid path for data
that was never in the tree. One byte, and omitting it is the classic way to
build a proof system that proves the wrong thing.

*Odd levels promote, they do not duplicate.* Duplicating the last node
(Bitcoin's shape) makes a tree of N and a tree of N+1 whose last row is a
copy produce the **same root**. Two different histories sharing a root is a
real ambiguity in a system whose claim is "this is exactly what happened".

Verified by proving every row in every window size from 1 to 64, and against
real production rows.

### The public provider: OpenTimestamps → Bitcoin

Chosen over a paid ledger for one reason that outranks cost: **the auditor
verifies with a tool we did not write.** The output is a standard `.ots`
file, checked with the public `ots verify` client against the Bitcoin
blockchain. A proof only our own code can validate is worth very little.

It also needs no account, no credentials and no fees, so switching it on was
never a commercial decision.

**Three states, and they are not the same thing.** The surfaces must never
round them together:

| State | What it means |
|---|---|
| `local` | Recorded here, published nowhere. Inside the very trust boundary a skeptic is questioning, so it proves nothing they must accept. A staging step. |
| `submitted` | At independent calendar servers, which have committed to including it. It has left our control — real, and weaker than the next row. |
| `confirmed` | The commitment is in a Bitcoin block. The root is now provably older than that block, and no party — us included — can backdate it. |

Bitcoin aggregation takes hours, so `submitted` is the normal state for a
while. The banner says "waiting to be written into Bitcoin" rather than
letting it borrow the credibility of `confirmed`.

**Redundancy.** The root goes to three calendars. One unreachable server must
not cost a practice its anchor, and the proof is valid if any single calendar
honours it. If *every* calendar fails, `anchor()` returns an error and **no
receipt is written** — a row here asserts a proof exists.

**Upgrades are never written back.** `ledger_anchors` is append-only, so the
stored receipt can never be rewritten — and does not need to be. A pending
proof already carries everything needed to fetch its Bitcoin attestation, so
`proof_status()` recomputes the current state on each read. The receipt stays
immutable and the answer stays current, which would otherwise be in tension.

**`GET /audit/anchor.ots?biz=&sequence=`** hands over the proof file. That
route is the point of the whole stage: an auditor runs `ots verify` against
Bitcoin, and nothing in that check involves our code, our servers, or our
good faith.

Enabled with `LEDGER_ANCHOR_PROVIDER=opentimestamps`. Unset, it falls back to
`local` — so a missing env var degrades to "we published nothing", never to a
false claim of independence.

### Second adapter: Hedera (built, not configured)

Kevin's original choice, and the one the spec named. Both exist because they
fail and succeed differently:

| | OpenTimestamps | Hedera |
|---|---|---|
| Finality | Hours (Bitcoin aggregation) | Seconds |
| Cost / setup | Free, no account | Small fee, needs an account + funded balance |
| Verified by | Public `ots` client vs Bitcoin | Public mirror-node REST vs the topic |
| Normal state after anchoring | `submitted` for most of a day | `confirmed` immediately |

Speed is the real difference. If a practice needs to say *proven* the same
afternoon, Hedera is the one that can; OTS spends its first day merely
submitted.

**Testnet is not evidence, and this is the load-bearing decision.** Hedera's
testnet is periodically **wiped**. A proof there looks identical to a real one
and then vanishes without warning, so `is_independent` is False on any network
but mainnet, and the banner calls it a rehearsal. Getting this backwards would
produce the worst outcome this feature can have — a practice believing it holds
evidence that has quietly ceased to exist.

`independent` is read from the **receipt's own** network, not the currently
configured one, so flipping the env var to mainnet cannot silently promote old
testnet proofs.

**Configuration** (all three required, or it refuses by name and writes no
receipt): `HEDERA_ACCOUNT_ID`, `HEDERA_PRIVATE_KEY`, `HEDERA_TOPIC_ID`, plus
`HEDERA_NETWORK=mainnet`. Uses `hiero-sdk-python` — the *native* SDK; the older
`hedera-sdk-py` wraps the Java SDK through pyjnius and would drag a JVM into
the image.

Nothing is configured yet, so selecting `hedera` today fails cleanly rather
than anchoring nowhere.

**Never publish business data — only a fingerprint.** The public network
holds proof of non-alteration and nothing else.

Positioning: opt-in premium for practices whose stakes justify it. Not base
layer.

---

## The guide — AI that finds, never AI that concludes

The rule: **the software finds and filters; the human concludes.** An
auditor is precisely the reader who must not be handed a verdict, and a
ledger whose software tells you what it means has stopped being
evidence.

That restraint is **structural, not a prompt instruction**. The model
receives the question and the 204-verb vocabulary. It returns a
**filter** — date range, verb, actor, subject. It never receives a row.
It cannot summarise records it was never given, and no clever question
talks it past that, because there is nothing to talk past.

Three surfaces run through **one** function, `audit_log.run_navigation`:

| Asked from | Gate | Records |
|---|---|---|
| History's search box | seat ladder + step-up | `ledger:searched` |
| The auditor portal | signed session, metered per link | `ledger:searched`, actor `auditor:{jti}` |
| Chief, in conversation | seat ladder + step-up | `ledger:searched` |

One function on purpose: a second copy is how this property holds on one
surface and quietly rots on the other.

**The signed window clamps the model.** On an auditor link the filter
comes from free text an outsider typed, so `run_navigation` intersects
it with the link's window — a later start wins, an earlier end wins.
Without that, *"everything from last year"* on a link scoped to one
quarter would widen the link, and the model would have become the
access-control decision.

**And the sentence must describe the search that actually ran.** Found
by driving the live portal: a January-scoped link asked for "everything
from the last two years" correctly returned zero rows, under the
sentence *"Showing everything recorded since 2022-07-01."* The clamp was
right and the sentence was a lie — an auditor would take away "nothing
happened in two years" from a search that covered one month. The
description is now regenerated from the **final** filter and the
narrowing is stated out loud. **Rule: when a filter is modified after
the model described it, the description is regenerated. Never report the
requested filter as the applied one.**

**Chief is given a count and a filter, never rows.** Ask *"when did you
last touch that client's invoices?"* and History opens on them. Hand
Chief the rows and it becomes the thing that says "nothing unusual
happened there" — the one conclusion the reader has to reach alone. The
handler is pinned by a test asserting `entries` never appears in it, and
the prompt says so in those terms.

**The ledger verb is `sensitive`, so it never reaches the MCP agent
surface.** Exposure there is *derived* from `read` classification, so
adding this verb silently put the audit trail on the agent surface — and
a long-lived agent token would have been the way around the step-up
shipped in the same commit. Caught by the exposure-count tripwire.
Read-ness asks "can this break anything"; sensitivity asks "may a third
party see it".

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

- **The auditor credential is out of the URL.** `/public/audit/{token}` is
  now an *entry* route: it resolves the link, sets a short-lived scoped
  cookie and 303s to `/public/audit/view`, which is the page the auditor
  actually reads. The token-bearing URL renders no body, loads no asset and
  never reaches the address bar, so what survives in browser history, in a
  bookmark, in a screenshot or on a shared screen is a URL that grants
  nothing. The link itself still arrives by email with the token in the path
  — that is unavoidable — but it is now spent on one request per session
  instead of every page view and every download.

  Four things the exchange deliberately does not weaken. **Revocation still
  bites**: every request re-checks the link's `revoked_at`, because a cookie
  that outlived a revoked link would turn "revoke" into "revoke in twelve
  hours". **A session never outlives its link** — the TTL is capped at the
  link's own expiry, so a 12-hour session cannot be minted from a link with
  five minutes left. **The window rides inside the session signature**, as it
  does on the link, so an edited cookie cannot widen what it may see. And
  **sessions are signed in a separate HMAC domain** (`auditor-session-v1|`),
  because both credentials use the same key — without it a cookie would
  verify as a link and a link as a cookie. That last one is pinned by a test
  that forges a payload satisfying *both* field shapes at once, since the
  obvious version of the test passes on field shape alone and would keep
  passing with the domain separation removed.

  Cookie: `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/public/audit`. Lax
  rather than Strict because the auditor arrives by clicking a link in an
  email client, and Strict withholds the cookie on exactly that cross-site
  top-level navigation.

- **The chain tip is bounded by the rows** (Kevin's ruling on the audit
  finding). `ledger_tip_forward_only` made `last_sequence` monotonic so it
  could not be rolled *back*, but nothing bounded how far *forward* it could
  go — and a tip ahead of the rows makes `ledger_verify` report *"records
  were removed"* about a ledger from which nothing was removed. A false
  accusation of tampering, indistinguishable from the real thing.

  The report described one hole; there were three. **UPDATE** could set any
  forward value. **DELETE + INSERT bypassed the UPDATE guard entirely** —
  deleting the tip row and re-inserting one with `last_sequence=999999`
  succeeded, so guarding a single verb was theatre. And **`(business_id,
  sequence)` had no unique index**, so a reset tip would mint duplicate
  sequence numbers — the exact ordering ambiguity the tip guard was written
  to prevent, still reachable by another road.

  Now: the tip may never exceed `max(sequence) + 1` for its tenant, on
  INSERT as well as UPDATE; the tip row cannot be deleted or truncated (and
  needs no exception path, because `ledger_erase_business` reads the tip and
  deliberately never resets it); and the sequence is unique per tenant.

  **Why `+ 1` and not `= max`:** `ledger_assign_sequence` is a BEFORE INSERT
  trigger, so it moves the tip while the row it describes does not exist
  yet. One ahead is the correct steady state for the duration of that
  trigger, and it is also the room the repair path needs. Tightening it to
  `= max` would break every write — and with fail-closed in place, that
  breaks the *business* write too.

  The residual is one row wide and **cannot accumulate**: the tip can still
  be nudged to exactly `max + 1`, which is a one-row false alarm, but a
  second nudge is refused because it would then exceed the bound. Closing
  that last row would mean teaching `ledger_verify` to tolerate `tip = max +
  1`, which would cost the detection of a genuine single-row tail loss —
  a worse trade.

  The multi-row worry was **tested, not reasoned about**: a statement's own
  rows can be invisible to queries under its snapshot, which would have made
  this rule reject every multi-row insert. All three shapes were run against
  the live database — separate INSERTs, a multi-row INSERT on a covered
  table, and a multi-row INSERT straight into `audit_log` — and all pass,
  because a query inside a plpgsql trigger runs under a fresh
  command-counter snapshot.

- **Step-up, the auditor's guide, and Chief's binding** (2026-08-04, BE#402
  / FE#306 / BE#403). Described in *The access point* and *The guide* above.
  Three notes worth keeping with the change record rather than the design:

  A **separate ledger password was rejected**, not overlooked. Same as the
  account password it is friction without protection; a new secret needs a
  reset path, and whoever can reset it from inside a signed-in session is
  the very attacker it was meant to stop. It would also be a thing a
  practitioner can lose, locking them out of their own audit trail.

  `GET /audit` **ignored `since`/`until`** until this arc — Chief's filter
  would have had its date range dropped while the panel claimed to show a
  window. A quiet wrong answer is the one kind a ledger surface must never
  give.

  Verified end to end **against production with a real signed-in user**, not
  only in tests: locked without an unlock, wrong password refused, correct
  password opens all five surfaces, forged token refused, **another user's
  valid unlock refused**, and the same payload signed in the auditor-link
  domain refused. Unit tests cannot prove the browser contract; that can.

## Still open

`AUDITOR_LINK_SECRET` was set on Railway 2026-08-03, at the free moment —
`auditor_links` held zero rows, so nothing had been signed with the
`MCP_TOKEN_SECRET` fallback. Note for later: changing that key now
invalidates every outstanding link, because the secret is what the signature
is checked against.

- **The ledger's audience is still wide.** The read gate admits the owner,
  any active seat from viewer up, and active accountant collaborators.
  Step-up puts a password prompt in front of that audience; it does not
  shrink it. Whether a viewer seat should reach the audit trail at all is
  an open product decision, deliberately not bundled into the step-up work.
- **One test row is permanently in a real ledger.** `ledger:selftest`
  ("stage1 proof") sits at sequence 5 of *KMJ Creative Solutions* — our own
  business, not a customer's. Append-only means it cannot be removed, and it
  is the only row in production with `verb_registered=false`. Harmless, but
  it will appear in that practice's History panel forever. The lesson is the
  one already recorded: rehearse on a throwaway tenant, never on a real one.

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
