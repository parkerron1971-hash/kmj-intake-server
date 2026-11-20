-- ROLLBACK-2026-11-20-gift-thankyou-events.sql
--
-- Undoes supabase/APPLY-2026-11-20-gift-thankyou-events.sql: the rows that
-- file moved (marked data->>'retyped_from' = 'payment_thankyou_created') go
-- back to 'payment_thankyou_created' and lose the mark. A gift thank-you the
-- code wrote as 'giving_thankyou_created' itself (since #1940) has no mark
-- and stays where it is. Nothing is deleted.
--
-- Running this puts old givers' names and amounts back in the books' class:
-- with CHURCH_MONEY_TICKS on, a login that only Sees the books reads them
-- again. Run it only with the switch off, or to apply the file again.
--
-- Safe to run twice. One transaction; lock_timeout 5s, statement_timeout 30s.

begin;

set local lock_timeout = '5s';
set local statement_timeout = '30s';

update public.events
   set event_type = 'payment_thankyou_created',
       data = data - 'retyped_from'
 where event_type = 'giving_thankyou_created'
   and data->>'retyped_from' = 'payment_thankyou_created';

commit;

-- Check after (read-only):
--   select count(*) from public.events
--    where event_type = 'giving_thankyou_created' and data->>'retyped_from' = 'payment_thankyou_created';
--   -- 0
