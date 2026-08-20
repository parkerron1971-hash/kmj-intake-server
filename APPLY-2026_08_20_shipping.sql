-- APPLY-2026_08_20_shipping.sql
-- Shipping that varies — the inputs a rate needs.
--
-- WHAT WAS WRONG
--   One flat fee per business, charged once per order containing
--   anything physical. The same money for a keychain and a twenty-pound
--   box, to the next street or across the country. A shop selling
--   anything heavy lost money on every order.
--
-- THE PRODUCT SIDE
--   ship_surcharge_cents  what a heavy item ADDS, per unit. This alone
--                         covers most small shops and needs no carrier
--                         account, no weights, and no maintenance.
--   weight_oz + dims      what a CARRIER needs in order to quote.
--                         Nullable on purpose: a product with no weight
--                         is simply not rated by a carrier and the
--                         built-in rate is used instead. A quote for a
--                         guessed weight is worse than no quote at all,
--                         because it gets charged.
--
-- THE ORDER SIDE
--   shipping_method       WHICH option the customer picked. The amount
--                         is priced server-side every time; only the
--                         code ever travels over the wire.
--   tracking_carrier      so a practitioner can say where it is.
--   tracking_number
--   shipped_at            deliberately distinct from fulfilled_at.
--                         "Fulfilled" has meant "the practitioner dealt
--                         with it" since Arc 27, and overloading it
--                         would silently rewrite the meaning of every
--                         order already in the table.
--
-- WHY THE SETTINGS ARE NOT COLUMNS
--   flat_cents, free_over_cents, pickup{enabled,note} and countries[]
--   live in settings.store.shipping — the same settings-blob pattern as
--   low_stock and product_files. shipping_rates.settings_of() reads the
--   legacy flat_shipping_cents as the fallback FOREVER, so a business
--   that never opens the new screen keeps charging exactly what it
--   charged before this shipped.
--
-- Status: APPLIED to production 2026-08-20 via the Management API.

alter table offerings add column if not exists ship_surcharge_cents int not null default 0;
alter table offerings add column if not exists weight_oz numeric;
alter table offerings add column if not exists length_in numeric;
alter table offerings add column if not exists width_in  numeric;
alter table offerings add column if not exists height_in numeric;

alter table orders add column if not exists shipping_method  text;
alter table orders add column if not exists tracking_carrier text;
alter table orders add column if not exists tracking_number  text;
alter table orders add column if not exists shipped_at       timestamptz;
