-- APPLY-2026_08_20_outcome_watches.sql
-- ─────────────────────────────────────────────────────────────────────
-- THE FOLLOW-THROUGH (2026-08-20, Kevin).
--
-- Chief acts and then goes quiet. It sends the invoice, mails the
-- purchase order, launches the campaign — and never once comes back to
-- say how any of it landed. Every loop it opens is closed by the
-- practitioner noticing, or not noticed at all.
--
-- A watch is one open loop: the thing Chief did, the outcome that would
-- close it, the date by which that outcome should have arrived, and —
-- once the sweep resolves it — what actually happened. Four kinds ship
-- with it, each resolving against a table that already carries the
-- answer:
--
--   invoice_paid      → invoices.paid_at
--   restock_arrived   → offerings.reorder_pending_at + inventory_qty
--   campaign_replies  → campaign_sends + events (campaigns_router owns
--                       the definition of a reply; we reuse it)
--   email_reply       → events(email_replied, sms_received) for the contact
--
-- WHY A ROW AND NOT A QUERY. "Which invoices are unpaid" needs no table
-- — it is one filter. What needs a table is the PROVENANCE: that on the
-- 14th the practitioner told Chief to send THIS one, and Chief is the
-- one holding the loop open. A dunning report says "3 invoices are
-- overdue". A watch says "you had me send Maria's on the 4th; she has
-- opened it twice and not paid." Only the second is Chief following
-- through on its own work, and the difference is entirely this row.
--
-- WHY OPENED AT THE HANDLER, NOT DERIVED FROM THE LEDGER. lead_response
-- derives rather than stamps, deliberately, because a missed call site
-- there reads as "nobody answered this lead" — a FALSE ALARM, and the
-- fastest way to teach someone to ignore a real one. Here the asymmetry
-- points the other way: a missed call site produces no watch, which is
-- silence. Silence is the safe failure, and the subject id the resolver
-- needs (which invoice, which offering) exists only in the handler —
-- audit_log.record_chief_turn passes no subject_refs on the chat path,
-- so there is nothing in the ledger to derive from.
--
-- RLS mirrors chief_missions exactly: owner ALL via businesses, seat
-- member read, seat writer write. The OWNER policy is the one that must
-- exist or every new signup is locked out of its own follow-ups.

create table if not exists public.chief_outcome_watches (
  id            uuid primary key default gen_random_uuid(),
  business_id   uuid not null references public.businesses(id) on delete cascade,

  -- Which loop this is. The engine's KINDS registry owns the resolver
  -- for each; a kind with no resolver is inert rather than an error.
  kind          text not null
                check (kind in ('invoice_paid','restock_arrived',
                                'campaign_replies','email_reply')),

  -- The Chief verb that opened it. Provenance, and the reason a watch
  -- can say "you had me send this" rather than "this is unpaid".
  verb          text not null default '',

  -- What the resolver re-reads. subject_id is text, not uuid: the
  -- offerings/invoices/campaigns ids are uuids today but a future kind
  -- may watch something keyed otherwise, and a cast is cheaper than a
  -- migration.
  subject_type  text not null default '',
  subject_id    text not null,

  -- What Chief did, in the practitioner's words, frozen at open time.
  -- Read back verbatim when the loop closes, so the report describes
  -- the action as it was understood THEN — an invoice later renumbered
  -- or a product later renamed must not rewrite history.
  label         text not null default '',

  opened_at     timestamptz not null default now(),
  -- When the outcome should have arrived. Past this with nothing
  -- landed is a miss. Set by the engine per kind, from the invoice's
  -- own due date where one exists rather than a flat window.
  due_at        timestamptz not null,

  status        text not null default 'open'
                check (status in ('open','landed','missed','void')),

  -- The measured facts at resolution — what the sweep actually read,
  -- so the notification quotes evidence instead of adjectives.
  outcome       jsonb not null default '{}'::jsonb,

  resolved_at   timestamptz,
  checked_at    timestamptz,
  -- When Chief spoke about this loop. Chief speaks ONCE per watch;
  -- without this a resolved-but-unannounced row re-announces on every
  -- pass, which is how a notification surface gets muted.
  announced_at  timestamptz,

  -- The audit_log row that recorded the opening action. Deliberately
  -- NOT a foreign key: audit_log is append-only behind triggers and a
  -- ledger write that failed must never take the follow-up down with
  -- it. Null means not recorded, never inferred.
  ledger_id     uuid,

  created_at    timestamptz not null default now()
);

-- The sweep's own query: open rows whose check is due, oldest first.
create index if not exists chief_outcome_watches_sweep_idx
  on public.chief_outcome_watches (status, due_at)
  where status = 'open';

-- The panel and the Chief verb: one business's loops, newest first.
create index if not exists chief_outcome_watches_business_idx
  on public.chief_outcome_watches (business_id, status, opened_at desc);

-- One open loop per subject. Two "send it" taps on the same invoice
-- must not become two follow-ups that both nag about the same money.
-- Partial so a NEW loop can legitimately open on the same subject once
-- the previous one has resolved (a re-sent invoice, a second PO).
create unique index if not exists chief_outcome_watches_one_open_idx
  on public.chief_outcome_watches (business_id, kind, subject_id)
  where status = 'open';

alter table public.chief_outcome_watches enable row level security;

drop policy if exists business_member_access on public.chief_outcome_watches;
create policy business_member_access on public.chief_outcome_watches
  for all
  using (business_id in (select id from public.businesses
                         where owner_id = auth.uid()))
  with check (business_id in (select id from public.businesses
                              where owner_id = auth.uid()));

drop policy if exists tenant_member_read on public.chief_outcome_watches;
create policy tenant_member_read on public.chief_outcome_watches
  for select
  using (is_business_member(business_id));

drop policy if exists tenant_writer_write on public.chief_outcome_watches;
create policy tenant_writer_write on public.chief_outcome_watches
  for all
  using (is_business_writer(business_id))
  with check (is_business_writer(business_id));

comment on table public.chief_outcome_watches is
  'THE FOLLOW-THROUGH — one row per loop Chief opened and has not yet '
  'closed. outcome_watch.py owns the resolvers and the sweep; every '
  'resolver re-reads the live business tables rather than trusting a '
  'cached figure, so a watch reports what is true now, not what was '
  'true when it opened.';
