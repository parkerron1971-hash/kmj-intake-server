-- ROLLBACK-2026-11-20-client-images-owner-writes.sql
--
-- Puts the client-images write policies back as
-- APPLY-2026-08-09-storage-write-lockdown.sql left them. This REOPENS the
-- hole the apply file closed: any signed-in login of any business can
-- upload into the bucket and delete from it again. Reads are untouched.
-- One transaction, lock_timeout 5s, safe to run twice.

begin;
set local lock_timeout = '5s';

drop policy if exists "ets write: client-images insert" on storage.objects;
create policy "ets write: client-images insert" on storage.objects for insert to authenticated
  with check (bucket_id = 'client-images');

drop policy if exists "ets write: client-images delete" on storage.objects;
create policy "ets write: client-images delete" on storage.objects for delete to authenticated
  using (bucket_id = 'client-images');

commit;
