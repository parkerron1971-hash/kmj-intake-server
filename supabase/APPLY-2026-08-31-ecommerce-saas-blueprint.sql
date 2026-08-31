-- APPLY-2026-08-31-ecommerce-saas-blueprint.sql
-- RUN ONCE (whole file).
--
-- Module blueprints for the 'ecommerce' and 'saas' verticals.
--
-- WHY THIS FILE EXISTS AND WHY IT IS NOT OPTIONAL
--   business_type_archetypes ALREADY carried rows for both types, so the
--   businesses.type FK has accepted them for a long time and businesses
--   could be stamped 'ecommerce' or 'saas'. What did not exist was anything
--   behind the stamp: no Chief profile, no dictionary, no playbook, and no
--   module blueprint. The code half of that ships in the same arc.
--
--   This file is the part that makes a SIGNUP produce something.
--   module_blueprint_agent.provision_modules() walks
--   business_type_module_blueprint and creates the core module set. With no
--   rows it returns [] and provisions NOTHING — the practitioner lands in an
--   empty workspace. Adding these two to the onboarding picker without this
--   file would be a card that leads nowhere, which is exactly the
--   dead-weight rule.
--
--   This is the mistake the nonprofit closure note records: the blueprint
--   FILE existed for four weeks while the TABLE held zero nonprofit rows,
--   and the comment said the vertical was closed the whole time. So this
--   file is applied and VERIFIED against the live table in the same pass —
--   writing a migration is not applying it.
--
-- ICONS are written as Postgres U& escapes rather than literal emoji.
--   The `icon` column is NOT NULL and holds emoji, and this file travels
--   through a PowerShell/JSON round-trip on its way to the Management API,
--   which mangles multi-byte literals. An escape is plain ASCII on the
--   wire and lands as the right codepoint.
--
-- IDEMPOTENT, ADDITIVE, NON-DESTRUCTIVE.
--   ON CONFLICT DO NOTHING on the (business_type, module_slug) key — a
--   re-run is a no-op and will never overwrite a curated row. No existing
--   data is read or modified.

-- ─── ecommerce ──────────────────────────────────────────────────────
-- The unit is an ORDER that has to be picked, packed and shipped. Stock
-- runs out, a carrier owns the delivery date, and a return is routine.

INSERT INTO public.business_type_module_blueprint
    (business_type, module_slug, module_name, icon, description, schema,
     tier, maturity_stage, sort_order, archetype, reason)
VALUES
('ecommerce', 'orders', 'Orders', U&'\+01F6D2',
 'Paid through packed to delivered — the spine of the store.',
 '{"views": ["list", "board"], "default_view": "list", "board_column": "status",
   "default_sort": "created_at",
   "fields": [
     {"name": "contact_id", "type": "contact_link", "label": "Customer"},
     {"name": "order_number", "type": "text", "label": "Order #"},
     {"name": "items", "type": "textarea", "label": "Items"},
     {"name": "order_total", "type": "number", "label": "Order total"},
     {"name": "status", "type": "select", "label": "Status",
      "options": ["paid", "packed", "shipped", "delivered", "returned"]},
     {"name": "tracking_number", "type": "text", "label": "Tracking"},
     {"name": "ship_by", "type": "date", "label": "Ship by"}
   ]}'::jsonb,
 'core', 'launching', 1, 'work_pipeline',
 'An order is not a booking. Without this the store has no place to see what is paid but not yet shipped.'),

('ecommerce', 'products', 'Products', U&'\+01F4E6',
 'The catalog, with the stock level beside each item.',
 '{"views": ["list"], "default_view": "list", "default_sort": "created_at",
   "fields": [
     {"name": "name", "type": "text", "label": "Product"},
     {"name": "sku", "type": "text", "label": "SKU"},
     {"name": "price", "type": "number", "label": "Price"},
     {"name": "stock_on_hand", "type": "number", "label": "Stock on hand"},
     {"name": "reorder_point", "type": "number", "label": "Reorder at"},
     {"name": "supplier", "type": "text", "label": "Supplier"},
     {"name": "status", "type": "select", "label": "Status",
      "options": ["active", "low_stock", "out_of_stock", "discontinued"]}
   ]}'::jsonb,
 'core', 'launching', 2, NULL,
 'reorder_point exists so the store reorders against lead time rather than against zero — the stock-out is the expensive failure, not the carrying cost.'),

('ecommerce', 'returns', 'Returns', U&'\+01F501',
 'What comes back, and why.',
 '{"views": ["list", "board"], "default_view": "list", "board_column": "status",
   "default_sort": "created_at",
   "fields": [
     {"name": "contact_id", "type": "contact_link", "label": "Customer"},
     {"name": "order_number", "type": "text", "label": "Order #"},
     {"name": "reason", "type": "select", "label": "Reason",
      "options": ["damaged", "wrong_item", "not_as_described", "changed_mind", "arrived_late"]},
     {"name": "status", "type": "select", "label": "Status",
      "options": ["requested", "approved", "received", "refunded", "declined"]},
     {"name": "refund_amount", "type": "number", "label": "Refund"}
   ]}'::jsonb,
 'core', 'launching', 3, 'work_pipeline',
 'Returns are a cost of selling online, not a failure. Logging the REASON is what turns them into product feedback instead of noise.'),

('ecommerce', 'suppliers', 'Suppliers', U&'\+01F69A',
 'Who you buy from, and how long they take.',
 '{"views": ["list"], "default_view": "list", "default_sort": "created_at",
   "fields": [
     {"name": "name", "type": "text", "label": "Supplier"},
     {"name": "contact_email", "type": "text", "label": "Contact"},
     {"name": "lead_time_days", "type": "number", "label": "Lead time (days)"},
     {"name": "minimum_order", "type": "number", "label": "Minimum order"},
     {"name": "notes", "type": "textarea", "label": "Notes"}
   ]}'::jsonb,
 'core', 'launching', 4, NULL,
 'lead_time_days is the number the reorder point is computed against; without it "reorder at" is a guess.'),

-- ─── saas ───────────────────────────────────────────────────────────
-- The money is subscribed rather than sold once. Churn is decided weeks
-- before the renewal that reveals it, and usage is the leading indicator.

('saas', 'accounts', 'Accounts', U&'\+01F511',
 'Trial through active, past-due and churned.',
 '{"views": ["list", "board"], "default_view": "list", "board_column": "status",
   "default_sort": "created_at",
   "fields": [
     {"name": "contact_id", "type": "contact_link", "label": "Primary contact"},
     {"name": "company", "type": "text", "label": "Company"},
     {"name": "plan", "type": "text", "label": "Plan"},
     {"name": "status", "type": "select", "label": "Status",
      "options": ["trial", "active", "past_due", "churned"]},
     {"name": "mrr", "type": "number", "label": "MRR"},
     {"name": "renewal_date", "type": "date", "label": "Renews"},
     {"name": "last_active", "type": "date", "label": "Last active"}
   ]}'::jsonb,
 'core', 'launching', 1, 'work_pipeline',
 'last_active sits beside renewal_date on purpose: usage leads and billing lags, so an account that stopped logging in is a renewal that has already failed.'),

('saas', 'demos', 'Demos', U&'\+01F4C5',
 'Let prospects book time without emailing you first.',
 '{"views": ["list"], "default_view": "list", "default_sort": "created_at",
   "fields": [
     {"name": "contact_id", "type": "contact_link", "label": "Prospect"},
     {"name": "company", "type": "text", "label": "Company"},
     {"name": "scheduled_at", "type": "date", "label": "Scheduled"},
     {"name": "use_case", "type": "textarea", "label": "What they came to do"},
     {"name": "outcome", "type": "select", "label": "Outcome",
      "options": ["scheduled", "held", "no_show", "won", "lost"]}
   ]}'::jsonb,
 'core', 'launching', 2, 'booking_calendar',
 'use_case is captured before the call because a demo that tours the product loses to one that does the job the prospect came for.'),

('saas', 'onboarding', 'Onboarding', U&'\+01F680',
 'Getting a new account to the thing it signed up to do.',
 '{"views": ["list", "board"], "default_view": "list", "board_column": "status",
   "default_sort": "created_at",
   "fields": [
     {"name": "contact_id", "type": "contact_link", "label": "Account"},
     {"name": "plan", "type": "text", "label": "Plan"},
     {"name": "kickoff_date", "type": "date", "label": "Kickoff"},
     {"name": "first_value_at", "type": "date", "label": "Reached first value"},
     {"name": "status", "type": "select", "label": "Status",
      "options": ["not_started", "in_progress", "activated", "stalled"]}
   ]}'::jsonb,
 'core', 'launching', 3, 'work_pipeline',
 'Churn is decided in the first weeks. first_value_at is the date this module exists to record — an account that never reaches it has already gone.'),

('saas', 'feature-requests', 'Feature Requests', U&'\+01F4A1',
 'What customers ask for, and who asked.',
 '{"views": ["list"], "default_view": "list", "default_sort": "created_at",
   "fields": [
     {"name": "title", "type": "text", "label": "Request"},
     {"name": "contact_id", "type": "contact_link", "label": "Asked by"},
     {"name": "detail", "type": "textarea", "label": "Detail"},
     {"name": "status", "type": "select", "label": "Status",
      "options": ["open", "planned", "shipped", "declined"]}
   ]}'::jsonb,
 'core', 'launching', 4, NULL,
 'Recording WHO asked is what lets a renewal conversation reference the thing they wanted, and what stops a roadmap being argued from memory.')

ON CONFLICT (business_type, module_slug) DO NOTHING;

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────
-- Expect 4 ecommerce rows and 4 saas rows, all tier='core', and the icons
-- to be real single-codepoint emoji rather than a mangled byte sequence.
SELECT business_type,
       count(*)                                   AS modules,
       count(*) FILTER (WHERE tier = 'core')      AS core_modules,
       count(DISTINCT icon)                       AS distinct_icons,
       bool_and(length(icon) = 1)                 AS icons_are_single_codepoint,
       string_agg(module_slug, ', ' ORDER BY sort_order) AS slugs
FROM public.business_type_module_blueprint
WHERE business_type IN ('ecommerce', 'saas')
GROUP BY business_type
ORDER BY business_type;
