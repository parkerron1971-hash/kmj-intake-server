-- ══════════════════════════════════════════════════════════════════
-- APPLY 2026-08-09 — storage writes require an identity and an owner
--
-- Measured before this ran, querying storage.objects as role `anon`:
--
--   business-assets      17 objects listable anonymously
--   site_images          13
--   proposals             5
--   ets-event-files       4
--   client-images         3
--   business-documents    1
--
--   has_table_privilege('anon','storage.objects', SELECT/INSERT/UPDATE/DELETE)
--     -> true, true, true, true
--
-- Every policy on storage.objects was `TO public USING (bucket_id = '…')`
-- and nothing else. `public` includes anon, and the anon key ships in the
-- browser bundle. So anyone could upload into, overwrite, or DELETE a
-- practitioner's client documents.
--
-- The reason those policies are shaped that way is that the app's own
-- uploads arrived as anon: every storage helper sent the anon key as
-- Authorization. Frontend #454 fixed that — uploads now carry the
-- practitioner's JWT — which is what makes this file safe to run. Doing
-- it in the other order would have made the app the first thing refused.
--
-- ── SCOPE ─────────────────────────────────────────────────────────
-- This closes WRITES only: INSERT, UPDATE, DELETE.
--
-- SELECT is deliberately left alone. Published customer sites load
-- images from these buckets anonymously, so revoking public read breaks
-- every live site — and business-documents/proposals need the frontend
-- moved onto signed URLs before their read can be closed. That is the
-- next step, and it is a frontend change first again.
--
-- Writes have no such constraint: after #454 there is no legitimate
-- anonymous writer left. Server-side uploads (brand_engine, dalle_client,
-- account_lifecycle) use the service role, which has rolbypassrls and is
-- unaffected by anything below.
--
-- ── OWNERSHIP ─────────────────────────────────────────────────────
-- business_users currently has ZERO rows: every business today is
-- reached through businesses.owner_id. A seat-only policy would
-- therefore lock out 100% of users — the exact failure class that hit
-- backend #464. owner_id is checked first and independently.
-- ══════════════════════════════════════════════════════════════════


-- ── Helper: which business does this object path belong to? ────────
-- Paths are '{business_id}/…' for uploads from the app, and
-- 'brand/{business_id}/…' for brand_engine's three objects. Anything
-- else returns NULL, which every policy below treats as "refuse".
create or replace function public.storage_business_id(objname text)
returns uuid
language sql
immutable
as $$
  select case
    when split_part(objname, '/', 1) ~
         '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
      then split_part(objname, '/', 1)::uuid
    when split_part(objname, '/', 1) = 'brand'
     and split_part(objname, '/', 2) ~
         '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
      then split_part(objname, '/', 2)::uuid
    else null
  end;
$$;

comment on function public.storage_business_id(text) is
  'Business id from a storage object path. NULL when the path names no '
  'business — storage policies treat NULL as refuse, so a new path shape '
  'fails closed rather than becoming unguarded.';


-- ── Helper: may the caller touch this business? ────────────────────
-- SECURITY DEFINER on purpose. `businesses` and `business_users` both
-- carry their own RLS, and evaluating them as the caller from inside a
-- storage policy is how the 42P17 policy-cycle outage happened before.
-- This runs as owner, reads two tables, and returns a boolean.
create or replace function public.user_can_access_business(biz uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select biz is not null
     and auth.uid() is not null
     and (
       -- Owner FIRST and independently. A brand-new business has an
       -- owner_id and no business_users row at all; checking seats
       -- alone locks out every owner (backend #464).
       exists (select 1 from businesses b
                where b.id = biz and b.owner_id = auth.uid())
       or exists (select 1 from business_users bu
                   where bu.business_id = biz
                     and bu.user_id = auth.uid()
                     and bu.revoked_at is null)
     );
$$;

comment on function public.user_can_access_business(uuid) is
  'True when the current JWT belongs to the owner of, or an unrevoked '
  'seat on, this business. SECURITY DEFINER so storage policies do not '
  're-enter the RLS on businesses/business_users.';

revoke all on function public.user_can_access_business(uuid) from public;
grant execute on function public.user_can_access_business(uuid) to authenticated;
grant execute on function public.storage_business_id(text) to authenticated;


-- ── Out with the anonymous write policies ──────────────────────────
drop policy if exists "Allow uploads"                          on storage.objects;
drop policy if exists "Allow updates"                          on storage.objects;
drop policy if exists "Allow deletes"                          on storage.objects;
drop policy if exists "Allow uploads to site_images"           on storage.objects;
drop policy if exists "Allow updates to site_images"           on storage.objects;
drop policy if exists "Allow deletes from site_images"         on storage.objects;
drop policy if exists "Allow public upload business-documents" on storage.objects;
drop policy if exists "Allow public delete business-documents" on storage.objects;
drop policy if exists "Allow public upload proposals"          on storage.objects;
drop policy if exists "Allow public uploads"                   on storage.objects;
drop policy if exists "Allow public deletes"                   on storage.objects;
drop policy if exists "Allow public upload"                    on storage.objects;
drop policy if exists "Allow public delete"                    on storage.objects;


-- ── In with owner-scoped ones, for the buckets keyed on a business ──
-- Only the verbs each bucket already had. proposals had no DELETE and
-- business-documents no UPDATE; this is a lockdown, not a place to hand
-- out capabilities nobody had.

create policy "biz write: business-assets insert" on storage.objects
  for insert to authenticated
  with check (bucket_id = 'business-assets'
              and public.user_can_access_business(public.storage_business_id(name)));

create policy "biz write: business-assets update" on storage.objects
  for update to authenticated
  using (bucket_id = 'business-assets'
         and public.user_can_access_business(public.storage_business_id(name)))
  with check (bucket_id = 'business-assets'
              and public.user_can_access_business(public.storage_business_id(name)));

create policy "biz write: business-assets delete" on storage.objects
  for delete to authenticated
  using (bucket_id = 'business-assets'
         and public.user_can_access_business(public.storage_business_id(name)));

create policy "biz write: site_images insert" on storage.objects
  for insert to authenticated
  with check (bucket_id = 'site_images'
              and public.user_can_access_business(public.storage_business_id(name)));

create policy "biz write: site_images update" on storage.objects
  for update to authenticated
  using (bucket_id = 'site_images'
         and public.user_can_access_business(public.storage_business_id(name)))
  with check (bucket_id = 'site_images'
              and public.user_can_access_business(public.storage_business_id(name)));

create policy "biz write: site_images delete" on storage.objects
  for delete to authenticated
  using (bucket_id = 'site_images'
         and public.user_can_access_business(public.storage_business_id(name)));

create policy "biz write: business-documents insert" on storage.objects
  for insert to authenticated
  with check (bucket_id = 'business-documents'
              and public.user_can_access_business(public.storage_business_id(name)));

create policy "biz write: business-documents delete" on storage.objects
  for delete to authenticated
  using (bucket_id = 'business-documents'
         and public.user_can_access_business(public.storage_business_id(name)));

create policy "biz write: proposals insert" on storage.objects
  for insert to authenticated
  with check (bucket_id = 'proposals'
              and public.user_can_access_business(public.storage_business_id(name)));


-- ── ETS buckets: signed in, but not business-scoped ────────────────
-- client-images is keyed on a PROJECT id and ets-event-files on an
-- EVENT id (including 'draft-<timestamp>' ids that are not uuids at
-- all), so storage_business_id() returns NULL for them and a
-- business-scoped policy would refuse every legitimate write.
--
-- Requiring `authenticated` still removes the part that matters most:
-- an anonymous stranger can no longer upload into, or delete from,
-- these buckets. Scoping them properly needs the ETS ownership model,
-- which is a different piece of work than this one — recorded rather
-- than guessed at.

create policy "ets write: client-images insert" on storage.objects
  for insert to authenticated with check (bucket_id = 'client-images');

create policy "ets write: client-images delete" on storage.objects
  for delete to authenticated using (bucket_id = 'client-images');

create policy "ets write: ets-event-files insert" on storage.objects
  for insert to authenticated with check (bucket_id = 'ets-event-files');

create policy "ets write: ets-event-files delete" on storage.objects
  for delete to authenticated using (bucket_id = 'ets-event-files');
