# Two-Sided Client Layer — Audit & Pressure Test

**Status:** Parts 1 and 2 only. Part 3 (the phased plan) is deliberately not
written — Kevin reads and responds first.
**Date:** 2026-08-31
**Scope read:** `kmj-intake-server` (this repo) only.
**Method:** read the modules, the migrations on disk, and the architecture
docs. No code written. No live database queried.

---

## 0. What I did NOT verify, stated up front

Four honest limits, because the rest of this document is only worth reading
if you know where its floor is.

1. **I did not read the frontend repo.** Every claim about what a
   practitioner *sees* is inference from the backend contract. Where the
   answer depends on React, I say so.
2. **I did not query the live database.** Migrations on disk are not
   migrations applied. This repo has already been bitten by exactly that:
   `vertical_registry.KNOWN_GAPS` carries a self-correction saying the
   nonprofit blueprint file existed for four weeks while the table held zero
   rows, and that a closure note which "cites a file has only checked that the
   file exists." Assume the same could be true of anything below marked
   *(schema on disk)*.
3. **Three tables I could not find a `CREATE TABLE` for in this repo:**
   `contacts`, `custom_modules`, `module_entries`. They are plainly live —
   dozens of modules read and write them — but their DDL predates the
   migration ledger or lives elsewhere. Anything I say about their *columns*
   is inferred from query strings, not read from schema.
4. **`docs/plans/` did not exist before this file.** If there is a planning
   convention I should have matched, I did not find it.

**Confidence key used below:** *verified* = I read the code that does it ·
*inferred* = consistent across several call sites but not stated anywhere ·
*uncertain* = I am guessing and flagging it.

---

# PART 1 — THE AUDIT

## 1.1 Identity and tenancy

### What exists

**The tenant root is `businesses.owner_id`.** *(verified)*

**The practitioner-side seat ladder is real and well built.** `viewer <
member < admin < owner`, resolved by `business_users_router.role_of` against
`business_users`, ranked by `_ROLE_RANK`. The chokepoint is
`business_access.py` — a dependency factory (`business_access(min_role)`)
plus an imperative twin (`assert_access`) for handlers whose `business_id`
arrives in a body or multipart form rather than a path or query.

Three properties of that module matter for this evaluation, and all three are
deliberate:

- It **depends on `sb_clients.authed_request`, not `require_user`**, because
  `authed_request` both verifies the JWT *and* binds it to a request
  contextvar so PostgREST helpers forward the caller's token and RLS
  evaluates a real `auth.uid()`. Swapping in a plain `require_user` would
  tighten authorization while silently disabling RLS underneath it.
- It answers **404, never 403**, for both "no such business" and "you have no
  role here" — so a stranger cannot use the error code to confirm a guessed
  id is real.
- It **fails closed**: a role check that cannot run raises 503, not a pass.

**There is already a cross-tenant identity in the system.**
`business_collaborators` *(schema on disk:
`__migrations__/2026_06_09_phasei3_pr3_collaborators.sql`)*:

```
id · business_id · user_id (NULL until accept) · invited_email
role   CHECK IN ('accountant','viewer','editor')
status CHECK IN ('pending','active','revoked','expired')
token · invited_by · invited_at · accepted_at · revoked_at · expiration_at
```

One accountant, one Supabase account, invited into several practices, each
grant independently revocable. **This is the shape a client account wants**,
and it is already in production.
`business_collaborators_router.is_active_accountant` is even written as "a
reusable check for future cross-router grants."

**There is already a client-side auth substrate.** `customer_token.py`:
HMAC-SHA256 over a `{biz, cus, iat, exp}` payload, `hmac.compare_digest`,
90-day TTL, and a `require_customer_token_dep` dependency that enforces four
steps in a fixed order — signature/expiry, then `claims.biz == path
business_id`, then reload the `business_customers` row (so revocation is a
row delete), then yield a frozen `CustomerContext`. Handlers never see the
raw token and cannot skip a step.

**The client record itself** is `business_customers` *(schema on disk:
`supabase/business-customers-migration.sql`)*:

```
id · business_id → businesses(id) ON DELETE CASCADE
contact_id → contacts(id) ON DELETE SET NULL   (nullable)
email · name · created_at
UNIQUE (business_id, lower(email)) WHERE email IS NOT NULL
```

Deliberately two records per human: `business_customers` is the *auth*
identity, `contacts` is the *CRM* record, joined by the nullable
`contact_id`. Anonymous walk-ins get a `business_customers` row with no
email and no contact.

### What exists but is shaped wrong

**`business_customers` has no `user_id` and cannot span tenants.** The row is
`ON DELETE CASCADE` from one business, uniqueness is scoped
`(business_id, email)`, and the token binds exactly one `(biz, cus)` pair.
One human who is a client of three practitioners is three unrelated rows with
three unrelated tokens and no way to know they are the same person. Item 1's
"single identity" requirement is a schema change, not a feature.

**Its RLS policy is practitioner-only, and it is the `FOR ALL` shape:**

```sql
CREATE POLICY business_customers_owner_all ON public.business_customers
  FOR ALL TO authenticated
  USING  (business_id IN (SELECT id FROM businesses WHERE owner_id = auth.uid()))
  WITH CHECK (...same...);
```

A logged-in client hitting PostgREST with their own JWT sees zero rows —
including their own.

**The token secret is global.** `CUSTOMER_TOKEN_SECRET` is one value for
every business, with a `TODO(phase-c-x)` in the file saying per-business
secrets are needed "before first real practitioner goes live." Rotating it
invalidates every client link on the platform at once. This is a live debt
that a client portal makes considerably worse, because the blast radius stops
being "booking links" and becomes "everyone's account."

### The honest answer on RLS

> *Can the policies express "this row is visible to the practitioner and to
> one specific client," or is that a rewrite?*

**Structurally expressible. Practically a rewrite — but not for the reason it
looks like.**

The mechanical part is easy and the pattern is already established.
`docs/RLS_MODEL.md` Rule 2 requires cross-table checks to go through
`SECURITY DEFINER` helpers (`is_business_owner`, `is_business_member`,
`is_business_admin`, `is_business_collaborator`). A fifth helper —
`is_business_client(business_id, auth.uid())` — is the same shape as the four
that exist.

Three things make it hard anyway:

1. **Today's policies scope by BUSINESS. A client needs scoping by ROW.** The
   universal predicate is `business_id IN (SELECT id FROM businesses WHERE
   owner_id = auth.uid())`. Its client analogue is not
   `is_business_client(business_id, auth.uid())` — that hands every client
   every row in the tenant. It has to be "this row *belongs to* this client,"
   and **most tables have no column that says so.** `module_entries` carries
   the link as `data->>'contact_id'` — a jsonb key with no FK, no index
   guarantee, and no NOT NULL, queried by `data=cs.{"contact_id":"…"}` in
   `contacts_router.related_entries`. A security boundary cannot rest on an
   optional jsonb key. Making rows client-scoped means adding a real column
   to every table a client may read, and backfilling it.

2. **Rule 3 is a live trap here.** Permissive policies OR together, so a new
   client-visible policy sitting next to the owner policy *widens* the table.
   That already caused a production hole on invoices / social_accounts /
   email_replies / business_profiles (fixed 2026-07-13). Every table touched
   by a client policy needs the `pg_policies` `qual = true` audit re-run.

3. **Rule 2's 42P17 recursion risk is exactly this shape.** A client policy
   is inherently cross-table — row → engagement → client → `auth.uid()` — and
   an inlined `EXISTS` between mutually-referencing tables is precisely what
   caused the outage that `2026_06_10_hotfix_rls_recursion.sql` fixed.

### The real blast radius (this is the finding)

**RLS is the backstop, not the gate.** Per `docs/RLS_MODEL.md`, the reliable
layer is the app-layer check, and the backend reads and writes with the
service-role key *after* `business_access` passes.

So the blast radius of a second account type is not measured in RLS policies.
It is measured in **handlers**. `business_access.py`'s own docstring counts
**446 handlers that take a business id from the caller**, and says roughly
half still have no check in the body. Every one resolves authority through
exactly one ladder — `role_of` against `business_users`. A client has no
`business_users` row, so `role_of` returns `None`, so `_rank(None) = 0`, so
**every business-scoped endpoint on the platform answers 404 to a client by
construction.**

That is the good news and the bad news in one sentence. The good news: there
is no accidental exposure — a client account cannot leak anything, because
nothing will talk to it. The bad news: "add a client account type" is not a
policy change. It is a decision about whether clients enter through the
existing ladder (as a rank below `viewer`) or through a **parallel,
deliberately separate surface** — and that is the biggest one-way door in the
whole proposal. See Part 2.

---

## 1.2 The vertical-aware terminology system

### What exists

**There are 14 canonical verticals, not seven.** *(verified —
`vertical_registry.CANONICAL`)*: coach, consultant, creative, course_creator,
financial_educator, fitness_wellness, service_provider, therapist,
personal_services, contractor, lawyer, ministry, nonprofit, custom. The
"seven verticals" framing survives in older comments (e.g.
`customer_balances.py`'s audit note) and is stale.

`vertical_registry.py` is the reconciliation spine across five historically
divergent maps, with a drift test and a shrinking `KNOWN_GAPS` list.
`resolve()` flattens a large alias table (the lawyer and contractor alias
sets are extensive) to a canonical key.

**Terminology** is `vertical_terminology.py`: `BASE_TERMS` plus per-vertical
overrides, resolved `VERTICAL_TERMS[type][k] or BASE_TERMS[k] or k`, with
`apply_substitutions()` expanding `{term:appointment}` tokens in static
templates. Per-business overrides exist on top
(`terminology_overrides_router.py`).

The client noun is already covered everywhere it matters: lawyer / coach /
consultant / creative / therapist / fitness → **Client**; ministry →
**Member**; course_creator → **Student**; nonprofit → **Donor**; contractor →
**Customer**; personal_services → **Client** (Kevin overruled "Guest" on
8/18).

### What is shaped wrong

**The server dictionary is a hand-maintained mirror of the frontend's
`dictionary.ts`.** Its own docstring: "kept in lockstep manually for v1." A
client portal doubles the number of surfaces that must agree, and the portal
is the one surface where getting the noun wrong is *visible to the
practitioner's own client*.

### Where it breaks

**It does not break on the noun. It breaks on three verticals for reasons
that have nothing to do with terminology.**

1. **Therapist — and it is not the PHI you are expecting.**
   `vertical_scope.py` blocks clinical modules for therapists with a
   multi-word keyword list, checked at the two seams where custom modules are
   created, and asserted by tests. The reasoning is stated plainly: storing
   session content makes the platform a HIPAA business associate, requiring a
   BAA with *every* downstream processor — model provider, Supabase, Twilio,
   Stripe — and "none of that is in place, and none of it is a checklist row:
   it is a legal posture."

   `check_module_scope()` inspects **module name, slug, description, and
   field labels**. It does not — and cannot — inspect *entry content*.

   Today that is fine, because the only person typing into this tenant is the
   practitioner, who is bound by their own licence. **A client portal opens a
   client-authored free-text channel into the tenant.** The moment a therapy
   client can type into a box, "I've been having panic attacks since the
   medication change" lands in your database, and no keyword list at
   module-creation time was ever going to stop it. That is not a terminology
   break. It is the HIPAA boundary moving from *what the practitioner may
   build* to *what a client may say*, which is a fundamentally weaker place to
   enforce it.

2. **Ministry and nonprofit — giving is a locked table.** Per
   `restricted_modules.py`, `access_level:"restricted"` entries (the ministry
   Giving module is the named example) live in `restricted_module_entries`,
   where the anon key is **REVOKEd**, the table is out of the realtime
   publication, access is **business-owner-only** (explicitly *not* the seat
   ladder yet), and every read/write/denial is written to
   `restricted_module_access_log`. A giving history is the single most obvious
   thing a member would want in a portal, and it is the single most
   locked-down table in the system. Also note: `action_registry` marks donor
   giving records **`sensitive`**, which `may_expose_to_agent()` refuses
   *regardless of read-ness* — the file calls this out as the exact case where
   "can this break anything" and "may a third party see it" diverge.

3. **Lawyer — trust accounting.** IOLTA language is wired
   (`trust_account` / `trust_deposit` / `trust_disbursement`), and
   `feature_gates` puts `vertical_ledgers` at Professional. Showing a client
   their trust balance is a regulated disclosure in most jurisdictions, not a
   UI feature. *(uncertain — I am reading the code, not the bar rules.)*

**Where it works cleanly:** coach, consultant, creative, course_creator,
personal_services, fitness_wellness, contractor, service_provider. That is 8
of 14 with no structural objection.

---

## 1.3 Bookings and availability

### What exists — and it is more than you may think

A **complete, live, anonymous-to-authenticated client funnel** already ships:

| Surface | File | Auth |
|---|---|---|
| `GET /widgets/booking/{biz}/config-anon` | `booking_widget_router.py` | anon, 10/IP/hr |
| `POST /widgets/booking/{biz}/book-anon` | same | anon, 10/IP/hr |
| `GET /widgets/booking/{biz}/config` | same | customer token |
| `POST /widgets/booking/{biz}/book` | same | customer token |
| `POST /widgets/request-fresh-link` | same | anon, 10/IP/hr |
| Hosted branded page `<slug>.mysolutionist.app/book` | `booking_page_router.py` + `booking_page_renderer.py` | public |
| Embeddable widget | `static/embed.js` (built in the frontend repo) | — |

Plus `availability.py`, `availability_engine.py`, `availability_router.py`,
`booking_series.py`, `booking_confirmation_emails.py` (already
terminology-aware).

### Foundation or dead end?

**Foundation, and specifically the identity half is already written.**

`POST /book-anon` does, in one handler, exactly the provisioning a client
portal signup needs: creates the `business_customers` row, links or creates a
`contacts` row deduped by email, creates the appointment, mints a token,
returns it. Swap "mints an HMAC token" for "creates or links a Supabase auth
user" and that is a client registration flow. Nothing about it is throwaway.

`booking_page_renderer.py` is also the **white-label precedent already in
production** (item 2): brand kit lifted from `settings.brand_kit` and applied
as CSS custom properties on `:root` so the embedded widget inherits the
practitioner's colors automatically, logo + name + tagline header, full
`<head>` with OG tags and canonical URL, and a small "Powered by Solutionist"
footer. The audit line for it (E4) is literally "practitioner brand + small
Solutionist attribution footer." **Item 2 is not a new capability. It is an
existing pattern applied to more pages.**

### What is shaped wrong

- **The rate limiter is in-memory, per-dyno**, with a `TODO(phase-c-x)` to
  move to Redis or Postgres. It is the only thing standing in front of the
  anon endpoints, and a login surface raises the stakes on it.
- **`config-anon` returns brand kit + module schema** to anonymous callers at
  10/IP/hr. Fine for a booking form; worth re-reading before it becomes the
  unauthenticated half of a portal.

---

## 1.4 The contract portal

### What exists

- **`contract_agent.py`** — an LLM drafter (proposals, engagement letters)
  that adapts to `voice_profile`, renders a PDF with reportlab, and uploads
  it to Supabase Storage. Owner/admin gated via
  `business_users_router.require_business_admin`.
- **`boldsign_router.py`** — e-sign adapter #1 under the "connect, don't
  build" ruling. `POST /esign/send` (by PDF URL), `/esign/list`,
  `/esign/{id}/refresh`, and a webhook that authenticates two ways (the
  `X-BoldSign-Signature` HMAC *and* looking the document up on our side, so a
  payload naming an unknown document is ignored, never inserted). Completion
  emits `contract_signed` on the event spine.
- **Chief actions** for contract creation, with a `fee_model` enum of
  `flat_fee | hourly | retainer | milestone` and payment clauses that branch
  on it (`chief_of_staff.py`).

### How close is it to a two-sided engagement record?

**Not close. It is a document pipeline, not a record.** *(verified for the
backend; the frontend "contract portal" UI is **uncertain** — I did not read
that repo.)*

Four things a shared engagement record needs, and their state here:

| Needed | State |
|---|---|
| Structured scope (not prose in a PDF) | **Absent.** The artifact is a generated PDF plus a BoldSign document id. |
| Milestones as rows | **Absent for engagements.** `grep -rn milestone` finds only `growth_milestones` (a practitioner-private GROW objective spine), free-text `milestones` fields on projects/objectives, and the `fee_model` enum value. There is no milestone table tied to a client engagement. |
| Deliverables + sign-off state machine | **Absent.** Signature is binary and terminal — BoldSign says signed or not. There is no per-deliverable acceptance. |
| A neutral history neither party authored | **Partially present — in the ledger, not in contracts.** See §1.7. |

One flag while I am here: `contract_agent.py`'s deployment notes instruct
creating a **PUBLIC** Storage bucket named `proposals` with public read AND
**public upload AND public delete** policies on `storage.objects`. If that is
still the live configuration, proposal PDFs are world-readable by URL and
world-deletable — before any client portal exists. *(uncertain — I read the
docstring, not the live bucket. Worth a five-minute check regardless of this
initiative.)*

---

## 1.5 The rewards module

### What Chief actually built: nothing named rewards

This is the finding I most want you to read carefully, because the premise of
item 3 rests on it.

**The archetype enum is closed at four members**: `fallback_generic`,
`booking_calendar`, `work_pipeline`, `event_roster` — pinned by
`__tests__/test_archetype_enum.py`, which exists precisely because "the
readiness audit found the enum stuck at two members."

**There is no `RewardProgress` archetype.** The string appears three times in
`module_spec_generator.py` and every occurrence is a comment or a
placeholder:

- line 222 — a docstring example of what a `component` field might hold
  (`'BookingCalendar' / 'RewardProgressCard'`);
- line 331 — a note that the going-forward nav bucket for "loyalty /
  lifecycle archetypes (RewardProgress, CustomerRoster, etc.)" is
  `"customers"`;
- line 1172 — the **sample text for `archetype_fallback_reason`**: the
  generator's own instructions use "needs a RewardProgress archetype" as the
  canonical example of *an archetype that does not exist*.

So when a barber says "I want a punch card," what Chief emits is
`propose_module_from_intake` → a generated `ModuleSpec` with archetype
`fallback_generic` (or `work_pipeline` if there is a clear status column) and
a mandatory `archetype_fallback_reason` explaining what archetype *would*
have fit. On accept it materializes into `custom_modules` + `module_entries`.
If the intake implies a rule ("on the 7th visit → free cut"), the generator
may also emit a `workflow_definitions` row with a `module_entry.updated`
trigger, shallow-equality conditions, and steps drawn from
`log | emit_event | update_context`.

That is a real, working, practitioner-facing tracker. It is not a rewards
program, and there is no client-visible surface for it. *(verified)*

### Is it per-business data with no client identity attached?

Yes, with one qualifier: **the link exists but it is soft.** `module_entries`
rows may carry `data.contact_id`, which is how
`contacts_router.related_entries` groups a contact's rows across modules
(`data=cs.{"contact_id":"…"}`). But it is a jsonb key: no foreign key, no NOT
NULL, no uniqueness, and not a thing any policy can safely rest on. The
generator's `contact_link` field is guidance to an LLM, not a constraint.

### What attaching identity would require — and the better primitive

Attaching identity to `module_entries` means promoting `data.contact_id` to a
real column with an FK and an index, backfilling it, and then writing a
row-scoped RLS policy on it. That is genuine work on a table that holds every
custom module's data for every business.

**But you probably should not do that, because the right primitive already
exists and is better.** `customer_balances.py`:

- append-only signed rows keyed `(business_id, contact_id, kind, unit,
  delta)`, balance by summation, nothing mutated in place — "this is money
  already handed over, so it gets what the GL gets";
- **one primitive, five money models** already: coach package/session,
  consultant retainer/money, lawyer retainer/hour, contractor deposit/money,
  and **gift_card/money**. "The verticals differ in the WORDS, not the
  mechanics. Resisting five bespoke tables is the whole design";
- `grant()` / `consume()` / `balance()` / `history()` / `describe_balances()`
  already written;
- keyed on **`contact_id`** — the CRM record, not `business_customers.id`.
  Worth noting for whatever identity model you pick.

A punch card is `kind='reward', unit='visit'`. A points program is
`kind='reward', unit='point'`. **A rewards balance is a sixth money model on a
ledger you already shipped, not a new module.**

Its one documented flaw, stated in its own docstring rather than hidden: the
overdraw race. `consume()` reads-then-writes across two PostgREST calls with
no transaction boundary, so two concurrent draws can both see "1 left." It
re-reads after writing and self-corrects by reversing its own row, returning
`overdrawn=True`. The clean fix is a DB function with `SELECT … FOR UPDATE`.
A client-facing redemption surface makes that race *much* more likely to fire
than a practitioner clicking a button.

---

## 1.6 Payments — where Connect actually stands

### What exists *(verified)*

Phase D.4 PR 1 is **live**, not planned:

- `stripe_connect_router.py` —
  `/payments/stripe-connect/{start,callback,disconnect,status}` plus the
  webhook receiver. Owner-gated, one-shot CSRF state, correct separation of
  `redirect_uri` (must match Stripe's registered URI) from the post-exchange
  frontend bounce.
- `stripe_connect_helpers.py` — OAuth with **`scope=read_write`**, code
  exchange → `businesses.stripe_account_id`, `fetch_account`, `deauthorize`,
  webhook signature verification.
- `stripe_checkout_helpers.py` — every money call carries
  **`headers={"Stripe-Account": acct_…}`**, and
  `application_fee_amount_cents` is plumbed through with **v1 = 0**.
- `payments_core.py` — a provider-agnostic adapter seam. New payment code
  imports `payments_core`, never a `stripe_*` module; `provider_for(biz_row)`
  reads `settings.payments.provider`. Adding a processor is one adapter class
  and one registry line.

### What this means, precisely

**You are on Standard Connect with DIRECT charges.** The charge is created *on
the practitioner's connected account*. Funds settle in **their** Stripe
balance. The platform never holds a cent.

This is exactly "build the intelligence, rent the plumbing," already
implemented, and it is the right posture. It also means the following, which I
do not think can be softened:

> **Milestone-based release of held client funds is not possible in this
> posture, and getting it would cost you the posture.**

Direct charges plus `application_fee` cannot hold money. To hold client funds
against milestones, the money has to land somewhere you control — destination
charges or separate charges-and-transfers **on the platform account**, with
funds sitting in *your* Stripe balance until you release them. That is the
custody line. Stripe will let you do it; Connect's terms and your state's
money-transmission analysis are the constraint, not the API. Stripe's own
framing is that platforms holding funds for later payout take on the
regulatory burden of doing so.

### The honest path

**Milestone-gated *billing*, not milestone-gated *custody*.** All three legs
already exist or are cheap:

1. **Authorize now, capture on sign-off.** `capture_method: manual` holds an
   authorization ~7 days without moving money. Real commitment, zero custody.
   Good for deposits and short milestones; useless for a three-month phase.
2. **Milestone → invoice.** Sign-off is a ledger event; the event fires an
   invoice on the connected account. The client's money goes direct to the
   practitioner, and the *record* of what was owed and when lives on our
   rails. This is the one that scales, and it is mostly wiring between things
   that exist.
3. **Deposit math already exists.** `payments_core.compute_deposit_cents()` is
   "the ONE place deposit amounts are computed," handling percent and flat
   with sane degradation (a computed deposit ≤ 0 or ≥ full price falls back to
   full price — "a misconfigured $0 deposit must not create a free booking").

The strategic claim survives intact: **you own the record of what was agreed
and what was delivered; Stripe moves the money.** That is a better moat than
escrow anyway, and it is the only version that does not put a money
transmitter licence on your roadmap.

---

## 1.7 The trust layer and the action ledger

### What exists *(verified — and this is the strongest thing in the repo)*

`audit_log` **is** the ledger (Stages 0–4 shipped 2026-08-03; Kevin ruled it
evolved rather than replaced). Six fields: `created_at` · `business_id` (never
null) · `actor_id` + `actor_type` · `verb` (controlled vocabulary,
`action_types`, 204 verbs synced at boot from `action_registry`) ·
`subject_refs` (`[{type,id}]`, GIN-indexed) · `authorized_by` (the *rule*, not
the actor).

Guarantees that are database-level, not application-level — which matters
because the whole backend writes as `service_role` with
`rolbypassrls = true`, so an application promise binds nobody:

- `BEFORE UPDATE` / `BEFORE DELETE` triggers **raise**. Even service-role
  cannot rewrite a row.
- `sequence` assigned per tenant under an advisory lock; `prev_hash` /
  `row_hash` chain. Python never sets any of the three.
- `ledger_chain_state` has **no FK to businesses**, so it survives erasure and
  a gap stays provable. `ledger_tombstones` outlives the business it
  describes. The one sanctioned deletion path, `ledger_erase_business()`
  (GDPR), writes the tombstone *first*.
- **24 database triggers** write ledger rows with no Python involved at all.
- `policy_engine.py` produces `authorized_by` — one evaluator replacing
  authorization that had been scattered across six mutually unaware
  subsystems.

Three doors, never sharing a credential: the app (JWT **plus** a 15-minute
`ledger_unlock` step-up, held in memory and never `localStorage`); the signed
auditor link (`auditor_links.py` + `auditor_portal.py` — the token becomes a
scoped cookie and never renders a page, revocation reaches the cookie, HMAC
domain-separated from the other two credential types); and the file
(CSV/PDF/JSON). Every auditor view writes a ledger row.

### Does it already serve as dispute evidence?

**It records business facts, not system events — the premise of the question
is better than you feared. But it cannot settle a scope dispute, for a
different reason.**

The verbs are business verbs (`create_invoice`, `send_invoice`,
`book_appointment`), `subject_refs` points at real business objects, and the
DB triggers mean facts get recorded whether or not Python remembered to. This
is not a syslog.

The gap is deliberate and is in `LEDGER_SELECT`:

```
id, actor_type, actor_id, verb, ok, error, summary, source,
created_at, target_type, target_id, sequence, authorized_by,
subject_refs, verb_registered
```

**No `payload`. No `result`.** `auditor_portal.py` states the reason: "record
CONTENTS never leave through this door." So the ledger can prove,
tamper-evidently and in sequence, *that* an invoice was created, by whom,
under which rule, at which millisecond — and it deliberately cannot show *what
the invoice said*.

For a client dispute — "that was not the agreed scope" — that is the wrong
half. You would be able to prove the event and not the content. Closing it
means either widening the select (which `auditor_portal.py` warns is a
one-place change with a wide reach, and which would push record contents
through the auditor door too) or putting the agreed scope in a *separate*
signed, versioned engagement record and letting the ledger point at it via
`subject_refs`. The second is right.

### The one-way door in the ledger

**`actor_type` has a CHECK constraint allowing only
`('user','chief','agent','system')`.** *(verified — stated in `audit_log.py`'s
docstring and enforced in the table.)*

There is no client actor. Non-chat writers already work around this by writing
`actor_type='system'` and carrying real identity in `actor_id` ('scheduler',
'trust-track'), with the frontend rendering `actor_id` as the display name.

Two-sided attribution needs either a fifth `actor_type` — a CHECK change on an
append-only table whose historical rows can never be rewritten to match a new
convention — or the `actor_id` workaround, which means "who did this" is
encoded by convention rather than by constraint on the one table whose entire
value proposition is that it does not rely on convention. **Pick this one
deliberately and early.** It is cheap now and permanent later.

---

## 1.8 API surface — could a third-party agent authenticate today?

### Yes. Better than expected. *(verified)*

This is the item where you are furthest along.

- **`mcp_server.py`** — a real MCP endpoint (JSON-RPC 2.0: `initialize`,
  `notifications/initialized`, `tools/list`, `tools/call`, `ping`), transport
  hand-written on purpose because the official SDK's Streamable HTTP needs an
  ASGI lifespan and this app starts its scheduler in the deprecated
  `on_event("startup")`. Kill switch `MCP_ENABLED=off`.
- **`mcp_tokens.py`** — scoped, named, revocable credentials. HMAC format
  shared with `customer_token.py`. **Only the SHA-256 hash is stored**; the
  plaintext is returned once by `mint()` and is then unrecoverable. Two-step
  verification by design: `verify_mcp_token()` (pure crypto, no DB — cheap
  enough to run first) then `is_revoked()` (one indexed read on `jti`), so
  "revoke" means "stops working now," not "stops working when it expires."
  Fail-closed on every ambiguous case — explicitly the opposite posture from
  the practitioner-facing modules, "because this is the surface where being
  wrong is expensive."
- **`mcp_oauth.py`** — OAuth 2.1 with RFC 7591 dynamic client registration, so
  claude.ai's connector dialog and a phone can connect. The access token it
  returns *is* an ordinary `mcp_tokens` credential — same table, same
  revocation, same Mission Control row. `mcp_server._caller_from_token` needed
  no change, which the file itself calls "the strongest available evidence
  that the seam is in the right place."
- **`agent_runs`** *(schema on disk)* — per-call audit trail: business_id
  (nullable, "null when refused BEFORE a business could be resolved"),
  surface, tool, actor, allowed, ok, duration_ms, error, `arg_keys` (keys, not
  values), detail. **Item 6's "audit trail of which agent did what" already
  exists** for the practitioner side.
- **The tool list is derived, never hand-maintained** —
  `action_registry.may_expose_to_agent()` decides, and `mcp_server` "ASKS it
  and never second-guesses it," because a second list would drift and "that
  drift is a security bug rather than a tidiness one." Today: 19 read verbs (5
  `ui` verbs excluded, 22 class-C verbs can never appear at any scope).
- **Writes are designed and dormant.**
  `may_expose_to_agent(verb, allow_writes=True)` already admits class A and B
  writes and refuses class C and anything unclassified. The only reason no
  agent can write is that `mcp_tokens.KNOWN_SCOPES = (SCOPE_READ,)` — a
  one-tuple. The permission model behind item 6 is **built**; it is switched
  off at a single constant.

### What is shaped wrong

**It is single-tenant and owner-only, and the code says so in as many words.**
`mcp_oauth.py`: the owner proves identity by pasting a live Agent Access key
into the consent screen, and

> "This does NOT generalise to customers. Stage 4 needs real per-user login.
> Single tenant is what makes this acceptable, and the moment a second tenant
> exists it stops being."

That is the exact boundary item 6 crosses. A client's agent needs real
per-user login, which is item 1 — **item 6 is blocked on item 1 and on nothing
else.** The scopes, the revocation, the audit trail, the derived tool list and
the write gate are all already there.

Also: `mcp_server` platform routes are hard 403 "platform owner only," and
`action_registry`'s `sensitive` bit (donor giving) refuses agent exposure
independently of read-ness.

**`agent_readiness.py`** is the outbound half (item 7 adjacent): a UCP
`/.well-known/ucp` probe with a measured starting position of **0 of 16** real
suppliers, and a careful soft-404 defence (four majors answer 200 with an HTML
app shell). A tripwire for the day agentic commerce arrives, not a feature
anyone can use this week.

---

## 1.9 Metering — who pays when a client generates activity

### What exists

- `api_usage_logger.log_api_usage(business_id: Optional[str] = None, …)` —
  **optional**, defaulting from `billing_context.current()`.
- `billing_context.py` — a ContextVar. Per-task, so concurrent requests cannot
  cross-read; an explicit `business_id` always wins. It is "bookkeeping, not
  authorization — being 'in' a business's billing context grants no access to
  it."
- `usage_metering.py` — weighted Chief-interaction units; prepaid model
  (allowance then `credit_ledger`), no postpaid overage, running dry
  soft-blocks **AI only** while bookings/invoices/bookkeeping never stop.
- `spend_guard.py` — two ceilings (per-business $25/day default, platform $50
  default), fail-**open** by doctrine.

### Where the context is actually set — and the hole

`billing_context.set_current()` is called in exactly **four places** *(verified
by grep)*: `business_access.py` ×2 (the dependency and `assert_access`),
`chief_of_staff.py` ×1, `ai_proxy.py` ×1.

**None of them is on a client-token path.**
`customer_token.require_customer_token_dep` verifies four things and sets no
billing context.

So: **an LLM call reached through a client credential logs `business_id:
None`.** And `spend_guard.py` states the consequence exactly — unattributed
spend "counts toward the platform ceiling only; it cannot trip anyone's
per-tenant one." A runaway on a client surface would burn the **platform**
ceiling, which is the one whose failure mode is Chief going dark for every
other paying practitioner. That is precisely the failure the two-ceiling
design was built to prevent, and a client portal would reintroduce it through
the one door the guard cannot see.

### The good news: the precedent is already shipped and correct

`site_concierge.py` is **an anonymous, public, client-facing AI surface that
already exists in production** — a chat agent on practitioners' composed
sites. It is not Chief (zero imports from Chief action modules, zero verbs; it
can answer, link, capture a lead, or escalate, and reads a fenced public-only
knowledge set so "leaking private data is structurally impossible").

Its billing model is the answer to your question:

- gated on `settings.concierge.enabled` **AND** the `site_concierge` feature
  gate (Professional tier) **AND** `billing_limits.require_units(business_id)`
  per reply;
- meters at weight 1 per reply via an **explicit**
  `log_api_usage(business_id=…)`, not via context inheritance;
- has daily caps as day-one spend protection independent of enforcement;
- and a **graceful-degrade law**: when any cap trips or the model fails, it
  returns `{degraded: true, capture: true}` and the widget falls back to lead
  capture. "It never shows an error dead-end."

**The practitioner pays for their client's AI activity, metered by endpoint
weight, capped daily, degrading to something useful rather than to an error.**
That is already ruled, already built, and already the right answer. Any client
portal should copy this file's posture literally.

It also carries the sensitive-vertical fence: therapist businesses get
scheduling/billing/admin/location answers only, and clinical-adjacent asks hit
a pinned deflection **without ever reaching the model**. Plus injection armor —
visitor messages are treated as data.

---

## 1.10 Scorecard

| # | Item | Exists | Shaped wrong | Missing entirely |
|---|---|---|---|---|
| 1 | Client accounts | `customer_token.py` (HMAC client auth, 4-step dep, revocation-by-delete) · `business_customers` · `business_collaborators` (the cross-tenant shape, in production) · `book-anon` (provisioning flow) | `business_customers` is per-tenant with no `user_id`; its RLS is owner-only `FOR ALL`; one global token secret; the seat ladder has no rank a client could occupy | Cross-tenant identity · row-scoped (not business-scoped) read policies · a client session |
| 2 | White-labeled client experience | `booking_page_renderer.py` — brand kit → CSS vars, logo/name/tagline, OG tags, "Powered by Solutionist" footer · `cloudflare_saas.py` custom hostnames with auto-renewed TLS | — | Nothing structural. This is the cheapest of the seven. |
| 3 | Rewards as the on-ramp | `customer_balances.py` — append-only `(business_id, contact_id, kind, unit, delta)` ledger, 5 money models, grant/consume/balance/history | `module_entries.data.contact_id` is a soft jsonb link, not a constraint · `consume()` has a documented overdraw race | **No rewards module and no `RewardProgress` archetype exist** — the enum is closed at 4 and `RewardProgress` appears only as a fallback-reason example. No client-visible surface for any module. |
| 4 | Shared engagement record | `contract_agent.py` (PDF drafts) · `boldsign_router.py` (e-sign + webhook + `contract_signed` event) · `audit_log` (neutral, tamper-evident history) | Contracts are documents, not records | Structured scope · milestone rows · deliverable sign-off state machine · any client-visible view |
| 5 | Money through the rails | Connect live (OAuth `read_write`, `Stripe-Account` direct charges, `application_fee` plumbed at 0) · `payments_core` adapter seam · `compute_deposit_cents()` | Direct charges **cannot** hold funds — correct for no-custody, fatal for escrow | Milestone→invoice wiring · `capture_method: manual` support. **Escrow is not missing; it is refused by the posture, and should stay refused.** |
| 6 | Agent-accessible by design | `mcp_server` (19 read verbs, derived list) · `mcp_tokens` (scoped/named/revocable, hash-only storage) · `mcp_oauth` (OAuth 2.1 + RFC 7591) · `agent_runs` audit trail · `may_expose_to_agent(allow_writes=True)` already admits class A/B | Owner-only and single-tenant, and the code says it "does NOT generalise to customers" | Per-user login (= item 1) · a client scope in `KNOWN_SCOPES` (currently a one-tuple). **Blocked on item 1 and nothing else.** |
| 7 | Network later | `referrals.py` (practitioner→practitioner, `?ref=` codes, invite-only coexistence) · `entity_groups_router.py` (one owner, many businesses) · `agent_readiness.py` (UCP probe) | Rewards are manual; double-sided deferred | Client-side discovery · benchmarks. **Not planned, per instruction. See Part 2 for the two decisions that would foreclose it.** |

---

# PART 2 — PRESSURE TEST

Everything above is factual. Everything below is opinion, and I have tried to
make it the useful kind.

## 2.0 The short version

**The direction is right and the sequencing in the brief is wrong.** Item 1 as
written — "a client gets their own login" — is not the first thing to build.
It is the most expensive, most irreversible, and least
independently-valuable item of the seven, and three of the other six can ship
without it.

I do not think the whole direction is wrong. I think you have correctly
identified where the moat is (item 4 — the neutral record — and item 6 — the
agent rails) and then proposed to pay for the least valuable part of it first
(the login).

## 2.1 The most expensive relative to value: item 1, client accounts

Not because auth is hard. Because of the number I found in
`business_access.py`'s own docstring: **446 handlers take a business id from
the caller.** Every one resolves authority through one ladder, and a client is
not on it.

Adding a second account type means answering, for each of those surfaces,
"what does this return to a client?" You cannot answer it in a policy. There
is no default that is safe — return-nothing breaks the portal,
return-something is a data leak. And the app layer, not RLS, is where the
answer has to live, because the backend reads as service-role.

Meanwhile the *value* of a login, on its own, to a practitioner is close to
zero. Their client can already book (anonymously), pay (Stripe), sign
(BoldSign), and be messaged (SMS/email). A login adds a password to remember
in exchange for nothing they did not have. **Every dollar of item 1's value is
borrowed from items 3, 4 and 5.** Build those first and let the login arrive
when there is something behind it worth logging into.

## 2.2 What breaks that you have not thought about

**(a) The therapist vertical inverts, and the mitigation you have does not
reach.** Covered in §1.2. Restating the shape because it is the one I would
lose sleep over: today PHI can only enter the tenant through a practitioner
who is personally licensed and whose module names get keyword-checked. A
client portal creates a **client-authored free-text channel**, and
`check_module_scope()` inspects module *names and field labels*, never entry
content. The HIPAA boundary moves from "what may be built" to "what may be
said," which is a much weaker place to hold it. My read: **therapist ships
last, or ships with no free-text input at all.** Not a terminology problem. A
posture problem.

**(b) The support burden transfers to you, and you have no channel for it.**
Today every human in the system is your customer. The moment clients have
accounts, the person who cannot log in is *your practitioner's client*, and
they will contact whoever is easier to find. There is a support-ticket path in
the build bridge for non-owners, but nothing shaped like consumer support.
This is not an engineering cost, which is why it does not show up in an
engineering audit and why I am putting it here.

**(c) Account lifecycle and GDPR get a second subject.**
`account_lifecycle.BUSINESS_CHILD_TABLES` (~148 entries) drives export and
delete, and the RLS checklist requires every new tenant-scoped table to be
added to it. But it is keyed on **business**. A cross-tenant client identity
is a data subject who exists in *several* businesses and belongs to none of
them. "Delete my account" from a client, and "delete my business" from a
practitioner who has clients shared with other practitioners, are two
questions the current model cannot answer. `ledger_erase_business()`'s
tombstone design is the right precedent and it is business-shaped.

**(d) The client is a spam vector into a system with real deliverability
stakes.** Consent, STOP/START, quiet hours and A2P are built
(`consent_router.py`, `ai_disclosure.py`) — for outbound. A logged-in client
who can message a practitioner is an inbound path with no equivalent
machinery, on infrastructure where your Twilio and Resend reputations are
shared across every tenant.

**(e) The `proposals` Storage bucket.** §1.4. If it is still public-read /
public-upload / public-delete, that is a live problem today, independent of
this initiative, and a client portal would put a spotlight on it.

**(f) The overdraw race becomes reachable by strangers.** §1.5.
`customer_balances.consume()` self-corrects and is honest about it, but it was
written for a practitioner clicking a button. Client-facing redemption at
10 req/IP/hr behind an in-memory per-dyno limiter is a different threat model.

**(g) One global `CUSTOMER_TOKEN_SECRET`.** Already flagged with a TODO in the
file. Today a rotation breaks booking links. After a portal, it logs out every
client of every practitioner simultaneously.

## 2.3 The cheaper sequence that reaches the same strategic position

The strategic position you want is: **the neutral record of what was agreed
and delivered lives on our rails, and both sides' agents can read it.** Notice
that a client *login* is not in that sentence.

Three of the seven ship with **no new identity model at all**, because
`customer_token.py` already exists:

- **The shared engagement record (item 4)** can be a signed, scoped, revocable
  link — the exact pattern `auditor_portal.py` already proves, down to the
  token-becomes-a-cookie trick, the revocation reaching the cookie, and every
  view writing a ledger row. A client clicks a link in an email and sees
  scope, milestones, and a sign-off button. No password. No account. Nothing
  to support.
- **The rewards balance (item 3)** is a sixth `kind` on `customer_balances`,
  read through the same signed link.
- **Milestone→invoice (item 5)** needs no client identity whatsoever. Sign-off
  is a ledger event; the invoice fires on the connected account.

That is items 3, 4 and 5 delivered on infrastructure that shipped months ago.
Identity becomes an **upgrade** you offer when a client is already using the
thing — "you have balances with three practitioners, want one login?" — which
is also, not coincidentally, the only honest way to get the cross-tenant
identity of item 1: **let it be earned by the data rather than assumed by the
schema.**

And it inverts the risk. The expensive irreversible decision gets made last,
with real usage data, instead of first, on a hypothesis.

## 2.4 Conflicts with the locked architecture disciplines

| Discipline | Verdict |
|---|---|
| **Every module Chief-callable** | **Reinforced, with a trap.** A client-facing surface must not become the first thing Chief cannot reach. But the inverse trap is worse: Chief's ~189 handlers are written for a practitioner and would happily read cross-client data. `may_expose_to_agent` + the `sensitive` bit + class-C exclusion are the right gate and they were designed for *outside agents*, not for *inside-the-tenant-but-not-the-owner* callers. That third caller type does not exist yet. |
| **Closed archetype enum** | **Tested, and it should hold.** The pressure to add `RewardProgress` will be immediate. Resist it. §1.5 argues rewards are a `customer_balances` kind, not an archetype — which is the enum working as designed, forcing the question "is this really a new surface shape?" and getting the answer "no." |
| **The build gate** | **No conflict.** `handle_queue_build_request` is owner-gated and fail-closed; non-owners get a support ticket. A client must land in the non-owner branch and must never see builder/GitHub/Claude Code language. Worth an explicit test the day clients exist. |
| **No action without authority** | **Direct conflict, and it is the crux.** `policy_engine` produces `authorized_by` for actors it knows: user, chief, agent, system. A client acting on their own behalf inside someone else's tenant is a **fifth actor class with no rule to cite**. Until `policy_engine` can name the rule that authorizes a client's action, every such action writes a ledger row that fails the discipline's own test — "Chief did this" vs "Chief was permitted to do this, here is the rule." **Extend `policy_engine` before anything a client does writes a row.** |
| **Client data never leaves the system** | **Reinforced and strained.** `site_concierge`'s fenced public-only knowledge set is the model to copy. The strain is item 6: a client's agent reading on their behalf is, by construction, client data leaving through a third party the practitioner never chose. The disclosure and consent surface for that does not exist. |

## 2.5 Metering — the specific answer

**Who pays: the practitioner.** Already ruled, already shipped, in
`site_concierge.py`. Do not re-litigate it and do not invent a client-pays
model — a client will not enter a card to check a punch-card balance, and a
practitioner will happily pay for something that makes their client come back.

**Where it breaks (§1.9):** `billing_context.set_current()` is called in four
places and none is a client path. Any LLM call reached through a client
credential logs `business_id: None`, and per `spend_guard.py` unattributed
spend "cannot trip anyone's per-tenant one" — it burns the **platform**
ceiling, whose failure mode is Chief going dark for every paying practitioner.
A client surface would reintroduce exactly the failure the two-ceiling design
exists to prevent.

**The fix is small and must be non-optional:** `require_customer_token_dep`
(and any successor client dependency) sets `billing_context` after step 3, the
same way `business_access` sets it only after the access check passes —
bookkeeping follows authorization, never grants it. Then add the client
surfaces to `pricing_config.unit_weights()`, because that table's own rule is
that every key must be a label something **actually logs** (the
`/director/build` weight hole is what that rule is made of).

**And a harder question you should decide explicitly:** every client
interaction is metered against a practitioner who is not in the room. A client
who chats twenty times burns a practitioner's credits with no signal to
either. `site_concierge` answers this with daily caps plus graceful degrade to
lead capture. Copy it exactly. **A client-facing surface that can spend a
practitioner's money without a per-client cap is a support incident waiting for
a date.**

## 2.6 The one-way doors, ranked

1. **Does a client enter through `business_users` as a rank below `viewer`, or
   through a parallel surface?** Everything else follows from this. Ranking
   them into the seat ladder means all 446 handlers silently become
   client-reachable and each must be re-audited — a permission model that
   fails *open* on every handler nobody thought about. A parallel surface (the
   `customer_token` / `auditor_portal` lineage) fails *closed* by default and
   costs duplicated read paths. **I would take the duplication.** Reversing
   this later means re-auditing every endpoint written in between.

2. **`audit_log.actor_type`'s CHECK constraint.** §1.7. Add a client actor
   type deliberately now, or accept forever that client actions are
   `actor_type='system'` with identity smuggled in `actor_id` — convention, on
   the one table whose entire value is that it does not rely on convention. On
   an append-only table, history cannot be migrated to a later decision.

3. **Whether client identity is keyed on `contacts.id` or
   `business_customers.id`.** These are already two records per human.
   `customer_balances` keys on **`contact_id`**; `customer_token` keys on
   **`business_customers.id`**; `business_customers.contact_id` is
   **nullable** with `ON DELETE SET NULL`. Cross-tenant identity is a third
   key above both. Choose the join now; every table added afterward inherits
   it.

4. **Whether the engagement record is a new table or an extension of
   contracts.** A new first-class `engagements` table with milestone and
   sign-off rows is the thing item 6 and item 7 both need to point at. Bolting
   milestones onto the PDF pipeline would be faster and would foreclose both.

5. **Whether the client-facing surface is served from the practitioner's
   domain or ours.** `cloudflare_saas.py` makes per-practitioner hostnames
   real, and each is its own origin — cookies, CSP, and the `auditor_portal`
   cookie-scoping pattern all change with it. Item 2's white-label promise
   pushes toward the practitioner's domain; every session mechanism you write
   before deciding gets rewritten after.

6. **(Item 7, flagged not planned, per instruction.)** Two decisions in the
   near-term work would make a network impossible later, and both are free to
   avoid now:
   - **A client identity with no cross-tenant primary key.** If the first
     client account is `business_customers.id`, there is no "same person" to
     build discovery, portable reviews, or cross-practitioner referrals on.
     You do not need to *use* a global identity in phase one. You need to not
     *preclude* one — a nullable `platform_identity_id` costs nothing today
     and is unrecoverable later.
   - **Rewards balances that are not comparable across businesses.** If
     rewards land as per-business custom modules with free-form jsonb, there
     is never a benchmark. As `customer_balances` rows with a shared
     `(kind, unit)` vocabulary, benchmarks are a query. **The item-3 decision
     and the item-7 option are the same decision**, which is the strongest
     argument in this document for doing rewards on the balance ledger.

## 2.7 My recommendation on the beta-one question

You proposed the rewards program as the phase-one shippable. **I would ship
the shared engagement record instead, and I hold this view with moderate
confidence.**

The case for rewards: genuinely wanted by personal_services and
fitness_wellness, cheap on `customer_balances`, and a natural signup pretext.

The case against it as *first*: it is a loyalty punch card. Practitioners who
want one have Square. It does not exercise the ledger, does not touch Connect,
does not create anything an agent would want to read, and its strategic payoff
is entirely downstream of a login you should not build yet. It proves nothing
about the hard parts.

The engagement record — scope and milestones on our rails, visible to both
sides through a signed link, sign-off firing an invoice on the connected
account, every step a ledger row — is:

- **wanted on its own** by consultant, creative, contractor, lawyer and coach
  (five verticals, and the four highest-value ones);
- **the thing item 6 exists to read**, so the agent story becomes a scope
  extension rather than a new surface;
- **the only one of the seven that produces the dispute evidence** §1.7 says
  the ledger cannot produce alone;
- **shippable with no new identity model**, on the `auditor_portal` link
  pattern;
- and it makes the practitioner unambiguously the hero, which is item 2's
  whole requirement.

Rewards then becomes phase two on the same ledger — cheap, because the balance
primitive and the client-link surface both already exist by then.

**If you disagree, the version of your sequence I would still endorse** is:
rewards first, but built on `customer_balances` (not a custom module), read
through a signed link (not a login), with the cross-tenant
`platform_identity_id` column present and nullable from day one. That keeps
every door in §2.6 open and costs almost nothing extra.

---

## What I need from you before Part 3

1. **§2.6 door 1** — parallel client surface, or a rank in the seat ladder? My
   recommendation: parallel. Everything else in the plan branches here.
2. **§2.7** — engagement record first, or rewards first? I have argued for the
   former and will plan whichever you pick.
3. **§1.2 / §2.2(a)** — do therapists ship in this arc at all? My
   recommendation: not in phase one, and not with free-text ever, until a BAA
   posture exists.
4. **§1.4** — is the `proposals` Storage bucket still public read/upload/delete?
   Worth checking regardless of this decision.
5. Confirmation that **milestone-gated billing, not custody** (§1.6) is
   acceptable as the permanent answer to item 5. If you want real escrow, that
   is a licensing conversation, not an engineering one, and the plan changes
   shape.
