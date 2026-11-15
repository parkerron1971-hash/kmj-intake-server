-- APPLY-2026-11-15-worship-screen-words.sql
--
-- ChurchSavvy's lower thirds (Kevin, 2026-11-15: "could we also have a way to
-- place lower thirds if we need to do lower thirds by itself"): a room screen
-- or an LED wall that shows a camera or a video can draw the words as lower
-- thirds instead of full slides, over the church's background or on a
-- see-through page a switcher or OBS lays over the camera.
-- worship_show.clean_words checks the shape ({"as": "slides" | "thirds" |
-- "see_through"}); this column only holds it. Empty means full slides, what
-- every screen drew before.
--
-- Additive and safe to run twice: a new column with a constant default,
-- nothing read or rewritten. The code reads screens without it until it's
-- here (worship_show_router._screens_call), so it can run before or after the
-- code deploys; until it runs, Setup doesn't offer the setting.

set lock_timeout = '5s';

alter table public.worship_screens
  add column if not exists words jsonb not null default '{}'::jsonb;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'worship_screens_words_shape') then
    alter table public.worship_screens
      add constraint worship_screens_words_shape
      check (jsonb_typeof(words) = 'object' and octet_length(words::text) <= 200);
  end if;
end $$;

-- Checks (read back after applying):
--   select column_name, data_type, column_default, is_nullable
--     from information_schema.columns where table_name = 'worship_screens' and column_name = 'words';
--   select conname from pg_constraint where conname = 'worship_screens_words_shape';
--   select count(*) from public.worship_screens where words <> '{}'::jsonb;   -- 0 right after
--
-- Rollback (the code keeps working without it: every screen draws full slides):
--   alter table public.worship_screens drop constraint if exists worship_screens_words_shape;
--   alter table public.worship_screens drop column if exists words;
