-- A Media part on a church's ChurchSavvy team (worship_team.py; Kevin
-- 2026-10-23, "Church Areas and Keys": a Media team gets the media part
-- already set up). Media runs the livestream, works on video clips and keeps
-- sermons, through those routes' own checks; it never changes the plan or
-- runs the screens. This only widens the parts a row may hold: planner,
-- worship, booth, media, admin. Every existing row already fits.
-- Idempotent.
begin;

alter table public.worship_team drop constraint if exists worship_team_roles_check;
alter table public.worship_team add constraint worship_team_roles_check
  check (cardinality(roles) between 1 and 5
         and roles <@ array['planner', 'worship', 'booth', 'media', 'admin']::text[]);

commit;
