-- The office's header says each login's lane ("Minnie · Treasurer"), Kevin
-- 2026-10-28: "yes build the church-branded office door". A lane was only
-- ever kept as the areas it opens, and an admin's areas are the whole
-- church, so a Treasurer read the same as any admin.
--
--   business_users.lane   the lane key (church_areas.LANES): set by the
--                         invite that carries a lane, and by Logins & areas
--
-- Additive only. Apply before the code: an invite with a lane writes it.
-- Rollback: drop the column.

alter table public.business_users add column if not exists lane text;
