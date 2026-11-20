-- APPLY-2026-11-20-client-images-owner-writes.sql
--
-- Only the platform owner adds to or deletes from the client-images bucket.
--
-- Read from production 2026-11-20: the bucket is public (anyone may READ a
-- file by its address, on purpose: the pictures are shown on pages), 3
-- objects, and its two write policies (from
-- APPLY-2026-08-09-storage-write-lockdown.sql) check only the bucket:
--   "ets write: client-images insert"  INSERT TO authenticated
--      WITH CHECK (bucket_id = 'client-images')
--   "ets write: client-images delete"  DELETE TO authenticated
--      USING (bucket_id = 'client-images')
-- so any signed-in login of any business on the platform could upload into
-- it or delete what is there. The 08-09 file recorded this and left it,
-- because the paths are keyed on a project id, not a business id.
--
-- Who writes there: only the app's ClientImagePanel (src/lib/supabase.ts
-- uploadClientImage / deleteProjectImage), inside the Director page of the
-- Solutionist module, which only the platform owner can open
-- (SolutionistLayout hands it over only when isOwner). So the writes get
-- the same rule as the Embrace the Shift files (#1972): the bucket AND
-- public.is_platform_owner(). Reads are unchanged ("Allow public reads").
--
-- One transaction, lock_timeout 5s, safe to run twice. Each DROP/CREATE
-- POLICY takes a brief lock on storage.objects (catalog only, no rows
-- read or changed): apply at a quiet time. A safety check stops it, with
-- nothing changed, if is_platform_owner() is missing.
--
-- Rollback: supabase/ROLLBACK-2026-11-20-client-images-owner-writes.sql
-- (REOPENS the hole: any signed-in login writes again).
--
-- Check before (read-only). Expect 3 rows: "Allow public reads" (SELECT,
-- {public}), the insert and the delete as above (bucket only).
--   select policyname, cmd, roles, qual, with_check
--     from pg_policies
--    where schemaname = 'storage' and tablename = 'objects'
--      and coalesce(qual, '') || coalesce(with_check, '') like '%client-images%'
--    order by 1;

begin;
set local lock_timeout = '5s';

do $$
begin
  if to_regprocedure('public.is_platform_owner()') is null then
    raise exception 'client-images-owner-writes: public.is_platform_owner() is missing; nothing was changed';
  end if;
end
$$;

drop policy if exists "ets write: client-images insert" on storage.objects;
create policy "ets write: client-images insert" on storage.objects for insert to authenticated
  with check (bucket_id = 'client-images' and public.is_platform_owner());

drop policy if exists "ets write: client-images delete" on storage.objects;
create policy "ets write: client-images delete" on storage.objects for delete to authenticated
  using (bucket_id = 'client-images' and public.is_platform_owner());

commit;

-- Check after (read-only). Expect 3 rows: "Allow public reads" as before;
-- the insert and the delete each with bucket_id = 'client-images' AND
-- is_platform_owner().
--   select policyname, cmd, roles, qual, with_check
--     from pg_policies
--    where schemaname = 'storage' and tablename = 'objects'
--      and coalesce(qual, '') || coalesce(with_check, '') like '%client-images%'
--    order by 1;
-- And no storage write policy names no bucket. Expect 0.
--   select count(*) from pg_policies
--    where schemaname = 'storage' and tablename = 'objects' and cmd <> 'SELECT'
--      and coalesce(qual, '') || coalesce(with_check, '') not like '%bucket_id%';
