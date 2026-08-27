# Agent prompt — Ministry / Church

You are building the **Ministry / Church** vertical of the Solutionist System, end to
end, in parallel with seven other agents each doing the same for their own
vertical.

**Read `docs/VERTICAL_AGENT_CONTRACT.md` first.** It is the rule set: what
you own, what you must not touch, and the four rules. This prompt is the
ministry-specific half.

## Repos

- backend — `kmj-intake-server`, trunk `main`, auto-deploys to Railway
- frontend — `solutionist-studio/solutionist-studio`, trunk `module-system`

Branch `vertical-ministry` from trunk in each. Never branch from another
vertical's branch. One PR per repo. Do not merge your own.

## What this vertical is

A congregation, and a guest funnel that almost nobody runs deliberately.

## The files you own

```
backend   workspace_benchmarks/bands/ministry.py
          workspace_layouts/ministry.json
          supabase/benchmarks/APPLY-2026-08-27-bench-ministry.sql
          supabase/APPLY-<date>-ministry-<name>.sql        (new — yours to write)
frontend  src/core/intelligence/desks/ministry.ts
```

Everything else is shared. If you need a shell change — a new `PanelKind`,
a new `DeskSource`, a new field in `workspace_field_catalog.py` — **do not
make it.** Write it up in your PR as a request. The integrator makes shell
changes once, for everyone.

## Where this vertical stands today

`businesses.type` = `ministry` · bands module `bands/ministry.py` · desk `desks/ministry.ts`

**0 of 4 bands can be computed from the schema as it stands.**

| key | label | band | status |
|---|---|---|---|
| `first_time_return` | First-timers who come back | industry 10%, target 20% | **no source** |
| `second_time_return` | Second-timers who come back | industry 25%, target 40% | **no source** |
| `third_time_stay` | Third-timers who stay | industry 35%, target 60% | **no source** |
| `giving_participation` | Households giving | industry 40%, target 45% | **no source** |

## What is missing, and why

**`first_time_return`** — Needs a first-visit marker and a visit ordinal on a person. `contacts.status` allows only lead|active|inactive|churned|vip — there is no 'first_time'. An earlier attempt filtered on exactly that and would have shown every church a guest return rate of zero, forever, with no error. Model the visit, then measure it.

**`second_time_return`** — Needs a first-visit marker and a visit ordinal on a person. `contacts.status` allows only lead|active|inactive|churned|vip — there is no 'first_time'. An earlier attempt filtered on exactly that and would have shown every church a guest return rate of zero, forever, with no error. Model the visit, then measure it.

**`third_time_stay`** — Needs a first-visit marker and a visit ordinal on a person. `contacts.status` allows only lead|active|inactive|churned|vip — there is no 'first_time'. An earlier attempt filtered on exactly that and would have shown every church a guest return rate of zero, forever, with no error. Model the visit, then measure it.

**`giving_participation`** — Needs a first-visit marker and a visit ordinal on a person. `contacts.status` allows only lead|active|inactive|churned|vip — there is no 'first_time'. An earlier attempt filtered on exactly that and would have shown every church a guest return rate of zero, forever, with no error. Model the visit, then measure it.

## The research you are working from

The average church sees 6-15% of first-time guests return for a second visit; growing churches reach about 20%. Around 70% of leaders say they have no effective process here and 36% have none at all. The second and third visits are where someone decides to belong — a guest who reaches a third visit is very likely to stay.

Every band you write carries a citation. `source` is checked by
`__tests__/test_workspace_benchmarks.py`; an unattributed band fails the
build. If a figure cannot be attributed, set `average=None` and say
"No industry benchmark — measured against your own history" in `source`.
That is honest. An invented median is not.

## Specific to you

Giving participation needs a household denominator, which nothing records. A gift IS a paid invoice in this system (giving_router.py records one per Stripe payment); reproduce that definition rather than inventing a second one — a desk figure that disagreed with the Donors report would be worse than no figure.

## The order of work

The panel is LAST. Most of these bands cannot be computed at all yet
because nothing records the underlying event.

1. **Decide what must be captured.** What event, on what table, with what
   columns? Reuse what exists if it genuinely fits — `sessions`,
   `contacts`, `invoices`, `time_entries`, `module_entries` and
   `customer_balances` are all live and tenant-scoped.
2. **Write the migration.** Idempotent, `supabase/APPLY-<date>-ministry-*.sql`,
   NOT applied — Kevin applies by hand. Add one row to the ledger in
   `docs/MIGRATIONS.md`.
3. **Wire the capture path** — a form, a Chief action, an import. A column
   nothing writes to is not a feature.
4. **Write the bands** in `bands/ministry.py`, with citations.
5. **Write the view arms** in your `bench-ministry.sql`, against columns you
   verified exist.
6. **Build the desk** in `desks/ministry.ts` and the layout in
   `workspace_layouts/ministry.json`.

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
