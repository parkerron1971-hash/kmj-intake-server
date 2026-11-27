-- supabase/APPLY-2026-11-27-sunday-hub.sql
--
-- Church Savvy: one Sunday hub (mission M-7; Kevin's decisions church-office-1,
-- 2026-11-27; kai/reviews/church-savvy-sunday-structure.md). The plan's ONE
-- migration: six nullable / defaulted columns on five live tables, all of
-- them written only by the server (service role; RLS on, browser roles
-- already revoked on each). Nothing reads them until SUNDAY_HUB is on, and the
-- switch goes on only after this is applied.
--
--   worship_services.live_ok_until   a Sunday the pastor opened for live
--   worship_services.live_ok_by      changes (media & tech may change the plan
--                                    until this moment, on that Sunday only)
--   serve_teams.open_to_ops          ministry operations may fill this team's
--                                    spots (worship and production: off until
--                                    their leader or the pastor opens it)
--   worship_settings.service_word    "Sunday" or "service" (Next service), the
--                                    church's own choice; null = worked out
--   worship_settings.team_areas      whose a plan item is by its kind
--                                    ({"song": "<group id>", ...}); null = the
--                                    defaults by team name
--   church_posts.screen_announcement_id
--                                    the screens announcement a News post was
--                                    posted with ("Also post to News" / "Also
--                                    show on the screens")
--
-- Additive only: no table, column, row or constraint dropped or rewritten.
-- One transaction, lock_timeout 5s, safe to run twice, ends with NOTIFY pgrst.

begin;
set local lock_timeout = '5s';

alter table public.worship_services add column if not exists live_ok_until timestamptz;
alter table public.worship_services add column if not exists live_ok_by uuid references auth.users(id) on delete set null;

alter table public.serve_teams add column if not exists open_to_ops boolean not null default false;

alter table public.worship_settings add column if not exists service_word text;
alter table public.worship_settings add column if not exists team_areas jsonb;
do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'worship_settings_service_word') then
    alter table public.worship_settings add constraint worship_settings_service_word
      check (service_word is null or service_word in ('Sunday', 'service'));
  end if;
  if not exists (select 1 from pg_constraint where conname = 'worship_settings_team_areas') then
    alter table public.worship_settings add constraint worship_settings_team_areas
      check (team_areas is null or (jsonb_typeof(team_areas) = 'object' and octet_length(team_areas::text) <= 4000));
  end if;
end $$;

alter table public.church_posts add column if not exists screen_announcement_id uuid
  references public.worship_announcements(id) on delete set null;
create index if not exists church_posts_screen_announcement
  on public.church_posts (screen_announcement_id) where screen_announcement_id is not null;

commit;

notify pgrst, 'reload schema';

-- ─── CHECK AFTER ─────────────────────────────────────────────────────
-- Six rows, each with its type and default:
-- select table_name, column_name, data_type, column_default, is_nullable
--   from information_schema.columns
--  where table_schema = 'public'
--    and (table_name, column_name) in (('worship_services', 'live_ok_until'), ('worship_services', 'live_ok_by'),
--         ('serve_teams', 'open_to_ops'), ('worship_settings', 'service_word'), ('worship_settings', 'team_areas'),
--         ('church_posts', 'screen_announcement_id'))
--  order by 1, 2;
-- Every team starts closed to ministry operations (0):
-- select count(*) from public.serve_teams where open_to_ops;

-- ─── ROLLBACK (only with SUNDAY_HUB=off on both services) ───────────
-- begin;
-- drop index if exists public.church_posts_screen_announcement;
-- alter table public.church_posts drop column if exists screen_announcement_id;
-- alter table public.worship_settings drop constraint if exists worship_settings_team_areas;
-- alter table public.worship_settings drop constraint if exists worship_settings_service_word;
-- alter table public.worship_settings drop column if exists team_areas;
-- alter table public.worship_settings drop column if exists service_word;
-- alter table public.serve_teams drop column if exists open_to_ops;
-- alter table public.worship_services drop column if exists live_ok_by;
-- alter table public.worship_services drop column if exists live_ok_until;
-- commit;
-- notify pgrst, 'reload schema';
