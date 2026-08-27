# The vertical agent contract

Eight agents, one per vertical, working at the same time without ever
resolving a merge conflict. This file is the rule set. Read it before
your vertical's prompt.

## Why the codebase looks like this

The seams were cut on 2026-08-27 for exactly this. Before that, a single
`workspace_benchmarks.py`, one SQL view and a 1,212-line `verticalDesks.ts`
held all eight verticals, so two people could not work at once without
colliding in the same object literal. A merge conflict inside a band
definition or a SQL view is resolved by guessing, and a wrong guess here
puts another industry's sentence under your number.

So the rule below is not bureaucracy. It is the reason the split exists.

## What you own

Replace `<v>` with your vertical's slug: `salon`, `trades`, `therapist`,
`ministry`, `consultant`, `nonprofit`, `lawyer`, `coach`.

| File | Repo | What it is |
|---|---|---|
| `workspace_benchmarks/bands/<v>.py` | backend | your bands + the four keys your desk binds |
| `workspace_layouts/<v>.json` | backend | your layout schema |
| `supabase/benchmarks/APPLY-*-bench-<v>.sql` | backend | your benchmark view |
| `supabase/APPLY-<date>-<v>-*.sql` | backend | any NEW table or column your vertical needs |
| `src/core/intelligence/desks/<v>.ts` | frontend | your desk definition |

Note `coach` and `consultant` share one bands module (`consultant.py`) and
one benchmark view, because they are measured against the same industry
figures. They have separate desk files. If you are the coach agent,
coordinate on the bands module or leave it to consultant — do not both
edit it.

## What you must NOT touch

| File | Why |
|---|---|
| `workspace_benchmarks/__init__.py`, `_band.py` | shared machinery; the resolver tests monkeypatch `_values_for` here |
| `workspace_benchmarks/bands/__init__.py` | the registry — one line per vertical, already written |
| `workspace_field_catalog.py` | the allow-list every binding resolves against |
| `workspace_primitives.py`, `workspace_layout_validator.py`, `workspace_resolver.py` | the engine |
| `supabase/APPLY-*-bench-aggregate.sql` | unions all seven views; changes only when a whole vertical is added |
| `desks/_shared.ts`, `desks/index.ts` | the desk vocabulary and registry |
| `deskData.ts`, `DeskSurface.tsx`, `desk.css` | the shell — one change there changes all eight desks |

**If your vertical genuinely needs a shell change** — a new `PanelKind`, a
new `DeskSource`, a new field in the catalog — do not make it. Write it up
in your PR description as a request. The integrator makes shell changes
once, for everyone, so that two agents cannot invent two different
versions of the same primitive.

## The four rules

**1. Every band carries a citation.** A band is an editorial claim this
product asserts to a practitioner who may act on it. `source` is checked
by `__tests__/test_workspace_benchmarks.py` and an unattributed band fails
the build. If you cannot attribute a figure, set `average=None` and say
"No industry benchmark — measured against your own history" in `source`.
That is honest. An invented median is not.

**2. Never compute a number from a column that does not mean what the
band says it means.** On 2026-08-26 two benchmark arms filtered
`contacts.status` on `'first_time'` and `'donor'`. That column allows only
`lead|active|inactive|churned|vip`, so both arms would have succeeded and
returned nothing — forever. A ministry would have been shown a guest
return rate of zero every Sunday with no error anywhere. **Verify every
column against `information_schema` before you write SQL against it.**
The file set in `supabase/` is not a faithful record of production; see
`docs/MIGRATIONS.md`.

**3. A metric with no honest source is ABSENT, not approximated.** A key
with no arm in your view renders its band with an empty figure reading
"not measured". That is the correct state and it is always better than a
plausible number computed from the wrong thing. Say in your PR which keys
you left absent and why.

**4. Your migration is not applied.** Ship it as
`supabase/APPLY-YYYY-MM-DD-<v>-<name>.sql`, idempotent, and say so in the
PR. Kevin applies migrations by hand. Add your row to the ledger table in
`docs/MIGRATIONS.md` — that file IS shared, so keep your edit to a single
added row and expect to rebase.

## The order of work

The panel is the last step, not the first. Most verticals cannot be
measured at all today:

```
lawyer      3 of 4 keys computable      contractor  0 of 4
salon       2 of 4                      ministry    0 of 4
therapist   2 of 4                      nonprofit   0 of 4
consultant  1 of 4
```

Nothing in the schema records a job, a guest visit, or a donor. So:

1. **Decide what the vertical must capture.** What event, on what table,
   with what columns? Reuse an existing table if one genuinely fits;
   `sessions`, `contacts`, `invoices`, `time_entries` and `module_entries`
   all exist and are already tenant-scoped.
2. **Write the migration** for whatever is missing.
3. **Wire the capture path** so the data can actually arrive — a form, a
   Chief action, an import. A column nothing writes to is not a feature.
4. **Write the bands**, with citations.
5. **Write the benchmark view arms** against columns you verified.
6. **Build the desk panel** and the layout schema.

## Before you open a PR

Run all of these. The integrator will run them again and a failure
blocks every other vertical, not just yours.

```bash
# backend
python -m pytest __tests__/test_workspace_*.py -q      # 229 passing today

# frontend
npm run typecheck
npx vite build
```

Then in your PR description, state plainly:

- which keys are measured and which are absent, and why
- every column your SQL reads, and that you verified each one exists
- what your migration does, and that it has not been applied
- any shell change you need but did not make

## Branch and PR

One branch per vertical, named `vertical-<v>`. Branch from the trunk —
`main` in `kmj-intake-server`, `module-system` in `solutionist-studio`.
Never branch from another vertical's branch, and never stack.

Open one PR per repo per vertical. Do not merge your own. Do not rebase
another vertical's branch.
