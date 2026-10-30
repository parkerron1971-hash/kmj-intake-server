-- The stream relay's start, end and sweep can't step on each other
-- (2026-10-29, Kevin: "yes start on the fixes"; Codex's re-checks of #1460,
-- findings B2-R, B3-R and B3-F). Additive to APPLY-2026-10-16-stream-relay.sql,
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
-- stream_sessions.draft_owed    an ended session still owes its sermon
--                               draft: a late end's real length took it
--                               past the line after a shorter count had
--                               already finished it with none. Set in the
--                               same step that saves that length, cleared
--                               only when the draft is made (B3-F2).
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
--   stream_relay_close      raises the saved totals to the caller's (never
--                           lowers them), then live -> ending and closes
--                           its live service. The end's totals are saved
--                           before anything can fail (B3-F). On an ended
--                           session with no draft, totals that take the
--                           saved length past the line mark the draft
--                           owed, in the same update (B3-F2).
--   stream_relay_finish     ending -> ended, together with the sermon draft:
--                           made from the SAVED length and the church's
--                           own setting, inserted and linked in the same
--                           step, so nothing can mark a session ended
--                           before its draft is accounted for (B3-F). An
--                           ended session is only ever given a draft while
--                           it is marked owed, and making it (or the
--                           church having drafts off) clears the mark.
--   stream_relay_retire     the step both claim and close share.
--
-- stream_relay_beat (the heartbeat's totals and last_seen_at) is one
-- UPDATE of a live row, raising never lowering; the row lock it takes
-- orders it against close, so it needs no church lock.
--
-- Server-only, like the tables: execute is revoked from the browser roles
-- and granted to service_role. Idempotent; safe to run twice.
begin;

-- 1. The heartbeat (was APPLY-2026-10-16-stream-relay-heartbeat.sql).
alter table public.stream_sessions add column if not exists last_seen_at timestamptz;

-- The sweep reads live sessions by when they were last heard from.
create index if not exists stream_sessions_live_seen
  on public.stream_sessions(last_seen_at) where status = 'live';

-- The late end's owed draft (B3-F2). The sweep reads these too.
alter table public.stream_sessions add column if not exists draft_owed boolean not null default false;

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

-- Earlier drafts of this file had close without the totals, close without
-- the line, and finish with the caller's "late" flag; a re-run replaces
-- them rather than leaving a second close or finish beside the new ones.
drop function if exists public.stream_relay_close(uuid, text);
drop function if exists public.stream_relay_close(uuid, text, integer, bigint);
drop function if exists public.stream_relay_finish(uuid, uuid, text, date, text, integer, boolean);

create or replace function public.stream_relay_close(
  p_session uuid, p_watch_prefix text, p_duration_s integer, p_bytes bigint, p_min_s integer)
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
  -- The caller's totals are saved first, whatever happens after: raised,
  -- never lowered, in every state (a late end's real length counts too).
  -- A late end whose totals take an ended session with no draft past the
  -- line marks the draft owed in this same update (the right-hand side
  -- reads the row as it was), so a retry or the sweep makes it whatever
  -- fails after this commits (B3-F2). A deleted draft's session is
  -- already past the line: no later end marks it again.
  update public.stream_sessions
    set duration_s = greatest(duration_s, coalesce(p_duration_s, 0)),
        bytes = greatest(bytes, coalesce(p_bytes, 0)),
        draft_owed = draft_owed or (status = 'ended' and sermon_id is null
                                    and duration_s < p_min_s and coalesce(p_duration_s, 0) >= p_min_s)
    where id = p_session;
  if v_s.status <> 'ended' then
    perform public.stream_relay_retire(p_session, p_watch_prefix, clock_timestamp());
  end if;
  select * into v_s from public.stream_sessions where id = p_session;
  return jsonb_build_object('outcome', case when v_s.status = 'ended' then 'ended' else 'ending' end,
                            'session', to_jsonb(v_s));
end $$;

create or replace function public.stream_relay_finish(
  p_session uuid, p_sermon uuid, p_title text, p_preached_on date, p_video_url text, p_min_s integer)
returns jsonb language plpgsql set search_path = public as $$
declare
  v_biz uuid;
  v_s public.stream_sessions;
  v_drafts boolean;
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
  if v_s.status = 'live' then
    return jsonb_build_object('outcome', 'live', 'session', to_jsonb(v_s));   -- close comes first
  end if;
  if v_s.status = 'ended' and not v_s.draft_owed then
    -- Another finalizer got here first: its answer stands. Every total any
    -- finalizer knew was saved by its close before this, so the winner
    -- decided on the longest length known.
    return jsonb_build_object('outcome', 'ended', 'session', to_jsonb(v_s));
  end if;
  select sermon_drafts into v_drafts from public.church_streams where business_id = v_biz;
  if v_s.sermon_id is null and coalesce(v_drafts, false) and v_s.duration_s >= p_min_s then
    if p_title is null or p_preached_on is null or p_video_url is null then
      -- The saved length passed the line after this caller looked: it
      -- comes back once with the draft's title and date.
      return jsonb_build_object('outcome', 'needs_draft', 'session', to_jsonb(v_s));
    end if;
    insert into public.sermons(id, business_id, title, preached_on, video_url, published)
    values (p_sermon, v_biz, p_title, p_preached_on, p_video_url, false)
    on conflict (id) do nothing;
    update public.stream_sessions set sermon_id = p_sermon where id = p_session;
  end if;
  -- Ending or owed, the draft is accounted for now: made, already linked,
  -- too short, or the church has drafts off.
  update public.stream_sessions set status = 'ended', draft_owed = false where id = p_session;
  select * into v_s from public.stream_sessions where id = p_session;
  return jsonb_build_object('outcome', 'ended', 'session', to_jsonb(v_s));
end $$;

create or replace function public.stream_relay_beat(p_session uuid, p_recorded_s integer, p_bytes bigint)
returns jsonb language plpgsql set search_path = public as $$
declare v_n integer;
begin
  -- One statement on a live row. A close holding this row (it updates it
  -- first, under the church lock) makes this wait, then re-check status:
  -- an ended or ending session is left alone.
  update public.stream_sessions
    set last_seen_at = clock_timestamp(),
        duration_s = greatest(duration_s, coalesce(p_recorded_s, 0)),
        bytes = greatest(bytes, coalesce(p_bytes, 0))
    where id = p_session and status = 'live';
  get diagnostics v_n = row_count;
  return jsonb_build_object('outcome', case when v_n = 1 then 'beat' else 'not_live' end);
end $$;

revoke all on function public.stream_relay_retire(uuid, text, timestamptz) from public, anon, authenticated;
revoke all on function public.stream_relay_claim(uuid, uuid, text, boolean, integer, bigint, integer, text)
  from public, anon, authenticated;
revoke all on function public.stream_relay_open_live(uuid, uuid, text, text, text) from public, anon, authenticated;
revoke all on function public.stream_relay_close(uuid, text, integer, bigint, integer) from public, anon, authenticated;
revoke all on function public.stream_relay_finish(uuid, uuid, text, date, text, integer)
  from public, anon, authenticated;
revoke all on function public.stream_relay_beat(uuid, integer, bigint) from public, anon, authenticated;
grant execute on function public.stream_relay_retire(uuid, text, timestamptz),
  public.stream_relay_claim(uuid, uuid, text, boolean, integer, bigint, integer, text),
  public.stream_relay_open_live(uuid, uuid, text, text, text),
  public.stream_relay_close(uuid, text, integer, bigint, integer),
  public.stream_relay_finish(uuid, uuid, text, date, text, integer),
  public.stream_relay_beat(uuid, integer, bigint) to service_role;

commit;

notify pgrst, 'reload schema';
