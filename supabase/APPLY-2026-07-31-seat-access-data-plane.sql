-- APPLY-2026-07-31-seat-access-data-plane.sql
-- Kevin's ruling 2026-07-31 ("make the path happen", access matrix
-- approved explicitly): an invited team seat must be able to actually
-- WORK in the business, not just see its name. Before this, of ~101
-- RLS tenant tables only businesses (read) and chief_conversations had
-- member policies — an accepted seat got a business in their switcher
-- with empty rooms behind it, and the door into a client's account
-- (client invites Kevin as a seat) led nowhere.
--
-- Model (matches business_users_router's multi-role v2 ladder,
-- viewer < member < manager < admin < owner):
--   is_business_member  (any ACTIVE seat, incl. viewer)  → READ
--   is_business_writer  (member/manager/admin seat)      → WRITE
-- Owner keeps full access via each table's existing owner policies.
-- Policies are additive (permissive OR) — nothing existing narrows.
--
-- The grant list is EXPLICIT, not information_schema-driven, so this
-- file is the audit record of exactly what a seat can touch. Untouched
-- (owner/service-role only): billing + metering internals (credit_ledger,
-- usage_*, api_usage, stripe_webhook_events, product_events), credentials
-- (connector_credentials, quickbooks_connections, social_accounts,
-- sms_bindings, plaid_items, mcp_* / push_subscriptions), agent surfaces
-- (agent_queue, agent_runs), audit/undo logs, gl_sync_queue, inference
-- internals, workflow_*, support_tickets + seat/collab tables (own
-- policies), and the RESTRICTED clinical class (restricted_module_entries
-- + its access log) which stays outside blanket seat access by design.

create or replace function public.is_business_writer(b_id uuid)
returns boolean
language sql stable security definer
set search_path = public
as $$
  select exists (select 1 from public.business_users bu
                 where bu.business_id = b_id and bu.user_id = auth.uid()
                   and bu.status = 'active'
                   and bu.role in ('member', 'manager', 'admin'));
$$;
revoke all on function public.is_business_writer(uuid) from public;
grant execute on function public.is_business_writer(uuid) to authenticated;

do $$
declare
  -- Operational CRUD the app performs directly via PostgREST: a working
  -- seat (member+) reads AND writes these.
  write_tables text[] := array[
    'bills', 'business_budgets', 'business_customers', 'business_expenses',
    'business_profiles', 'business_sites', 'campaigns', 'category_rules',
    'chart_of_accounts', 'chief_notifications', 'contacts', 'contractors',
    'custom_modules', 'customer_ledger', 'design_feedback', 'email_replies',
    'events', 'foundation_documents', 'foundation_progress',
    'growth_milestones', 'growth_objectives', 'intake_forms', 'invoices',
    'module_entries', 'module_specs', 'offerings', 'orders',
    'plaid_transactions', 'practitioner_rules', 'products', 'sessions',
    'site_chat_history', 'site_content_overrides', 'strategy_tracks',
    'tasks', 'time_entries'];
  -- Visible to every active seat (viewer included); writes stay with the
  -- owner and the backend's service-role paths.
  read_only_tables text[] := array[
    'academy_courses', 'academy_enrollments', 'academy_lessons',
    'accounting_periods', 'campaign_sends', 'chief_actions',
    'chief_activity', 'chief_bookkeeping_proposals', 'chief_jobs',
    'chief_learning_signals', 'chief_memories', 'chief_patterns',
    'chief_playbooks', 'chief_proposals', 'chief_scheduled_actions',
    'chief_templates', 'coa_external_mappings', 'connectors',
    'design_rationales', 'gl_divergence_alarms', 'insights',
    'journal_entries', 'ledger_entries', 'outbound_transfers',
    'period_edit_overrides', 'plaid_accounts', 'quickbooks_pushed_entries',
    'rule_runs', 'sms_consents', 'sms_keywords', 'sms_messages',
    'sms_opt_outs'];
  t text;
begin
  foreach t in array (write_tables || read_only_tables) loop
    execute format('drop policy if exists tenant_member_read on public.%I', t);
    execute format(
      'create policy tenant_member_read on public.%I for select '
      'to authenticated using (public.is_business_member(business_id))', t);
  end loop;
  foreach t in array write_tables loop
    execute format('drop policy if exists tenant_writer_write on public.%I', t);
    execute format(
      'create policy tenant_writer_write on public.%I for all '
      'to authenticated using (public.is_business_writer(business_id)) '
      'with check (public.is_business_writer(business_id))', t);
  end loop;
end $$;

-- Verify (expected: 68 tenant_member_read, 36 tenant_writer_write):
--   select policyname, count(*) from pg_policies
--   where policyname in ('tenant_member_read','tenant_writer_write')
--   group by policyname;
