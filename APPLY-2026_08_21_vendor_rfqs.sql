-- APPLY-2026_08_21_vendor_rfqs.sql
-- ─────────────────────────────────────────────────────────────────────
-- THE SOURCING DESK, STAGE 2 — the bridge. "Getting connected" is the
-- part nobody else does.
--
-- Finding a manufacturer is the easy half. The hard half is writing the
-- email that gets answered, and that is where Chief has an unfair
-- advantage it did not have to build: it already knows what this
-- business sells, at what price, at what volume, under what name. So the
-- request for quote writes itself with REAL numbers instead of the
-- "please send info" that manufacturers ignore.
--
-- WHY A TABLE
--   An RFQ is a loop that was opened. Something has to remember it was
--   opened so that (a) the practitioner can see who they asked and when,
--   (b) the vendor's status can move candidate → contacted without
--   guessing, and (c) the follow-through sweep has something to notice
--   going quiet. A sent email with no row is a loop nobody can close.
--
-- WHAT IS STORED IS WHAT WAS SENT
--   subject and body are written at send time from the same composer
--   that produced the preview, so the record is the email, not a
--   reconstruction of it. If the two could drift, the record would be
--   evidence of something that never happened.
--
-- THE FAN-OUT IS ONE ROW PER VENDOR
--   Asking five vendors is five rows, not one row with five addresses.
--   Replies arrive per vendor, statuses move per vendor, and quotes come
--   back per vendor. It also means the per-vendor record exists before
--   anyone is tempted to treat this as a mailing list.
--
-- RLS mirrors suppliers exactly. The OWNER policy is the one that must
-- exist or every new signup is locked out of their own table.
--
-- Verified against production inside a DO block that ended in `raise
-- exception`, so every fixture rolled back (leftover check after: 0 rfqs,
-- 0 test vendors):
--
--   sent_in_window=2 all_rows=4   the 24h send-cap window excluded both a
--                                 30-hour-old send AND the draft — drafts
--                                 must never count against a send ceiling
--   repeat_window=3               the 7-day repeat guard correctly still
--                                 sees the 30-hour-old one
--   bogus_status_rejected=ok      the status vocabulary is closed
--   orphans_after_vendor_delete=0 deleting a vendor takes its requests
--                                 with it, so an RFQ can never point at a
--                                 vendor that no longer exists
--   owner_sees=1 stranger_sees=0  the OWNER policy works; isolation holds
--
-- Status: APPLIED to production 2026-08-21 via the Management API.

create table if not exists public.vendor_rfqs (
  id            uuid primary key default gen_random_uuid(),
  business_id   uuid not null references public.businesses(id) on delete cascade,
  supplier_id   uuid not null references public.suppliers(id) on delete cascade,

  -- What this was about. offering_id is nullable on purpose: plenty of
  -- RFQs are for something the business does not stock yet, which is the
  -- whole reason they are looking for a maker.
  offering_id   uuid references public.offerings(id) on delete set null,
  need          text not null,
  qty           int,

  -- Exactly what left the building.
  subject       text not null,
  body          text not null,
  to_email      text not null,

  -- draft → sent → replied → closed. 'draft' rows exist so a
  -- practitioner can prepare a batch and send it when they are ready;
  -- nothing is sent without an explicit send.
  status        text not null default 'draft'
                check (status in ('draft','sent','replied','closed')),
  sent_at       timestamptz,
  replied_at    timestamptz,

  created_by    uuid,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index if not exists vendor_rfqs_business_status_idx
  on public.vendor_rfqs (business_id, status, created_at desc);
create index if not exists vendor_rfqs_supplier_idx
  on public.vendor_rfqs (supplier_id);

alter table public.vendor_rfqs enable row level security;

drop policy if exists business_member_access on public.vendor_rfqs;
create policy business_member_access on public.vendor_rfqs
  for all
  using (business_id in (select id from public.businesses
                         where owner_id = auth.uid()))
  with check (business_id in (select id from public.businesses
                              where owner_id = auth.uid()));

drop policy if exists tenant_member_read on public.vendor_rfqs;
create policy tenant_member_read on public.vendor_rfqs
  for select
  using (is_business_member(business_id));

drop policy if exists tenant_writer_write on public.vendor_rfqs;
create policy tenant_writer_write on public.vendor_rfqs
  for all
  using (is_business_writer(business_id))
  with check (is_business_writer(business_id));

comment on table public.vendor_rfqs is
  'THE SOURCING DESK stage 2: one row per vendor asked for a quote. '
  'subject/body are what was actually sent, written by the same composer '
  'that produced the preview. One row per vendor so replies, statuses '
  'and quotes stay per-vendor.';
