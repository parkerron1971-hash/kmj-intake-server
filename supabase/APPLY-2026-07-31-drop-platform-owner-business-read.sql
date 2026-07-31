-- APPLY-2026-07-31-drop-platform-owner-business-read.sql
-- Kevin's ruling 2026-07-31: client businesses must NOT appear in his
-- everyday account switcher — platform-wide visibility belongs to
-- Mission Control surfaces only (tickets, subscriptions, analytics).
--
-- The businesses_platform_owner_read policy (support-tickets migration)
-- existed for ONE reason: the Mission Control ticket panel embedded
-- businesses(name), which resolves through businesses RLS. Side effect:
-- the business switcher (an unfiltered RLS-scoped list) showed the
-- platform owner EVERY business on the platform — MaCnificent Hair Co
-- surfaced in his list looking like his own account.
--
-- Fix: denormalize the name onto the ticket (stamped at filing time by
-- the app; backfilled here), drop the businesses policy outright. The
-- is_platform_owner() helper stays — tickets_owner_all and the
-- product_events read policy still use it. NOTE: do NOT replace this
-- with an inline EXISTS over support_tickets on the businesses policy —
-- the ticket policies already subquery businesses, and A↔B inline RLS
-- is the 42P17 recursion class.

alter table public.support_tickets
  add column if not exists business_name text;

update public.support_tickets t
   set business_name = b.name
  from public.businesses b
 where b.id = t.business_id
   and t.business_name is null;

drop policy if exists businesses_platform_owner_read on public.businesses;
