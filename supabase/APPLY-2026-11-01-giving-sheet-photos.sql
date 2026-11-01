-- The paper count sheet's photo, kept for good (Kevin, 2026-11-01: "store
-- those pictures and the data for future checks and balances so we have
-- hard copies digital copies and batches"). giving_sheets.py.
--
--   giving_count_photos   one photo of a filled-in count sheet: where it is
--                         in storage, what was read from it (the draft),
--                         and the gifts it became once the treasurer saved
--                         them (status used). Server-only (RLS on, no
--                         policies, browser roles revoked).
--   storage bucket giving-sheets   PRIVATE. The photos are read through
--                         signed links the server makes for finance people
--                         only; no storage policy lets a browser in.
-- Idempotent.
begin;

create table if not exists public.giving_count_photos(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  count_id uuid not null references public.giving_counts(id) on delete cascade,
  path text not null check (char_length(path) between 10 and 300),
  media_type text not null check (media_type in ('image/jpeg', 'image/png', 'image/webp')),
  status text not null default 'reading' check (status in ('reading', 'read', 'unread', 'used')),
  draft jsonb check (draft is null or (jsonb_typeof(draft) = 'object' and octet_length(draft::text) <= 200000)),
  error text check (error is null or char_length(error) <= 300),
  gift_ids uuid[] not null default '{}' check (cardinality(gift_ids) <= 200),
  created_by uuid,
  created_at timestamptz not null default now(),
  used_at timestamptz
);
create index if not exists giving_count_photos_by_count
  on public.giving_count_photos (business_id, count_id, created_at);

alter table public.giving_count_photos enable row level security;
revoke all on public.giving_count_photos from anon, authenticated;
grant all on public.giving_count_photos to service_role;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('giving-sheets', 'giving-sheets', false, 8388608, array['image/jpeg', 'image/png', 'image/webp'])
on conflict (id) do update set public = false, file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

commit;

-- Check:
--   select to_regclass('public.giving_count_photos');
--   select id, public, file_size_limit from storage.buckets where id = 'giving-sheets';   -- false, 8388608
