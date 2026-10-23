-- Photos in a group's chat (Kevin, 2026-10-20: "let's continue so we can
-- finish up"; the approved canvas "Church Groups, Together", board Chat:
-- the pantry photo; board Settings: "Photos and polls · Photos are checked
-- too. Leaders can hide one and tell the safety team."). A photo is a
-- message: its caption is the message's text, checked like any message;
-- the picture is checked before it's stored. Idempotent.
--
--   msg_photos   a message's picture: where it's stored (privately, under
--                this church's own chat-photos folder), its size, and
--                whether the message's text is a caption
begin;

create table if not exists public.msg_photos(
  message_id uuid primary key references public.msg_messages(id) on delete cascade,
  business_id uuid not null references public.businesses(id) on delete cascade,
  path text not null check (length(path) <= 300 and path like business_id::text || '/chat-photos/%.webp'),
  width int not null check (width between 1 and 4000),
  height int not null check (height between 1 and 4000),
  captioned boolean not null default false,
  created_at timestamptz not null default now()
);
create index if not exists msg_photos_business on public.msg_photos(business_id, created_at);

-- Server-only, like the messages themselves.
alter table public.msg_photos enable row level security;
revoke all on public.msg_photos from anon, authenticated;
grant all on public.msg_photos to service_role;

-- A photo's message is this church's own, and its file sits in that
-- message's own chat's folder.
create or replace function public.msg_photo_same_business() returns trigger
language plpgsql set search_path = public as $$
declare t uuid;
begin
  select m.thread_id into t from public.msg_messages m where m.id = new.message_id and m.business_id = new.business_id;
  if t is null then
    raise exception 'That message is not in this business';
  end if;
  if new.path not like new.business_id::text || '/chat-photos/' || t::text || '/%' then
    raise exception 'That photo is not in this chat''s folder';
  end if;
  return new;
end $$;
revoke all on function public.msg_photo_same_business() from public, anon, authenticated;
drop trigger if exists msg_photo_same_business on public.msg_photos;
create trigger msg_photo_same_business before insert or update on public.msg_photos
  for each row execute function public.msg_photo_same_business();

commit;
