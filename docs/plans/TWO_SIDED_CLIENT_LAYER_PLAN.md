# Two-Sided Client Layer — Plan of Action

**Status:** Part 3. Companion to `TWO_SIDED_CLIENT_LAYER_AUDIT.md` (Parts 1–2).
**Date:** 2026-08-31
**Decisions locked by Kevin:** parallel client surface (not the seat ladder) ·
engagement record before rewards · therapists out of this arc · milestone-gated
billing, not custody · client actor type added now.

---

## 0. One correction to the build order, before anything else

**"Book and pay first. Cancel and reschedule held back" is exactly inverted
relative to what the architecture permits — and the fix is not a workaround, it
is answer 1 applied consistently.**

Read off `action_registry.py` *(verified)*:

| Verb | Class | The registry's own reason |
|---|---|---|
| `create_booking` | **C** | "creates the appointment AND emails the client a confirmation… The send is what makes this C while cancel/reschedule are A" |
| `generate_payment_link` | **C** | "creates a Stripe Price + PaymentLink — external money object" |
| `create_invoice` / `send_invoice` / `mark_invoice_paid` | **C** | money-touching |
| `cancel_booking` | **A** | "Verified it sends NO client email… §2.4 lists scheduling as class A" |
| `reschedule_booking` | **A** | "moves an appointment; sends nothing, same as cancel" |

And `may_expose_to_agent(verb, allow_writes=True)` admits **class A and B
only** — "class C never qualifies, and neither does anything unclassified."
`is_autonomy_eligible` states the rule flatly: "Class C never — that is the
§2.4 rule and not a knob."

So on the MCP surface, book and pay are permanently unavailable and
cancel/reschedule are the *only* two things you named that an agent could ever
do. Flipping `KNOWN_SCOPES` does not change this; the scope tuple is not what
is stopping class C.

### The resolution

**A client's agent must not touch the MCP / action-registry surface at all.**

That surface is Chief's verb toolkit, and every classification in it answers
one question: *may Chief do this on the practitioner's behalf, unprompted,
inside their business?* `create_booking` is class C because **Chief** inventing
an appointment and emailing a client about it is not something Chief should do
on its own. That reasoning does not transfer to a client booking themselves.
The registry even flags the seam: on `cancel_booking` it notes that a silently
cancelled client appointment "is a product question, not a classification one."

A client booking themselves is self-authorized, and **the endpoint already
exists**: `POST /widgets/booking/{business_id}/book`, authed by
`require_customer_token_dep`, which as of Phase D.4 already creates the
appointment, runs the double-book guard, sends the confirmation email with
`.ics`, and fires the A2P confirmation SMS *(verified —
`booking_widget_router.py:901`)*.

**So the client agent surface is the client surface with a client credential —
not MCP.** This is the parallel-surface decision (answer 1) applied to agents
rather than only to humans. It keeps the class C rule untouched, keeps Chief as
the undisplaced business-side surface, and delivers "book and pay first"
exactly as you asked.

**This also removes a hidden backwards dependency.** Routed through MCP, Phase
1's agent write would have depended on **Phase 4**: `mcp_tokens` are minted by
the owner, and there is no client account to mint one for until client identity
exists. Routed through the client surface, there is no dependency —
`customer_token` already binds `(biz, cus)` with no account behind it.

`KNOWN_SCOPES` beyond read-only remains worth doing, but it is a **different
audience** (the practitioner's own agent, Chief-adjacent) and its first
admissible writes are `cancel_booking` and `reschedule_booking` — the two you
wanted held back. It is not in Phase 1. See Phase 3.5.

---

## 1. Answer to the `vertical_scope.py` question

> *Does it need a second kind of rule to express "no client-authored free text
> in this vertical", or is keeping the vertical out entirely sufficient?*

**Keeping the vertical out is sufficient for this arc — but only if the gate is
explicit and test-pinned rather than implicit.** Today "therapists are out"
would be true by accident: no client surface exists, so no vertical has one. The
moment Phase 1 ships, "out" has to be a thing the code says.

`vertical_scope.OUT_OF_SCOPE` is the right home and its current shape is the
wrong one. `ScopeRule` carries `blocked` (a phrase list), `reason`,
`allowed_note` and `prompt` — all built for `check_module_scope()`, which
inspects module *name, slug, description and field labels* at creation time. A
client-input rule is a different question asked at a different moment.

**Recommendation: add a second rule kind, but make it a capability gate, not a
content scan.**

```
ScopeRule.client_surface: "denied" | "no_free_text" | "allowed"
```

with a `client_surface_allowed(business_type) -> bool` helper called at the one
seam where a client-facing surface is enabled for a business.

What I would **not** do is keyword-scan client-authored prose. The module
already argues the case against an LLM classifier here — "a false negative here
is a HIPAA exposure rather than an inconvenience" — and a keyword list over
free-form client text fails open far more often than one over a module name a
practitioner deliberately chose. Refusing the surface is the correct direction
to be wrong in; filtering its contents is not.

**Sizing:** XS. One field, one helper, one test. Ships in Phase 0 so that
"therapists are out" is enforced from the first commit rather than asserted in
a plan document.

---

## 2. Phase 0 — the one-way doors *(ships with Phase 1, reviewed separately)*

Everything here is irreversible-if-deferred and cheap-if-done-now. None of it
is visible to a practitioner. It exists so Phases 1–4 do not have to undo it.

### 0.1 `audit_log.actor_type` — add the client actor

`supabase/APPLY-2026-07-30-audit-log.sql:31` currently reads:

```sql
actor_type text not null check (actor_type in ('user','chief','agent','system')),
```

Add `'client'`. The table is append-only with `BEFORE UPDATE` / `BEFORE DELETE`
triggers that raise, so **history cannot be migrated to a later decision** —
rows written before the constraint changes can never be relabelled.

The alternative (client actions as `actor_type='system'` with identity in
`actor_id`, the way the scheduler does it) encodes "who did this" by convention
on the one table whose entire value proposition is that it does not rely on
convention. Reject it.

*Also worth deciding in the same migration:* whether a client's **agent** is
`'client'` or `'agent'`. My recommendation is `'client'` with the agent
identity carried in `authorship` (the `APPLY-2026-08-10-ledger-ai-authorship`
column already exists to say "which machine decided" alongside `actor_type`'s
"a machine decided"). One actor type for "the client side acted"; authorship
distinguishes the human from their agent. Adding both `'client'` and
`'client_agent'` would make every future query about client activity a two-value
`IN` list forever.

**Sizing:** XS · **Gate:** the constraint is live in Supabase and a test asserts
`record(actor_type='client')` succeeds.

### 0.2 `policy_engine` — the fifth actor class

`evaluate()` calls `role_of(business_id, user_id)`, which returns `None` for a
client, and every downstream rule is written for user/chief/agent/system on the
`chat | scheduler | workflow | notification | autopilot | trust-track | agent`
surfaces.

Per the audit's §2.4 finding, **no client action may write a ledger row until
`policy_engine` can name the rule that authorized it**, or every such row fails
the discipline's own test ("Chief did this" vs "Chief was permitted to do this,
here is the rule").

Add `surface='client'` and a rule family — `client:self` (the client acting on
their own record), `client:agent` (their agent, same authority, different
authorship). The `Verdict.rule` string is what lands in `authorized_by` and it
"has to survive being queried a year from now," so name it once, carefully.

**Sizing:** S · **Gate:** the evaluator exists, its vocabulary is closed and
fails closed on drift, and the vertical gate is enforced inside it.

**Scope note — what Phase 0 deliberately does NOT do.** It ships the evaluator
and its tests; it does **not** rewire the live
`POST /widgets/booking/{business_id}/book` endpoint to call it. Wiring a
running, client-facing booking endpoint to a new refusal path changes behaviour
for real customers of real practitioners, and it belongs with the surface work
in Phase 1 where the ledger rows are part of the deliverable — not with the
schema doors, where the whole point is that nothing observable changes. Phase 1
inherits this as its first task, and its gate carries the assertion that no
client write reaches `audit_log.record()` without a `client:*` rule.

### 0.3 `platform_identity_id` — the column Phase 4 needs and Phase 1 must not preclude

Nullable `uuid` on `business_customers`, no FK yet, no table behind it, nothing
reads it. Costs one column today; unrecoverable later, because by Phase 4 there
will be client rows across many tenants with no way to say two of them are the
same person.

**⚠ A dependency you should decide now, not in Phase 4.** Your Phase 4 trigger
is *"a client hitting their second business on the platform."* Detecting that
requires matching a person **across tenants** — and Phases 1–3, as specified,
store nothing that can do it. `business_customers` is uniquely keyed
`(business_id, lower(email))`; there is no cross-tenant index and deliberately
so.

Two honest options, and they must be chosen before Phase 1 writes its first
client row:

- **(a) A cross-tenant email hash.** Store `sha256(lower(email) + platform
  pepper)` on `business_customers`, indexed, not reversible to an address
  without the pepper. Phase 4's trigger becomes a lookup. This is a real
  cross-tenant linkage of client data and must be disclosed in the client-facing
  privacy copy from Phase 1, not retrofitted at Phase 4.
- **(b) Self-declaration only.** No cross-tenant matching. Phase 4's identity is
  offered when a client *says* they have another practitioner, or via an
  invite link. Nothing links until the client links it.

**Recommendation: (b) for this arc, with the column present.** (a) is a
meaningful privacy posture change — one practitioner's client list becomes
joinable to another's inside your database — and it buys a trigger you do not
need until Phase 4. (b) keeps the door open at zero privacy cost; if Phase 4
shows self-declaration is too weak a trigger, (a) is still available then, on
data you will by that point have disclosed a reason to collect. **But if you
want (a), the pepper and the hash must ship in Phase 0**, because backfilling a
hash over emails you have already collected under a narrower notice is the
expensive version.

**Sizing:** XS (option b) · **Gate:** migration applied; column present; nothing
reads it.

### 0.4 `vertical_scope.client_surface` — therapists out, explicitly

Per §1 above.

**Sizing:** XS · **Gate:** `client_surface_allowed('therapist')` is False and a
test pins it; the Phase 1 enable path calls it.

### 0.5 Close the metering hole

The audit's §1.9 finding: `billing_context.set_current()` is called in four
places, none on a client path, so an LLM call reached through a client
credential logs `business_id: None` — and per `spend_guard.py` unattributed
spend "counts toward the platform ceiling only," the ceiling whose failure mode
is Chief going dark for every paying practitioner.

`require_customer_token_dep` sets `billing_context` after step 3 — the same
ordering discipline `business_access` uses, where bookkeeping follows
authorization and never grants it. This is a three-line change and it is the
single highest-leverage protective edit in the whole plan.

**Ships in Phase 0 and not later**, because it protects Chief *today*: the
client-token booking endpoints already exist and already run.

**Sizing:** XS · **Gate:** a test asserts `billing_context.current()` equals the
path business id inside a `require_customer_token_dep`-authed request, and is
None before it.

---

## 3. Phase 1 — the engagement record

**The shippable claim:** a practitioner writes scope, milestones and
deliverables once; their client sees it at a link with no password; sign-off is
a two-sided act recorded on the ledger; the invoice fires on the connected
account. Wanted on its own by consultant, creative, contractor, lawyer and
coach.

### 1.1 What gets built

**A first-class `engagements` table**, not an extension of the contract
pipeline. Per audit §2.6 door 4: this is the object items 6 and 7 both need to
point at, and bolting milestones onto the PDF pipeline would foreclose both.

```
engagements          business_id · contact_id · title · scope (structured) ·
                     status · fee_model · created_at · version
engagement_milestones engagement_id · title · sequence · amount_cents ·
                     due_date · status · signed_off_at · signed_off_by
```

`contract_agent.py` keeps its job — it drafts the prose and the PDF. The
engagement record is the *structured* half, and `subject_refs` on the ledger
points at it. That is the audit's §1.7 answer to the dispute-evidence gap:
`LEDGER_SELECT` deliberately excludes `payload` and `result`, so the agreed
scope lives in a signed, versioned record the ledger *references* rather than in
ledger rows the auditor door would then have to widen for.

**The client-facing surface reuses `auditor_portal.py`'s pattern verbatim** —
the token is an entry route that sets a scoped cookie and 303s, so the
credential never renders a page, never reaches the address bar, and never
survives in history or a screenshot; revocation re-checks on every request;
every view writes a ledger row. That module is the closest thing in the repo to
what a client engagement view needs, and copying it is cheaper and safer than
inventing a second pattern.

**Branding** is `booking_page_renderer.py`'s brand-kit-to-CSS-variables
treatment applied to a second page type. Per audit §1.3, item 2 is not new
capability — it is an existing pattern applied to more pages.

**Sign-off → invoice** is the milestone-gated *billing* path: sign-off writes a
ledger row, emits a spine event (a new `EVENT_CATALOG` entry — the catalog is
drift-tested, so it cannot be skipped), and the event fires an invoice on the
connected account via `payments_core`. No funds are ever held.

### 1.2 Client agent write access

Per §0 above: the client surface, not MCP. A client credential with a **write
scope** reaching `book`, `pay` and `sign off` — the three verbs a client agent
plausibly needs in this phase — through the existing client endpoints, with
`policy_engine` naming `client:agent` on every row.

Cancel and reschedule stay out, as you asked. Note that this is now a *product*
choice rather than a constraint, since the client surface has no class ladder —
so state it in the code, with the reason, or it will read as an oversight.

### 1.3 What Phase 1 displaces or delays

| Roadmap item | Effect |
|---|---|
| Phase D.4 PR 2/3 (payment_intent / checkout.session / invoice / charge webhook handlers) | **Accelerated, not displaced.** Sign-off→invoice needs the invoice handlers PR 2/3 already scopes. Build them here rather than twice. |
| The v2 accountant arc (`business_collaborators_router`'s "accountant-operates-the-business experience") | **Delayed.** Same reviewer attention, same cross-tenant read-path questions. |
| Per-business `customer_token` secrets (`TODO(phase-c-x)`) | **Promoted to a blocker, but for Phase 2, not Phase 1.** See §4. |
| The in-memory booking rate limiter TODO | **Not displaced. Phase 1 must not widen it** — the engagement link is cookie-scoped like `auditor_portal`, not IP-rate-limited like the anon widgets. |
| Rewards | Deferred to Phase 3 by your ruling. |

**Made redundant:** nothing. Notably *not* `contract_agent.py` — it keeps
drafting.

### 1.4 Build gate

- `engagements` + `engagement_milestones` live in Supabase, in
  `BUSINESS_CHILD_TABLES`, RLS on, no `qual = true` policy on either (the
  `pg_policies` check from `RLS_MODEL.md`, run live).
- Every client-surface write path calls `policy_engine.evaluate()` and writes a
  ledger row with a `client:*` rule.
- `client_surface_allowed()` gates the enable path; therapist is False.
- Sign-off→invoice works end to end against a real connected account in test
  mode, and **no code path can hold funds** — asserted by a test that greps for
  `transfer_data` / `on_behalf_of` / destination-charge parameters and fails if
  any appears.
- One real beta business has run a full engagement and would keep it.

**Sizing: L.** The largest phase, and the only one whose size is mostly new
surface rather than new plumbing.

### 1.5 One-way doors in Phase 1

1. **`engagements` as its own table vs. an extension of contracts.** Decided:
   own table. Reversing means re-pointing every `subject_refs` written in
   between.
2. **The client engagement link's cookie scope and domain.** Per audit §2.6 door
   5: `cloudflare_saas.py` makes per-practitioner hostnames real, and each is
   its own origin. `auditor_portal` scopes its cookie to `Path=/public/audit` on
   our host. **If the white-label promise means the engagement page eventually
   serves from the practitioner's domain, the session mechanism written now gets
   rewritten then.** Decide the domain before writing the cookie, not after.
3. **Milestone amount as `amount_cents` on the milestone vs. derived from the
   invoice.** Storing it makes the engagement the source of truth and the
   invoice a consequence. Deriving it makes Stripe the source of truth. The
   former is the whole strategic claim; pick it deliberately.
4. **Whether sign-off is revocable.** An append-only sign-off is evidence; a
   toggleable one is a UI state. Given the dispute-evidence purpose, sign-off
   should be an append-only event with a separate `sign_off_withdrawn` event
   rather than a mutable boolean. Cheap now, impossible to reconstruct later.

---

## 4. Phase 2 — remembered state

Saved card, one-tap rebook, visit history. No account.

**⚠ This phase has a hard prerequisite that is currently a TODO.**
`customer_token.py` uses a **single global `CUSTOMER_TOKEN_SECRET`** with a
`TODO(phase-c-x)` saying per-business secrets are needed "before first real
practitioner goes live." Today a rotation breaks booking links. **Once that
token is the thing standing between a stranger and a saved card, it becomes an
authentication credential of real value, and one global secret means one
rotation logs out every client of every practitioner simultaneously — and one
leak is platform-wide.**

Per-business token secrets are a **Phase 2 blocker**, not a nice-to-have. That
is the answer to "does any phase depend on something later in the order": no
phase depends on a *later phase*, but Phase 2 depends on a debt currently
deferred to an unscheduled "phase-c-x".

Saved card is a Stripe Customer + SetupIntent **on the connected account**, per
business. No cross-tenant identity needed, and no custody — consistent with
answer 5.

**Displaces:** the anon booking widget's in-memory rate limiter finally has to
move to Postgres or Redis; a saved-card surface behind a per-dyno limiter is not
defensible.

**Gate:** per-business token secrets live and rotatable · saved card works
without the platform touching a PAN (SetupIntent only, never a raw card) · a
revoked client link cannot reach a saved card.

**Sizing: M.**

**One-way door:** where the saved payment method is keyed. On
`business_customers.id` it is per-tenant and correct for now; on a cross-tenant
identity it is portable and a much bigger regulatory surface. Key it per-tenant.

---

## 5. Phase 3 — rewards

`customer_balances` as a sixth `kind`, per audit §1.5 — not a custom module, not
a new archetype. The enum stays closed at four, which is the enum working as
designed.

Read through the Phase 1 signed link. `platform_identity_id` present and
nullable, per your ruling.

**⚠ The overdraw race becomes reachable by strangers.**
`customer_balances.consume()` reads-then-writes across two PostgREST calls with
no transaction boundary and self-corrects by reversing its own row. That is
honest and adequate for a practitioner clicking a button; it is not adequate for
client-facing redemption. **The clean fix — a database function with
`SELECT … FOR UPDATE` — moves from "beyond this arc" (its docstring) to a Phase
3 blocker.**

**Displaces:** nothing on the roadmap. **Makes redundant:** the pressure to add
a `RewardProgress` archetype. Say so explicitly when it comes up.

**Gate:** redemption is atomic under concurrent draw (a test that fires two
concurrent `consume()` calls and asserts the balance never goes negative) ·
rewards `(kind, unit)` vocabulary is shared across businesses, not per-business
free-form — this is what keeps the item-7 benchmark option alive.

**Sizing: S**, given Phase 1 built the client surface and `customer_balances`
already exists.

---

## 6. Phase 3.5 — `KNOWN_SCOPES` beyond read *(practitioner-side, optional)*

Separated out because §0 showed it is a different audience from the client
agent, and nothing in Phases 1–4 depends on it.

A `write` scope on `mcp_tokens` admits class A and B verbs to the
practitioner's own agent. First admissible booking verbs: `cancel_booking` and
`reschedule_booking` (both class A). `create_booking` and every payment verb
remain permanently out at any scope.

**Gate:** `may_expose_to_agent(verb, allow_writes=True)` is the only decider
(no second list) · `agent_runs` records every write · a test asserts no class C
verb is reachable at any scope.

**Sizing: S.**

---

## 7. Phase 4 — client identity

Logins offered to clients already using the thing, never as a gate in front of a
first booking.

By this point `customer_token` has carried real client sessions for three
phases, so the question is narrow: promote a `business_customers` row to a
Supabase auth user, populate `platform_identity_id`, and let one identity hold
several. `business_collaborators` is the working precedent for one user across
several tenants with independently revocable grants.

**The trigger depends on a Phase 0 decision** (§0.3): "a client hitting their
second business" is only detectable if something matches people across tenants.
Under recommendation (b) the trigger becomes self-declaration or an invite,
which is weaker but costs no privacy posture.

**Displaces:** the v2 accountant arc again, and for the same reason — this is
where the cross-tenant read paths finally get built, and doing both at once is
how the 42P17 recursion outage happens a second time.

**Gate:** a client with accounts at two businesses sees exactly two engagements
and nothing else, verified against the live `pg_policies` output, not against a
test double · GDPR export/delete answers for a subject who spans tenants ·
`account_lifecycle` handles a client who is not a `BUSINESS_CHILD_TABLES` row.

**Sizing: XL** — and it is XL *because* Phases 1–3 deliberately avoided it.

---

## 8. Dependency check — is the sequence right?

**Yes, with three corrections, all stated above and none of which reorder the
phases.**

1. **Phase 1's agent write, as written in the brief, depended on Phase 4.**
   Routed through MCP, a client agent needs a client account that does not exist
   until Phase 4. Routed through the client surface (§0), the dependency
   disappears. **This is the one place the original order would have deadlocked.**
2. **Phase 2 depends on a deferred TODO, not on a later phase.** Per-business
   `customer_token` secrets are currently unscheduled and become a Phase 2
   blocker (§4).
3. **Phase 4's trigger depends on a Phase 0 decision** (§0.3). Not a
   reordering — a decision that has to be made early and is easy to miss.

Otherwise the order is sound and each phase reads only from phases before it:

```
Phase 0  doors + metering ──┬─→ Phase 1  engagement record ──┬─→ Phase 2  remembered state
                            │        (+ client agent write)  │
                            │                                └─→ Phase 3  rewards
                            └─────────────────────────────────→ Phase 3.5 agent writes (independent)
Phase 1 + 2 + 3 ─────────────────────────────────────────────→ Phase 4  client identity
```

**One structural note on Phase 1 being first.** It is the right call and it
carries the arc's whole risk: it is the only phase that is L, the only one
building genuinely new surface, and the only one whose value has to land with a
real practitioner before anything else is justified. If Phase 1 does not get
used by the beta business, Phases 2–4 should not be built — and that is a
feature of this ordering, not a flaw in it.

---

## 9. Sizing summary

| Phase | Size | Blocking on |
|---|---|---|
| 0 — doors + metering | **S** total (5 items, XS–S each) | nothing |
| 1 — engagement record + client agent write | **L** | Phase 0 |
| 2 — remembered state | **M** | Phase 1 · per-business token secrets |
| 3 — rewards | **S** | Phase 1 · atomic `consume()` |
| 3.5 — agent write scope | **S** | Phase 0 (independent of 1–4) |
| 4 — client identity | **XL** | Phases 1–3 · §0.3 decision |

---

## 10. Every one-way door in one place

| # | Door | Decided | Phase |
|---|---|---|---|
| 1 | Parallel client surface vs. seat ladder | **Parallel** (Kevin) | 0 |
| 2 | `audit_log.actor_type` gains `'client'` | **Yes** (Kevin) | 0 |
| 3 | Client agent = `'client'` + authorship, not `'client_agent'` | recommended | 0 |
| 4 | Cross-tenant matching: email hash vs. self-declaration | **recommended (b)** — needs your call | 0 |
| 5 | `policy_engine` client rule names (`client:self` / `client:agent`) | recommended | 0 |
| 6 | `engagements` as its own table | **Yes** | 1 |
| 7 | Engagement page domain — ours vs. practitioner's | **open — decide before writing the cookie** | 1 |
| 8 | Milestone amount stored vs. derived from Stripe | recommended stored | 1 |
| 9 | Sign-off append-only vs. mutable | recommended append-only | 1 |
| 10 | Saved payment method keyed per-tenant | recommended per-tenant | 2 |
| 11 | Rewards `(kind, unit)` shared vocabulary vs. per-business | recommended shared | 3 |

Doors 4 and 7 are the two still genuinely open, and both need answering before
Phase 1 writes code — 4 because it changes what Phase 0's migration contains, 7
because it changes how Phase 1's session works.

---

## 11. A note on where this makes the later custody move harder

You asked me to flag anything that would make a later move to destination
charges or a partner escrow provider more expensive. Two things:

1. **Milestone `amount_cents` stored on the engagement (door 8) is the right
   call and makes escrow *easier*, not harder** — the amount to hold is already
   a first-class number rather than something reconstructed from Stripe.
2. **The genuine friction is `payments_core`'s adapter surface.** Its verbs are
   money-moving verbs on a *connected account* (`create_booking_checkout`,
   `create_refund`, `is_connected`), and the seam "grows a verb the day a second
   call site needs it — never speculatively." Escrow needs verbs the seam does
   not have and would not naturally grow: hold, release, reverse-a-hold. That is
   a seam extension, not a rewrite, and the adapter pattern is exactly what
   makes it survivable — but do not let Phase 1 add a *fourth* place that talks
   to Stripe directly, or the later move becomes four migrations instead of one.
   **Every payment call in Phase 1 goes through `payments_core`.** That single
   discipline is what keeps the custody option open.
