-- APPLY-2026_08_20_offering_barcode.sql
-- SCAN THE SHELF, rung one — the product code the scanner learns.
--
-- WHY A NEW COLUMN AND NOT `sku`
--   sku is free text a human typed for their own filing. barcode is a
--   machine key read off the package, and the whole economics of the
--   scanner depend on it being exact: an exact hit costs zero tokens
--   and cannot be wrong, while a fuzzy name match costs a vision call
--   and quietly breeds duplicate products. Overloading sku would mix
--   the two and make neither trustworthy.
--
-- WHY UNIQUE PER BUSINESS
--   One code means one product, so a scan is never ambiguous. Scoped to
--   the business because two practitioners can legitimately stock the
--   same item. The index is PARTIAL (barcode is not null) so the
--   hundreds of existing rows with no code do not collide — and because
--   the column is new, nothing can violate it on the way in.
--
-- Status: APPLIED to production 2026-08-20 via the Management API.

alter table offerings add column if not exists barcode text;

create unique index if not exists offerings_business_barcode_uniq
  on offerings (business_id, barcode) where barcode is not null;
