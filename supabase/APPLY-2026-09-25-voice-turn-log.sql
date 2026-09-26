-- APPLY-2026-09-25-voice-turn-log.sql
--
-- One row per spoken call turn, reported by the app itself (ChiefCallMode →
-- POST /agents/chief/voice/turn → voice_metrics.record). Only the app can
-- hear audio, so only the app can measure time to first AUDIO: from the end
-- of the practitioner's turn (the speech relay's speech_stopped) to the
-- first audible sample Chief made. The SLO is 1000ms at p95
-- (VOICE_TTFA_BUDGET_MS), kept apart from the first-TOKEN SLO in
-- model_route_log; join the two on request_id.
--
-- Server-owned rows: RLS on, NO policies, no anon/authenticated grants.
-- The service role writes; the owner reads through GET /platform/voice/stats.
-- The code is fail-soft without this table: the [voice] log line carries
-- every field. Durations and counts only; no transcript, no reply text.
--
-- Idempotent.

create table if not exists public.voice_turn_log (
  id              uuid primary key default gen_random_uuid(),
  created_at      timestamptz not null default now(),
  request_id      text,
  business_id     uuid,
  user_id         uuid,
  ttfa_ms         integer,          -- turn end → first audible sample (THE number)
  reply_audio_ms  integer,          -- turn end → first audio of the reply itself
  transcript_ms   integer,          -- turn end → transcript in hand
  first_text_ms   integer,          -- turn end → first reply text on the wire
  vad_silence_ms  integer,          -- the silence the relay waits before speech_stopped
  first_audio     text,             -- opener | lead | reply | phrase | none
  outcome         text,             -- spoken | interrupted | failed | silent | superseded
  engine          text,             -- openai | elevenlabs | browser | unknown
  barge_in        boolean not null default false,
  barge_in_ms     integer,          -- practitioner started talking → Chief went quiet
  underruns       integer,
  tts_requests    integer,
  tts_cache_hits  integer,
  budget_ms       integer,
  slo_applies     boolean not null default true,
  slo_met         boolean
);

create index if not exists voice_turn_log_created_idx
  on public.voice_turn_log (created_at desc);
create index if not exists voice_turn_log_request_idx
  on public.voice_turn_log (request_id);

alter table public.voice_turn_log enable row level security;
revoke all on table public.voice_turn_log from anon, authenticated;

-- Verify:
--   select relrowsecurity from pg_class where relname = 'voice_turn_log';           -- true
--   select count(*) from pg_policies where tablename = 'voice_turn_log';            -- 0
--
-- Time to first audio vs time to first token, the same turns:
--   select percentile_cont(0.95) within group (order by v.ttfa_ms) as ttfa_p95,
--          percentile_cont(0.95) within group (order by m.ttft_ms) as ttft_p95,
--          count(*)
--     from public.voice_turn_log v
--     left join public.model_route_log m on m.request_id = v.request_id
--    where v.slo_applies and v.created_at > now() - interval '1 day';
