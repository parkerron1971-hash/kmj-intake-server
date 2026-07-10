-- APPLY-2026-07-10-sms-missing-tables.sql
-- ═══════════════════════════════════════════════════════════════════
-- RUN THIS ONCE in the Supabase SQL Editor (whole file, one paste).
--
-- Root cause of "texting back and forth is not working": the SMS
-- routing tables (sms_opt_outs / sms_bindings / sms_keywords) were
-- applied, but sms_messages — every text sent or received — and
-- sms_consents were NEVER CREATED. Every message since launch hit a
-- missing table and was silently dropped (the keyword auto-reply
-- worked because it's generated in code, no storage needed).
--
-- Pairs with the sms/missing-tables-fix backend PR, which moves the
-- SMS modules to the service-role key: these tables ship with
-- owner-scoped RLS (message content must NOT be readable with the
-- public anon key), and the service role bypasses RLS for the
-- webhook-validated server writes.
-- ═══════════════════════════════════════════════════════════════════

-- ── 1. sms_messages — the conversation store ────────────────────────
create table if not exists public.sms_messages (
  id           uuid primary key default gen_random_uuid(),
  business_id  uuid references public.businesses(id),
  contact_id   uuid references public.contacts(id),
  phone_number text not null,            -- counterpart E.164
  message      text not null,
  direction    text not null,            -- 'inbound' | 'outbound'
  status       text not null default 'received',
                                         -- outbound: 'sent'|'delivered'|'failed'
                                         -- inbound:  'received'
  telnyx_id    text,                     -- provider message id (Telnyx OR Twilio SID)
  media_urls   text[],                   -- MMS attachments (inbound)
  read         boolean not null default false,
  created_at   timestamptz not null default now()
);

create index if not exists idx_sms_messages_business_created
  on public.sms_messages (business_id, created_at desc);
create index if not exists idx_sms_messages_contact
  on public.sms_messages (contact_id, created_at desc);
create index if not exists idx_sms_messages_unread
  on public.sms_messages (business_id) where direction = 'inbound' and read = false;
create index if not exists idx_sms_messages_provider
  on public.sms_messages (telnyx_id);

-- Owner-scoped RLS: the practitioner reads their business's texts and
-- can flip read-markers; the backend writes via service role (bypasses
-- RLS). One-way EXISTS to businesses — no policy cycle (the 42P17
-- lesson: only MUTUAL cross-references between two tables' policies
-- deadlock; businesses' policies don't reference sms_messages).
alter table public.sms_messages enable row level security;

drop policy if exists sms_messages_owner_select on public.sms_messages;
create policy sms_messages_owner_select on public.sms_messages
  for select to authenticated
  using (exists (
    select 1 from public.businesses b
    where b.id = sms_messages.business_id
      and b.owner_id = auth.uid()
  ));

drop policy if exists sms_messages_owner_update on public.sms_messages;
create policy sms_messages_owner_update on public.sms_messages
  for update to authenticated
  using (exists (
    select 1 from public.businesses b
    where b.id = sms_messages.business_id
      and b.owner_id = auth.uid()
  ))
  with check (exists (
    select 1 from public.businesses b
    where b.id = sms_messages.business_id
      and b.owner_id = auth.uid()
  ));

comment on table public.sms_messages is
  'Two-way SMS/MMS log (Twilio primary). Written server-side (service role); owner-scoped reads for the Dispatch Desk + contact Texts tab.';

-- ── 2. sms_consents — the A2P consent audit trail ───────────────────
-- (Original migration was committed but never run; created here WITH
-- the business_id column from the follow-up migration, and LOCKED
-- rather than permissive: both writers — the public opt-in endpoint
-- and the booking widget — go through the backend service role.)
create table if not exists public.sms_consents (
  id           bigint generated always as identity primary key,
  phone        text not null,
  name         text,
  source       text not null default 'web_form',   -- 'web_form' | 'booking'
  business_id  uuid references public.businesses(id),  -- NULL = platform-wide
  consented_at timestamptz not null default now(),
  ip           text,
  user_agent   text
);
create index if not exists sms_consents_phone_idx on public.sms_consents (phone);
-- In case an older run created it without the column:
alter table public.sms_consents add column if not exists business_id uuid references public.businesses(id);

alter table public.sms_consents enable row level security;
-- No anon/authenticated policies on purpose: service-role only.
drop policy if exists sms_consents_all on public.sms_consents;

comment on table public.sms_consents is
  'SMS opt-in audit trail (web form + booking widget). Proof of consent for carrier audits. Service-role access only.';

-- ── 3. Make PostgREST see the new tables immediately ────────────────
notify pgrst, 'reload schema';

-- ── Verify (should each return 0 rows, not an error) ────────────────
select count(*) as sms_messages_ok from public.sms_messages;
select count(*) as sms_consents_ok from public.sms_consents;
