-- APPLY-2026-11-13-church-mail.sql
--
-- Church email in the system (church_mail.py, chief_church_mail.py). Kevin,
-- 2026-11-11: "I want to make sure chief knows how to get people there email
-- with the @domain name for each church"; "prayer would go to the leader of
-- prayer so assign that to that role"; 2026-11-13: "can we build what is
-- needed so this can go live right away?" Plan: artifact WYc8oLMAerrqDkCBa5Dq2t.
--
-- Two server-only tables:
--
--   church_mailboxes  one address at the church's own domain, and who it
--                     reaches. Who is never copied onto the box: it names a
--                     login, a person, a role, the prayer list, the office or
--                     an outside address, and the server looks the holder up
--                     each time mail arrives. Take someone off the team or
--                     out of a role and their mail goes to the office box
--                     that moment, with nothing to clean up. One live box an
--                     address (a box turned off keeps its mail and frees the
--                     address); one catch-all a church.
--   church_mail       each message that came in to a box, and where it went:
--                     copied to the holder's own email, put on the prayer
--                     list, held (failed its sender checks, or looped), or
--                     failed to copy. Kept when the box is turned off, so
--                     the mail history stays with the address.
--
-- New tables only: one transaction, safe to run twice, nothing dropped. Apply
-- before the code that reads it: until then no church has a box, so mail is
-- sorted exactly as it is today.
begin;

set local lock_timeout = '5s';

create table if not exists public.church_mailboxes(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  domain text not null check (domain ~ '^[a-z0-9.-]+\.[a-z]{2,}$'),
  local text not null check (local ~ '^[a-z0-9]([a-z0-9._-]{0,38}[a-z0-9])?$'),
  kind text not null check (kind in ('person', 'role', 'prayer', 'office', 'forward')),
  user_id uuid references auth.users(id) on delete set null,
  contact_id uuid references public.contacts(id) on delete set null,
  role_key text check (role_key is null or char_length(role_key) <= 80),
  share_with uuid[] not null default '{}',
  forward_to text check (forward_to is null or (char_length(forward_to) <= 254
                         and forward_to ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$')),
  catch_all boolean not null default false,
  status text not null default 'active' check (status in ('active', 'off')),
  told_at timestamptz,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint church_mailboxes_kind_target check (
    (kind = 'person' and (user_id is not null or contact_id is not null) or kind <> 'person')
    and (kind <> 'role' or role_key is not null)
    and (kind <> 'forward' or forward_to is not null)
    and (not catch_all or kind = 'office'))
);

create unique index if not exists church_mailboxes_address_live
  on public.church_mailboxes (domain, local) where status = 'active';
create unique index if not exists church_mailboxes_one_catch_all
  on public.church_mailboxes (business_id) where status = 'active' and catch_all;
create index if not exists church_mailboxes_church
  on public.church_mailboxes (business_id, status);

-- A box's person is the box's own church's, whatever the caller passes.
create or replace function public.church_mailboxes_same_business() returns trigger
language plpgsql set search_path = public as $$
begin
  if new.contact_id is not null
     and not exists (select 1 from public.contacts c
                     where c.id = new.contact_id and c.business_id = new.business_id) then
    raise exception 'That person is not in this church';
  end if;
  return new;
end $$;

drop trigger if exists church_mailboxes_same_business on public.church_mailboxes;
create trigger church_mailboxes_same_business
  before insert or update of contact_id, business_id on public.church_mailboxes
  for each row execute function public.church_mailboxes_same_business();

revoke all on function public.church_mailboxes_same_business() from public, anon, authenticated;

create table if not exists public.church_mail(
  id uuid primary key default gen_random_uuid(),
  business_id uuid not null references public.businesses(id) on delete cascade,
  mailbox_id uuid references public.church_mailboxes(id) on delete set null,
  to_address text not null check (char_length(to_address) <= 254),
  from_email text not null check (char_length(from_email) <= 254),
  from_name text check (from_name is null or char_length(from_name) <= 200),
  subject text check (subject is null or char_length(subject) <= 1000),
  body_text text check (body_text is null or char_length(body_text) <= 100000),
  body_html text check (body_html is null or char_length(body_html) <= 1000000),
  attachments jsonb not null default '[]'::jsonb,
  email_id text not null check (char_length(email_id) between 1 and 200),
  message_id text check (message_id is null or char_length(message_id) <= 1000),
  outcome text not null check (outcome in ('copied', 'prayer', 'held', 'failed', 'stored')),
  why text check (why is null or char_length(why) <= 300),
  delivered jsonb not null default '[]'::jsonb,
  received_at timestamptz not null default now()
);

-- One row a message an address: a webhook Resend sends twice writes once.
create unique index if not exists church_mail_once
  on public.church_mail (email_id, to_address);
create index if not exists church_mail_church
  on public.church_mail (business_id, received_at desc);
create index if not exists church_mail_box
  on public.church_mail (mailbox_id, received_at desc);

alter table public.church_mailboxes enable row level security;
revoke all on public.church_mailboxes from anon, authenticated;
grant all on public.church_mailboxes to service_role;
alter table public.church_mail enable row level security;
revoke all on public.church_mail from anon, authenticated;
grant all on public.church_mail to service_role;

comment on table public.church_mailboxes is
  'Church email addresses at the church''s own domain (church_mail.py). Who a box reaches is looked up live from the login, the person''s roles, the role or the office each time mail arrives, never copied onto it. Server-only (RLS on, no policies).';
comment on column public.church_mailboxes.share_with is
  'An office box: the logins that get its mail. Empty means the owner. A login taken off the team stops getting it at once.';
comment on column public.church_mailboxes.told_at is
  'When the person got the welcome note naming their address (sent once, after mail to the domain reaches the system).';
comment on column public.church_mailboxes.catch_all is
  'The office box that gets mail for any address the church has no box for, and for any box whose person has left.';
comment on table public.church_mail is
  'Mail that came in to a church box and where it went (church_mail.py). Kept when a box is turned off. Never shown to Chief. Server-only (RLS on, no policies).';

commit;

-- Check:
--   select c.relname, c.relrowsecurity,
--          (select count(*) from pg_policies p where p.schemaname = 'public' and p.tablename = c.relname) as policies,
--          has_table_privilege('authenticated', c.oid, 'select') as browser_reads,
--          has_table_privilege('anon', c.oid, 'select') as anon_reads
--     from pg_class c where c.oid in ('public.church_mailboxes'::regclass, 'public.church_mail'::regclass);
--   -- both: true, 0, false, false
--   select count(*) from pg_indexes where schemaname = 'public' and indexname in
--     ('church_mailboxes_address_live', 'church_mailboxes_one_catch_all', 'church_mailboxes_church',
--      'church_mail_once', 'church_mail_church', 'church_mail_box');
--   -- 6
--   select count(*) from pg_trigger where tgname = 'church_mailboxes_same_business' and not tgisinternal;
--   -- 1
--
-- Rollback (loses every church address and the mail kept for them):
--   drop table if exists public.church_mail;
--   drop table if exists public.church_mailboxes;
--   drop function if exists public.church_mailboxes_same_business();
