-- APPLY-2026_08_20_stock_moves.sql
-- Closing the two stock gaps this arc left open.
--
-- 1) THE OVERSELL RACE
--    mark_order_paid decremented read-then-write: two simultaneous paid
--    orders on the last unit could both read qty=1 and both write qty=0,
--    selling one unit twice. decrement_offering_stock() takes a row lock
--    (SELECT ... FOR UPDATE) before computing the new value, so callers
--    serialize and the second sees the first one's write. The clamp lives
--    in the same place, which is why an oversell now shows as 0 rather
--    than as a negative count.
--
--    EXECUTE is revoked from anon and authenticated: only the service
--    role may move stock. A client that could call this could drain a
--    practitioner's inventory to zero.
--
-- 2) INVOICE SALES NEVER LEFT THE SHELF
--    A product sold on an invoice never came off the count, because
--    invoice line items had no link to a product. The link is a JSON key
--    (invoices.items is jsonb) so no table changed.
--
--    WHY A TRIGGER AND NOT FIVE PATCHED CALL SITES: five paths mark an
--    invoice paid — the Connect webhook, the older Stripe proxy (twice),
--    Chief's mark_invoice_paid action, and the FRONTEND, which PATCHes
--    PostgREST directly and cannot call Python at all. A trigger catches
--    every one of them by construction, including the sixth someone adds
--    next year.
--
--    It is FAIL-OPEN on purpose. Recording that money arrived matters
--    more than adjusting a count, so a stock failure raises a warning and
--    lets the payment through. It is also idempotent: stock_applied_at is
--    stamped once, so paid -> unpaid -> paid never takes stock twice.
--
--    Refunds deliberately do NOT restock. A refund does not mean the
--    goods came back through the door; if they did, the practitioner
--    receives them like any other returned stock.
--
-- Verified against production before shipping (both exercised inside a
-- transaction that was rolled back, leaving nothing behind):
--   decrement: 5 -3 -> old=5 new=2 tracked=t
--              2 -99 -> old=2 new=0 tracked=t   (clamped, never negative)
--              stored value really was 0
--              untracked (inventory_qty is null) -> tracked=f, no write
--              wrong business_id                 -> tracked=f, no write
--   trigger:   invoice with 3 lines (one product, one service, one junk
--              offering_id) paid -> qty 10 -> 7, stamped, exactly 1
--              movement event, reason "invoice SELFTEST-1"
--              paid -> sent -> paid -> still 7 (no double-take)
--
-- Status: APPLIED to production 2026-08-20 via the Management API.


-- ─── 1. The atomic decrement ─────────────────────────────────────────

alter table invoices add column if not exists stock_applied_at timestamptz;

create or replace function public.decrement_offering_stock(
  p_offering_id uuid,
  p_business_id uuid,
  p_qty int,
  out old_qty int,
  out new_qty int,
  out tracked boolean
)
language plpgsql
security invoker
set search_path = public, pg_temp
as $fn$
begin
  -- FOR UPDATE is the whole fix: it serializes concurrent sales of the
  -- same product, so the second caller re-reads the first one's write
  -- instead of racing it.
  select o.inventory_qty into old_qty
    from offerings o
   where o.id = p_offering_id
     and o.business_id = p_business_id
   for update;

  if not found or old_qty is null then
    tracked := false;
    new_qty := null;
    return;
  end if;

  new_qty := greatest(0, old_qty - greatest(0, coalesce(p_qty, 0)));
  update offerings o set inventory_qty = new_qty
   where o.id = p_offering_id and o.business_id = p_business_id;
  tracked := true;
end;
$fn$;

revoke all on function public.decrement_offering_stock(uuid, uuid, int) from public;
revoke all on function public.decrement_offering_stock(uuid, uuid, int) from anon, authenticated;
grant execute on function public.decrement_offering_stock(uuid, uuid, int) to service_role;


-- ─── 2. Invoice sales move stock ─────────────────────────────────────

create or replace function public.invoices_apply_stock()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $fn$
declare
  it     jsonb;
  v_oid  uuid;
  v_qty  int;
  r      record;
  touched boolean := false;
begin
  if new.stock_applied_at is not null then
    return new;
  end if;
  if jsonb_typeof(new.items) is distinct from 'array' then
    return new;
  end if;

  begin
    for it in select * from jsonb_array_elements(new.items) loop
      begin
        v_oid := nullif(trim(it->>'offering_id'), '')::uuid;
      exception when others then
        v_oid := null;
      end;
      if v_oid is null then
        continue;
      end if;

      begin
        v_qty := greatest(0, floor(coalesce((it->>'quantity')::numeric, 1))::int);
      exception when others then
        v_qty := 1;
      end;
      if v_qty = 0 then
        continue;
      end if;

      select * into r
        from public.decrement_offering_stock(v_oid, new.business_id, v_qty);

      if r.tracked then
        touched := true;
        insert into public.events (business_id, event_type, data, source)
        values (
          new.business_id,
          'stock_adjusted',
          jsonb_build_object(
            'offering_id',   v_oid,
            'offering_name', coalesce(nullif(it->>'description', ''), ''),
            'delta',         r.new_qty - r.old_qty,
            'new_qty',       r.new_qty,
            'reason',        'invoice ' || coalesce(nullif(new.invoice_number, ''),
                                                    left(new.id::text, 8)),
            'actor',         'sale'
          ),
          'store'
        );
      end if;
    end loop;

    if touched then
      new.stock_applied_at := now();
    end if;
  exception when others then
    raise warning 'invoices_apply_stock skipped for invoice %: %', new.id, sqlerrm;
  end;

  return new;
end;
$fn$;

drop trigger if exists trg_invoices_apply_stock on public.invoices;
create trigger trg_invoices_apply_stock
  before update on public.invoices
  for each row
  when (new.status = 'paid' and old.status is distinct from 'paid')
  execute function public.invoices_apply_stock();
