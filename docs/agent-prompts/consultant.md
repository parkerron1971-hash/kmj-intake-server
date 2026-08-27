# Agent prompt — Consultant

You are building the **Consultant** vertical of the Solutionist System, end to
end, in parallel with seven other agents each doing the same for their own
vertical.

**Read `docs/VERTICAL_AGENT_CONTRACT.md` first.** It is the rule set: what
you own, what you must not touch, and the four rules. This prompt is the
consultant-specific half.

## Repos

- backend — `kmj-intake-server`, trunk `main`, auto-deploys to Railway
- frontend — `solutionist-studio/solutionist-studio`, trunk `module-system`

Branch `vertical-consultant` from trunk in each. Never branch from another
vertical's branch. One PR per repo. Do not merge your own.

## What this vertical is

Sells booked capacity. The failure is a full month followed by an empty one.

## The files you own

```
backend   workspace_benchmarks/bands/consultant.py
          workspace_layouts/consultant.json
          supabase/benchmarks/APPLY-2026-08-27-bench-consultant.sql
          supabase/APPLY-<date>-consultant-<name>.sql        (new — yours to write)
frontend  src/core/intelligence/desks/consultant.ts
```

Everything else is shared. If you need a shell change — a new `PanelKind`,
a new `DeskSource`, a new field in `workspace_field_catalog.py` — **do not
make it.** Write it up in your PR as a request. The integrator makes shell
changes once, for everyone.

## Where this vertical stands today

`businesses.type` = `consultant` · bands module `bands/consultant.py` · desk `desks/consultant.ts`

**1 of 4 bands can be computed from the schema as it stands.**

| key | label | band | status |
|---|---|---|---|
| `utilization_now` | Utilisation, this month | industry 70%, target 78% | computes today |
| `utilization_projected` | Utilisation, next six weeks | no published average, target 70% | **no source** |
| `proposal_win_rate` | Proposal win rate | industry 40%, target 55% | **no source** |
| `retainer_renewal` | Retainer renewal | industry 75%, target 90% | **no source** |

## What is missing, and why

**`utilization_projected`** — Needs booked-forward commitments distinguished from history; `sessions` does not separate them.

**`proposal_win_rate`** — Nothing models a proposal as a row.

**`retainer_renewal`** — Nothing models a retainer term as a row.

## The research you are working from

75-85% utilisation is the working band. Above 90% you have no bench, and the next urgent client request has nowhere to go but your weekend. The projected figure matters more than the current one: the point of the pair is to see the empty month while there is still time to fill it.

Every band you write carries a citation. `source` is checked by
`__tests__/test_workspace_benchmarks.py`; an unattributed band fails the
build. If a figure cannot be attributed, set `average=None` and say
"No industry benchmark — measured against your own history" in `source`.
That is honest. An invented median is not.

## Specific to you

**You share `bands/consultant.py` and the consultant benchmark view with the COACH agent** — both are measured against the same industry figures. Agree who edits the bands module, or leave it to whichever of you starts first. You each own your own desk file.

`utilization_now` already computes from `time_entries` (billable minutes over recorded). It is the same SQL as the lawyer's `utilization`, read against a different band — that is deliberate.

## The order of work

The panel is LAST. Most of these bands cannot be computed at all yet
because nothing records the underlying event.

1. **Decide what must be captured.** What event, on what table, with what
   columns? Reuse what exists if it genuinely fits — `sessions`,
   `contacts`, `invoices`, `time_entries`, `module_entries` and
   `customer_balances` are all live and tenant-scoped.
2. **Write the migration.** Idempotent, `supabase/APPLY-<date>-consultant-*.sql`,
   NOT applied — Kevin applies by hand. Add one row to the ledger in
   `docs/MIGRATIONS.md`.
3. **Wire the capture path** — a form, a Chief action, an import. A column
   nothing writes to is not a feature.
4. **Write the bands** in `bands/consultant.py`, with citations.
5. **Write the view arms** in your `bench-consultant.sql`, against columns you
   verified exist.
6. **Build the desk** in `desks/consultant.ts` and the layout in
   `workspace_layouts/consultant.json`.

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
