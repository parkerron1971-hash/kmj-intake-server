-- The church's pictures and videos for Sunday's screens (ChurchSavvy,
-- step 2: the library Kevin asked for, 2026-10-19: "a place for library
-- stuff ... flyers and stuff that need to be found on the fly ... Videos
-- can get uploaded for video announcements"). One table, server-only (RLS
-- on, no policies, browser roles revoked); worship_media_router.py checks
-- the seat on every read and write.
--
--   worship_media   one picture or video: its name, the object in the
--                   public business-assets bucket ("{business}/worship-
--                   {id}.{ext}", a screen plays it with no sign-in, so it
--                   must not expire), its size and type. `status` is
--                   uploading until the server has checked the stored file
--                   is the picture or video it says it is; then ready.
-- Idempotent.
begin;

create table if not exists public.worship_media(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  kind text not null check (kind in ('image', 'video')),
  name text not null check (char_length(btrim(name)) between 1 and 120),
  object_name text not null check (object_name ~ '^[0-9a-f-]{36}/worship-[0-9a-f-]{36}\.(png|jpg|webp|mp4|webm|mov)$'),
  mime text not null check (mime in ('image/png', 'image/jpeg', 'image/webp', 'video/mp4', 'video/webm', 'video/quicktime')),
  bytes bigint not null check (bytes between 1 and 104857600),
  url text,
  status text not null default 'uploading' check (status in ('uploading', 'ready')),
  archived_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create unique index if not exists worship_media_object on public.worship_media (object_name);
create index if not exists worship_media_by_church on public.worship_media (business_id, archived_at, created_at desc);

alter table public.worship_media enable row level security;
revoke all on public.worship_media from anon, authenticated;
grant all on public.worship_media to service_role;

commit;
