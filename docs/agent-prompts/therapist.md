# Agent prompt — Therapist / Clinical

You are building the **Therapist / Clinical** vertical of the Solutionist System, end to
end, in parallel with seven other agents each doing the same for their own
vertical.

**Read `docs/VERTICAL_AGENT_CONTRACT.md` first.** It is the rule set: what
you own, what you must not touch, and the four rules. This prompt is the
therapist-specific half.

## Repos

- backend — `kmj-intake-server`, trunk `main`, auto-deploys to Railway
- frontend — `solutionist-studio/solutionist-studio`, trunk `module-system`

Branch `vertical-therapist` from trunk in each. Never branch from another
vertical's branch. One PR per repo. Do not merge your own.

## What this vertical is

A caseload, not a calendar. The business is a set of people mid-course, and the risk is silent drop-off.

## The files you own

```
backend   workspace_benchmarks/bands/therapist.py
          workspace_layouts/therapist.json
          supabase/benchmarks/APPLY-2026-08-27-bench-therapist.sql
          supabase/APPLY-<date>-therapist-<name>.sql        (new — yours to write)
frontend  src/core/intelligence/desks/therapist.ts
```

Everything else is shared. If you need a shell change — a new `PanelKind`,
a new `DeskSource`, a new field in `workspace_field_catalog.py` — **do not
make it.** Write it up in your PR as a request. The integrator makes shell
changes once, for everyone.

## Where this vertical stands today

`businesses.type` = `therapist` · bands module `bands/therapist.py` · desk `desks/therapist.ts`

**2 of 4 bands can be computed from the schema as it stands.**

| key | label | band | status |
|---|---|---|---|
| `client_retention` | Clients reaching 8+ sessions | industry 85%, target 90% | computes today |
| `no_show_rate` | No-show and late cancellation | industry 15%, target 8% | computes today |
| `caseload_utilization` | Caseload utilisation | industry 70%, target 80% | **no source** |
| `booked_before_leaving` | Next session booked in the room | no published average, target 80% | **no source** |

## What is missing, and why

**`caseload_utilization`** — Needs the clinician's capacity — how many slots they intend to hold — which nothing records.

**`booked_before_leaving`** — Has NO published industry benchmark, and the band already says so in its source line. Keep it that way: it is measured against the practice's own history. It needs to distinguish a session booked in the room from one booked later, which `sessions` does not currently record.

## The research you are working from

A healthy practice holds 80-85% of clients to eight sessions or more; strong group practices reach 90-95%. Early drop-off is the expensive kind — the intake work is already spent. No-show under 15% keeps a schedule stable; high performers sit at 5-8%, and behavioural health runs far worse than primary care. Caseload above 85% is a hiring signal, not a win: it is the number that precedes burnout.

Every band you write carries a citation. `source` is checked by
`__tests__/test_workspace_benchmarks.py`; an unattributed band fails the
build. If a figure cannot be attributed, set `average=None` and say
"No industry benchmark — measured against your own history" in `source`.
That is honest. An invented median is not.

## Specific to you

**HIPAA BOUNDARY.** `vertical_scope.py` refuses clinical notes outright, enforced at module-creation seams. Do not add a column, a field or a panel that would hold clinical content. Counts, dates and attendance are fine; what was said is not. The therapist desk also marks panels `sensitive: true` — names are masked on every load and the reveal is deliberately never remembered. Respect that on anything you add.

## The order of work

The panel is LAST. Most of these bands cannot be computed at all yet
because nothing records the underlying event.

1. **Decide what must be captured.** What event, on what table, with what
   columns? Reuse what exists if it genuinely fits — `sessions`,
   `contacts`, `invoices`, `time_entries`, `module_entries` and
   `customer_balances` are all live and tenant-scoped.
2. **Write the migration.** Idempotent, `supabase/APPLY-<date>-therapist-*.sql`,
   NOT applied — Kevin applies by hand. Add one row to the ledger in
   `docs/MIGRATIONS.md`.
3. **Wire the capture path** — a form, a Chief action, an import. A column
   nothing writes to is not a feature.
4. **Write the bands** in `bands/therapist.py`, with citations.
5. **Write the view arms** in your `bench-therapist.sql`, against columns you
   verified exist.
6. **Build the desk** in `desks/therapist.ts` and the layout in
   `workspace_layouts/therapist.json`.

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
