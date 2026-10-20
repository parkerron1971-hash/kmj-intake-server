-- APPLY-2026-10-20-worship-stage.sql
--
-- ChurchSavvy's confidence screen (canvas board 33): each stage screen keeps
-- how it looks to the people on stage: its layout (the band's view, the
-- pastor's, notes, a countdown, or auto), what it shows, and how big.
-- worship_show.clean_stage checks the shape; this column only holds it.
--
-- Additive and safe to run twice: a new column with a default, nothing
-- read or rewritten. Apply BEFORE the code that selects it deploys.

alter table public.worship_screens
  add column if not exists stage jsonb not null default '{}'::jsonb;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'worship_screens_stage_shape') then
    alter table public.worship_screens
      add constraint worship_screens_stage_shape
      check (jsonb_typeof(stage) = 'object' and octet_length(stage::text) <= 1000);
  end if;
end $$;
