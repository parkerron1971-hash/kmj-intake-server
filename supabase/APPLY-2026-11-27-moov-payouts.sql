-- ═════════════════════════════════════════════════════════════════════
-- Moov payouts (test mode): a church pays its 1099 people from its OWN bank
-- ═════════════════════════════════════════════════════════════════════
-- moov_payouts.py. Kevin applies this by hand. Additive and idempotent.
-- Nothing here holds a bank or card number: only Moov's own ids, statuses
-- and the church's caps.
--
--   moov_accounts ....... one row per church (kind 'church': the church's own
--                         Moov business account, its opt-in and caps) and one
--                         per payee (kind 'payee': a contractor's Moov account)
--   moov_payouts ........ one row per payout; its idempotency key is unique,
--                         and a bill can have only one payout in flight or paid
--   moov_webhook_events . Moov's event ids, so a repeat delivery is seen
--
-- RLS: on for all three. The owner may READ their church's accounts and
-- payouts; every write is the server's (service role). No browser role reads
-- the webhook events.
-- Rollback: the DROP lines at the end.
-- ═════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS public.moov_accounts (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id         uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
    kind                text NOT NULL CHECK (kind IN ('church', 'payee')),
    contractor_id       uuid REFERENCES public.contractors(id) ON DELETE CASCADE,
    mode                text NOT NULL DEFAULT 'test' CHECK (mode IN ('test', 'live')),
    opted_in            boolean NOT NULL DEFAULT false,
    opted_in_by         uuid,
    opted_in_at         timestamptz,
    invite_code         text,
    moov_account_id     text,
    status              text NOT NULL DEFAULT 'off'
                          CHECK (status IN ('off', 'invited', 'pending', 'active', 'restricted', 'disabled')),
    bank_ready          boolean NOT NULL DEFAULT false,
    per_payment_cap     numeric(12,2) NOT NULL DEFAULT 1000 CHECK (per_payment_cap > 0),
    daily_cap           numeric(12,2) NOT NULL DEFAULT 2500 CHECK (daily_cap > 0),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CHECK ((kind = 'payee') = (contractor_id IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_moov_accounts_church
    ON public.moov_accounts (business_id, mode) WHERE kind = 'church';
CREATE UNIQUE INDEX IF NOT EXISTS uq_moov_accounts_payee
    ON public.moov_accounts (contractor_id, mode) WHERE kind = 'payee';
-- One Moov account belongs to one row: no church can claim another's account.
CREATE UNIQUE INDEX IF NOT EXISTS uq_moov_accounts_moov_id
    ON public.moov_accounts (moov_account_id, mode) WHERE moov_account_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_moov_accounts_moov_id
    ON public.moov_accounts (moov_account_id);

CREATE TABLE IF NOT EXISTS public.moov_payouts (
    id                              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id                     uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
    contractor_id                   uuid REFERENCES public.contractors(id) ON DELETE SET NULL,
    bill_id                         uuid REFERENCES public.bills(id) ON DELETE SET NULL,
    bill_made_here                  boolean NOT NULL DEFAULT false,
    bill_was_status                 text,
    mode                            text NOT NULL DEFAULT 'test' CHECK (mode IN ('test', 'live')),
    amount                          numeric(12,2) NOT NULL CHECK (amount > 0),
    speed                           text NOT NULL DEFAULT 'next_day'
                                      CHECK (speed IN ('next_day', 'same_day', 'instant')),
    fee_estimate                    numeric(8,2),
    description                     text,
    status                          text NOT NULL DEFAULT 'created'
                                      CHECK (status IN ('created', 'queued', 'pending', 'completed',
                                                        'failed', 'reversed', 'canceled')),
    idempotency_key                 text NOT NULL,
    moov_transfer_id                text,
    source_account_id               text,
    source_payment_method_id        text,
    destination_account_id          text,
    destination_payment_method_id   text,
    failure_reason                  text,
    return_code                     text,
    needs_review                    boolean NOT NULL DEFAULT false,
    approved_by                     uuid NOT NULL,
    created_at                      timestamptz NOT NULL DEFAULT now(),
    updated_at                      timestamptz NOT NULL DEFAULT now(),
    completed_at                    timestamptz,
    failed_at                       timestamptz,
    bill_settled_at                 timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_moov_payouts_key
    ON public.moov_payouts (idempotency_key);
CREATE UNIQUE INDEX IF NOT EXISTS uq_moov_payouts_transfer
    ON public.moov_payouts (moov_transfer_id) WHERE moov_transfer_id IS NOT NULL;
-- One payout in flight or paid per bill: a bill is never sent twice.
CREATE UNIQUE INDEX IF NOT EXISTS uq_moov_payouts_live_bill
    ON public.moov_payouts (bill_id)
    WHERE bill_id IS NOT NULL AND status IN ('created', 'queued', 'pending', 'completed');
CREATE INDEX IF NOT EXISTS idx_moov_payouts_business
    ON public.moov_payouts (business_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.moov_webhook_events (
    event_id        text PRIMARY KEY,
    type            text,
    received_at     timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.moov_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.moov_payouts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.moov_webhook_events ENABLE ROW LEVEL SECURITY;

-- Owner read only. A direct owner_id compare on businesses (no policy on
-- businesses reads back into these tables, so no 42P17 recursion).
DROP POLICY IF EXISTS moov_accounts_owner_read ON public.moov_accounts;
CREATE POLICY moov_accounts_owner_read ON public.moov_accounts
    FOR SELECT
    USING (EXISTS (SELECT 1 FROM public.businesses b
                   WHERE b.id = moov_accounts.business_id AND b.owner_id = auth.uid()));

DROP POLICY IF EXISTS moov_payouts_owner_read ON public.moov_payouts;
CREATE POLICY moov_payouts_owner_read ON public.moov_payouts
    FOR SELECT
    USING (EXISTS (SELECT 1 FROM public.businesses b
                   WHERE b.id = moov_payouts.business_id AND b.owner_id = auth.uid()));

REVOKE ALL ON public.moov_webhook_events FROM anon, authenticated;
REVOKE INSERT, UPDATE, DELETE ON public.moov_accounts FROM anon, authenticated;
REVOKE INSERT, UPDATE, DELETE ON public.moov_payouts FROM anon, authenticated;

-- ─── After-check (expect 3 rows, rls on) ─────────────────────────────
--   SELECT relname, relrowsecurity FROM pg_class
--    WHERE relname IN ('moov_accounts', 'moov_payouts', 'moov_webhook_events');

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP TABLE IF EXISTS public.moov_webhook_events;
--   DROP TABLE IF EXISTS public.moov_payouts;
--   DROP TABLE IF EXISTS public.moov_accounts;
