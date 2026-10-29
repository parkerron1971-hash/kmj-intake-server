-- Homework files nothing points at any more (2026-10-18), the loose end left
-- by uploads (APPLY-2026-10-18-academy-uploads.sql).
--
-- A file in the private academy-work bucket belongs to one academy_item_work
-- row (its file_path). When the homework, the student or the whole class is
-- deleted, the row goes with it but the file stays; so does a file stored
-- whose attach never landed. A deleted account's files already go with it
-- (account_lifecycle.STORAGE_BUCKETS). academy_work_orphans names the rest,
-- oldest first, and academy_work.sweep_tick deletes them through the storage
-- API once a day.
--
-- Only files a day old or more: an upload is attached within seconds of being
-- stored, so a file in flight is never one. Only names in the one shape the
-- backend stores. Service role only, like the rest of the bucket.
--
-- Idempotent. Rehearsed with a rollback probe; applied by hand like every
-- APPLY file.

begin;

create index if not exists academy_item_work_file_path_idx
  on public.academy_item_work (file_path) where file_path is not null;

create or replace function public.academy_work_orphans(p_limit int default 500)
returns jsonb language sql stable security definer set search_path to 'public', 'pg_temp' as $$
  select coalesce(jsonb_agg(f.name order by f.created_at), '[]'::jsonb)
    from (select o.name, o.created_at
            from storage.objects o
           where o.bucket_id = 'academy-work'
             and o.created_at < now() - interval '1 day'
             and o.name ~ '^[0-9a-f-]{36}/[0-9a-f-]{36}/[0-9a-f-]{36}-[0-9a-f-]{36}-[0-9a-f]{8}\.(jpg|png|pdf|mp3|m4a|ogg|wav|webm|mp4|mov)$'
             and not exists (select 1 from public.academy_item_work w where w.file_path = o.name)
           order by o.created_at
           limit least(greatest(coalesce(p_limit, 500), 1), 1000)) f
$$;
revoke all on function public.academy_work_orphans(int) from public, anon, authenticated;
grant execute on function public.academy_work_orphans(int) to service_role;

commit;
