-- The Sunday match, step 2 (2026-10-31): run AFTER the code is deployed.
--
-- With the code, a church's gift not given by card books into 1160 Gifts to
-- Deposit instead of straight to Cash, but ONLY where the Sunday match is on
-- (gl_engine._gift_waits + giving_deposits.ledger_gifts_wait), since only
-- there can a matched deposit clear 1160. GIVING_DEPOSITS is "owner" today:
-- the platform owner's churches. Gifts already in the ledger keep their old
-- entry until re-posted; this queues each of theirs once, and the ledger's own
-- queue reverses the old entry and posts the new. Income doesn't change, only
-- where the money sits on the balance sheet.
--
-- AT THE THURSDAY SWITCH-ON (GIVING_DEPOSITS=on): run it again without the
-- owner line, for every church. Switching it off later needs the same re-run.
insert into public.gl_sync_queue (business_id, source_table, source_id, op)
select i.business_id, 'invoices', i.id::text, 'update'
from public.invoices i
join public.businesses b on b.id = i.business_id
where i.is_gift = true
  and i.status = 'paid'
  and coalesce(lower(i.payment_method), '') not like '%stripe%'
  and coalesce(lower(i.payment_method), '') not like '%card%'
  -- The platform owner's churches (Love City's owner), while the switch is "owner".
  and b.owner_id = (select owner_id from public.businesses where id = '009e9a2c-3e81-4bfc-a92a-205a8806aa99');

-- Check it drained (a few minutes later): 0 rows left for invoices.
--   select count(*) from public.gl_sync_queue
--    where source_table = 'invoices' and processed_at is null;
