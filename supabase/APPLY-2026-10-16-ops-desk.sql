-- The ops desk: Kevin's own operating system for running Solutionist alone
-- (Kevin, 2026-10-15: "make my operation easy … a task list that can connect
-- to calendar on my phone … build path for KAI … turn what you found into a
-- system for myself"). Idempotent.
--
--   platform_ops_tasks     every piece of work, in one of four lanes:
--                          fix (no limit), build (two at a time — ops_desk.py
--                          enforces it), try (ideas; never merges), ops
--                          (the chores that keep the company running).
--   platform_ops_settings  one row: Kevin's time zone, rhythm overrides, the
--                          calendar link's version (the link is an HMAC of it;
--                          rotating bumps it), KAI's latest note, which rhythm
--                          moments KAI has been prompted for, Kevin's hours,
--                          and the scorecard history the Scope keeper writes.
--
-- Service-role only: RLS on, no policies, browser roles revoked. ops_desk.py
-- is the one door, owner-only (require_owner) and the paired device (KAI).
begin;

create table if not exists public.platform_ops_tasks(
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  title text not null check (length(title) between 1 and 200),
  detail text not null default '' check (length(detail) <= 4000),
  lane text not null default 'try' check (lane in ('fix','build','try','ops')),
  lane_since timestamptz not null default now(),
  status text not null default 'open' check (status in ('open','doing','waiting','done','dropped')),
  kind text not null default 'task' check (kind in ('task','decision','switch','hire')),
  seat text not null default 'owner' check (seat in ('owner','product','code','support','money','growth','safety')),
  holder text not null default 'kevin' check (holder in ('kevin','kai','agent','hire')),
  source text not null default 'kevin' check (source in ('kevin','kai','plan','agent')),
  due_on date check (due_on between date '2024-01-01' and date '2100-01-01'),
  starts_at timestamptz,
  minutes int check (minutes between 5 and 600),
  link text not null default '' check (length(link) <= 500),
  -- The five answers at the door into Build (who asked, who owns it at night,
  -- what it costs a month, what switches it off, what waits because of it).
  door jsonb not null default '{}'::jsonb,
  done_at timestamptz,
  sort int not null default 0
);
create index if not exists platform_ops_tasks_active
  on public.platform_ops_tasks(lane, status) where status in ('open','doing','waiting');
create index if not exists platform_ops_tasks_due
  on public.platform_ops_tasks(due_on) where due_on is not null;

create table if not exists public.platform_ops_settings(
  id text primary key default 'owner' check (id = 'owner'),
  updated_at timestamptz not null default now(),
  tz text not null default 'America/New_York' check (length(tz) between 3 and 64),
  rhythm jsonb not null default '{}'::jsonb,
  calendar_version int not null default 1 check (calendar_version between 1 and 100000),
  kai_note jsonb,
  moments jsonb not null default '{}'::jsonb,
  hours jsonb not null default '{}'::jsonb,
  history jsonb not null default '{}'::jsonb
);

do $$ declare t text; begin
  foreach t in array array['platform_ops_tasks','platform_ops_settings'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
    execute format('grant all on public.%I to service_role', t);
  end loop;
end $$;

insert into public.platform_ops_settings(id) values ('owner') on conflict (id) do nothing;

-- The first lanes, from the team plan (artifact 1aZ4dpUZVvknD8V2bUCSwN) and
-- what was open on 2026-10-15. Fixed ids so a re-run adds nothing.
insert into public.platform_ops_tasks
  (id, title, detail, lane, status, kind, seat, holder, source, due_on, minutes, link, door, sort)
values
  ('0d5e0000-0000-4000-8000-000000000001',
   'Love City leaves Subsplash (M-1)',
   'The church moves its website, giving and member app onto Solutionist. Subsplash renews Dec 30, so notice is due by Nov 30. KAI coordinates the milestone.',
   'build', 'doing', 'task', 'product', 'kai', 'plan', date '2026-11-30', null,
   'docs/plans/SUBSPLASH_EXIT_PLAN_2026-10-14.md',
   '{"who_asked":"Love City Church, the first church customer","owner_seat":"Code & deploys (Kevin, until the second key)","monthly_cost":"Stripe fees on gifts; no new AI cost","off_switch":"Love City keeps Subsplash until the Dec 30 renewal","what_waits":"Trade editions wait in Try"}'::jsonb, 1),
  ('0d5e0000-0000-4000-8000-000000000002',
   'Ops desk: your week, the lanes, the calendar and KAI''s seat',
   'This system. Done when Mission Control shows Plan, the calendar is on your phone, and KAI writes its first morning note.',
   'build', 'doing', 'task', 'product', 'kevin', 'plan', date '2026-10-20', null, '',
   '{"who_asked":"Kevin, 2026-10-15","owner_seat":"Product (Kevin)","monthly_cost":"Nothing new: one daily pass, no AI","off_switch":"OPS_DESK=off","what_waits":"Staff access for Mission Control"}'::jsonb, 2),

  ('0d5e0000-0000-4000-8000-000000000010',
   'Put your week on your phone',
   'Mission Control → Build → Plan → Put it on my phone. iPhone: tap the webcal link, then Subscribe. Android: add the https link in Google Calendar on the web (Other calendars → From URL); it syncs to the phone.',
   'ops', 'open', 'task', 'owner', 'kevin', 'plan', date '2026-10-16', 5, '', '{}'::jsonb, 10),
  ('0d5e0000-0000-4000-8000-000000000011',
   'Set up break-glass access',
   'A password manager with emergency access for one trusted person. A backup card on every bill: Railway, Vercel, Supabase, GitHub, Twilio, Anthropic, Stripe (a lapsed bill has already stopped deploys and the PR check once). A one-page "if I can''t be reached" note that points to docs/RUNBOOK.md and docs/RESTORE.md.',
   'ops', 'open', 'task', 'owner', 'kevin', 'plan', date '2026-10-23', 120, '', '{}'::jsonb, 11),
  ('0d5e0000-0000-4000-8000-000000000012',
   'Start looking for the ops & support person',
   'At about 15 paying businesses, so they start around 25. Part-time, 15–20 hours a week. The job outline is in the team plan.',
   'ops', 'waiting', 'hire', 'support', 'kevin', 'plan', null, null,
   'https://claude.ai/artifact/1aZ4dpUZVvknD8V2bUCSwN', '{}'::jsonb, 12),
  ('0d5e0000-0000-4000-8000-000000000013',
   'Decide: does Chief''s advice get past the answer check? (PR #1090)',
   'Open since Sept 28. Merged #1331 and #1337 look like they already did this; confirm, then close it (or rebase it if something is still missing).',
   'ops', 'open', 'decision', 'product', 'kevin', 'plan', date '2026-10-23', 15,
   'https://github.com/parkerron1971-hash/kmj-intake-server/pull/1090', '{}'::jsonb, 13),
  ('0d5e0000-0000-4000-8000-000000000015',
   'Decide: publish the 27 news drafts, or close them',
   'Each is a green frontend PR adding one news post (#747 to #1162). None is published (the news page has one post). unfinished_work lists them every day as waiting on your yes. Pick the few worth publishing and close the rest.',
   'ops', 'open', 'decision', 'growth', 'kevin', 'plan', date '2026-10-23', 20,
   'https://github.com/parkerron1971-hash/solutionist-studio/pulls?q=is%3Aopen+is%3Apr+news', '{}'::jsonb, 15),
  ('0d5e0000-0000-4000-8000-000000000016',
   'Give the nightly What''s-New routine one standing branch again',
   'The rolling wn-sweep PR merged on Oct 1 (#1065). Since then the routine opens one PR a night with overlapping entries (#1166, #1178 and #1193 share three). Its prompt is yours to paste: point it at one standing branch it updates.',
   'ops', 'open', 'task', 'product', 'kevin', 'plan', date '2026-10-20', 10, '', '{}'::jsonb, 16),
  ('0d5e0000-0000-4000-8000-000000000014',
   'Remove finished working copies',
   'Backend worktrees whose branch is merged or closed, clean, and untouched for 3 days. Never a frontend worktree (node_modules junctions).',
   'ops', 'open', 'task', 'code', 'kai', 'plan', null, null, '', '{}'::jsonb, 14),

  ('0d5e0000-0000-4000-8000-000000000020',
   'Chief errors on 9–11% of turns (flagged Oct 2)',
   'KAI: read the latest Chief quality run and the turns that errored, find the biggest cause, and bring Kevin one fix. Quiet-week work if it isn''t urgent.',
   'fix', 'open', 'task', 'code', 'kai', 'plan', null, null, '', '{}'::jsonb, 20),
  ('0d5e0000-0000-4000-8000-000000000021',
   'Switch on or take out: the barber plans',
   'Solo / Booked / Boss are built and switched off (PLAN_<KEY>_OFFERED) since early October, and no screen shows them. Switch them on with the barber edition, or remove them.',
   'fix', 'open', 'switch', 'product', 'kevin', 'plan', date '2026-11-03', null, '', '{}'::jsonb, 21),

  ('0d5e0000-0000-4000-8000-000000000030',
   'Staff access for Mission Control, by seat',
   'Mission Control lets in one email address (require_owner in 76 backend files). Named staff accounts limited to their seat''s rooms, every action logged, nothing irreversible without Kevin. Needed before the first hire.',
   'try', 'open', 'task', 'code', 'kevin', 'plan', null, null, '', '{}'::jsonb, 30),
  ('0d5e0000-0000-4000-8000-000000000031',
   'Trade editions: /barbers and /coaches, with the trade carried through signup',
   'One domain, trade pages, the trade and plan carried through signup, the app showing audience plans. Barbers (solo) and coaches first.',
   'try', 'open', 'task', 'growth', 'kevin', 'plan', null, null, '', '{}'::jsonb, 31),
  ('0d5e0000-0000-4000-8000-000000000032',
   'Local CPU decision model (prototype)',
   'A prototype, open as PR #1406. It stays a Try until a Build slot opens and it passes the door.',
   'try', 'open', 'task', 'product', 'kevin', 'plan', null, null,
   'https://github.com/parkerron1971-hash/kmj-intake-server/pull/1406', '{}'::jsonb, 32),
  ('0d5e0000-0000-4000-8000-000000000033',
   'Acuity migration for solo calendars (draft)',
   'A draft, open as PR #1257 since Oct 4.',
   'try', 'open', 'task', 'product', 'kevin', 'plan', null, null,
   'https://github.com/parkerron1971-hash/kmj-intake-server/pull/1257', '{}'::jsonb, 33)
on conflict (id) do nothing;

commit;

-- Verify:
--   select lane, status, count(*) from public.platform_ops_tasks group by 1, 2 order by 1, 2;
--   select id, tz, calendar_version from public.platform_ops_settings;
--   select relrowsecurity from pg_class where relname in ('platform_ops_tasks','platform_ops_settings');
