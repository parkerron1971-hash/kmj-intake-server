# Agent prompt — Law firm

You are building the **Law firm** vertical of the Solutionist System, end to
end, in parallel with seven other agents each doing the same for their own
vertical.

**Read `docs/VERTICAL_AGENT_CONTRACT.md` first.** It is the rule set: what
you own, what you must not touch, and the four rules. This prompt is the
lawyer-specific half.

## Repos

- backend — `kmj-intake-server`, trunk `main`, auto-deploys to Railway
- frontend — `solutionist-studio/solutionist-studio`, trunk `module-system`

Branch `vertical-lawyer` from trunk in each. Never branch from another
vertical's branch. One PR per repo. Do not merge your own.

## What this vertical is

Deadlines and documents. If those are not first it feels wrong to a lawyer, whatever else is on the screen.

## The files you own

```
backend   workspace_benchmarks/bands/lawyer.py
          workspace_layouts/lawyer.json
          supabase/benchmarks/APPLY-2026-08-27-bench-lawyer.sql
          supabase/APPLY-<date>-lawyer-<name>.sql        (new — yours to write)
frontend  src/core/intelligence/desks/lawyer.ts
```

Everything else is shared. If you need a shell change — a new `PanelKind`,
a new `DeskSource`, a new field in `workspace_field_catalog.py` — **do not
make it.** Write it up in your PR as a request. The integrator makes shell
changes once, for everyone.

## Where this vertical stands today

`businesses.type` = `lawyer` · bands module `bands/lawyer.py` · desk `desks/lawyer.ts`

**3 of 4 bands can be computed from the schema as it stands.**

| key | label | band | status |
|---|---|---|---|
| `utilization` | Utilisation — hours captured | industry 38%, target 50% | computes today |
| `realization` | Realisation — hours billed | industry 88%, target 92% | computes today |
| `collection` | Collection — invoices paid | industry 93%, target 97% | computes today |
| `realization_lockup` | Days of work not yet billed | industry 43 days, target 30 days | **no source** |

## What is missing, and why

**`realization_lockup`** — Days of annual revenue sitting as work DONE and NOT INVOICED — the half a firm controls directly. `time_entries` has everything needed (minutes, rate, invoice_id, status), so this is computable today and is the closest win of any vertical. Guard it the way `collection_lockup` is guarded: past a year the ratio stops measuring lockup and starts reporting that nothing is being collected.

## The research you are working from

The average lawyer records 3.0 billable hours in an eight-hour day; a solo records 2.1. Utilisation average is 38% against a 50% target. Realisation and collection compound: 92% realisation on 95% collection is 87% of what was recorded. Median total lockup across firms is 93 days — better than three months of revenue sitting outside the firm.

Every band you write carries a citation. `source` is checked by
`__tests__/test_workspace_benchmarks.py`; an unattributed band fails the
build. If a figure cannot be attributed, set `average=None` and say
"No industry benchmark — measured against your own history" in `source`.
That is honest. An invented median is not.

## Specific to you

This is the furthest-along vertical: three of four bands already compute. **Trust accounting is not the firm's money** and does not live in Invoices — the desk opens the account it belongs to. Do not fold trust into a revenue figure.

## The order of work

The panel is LAST. Most of these bands cannot be computed at all yet
because nothing records the underlying event.

1. **Decide what must be captured.** What event, on what table, with what
   columns? Reuse what exists if it genuinely fits — `sessions`,
   `contacts`, `invoices`, `time_entries`, `module_entries` and
   `customer_balances` are all live and tenant-scoped.
2. **Write the migration.** Idempotent, `supabase/APPLY-<date>-lawyer-*.sql`,
   NOT applied — Kevin applies by hand. Add one row to the ledger in
   `docs/MIGRATIONS.md`.
3. **Wire the capture path** — a form, a Chief action, an import. A column
   nothing writes to is not a feature.
4. **Write the bands** in `bands/lawyer.py`, with citations.
5. **Write the view arms** in your `bench-lawyer.sql`, against columns you
   verified exist.
6. **Build the desk** in `desks/lawyer.ts` and the layout in
   `workspace_layouts/lawyer.json`.

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
