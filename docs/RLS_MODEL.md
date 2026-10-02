# RLS & tenant-isolation model

How the Solutionist System keeps one business's data invisible to
another. Read this before touching any Supabase RLS policy — a naive
change here re-caused a production outage once and opened a cross-tenant
hole another time.

## Two layers of isolation (both required)

1. **App-layer owner check (the reliable one).** The backend reads/writes
   with the **service-role key** (bypasses RLS) *after* confirming
   ownership in code: `_require_owner(business_id, user)` compares
   `businesses.owner_id` to the JWT user id and 403s on mismatch.
   Canonical: `contacts_router.py`. Every write router uses this. It does
   NOT depend on RLS being configured correctly.
2. **RLS (the backstop).** Postgres row-level security on the tables, so
   even a direct PostgREST call with the public anon key (which ships in
   the client bundle) only sees the caller's own rows. The frontend uses
   the user's JWT (`authenticated` role); the owner-scoped policy
   evaluates `auth.uid()`.

~~Verified 2026-07-13: RLS is **on** for all core + sensitive tables.~~

**Corrected 2026-09-01.** That claim was false when it was written, or
became false without anyone noticing — Supabase's linter reports RLS
**off** on two `public` tables, `leads` and `discovery_submissions`,
neither of which has ever carried an RLS statement in any migration in
this repo. They therefore stood at Supabase defaults: `anon` and
`authenticated` holding table grants, with RLS the only thing that would
have restricted rows, and the anon key ships in the frontend bundle.
Closed by `supabase/APPLY-2026-09-01-rls-advisor-errors.sql`.

The lesson is the same one `vertical_registry.KNOWN_GAPS` records about
the nonprofit blueprint: **a stale verification claim is worse than no
claim**, because it is exactly what stops the next person looking. Do
not write "verified" here without a date AND the query whose output you
read. If you cannot paste the output, you checked that a file exists.

**Verify with (run live, not from memory):**
```sql
SELECT c.relname, c.relrowsecurity
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind = 'r' AND NOT c.relrowsecurity
 ORDER BY 1;
```

## Rule 0 — a SECURITY DEFINER *view* is not a SECURITY DEFINER *function*

Rule 2 below **requires** `SECURITY DEFINER` functions for cross-table
policy checks. That is right, and this is not a caveat on it.

A definer *view* is the inverse hazard: it executes with the **view
owner's** privileges, so RLS on the tables underneath does not apply to
whoever queries the view. Postgres 15 makes definer the DEFAULT for
views — you opt out with `security_invoker = true` — which is how eight
of them accumulated on this project without anyone deciding to.

Today that is mostly latent, because nothing but the practitioner's own
frontend points a JWT at PostgREST. It stops being latent the moment a
second kind of account exists: a client-facing surface would be the first
thing to aim a non-owner JWT at that door. Any new view goes in with
`security_invoker = true` unless there is a written reason not to.

## Rule 1 — server code uses service-role, never anon

The backend must access the DB with `SUPABASE_SERVICE_ROLE_KEY` (via
`sb_clients.sb_*_as_service` or a helper that reads that env var). The
anon key is public. Any server path using the anon key on a
tenant-scoped table breaks the moment its permissive policy is removed —
this is exactly what bit us (see Rule 3).

## Rule 2 — cross-table policy checks go through SECURITY DEFINER helpers

A policy that inlines an `EXISTS` between tables that reference each
other (e.g. `businesses` ↔ `business_users` ↔ `business_collaborators`)
creates an infinite-recursion cycle → **42P17 production outage**
(hotfix `2026_06_10_hotfix_rls_recursion.sql`). Route every cross-table
check through a `SECURITY DEFINER` helper (`is_business_owner`,
`is_business_member`, `is_business_admin`, `is_business_collaborator`),
each `GRANT EXECUTE ... TO service_role`. Never inline the cross-table
`EXISTS` in the policy.

## Rule 3 — one permissive policy defeats all the others

Postgres combines multiple **permissive** policies on a table with
**OR**. So a leftover `USING (true)` "allow-all" policy sitting next to a
correct owner-scoped one **cancels the scoping** — the table is open.
This bit invoices / social_accounts / email_replies / business_profiles
(fixed 2026-07-13, `APPLY-2026-07-13-drop-permissive-policies.sql`): they
had both an owner-scoped policy and an `*_all` policy with `qual = true`.

**When adding a policy:** confirm no other policy on the table has
`qual = true`:
```sql
SELECT policyname, cmd, qual FROM pg_policies WHERE tablename = '<table>';
```
Every `qual` should reference the owner (`owner_id = auth.uid()` or
`business_id IN (SELECT id FROM businesses WHERE owner_id = auth.uid())`
or a SECURITY DEFINER helper). If any is literally `true`, that table is
open — drop that policy.

## Adding a new tenant-scoped table (checklist)

1. `ENABLE ROW LEVEL SECURITY`.
2. One owner-scoped policy (via the helpers for anything cross-table).
3. **No** `USING (true)` policy.
4. Backend access via service-role only.
5. Add the table to `account_lifecycle.BUSINESS_CHILD_TABLES` (export +
   delete coverage).
6. Verify live with the `pg_policies` query above.
