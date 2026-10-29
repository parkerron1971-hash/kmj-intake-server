-- The stream relay's start, end and sweep can't step on each other
-- (2026-10-29, Kevin: "yes start on the fixes"; Codex's re-check of #1460,
-- findings B2-R and B3-R). Additive to APPLY-2026-10-16-stream-relay.sql,
-- which is applied and stays as it was. This file also carries the
-- heartbeat column that APPLY-2026-10-16-stream-relay-heartbeat.sql added
-- (never applied; folded in here, same statements), so it is the one
-- file to apply.
--
-- stream_sessions.last_seen_at  the last time the relay said this stream
--                               was still its own (POST /relay/started is
--                               also the heartbeat, every minute). A live
--                               session the relay stopped reporting is
--                               closed by the backend's own sweep.
--
-- stream_sessions.status gains 'ending': the service is over and its live
-- service is closed, but its sermon draft isn't saved yet. A session goes
-- live -> ending -> ended, never back. 'ending' doesn't hold the church's
-- one live slot, so the next service can start while the last one's draft
-- is still being saved.
--
-- Every change of state happens in one of these functions, under one lock
-- per church (a transaction advisory lock), so two requests can't
-- interleave inside a change:
--
--   stream_relay_claim      the relay's start/heartbeat for one run.
--                           Looks at THAT run's own session first: a run
--                           already ending or ended is answered "closed"
--                           and nothing else is touched (B2-R: an old
--                           run's retry never retires the newer one). A
--                           run the backend never saw, asked for only as
--                           it finishes, gets an 'ending' session and
--                           never touches the live one. A new live run
--                           takes over only from a live session that has
--                           stopped beating for p_quiet_s; one still
--                           beating answers "busy".
--   stream_relay_open_live  opens the member app's live service for a
--                           session AND links it, only while the session
--                           is still live (B3-R: a start retry that lost a
--                           race with the sweep opens nothing).
--   stream_relay_close      live -> ending, and closes its live service.
--   stream_relay_retire     the step both claim and close share.
--
-- Server-only, like the tables: execute is revoked from the browser roles
-- and granted to service_role. Idempotent; safe to run twice.
begin;

-- 1. The heartbeat (was APPLY-2026-10-16-stream-relay-heartbeat.sql).
alter table public.stream_sessions add column if not exists last_seen_at timestamptz;

-- The sweep reads live sessions by when they were last heard from.
create index if not exists stream_sessions_live_seen
  on public.stream_sessions(last_seen_at) where status = 'live';

-- 2. The 'ending' state. The applied table's inline check is named
-- stream_sessions_status_check by Postgres; it is replaced, and the guard
-- refuses the whole file if some other check on status is still there.
alter table public.stream_sessions drop constraint if exists stream_sessions_status_check;
alter table public.stream_sessions add constraint stream_sessions_status_check
  check (status in ('live', 'ending', 'ended'));
do $$ begin
  if exists (select 1 from pg_constraint
             where conrelid = 'public.stream_sessions'::regclass and contype = 'c'
               and conname <> 'stream_sessions_status_check'
               and pg_get_constraintdef(oid) ilike '%status%') then
    raise exception 'stream_sessions has another check on status; look before applying';
  end if;
end $$;

-- 3. The transitions.

create or replace function public.stream_relay_retire(p_session uuid, p_watch_prefix text, p_at timestamptz)
returns void language plpgsql set search_path = public as $$
declare v_s public.stream_sessions;
begin
  update public.stream_sessions set status = 'ending', ended_at = coalesce(ended_at, p_at)
    where id = p_session and status = 'live';
  select * into v_s from public.stream_sessions where id = p_session;
  if not found then
    return;
  end if;
  -- Its live service: the one it linked, or one of ours for this
  -- recording that never got linked.
  update public.live_sessions set status = 'ended', ended_at = p_at, updated_at = p_at
    where business_id = v_s.business_id and status = 'live'
      and (id = v_s.live_session_id or stream_url = p_watch_prefix || v_s.id::text);
end $$;

create or replace function public.stream_relay_claim(
  p_business uuid, p_session uuid, p_playlist text, p_ending boolean,
  p_recorded_s integer, p_bytes bigint, p_quiet_s integer, p_watch_prefix text)
returns jsonb language plpgsql set search_path = public as $$
declare
  v_s public.stream_sessions;
  v_cur public.stream_sessions;
  v_now timestamptz := clock_timestamp();
  v_rec integer := greatest(coalesce(p_recorded_s, 0), 0);
begin
  perform pg_advisory_xact_lock(hashtextextended('stream_relay:' || p_business::text, 0));
  -- This run's own session decides first.
  select * into v_s from public.stream_sessions where id = p_session;
  if found then
    if v_s.business_id <> p_business then
      return jsonb_build_object('outcome', 'foreign');
    end if;
    return jsonb_build_object('outcome', case when v_s.status = 'live' then 'live' else 'closed' end,
                              'session', to_jsonb(v_s));
  end if;
  if p_ending then
    -- A recording the backend never saw (it was down for the whole
    -- service): its session starts out over, beside whatever is live now.
    insert into public.stream_sessions(id, business_id, status, playlist_path, duration_s, bytes,
                                       started_at, last_seen_at, ended_at)
    values (p_session, p_business, 'ending', p_playlist, v_rec, greatest(coalesce(p_bytes, 0), 0),
            v_now - make_interval(secs => v_rec), v_now, v_now)
    returning * into v_s;
    return jsonb_build_object('outcome', 'opened', 'session', to_jsonb(v_s));
  end if;
  select * into v_cur from public.stream_sessions
    where business_id = p_business and status = 'live' limit 1;
  if found then
    if coalesce(v_cur.last_seen_at, v_cur.started_at) > v_now - make_interval(secs => p_quiet_s) then
      return jsonb_build_object('outcome', 'busy', 'holder', v_cur.id);
    end if;
    perform public.stream_relay_retire(v_cur.id, p_watch_prefix, v_now);
    select * into v_cur from public.stream_sessions where id = v_cur.id;
  end if;
  insert into public.stream_sessions(id, business_id, status, playlist_path, last_seen_at)
  values (p_session, p_business, 'live', p_playlist, v_now)
  returning * into v_s;
  return jsonb_build_object('outcome', 'opened', 'session', to_jsonb(v_s),
                            'retired', case when v_cur.id is null then null else to_jsonb(v_cur) end);
end $$;

create or replace function public.stream_relay_open_live(
  p_session uuid, p_live uuid, p_stream_url text, p_title text, p_watch_prefix text)
returns jsonb language plpgsql set search_path = public as $$
declare
  v_biz uuid;
  v_s public.stream_sessions;
  v_cur public.live_sessions;
  v_made public.live_sessions;
  v_now timestamptz := clock_timestamp();
begin
  select business_id into v_biz from public.stream_sessions where id = p_session;
  if not found then
    return jsonb_build_object('outcome', 'missing');
  end if;
  perform pg_advisory_xact_lock(hashtextextended('stream_relay:' || v_biz::text, 0));
  select * into v_s from public.stream_sessions where id = p_session;
  if not found then
    return jsonb_build_object('outcome', 'missing');
  end if;
  if v_s.status <> 'live' then
    return jsonb_build_object('outcome', 'closed', 'session', to_jsonb(v_s));
  end if;
  if v_s.live_session_id is not null then
    return jsonb_build_object('outcome', 'linked', 'live_id', v_s.live_session_id);
  end if;
  select * into v_cur from public.live_sessions
    where business_id = v_biz and status = 'live' limit 1 for update;
  if found then
    if v_cur.stream_url = p_stream_url then
      update public.stream_sessions set live_session_id = v_cur.id where id = p_session;
      return jsonb_build_object('outcome', 'adopted', 'live', to_jsonb(v_cur));
    end if;
    if left(v_cur.stream_url, length(p_watch_prefix)) <> p_watch_prefix then
      -- The team went live with another link: theirs is left alone.
      return jsonb_build_object('outcome', 'manual');
    end if;
    -- Ours, for another recording. This church's one live recording is
    -- p_session, so that one is over and its service is left over.
    update public.live_sessions set status = 'ended', ended_at = v_now, updated_at = v_now
      where id = v_cur.id;
  end if;
  insert into public.live_sessions(id, business_id, title, stream_url, status, chat_open)
  values (p_live, v_biz, p_title, p_stream_url, 'live', true)
  on conflict (id) do nothing
  returning * into v_made;
  update public.stream_sessions set live_session_id = p_live where id = p_session;
  if v_made.id is null then
    -- This recording's service was opened before and someone ended it by
    -- hand: it stays ended.
    return jsonb_build_object('outcome', 'linked', 'live_id', p_live);
  end if;
  return jsonb_build_object('outcome', 'opened', 'live', to_jsonb(v_made));
end $$;

create or replace function public.stream_relay_close(p_session uuid, p_watch_prefix text)
returns jsonb language plpgsql set search_path = public as $$
declare
  v_biz uuid;
  v_s public.stream_sessions;
begin
  select business_id into v_biz from public.stream_sessions where id = p_session;
  if not found then
    return jsonb_build_object('outcome', 'missing');
  end if;
  perform pg_advisory_xact_lock(hashtextextended('stream_relay:' || v_biz::text, 0));
  select * into v_s from public.stream_sessions where id = p_session;
  if not found then
    return jsonb_build_object('outcome', 'missing');
  end if;
  if v_s.status = 'ended' then
    return jsonb_build_object('outcome', 'ended', 'session', to_jsonb(v_s));
  end if;
  perform public.stream_relay_retire(p_session, p_watch_prefix, clock_timestamp());
  select * into v_s from public.stream_sessions where id = p_session;
  return jsonb_build_object('outcome', 'ending', 'session', to_jsonb(v_s));
end $$;

revoke all on function public.stream_relay_retire(uuid, text, timestamptz) from public, anon, authenticated;
revoke all on function public.stream_relay_claim(uuid, uuid, text, boolean, integer, bigint, integer, text)
  from public, anon, authenticated;
revoke all on function public.stream_relay_open_live(uuid, uuid, text, text, text) from public, anon, authenticated;
revoke all on function public.stream_relay_close(uuid, text) from public, anon, authenticated;
grant execute on function public.stream_relay_retire(uuid, text, timestamptz),
  public.stream_relay_claim(uuid, uuid, text, boolean, integer, bigint, integer, text),
  public.stream_relay_open_live(uuid, uuid, text, text, text),
  public.stream_relay_close(uuid, text) to service_role;

commit;

notify pgrst, 'reload schema';
