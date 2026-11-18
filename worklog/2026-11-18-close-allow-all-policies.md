---
title: Twenty tenant tables were open to the public anon key. The migration that closes them, and the server paths that leaned on the hole
date: 2026-11-18
agent: Claude Code (Claude Fable 5.2)
asked: 'Found while reading production''s policy catalog for the giving work, 2026-11-18. Kevin the same day: "yes fix and build what is needed."'
status: waiting on Kevin
prs: []
migrations: ["supabase/APPLY-2026-11-18-close-allow-all-policies.sql (NOT APPLIED; deploy the server first, then run it)"]
left_undone:
  - "NOT APPLIED. The hole is open on production until Kevin runs supabase/APPLY-2026-11-18-close-allow-all-policies.sql, AFTER the server in this pull request is deployed. Applied before the code, every public site and storefront page loses its products."
  - "Not pushed: local commits on the branch close-allow-all-policies, for the parent session to have reviewed and open as a pull request."
  - "THE OTHER ALLOW-ALL POLICIES ON PRODUCTION ARE NOT TOUCHED (list below): the Embrace the Shift module's ets_* tables, of which four are open for every command to anyone (ets_events, ets_event_tiers, ets_registrations, ets_event_files: 'Allow all for anon') and five more are readable by anyone (inquiries, emails, engagements, sessions log, signatures). They need their own pass: the module's pages read them straight from the browser, some of them signed out."
  - "Nothing here was run against a real Postgres or PostgREST. The SQL is checked as text; the policies' behaviour is reasoned from the catalog read on 2026-11-18."
  - "The eight per-command policies on site_chat_history and site_content_overrides were made in the dashboard. Their exact USING / WITH CHECK text was not read (only that each holds a literal true), so the rollback recreates the dashboard template's shape."
  - "A Viewer office login loses direct writes to tasks, products, foundation_progress, foundation_documents and site_content_overrides through its own JWT (Chief's `_sb`, the app's own calls). It only ever had them through the allow-all policy; the seat policies give a Viewer a read."
  - "An accountant collaborator has no policy on business_expenses, tasks or products, so the app's direct reads of those come back empty for one. Invoices have been that way since 2026-07-13; an accountant's books go through the server's routes."
  - "The frontend repo's older supabase/*-migration.sql files (tasks, products, chief-patterns, living-growth-system, marketing-leads, practitioner-profile, foundation-track, business-expenses, site-content-overrides, schema-audit-fix) recreate these policies if anyone runs them again. Only this repo's two were given a warning line; the frontend's were not touched."
decisions:
  - "The owner is never left with less than the owner's own staff. Seven tables had seat policies (tenant_member_read / tenant_writer_write) and no owner policy at all: the allow-all one was the owner's only way in. Each gets an owner policy of the same reach the seats already hold (business_owner_access where seats write, business_owner_read where seats read), through is_business_owner. No new reach for anyone but the owner on the owner's own business."
  - "sms_bindings had nothing but the allow-all policy, and Messages (SmsHub) lists who texted the keyword from it in the browser. It gets a read for the owner AND for office logins, and no write for either. APPLY-2026-07-31-seat-access-data-plane.sql named sms_bindings as owner/service only, but office logins have read it all along through the allow-all policy and the texting room is theirs to work; taking it away would empty that list for church staff. Dropping the one tenant_member_read line makes it owner-only."
  - "anon is revoked only on the sixteen tables no browser reads directly. tasks, products, business_expenses and sms_bindings keep anon's grants: the app falls back to the anon bearer when a session lapses, and an empty list from the policies is a better failure than a permission error on those four screens."
  - "Server paths were moved to the service role only where the row is the server's own or the caller is already checked: a public site's products (bounded to the business the slug resolved to), Chief's learned patterns (pinned to the chat's business), and the business owner's practitioner profile (the owner id comes from the business row the caller passed the access check for)."
  - "site_chat_history and module_specs keep their user-JWT server paths; the owner policy covers the owner. The director's refine routes say they have no owner gate of their own, so writing them as the server would have widened them."
  - "A guard test refuses any migration dated 2026-11-18 or later that creates a policy with a literal-true USING or WITH CHECK, unless the file and policy are on an allow-list with a reason. It is stricter than 'on a table with a business_id column': a public reference table goes on the list with why."
related: [2026-11-18-one-money-gate.md]
---
Production's `pg_policies`, read 2026-11-18: twenty tenant tables have RLS
on, a scoped policy or two, and beside them a PERMISSIVE policy whose USING
and WITH CHECK are literally `true`, TO public. Postgres ORs permissive
policies, so that one cancels the rest (docs/RLS_MODEL.md, Rule 3). `anon`
holds select and delete on all twenty. The anon key ships in the app bundle,
so anyone with it could read, change or delete every business's rows there:
tasks (19 rows), the phone numbers bound to each church's texting
(sms_bindings, 40), who opted out, Chief's learned patterns (29), foundation
progress (196), module proposals (94), site chat and content overrides,
practitioner profiles, products, growth plans, connectors, workflow
definitions, marketing leads, and one expense row. For a church,
`business_expenses` was open to the public even though its restrictive money
policy applies to every signed-in login: that policy is TO authenticated, and
anon is not.

## The twenty, one by one

"Server" = which key each server path uses. "User JWT" = the helper forwards
the signed-in person's token (chief `_sb`, brand_engine `_sb_get`,
foundation_agent, the director and override stores), service role when no
one is signed in. "App" = the frontend's own PostgREST calls
(`supabaseQuery` / `useSupabaseQuery`), which send the user's JWT once
signed in. No signed-out page of the app reads any of the twenty; public
sites are rendered by the server.

| table | server paths | app paths | left after the drop | verdict |
|---|---|---|---|---|
| business_expenses | service everywhere (chief_expense_actions, church_checks, church_help, expense_categories, giving_deposits, gl_engine, reports_engine) | RevenueExpenses, RevenueAnalytics, signed in | owner all; seats read, Member+ write; the church money policy over all of them | DROP |
| chief_patterns | chief `_sb` (user JWT): five reads, two writes | none | owner all; seats read | DROP, and the two writes move to the service role (an office login's would be refused) |
| connector_action_log | workflow_engine, service | none | nothing: server-only | DROP, revoke anon |
| connectors | workflow_engine, service | none | seats read; + owner read (new) | DROP + business_owner_read, revoke anon |
| foundation_documents | foundation_agent / foundation_router (user JWT, service when none) | none (through the server) | owner all; seats read, Member+ write | DROP, revoke anon |
| foundation_progress | foundation_agent (user JWT, service when none) | none (through the server) | owner all; seats read, Member+ write | DROP, revoke anon |
| growth_milestones | growth_objective_agent / router, workflow_engine, service | none (GrowthTimeline asks the server) | seats read, Member+ write; + owner all (new) | DROP + business_owner_access, revoke anon |
| growth_objectives | growth_objective_agent / router, service | none | seats read, Member+ write; + owner all (new) | DROP + business_owner_access, revoke anon |
| marketing_leads | marketing_pages (the public lead form), lead_admin, platform_console, platform_chief_actions, launch_access, marketing_outcomes: service | none (LeadsAdminPanel asks the server) | nothing: server-only. No business_id; it is the platform's own list of names and emails | DROP, revoke anon |
| module_specs | business_blueprint, module_spec_generator, module_spec_router: service; chief_module_actions: one read under the user JWT (reject a proposal) | none | seats read, Member+ write; + owner all (new, or the owner's own "reject" would say the proposal isn't there) | DROP + business_owner_access, revoke anon |
| practitioner_profiles | practitioner_profile_agent, voice_depth_agent, agent_site, availability, booking widget, brain, marketing, knowledge, rail, ein_prep, academy, outside_calendar: service; brand_engine.get_bundle, chief_availability, booking_rehearsal: user JWT | none (BrandHub writes through the server) | the owner's own row (owner_full_access). Keyed by owner_id, so no seat policy fits | DROP, revoke anon, and the three user-JWT reads move to the service role (an office login's would come back empty) |
| products | chief `_sb` and brand_engine `_sb_get` (user JWT, service when none); stripe_proxy, design_coach and the other readers: service; public_site: SIX READS WITH THE ANON KEY | ProductCatalog, CourseStudio, InvoiceComposer, ShowcaseShelf, MediaLibrary, CheckoutSheet, CatalogPage, the command palette: signed in | owner all; seats read, Member+ write | DROP, and public_site's six reads move to the service role FIRST |
| site_chat_history | director refine store (user JWT, service when none) | none | seats read, Member+ write; + owner all (new, or the owner's own chat with the site director stops saving) | DROP + business_owner_access, revoke anon |
| site_content_overrides | override store (user JWT, service when none; one patch already service) | none | owner all; seats read, Member+ write | DROP, revoke anon |
| sms_bindings | sms_routing, sms_alerts, text_room: service | SmsHub lists who texted the keyword, signed in | + owner read, + office-login read (both new); no write | DROP + business_owner_read + tenant_member_read |
| sms_keywords | sms_routing, chief_sms_actions, site_composer: service | none | seats read; + owner read (new) | DROP + business_owner_read, revoke anon |
| sms_opt_outs | sms_routing, sms_service, sms_alerts, text_room, new_here, contacts import, chief_sms_actions, hermes: service | none | seats read; + owner read (new). Nobody but the server can add or clear a STOP | DROP + business_owner_read, revoke anon |
| tasks | chief `_sb` (user JWT, service when none); the church modules, dev_bridge, ops_desk, member portal, rules engine: service | TasksPanel, ProjectDeck, CalendarView, Home, Needs you, Projects: signed in | owner all; seats read, Member+ write | DROP |
| workflow_definitions | workflow_engine, growth_objective_agent, module_spec_generator: service | none | nothing: server-only (rows with no business are the global templates) | DROP, revoke anon |
| workflow_runs | workflow_engine, workflow_router, growth_objective_router: service | none | nothing: server-only | DROP, revoke anon |

## The server changes that go first

- `public_site.py`: the six `products` reads behind a public site, storefront
  and booking page used the anon key. They are read as the server now, each
  bounded to the business the public slug resolved to.
- `chief_of_staff._upsert_pattern`: Chief's two writes of what it has learned
  are the server's, and the update is pinned to the chat's business.
- `brand_engine.get_bundle`, `chief_availability`, `booking_rehearsal`: the
  business owner's practitioner profile (the bundle's name and title, the
  timezone the scheduling check falls back to) is read as the server.

## The other allow-all policies on production (not changed here)

- **Embrace the Shift** (the frontend's `src/modules/embrace-the-shift`, its
  own event and enquiry program; its pages read these straight from the
  browser):
  - `ets_events`, `ets_event_tiers`, `ets_registrations`, `ets_event_files`:
    "Allow all for anon", every command. Anyone can change or delete an event,
    its prices and its registrations. Recommend: public read of a published
    event and a public insert of a registration only, everything else the
    signed-in owner's.
  - `ets_inquiries` (public insert and public read), `ets_registrations`
    (public insert, "read own" that is in fact everyone), `ets_emails`,
    `ets_engagements`, `ets_sessions_log`, `ets_signatures`, `ets_agent_log`:
    readable by anyone. Enquiries, signatures and email are people's
    details. Recommend: keep the two public inserts, close every read to the
    signed-in owner.
- `sol_market_prices`, `sol_economic_indicators`, `sol_news_items`,
  `sol_shift_scores`: public market and news data, read-only. Public by
  design; leave.
- `state_filing_data`, `business_type_archetypes`,
  `business_type_module_blueprint`: reference tables with no business's rows,
  read-only. Leave. `action_types` is read-only to signed-in logins. Leave.

Tests: `__tests__/test_close_allow_all_policies.py` (14: the migration as text, the rollback, the ledger, the guard
against a new allow-all policy, and the four server paths). Four deliberate breaks of the SQL (a drop left out, anon
revoked on a table the app reads, an allow-all policy added, an extra drop) each made it fail. The 192 test files that
touch the changed modules, the ledger, the worklog or the migration scans: 6,207 passed. Seven test fakes now also
stand in for the server-key reads (`_owner_tz_get`, public_site's `_sb_service`).

## After the first CI run: the reads fail soft, and go through seams the tests already hold

The first push failed parts 1, 3 and 4 with one error everywhere:
`sb_headers_service requires SUPABASE_SERVICE_ROLE_KEY`. CI's test parts set
no Supabase key at all and run each test file in its own worker; the local
run that had passed shares one process, where (most likely) an earlier file had left a key
in the environment. `brand_engine._owner_profile` called
`sb_clients.sb_get_as_service` directly, which raises when the key is
missing, so every test that builds a brand bundle behind a stand-in for
`brand_engine._sb_get` broke, and so would a real bundle on a server with no
key.

- `brand_engine._owner_profile` reads through `_sb_get`, the module's one
  read seam, which reads `/practitioner_profiles?owner_id=eq.` as the server
  (`_SERVER_READ_PATHS`: read only, `_sb_patch` is untouched). A profile that
  cannot be read is no profile; the bundle is built without the practitioner.
  No test needed editing: their stand-ins for `_sb_get` cover it.
- `public_site._site_products(client, biz_id, query)` is the one reader for a
  public page's products. It pins the business itself and never takes the
  page down: a refused read, a network failure or a missing service key is a
  page with no products and a line in the log. Before this, five of the six
  reads (anon key or not) were not guarded where they were made.
- `chief_availability._owner_tz_get` answers None when the server read cannot
  be made, so the check says "unavailable" in its own words, never a raw
  error and never a guessed timezone.
- Nothing falls back to the anon key, and CI's environment is unchanged.

The whole suite, the way CI runs it (four parts from
`scripts/shard_tests.py`, one worker per file group, no Supabase key or URL
in the environment): 24,658 passed. Five tests failed, all of them
wall-clock assertions in Chief's timing files
(`test_chief_turn_timing`, `test_chief_turn_latency`,
`test_chief_quick_plan_integration`, `test_chief_invoice_early_read`); the
same ones fail the same way on today's main when those files run side by side
on this machine, and all pass on both when run one file at a time.

