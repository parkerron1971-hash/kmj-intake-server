-- ═════════════════════════════════════════════════════════════════════
-- Phase F.2 v1 — Plaid bookkeeping + reconciliation schema
-- ═════════════════════════════════════════════════════════════════════
-- Path C-style additive migration. CREATE TABLE IF NOT EXISTS + idempotent
-- RLS policies. Safe to re-run.
--
-- Tables:
--   plaid_items          (one row per linked institution per business)
--   plaid_accounts       (one row per Plaid account inside an item)
--   plaid_transactions   (one row per transaction, with reconciliation)
--   category_rules       (per-merchant override; F.2-Fork-3 hybrid)
--
-- Access tokens are encrypted at rest via pgcrypto (T9-α ruling).
-- Reads route through the helper sb_clients.sb_get_as_service +
-- decrypt-at-read inside the Python layer; ciphertext stored as bytea.
--
-- Apply via Supabase Studio → SQL editor → Run.
-- ═════════════════════════════════════════════════════════════════════

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ─── Token encryption RPCs ──────────────────────────────────────────
-- T9-α ruling: access tokens encrypted via pgp_sym_encrypt. The
-- backend never holds raw key material in process — it calls these
-- RPCs with the key passed in from the PLAID_ENCRYPTION_KEY env var.
-- EXECUTE is restricted to the service role (authenticated + anon
-- have no grant), so a leaked anon/authenticated key alone cannot
-- decrypt.

CREATE OR REPLACE FUNCTION public.plaid_token_encrypt(plain text, key text)
    RETURNS bytea
    LANGUAGE sql
    SECURITY DEFINER
    AS $$
        SELECT pgp_sym_encrypt(plain, key)
    $$;

CREATE OR REPLACE FUNCTION public.plaid_token_decrypt(cipher bytea, key text)
    RETURNS text
    LANGUAGE sql
    SECURITY DEFINER
    AS $$
        SELECT pgp_sym_decrypt(cipher, key)
    $$;

REVOKE EXECUTE ON FUNCTION public.plaid_token_encrypt(text, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.plaid_token_encrypt(text, text) FROM anon;
REVOKE EXECUTE ON FUNCTION public.plaid_token_encrypt(text, text) FROM authenticated;
REVOKE EXECUTE ON FUNCTION public.plaid_token_decrypt(bytea, text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.plaid_token_decrypt(bytea, text) FROM anon;
REVOKE EXECUTE ON FUNCTION public.plaid_token_decrypt(bytea, text) FROM authenticated;

-- ─── plaid_items ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.plaid_items (
    item_id              text PRIMARY KEY,
    business_id          uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
    -- Encrypted via pgcrypto. Decrypt only on the server with the
    -- PLAID_ENCRYPTION_KEY env var (see plaid_helpers.py).
    access_token_enc     bytea NOT NULL,
    institution_id       text,
    institution_name     text,
    status               text NOT NULL DEFAULT 'active',  -- active / re-auth-required / revoked / error
    cursor               text,                            -- /transactions/sync cursor
    last_sync_at         timestamptz,
    last_error           text,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_plaid_items_business
    ON public.plaid_items (business_id);
CREATE INDEX IF NOT EXISTS idx_plaid_items_status
    ON public.plaid_items (status);

-- ─── plaid_accounts ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.plaid_accounts (
    account_id           text PRIMARY KEY,
    item_id              text NOT NULL REFERENCES public.plaid_items(item_id) ON DELETE CASCADE,
    business_id          uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
    name                 text,
    official_name        text,
    type                 text,            -- depository / credit / loan / investment / brokerage
    subtype              text,            -- checking / savings / credit_card / etc.
    mask                 text,            -- last 4 digits
    last_balance         numeric(14,2),
    last_balance_at      timestamptz,
    iso_currency         text DEFAULT 'USD',
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_plaid_accounts_item
    ON public.plaid_accounts (item_id);
CREATE INDEX IF NOT EXISTS idx_plaid_accounts_business
    ON public.plaid_accounts (business_id);

-- ─── plaid_transactions ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.plaid_transactions (
    transaction_id              text PRIMARY KEY,
    account_id                  text NOT NULL REFERENCES public.plaid_accounts(account_id) ON DELETE CASCADE,
    business_id                 uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
    -- Plaid sign convention: positive = outflow (debit), negative = inflow (credit/deposit).
    amount                      numeric(14,2) NOT NULL,
    iso_currency_code           text DEFAULT 'USD',
    date                        date NOT NULL,
    authorized_date             date,
    datetime                    timestamptz,
    name                        text,
    merchant_name               text,
    plaid_category_primary      text,
    plaid_category_detail       text,
    -- Solutionist 5-bucket override. Pinned via CHECK to match the
    -- existing business_expenses.category constraint + the Allocator.
    business_category           text CHECK (business_category IN
        ('tax', 'owner_pay', 'operating', 'savings', 'other')),
    business_subcategory        text,
    pending                     boolean DEFAULT false,
    -- Reconciliation (Phase F.2 auto-match + F.1 prep).
    reconciled_to_payout_id     text,
    reconciled_to_charge_id     text,
    reconciled_to_transfer_id   text,            -- Placeholder for F.1 outbound match.
    reconciliation_status       text NOT NULL DEFAULT 'unmatched'
        CHECK (reconciliation_status IN
            ('unmatched', 'auto_matched', 'manual_matched', 'ignored')),
    practitioner_notes          text,
    created_at                  timestamptz NOT NULL DEFAULT now(),
    updated_at                  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_plaid_tx_business_date
    ON public.plaid_transactions (business_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_plaid_tx_account
    ON public.plaid_transactions (account_id);
CREATE INDEX IF NOT EXISTS idx_plaid_tx_reconciliation
    ON public.plaid_transactions (business_id, reconciliation_status);
CREATE INDEX IF NOT EXISTS idx_plaid_tx_merchant
    ON public.plaid_transactions (business_id, merchant_name)
    WHERE merchant_name IS NOT NULL;

-- ─── category_rules ──────────────────────────────────────────────────
-- F.2-Fork-3 (α hybrid) — persisted per-merchant overrides so future
-- transactions from the same merchant auto-categorize. The drawer's
-- "Save & create rule" checkbox writes here; the reconciliation /
-- categorization pass checks this table BEFORE applying the static
-- Plaid → 5-bucket map.
CREATE TABLE IF NOT EXISTS public.category_rules (
    id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id                 uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
    -- Match strategy: case-insensitive equality on merchant_name today.
    -- Plaid's normalized merchant names are remarkably consistent so
    -- exact match is enough for v1; regex / contains can land in v1.5.
    merchant_name               text NOT NULL,
    business_category           text NOT NULL CHECK (business_category IN
        ('tax', 'owner_pay', 'operating', 'savings', 'other')),
    business_subcategory        text,
    created_at                  timestamptz NOT NULL DEFAULT now(),
    updated_at                  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (business_id, merchant_name)
);

CREATE INDEX IF NOT EXISTS idx_category_rules_business
    ON public.category_rules (business_id);

-- ─── plaid_webhook_events (idempotency) ──────────────────────────────
-- Plaid webhook idempotency keyed by webhook_code + item_id + dedup
-- field. Separate from stripe_webhook_events because Plaid's event
-- shape differs (no global event id). Sticking to a dedicated table
-- keeps both schemas legible.
CREATE TABLE IF NOT EXISTS public.plaid_webhook_events (
    id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    webhook_type                text NOT NULL,                 -- TRANSACTIONS / ITEM / etc.
    webhook_code                text NOT NULL,                 -- SYNC_UPDATES_AVAILABLE / ITEM_LOGIN_REQUIRED / etc.
    item_id                     text,
    new_transactions            integer,
    raw                         jsonb NOT NULL,
    received_at                 timestamptz NOT NULL DEFAULT now(),
    processed_at                timestamptz,
    processed_ok                boolean,
    processed_error             text
);

CREATE INDEX IF NOT EXISTS idx_plaid_webhook_item
    ON public.plaid_webhook_events (item_id);

-- ═════════════════════════════════════════════════════════════════════
-- Row Level Security
-- ═════════════════════════════════════════════════════════════════════
-- Pattern mirrors the existing Solutionist RLS: practitioner can read
-- their own businesses' data via the owner_id match through businesses;
-- writes happen exclusively via the service role (Plaid webhook + the
-- backend's authenticated endpoints).
--
-- The auth.uid()-to-business path goes through businesses.owner_id;
-- a JOIN-based EXISTS check is the conventional way in Supabase.

ALTER TABLE public.plaid_items           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.plaid_accounts        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.plaid_transactions    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.category_rules        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.plaid_webhook_events  ENABLE ROW LEVEL SECURITY;

-- ─── plaid_items: owner SELECT only ────────────────────────────────
DROP POLICY IF EXISTS plaid_items_owner_select ON public.plaid_items;
CREATE POLICY plaid_items_owner_select ON public.plaid_items
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.businesses b
            WHERE b.id = plaid_items.business_id
              AND b.owner_id = auth.uid()
        )
    );

-- ─── plaid_accounts: owner SELECT only ──────────────────────────────
DROP POLICY IF EXISTS plaid_accounts_owner_select ON public.plaid_accounts;
CREATE POLICY plaid_accounts_owner_select ON public.plaid_accounts
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.businesses b
            WHERE b.id = plaid_accounts.business_id
              AND b.owner_id = auth.uid()
        )
    );

-- ─── plaid_transactions: owner SELECT + UPDATE (override category) ──
-- Practitioners can re-categorize / mark ignored / add notes via the
-- drawer; everything else routes through the backend service role.
DROP POLICY IF EXISTS plaid_tx_owner_select ON public.plaid_transactions;
CREATE POLICY plaid_tx_owner_select ON public.plaid_transactions
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.businesses b
            WHERE b.id = plaid_transactions.business_id
              AND b.owner_id = auth.uid()
        )
    );

DROP POLICY IF EXISTS plaid_tx_owner_update ON public.plaid_transactions;
CREATE POLICY plaid_tx_owner_update ON public.plaid_transactions
    FOR UPDATE
    USING (
        EXISTS (
            SELECT 1 FROM public.businesses b
            WHERE b.id = plaid_transactions.business_id
              AND b.owner_id = auth.uid()
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.businesses b
            WHERE b.id = plaid_transactions.business_id
              AND b.owner_id = auth.uid()
        )
    );

-- ─── category_rules: full owner CRUD ─────────────────────────────────
-- Rules are practitioner authored; service role is not required.
DROP POLICY IF EXISTS category_rules_owner_select ON public.category_rules;
CREATE POLICY category_rules_owner_select ON public.category_rules
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM public.businesses b
            WHERE b.id = category_rules.business_id
              AND b.owner_id = auth.uid()
        )
    );

DROP POLICY IF EXISTS category_rules_owner_insert ON public.category_rules;
CREATE POLICY category_rules_owner_insert ON public.category_rules
    FOR INSERT
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.businesses b
            WHERE b.id = category_rules.business_id
              AND b.owner_id = auth.uid()
        )
    );

DROP POLICY IF EXISTS category_rules_owner_update ON public.category_rules;
CREATE POLICY category_rules_owner_update ON public.category_rules
    FOR UPDATE
    USING (
        EXISTS (
            SELECT 1 FROM public.businesses b
            WHERE b.id = category_rules.business_id
              AND b.owner_id = auth.uid()
        )
    );

DROP POLICY IF EXISTS category_rules_owner_delete ON public.category_rules;
CREATE POLICY category_rules_owner_delete ON public.category_rules
    FOR DELETE
    USING (
        EXISTS (
            SELECT 1 FROM public.businesses b
            WHERE b.id = category_rules.business_id
              AND b.owner_id = auth.uid()
        )
    );

-- ─── plaid_webhook_events: no end-user access ────────────────────────
-- Webhook outcomes are debugging audit; practitioners don't need to
-- see them. Service role only.
-- (No policies → RLS enabled → nobody can read; only service role
-- which bypasses RLS can touch the table. This is intentional.)

-- ═════════════════════════════════════════════════════════════════════
-- Verify
-- ═════════════════════════════════════════════════════════════════════
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'plaid_items', 'plaid_accounts', 'plaid_transactions',
    'category_rules', 'plaid_webhook_events'
  )
ORDER BY table_name;

SELECT schemaname, tablename, rowsecurity
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename IN (
    'plaid_items', 'plaid_accounts', 'plaid_transactions',
    'category_rules', 'plaid_webhook_events'
  )
ORDER BY tablename;
