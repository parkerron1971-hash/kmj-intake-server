# Path C — Archetype write discipline

This file lives next to the migrations so anyone adding a new vertical
sees it. Read before adding a new archetype or shipping a migration
that creates a business with a new `type` value.

## Until 2026_06_07_pathc_phase1_fk_constraint.sql lands in prod

`public.businesses.type` is governed by the legacy **CHECK constraint**
named `businesses_type_check`. Any new archetype you seed into
`public.business_type_archetypes` is **invisible** to the constraint —
INSERTs with the new value will fail (Postgres code 23514).

**Rule:** when you add a new archetype row, you MUST also `ALTER TABLE
public.businesses` to widen the CHECK to include the new value in the
SAME migration. See
`supabase/businesses-type-check-extend-migration.sql` for the pattern.

## After 2026_06_07_pathc_phase1_fk_constraint.sql lands

The CHECK constraint is dropped and replaced with a FOREIGN KEY:

```
businesses.type → business_type_archetypes(business_type)
```

**At that point this rule INVERTS:** you no longer touch a CHECK
constraint. Adding a new archetype row is enough — the FK admits the
new value system-wide automatically. (The archetype seed migration
becomes the single source of truth, which is the whole point of
Path C.)

## When in doubt

Run `__migrations__/2026_06_07_pathc_phase1_diagnostic.sql` against
your target database. If Q5 returns any rows, you have prod
`businesses.type` values that aren't yet archetype rows — seed those
first before applying the FK.

## Cross-table mirror discipline (app-level, Phase 1d)

When you write `businesses.type`, also write
`business_profiles.business_type` (and vice versa). The defensive
mirrors live in:

- Frontend: `solutionist-studio/src/core/components/BusinessSettings.tsx`
  → `save()` calls both PATCHes.
- Backend: `kmj-intake-server/business_profile_agent.py`
  → `upsert_profile()` mirrors profile-side writes back to businesses.

If you add a new writer of either column, mirror to the other in the
same code path. The diagnostic in `VerticalProvider.tsx` (gated behind
`?debug=verticals`) surfaces drift in real time during development.
