-- Our own stream relay (2026-10-16, Kevin: "lets fix and build now").
--
-- The church's streaming software sends ONE stream to our relay server
-- (a DigitalOcean droplet, stream_relay/ in this repo). The relay passes
-- copies on to YouTube and Facebook unchanged and writes the service to
-- Cloudflare R2 as it streams, so members can watch live in the member
-- app and the recording becomes a sermon draft when the service ends.
--
-- church_streams   one row per church: its stream key (hashed; the
--                  church sees the full key once, when it is made) and
--                  where copies go. YouTube / Facebook stream keys are
--                  Fernet ciphertext (STREAM_DEST_ENCRYPTION_KEY).
-- stream_sessions  one row per service the relay saw: when, how long,
--                  where the recording lives, and the live service and
--                  sermon draft it made.
--
-- Both are SERVER-ONLY (like live_sessions): stream_relay_router.py is
-- the only door, behind the church's manager check or the relay's shared
-- secret. Idempotent.
begin;

create table if not exists public.church_streams(
  business_id uuid primary key references public.businesses(id) on delete cascade,
  key_hash text not null unique check (key_hash ~ '^[0-9a-f]{64}$'),
  key_last4 text not null check (length(key_last4) = 4),
  youtube_on boolean not null default false,
  youtube_key_enc text not null default '',
  facebook_on boolean not null default false,
  facebook_key_enc text not null default '',
  -- Make a sermon draft from each recording (the church publishes it).
  sermon_drafts boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.stream_sessions(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  status text not null default 'live' check (status in ('live','ended')),
  -- The live service this stream started (null when the team had
  -- already gone live with another link; theirs is left alone).
  live_session_id uuid references public.live_sessions(id) on delete set null,
  sermon_id uuid references public.sermons(id) on delete set null,
  -- R2 object path of the HLS playlist: live/<business>/<session>/index.m3u8
  playlist_path text not null default '' check (length(playlist_path) <= 300),
  duration_s integer not null default 0 check (duration_s >= 0),
  bytes bigint not null default 0 check (bytes >= 0),
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  created_at timestamptz not null default now()
);
-- One live stream at a time per church.
create unique index if not exists stream_sessions_one_live on public.stream_sessions(business_id) where status = 'live';
create index if not exists stream_sessions_business on public.stream_sessions(business_id, started_at desc);

do $$ declare t text; begin
  foreach t in array array['church_streams','stream_sessions'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
  end loop;
end $$;

commit;
