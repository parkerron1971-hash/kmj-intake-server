-- APPLY-2026-10-26-worship-lobby.sql
--
-- ChurchSavvy's lobby TV on its own (round 5, canvas board 26): each lobby
-- screen keeps whether it follows the booth or runs its own week, when it
-- shows what (the welcome loop, this week, a countdown to a night, or off),
-- and what it shows. worship_show.clean_lobby checks the shape; this column
-- only holds it. Empty means "follows the booth", what every lobby screen
-- did before.
--
-- Additive and safe to run twice: a new column with a default, nothing
-- read or rewritten. Apply BEFORE the code that selects it deploys.

alter table public.worship_screens
  add column if not exists lobby jsonb not null default '{}'::jsonb;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'worship_screens_lobby_shape') then
    alter table public.worship_screens
      add constraint worship_screens_lobby_shape
      check (jsonb_typeof(lobby) = 'object' and octet_length(lobby::text) <= 4000);
  end if;
end $$;
