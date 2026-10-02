-- APPLY-2026-09-05-pay-your-team.sql
-- Pay your team — the payroll DATA LAYER (Route D, 2026-09-05).
--
-- What this is: employees, their W-4 tax profile, and pay runs with
-- per-employee line items. What it is NOT: a money rail or a tax filer.
-- No bank account numbers live here (the payout rail owns those; we keep
-- only the rail's reference id). Nothing in these tables moves money.
--
-- SSN handling mirrors contractors.tin_encrypted: Fernet ciphertext with
-- the key in the TIN_ENCRYPTION_KEY env var, last4 for display, and the
-- profile table carries NO RLS policies — service-role only, like
-- quickbooks_connections — so a leaked anon/user session can never read
-- ciphertext it has no key for anyway.
--
-- Additive + idempotent. Rollback at the bottom.

CREATE TABLE IF NOT EXISTS public.employees (
  id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id                 uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  first_name                  text NOT NULL,
  last_name                   text NOT NULL,
  email                       text,
  phone                       text,
  hire_date                   date,
  termination_date            date,
  status                      text NOT NULL DEFAULT 'active'
                                CHECK (status IN ('active', 'terminated')),
  pay_type                    text NOT NULL DEFAULT 'hourly'
                                CHECK (pay_type IN ('hourly', 'salary')),
  -- hourly: dollars per hour. salary: dollars per YEAR.
  pay_rate                    numeric(12,2) NOT NULL DEFAULT 0 CHECK (pay_rate >= 0),
  pay_frequency               text NOT NULL DEFAULT 'biweekly'
                                CHECK (pay_frequency IN ('weekly', 'biweekly', 'semimonthly', 'monthly')),
  work_state                  text,          -- 2-letter; where the work happens
  residence_state             text,          -- 2-letter; where they live
  -- Direct deposit is an electronic wage payment; most states require the
  -- employee's written consent. We record WHEN they consented, never the
  -- account — the rail (Plaid / Stripe Treasury) holds the account.
  direct_deposit_consented_at timestamptz,
  payout_rail                 text CHECK (payout_rail IS NULL OR payout_rail IN ('plaid', 'stripe_treasury', 'manual')),
  payout_ref                  text,          -- the rail's id for this person; never an account number
  new_hire_reported_at        timestamptz,   -- state new-hire report (due within 20 days)
  notes                       text,
  created_at                  timestamptz NOT NULL DEFAULT now(),
  updated_at                  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_employees_business
  ON public.employees (business_id, status);

CREATE TABLE IF NOT EXISTS public.employee_tax_profiles (
  employee_id     uuid PRIMARY KEY REFERENCES public.employees(id) ON DELETE CASCADE,
  business_id     uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  ssn_encrypted   text,
  ssn_last4       text,
  address         jsonb NOT NULL DEFAULT '{}'::jsonb,
  -- Form W-4 (2020+) step values. The form itself stays with the
  -- employer — it is never sent to the IRS or the state.
  federal         jsonb NOT NULL DEFAULT '{}'::jsonb,
  -- State withholding form values, shape varies by state.
  state           jsonb NOT NULL DEFAULT '{}'::jsonb,
  w4_version      text NOT NULL DEFAULT '2020',
  w4_signed_at    timestamptz,
  updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_employee_tax_profiles_business
  ON public.employee_tax_profiles (business_id);

CREATE TABLE IF NOT EXISTS public.pay_runs (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id   uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  period_start  date NOT NULL,
  period_end    date NOT NULL,
  pay_date      date NOT NULL,
  status        text NOT NULL DEFAULT 'draft'
                  CHECK (status IN ('draft', 'approved', 'paid', 'cancelled')),
  -- Who filled the withholding numbers: the owner by hand, or a tax engine.
  calc_source   text NOT NULL DEFAULT 'manual'
                  CHECK (calc_source IN ('manual', 'symmetry')),
  totals        jsonb NOT NULL DEFAULT '{}'::jsonb,
  payout_rail   text CHECK (payout_rail IS NULL OR payout_rail IN ('plaid', 'stripe_treasury', 'manual')),
  rail_ref      text,
  approved_at   timestamptz,
  approved_by   uuid,
  paid_at       timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pay_runs_business
  ON public.pay_runs (business_id, pay_date DESC);

CREATE TABLE IF NOT EXISTS public.pay_run_items (
  id                        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  pay_run_id                uuid NOT NULL REFERENCES public.pay_runs(id) ON DELETE CASCADE,
  business_id               uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
  employee_id               uuid NOT NULL REFERENCES public.employees(id) ON DELETE CASCADE,
  hours                     numeric(8,2) NOT NULL DEFAULT 0,
  overtime_hours            numeric(8,2) NOT NULL DEFAULT 0,
  gross                     numeric(12,2) NOT NULL DEFAULT 0,
  -- Employee-side withholdings. FIT/SIT are NULL until a tax engine or
  -- the owner fills them; FICA is statutory and computed here.
  federal_withholding       numeric(12,2),
  state_withholding         numeric(12,2),
  social_security_employee  numeric(12,2) NOT NULL DEFAULT 0,
  medicare_employee         numeric(12,2) NOT NULL DEFAULT 0,
  other_deductions          numeric(12,2) NOT NULL DEFAULT 0,
  net                       numeric(12,2),
  -- Employer-side taxes (not deducted from the employee).
  employer_social_security  numeric(12,2) NOT NULL DEFAULT 0,
  employer_medicare         numeric(12,2) NOT NULL DEFAULT 0,
  employer_futa             numeric(12,2) NOT NULL DEFAULT 0,
  employer_suta             numeric(12,2),
  calc_status               text NOT NULL DEFAULT 'needs_calculation'
                              CHECK (calc_status IN ('needs_calculation', 'calculated', 'manual')),
  calc_payload              jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at                timestamptz NOT NULL DEFAULT now(),
  updated_at                timestamptz NOT NULL DEFAULT now(),
  UNIQUE (pay_run_id, employee_id)
);
CREATE INDEX IF NOT EXISTS idx_pay_run_items_run
  ON public.pay_run_items (pay_run_id);
CREATE INDEX IF NOT EXISTS idx_pay_run_items_employee
  ON public.pay_run_items (employee_id, created_at DESC);

-- ─── RLS ────────────────────────────────────────────────────────────
-- Owner READ on employees / pay_runs / pay_run_items (writes go through
-- the backend service role, which also enforces seat roles).
-- employee_tax_profiles: RLS ON, NO policies — service-role only.
ALTER TABLE public.employees             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.employee_tax_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pay_runs              ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pay_run_items         ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS employees_owner_read ON public.employees;
CREATE POLICY employees_owner_read ON public.employees
  FOR SELECT
  USING (EXISTS (SELECT 1 FROM public.businesses b
                 WHERE b.id = employees.business_id AND b.owner_id = auth.uid()));

DROP POLICY IF EXISTS pay_runs_owner_read ON public.pay_runs;
CREATE POLICY pay_runs_owner_read ON public.pay_runs
  FOR SELECT
  USING (EXISTS (SELECT 1 FROM public.businesses b
                 WHERE b.id = pay_runs.business_id AND b.owner_id = auth.uid()));

DROP POLICY IF EXISTS pay_run_items_owner_read ON public.pay_run_items;
CREATE POLICY pay_run_items_owner_read ON public.pay_run_items
  FOR SELECT
  USING (EXISTS (SELECT 1 FROM public.businesses b
                 WHERE b.id = pay_run_items.business_id AND b.owner_id = auth.uid()));

-- ─── Rollback ───────────────────────────────────────────────────────
--   DROP TABLE IF EXISTS public.pay_run_items;
--   DROP TABLE IF EXISTS public.pay_runs;
--   DROP TABLE IF EXISTS public.employee_tax_profiles;
--   DROP TABLE IF EXISTS public.employees;
