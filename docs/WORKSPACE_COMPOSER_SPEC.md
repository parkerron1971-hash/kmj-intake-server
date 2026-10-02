# Chief Workspace Composer — Phase One Spec

Derived 2026-08-26. The brief referenced `chief-workspace-composer-spec.md`,
which does not exist in this repo or anywhere on the build machine. This
document is the reconstruction, written from the brief, and it is now the
source of truth the code and the validator are built against. If the
original surfaces, reconcile field names against this file — the structure
below is what ships.

Chief is a **workspace composer**. At onboarding it decides what kind of
business this is, then renders a workspace built for that business type —
different structure, different vocabulary. Not a re-skinned generic CRM.

Phase one limits Chief to a **classification** decision, not a design
decision. Five layout presets are hand-authored. Chief reads the intake
answers, picks one, and narrates why. The schema is shaped so phase two can
compose within an archetype without a rewrite.

---

## 1. Primitive registry

Six primitives. These are the only building blocks in phase one. Each takes
a declared data contract and renders it. **No primitive fetches its own
data** — the renderer resolves bindings and hands down plain values.

The registry (`workspace_primitives.py`) is one module, the single source of
truth. Nothing else may declare a primitive.

Each primitive declares:

| key | meaning |
| --- | --- |
| `id` | stable slug used in layout schemas |
| `label` | human name |
| `purpose` | one line, shown in Chief's narration |
| `bindings` | named data contracts, each `required` or not |
| `options` | render options with declared types and ranges |
| `allowed_roles` | which surface roles this primitive may occupy |

A binding is a **collection** or a **scalar**. Collection bindings declare
`fields` — a map of contract field name to type. Required fields must be
bound; optional fields may be omitted. A binding may also declare
`min_items` / `max_items`, enforced against the preset's declared shape.

### 1.1 `timeline_day`

One day, parallel resource lanes, events positioned by start time and
duration. Flags open gaps.

- `lanes` (collection, required) — `id:string`, `label:string`,
  `subtitle:string?`
- `events` (collection, required) — `id:string`, `lane_id:string`,
  `start:time`, `duration_minutes:int`, `title:string`, `subtitle:string?`,
  `state:string?`
- `day` (scalar, optional) — `date:date`

Options: `day_start` int 0-23 (8), `day_end` int 1-24 (20),
`gap_threshold_minutes` int 5-240 (30), `show_gaps` bool (true),
`lane_noun` string ("Resource").

Roles: `lead`, `secondary`.

### 1.2 `priority_docket`

Rows ordered by urgency **in days, not by clock**. Hairline rules,
right-aligned metric.

- `rows` (collection, required) — `id:string`, `title:string`,
  `metric_value:number`, `metric_unit:string?`, `subtitle:string?`,
  `stage:string?`, `owner:string?`

Options: `sort` enum `urgency_days` | `stage` (`urgency_days`),
`metric_label` string ("Due in"), `metric_unit` string ("days"),
`stages` string list (max 8, required when `sort` is `stage`),
`urgent_threshold_days` int 0-90 (7).

The unit is a property of the docket rather than of each row — every row
on one docket is measured the same way — so it is an option, and the
per-row field is the optional override. `sort: "stage"` additionally
requires `rows` to bind `stage` (`field_required_when` in the registry,
enforced by check 2): a stage sort with nothing to sort into is one
undifferentiated pile.

The two sorts are different readings of the same rows, and the polarity
flips between them: under `urgency_days` the metric is time remaining and
low is bad; under `stage` it is time-in-stage and high is bad.

Roles: `lead`, `secondary`.

### 1.3 `week_grid`

Seven day columns, events placed where they fall.

- `week_of` (scalar, optional) — `date:date`
- `events` (collection, required) — `id:string`, `date:date`,
  `title:string`, `time:time?`, `subtitle:string?`, `attendance:int?`,
  `kind:string?`

There is deliberately **no `days` binding**. The seven columns are a
calendar fact, not tenant data; the primitive generates them from
`week_of` (or today). A layout that could bind them could ship a
six-column week.

Options: `week_start` enum `sun` | `mon` (`sun`), `show_counts` bool
(false), `count_noun` string ("attending").

Roles: `lead`, `secondary`.

### 1.4 `attention_queue`

Ordered list of things awaiting a human action, each with an age.

- `items` (collection, required) — `id:string`, `title:string`,
  `age_days:int`, `subtitle:string?`, `action_label:string?`

Options: `age_unit` enum `days` | `weeks` (`days`),
`escalate_after_days` int 1-365 (30), `max_visible` int 3-25 (8).

Roles: `secondary`, `footer`.

### 1.5 `metric_row`

Two to four figures **at rest**. Footer material, never the hero.

- `metrics` (collection, required, 2-4 items) — `id:string`,
  `label:string`, `value:number`, `unit:string?`, `trend:string?`

Options: `format` enum `number` | `currency` | `duration` | `percent`
(`number`).

Roles: `secondary`, `footer`. **`lead` is not permitted** — the "never the
hero" rule is enforced by the registry, not by convention.

### 1.6 `ledger`

Debits and credits with a running balance.

- `entries` (collection, required) — `id:string`, `date:date`,
  `description:string`, `debit:number?`, `credit:number?`,
  `balance:number?`
- `opening_balance` (scalar, optional) — `value:number`

`balance` is optional because no ledger table stores a running balance —
it is an artifact of row order. Left unbound, the primitive accumulates
from `opening_balance`, oldest first.

Options: `currency` string ("USD"), `max_visible` int 3-50 (10).

Roles: `secondary`, `footer`.

---

## 2. Layout schema

A layout schema is one JSON document describing one workspace.

```jsonc
{
  "schema_version": 1,
  "archetype": "salon",
  "label": "Salon / Barber",
  "vertical": "personal_services",
  "rationale": "The day is the product...",
  "suppressed": [
    { "primitive": "ledger", "reason": "..." }
  ],
  "surfaces": [
    {
      "id": "chair_day",
      "primitive": "timeline_day",
      "role": "lead",
      "title": "Today on the floor",
      "rationale": "...",
      "bindings": { "<binding>": { /* source descriptor */ } },
      "options": { "day_start": 9 }
    }
  ],
  "terminology": {
    "client": { "value": "Client", "origin": "preset" }
  },
  "theme": { "palette": {}, "display_font": "..." }
}
```

### 2.1 Source descriptors

Every binding resolves through a descriptor — never a raw query.

```jsonc
{
  "source": "bookings",
  "scope": "business",
  "filter": { "status": "confirmed" },
  "fields": { "id": "id", "title": "service_name" },
  "order": "start_at.asc",
  "limit": 60
}
```

`fields` maps **contract field name to catalog column**. Every required
contract field must appear. Every column named must exist in the catalog
entry for that source, and its declared type must be able to satisfy the
contract field's type (`workspace_field_catalog.TYPE_SATISFIES`).

A field may instead name a **derivation**:

```jsonc
"age_days": { "column": "last_interaction", "derive": "days_since" }
```

`age_days` is why derivations exist: an attention queue is ordered by how
long something has waited, and no table stores that. The catalog declares
each derivation's input types and result type
(`workspace_field_catalog.DERIVATIONS`), so check 3 can prove the
arithmetic lands on the contract's type.

`filter` values are literals, or a flat list of literals meaning `IN`.
Never a PostgREST fragment — check 4 rejects those, and that is what stops
a smuggled `business_id=eq.…` becoming a cross-tenant read once Chief is
authoring bindings.

A collection binding may declare `expect_items` — the shape the preset
intends, checked against the contract's `min_items`/`max_items` before any
data exists. `metric_row` is the user: two to four figures, never five.

Scalar bindings use `{ "source": ..., "scope": "business", "fields": {...} }`
with a single field.

### 2.2 Roles and budget

`role` is one of `lead`, `secondary`, `footer`. Exactly one `lead` per
layout. At most **five** surfaces total.

### 2.3 Terminology map

`terminology` maps a term key (the same keys `vertical_terminology.py`
already uses — `client`, `project`, `appointment`, ...) to:

```jsonc
{ "value": "Matter", "origin": "preset" }
```

`origin` is `preset` or `user_override`. **A row whose origin is
`user_override` is never overwritten** — not by re-classification, not by
an archetype switch, not by a preset refresh.

---

## 3. Archetypes

| archetype | vertical | lead | secondary | structural decision |
| --- | --- | --- | --- | --- |
| `salon` | `personal_services` | `timeline_day` | `attention_queue` | chair lanes, hours down the side |
| `law_firm` | `lawyer` | `priority_docket` | `metric_row` | no timeline at all; deadline order |
| `ministry` | `ministry` | `week_grid` | `attention_queue` | gatherings across seven days |
| `consultant` | `consultant` | `priority_docket` | `metric_row` | docket sorted by engagement stage |
| `trades` | `contractor` | `timeline_day` | `ledger` | crew lanes, travel gaps visible |

---

## 4. The validator

Server-side. Runs on any layout schema before persist or render. **Rejects,
never silently repairs.** Seven checks, in this order:

1. **`primitive_exists`** — every `surfaces[].primitive` is in the registry.
2. **`contract_satisfied`** — every required binding present; every required
   contract field bound; no unknown binding names; item-count bounds hold.
3. **`fields_resolve`** — every `source` is in the field catalog and every
   column named in `fields`/`filter`/`order` exists on it for this tenant.
4. **`tenant_scope`** — every binding declares `scope: "business"`, its
   source carries a tenant column, no filter names a `business_id` other
   than the tenant's own, and no filter value is a PostgREST expression.
   Validating with no `business_id` **tightens** this check rather than
   relaxing it: a pinned tenant column then has nothing legitimate to
   match.
5. **`options_in_range`** — every option is known to the primitive, of the
   declared type, and within its declared range/enum. Roles are checked
   against `allowed_roles` here too.
6. **`rationale_present`** — document `rationale` is a non-empty string;
   `suppressed` is present (an empty list is a claim, an absent key is a
   shrug) and every entry names a real primitive the layout does **not**
   render, with a reason; the lead surface says why it leads; every
   terminology row has a value and a known origin.
7. **`surface_budget`** — at most 5 surfaces, exactly one `lead`.

Checks 1-5 are per-surface and dependent: a surface that fails check *N* is
skipped for checks *N+1...5* rather than producing cascading noise. Checks 6
and 7 are document-level and always run. All surviving errors are reported
together.

### 4.1 Structured error

```jsonc
{
  "check": "tenant_scope",
  "code": "cross_tenant_binding",
  "path": "surfaces[1].bindings.rows.filter.business_id",
  "message": "binding reaches business_id 'other-biz'; tenant is 'biz-1'",
  "value": "other-biz"
}
```

`validate_layout()` returns a `ValidationResult`; `assert_valid()` raises
`LayoutValidationError` carrying `.errors`.

---

## 5. Classification

`workspace_archetypes.classify(answers)` reads intake answers and returns
one of the five archetypes, deterministically — no LLM. Signals are the
declared vertical/business type (strongest), then keyword evidence from the
free-text answers, then the shape of what they said they schedule.

Returns `archetype`, `confidence`, `runner_up`, `signals` (what fired), and
the preset's `rationale`. Chief shows the pick **and** why, and the override
is always visible: switching archetypes is one call and preserves every
`user_override` terminology row.

---

## 6. Where it lives

| concern | file |
| --- | --- |
| primitive registry | `workspace_primitives.py` |
| bindable sources, types, derivations | `workspace_field_catalog.py` |
| the seven checks | `workspace_layout_validator.py` |
| the five presets + loader | `workspace_layouts/` |
| classification | `workspace_archetypes.py` |
| HTTP surface | `workspace_composer_router.py` |
| Chief's three verbs | `chief_workspace_actions.py` |
| primitives + the one renderer | `workspace_ui/` |
| clickable visual reference | `workspace_ui/five-workspaces-demo.html` |
| schema + lane column + metrics view | `supabase/APPLY-2026-08-26-workspace-composer.sql` |

Chief's verbs are `choose_workspace`, `switch_workspace` and
`rename_term`. Adding a verb means three edits, not one, and the suite
fails loudly on each if it is missed: the handler in
`chief_of_staff.ACTION_HANDLERS`, a classification in `action_registry`
(which is where the ledger vocabulary comes from), and an
`[ACTION:{...}]` example in Chief's prompt — an undocumented verb has no
way to be invoked. All three are class A: they write one
`business_profiles` row, nothing leaves the system, and switching back is
one further call.

Practitioners never see an archetype slug, a primitive name, or the words
preset/schema/validator. The prompt says so explicitly, because the
action results are mirrored into Chief's own wording.

---

## 7. Out of scope (phase one)

Chief composing layouts from scratch; Chief authoring blocks; continuous
recomposition after onboarding; any new primitive beyond the six above.
