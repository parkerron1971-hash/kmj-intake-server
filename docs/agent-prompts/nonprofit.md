# Agent prompt — Nonprofit

You are building the **Nonprofit** vertical of the Solutionist System, end to
end, in parallel with seven other agents each doing the same for their own
vertical.

**Read `docs/VERTICAL_AGENT_CONTRACT.md` first.** It is the rule set: what
you own, what you must not touch, and the four rules. This prompt is the
nonprofit-specific half.

## Repos

- backend — `kmj-intake-server`, trunk `main`, auto-deploys to Railway
- frontend — `solutionist-studio/solutionist-studio`, trunk `module-system`

Branch `vertical-nonprofit` from trunk in each. Never branch from another
vertical's branch. One PR per repo. Do not merge your own.

## What this vertical is

Obligations to funders, and a donor base that quietly erodes.

## The files you own

```
backend   workspace_benchmarks/bands/nonprofit.py
          workspace_layouts/nonprofit.json
          supabase/benchmarks/APPLY-2026-08-27-bench-nonprofit.sql
          supabase/APPLY-<date>-nonprofit-<name>.sql        (new — yours to write)
frontend  src/core/intelligence/desks/nonprofit.ts
```

Everything else is shared. If you need a shell change — a new `PanelKind`,
a new `DeskSource`, a new field in `workspace_field_catalog.py` — **do not
make it.** Write it up in your PR as a request. The integrator makes shell
changes once, for everyone.

## Where this vertical stands today

`businesses.type` = `nonprofit` · bands module `bands/nonprofit.py` · desk `desks/nonprofit.ts`

**0 of 4 bands can be computed from the schema as it stands.**

| key | label | band | status |
|---|---|---|---|
| `donor_retention` | Donor retention | industry 45%, target 55% | **no source** |
| `first_time_donor_retention` | First-time donors who give again | industry 24%, target 35% | **no source** |
| `recurring_share` | Income that recurs | industry 20%, target 35% | **no source** |
| `grants_on_time` | Reports filed on time | no published average, target 100% | **no source** |

## What is missing, and why

**`donor_retention`** — Nothing distinguishes a donor from any other contact, or a recurring gift from a one-off, or a grant obligation from a task. `contacts.status` has no 'donor' value — an earlier attempt filtered on exactly that and would have returned nothing forever.

**`first_time_donor_retention`** — Nothing distinguishes a donor from any other contact, or a recurring gift from a one-off, or a grant obligation from a task. `contacts.status` has no 'donor' value — an earlier attempt filtered on exactly that and would have returned nothing forever.

**`recurring_share`** — Nothing distinguishes a donor from any other contact, or a recurring gift from a one-off, or a grant obligation from a task. `contacts.status` has no 'donor' value — an earlier attempt filtered on exactly that and would have returned nothing forever.

**`grants_on_time`** — Nothing distinguishes a donor from any other contact, or a recurring gift from a one-off, or a grant obligation from a task. `contacts.status` has no 'donor' value — an earlier attempt filtered on exactly that and would have returned nothing forever.

## The research you are working from

Overall donor retention runs about 45%, and first-time donor retention is far worse — roughly 20%, meaning four in five first-time donors never give again. Recurring donors retain at around 90%, which is why recurring share is the number that compounds. Grant reporting on time is table stakes: a missed report costs the next grant, not this one.

Every band you write carries a citation. `source` is checked by
`__tests__/test_workspace_benchmarks.py`; an unattributed band fails the
build. If a figure cannot be attributed, set `average=None` and say
"No industry benchmark — measured against your own history" in `source`.
That is honest. An invented median is not.

## Specific to you

A secular 501(c)(3) is NOT a church — `canonicalType` used to route every nonprofit to the ministry desk, which is why the nonprofit desk and its own mark exist. Keep them distinct.

A gift IS a paid invoice here (see giving_router.py and gl_reports_t4.donor_report); restricted ones carry category='restricted'. Reuse that definition.

## The order of work

The panel is LAST. Most of these bands cannot be computed at all yet
because nothing records the underlying event.

1. **Decide what must be captured.** What event, on what table, with what
   columns? Reuse what exists if it genuinely fits — `sessions`,
   `contacts`, `invoices`, `time_entries`, `module_entries` and
   `customer_balances` are all live and tenant-scoped.
2. **Write the migration.** Idempotent, `supabase/APPLY-<date>-nonprofit-*.sql`,
   NOT applied — Kevin applies by hand. Add one row to the ledger in
   `docs/MIGRATIONS.md`.
3. **Wire the capture path** — a form, a Chief action, an import. A column
   nothing writes to is not a feature.
4. **Write the bands** in `bands/nonprofit.py`, with citations.
5. **Write the view arms** in your `bench-nonprofit.sql`, against columns you
   verified exist.
6. **Build the desk** in `desks/nonprofit.ts` and the layout in
   `workspace_layouts/nonprofit.json`.

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
