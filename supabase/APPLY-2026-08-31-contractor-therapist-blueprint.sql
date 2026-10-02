-- APPLY-2026-08-31-contractor-therapist-blueprint.sql
-- RUN ONCE (whole file).
--
-- Module blueprints for 'contractor' and 'therapist'.
--
-- WHY THESE TWO WERE MISSING
--   Both shipped as full verticals in July 2026 — picker card, Chief
--   profile, terminology, contract framing, autopilot — and neither ever
--   got a business_type_module_blueprint row. module_blueprint_agent
--   .provision_modules() walks that table and creates the core module set;
--   with no rows it returns [] and provisions NOTHING, so both picker cards
--   lead to an empty workspace.
--
--   Nobody is broken today: the live businesses table currently holds no
--   contractor and no therapist. This is latent and fires on the next
--   signup from either — which is exactly the shape of the nonprofit gap
--   recorded in vertical_registry.KNOWN_GAPS, where the blueprint FILE
--   existed for four weeks while the TABLE held zero rows and a comment
--   claimed the vertical was closed.
--
-- THE THERAPIST ROWS AND THE HIPAA LINE — read before editing
--   vertical_scope.py refuses any module whose name contains 'diagnosis',
--   'symptom', 'medication', 'progress note', 'medical record', 'phi' and
--   a dozen more. The therapist vertical launched with clinical records
--   deliberately OUT OF SCOPE so the platform never becomes a HIPAA
--   business associate.
--
--   So these four modules are scheduling, billing and practice admin, and
--   nothing else. In particular `superbills` records that a superbill was
--   ISSUED and for how much — it does NOT carry CPT or ICD-10 codes, even
--   though a real superbill does, because those are the clinical half.
--   `insurance` tracks the payer and when coverage was last verified, not
--   a member identifier. A practitioner keeps the clinical record in their
--   EHR; this is the money and the calendar around it.
--
--   If a future edit adds a clinical field here, vertical_scope will still
--   refuse the equivalent module at the CREATE path while this table
--   provisions it anyway — the two would disagree, and this table would
--   win. Do not put it back.
--
-- ICONS are Postgres U& escapes rather than literal emoji: the file travels
--   through a PowerShell/JSON round-trip that mangles multi-byte literals.
--   The verify asserts length(icon) = 1.
--
-- IDEMPOTENT, ADDITIVE, NON-DESTRUCTIVE.
--   ON CONFLICT on the (business_type, module_slug) primary key does
--   nothing, so a re-run is a no-op and never overwrites a curated row.

INSERT INTO public.business_type_module_blueprint
    (business_type, module_slug, module_name, icon, description, schema,
     tier, maturity_stage, sort_order, archetype, reason)
VALUES

-- ─── contractor ─────────────────────────────────────────────────────
-- A JOB at a customer site: quoted before it starts, materials and labor
-- billed separately, deposit up front, change orders when scope moves.

('contractor', 'estimates', 'Estimates', U&'\+01F4CB',
 'What you bid, and whether it was accepted.',
 '{"views": ["list", "board"], "default_view": "list", "board_column": "status",
   "default_sort": "created_at",
   "fields": [
     {"name": "contact_id", "type": "contact_link", "label": "Customer"},
     {"name": "job_address", "type": "text", "label": "Job address"},
     {"name": "scope", "type": "textarea", "label": "Scope of work"},
     {"name": "materials_estimate", "type": "number", "label": "Materials"},
     {"name": "labor_estimate", "type": "number", "label": "Labor"},
     {"name": "total", "type": "number", "label": "Total"},
     {"name": "status", "type": "select", "label": "Status",
      "options": ["draft", "sent", "accepted", "declined", "expired"]},
     {"name": "valid_until", "type": "date", "label": "Valid until"}
   ]}'::jsonb,
 'core', 'launching', 1, 'work_pipeline',
 'The bid is not the sale. Materials and labor are separate fields because job costing and, in most states, sales tax both turn on the split — and because a bid that itemises what a cheaper bid left out wins more often than one that lowers the number.'),

('contractor', 'jobs', 'Jobs', U&'\+01F528',
 'Work that was won, from scheduled through complete.',
 '{"views": ["list", "board"], "default_view": "list", "board_column": "status",
   "default_sort": "created_at",
   "fields": [
     {"name": "contact_id", "type": "contact_link", "label": "Customer"},
     {"name": "job_address", "type": "text", "label": "Job address"},
     {"name": "scope", "type": "textarea", "label": "Scope of work"},
     {"name": "start_date", "type": "date", "label": "Start"},
     {"name": "status", "type": "select", "label": "Status",
      "options": ["scheduled", "in_progress", "blocked", "complete"]},
     {"name": "deposit_received", "type": "number", "label": "Deposit received"},
     {"name": "balance_due", "type": "number", "label": "Balance due"}
   ]}'::jsonb,
 'core', 'launching', 2, 'work_pipeline',
 'deposit_received sits on the job rather than in an invoice because ordering materials before the deposit clears is how a trade business ends up financing its customer.'),

('contractor', 'change-orders', 'Change Orders', U&'\+01F4DD',
 'Scope that moved after the price was agreed.',
 '{"views": ["list"], "default_view": "list", "default_sort": "created_at",
   "fields": [
     {"name": "job", "type": "text", "label": "Job"},
     {"name": "contact_id", "type": "contact_link", "label": "Customer"},
     {"name": "description", "type": "textarea", "label": "What changed"},
     {"name": "price", "type": "number", "label": "Price"},
     {"name": "status", "type": "select", "label": "Status",
      "options": ["proposed", "approved", "declined"]},
     {"name": "approved_date", "type": "date", "label": "Approved"}
   ]}'::jsonb,
 'core', 'launching', 3, NULL,
 'The single most-lost money in the trade: a change agreed verbally on site is the one that does not get paid. This module exists so it is priced and recorded BEFORE the work, not discovered at invoicing.'),

('contractor', 'visits', 'Site Visits', U&'\+01F690',
 'Estimate calls, work days, inspections and callbacks.',
 '{"views": ["list"], "default_view": "list", "default_sort": "created_at",
   "fields": [
     {"name": "contact_id", "type": "contact_link", "label": "Customer"},
     {"name": "job_address", "type": "text", "label": "Address"},
     {"name": "scheduled_at", "type": "date", "label": "Scheduled"},
     {"name": "purpose", "type": "select", "label": "Purpose",
      "options": ["estimate", "work", "inspection", "callback"]},
     {"name": "notes", "type": "textarea", "label": "Notes"}
   ]}'::jsonb,
 'core', 'launching', 4, 'booking_calendar',
 'A visit is not an appointment with a client in an office — it has an address and a purpose, and the callback purpose is what makes warranty work visible instead of invisible.'),

('contractor', 'materials', 'Materials', U&'\+01F9F1',
 'What was ordered for which job, and when it lands.',
 '{"views": ["list"], "default_view": "list", "default_sort": "created_at",
   "fields": [
     {"name": "job", "type": "text", "label": "Job"},
     {"name": "supplier", "type": "text", "label": "Supplier"},
     {"name": "item", "type": "text", "label": "Item"},
     {"name": "quantity", "type": "number", "label": "Quantity"},
     {"name": "cost", "type": "number", "label": "Cost"},
     {"name": "expected_date", "type": "date", "label": "Expected"},
     {"name": "status", "type": "select", "label": "Status",
      "options": ["needed", "ordered", "received", "returned"]}
   ]}'::jsonb,
 'core', 'launching', 5, NULL,
 'Materials tie to a job so cost lands against the work it funded rather than into a general expense bucket, which is what makes a job profitable or not on paper.'),

-- ─── therapist ──────────────────────────────────────────────────────
-- Scheduling, billing and practice admin ONLY. No clinical content — see
-- the header. vertical_scope refuses the clinical equivalents at the
-- module-create path and these must not contradict it.

('therapist', 'sessions', 'Sessions', U&'\+01F4C5',
 'The calendar and what each session was billed at.',
 '{"views": ["list"], "default_view": "list", "default_sort": "created_at",
   "fields": [
     {"name": "contact_id", "type": "contact_link", "label": "Client"},
     {"name": "scheduled_at", "type": "date", "label": "Scheduled"},
     {"name": "session_type", "type": "select", "label": "Type",
      "options": ["intake", "individual", "couple", "family", "group"]},
     {"name": "status", "type": "select", "label": "Status",
      "options": ["scheduled", "held", "no_show", "late_cancel", "cancelled"]},
     {"name": "fee", "type": "number", "label": "Fee"}
   ]}'::jsonb,
 'core', 'launching', 1, 'booking_calendar',
 'Deliberately carries NO clinical field — no note, no diagnosis, no content. session_type is a billing and scheduling distinction, not a clinical one. The no_show and late_cancel statuses exist because those fees are taxable revenue that otherwise goes unrecorded.'),

('therapist', 'waitlist', 'Waitlist', U&'\+00231B',
 'Who could take a slot that opens today.',
 '{"views": ["list"], "default_view": "list", "default_sort": "created_at",
   "fields": [
     {"name": "contact_id", "type": "contact_link", "label": "Client"},
     {"name": "preferred_times", "type": "text", "label": "Preferred times"},
     {"name": "added_date", "type": "date", "label": "Added"},
     {"name": "status", "type": "select", "label": "Status",
      "options": ["waiting", "offered", "scheduled", "removed"]}
   ]}'::jsonb,
 'core', 'launching', 2, NULL,
 'A cancelled hour that is not refilled is revenue that cannot be recovered — the slot does not carry forward. A short waitlist that can be texted same-day is worth more to a practice than a longer roster.'),

('therapist', 'insurance', 'Insurance', U&'\+01F4C4',
 'Payer, plan, and when coverage was last checked.',
 '{"views": ["list"], "default_view": "list", "default_sort": "created_at",
   "fields": [
     {"name": "contact_id", "type": "contact_link", "label": "Client"},
     {"name": "payer", "type": "text", "label": "Payer"},
     {"name": "plan", "type": "text", "label": "Plan"},
     {"name": "coverage_verified_date", "type": "date", "label": "Coverage verified"},
     {"name": "copay", "type": "number", "label": "Copay"},
     {"name": "status", "type": "select", "label": "Status",
      "options": ["unverified", "active", "lapsed", "self_pay"]}
   ]}'::jsonb,
 'core', 'launching', 3, NULL,
 'Claims denied on eligibility usually fail on stale coverage data rather than anything about the care, so coverage_verified_date is the field that earns this module. No member identifier and no codes — payer and plan are billing admin; the rest belongs in the EHR.'),

('therapist', 'superbills', 'Superbills', U&'\+01F9FE',
 'Which superbills were issued, for how much, and whether they were reimbursed.',
 '{"views": ["list"], "default_view": "list", "default_sort": "created_at",
   "fields": [
     {"name": "contact_id", "type": "contact_link", "label": "Client"},
     {"name": "date_of_service", "type": "date", "label": "Date of service"},
     {"name": "amount", "type": "number", "label": "Amount"},
     {"name": "issued_date", "type": "date", "label": "Issued"},
     {"name": "status", "type": "select", "label": "Status",
      "options": ["issued", "submitted_by_client", "reimbursed", "denied"]}
   ]}'::jsonb,
 'core', 'launching', 4, NULL,
 'Records that a superbill was ISSUED and for how much. A real superbill carries CPT and ICD-10 codes; those are the clinical half and are deliberately absent, because storing them is the line the vertical was narrowed to avoid. date_of_service is here because a claim paid months later still belongs to the session date.')

ON CONFLICT (business_type, module_slug) DO NOTHING;

notify pgrst, 'reload schema';

-- ─── Verify ─────────────────────────────────────────────────────────
-- Expect 5 contractor rows and 4 therapist rows, all core, single-codepoint
-- icons, and NO clinical vocabulary anywhere in the therapist rows.
SELECT business_type,
       count(*)                              AS modules,
       count(*) FILTER (WHERE tier='core')   AS core_modules,
       bool_and(length(icon) = 1)            AS icons_ok,
       string_agg(module_slug, ', ' ORDER BY sort_order) AS slugs
FROM public.business_type_module_blueprint
WHERE business_type IN ('contractor', 'therapist')
GROUP BY business_type
ORDER BY business_type;

-- The scope assertion, run as data rather than trusted to review.
SELECT count(*) AS therapist_rows_touching_clinical_vocabulary
FROM public.business_type_module_blueprint
WHERE business_type = 'therapist'
  AND lower(module_name || ' ' || coalesce(description,'') || ' ' || schema::text)
      ~ '(diagnos|symptom|medication|prescription|progress note|clinical note|session note|treatment plan|medical record|health record|protected health|psychotherap)';
