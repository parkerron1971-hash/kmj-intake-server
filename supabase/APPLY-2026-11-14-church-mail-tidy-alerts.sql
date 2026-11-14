-- APPLY-2026-11-14-church-mail-tidy-alerts.sql
--
-- Church mail: archive and delete, and an alert when new mail comes
-- (church_mail_room.py, church_mail_alerts.py). Kevin, 2026-11-14, on the
-- mock (artifact 1fGHqCVMe9fxwceAbjbaJZ): "I love the design. lets build it".
--
--   church_mail          + archived_by   the logins that archived it (archive
--                                         is per person, like read_by)
--                        + deleted_at,   in the box's Trash since then, by whom
--                          deleted_by,   (delete is for everyone on the box;
--                          deleted_name  gone for good 30 days later)
--                        + alert_at      when its new-mail alert is due (null:
--                                         never, as for everything before this)
--                        + alerted_at    when the alert went out
--   church_mail_people   + alerts        'all' | 'mine' | 'off' (null = all)
--                        + alert_push    phone alerts (null = on)
--                        + alert_bell    the bell (null = on)
--
-- Additive only: nullable columns and one with a constant default (no table
-- rewrite), two partial indexes, one transaction, safe to run twice. Apply
-- BEFORE the code that reads them: the room selects these columns.
begin;

set local lock_timeout = '5s';

alter table public.church_mail
  add column if not exists archived_by uuid[] not null default '{}',
  add column if not exists deleted_at timestamptz,
  add column if not exists deleted_by uuid,
  add column if not exists deleted_name text,
  add column if not exists alert_at timestamptz,
  add column if not exists alerted_at timestamptz;

alter table public.church_mail drop constraint if exists church_mail_deleted_name_check;
alter table public.church_mail add constraint church_mail_deleted_name_check
  check (deleted_name is null or char_length(deleted_name) <= 200);

-- The alert sweep reads only what's due; the trash sweep only what's deleted.
create index if not exists church_mail_alert_due on public.church_mail (alert_at)
  where alerted_at is null and alert_at is not null;
create index if not exists church_mail_trash on public.church_mail (business_id, deleted_at)
  where deleted_at is not null;

alter table public.church_mail_people
  add column if not exists alerts text,
  add column if not exists alert_push boolean,
  add column if not exists alert_bell boolean;

alter table public.church_mail_people drop constraint if exists church_mail_people_alerts_check;
alter table public.church_mail_people add constraint church_mail_people_alerts_check
  check (alerts is null or alerts in ('all', 'mine', 'off'));

comment on column public.church_mail.archived_by is
  'The logins that archived it in the Email room (per person; out of their list, still in their Archive and search).';
comment on column public.church_mail.deleted_at is
  'In the box''s Trash since then (deleted for everyone on the box); church_mail_alerts deletes it for good after 30 days.';
comment on column public.church_mail.alert_at is
  'When its new-mail alert is due (church_mail_alerts); null = never. Quiet hours hold it until morning.';
comment on column public.church_mail_people.alerts is
  'New church mail alerts: all (own box and shared boxes), mine (own box only), off. Null = all.';

commit;

-- Check:
--   select column_name, data_type from information_schema.columns where table_schema = 'public'
--     and ((table_name = 'church_mail' and column_name in ('archived_by', 'deleted_at', 'deleted_by', 'deleted_name', 'alert_at', 'alerted_at'))
--       or (table_name = 'church_mail_people' and column_name in ('alerts', 'alert_push', 'alert_bell')))
--     order by table_name, column_name;
--   -- 9 rows
--   select indexname from pg_indexes where tablename = 'church_mail' and indexname in ('church_mail_alert_due', 'church_mail_trash');
--   -- 2 rows
--
-- Rollback (loses who archived what, the Trash, and everyone's alert settings):
--   drop index if exists public.church_mail_alert_due;
--   drop index if exists public.church_mail_trash;
--   alter table public.church_mail drop constraint if exists church_mail_deleted_name_check;
--   alter table public.church_mail drop column if exists archived_by, drop column if exists deleted_at,
--     drop column if exists deleted_by, drop column if exists deleted_name, drop column if exists alert_at,
--     drop column if exists alerted_at;
--   alter table public.church_mail_people drop constraint if exists church_mail_people_alerts_check;
--   alter table public.church_mail_people drop column if exists alerts, drop column if exists alert_push,
--     drop column if exists alert_bell;
