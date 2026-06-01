-- ═══════════════════════════════════════════════════════════════════════
-- business_customers — auth identity for customer-facing widget surfaces
-- ═══════════════════════════════════════════════════════════════════════
-- Phase C.1 introduces customer-facing widgets (BookingForm, etc) backed
-- by signed tokenized URLs (no Supabase auth account for customers). This
-- table is the auth identity for those tokens: one row per (business,
-- customer) binding. Tokens carry biz + cus claims that match this row.
--
-- Relationship to contacts:
--   - business_customers is the AUTH identity (token-bearing).
--   - contacts is the DATA identity (CRM, the practitioner's view).
--   - The two link via business_customers.contact_id (nullable — anon
--     walk-ins create a customer row before a contact exists).
--   - Customer data (appointments, etc.) lives in module_entries
--     scoped to the contact_id, NOT this table. Token revocation
--     (= row delete) does NOT delete appointment history on the
--     practitioner side.
--
-- RLS:
--   - Practitioners (authenticated role) see/manage only their own
--     business's customers (matches the businesses RLS pattern).
--   - Anon role has ZERO direct access. All customer-facing reads go
--     through FastAPI endpoints that use service-role internally and
--     verify HMAC-signed token claims before scoping data.
--
-- NON-DESTRUCTIVE + IDEMPOTENT.
-- ═══════════════════════════════════════════════════════════════════════

BEGIN;

CREATE TABLE IF NOT EXISTS public.business_customers (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  contact_id  uuid REFERENCES public.contacts(id) ON DELETE SET NULL,
  email       text,
  name        text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT business_customers_email_check CHECK (email IS NULL OR email LIKE '%@%')
);

CREATE INDEX IF NOT EXISTS business_customers_business_id_idx
  ON public.business_customers(business_id);

CREATE INDEX IF NOT EXISTS business_customers_contact_id_idx
  ON public.business_customers(contact_id) WHERE contact_id IS NOT NULL;

-- Unique on (business_id, lower(email)) — dedupe walk-ins by email, but
-- only for rows that HAVE an email (anon walk-ins without one are allowed).
CREATE UNIQUE INDEX IF NOT EXISTS business_customers_biz_email_uniq
  ON public.business_customers(business_id, lower(email)) WHERE email IS NOT NULL;

ALTER TABLE public.business_customers ENABLE ROW LEVEL SECURITY;

-- Practitioner-only access (matches the businesses.owner_id pattern used
-- across the rest of the RLS-aware tables: module_specs, growth_objectives,
-- workflow_definitions, etc).
DROP POLICY IF EXISTS business_customers_owner_all ON public.business_customers;
CREATE POLICY business_customers_owner_all ON public.business_customers
  FOR ALL TO authenticated
  USING  (business_id IN (SELECT id FROM public.businesses WHERE owner_id = auth.uid()))
  WITH CHECK (business_id IN (SELECT id FROM public.businesses WHERE owner_id = auth.uid()));

-- Anon role gets NO policy → no access by default. Customer-facing reads
-- route through FastAPI endpoints with service-role + token verification.

COMMIT;
