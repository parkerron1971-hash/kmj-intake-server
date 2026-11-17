-- businesses_server_columns_check.sql — did anyone use the businesses column
-- hole before supabase/APPLY-2026-11-17-businesses-server-columns.sql?
--
-- Read-only. Counts only: no id, name or email is selected anywhere. Run each
-- query on its own in the Supabase SQL editor (it shows the last result).
--
-- THE HOLE: until the migration, the app's login (authenticated) could PATCH
-- its own businesses row's server columns through PostgREST: comp_tier (any
-- plan, free), subscription_status / trial_ends_at / current_period_end,
-- subscription_plan, tier, the Stripe ids, in_the_clear, is_active,
-- entity_group_id, use_composer, attribution, created_at, and an office admin
-- could set owner_id to themselves. It could also INSERT a business directly.
--
-- WHAT NO RECORD EXISTS FOR: comps (POST /access/business/{id}/tier writes no
-- audit row and logs with logger.info, which Railway doesn't show) and Platform
-- Chief's extend_trial. So Q1 can't say "forged"; it says "doesn't look like
-- anything the server writes", and the numbers are for Kevin to hold against
-- the comps and trial extensions he gave. Q2 is the stronger signal: it counts
-- the statements the app's own roles actually ran.
--
-- Q1 — rows that don't look like anything the server writes (one row of counts)
with b as (
  select * from public.businesses where not coalesce(is_sample, false)
)
select
  (select count(*) from b)                                                     as businesses,
  -- Comps: only Kevin sets these. Compare with the comps he gave.
  (select count(*) from b where comp_tier is not null)                         as comped,
  (select coalesce(jsonb_object_agg(comp_tier, n), '{}'::jsonb)
     from (select comp_tier, count(*) as n from b where comp_tier is not null group by 1) x)
                                                                               as comped_by_plan,
  -- 'active' only ever comes from a Stripe subscription.
  (select count(*) from b where subscription_status = 'active' and stripe_subscription_id is null)
                                                                               as active_without_subscription,
  (select count(*) from b where subscription_status in ('past_due', 'unpaid', 'incomplete', 'paused')
                                and stripe_subscription_id is null)          as billing_state_without_subscription,
  -- A trial without a subscription is a no-card trial (its settings marker)
  -- or one Platform Chief extended; anything else is unexplained.
  (select count(*) from b where subscription_status = 'trialing' and stripe_subscription_id is null
                                and not (coalesce(settings, '{}'::jsonb) ? 'no_card_trial'))
                                                                               as trialing_without_subscription_or_marker,
  -- A subscription id no Stripe webhook ever named (webhook rows may be
  -- purged after 90 days: a live monthly subscription has newer events).
  (select count(*) from b where stripe_subscription_id is not null and not exists (
     select 1 from public.stripe_webhook_events e
      where e.business_id = b.id or e.raw -> 'data' -> 'object' ->> 'id' = b.stripe_subscription_id))
                                                                               as subscription_no_webhook_named,
  -- One Stripe id on more than one business (or owner).
  (select count(*) from (select stripe_subscription_id from b where stripe_subscription_id is not null
                          group by 1 having count(*) > 1) x)                   as subscription_ids_shared,
  (select count(*) from (select stripe_customer_id from b where stripe_customer_id is not null
                          group by 1 having count(distinct owner_id) > 1) x)   as customer_ids_across_owners,
  (select count(*) from (select stripe_account_id from b where stripe_account_id is not null
                          group by 1 having count(distinct owner_id) > 1) x)   as connect_accounts_across_owners,
  -- A Connect account the server never recorded: guard_financial_account_connection
  -- locks every account written since 2026-09-07, so this is an account set
  -- before then, or with that trigger off.
  (select count(*) from b where stripe_account_id is not null and not exists (
     select 1 from public.business_financial_account_locks l
      where l.business_id = b.id and l.stripe_account_id = b.stripe_account_id))
                                                                               as connect_account_not_locked,
  -- Stripe price ids start with price_.
  (select count(*) from b where subscription_plan is not null and subscription_plan not like 'price\_%')
                                                                               as plan_not_a_price_id,
  -- Dates no plan produces: trials are days, a year is the longest term.
  (select count(*) from b where trial_ends_at > now() + interval '45 days')    as trial_ends_far_out,
  (select count(*) from b where current_period_end > now() + interval '400 days')
                                                                               as period_ends_far_out,
  (select count(*) from b where created_at > now() + interval '1 minute'
                                 or created_at < timestamptz '2024-01-01')    as created_at_out_of_range,
  -- The plan mirror shows a plan with nothing behind it (the Stripe webhook,
  -- the no-card trial and trial_expiry are its writers; the signup door
  -- copied the app's tier until this PR).
  (select count(*) from b where tier is not null and tier not in ('starter', 'free')
                                and comp_tier is null and subscription_status is null)
                                                                               as tier_without_plan,
  -- An office admin who made themselves the owner keeps their seat row.
  (select count(*) from b where exists (
     select 1 from public.business_users u where u.business_id = b.id and u.user_id = b.owner_id))
                                                                               as owner_also_has_a_seat,
  (select count(*) from b where not exists (select 1 from auth.users a where a.id = b.owner_id))
                                                                               as owner_not_a_login,
  -- The badge says all seven foundation phases are done.
  (select count(*) from b where in_the_clear and (
     select count(distinct f.phase) from public.foundation_progress f
      where f.business_id = b.id and f.status = 'complete') < 7)              as in_the_clear_without_seven_phases,
  -- The server never turns a real business off (only a sample is born
  -- inactive); an inactive one is out of the business cap's count.
  (select count(*) from b where not coalesce(is_active, true))                 as inactive,
  (select count(*) from b where entity_group_id is not null and not exists (
     select 1 from public.entity_groups g where g.id = b.entity_group_id and g.owner_id = b.owner_id))
                                                                               as group_not_the_owners,
  (select count(*) from b where use_composer)                                  as use_composer_on;
--
-- Expected when nobody used the hole: every count 0 except businesses, comped
-- (Kevin's comps), trialing_* (Platform Chief's extensions), inactive (0), and
-- use_composer_on (the businesses Kevin switched to the composer).
--
-- Q2 — statements the app's own roles ran that named a server column (needs
-- pg_stat_statements, on by default in Supabase; counts since its last reset).
-- PostgREST writes PATCH as `UPDATE "public"."businesses" SET "<col>" = ...
-- FROM ...` and POST as `INSERT INTO "public"."businesses"("<col>", ...)`,
-- naming exactly the columns the request sent; the query text carries no
-- values. Any row here is a request no app screen makes.
with s as (
  select s.calls, lower(s.query) as q
    from extensions.pg_stat_statements s
   where s.userid in ('authenticated'::regrole, 'anon'::regrole)
), w as (
  select calls,
         case when q like '%insert into "public"."businesses"%' then 'insert' else 'update' end as kind,
         coalesce(substring(q from 'update "public"\."businesses" set (.*?) from '),
                  substring(q from 'insert into "public"\."businesses"\s*\(([^)]*)\)'), '') as cols
    from s
   where q like '%update "public"."businesses" set %' or q like '%insert into "public"."businesses"%'
)
select c.col, w.kind, count(*) as statements, sum(w.calls) as calls,
       (select stats_reset from extensions.pg_stat_statements_info) as counted_since
  from w cross join unnest(array['id', 'owner_id', 'created_at', 'attribution', 'comp_tier', 'tier',
         'subscription_status', 'subscription_plan', 'trial_ends_at', 'current_period_end',
         'cancel_at_period_end', 'stripe_customer_id', 'stripe_subscription_id', 'stripe_account_id',
         'in_the_clear', 'in_the_clear_at', 'is_active', 'entity_group_id', 'use_composer',
         'is_sample', 'sample_of']) as c(col)
 where position('"' || c.col || '"' in w.cols) > 0
 group by 1, 2
 order by 1, 2;
-- Expected: no rows. (in_the_clear may show: foundation_agent wrote it
-- with the user's login until this PR; every other column is a forgery.)
--
-- Q3 — any business the app's roles inserted directly (never legitimate).
select count(*) as statements, coalesce(sum(calls), 0) as calls
  from extensions.pg_stat_statements
 where userid in ('authenticated'::regrole, 'anon'::regrole)
   and lower(query) like '%insert into "public"."businesses"%';
-- Expected: 0, 0.
