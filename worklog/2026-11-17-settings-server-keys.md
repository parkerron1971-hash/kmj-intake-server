---
title: The server's keys in businesses.settings stay the server's, and a settings write names only its own keys
date: 2026-11-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-16/17, after the first paying church''s founding place (settings.founding_church) was found gone two hours after its first payment: "top tier, no cut corners"'
status: in review
prs: [kmj-intake-server#1878, solutionist-studio (PR 2, after #1878 merges)]
migrations: [supabase/APPLY-2026-11-17-settings-server-keys.sql (NOT APPLIED; the parent session applies it)]
left_undone:
  - "Apply supabase/APPLY-2026-11-17-settings-server-keys.sql (SQL editor). Until then business_settings.merge falls back to a fresh read and a whole write, and Railway prints '[settings] merge_business_settings isn't in the database yet' once every five minutes per replica."
  - "Put the first church's founding place back (a data fix, not in the migration; the parent session with Kevin). The SQL editor and the service role are not held by the guard."
  - "Frontend PR 2: the app's 37 whole-object writers from its sign-in copy (table below) become single-key merges (merge_business_settings), RoomOrientationStrip first."
  - "Not changed here, listed below: the server writers that still write the whole object from a row read in the same request (about 45, a window of milliseconds), Chief's writers that run with the user's login (13, from the turn's row: seconds), and the compare-and-set writers (7). Each can move to business_settings.merge with its own tests; the guard already keeps the server's keys out of their stale copies where they run as the user."
  - "SEPARATE HOLE, not fixed here: an owner or admin can PATCH their own businesses row's COLUMNS through RLS (businesses_admin_update has no column list, and no repo migration revokes column UPDATE or guards them). feature_gates.plan_of trusts comp_tier, so the app's login could comp its own business any plan; subscription_status, tier, trial_ends_at, subscription_plan, stripe_* the same. The app only ever writes settings, voice_profile, name and type on this table. Check production first (pg_trigger on businesses, information_schema.column_privileges for authenticated), then the same kind of guard for those columns in its own PR."
  - "Not proved on the real database: no production read or write. After the migration, Check lines at the end of the file read it back."
decisions:
  - "What was lost and how: church_founding.claim wrote settings.founding_church through church_billing._merge_setting, which read the row and wrote the whole object back; so did every other writer, and the app's rooms write the whole object from the copy loaded at sign-in. The row's last write (23:35:38 UTC) carried a copy from before the payment (~21:4x). rooms_visited is on the row and RoomOrientationStrip writes it once for every room a business under 30 days old opens, from activeBusiness.settings: the likeliest writer. It can't be proved without production logs; the fix doesn't depend on which one it was."
  - "SERVER_KEYS (42, business_settings.py, mirrored in business_settings_server_keys(); a test pins them equal): money and offers (founding_church, no_card_trial, sample_church, church_move, extra_logins, church_texts_bill, stripe, churchsavvy_only, platform_books); gates the API holds behind the owner, a role or a step-up (computer, email_domain, autonomy, content_autonomy, automations_paused, church_owner_contact_id); the server's records (lifecycle_emails, which holds sample_follow_up_at, chief_insights, chief_playbook, maturity, church_leaders_note, church_team_rollup, interview_events); settings with their own checked endpoint (availability, booking_page, business_picture, church_serving, churchsavvy, client_sources, concierge, doc_defaults, giving, journeys, member_portal, messaging, new_here, news, reading_plan, site_prefs, sms_replies, studio, superbill, texting_hours). first_run is not a settings key (first_run_arc is its own table)."
  - "The rule for the list: a key the server writes that the app never writes itself (the frontend inventory below) and that no server path writes with the user's login (Chief's _sb inside a chat forwards the practitioner's JWT, and so does brand_engine's _sb_patch: brand_kit, track, business_track_done, events_public, goals, content_calendar, website_content, store, email_templates_v2 stay off it). A test fails if a key the app or a user-login writer writes is added, and a tripwire counts the user-login settings writers so a new one is looked at."
  - "The guard keeps rather than refuses: the app's whole-object writes carry stale copies of these keys today, and refusing would break every one of them. merge_business_settings refuses a server key to the app's logins out loud (42501), because a new caller should hear it."
  - "BIRTH_KEYS = churchsavvy_only: the ChurchSavvy app makes its church with it (it only narrows what the church opens), and dropping it later would open everything, so it is held after birth. Every other server key is left out of what a client sends at birth: launch_access.birth_settings for the signup door (the old code copied body.settings verbatim as the service role, and setdefault let a sent autonomy beat the regulated default) and for account_lifecycle's import (which copied the bundle's settings verbatim: a founding place, a trial marker, extra logins or Chief's step-up limits could be imported)."
  - "Atomic: merge_business_settings is one UPDATE, settings = business_settings_merge_at(settings, under, set, drop), so a concurrent write is never undone (Postgres re-evaluates the SET on the newest row version under READ COMMITTED). SECURITY INVOKER: for the app RLS still decides whose row, and the guard still runs. The fallback (no function yet: PGRST202) is the old fresh read and whole write, cached for five minutes per process."
  - "Converted to business_settings.merge in this PR: church_billing._merge_setting (founding_church, church_move, extra_logins), lifecycle_emails._stamp (inside lifecycle_emails), no_card_trial.verify_phone_code (inside no_card_trial), chief_insights._mark_run and chief_playbook._mark_run (their rows were read before a model call), maturity_engine._write_cache, stripe_connect_router._handle_account_updated (inside stripe), email_domain_monitor._write_cfg (the sweep's row was read before its DNS checks) and email_domains_router._write_settings."
related: [2026-11-14-founding-deal-cards.md, 2026-11-16-churches-no-trial.md, 2026-11-15-sample-church-be1.md, 2026-11-16-new-customer-alert.md]
---
The first paying church's founding place was written to its settings when
its first payment landed and was gone two hours later: every writer of
`businesses.settings` read the whole object, changed one key and wrote the
whole object back, and one of them wrote a copy from before the payment.
From this PR the database keeps the server's 42 keys whatever the app sends
(and the app can no longer forge one), the hot server writers send only the
key they mean, and a new business is born without any server key it was
never given.

Overlaps (both repos' worklogs read): the founding deal (2026-11-14) made
the place; churches-no-trial (2026-11-16) and the new-customer alert
(2026-11-16) touch the same first payment but not settings writes; the
sample church BE-1 wrote the guard pattern this follows
(businesses_guard_sample). A frontend agent fixing church sign-up words
(2026-11-16) touched OnboardingFlow, which only sends birth settings.

## Every writer of businesses.settings (2026-11-17, from main / module-system)

How each writes, before this PR. "Whole, stale" = the whole object from a
copy held for a while; "whole, fresh" = the whole object from a read
moments before (milliseconds); "conditional" = whole object, but only while
its own key still reads as expected.

### Frontend (solutionist-studio), as the user's login: the guard holds all of these

| Writer | Keys | How |
|---|---|---|
| RoomOrientationStrip | rooms_visited | whole, stale (the sign-in copy; one write per room a young business opens) |
| AutopilotPanel | autopilot | whole, stale |
| PeriodsSection | period_lock_mode, period_close_two_signature, financial | whole, stale |
| QuickBooksSection (supabase-js) | financial | whole, stale |
| ChiefPreferences (2) | chief_preferences | whole, stale |
| ContactsList (2) | saved_filters | whole, stale |
| ContentStrategy (2) | content_calendar, website_content | whole, stale |
| FormsPanel | email_templates_v2 | whole, stale |
| EmailTemplates | email_templates | whole, stale |
| FunderProfileCard | funder_profile | whole, stale |
| GetFound (2) | get_found | whole, stale |
| GoalsPanel | goals | whole, stale |
| GoogleProfile | public_listing | whole, stale |
| GrantBoilerplateCard | grant_boilerplate | whole, stale |
| IdeaBoard (3) | boards, strategy | whole, stale |
| IntegrationsHub (2) | payments, payment_providers | whole, stale |
| LinkPage | link_page | whole, stale |
| MediaLibrary, ProductCatalog | media_library | whole, stale |
| NotificationCenter | notifications | whole, stale |
| OnboardingChecklist | checklist_dismissed | whole, stale |
| OperationsDashboard | dashboard | whole, stale |
| PrintMaterials | print_materials | whole, stale |
| RevenueAllocator | revenue_allocator | whole, stale |
| RevenuePanel | financial | whole, stale |
| ReviewPanel (2), VisionPanel | strategy | whole, stale |
| StoreOrdersPanel | store | whole, stale |
| TourController | tour_done_v1 | whole, stale |
| BusinessSettings | threshold keys, sms_alerts, feed2, notifications, practitioner_name, avatar_url | changed keys over a fresh read |
| useSteps.saveRoad | next_steps | whole, fresh |
| MakeItYours | chief_preferences | whole, fresh |
| PhotoAndName | avatar_url, practitioner_name | whole, fresh |
| ReportBrandingCard | branding | whole, fresh |
| TestimonialsManager | website_content | whole, fresh |
| galleryUpload | media_library | whole, fresh |
| ThemeProvider | theme | whole, fresh |
| AboutMeReview, VoiceToneEditor, BusinessIdentityEditor | (voice_profile; name, type) | other columns only |

### Backend, made atomic or stripped in this PR

| Writer | Keys | Before | Now |
|---|---|---|---|
| church_billing._merge_setting (claim, move, extra logins) | founding_church, church_move, extra_logins | whole, fresh (read-modify-write) | merge |
| lifecycle_emails._stamp | lifecycle_emails.* (sample_follow_up_at too) | whole, fresh | merge inside lifecycle_emails |
| no_card_trial.verify_phone_code | no_card_trial.phone_* | whole, fresh | merge inside no_card_trial |
| chief_insights._mark_run | chief_insights | whole, stale (row read before the model call) | merge |
| chief_playbook._mark_run | chief_playbook | whole, stale (same) | merge |
| maturity_engine._write_cache | maturity | whole, fresh | merge |
| stripe_connect_router._handle_account_updated | stripe.* | whole, fresh | merge inside stripe |
| email_domain_monitor._write_cfg | email_domain | whole, stale (sweep row, before DNS checks) | merge |
| email_domains_router._write_settings | email_domain | whole, fresh | merge |
| launch_access.create_business (insert) | client's body.settings | verbatim, as the service role | birth_settings: server keys left out |
| account_lifecycle.import_account (insert) | the bundle's settings | verbatim, as the service role | birth_settings: server keys left out |

### Backend, unchanged (service role unless said)

| Writer | Keys | How |
|---|---|---|
| no_card_trial.start | no_card_trial (+ trial columns) | conditional (no subscription, no trial yet), row from the same request |
| sample_church_seed, sample_church.touch / _mark_ending | sample_church | conditional on the marker / is_sample |
| church_leaders_note.swap, church_team_week.swap, church_texts._write_record | church_leaders_note, church_team_rollup, church_texts_bill | conditional on their own key |
| chief_grow_actions (6), chief_of_staff (3), chief_offering_actions (2), chief_strategy_actions.complete_strategy_track, business_track_actions.complete_business_track | goals, content_calendar, website_content, email_templates_v2, events_public, store, track, business_track_done | whole, from the turn's row; Chief's _sb runs as the user in a chat, so the guard keeps the server's keys out of these |
| brand_engine save_brand_kit / upload_asset / remove_asset, creative_expression | brand_kit | whole, fresh; the user's login when one is bound |
| availability_router, chief_offering _save_availability_settings | availability | whole, fresh |
| booking_page_router, chief_offering _publish_booking_page_sync | booking_page | whole, fresh |
| business_track_actions.save_client_sources | client_sources | whole, fresh |
| celebrations, church_news.news_settings | news (+ member_portal.notifications) | whole, fresh |
| chief_agent.agent_enable, standing_permissions._write_autonomy | autonomy | whole, fresh |
| chief_door_actions (2), giving_router, member_portal_gifts | giving, member_portal | whole, fresh |
| chief_sms_actions.set_sms_alerts | sms_alerts | whole, fresh |
| chief_strategy_actions._save_settings | business_picture, concierge | whole, fresh |
| church_assignments.pick_owner_person | church_owner_contact_id | whole, fresh |
| church_serving.save_settings | church_serving | whole, fresh |
| content_approval._save_calendar / set_autonomy | content_calendar, content_autonomy | whole, fresh |
| doc_templates_router.save_sticky_terms | doc_defaults | whole, fresh |
| events_rsvp_router | events_public | whole, fresh |
| inventory_scan, store_router, store_files | store | whole, fresh |
| journeys_router.write | journeys, get_found | whole, fresh |
| member_app_pictures, member_asks, member_directory, member_portal | member_portal, media_library | whole, fresh |
| messaging_router, new_here, reading_plans, text_room, texting_hours | messaging, new_here, reading_plan, sms_replies, texting_hours | whole, fresh |
| rules_router pause_all / trust_grant / trust_revoke | automations_paused, autopilot | whole, fresh |
| setup_plan.apply_setup_plan | financial | whole, fresh |
| site_composer (4), site_concierge, studio_light_table | site_prefs, brand_kit, interview_events, media_library, concierge, studio | whole, fresh |
| sunday_planning, superbill | churchsavvy, superbill | whole, fresh |
| platform_console, sample_church (inserts) | platform_books, practitioner_name; the sample's switches | server-made |
| chief_computer_settings, image studio (SQL functions) | computer, content_calendar | jsonb_set in one UPDATE (already atomic) |
