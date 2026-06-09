-- ═════════════════════════════════════════════════════════════════════
-- Phase I.1a — Double-entry General Ledger — schema + COA
-- ═════════════════════════════════════════════════════════════════════
-- Greenfield GL foundation. Accrual-recorded books (GL-2) with a Stripe-
-- Clearing / Undeposited-Funds pattern (GL-4). Ledger lines are append-only
-- and immutable (audit-trail anchor): corrections post REVERSING entries;
-- never UPDATE/DELETE a ledger_entry. A journal_entry is one event with N
-- balanced ledger lines (GL-3). gl_sync_queue is the C+enqueue-trigger
-- substrate (Ruling GL-1) — the enqueue TRIGGERS are wired in I.2, not here.
--
-- Additive + idempotent. Clean rollback (DROP the new tables; source tables
-- untouched). Apply via Supabase Studio → SQL.
-- ═════════════════════════════════════════════════════════════════════

-- ─── Chart of accounts ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.chart_of_accounts (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id          uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
    code                 text NOT NULL,
    name                 text NOT NULL,
    type                 text NOT NULL CHECK (type IN ('asset','liability','equity','income','expense')),
    normal_balance       text NOT NULL CHECK (normal_balance IN ('debit','credit')),
    -- Hybrid hinge (F12): income/expense accounts carry a Profit-First bucket
    -- so the Allocator + Tax-Set-Aside keep working off the GL.
    profit_first_bucket  text CHECK (profit_first_bucket IN ('tax','owner_pay','operating','savings','other')),
    is_trust             boolean NOT NULL DEFAULT false,   -- IOLTA prep (I.7)
    parent_code          text,
    is_system            boolean NOT NULL DEFAULT true,
    currency             text NOT NULL DEFAULT 'USD',
    created_at           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (business_id, code)
);
CREATE INDEX IF NOT EXISTS idx_coa_business ON public.chart_of_accounts (business_id, type);

-- ─── Journal entries (event headers) ────────────────────────────────
CREATE TABLE IF NOT EXISTS public.journal_entries (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id          uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
    entry_date           date NOT NULL,
    description          text,
    -- Idempotency key: one entry per (event type, source row).
    source_type          text NOT NULL,    -- invoice_issue | invoice_payment | invoice_refund
                                            -- | expense | bill_issue | bill_payment
                                            -- | plaid_transaction | opening_balance | manual | closing
    source_id            text NOT NULL,
    is_reversal          boolean NOT NULL DEFAULT false,
    reverses_entry_id    uuid,
    created_at           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (business_id, source_type, source_id)
);
CREATE INDEX IF NOT EXISTS idx_je_business_date ON public.journal_entries (business_id, entry_date);

-- ─── Ledger entries (immutable lines) ───────────────────────────────
CREATE TABLE IF NOT EXISTS public.ledger_entries (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id          uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
    journal_entry_id     uuid NOT NULL REFERENCES public.journal_entries(id) ON DELETE CASCADE,
    account_id           uuid NOT NULL REFERENCES public.chart_of_accounts(id),
    -- Denormalized for fast report queries (no join needed).
    account_code         text NOT NULL,
    account_type         text NOT NULL,
    profit_first_bucket  text,
    source_type          text NOT NULL,
    debit                numeric(14,2) NOT NULL DEFAULT 0 CHECK (debit >= 0),
    credit               numeric(14,2) NOT NULL DEFAULT 0 CHECK (credit >= 0),
    entry_date           date NOT NULL,
    currency             text NOT NULL DEFAULT 'USD',
    memo                 text,
    created_at           timestamptz NOT NULL DEFAULT now(),
    -- A line is debit XOR credit.
    CHECK (NOT (debit > 0 AND credit > 0))
);
CREATE INDEX IF NOT EXISTS idx_le_business_account ON public.ledger_entries (business_id, account_code, entry_date);
CREATE INDEX IF NOT EXISTS idx_le_business_source ON public.ledger_entries (business_id, source_type, entry_date);

-- ─── Accounting periods (table only; close logic in I.3) ────────────
CREATE TABLE IF NOT EXISTS public.accounting_periods (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id          uuid NOT NULL REFERENCES public.businesses(id) ON DELETE CASCADE,
    period_start         date NOT NULL,
    period_end           date NOT NULL,
    status               text NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed')),
    closed_at            timestamptz,
    closed_by            uuid,
    created_at           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (business_id, period_start, period_end)
);

-- ─── GL sync queue (C+enqueue-trigger substrate; triggers land in I.2) ─
CREATE TABLE IF NOT EXISTS public.gl_sync_queue (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id          uuid NOT NULL,
    source_table         text NOT NULL,
    source_id            text NOT NULL,
    op                   text NOT NULL,             -- insert | update | delete
    enqueued_at          timestamptz NOT NULL DEFAULT now(),
    processed_at         timestamptz
);
CREATE INDEX IF NOT EXISTS idx_gl_queue_unprocessed
    ON public.gl_sync_queue (business_id) WHERE processed_at IS NULL;

-- ═════════════════════════════════════════════════════════════════════
-- RLS — owner read on all GL tables (writes flow through the backend
-- service role, same as Phase F.2/G/H). gl_sync_queue is service-only.
-- ═════════════════════════════════════════════════════════════════════
ALTER TABLE public.chart_of_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.journal_entries   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ledger_entries    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.accounting_periods ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gl_sync_queue     ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['chart_of_accounts','journal_entries','ledger_entries','accounting_periods']
  LOOP
    EXECUTE format('DROP POLICY IF EXISTS %I_owner_read ON public.%I;', t, t);
    EXECUTE format(
      'CREATE POLICY %I_owner_read ON public.%I FOR SELECT USING (' ||
      'EXISTS (SELECT 1 FROM public.businesses b WHERE b.id = %I.business_id AND b.owner_id = auth.uid()));',
      t, t, t);
  END LOOP;
END $$;
-- gl_sync_queue: no policies → service-role only (intentional).

-- ─── Rollback ────────────────────────────────────────────────────────
--   DROP TABLE IF EXISTS public.gl_sync_queue;
--   DROP TABLE IF EXISTS public.accounting_periods;
--   DROP TABLE IF EXISTS public.ledger_entries;
--   DROP TABLE IF EXISTS public.journal_entries;
--   DROP TABLE IF EXISTS public.chart_of_accounts;

-- ─── Verify ──────────────────────────────────────────────────────────
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('chart_of_accounts','journal_entries','ledger_entries',
                     'accounting_periods','gl_sync_queue')
ORDER BY table_name;
