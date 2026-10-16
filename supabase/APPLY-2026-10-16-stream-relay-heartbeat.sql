-- The stream relay hears from the relay every minute (2026-10-16, Codex's
-- review of #1460/#1461, findings B2/B3/R4). Additive to
-- APPLY-2026-10-16-stream-relay.sql, which is already applied and stays
-- as it was.
--
-- stream_sessions.last_seen_at  the last time the relay said this stream
--                               was still its own (POST /relay/started is
--                               also the heartbeat, every minute). A live
--                               session the relay stopped reporting —
--                               a lost droplet, a finish that never got
--                               through — is closed by the backend's own
--                               sweep (stream_relay_router.sweep_stale)
--                               instead of staying "live" forever and
--                               being reused next Sunday.
--
-- Nothing else changes: a session still ends exactly once (status goes to
-- 'ended' only after its live service is closed and its draft is saved),
-- and the draft's id is derived from the session's, so a retried or
-- doubled end makes one draft (sermons' own primary key is the guard).
-- Idempotent; safe to run twice.
begin;

alter table public.stream_sessions add column if not exists last_seen_at timestamptz;

-- The sweep reads live sessions by when they were last heard from.
create index if not exists stream_sessions_live_seen
  on public.stream_sessions(last_seen_at) where status = 'live';

commit;
