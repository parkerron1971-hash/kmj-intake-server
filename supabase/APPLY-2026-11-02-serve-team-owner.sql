-- Sunday's teams belong to ChurchSavvy or to Volunteers (sunday_planning.py;
-- Kevin 2026-11-02: "churchsavvy is shapretta because that has to do with
-- the service projection and order of service for production team and
-- partnering with worship team. volunteers and roles laquesha is doing is her
-- assignment", then "yes churchsavvy for worship team, announcements to
-- shapretta. go"). One schedule, two doors:
--
--   serve_teams.owner   'churchsavvy': the worship and production teams (the
--                       Media & Communications lane, with the worship pastor);
--                       'volunteers': every other team (greeters, ushers,
--                       kids, parking, hospitality, outreach: the Sunday &
--                       Serving lane). In a church each office login changes
--                       only its own teams; everyone who opens Planning still
--                       reads every team, so the whole Sunday shows.
--
-- The teams already there are sorted once, when the column is added: a team
-- whose name has worship, praise, band, choir, music, singers, production,
-- sound, audio, camera, stream, media, tech, booth, lights, slides or
-- projection in it is ChurchSavvy's, any other is Volunteers'. It is the rule
-- a new team nobody gave an owner follows (sunday_planning.CHURCHSAVVY_WORDS).
-- Running the file again changes nothing, so it never undoes a team a church
-- moved by hand. Love City has no Sunday teams yet (2026-11-02).
--
-- Additive and safe to run twice. Server-only like the rest of serve_*: the
-- table's RLS and revokes (APPLY-2026-10-23-sunday-planning.sql) cover the
-- new column. Before it's applied every team reads as Volunteers' and a new
-- team is saved without it.
-- Rollback: alter table public.serve_teams drop column if exists owner;
begin;

do $$
begin
  if not exists (select 1 from information_schema.columns
                  where table_schema = 'public' and table_name = 'serve_teams' and column_name = 'owner') then
    alter table public.serve_teams
      add column owner text not null default 'volunteers'
        constraint serve_teams_owner_known check (owner in ('churchsavvy', 'volunteers'));
    update public.serve_teams t
       set owner = 'churchsavvy'
      from public.groups g
     where g.id = t.group_id
       and g.name ~* '(worship|praise|band|choir|music|singers|production|sound|audio|camera|stream|media|tech|booth|lights|slides|projection)';
  end if;
end $$;

commit;
