---
title: The app's logins change only the owner's columns of businesses; plans, billing, Stripe ids and ownership are the server's
date: 2026-11-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-17, after the settings guard (#1878) named a second hole: "top tier, no cut corners"'
status: shipped
prs: ["kmj-intake-server#1880 (no frontend PR: the app writes only owner columns)"]
migrations: ["supabase/APPLY-2026-11-17-businesses-server-columns.sql (NOT APPLIED; the parent session applies it, after this PR deploys)"]
left_undone:
  - "Apply supabase/APPLY-2026-11-17-businesses-server-columns.sql (SQL editor) after this PR has deployed: run its Before query first, then the file, then its Check lines. Until then the hole is open in production; the code works the same either way."
  - "Run scripts/businesses_server_columns_check.sql, Q1 to Q3 one at a time (counts only), and read the numbers with Kevin: comped against the comps he gave, trialing_without_subscription_or_marker against Platform Chief's trial extensions, everything else expected 0. Q2/Q3 (pg_stat_statements) say whether an app login ever ran a write naming a server column, or inserted a business, since the stats were last reset."
  - "type stays the owner's (by design: the app's Kind of business picker and POST /business-profile/profile/{id}), so what a change of type unlocks is still open and is a server rule for Kevin to decide: a church relabelled as a business meets the no-card trial at GET /billing/access (no_card_trial.eligible reads the type as it is now), and a paused kind (therapist) can be chosen after birth through the profile route (the picker hides it; nothing refuses it)."
  - "POST /account/import makes a business without the signup door's gates (invite-only, the business cap, paused kinds, the church sample). Its own PR."
  - "Comps leave no record: launch_access.set_comp_tier logs with logger.info (Railway shows print() only) and writes no audit row, so no later check can tell a comp from a forgery. It should print and write the action ledger."
  - "An owner can still DELETE their own businesses row through PostgREST (owner_full_access is FOR ALL). Not a privilege gain (it is their row), but it skips account_lifecycle's delete (storage, Stripe). Revoke DELETE too once the app is checked for any direct delete."
decisions:
  - "Classification of the 30 production columns (read 2026-11-17). Owner's, granted UPDATE to authenticated (9): name, type, settings, voice_profile, cdi_vocabulary, brand_kit_history, brand_kit_draft, brand_kit_draft_at, updated_at. Server's, refused (19): id, owner_id, created_at, attribution (all four birth-only: set once by the server), comp_tier, tier, subscription_status, subscription_plan, trial_ends_at, current_period_end, cancel_at_period_end, stripe_customer_id, stripe_subscription_id, stripe_account_id, in_the_clear, in_the_clear_at, is_active, entity_group_id, use_composer. Left to businesses_guard_sample (2): is_sample, sample_of (not granted either)."
  - "Two layers, for anon and authenticated only. Privileges: REVOKE INSERT, UPDATE on the table, GRANT UPDATE on the nine; a write naming anything else fails with 42501 before a row is touched, a mixed PATCH lands nothing, and a column added later is closed to the app until granted (docs/RLS_MODEL.md Rule 4). Trigger businesses_guard_server_columns (BEFORE INSERT OR UPDATE, SECURITY INVOKER, current_user, reads no table): refuses an app INSERT and any app UPDATE that changes a server column, so a later blanket GRANT can't reopen it. Grants alone vanish with one pasted GRANT ALL; a trigger alone is open for every new column. Together they are loud, closed by default, and survive a widened grant."
  - "Refuse, not keep (the settings guard keeps): nothing the app's logins send names a server column, so a write that does is a forgery or a writer nobody knows about, and keeping its value quietly would tell it it had saved. The grants refuse the same write with the same code, so a widened grant changes nothing a caller sees. A server column sent back unchanged passes the trigger."
  - "No app login may insert a business at all (grants and trigger), not 'insert with safe defaults': the app has made every business through POST /access/businesses/create since Arc 19 Phase B, and a direct insert with safe billing columns would still skip the invite gate, the business cap, the paused kinds and the church sample."
  - "type stays the owner's: the app's picker writes it (every kind, church included), and the server changes it with only an owner check through POST /business-profile/profile/{id} (business_profiles.business_type, mirrored to businesses.type by sync_profile_type_trigger as the service role, since that route doesn't bind the user's JWT). A guard on the column would not decide who may change it; the money edges are in left_undone. sync_profile_type_trigger still works when the app's login updates business_profiles itself: it writes type and updated_at, both granted (proved in the database test)."
  - "owner_id is the worst of them: businesses_admin_update's WITH CHECK asks only is_business_admin(id), which reads business_users, so an office admin could set owner_id to themselves and take the church. There is no ownership transfer anywhere in the app; the SQL editor stays the way."
  - "Server writers changed: foundation_agent._recompute_in_the_clear reads and writes as the service role (as_server=True) instead of the user's login when one is bound (the badge is the server's); launch_access.create_business writes BIRTH_TIER = 'starter' instead of copying body.tier as the service role (the app sends 'starter', so nothing it sees changes)."
  - "No frontend PR: the app writes name, type (BusinessIdentityEditor), voice_profile (AboutMeReview, VoiceToneEditor) and settings (lib/businessSettings, merge_business_settings or its fallback PATCH), all granted; it inserts no business (OnboardingFlow and ChurchSavvyApp use /access/businesses/create)."
related: [2026-11-17-settings-server-keys.md, 2026-11-15-sample-church-be1.md, 2026-11-16-churches-no-trial.md]
---
The app's own login could PATCH its businesses row's plan, billing, Stripe
and ownership columns through PostgREST (RLS decides whose row, not which
columns), comp itself any plan, start a trial, move a church's giving account,
or, as an office admin, make itself the owner. From this PR's migration the
database grants the app's logins nine owner columns and refuses everything
else, out loud, twice over; the two server writers that leaned on a user login
or a client value now write as the server.

Overlaps (both repos' worklogs read): the settings guard (2026-11-17,
kmj-intake-server #1878, frontend #1588) found this hole and left it here; its
trigger guards the server's keys inside `settings` and fires after this one.
The sample church BE-1 (2026-11-15) wrote `businesses_guard_sample`, which
already refuses `is_sample`/`sample_of` and fires first. Churches-no-trial
(2026-11-16) made the trial read the type, which is why a change of type is in
left_undone. Nothing in flight in the frontend touches these columns.

## The 30 columns, who writes them, and why each is where it is

"App" is the frontend with the user's login (module-system, 2026-11-17).
"User-login server" is a backend path that forwards the user's JWT when one is
bound (Chief's `_sb` in a chat, `brand_engine._sb_patch`,
`foundation_agent._sb_patch`). Everything else is the service role.

| Column | Class | App | User-login server | Service role | Why |
|---|---|---|---|---|---|
| name | owner | BusinessIdentityEditor | | create_business, import, platform setup, sample | the owner's name for it |
| type | owner | BusinessIdentityEditor; sync_profile_type_trigger when the app updates business_profiles | | create_business, import, /business-profile (via the mirror) | the kind of business, by design; money edges in left_undone |
| settings | owner (server keys: #1878) | lib/businessSettings | Chief (13 writes), brand_engine, creative_expression | many | |
| voice_profile | owner | AboutMeReview, VoiceToneEditor | Chief update_voice_profile | create_business | |
| cdi_vocabulary | owner | | | create_business | design vocabulary key from the type; gates nothing |
| brand_kit_history | owner | | brand_engine.save_brand_kit | | the owner's brand work |
| brand_kit_draft, brand_kit_draft_at | owner | | brand_engine save/clear draft | | the owner's brand work |
| updated_at | owner (harmless) | | brand_engine; the type mirror | trg_businesses_updated_at overwrites it | |
| id | server (birth) | | | default | |
| owner_id | server (birth) | | | create_business, import, platform setup, sample | an admin could take the business |
| created_at | server (birth) | | | default | a business's age drives first-week logic |
| attribution | server (birth) | | | create_business (whitelisted) | Kevin's growth numbers |
| comp_tier | server | | | set_comp_tier (owner only) | plan_of honours it: any plan, free |
| tier | server | | | Stripe webhook, no-card trial, trial_expiry, create_business (now 'starter') | the plan mirror the app shows |
| subscription_status | server | | | webhook, no-card trial, trial_expiry, Platform Chief | access_state |
| subscription_plan | server | | | webhook, no-card trial | plan_of, founding checks |
| trial_ends_at | server | | | webhook, no-card trial, Platform Chief | access_state |
| current_period_end, cancel_at_period_end | server | | | webhook | billing state |
| stripe_customer_id | server | | | stripe_billing | whose billing portal |
| stripe_subscription_id | server | | | webhook | access, trial eligibility |
| stripe_account_id | server | | | stripe_connect_router | where giving and payments go |
| in_the_clear, in_the_clear_at | server | | foundation_agent (until this PR) | foundation_agent (from this PR) | the public "In The Clear" badge |
| is_active | server | | | sample_church (insert) | the business cap counts active rows |
| entity_group_id | server | | | entity_groups_router (owner-checked) | consolidation (reports filter by owner, so no cross-owner read) |
| use_composer | server | | | Kevin (SQL) | routes site builds through extra paid model calls |
| is_sample, sample_of | businesses_guard_sample | | | sample_church | |

Every backend write to businesses (87 call sites, AST scan of main): all are
the service role except the user-login ones above, which
`__tests__/test_businesses_server_columns.py` scans for on every run (20
today) and fails if one names a column outside the nine.

## The abuse check

`scripts/businesses_server_columns_check.sql`, read-only, counts only (no id,
name or email), three queries to run one at a time in the SQL editor. Q1: one
row of counts of rows that look like nothing the server writes (comps by plan,
`active` with no subscription, trials with no subscription and no no-card
marker, subscription ids no webhook named, Stripe ids shared across owners,
Connect accounts the lock table never recorded, non-price plans, far-out
dates, a tier with no plan behind it, an owner who also holds a seat (what an
admin who took a church would look like), the badge without seven phases,
inactive rows, groups that aren't the owner's, use_composer). Q2: from
pg_stat_statements, the statements the app's own roles ran that named a
server column, by column (PostgREST names exactly the sent columns and no
values). Q3: direct inserts by the app's roles. Checked on PGlite against a
stand-in schema with planted forgeries: each one shows, the app's normal
writes don't.

Tests: `__tests__/businesses_server_columns_db.mjs` (120 checks, in CI: the
hole before, every legitimate write after, every server column refused to an
owner and an office admin, no app insert, the server and the SQL editor free,
the trigger refusing the same writes with the grants widened, the trigger
order), `__tests__/test_businesses_server_columns.py` (the lists, the
user-login writer scan, the SQL's shape, the badge and the birth tier).
