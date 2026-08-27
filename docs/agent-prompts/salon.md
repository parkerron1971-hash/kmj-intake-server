# Agent prompt — Salon / Barber

You are building the **Salon / Barber** vertical of the Solutionist System, end to
end, in parallel with seven other agents each doing the same for their own
vertical.

**Read `docs/VERTICAL_AGENT_CONTRACT.md` first.** It is the rule set: what
you own, what you must not touch, and the four rules. This prompt is the
salon-specific half.

## Repos

- backend — `kmj-intake-server`, trunk `main`, auto-deploys to Railway
- frontend — `solutionist-studio/solutionist-studio`, trunk `module-system`

Branch `vertical-salon` from trunk in each. Never branch from another
vertical's branch. One PR per repo. Do not merge your own.

## What this vertical is

The day is the product. What gets sold is chair-hours, and an hour that passes empty is gone.

## The files you own

```
backend   workspace_benchmarks/bands/salon.py
          workspace_layouts/salon.json
          supabase/benchmarks/APPLY-2026-08-27-bench-salon.sql
          supabase/APPLY-<date>-salon-<name>.sql        (new — yours to write)
frontend  src/core/intelligence/desks/personal_services.ts
```

Everything else is shared. If you need a shell change — a new `PanelKind`,
a new `DeskSource`, a new field in `workspace_field_catalog.py` — **do not
make it.** Write it up in your PR as a request. The integrator makes shell
changes once, for everyone.

## Where this vertical stands today

`businesses.type` = `personal_services` · bands module `bands/salon.py` · desk `desks/personal_services.ts`

**2 of 4 bands can be computed from the schema as it stands.**

| key | label | band | status |
|---|---|---|---|
| `rebooking_rate` | Rebooking rate | industry 52%, target 80% | computes today |
| `chair_utilization` | Chair utilisation | industry 48%, target 65% | **no source** |
| `retail_attach` | Retail attach | industry 12%, target 20% | **no source** |
| `new_client_return` | New clients who come back | industry 50%, target 65% | computes today |

## What is missing, and why

**`chair_utilization`** — Needs bookable floor hours as a denominator. `availability` stores `concurrent_capacity`, which is a COUNT OF CHAIRS, not a staffed roster — and there is no named staff anywhere in this product (`business_users` has no name column at all). Decide whether the shop declares its open hours and chair count, or whether this band should be dropped.

**`retail_attach`** — Needs `invoices.items` to distinguish retail from service. `items` is jsonb and practitioner-defined, so nothing guarantees the distinction exists. Either establish a convention and write it, or drop the band.

## The research you are working from

Prebooked clients return at 70-80%; those who leave without a next appointment return at 30-40%. Industry rebooking is 52%, top performers clear 80%, and 60% is the line below which a book stops replacing itself. Most booking systems never surface it — you have to dig it out of a report. That is the opening: rebooking on the home screen is a genuine differentiator, not a feature.

Every band you write carries a citation. `source` is checked by
`__tests__/test_workspace_benchmarks.py`; an unattributed band fails the
build. If a figure cannot be attributed, set `average=None` and say
"No industry benchmark — measured against your own history" in `source`.
That is honest. An invented median is not.

## Specific to you

The salon board deliberately draws ONE undivided day, not chair lanes — because no named staff exist to label them. Do not reintroduce lanes without introducing staff first.

## The order of work

The panel is LAST. Most of these bands cannot be computed at all yet
because nothing records the underlying event.

1. **Decide what must be captured.** What event, on what table, with what
   columns? Reuse what exists if it genuinely fits — `sessions`,
   `contacts`, `invoices`, `time_entries`, `module_entries` and
   `customer_balances` are all live and tenant-scoped.
2. **Write the migration.** Idempotent, `supabase/APPLY-<date>-salon-*.sql`,
   NOT applied — Kevin applies by hand. Add one row to the ledger in
   `docs/MIGRATIONS.md`.
3. **Wire the capture path** — a form, a Chief action, an import. A column
   nothing writes to is not a feature.
4. **Write the bands** in `bands/salon.py`, with citations.
5. **Write the view arms** in your `bench-salon.sql`, against columns you
   verified exist.
6. **Build the desk** in `desks/personal_services.ts` and the layout in
   `workspace_layouts/salon.json`.

## The rule that matters most

**Verify every column against `information_schema` before writing SQL
against it.** On 2026-08-26 two benchmark arms filtered `contacts.status`
on `'first_time'` and `'donor'`. That column allows only
`lead|active|inactive|churned|vip`, so both would have *succeeded* and
returned nothing — forever, with no error anywhere. `docs/MIGRATIONS.md`
says it plainly: the file set is not a faithful record of production.

A metric with no honest source is **absent, not approximated**. A key with
no arm renders "not measured", which is correct and always better than a
plausible number computed from the wrong column. Say in your PR which keys
you left absent and why.

## Before you open a PR

```bash
python -m pytest __tests__/test_workspace_*.py -q   # 229 green today
npm run typecheck
npx vite build
```

State in the PR description:

- which keys are measured and which are absent, and why
- every column your SQL reads, and that you verified each exists
- what your migration does, and that it is not applied
- any shell change you need but did not make
