-- APPLY-2026-11-27-needs-a-look.sql
--
-- "Needs a look": hold the automation, never the person (inbound_risk.py,
-- inbound_hold.py; docs/INBOUND_SAFETY.md). Kevin, 2026-11-27, on the Sofia
-- Marino / Julien Mercier connect cards: yes to building "Needs a look" now, a
-- held card is a contact with a "held" mark, the shared cross-church scam list
-- with the two-church rule and salted hashes only, the cheap second opinion on
-- mid-score cards (never prayer).
--
-- Four new server-only tables (RLS on, no policies, browser roles revoked).
-- Nothing in them is ever a message's words, a name or a church's name: hashes
-- are HMAC-SHA256 with a server secret (INBOUND_HASH_SALT, else one derived
-- from the service key), so an address can't be guessed back out.
--
-- inbound_checks       one row a checked submission (connect card, contact
--                      form, website prayer request)
--   id                 derived from the submission's receipt (a retry is one row)
--   receipt            the submission's receipt (its events / care row id)
--   contact_id         the contact it became (none for prayer)
--   door               connect_card | contact_form | prayer_request
--   verdict            clear | needs_look | bot;  score, reasons [{code, points, words}]
--   second_opinion     person | pitch | scam when the cheap model was asked
--   email_hash, domain_hash, phone_hash, text_hash   (salted; for repeats)
--   state              held (waiting for a look) | clear | watched (switch in
--                      watch mode) | flagged (a prayer request, delivered) |
--                      released (Real person) | closed (Not a guest / Scam)
--   pending            what a held card runs when released ({receipt, texts_ok})
-- inbound_decisions    one row a tap: real | not_a_guest | scam, who, via app or
--                      Chief, and `before` (what it changed, for undo)
-- inbound_senders      a church's own memory of a sender, by hash: real | scam
-- inbound_shared_list  hashes every church sees as "+3, other churches marked
--                      this sender a scam": two churches' Scam within 30 days,
--                      or the platform owner; expires 90 days after the last tap
--
-- New tables only: one transaction, safe to run twice, nothing dropped. Apply
-- any time: until then no card is ever held (a hold that couldn't be recorded
-- couldn't be released), and INBOUND_SAFETY stays off by default anyway.
--
-- CHECK BEFORE (expect: four nulls):
--   select to_regclass('public.inbound_checks'), to_regclass('public.inbound_decisions'),
--          to_regclass('public.inbound_senders'), to_regclass('public.inbound_shared_list');
begin;

set local lock_timeout = '5s';

create table if not exists public.inbound_checks(
  id uuid primary key,
  business_id uuid not null references public.businesses(id) on delete cascade,
  receipt text not null,
  contact_id uuid references public.contacts(id) on delete set null,
  door text not null default '',
  verdict text not null default 'clear',
  score integer not null default 0,
  reasons jsonb not null default '[]'::jsonb,
  second_opinion text,
  email_hash text,
  domain_hash text,
  phone_hash text,
  text_hash text,
  state text not null default 'clear',
  pending jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  decided_at timestamptz,
  constraint inbound_checks_verdict check (verdict in ('clear', 'needs_look', 'bot')),
  constraint inbound_checks_state check (state in ('held', 'clear', 'watched', 'flagged', 'released', 'closed')),
  constraint inbound_checks_door_len check (char_length(door) <= 40),
  constraint inbound_checks_receipt_len check (char_length(receipt) between 1 and 80),
  constraint inbound_checks_second check (second_opinion is null or second_opinion in ('person', 'pitch', 'scam')),
  constraint inbound_checks_reasons_list check (jsonb_typeof(reasons) = 'array'),
  constraint inbound_checks_pending_obj check (jsonb_typeof(pending) = 'object')
);
create index if not exists inbound_checks_waiting on public.inbound_checks (business_id, state, created_at desc);
create index if not exists inbound_checks_contact on public.inbound_checks (business_id, contact_id);
create index if not exists inbound_checks_email on public.inbound_checks (email_hash, created_at) where email_hash is not null;
create index if not exists inbound_checks_domain on public.inbound_checks (domain_hash, created_at) where domain_hash is not null;
create index if not exists inbound_checks_phone on public.inbound_checks (phone_hash, created_at) where phone_hash is not null;
create index if not exists inbound_checks_text on public.inbound_checks (text_hash, created_at) where text_hash is not null;

create table if not exists public.inbound_decisions(
  id uuid primary key,
  business_id uuid not null references public.businesses(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  verdict text not null,
  via text not null default 'app',
  by_user uuid,
  by_name text not null default '',
  before jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  undone_at timestamptz,
  undone_by uuid,
  constraint inbound_decisions_verdict check (verdict in ('real', 'not_a_guest', 'scam')),
  constraint inbound_decisions_via check (via in ('app', 'chief')),
  constraint inbound_decisions_name_len check (char_length(by_name) <= 120),
  constraint inbound_decisions_before_obj check (jsonb_typeof(before) = 'object')
);
create index if not exists inbound_decisions_contact on public.inbound_decisions (business_id, contact_id, created_at desc);

create table if not exists public.inbound_senders(
  business_id uuid not null references public.businesses(id) on delete cascade,
  kind text not null,
  hash text not null,
  verdict text not null,
  at timestamptz not null default now(),
  decision_id uuid,
  primary key (business_id, kind, hash),
  constraint inbound_senders_kind check (kind in ('email', 'domain', 'phone', 'text')),
  constraint inbound_senders_verdict check (verdict in ('real', 'scam')),
  constraint inbound_senders_hash_len check (char_length(hash) = 64)
);
-- The two-church rule reads every church's Scam for one hash.
create index if not exists inbound_senders_hash on public.inbound_senders (kind, hash, verdict, at);
create index if not exists inbound_senders_decision on public.inbound_senders (business_id, decision_id);

create table if not exists public.inbound_shared_list(
  kind text not null,
  hash text not null,
  source text not null default 'churches',
  churches integer not null default 0,
  added_at timestamptz not null default now(),
  last_tap_at timestamptz not null default now(),
  expires_at timestamptz not null,
  primary key (kind, hash),
  constraint inbound_shared_kind check (kind in ('email', 'domain', 'phone', 'text')),
  constraint inbound_shared_source check (source in ('churches', 'platform')),
  constraint inbound_shared_hash_len check (char_length(hash) = 64),
  constraint inbound_shared_churches check (churches >= 0)
);
create index if not exists inbound_shared_list_hash on public.inbound_shared_list (hash, expires_at);

alter table public.inbound_checks enable row level security;
alter table public.inbound_decisions enable row level security;
alter table public.inbound_senders enable row level security;
alter table public.inbound_shared_list enable row level security;
revoke all on public.inbound_checks, public.inbound_decisions, public.inbound_senders, public.inbound_shared_list
  from public, anon, authenticated;
grant select, insert, update, delete on public.inbound_checks, public.inbound_decisions, public.inbound_senders,
  public.inbound_shared_list to service_role;

notify pgrst, 'reload schema';
commit;

-- CHECK AFTER (expect four rows: rls true, 0 policies, browser_reads false, server_writes true):
--   select c.relname, c.relrowsecurity as rls,
--          (select count(*) from pg_policies p where p.tablename = c.relname) as policies,
--          has_table_privilege('authenticated', c.oid, 'select') as browser_reads,
--          has_table_privilege('service_role', c.oid, 'insert') as server_writes
--     from pg_class c
--    where c.relname in ('inbound_checks', 'inbound_decisions', 'inbound_senders', 'inbound_shared_list')
--    order by 1;
--
-- ROLLBACK: INBOUND_SAFETY=off on kmj-intake-server stops every check and hold at
-- once (people already held stay marked until someone taps; Members still shows
-- them). To remove what was stored as well:
--   drop table if exists public.inbound_shared_list, public.inbound_senders,
--     public.inbound_decisions, public.inbound_checks;
