-- APPLY-2026_08_10_google_mailboxes.sql
--
-- Storage for connected Gmail / Google Workspace mailboxes.
--
-- WHY THIS IS ITS OWN TABLE, NOT businesses.settings
--   The repo's no-migration convention (settings.email_domain,
--   settings.giving) is right for CONFIG. A Google refresh token is not
--   config — it is a standing credential that reads a person's mail, and
--   it never expires until revoked. `businesses` rows are reachable by
--   seat members, so a token parked in settings would be handed to every
--   seat on the account. It lives here instead.
--
-- WHY RLS IS ON WITH NO POLICIES
--   Not an oversight. RLS enabled + zero policies = PostgREST returns
--   nothing for ANY anon or user JWT, while the service role bypasses RLS
--   entirely. That is exactly the reach we want: only server-initiated
--   code (sb_*_as_service) ever touches these rows. There is deliberately
--   no owner policy — the owner has no reason to read their own refresh
--   token through the API, and a policy that let them would also be the
--   policy an attacker with their JWT would use.
--
--   This differs from the new-table owner-RLS trap (seat policies alone
--   lock out the owner) because NOBODY is meant to read this over the
--   wire. The status a practitioner sees comes from /connect/google/status,
--   which reads this table service-side and returns only non-secret fields.

create extension if not exists pgcrypto;

create table if not exists public.google_mailboxes (
  id                uuid primary key default gen_random_uuid(),
  business_id       uuid not null references public.businesses(id) on delete cascade,

  -- Which mailbox. google_sub is the stable account id; the address can
  -- change (rename, alias promotion) and must never be the join key.
  google_email      text not null,
  google_sub        text,

  -- Credentials. refresh_token is the long-lived one; access_token is a
  -- cache so a sync run inside the hour doesn't re-mint needlessly.
  refresh_token     text not null,
  access_token      text,
  access_expires_at timestamptz,
  scopes            text,

  -- Lifecycle. status flips to 'revoked' when Google rejects the refresh
  -- token (user removed access from their Google account, password reset,
  -- admin policy change). last_error keeps the provider's own words so a
  -- support answer doesn't have to guess.
  status            text not null default 'connected',
  last_error        text,

  -- Who attached it, for the audit trail. Not an access-control field.
  connected_by      uuid,
  connected_at      timestamptz not null default now(),
  updated_at        timestamptz not null default now(),

  -- One row per mailbox per business. Reconnecting the same address
  -- updates in place rather than accumulating dead tokens.
  unique (business_id, google_email)
);

create index if not exists google_mailboxes_business_idx
  on public.google_mailboxes (business_id);

-- Lets the sync worker find rows needing a refresh without a full scan.
create index if not exists google_mailboxes_status_idx
  on public.google_mailboxes (status, access_expires_at);

alter table public.google_mailboxes enable row level security;

-- INTENTIONALLY NO POLICIES. See the header. Do not "fix" this by adding
-- an owner select policy — that would expose refresh_token to any holder
-- of the owner's JWT, which is the exact thing this table exists to avoid.

comment on table public.google_mailboxes is
  'Connected Gmail/Workspace mailboxes. RLS on with NO policies by design: service-role access only. Never add a user-facing SELECT policy — refresh_token is a credential.';
