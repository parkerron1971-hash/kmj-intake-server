-- Archive is independent of invoice/payment status. Existing invoices remain active.
ALTER TABLE public.invoices ADD COLUMN IF NOT EXISTS archived_at timestamptz;
CREATE INDEX IF NOT EXISTS invoices_business_archive_idx ON public.invoices (business_id, archived_at);
