-- Sermons (Kevin's church plan, "Sermons & Live": a sermon library by
-- series; live streams come next). Idempotent.
--
-- A sermon is a message preached on a day: its title, speaker, scripture,
-- a short summary, questions for small groups, and where to watch or
-- listen (a YouTube / Vimeo / Facebook link, an audio link). Series group
-- them ("Romans: Grace Upon Grace"). Published sermons appear on the
-- church's site at /sermons; drafts stay in the app.
--
-- Access is the rest of the church's records (like attendance and groups):
-- the owner and writing seats edit, any seat reads. The public page is
-- rendered by the server (service role) and shows published sermons only.
begin;

create table if not exists public.sermon_series(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  title text not null check (length(btrim(title)) between 1 and 100),
  description text not null default '' check (length(description) <= 1000),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists sermon_series_business on public.sermon_series(business_id, title);

create table if not exists public.sermons(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  series_id uuid references public.sermon_series(id) on delete set null,
  title text not null check (length(btrim(title)) between 1 and 160),
  preached_on date not null,
  speaker text not null default '' check (length(speaker) <= 100),
  scripture text not null default '' check (length(scripture) <= 160),
  summary text not null default '' check (length(summary) <= 2000),
  -- For small groups to talk through during the week.
  questions text not null default '' check (length(questions) <= 2000),
  video_url text not null default '' check (video_url = '' or (length(video_url) <= 500 and video_url ~ '^https://')),
  audio_url text not null default '' check (audio_url = '' or (length(audio_url) <= 500 and audio_url ~ '^https://')),
  published boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists sermons_business on public.sermons(business_id, published, preached_on desc);
create index if not exists sermons_series on public.sermons(series_id);

do $$ declare t text; begin
  foreach t in array array['sermon_series','sermons'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('drop policy if exists business_member_access on public.%I', t);
    execute format('create policy business_member_access on public.%I for all to authenticated
      using (business_id in (select id from public.businesses where owner_id = auth.uid()))
      with check (business_id in (select id from public.businesses where owner_id = auth.uid()))', t);
    execute format('drop policy if exists tenant_writer_write on public.%I', t);
    execute format('create policy tenant_writer_write on public.%I for all to authenticated
      using (public.is_business_writer(business_id)) with check (public.is_business_writer(business_id))', t);
    execute format('drop policy if exists tenant_member_read on public.%I', t);
    execute format('create policy tenant_member_read on public.%I for select to authenticated
      using (public.is_business_member(business_id))', t);
    execute format('revoke all on public.%I from anon', t);
    execute format('grant select, insert, update, delete on public.%I to authenticated', t);
    execute format('grant all on public.%I to service_role', t);
  end loop;
end $$;

-- A sermon's series must be this church's own.
create or replace function public.sermons_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.series_id is not null and not exists (
       select 1 from public.sermon_series s where s.id = new.series_id and s.business_id = new.business_id) then
    raise exception 'That series is not in this business';
  end if;
  return new;
end $$;
revoke all on function public.sermons_same_business() from public, anon, authenticated;
drop trigger if exists sermons_same_business on public.sermons;
create trigger sermons_same_business before insert or update on public.sermons
  for each row execute function public.sermons_same_business();

commit;
