# Agent prompt — Trades / Home Services

You are building the **Trades / Home Services** vertical of the Solutionist System, end to
end, in parallel with seven other agents each doing the same for their own
vertical.

**Read `docs/VERTICAL_AGENT_CONTRACT.md` first.** It is the rule set: what
you own, what you must not touch, and the four rules. This prompt is the
trades-specific half.

## Repos

- backend — `kmj-intake-server`, trunk `main`, auto-deploys to Railway
- frontend — `solutionist-studio/solutionist-studio`, trunk `module-system`

Branch `vertical-trades` from trunk in each. Never branch from another
vertical's branch. One PR per repo. Do not merge your own.

## What this vertical is

Sells crew-hours against jobs. The money leaks between the van arriving and the invoice going out.

## The files you own

```
backend   workspace_benchmarks/bands/trades.py
          workspace_layouts/trades.json
          supabase/benchmarks/APPLY-2026-08-27-bench-trades.sql
          supabase/APPLY-<date>-trades-<name>.sql        (new — yours to write)
frontend  src/core/intelligence/desks/contractor.ts
```

Everything else is shared. If you need a shell change — a new `PanelKind`,
a new `DeskSource`, a new field in `workspace_field_catalog.py` — **do not
make it.** Write it up in your PR as a request. The integrator makes shell
changes once, for everyone.

## Where this vertical stands today

`businesses.type` = `contractor` · bands module `bands/trades.py` · desk `desks/contractor.ts`

**0 of 4 bands can be computed from the schema as it stands.**

| key | label | band | status |
|---|---|---|---|
| `first_time_fix` | First-time fix rate | industry 75%, target 86% | **no source** |
| `tech_utilization` | Technician utilisation | industry 55%, target 75% | **no source** |
| `estimate_close_rate` | Estimate close rate | industry 50%, target 60% | **no source** |
| `membership_attach` | Membership attach | industry 45%, target 60% | **no source** |

## What is missing, and why

**`first_time_fix`** — Nothing models a job, a dispatch, an estimate or a membership as a row. This is the biggest schema gap of the eight — start here, not at the panel.

**`tech_utilization`** — Nothing models a job, a dispatch, an estimate or a membership as a row. This is the biggest schema gap of the eight — start here, not at the panel.

**`estimate_close_rate`** — Nothing models a job, a dispatch, an estimate or a membership as a row. This is the biggest schema gap of the eight — start here, not at the panel.

**`membership_attach`** — Nothing models a job, a dispatch, an estimate or a membership as a row. This is the biggest schema gap of the eight — start here, not at the panel.

## The research you are working from

Median first-time fix is 75% across 157 service organisations; top quintile 86%, bottom 53%. Under 70% is a dispatch-and-parts problem, not a skill problem. Technician utilisation benchmark is 75-85%. Estimate close is 40-60% healthy — below 40% is almost always follow-up rather than price, because 90% of contractors stop after the first or second touch. Membership attach baseline 40-50%, best-in-class 60-90%, and it is the number that predicts next year rather than this one.

Every band you write carries a citation. `source` is checked by
`__tests__/test_workspace_benchmarks.py`; an unattributed band fails the
build. If a figure cannot be attributed, set `average=None` and say
"No industry benchmark — measured against your own history" in `source`.
That is honest. An invented median is not.

## Specific to you

`contractors` DOES carry names, so a crew board can bind real lanes — unlike the salon. `default_category` looks like a trade and is NOT: it is a Profit First bucket (tax|owner_pay|operating|savings|other). `onboarding_status` is invited|pending|active|restricted.

## The order of work

The panel is LAST. Most of these bands cannot be computed at all yet
because nothing records the underlying event.

1. **Decide what must be captured.** What event, on what table, with what
   columns? Reuse what exists if it genuinely fits — `sessions`,
   `contacts`, `invoices`, `time_entries`, `module_entries` and
   `customer_balances` are all live and tenant-scoped.
2. **Write the migration.** Idempotent, `supabase/APPLY-<date>-trades-*.sql`,
   NOT applied — Kevin applies by hand. Add one row to the ledger in
   `docs/MIGRATIONS.md`.
3. **Wire the capture path** — a form, a Chief action, an import. A column
   nothing writes to is not a feature.
4. **Write the bands** in `bands/trades.py`, with citations.
5. **Write the view arms** in your `bench-trades.sql`, against columns you
   verified exist.
6. **Build the desk** in `desks/contractor.ts` and the layout in
   `workspace_layouts/trades.json`.

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
