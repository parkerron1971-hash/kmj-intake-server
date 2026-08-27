-- Chief's first seven days (2026-08-28): one row per business recording
-- the day-one arc — when the trial actually began, whether Chief has
-- introduced herself yet, and how far the practitioner has walked.
--
-- WHY A ROW AND NOT A COMPUTED ANSWER
-- The day-one plug-in list is already recomputed on every Chief turn
-- from live probes (business_track_router.resolve_plugins), and it stays
-- the authority on what is DONE. What a probe cannot know is what has
-- been SAID: whether the introduction was delivered, which steps Chief
-- already congratulated, which links were already handed over. "Done" is
-- cheap to recompute; a conversation is not, which is why this is stored
-- rather than derived.
--
-- WHY started_at IS NOT trial_ends_at MINUS SEVEN
-- usage_metering.trial_window_start() derives the trial's first instant
-- by subtracting the configured length from trial_ends_at, and says so —
-- it moves if the dial moves. That is fine for a credit tank, which is a
-- budget. It is wrong for a narrative: "which day of your week is this"
-- must not shift under someone because an env var changed on Thursday.
-- The arc stamps its own start, once, and counts from that.
--
-- SERVICE-ROLE ONLY (dev_tasks / platform_changelog precedent): RLS on,
-- no policies. Nothing in the frontend reads this table directly — the
-- arc's state rides on GET /billing/access, which the server answers
-- with the service-role key after its own owner check. If a direct
-- client read is ever wanted, add an owner-scoped policy through
-- public.is_business_owner (docs/RLS_MODEL.md rule 2) — never an inline
-- cross-table EXISTS (rule 2, the 42P17 outage) and never USING (true)
-- (rule 3, one permissive policy defeats all the others).
--
-- Idempotent; apply after merge.

create table if not exists public.first_run_arc (
  id                 uuid primary key default gen_random_uuid(),
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),

  business_id        uuid not null
                     references public.businesses(id) on delete cascade,

  -- What `started_at` is anchored to — and the arc's one and only state
  -- transition. 'signup' is business creation, the ONLY door for comped,
  -- invited and grandfathered accounts (they never reach Stripe at all).
  -- 'subscription' is a Stripe subscription entering `trialing`.
  --
  -- A signup-anchored arc flips to 'subscription' exactly once: when the
  -- trial actually begins, and only while the introduction is still
  -- undelivered. After the flip it never moves again — which is what
  -- stops a repeated or replayed `trialing` webhook (Stripe sends
  -- `updated` for any trial-period change, not just `created`) from
  -- resetting somebody to day one a second time.
  source             text not null
                     check (source in ('subscription', 'signup')),

  -- Day one is counted from here. Stamped once by whichever door opened
  -- the arc first; a re-subscribe, a plan change or a replayed webhook
  -- must never move it.
  started_at         timestamptz not null default now(),

  -- NULL when the arc opened at signup and no subscription exists yet.
  -- A later subscription fills this in without touching started_at.
  trial_ends_at      timestamptz,

  status             text not null default 'pending_intro'
                     check (status in ('pending_intro', 'walking',
                                       'done', 'dismissed')),

  -- Set when Chief's introduction has actually been delivered, so a
  -- refresh never replays it.
  intro_delivered_at timestamptz,

  -- PLUGIN_CATALOG keys the arc has already acknowledged. The live
  -- probes remain the authority on what is done; this records what Chief
  -- has already congratulated, so she never congratulates it twice.
  completed_steps    jsonb not null default '[]'::jsonb,

  -- Share-kit keys already handed over, so day seven does not re-offer a
  -- link they copied on day two.
  shared_links       jsonb not null default '[]'::jsonb,

  -- The last daily beat sent, and when. 0 = none sent yet.
  last_beat_day      smallint not null default 0,
  last_beat_at       timestamptz
);

-- One arc per business. This is the idempotency guarantee begin() leans
-- on: two doors can race (a webhook and a signup in the same second) and
-- exactly one row survives, so nobody gets two day-ones.
create unique index if not exists first_run_arc_business_idx
  on public.first_run_arc (business_id);

-- The daily-beat sweep asks one question: which live arcs are due a
-- beat? Partial, because a finished or dismissed arc is never swept.
create index if not exists first_run_arc_active_idx
  on public.first_run_arc (last_beat_at nulls first)
  where status in ('pending_intro', 'walking');

alter table public.first_run_arc enable row level security;
