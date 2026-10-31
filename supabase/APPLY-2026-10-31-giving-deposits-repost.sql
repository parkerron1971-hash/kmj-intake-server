-- The Sunday match, step 2 (2026-10-31): run AFTER the code is deployed.
--
-- With the code, a church's gift not given by card books into 1160 Gifts to
-- Deposit instead of straight to Cash (gl_engine._gift_waits). Gifts already
-- in the ledger keep their old entry until they are re-posted; this queues
-- each of them once, and the ledger's own queue (process_queue) reverses the
-- old entry and posts the new. Nothing about a gift changes, only where its
-- money sits on the balance sheet: income is the same. Run before the code
-- and the old code re-posts the same entry, so run it after.
insert into public.gl_sync_queue (business_id, source_table, source_id, op)
select i.business_id, 'invoices', i.id::text, 'update'
from public.invoices i
where i.is_gift = true
  and i.status = 'paid'
  and coalesce(lower(i.payment_method), '') not like '%stripe%'
  and coalesce(lower(i.payment_method), '') not like '%card%';

-- Check it drained (a few minutes later): 0 rows left for invoices.
--   select count(*) from public.gl_sync_queue
--    where source_table = 'invoices' and processed_at is null;
