-- APPLY-2026-11-20-gift-thankyou-events.sql
--
-- The old gift thank-you events move to the giving class.
--
-- Before #1940 (2026-11-18) the payment agent (payment_agent.py,
-- _scan_thank_yous) wrote every thank-you it drafted as one event,
-- events.event_type = 'payment_thankyou_created', with the person's contact
-- id and data.amount: for a business payment, and for a GIFT too. The events
-- policy reads event types by class (APPLY-2026-10-27-church-keys-gift-rows
-- .sql): '^giving' is who gave (ministry_giving_access), '^(invoice|payment)'
-- is the books (ministry_finance_guard). So an old gift's thank-you sits in
-- the books' class, where a login the owner gave giving at See WITHOUT "who
-- gave" would read a giver's name and amount the moment CHURCH_MONEY_TICKS is
-- switched on. Since #1940 a gift's thank-you is written
-- 'giving_thankyou_created'. This file retypes the old gift rows the same way.
--
-- WHICH ROWS: exactly the code's own test, nothing else.
--   payment_agent.py:  trigger = str(ev.get("event_type") or "")
--                      for_gift = trigger.startswith(("giving", "donation"))
--   and the trigger is kept on the event as data->>'trigger_event'. In SQL:
--     starts_with(data->>'trigger_event', 'giving')
--     or starts_with(data->>'trigger_event', 'donation')
--   (case-sensitive, as Python's startswith; no trigger is not a gift).
--
-- KEPT, NOT DELETED: each row keeps its id, business, contact, amount, source
-- and time. Two things change: event_type, and one key added to data,
-- "retyped_from": "payment_thankyou_created", so the rollback moves back
-- exactly these rows and never a thank-you the code wrote as a gift since.
--
-- Nothing reads either event type today (the agent reads only the payment
-- events that prompt a thank-you). Safe to run twice: a second run finds no
-- old gift row and changes nothing. One transaction; lock_timeout 5s,
-- statement_timeout 30s; rows only, no table, policy or function touched.
--
-- Production, read 2026-11-20: 0 rows of either event type
-- ('payment_thankyou_created' or 'giving_thankyou_created'). Applied today
-- it moves nothing; it is here so that any written before the switch goes
-- on are moved too. Run Check before first.
--
-- Check before (read-only; Q1 is how many rows this file moves):
--   select count(*) as old_gift_rows from public.events
--    where event_type = 'payment_thankyou_created'
--      and (starts_with(data->>'trigger_event', 'giving') or starts_with(data->>'trigger_event', 'donation'));
--   -- Q1: the rows this file retypes
--   select count(*) as payment_rows_left_alone from public.events
--    where event_type = 'payment_thankyou_created'
--      and not coalesce(starts_with(data->>'trigger_event', 'giving') or starts_with(data->>'trigger_event', 'donation'), false);
--   -- Q2: a business payment's thank-yous, which stay as they are
--   select count(*) as giving_rows_already from public.events where event_type = 'giving_thankyou_created';
--   -- Q3: gift thank-yous the code wrote since #1940 (after this file: Q3 + Q1)
--   select data->>'trigger_event' as prompted_by, count(*) from public.events
--    where event_type = 'payment_thankyou_created' group by 1 order by 1;
--   -- Q4: what prompted each old thank-you (giving_received, donation_received: moved; payment_received,
--   --     deposit_paid, balance_paid: stay)

begin;

set local lock_timeout = '5s';
set local statement_timeout = '30s';

update public.events
   set event_type = 'giving_thankyou_created',
       data = coalesce(data, '{}'::jsonb) || jsonb_build_object('retyped_from', 'payment_thankyou_created')
 where event_type = 'payment_thankyou_created'
   and (starts_with(data->>'trigger_event', 'giving') or starts_with(data->>'trigger_event', 'donation'));

commit;

-- Check after (read-only):
--   select count(*) as old_gift_rows_left from public.events
--    where event_type = 'payment_thankyou_created'
--      and (starts_with(data->>'trigger_event', 'giving') or starts_with(data->>'trigger_event', 'donation'));
--   -- 0
--   select count(*) as moved from public.events
--    where event_type = 'giving_thankyou_created' and data->>'retyped_from' = 'payment_thankyou_created';
--   -- Q1 from before
--   select count(*) as payment_rows_left_alone from public.events
--    where event_type = 'payment_thankyou_created'
--      and not coalesce(starts_with(data->>'trigger_event', 'giving') or starts_with(data->>'trigger_event', 'donation'), false);
--   -- Q2 from before, unchanged
--
-- Rollback: supabase/ROLLBACK-2026-11-20-gift-thankyou-events.sql (moves back exactly the rows marked here).
