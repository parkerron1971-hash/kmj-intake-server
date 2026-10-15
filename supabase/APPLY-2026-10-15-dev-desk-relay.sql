-- M-3 a1: apply by hand before deploying the relay code. Never applied by CI.
-- All tables and RPCs are service-role only. No browser policies.
begin;

create table if not exists public.dev_fleet_sessions (
  device_id uuid not null references public.dev_bridge_devices(id) on delete cascade,
  session_key text not null,
  handle text, kind text not null check (kind in ('claude','codex','grok','shell')),
  owner text not null check (owner in ('you','kai','chief')),
  project text, branch text, task text,
  state text not null check (state in ('starting','working','needs-you','ready','held','ended','unwatched')),
  since timestamptz, doing text, ask text, last text, idle_s int,
  hold jsonb, approval jsonb, mission jsonb, subagents int default 0,
  task_id uuid, on_phone boolean default false, permission_mode text,
  screen_rev int default 0, updated_at timestamptz not null default now(), ended_at timestamptz,
  primary key (device_id, session_key)
);
create index if not exists dev_fleet_sessions_ended_idx on public.dev_fleet_sessions (ended_at);
create table if not exists public.dev_fleet_screens (
  device_id uuid not null, session_key text not null,
  rev int not null, text text not null check (length(text) <= 16000), state text,
  at timestamptz not null default now(), received_at timestamptz not null default clock_timestamp(),
  primary key (device_id, session_key),
  foreign key (device_id, session_key) references public.dev_fleet_sessions on delete cascade
);
alter table public.dev_bridge_devices add column if not exists fleet_watch jsonb;
alter table public.dev_bridge_devices add column if not exists fleet_open_until timestamptz;

create table if not exists public.dev_cards (
  id uuid primary key default gen_random_uuid(), created_at timestamptz not null default now(),
  device_id uuid not null references public.dev_bridge_devices(id) on delete cascade,
  kind text not null check (kind in ('link','image','file','screenshot','preview')),
  title text, caption text, url text, mime text, bytes int, width int, height int, sha256 text,
  object_path text, thumb_path text, filename text, worker text, mission text,
  expires_at timestamptz not null default now() + interval '30 days'
);
create index if not exists dev_cards_expiry_idx on public.dev_cards (expires_at);
create table if not exists public.dev_alerts (
  id uuid primary key default gen_random_uuid(), created_at timestamptz not null default now(),
  source text not null, kind text, key text not null,
  level text not null check (level in ('info','warn','urgent')),
  title text, body text, nav text, card_id uuid, device_id uuid, watch_id uuid,
  delivered text not null check (delivered in ('pushed','inbox','deduped','quiet','rate','email','off')),
  pushed int not null default 0, count int not null default 1, read_at timestamptz, digested_at timestamptz
);
create index if not exists dev_alerts_key_idx on public.dev_alerts (key, created_at desc);
create index if not exists dev_alerts_unread_idx on public.dev_alerts (created_at desc) where read_at is null;
create index if not exists dev_alerts_digest_idx on public.dev_alerts (created_at) where digested_at is null and delivered in ('rate','quiet');
-- Hash-only dedupe tombstones let CI run/conclusion keys survive inbox retention.
create table if not exists public.dev_alert_dedupe (
  scope text primary key, source text not null, key text not null,
  alert_id uuid, seen_at timestamptz not null default now()
);
create table if not exists public.dev_alert_settings (
  id int primary key default 1 check (id = 1), settings jsonb not null, updated_at timestamptz not null default now()
);
insert into public.dev_alert_settings (id, settings) values (1, '{
  "enabled":true,"tz":"America/New_York",
  "quiet":{"on":true,"start":"22:00","end":"07:00","urgent_breaks_through":true,"morning_digest":true},
  "sources":{"worker_needs_you":"push","worker_finished":"inbox","kai":"push","missions":"push","session_crashed":"push","ci":"push","deploys":"push","sites":"push","schedules":"push","desktop_offline":"push"},
  "limits":{"per_hour":20,"per_source_10min":6},"email_fallback":"urgent"
}'::jsonb) on conflict (id) do nothing;

-- Serialize a device's full snapshot, deltas and screens. Every RPC checks
-- revocation again under this lock, closing the auth/write race.
create or replace function public.dev_fleet_sync(p_device uuid, p_full boolean, p_sessions jsonb)
returns jsonb language plpgsql set search_path = public as $$
declare r public.dev_fleet_sessions; stamp timestamptz := clock_timestamp(); total int;
begin
  perform 1 from public.dev_bridge_devices where id=p_device and not revoked for update;
  if not found then return '{"error":401}'::jsonb; end if;
  if jsonb_typeof(p_sessions) <> 'array' or jsonb_array_length(p_sessions)>60 then
    return '{"error":413}'::jsonb;
  end if;
  select count(*) into total from (
    select session_key from public.dev_fleet_sessions
      where device_id=p_device and ended_at is null and not p_full
        and session_key not in (select x->>'session_key' from jsonb_array_elements(p_sessions) x)
    union
    select x->>'session_key' from jsonb_array_elements(p_sessions) x where x->>'state'<>'ended'
  ) active;
  if total>60 then return '{"error":413}'::jsonb; end if;
  for r in select * from jsonb_populate_recordset(null::public.dev_fleet_sessions, p_sessions) loop
    insert into public.dev_fleet_sessions as existing
      (device_id,session_key,handle,kind,owner,project,branch,task,state,since,doing,ask,last,idle_s,
       hold,approval,mission,subagents,task_id,on_phone,permission_mode,screen_rev,updated_at,ended_at)
    values (p_device,r.session_key,r.handle,r.kind,r.owner,r.project,r.branch,r.task,r.state,r.since,
       r.doing,r.ask,r.last,r.idle_s,r.hold,r.approval,r.mission,coalesce(r.subagents,0),r.task_id,
       coalesce(r.on_phone,false),r.permission_mode,coalesce(r.screen_rev,0),stamp,
       case when r.state='ended' then stamp else null end)
    on conflict (device_id,session_key) do update set
      handle=excluded.handle,kind=excluded.kind,owner=excluded.owner,project=excluded.project,
      branch=excluded.branch,task=excluded.task,state=excluded.state,since=excluded.since,
      doing=excluded.doing,ask=excluded.ask,last=excluded.last,idle_s=excluded.idle_s,
      hold=excluded.hold,approval=excluded.approval,mission=excluded.mission,subagents=excluded.subagents,
      task_id=excluded.task_id,on_phone=excluded.on_phone,permission_mode=excluded.permission_mode,
      screen_rev=greatest(existing.screen_rev,excluded.screen_rev),updated_at=stamp,
      ended_at=case when excluded.state='ended' then coalesce(existing.ended_at,stamp) else null end;
  end loop;
  if p_full then
    update public.dev_fleet_sessions set state='ended',ended_at=stamp,updated_at=stamp
      where device_id=p_device and ended_at is null and session_key not in
        (select x->>'session_key' from jsonb_array_elements(p_sessions) x);
  end if;
  return '{"ok":true}'::jsonb;
end $$;

create or replace function public.dev_fleet_screen(p_device uuid,p_key text,p_rev int,p_text text,p_state text,p_at timestamptz)
returns jsonb language plpgsql set search_path = public as $$
declare previous public.dev_fleet_screens; stamp timestamptz := clock_timestamp();
begin
  perform 1 from public.dev_bridge_devices where id=p_device and not revoked for update;
  if not found then return '{"error":401}'::jsonb; end if;
  perform 1 from public.dev_fleet_sessions where device_id=p_device and session_key=p_key;
  if not found then return '{"error":404}'::jsonb; end if;
  select * into previous from public.dev_fleet_screens where device_id=p_device and session_key=p_key;
  if found then
    if p_rev<=previous.rev then return '{"ok":true,"stale":true}'::jsonb; end if;
    if stamp-previous.received_at<interval '1.5 seconds' then return '{"error":429}'::jsonb; end if;
  end if;
  if length(p_text)>16000 then return '{"error":413}'::jsonb; end if;
  insert into public.dev_fleet_screens(device_id,session_key,rev,text,state,at,received_at)
    values(p_device,p_key,p_rev,p_text,p_state,coalesce(p_at,stamp),stamp)
    on conflict(device_id,session_key) do update set rev=excluded.rev,text=excluded.text,
      state=excluded.state,at=excluded.at,received_at=stamp;
  update public.dev_fleet_sessions set screen_rev=greatest(screen_rev,p_rev)
    where device_id=p_device and session_key=p_key;
  return '{"ok":true}'::jsonb;
end $$;

-- Cards can spend time uploading: recheck the token at insert AND activation.
create or replace function public.dev_relay_active_device() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.device_id is not null then
    perform 1 from public.dev_bridge_devices where id=new.device_id and not revoked for update;
    if not found then raise exception 'device revoked' using errcode='42501'; end if;
  end if;
  return new;
end $$;
drop trigger if exists dev_cards_active_device on public.dev_cards;
create trigger dev_cards_active_device before insert or update on public.dev_cards
  for each row execute function public.dev_relay_active_device();

create or replace function public.dev_alert_claim(p_row jsonb) returns jsonb
language plpgsql set search_path = public as $$
declare r public.dev_alerts; old public.dev_alert_dedupe; scope_key text; stamp timestamptz := clock_timestamp();
begin
  -- Short transaction only; no delivery/network work under this lock.
  perform pg_advisory_xact_lock(37151015);
  r := jsonb_populate_record(null::public.dev_alerts,p_row);
  if r.device_id is not null then
    perform 1 from public.dev_bridge_devices where id=r.device_id and not revoked for update;
    if not found then raise exception 'device revoked' using errcode='42501'; end if;
  end if;
  scope_key := r.source || ':' || coalesce(r.device_id::text,'owner') || ':' || coalesce(r.watch_id::text,'none');
  -- Sites dedupe only the current transition; down/up/down must alert again.
  if r.source<>'sites' then scope_key := scope_key || ':' || r.key; end if;
  select * into old from public.dev_alert_dedupe where scope=scope_key;
  if found and old.key=r.key and (r.source in ('ci','sites') or old.seen_at>stamp-interval '30 minutes') then
    update public.dev_alerts set count=count+1 where id=old.alert_id;
    return jsonb_build_object('deduped',true);
  end if;
  insert into public.dev_alerts(id,created_at,source,kind,key,level,title,body,nav,card_id,device_id,watch_id,delivered,pushed,count)
    values(r.id,stamp,r.source,r.kind,r.key,r.level,r.title,r.body,r.nav,r.card_id,r.device_id,r.watch_id,'inbox',0,1)
    returning * into r;
  insert into public.dev_alert_dedupe(scope,source,key,alert_id,seen_at)
    values(scope_key,r.source,r.key,r.id,stamp) on conflict(scope) do update set
    key=excluded.key,alert_id=excluded.alert_id,seen_at=excluded.seen_at;
  return jsonb_build_object('row',to_jsonb(r),'deduped',false);
end $$;

create or replace function public.dev_alert_unread() returns bigint
language sql stable set search_path = public as $$
  select count(*) from public.dev_alerts where read_at is null
$$;

alter table public.dev_fleet_sessions enable row level security;
alter table public.dev_fleet_screens enable row level security;
alter table public.dev_cards enable row level security;
alter table public.dev_alerts enable row level security;
alter table public.dev_alert_dedupe enable row level security;
alter table public.dev_alert_settings enable row level security;
revoke all on public.dev_fleet_sessions, public.dev_fleet_screens, public.dev_cards,
  public.dev_alerts, public.dev_alert_dedupe, public.dev_alert_settings from anon, authenticated;
grant all on public.dev_fleet_sessions, public.dev_fleet_screens, public.dev_cards,
  public.dev_alerts, public.dev_alert_dedupe, public.dev_alert_settings to service_role;
revoke all on function public.dev_fleet_sync(uuid,boolean,jsonb),
  public.dev_fleet_screen(uuid,text,int,text,text,timestamptz), public.dev_relay_active_device(),
  public.dev_alert_claim(jsonb), public.dev_alert_unread() from public, anon, authenticated;
grant execute on function public.dev_fleet_sync(uuid,boolean,jsonb),
  public.dev_fleet_screen(uuid,text,int,text,text,timestamptz), public.dev_relay_active_device(),
  public.dev_alert_claim(jsonb), public.dev_alert_unread() to service_role;

insert into storage.buckets (id,name,public,file_size_limit,allowed_mime_types)
values ('dev-desk','dev-desk',false,10485760,
  array['image/png','image/jpeg','image/webp','image/gif','application/pdf','text/plain','text/markdown','application/json','text/csv'])
on conflict(id) do update set public=false,file_size_limit=excluded.file_size_limit,
  allowed_mime_types=excluded.allowed_mime_types;
-- Existing buckets may have broad permissive policies. These restrictive
-- guards keep this bucket service-only even when such a policy matches.
drop policy if exists dev_desk_service_only on storage.objects;
create policy dev_desk_service_only on storage.objects as restrictive for all to anon,authenticated
  using (bucket_id <> 'dev-desk') with check (bucket_id <> 'dev-desk');

commit;
