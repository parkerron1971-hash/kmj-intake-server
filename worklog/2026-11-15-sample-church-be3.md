---
title: Nothing in a sample church is ever sent, spent, published or learned from (sample church, BE-3, the guards and the daily cleanup)
date: 2026-11-15
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-14, approved the sample church signup: "top tier, no cut corners". BE-3 of the plan: the send and spend guards, the sweeps, the no-sends test and the daily cleanup.'
status: in review
prs: [kmj-intake-server#1855]
migrations: []
left_undone:
  - "A visitor really owns their sample, so their own login can still write its child tables (contacts, events and so on) straight through PostgREST. The app never does: its guard (solutionist-studio #1561) refuses every Supabase write not in read_posts, and nothing written there can be sent (the seams) or acted on (the sweeps). A database wall would be a restrictive policy through a SECURITY DEFINER is_sample_business(b) helper (docs/RLS_MODEL.md rule 2), a migration for Kevin to apply. Not built."
  - "The write guard reads JSON bodies only. A form or file upload that names a sample only in a form field (not its path or query) passes it; the seams still refuse anything that would send."
  - "BE-4 (the sample's Chief) must wrap its turn in sample_church.allow_sample_chief(): llm_call refuses every AI call billed to a sample outside it. /sample-church/* is open in the write guard for BE-4's routes."
  - "exclude() keeps samples out of a sweep's query by id. Past EXCLUDE_MAX (150) samples it says nothing (logged) and drop_samples alone filters, so a limited query could again fill with samples' rows. Raise it, or move the filter into the database, before there are that many."
decisions:
  - "Three layers, each enough for what it covers: the provider seams refuse (twilio_sms.send_sms, email_sender.send_via_resend, church_mail's direct Resend post, public_site's contact form, push send_to_business and send_to_user with a business, member_push, llm_call); the sweeps pass a sample by; a write guard answers 409 to every write request that names one."
  - "For everyone, not only samples: no text to a number set aside for fiction (+1 NXX 555-01xx) and no mail to a reserved domain (example.com/.net/.org and their subdomains, *.example, *.test, *.invalid, *.localhost). A made-up record that ever leaked out of a sample still reaches nobody. MADE_UP_RECIPIENT_GUARD=off is its kill switch; the test suite's conftest sets it, because tests address their fake mail to example.com, and the sample church's tests turn it back on."
  - "A refused send raises sample_church.SendRefused (a RuntimeError), which every caller already treats as a failed send. A refused AI call is a synthetic 403 Response (llm_call.post, post_with, apost, post_lane), a refused stream a context holding that 403, and sdk_client() raises SampleSpendRefused; all before the call, so nothing is spent or metered."
  - "The spend refusal sits at the front of the llm_call seam, not in _meter, which runs after the call is paid for. It reads the call's business_id or billing_context.current(), and lets through only a task inside sample_church.allow_sample_chief() (the contextvar BE-4 sets)."
  - "Sweeps: drop_samples, drop_sample_map and skip_id after one batched prime() (every answer kept for good, both ways), plus exclude() in the query of every row-driven sweep whose skipped rows would stay due (follow-ups, prayer, leader terms, scheduled group posts, event holds, campaigns, drafts, cases, assignments, workflow runs), so N identical seeded samples can never crowd real churches out of a limit."
  - "A sweep closes a sample's own due row where leaving it would re-pick it every tick (a scheduled move marked failed 'sample church', an assignment pushed a day, a keep-warm chain stopped, events stamped handled, a standing send held, a clip or video job failed). It never writes anything new for one."
  - "no_card_trial.blocks and blocks_async return a sample's row marked is_sample, so every no-card gate (site_hidden, preview_blocked, the preview token's needed, check, check_build) holds a sample back, and card_message words it as the sample (sample_church.MESSAGE), never 'add a card'."
  - "A sample's member app opens only in its owner's preview (the one-time link being opened, or the preview cookie); otherwise _church_for_request answers None, so no sign-in code is ever sent. POST /member-portal/{business_id}/preview is in READ_POSTS for that reason: it writes only its own two-minute ticket."
  - "Idle is measured from settings.sample_church.last_seen_at, which /billing/access (access_block) stamps at most every 12 hours and only on a READY sample, so the stamp never races the seed's pending-to-ready write. Before the first stamp it is the sample's created_at."
  - "The daily cleanup (08:20 UTC, leader-gated; SAMPLE_CHURCH_CLEANUP=off stops it) deletes through sample_church.delete (account_lifecycle._delete_business): home pays (a subscription id, or active, trialing, past_due or unpaid), home gone (sample_of null, or naming no row), 'ending' for more than 15 minutes, idle 60 days. At most 50 a day; a read failure deletes nothing; it logs counts only."
  - "The write guard is pure ASGI, added before CORSMiddleware so it sits inside it (the 409 carries CORS headers; a preflight never reaches it). It reads path UUIDs, the business_id, biz and businessId query keys, and the same keys at the top of a JSON body up to 256 KB, and answers BE-1's shape {detail: {error: sample_church, what: write, message}}. Exempt: READ_POSTS (POST only), /agents/chief/chat and its /stream, /agents/chief/prewarm (which answers 'warmed nothing' for a sample by itself), /sample-church/*."
  - "READ_POSTS uses the app guard's format (solutionist-studio #1561): plain paths, {param} segments, a trailing /*; the server matches the same way, and a test pins the shape. Twelve server POSTs (each handler read: no write but a rate counter or the preview ticket, no AI) and the Supabase reads the app makes by POST (the storage list and nine academy functions with no insert, update or delete in their SQL). Anything that drafts or reads a file with AI is left out on purpose."
related: [2026-11-15-sample-church-be1.md, 2026-10-03-no-card-trial.md]
---
BE-3 closes every path by which a sample church could send, spend, publish
or teach Chief anything, and adds the daily cleanup. Nothing changes for a
business that is not a sample, except the two guards that hold for everyone:
no text to 555-01xx and no mail to a reserved domain. The "nothing is ever
sent" test (`__tests__/test_sample_church_no_sends.py`) runs every scheduled
job over a sample with everything due and every switch on, then runs the
jobs that act over the same rows on a control church, which must see sends.

## Closed paths

- **Texts**: `twilio_sms.send_sms` (the one Twilio send) refuses a sample and any fictional number. Samples have no `sms_numbers`, so no inbound. The texting registration sweep does nothing for one.
- **Email**: `email_sender.send_via_resend` refuses a sample (by business_id, or the business a routed reply-to names) and reserved domains; `church_mail` (`_resend` POST /emails, `send_copy`, `relay_reply`); `public_site`'s contact form (409 for a sample, never to a reserved address). Member sign-in codes: a sample's member app can't be reached outside the owner's preview, and both senders refuse besides.
- **Push**: `push_notifications.send_to_business`, `send_to_user(business_id=...)`, the morning brief tick; `member_push._send` (every member note, held or not) and its two sweeps. Person-level `send_to_user` callers are covered by their sweeps (table below).
- **Scheduled jobs**: every add_job classified below, skips added where needed.
- **Public web**: a sample's public address shows "coming soon" (`no_card_trial.site_hidden`); its previews need the owner's token (`preview_blocked`; `/billing/trial/preview-token` answers needed=true); token previews carry `X-Robots-Tag: noindex`; the member app opens only in the owner's preview; public giving checkout, event RSVP and sign-ups (`_public_church`: signup, release, claim), the contact form, kids stations (`station_from_token`) and worship screens (`screen_from_token`) refuse it; the new-here card and the daily page go through `_church_for_request`.
- **AI spend**: `usage_metering.can_interact` is False; `llm_call` refuses before the call (except inside `allow_sample_chief()`); `/ai/proxy` answers 409 for a sample named in its metadata; `/agents/chief/prewarm` warms nothing; semantic memory never embeds or matches a sample's; keep-warm never starts or pings one.
- **Money**: BE-1's refusals confirmed (checkout, credit packs, Connect start, create and session, numbers through require_card, the registration send, domains). Added: public giving checkout, `church_texts.bill_tick`, the ledger anchor sweep (paid), `balance_sweep`, the clip finder (a paid service). Every other money POST names the business and meets the write guard.
- **Integrations**: `oauth_connect_ticket.mint` refuses a sample (Google, Meta, social and QuickBooks all mint there first); connected-AI `claim`; `mcp_server._resolve_business` never resolves to a sample (a token naming one gets nothing; an owner's JWT skips it). Plaid, Square, calendar feeds and Stripe Connect start by a POST naming the business, which the write guard refuses.
- **Learning**: `vertical_distill.contributes()` is False for a sample (the tick primes the batch in one read); chief_insights, chief_playbook, brain_pass (`active_businesses`), outcome_ledger and semantic memory never see one.
- **Platform counts**: `platform_console` (practitioners, total_businesses) already filters is_active (confirmed); `is_sample=not.is.true` added to `margin._businesses`, `platform_money.read_income`, `church_billing._founding_taken` and `church_founding.taken`. `retention_metrics` reads no businesses list.
- **READ_POSTS** filled and served in `/billing/access`'s `sample.read_posts` (and in its fallback); the write guard; the cleanup; the last-visit stamp.

## The scheduled jobs (kmj_intake_automation.py; the worker runs this same list)

"Covered" means the job's business query filters `is_active=eq.true`, which a sample (is_active false) never passes. `test_every_scheduled_job_is_classified` fails when a job is added without a place in this list.

| job | tick | finds businesses by | class | what BE-3 did |
|---|---|---|---|---|
| scheduler_lease_renew | scheduler_lock.renew_tick | none | not business-scoped | none |
| dev_alert_digest_tick | dev_alerts.dev_alert_digest_tick | dev_alerts rows | platform owner only | none |
| dev_relay_purge | dev_relay.dev_relay_purge | dev tables | not business-scoped | none |
| followup_check | check_followup_sequences | in-memory COMPLETED_PROJECTS | not business-scoped | none |
| workflow_drain | workflow_engine.drain_tick | workflow_runs, then businesses select=* | needs skip | exclude() in the scan + skip in advance_run |
| autopilot_sweep | chief_of_staff.autopilot_sweep_tick | /businesses (no filter) | needs skip | skip added + is_sample in select |
| chief_keep_warm | chief_keep_warm.tick | chief_keep_warm rows | needs skip (LLM) | skip added remember() + _one |
| gl_drain | gl_engine.drain_tick | gl_sync_queue | internal ledger only | none |
| stripe_usage_report | usage_metering.stripe_report_tick | subscription_status active/trialing + sub id | covered (a sample has no subscription) | none |
| rules_overdue_tick | rules_engine.overdue_tick | practitioner_rules | needs skip | skip added rules_engine.on_event |
| push_morning_brief | push_notifications.morning_brief_tick | push_subscriptions, businesses select=* | needs skip | skip added |
| gl_divergence | gl_engine.divergence_tick | journal_entries | internal only | none |
| gmail_sync | gmail_sync.sync_tick | google_mailboxes connected | needs skip (low) | skip added |
| hermes_tick | hermes_agent | platform counts | platform owner only | none |
| support_drafts | support_drafts.drafts_tick | support queue | platform owner only | none |
| chief_quality | chief_quality.quality_tick | usage totals | platform owner only | none |
| customer_health | customer_health.health_tick -> first_week.first_week_report | is_active=eq.true | covered | none |
| unfinished_work | unfinished_work.watch_tick | GitHub | platform owner only | none |
| scope_keeper | ops_desk.keeper_tick | operator tasks | platform owner only | none |
| money_auditor | money_auditor.audit_tick | subscribed businesses, Stripe GET | platform owner only | none |
| church_texts | church_texts.bill_tick | subscription_plan / comp_tier | needs skip (defensive, Stripe) | skip added |
| msg_retention | member_portal_messaging.retention_tick | settings messaging enabled | maintenance (deletes only) | none |
| rail_practice_retention | chief_rail.prune_tick | none | not business-scoped | none |
| member_push_sweep | member_push.sweep_tick | settings member_portal notifications | needs skip | skip added sweep_tick + sweep_held |
| stream_relay_sweep | stream_relay_router.sweep_stale | stream_sessions live | needs skip (low) | skip added |
| trial_expiry | trial_expiry.expire_tick | trialing, no sub | covered (a sample never trials) | none |
| email_domain_monitor | email_domain_monitor.monitor_tick | settings email_domain verified | needs skip (low) | skip added |
| sms_reminder_sweep | sms_alerts.reminder_sweep | sessions, businesses id=in | needs skip | skip added biz_map |
| sms_number_release_sweep | sms_numbers_router.release_sweep | sms_numbers releasing | not outbound (saves money) | none |
| notif_urgent_check / morning_brief / midday_ping / evening_summary / unanswered_leads | notification_engine | _all_active_business_ids is_active=eq.true | covered | none |
| notif_setup_brief | notification_engine.setup_brief_local_morning_tick | is_active=eq.true | covered | none |
| church_follow_up_sweep | church_follow_up.sweep (5 sub-sweeps) | attendance, church_follow_ups, leader roles, care requests, prayer | needs skip | exclude() + drop in each sub-sweep (first visits, prayer too) |
| church_checkin_sweep | church_checkin.sweep | church_checkin_settings enabled | needs skip (low) | skip added |
| church_shepherd_sweep | church_shepherd_signals.sweep | church_shepherds -> businesses | needs skip | skip added |
| church_leader_tasks_sweep | church_leader_tasks.sweep_tick | tasks -> businesses | needs skip | skip added |
| church_office_tasks_sweep | church_office_tasks.sweep_tick | tasks -> businesses | needs skip | skip added |
| church_team_rollup | church_team_week.rollup_tick | business_users managers -> businesses | needs skip | skip added |
| church_assignments_sweep | church_assignments.sweep_tick | _open_churches (owner) | needs skip | skip added _open_churches + loop |
| church_handovers_sweep | church_handovers.sweep_tick | _open_churches + church_handovers | needs skip | skip added |
| church_mail_alert_sweep | church_mail_alerts.sweep | church_mail alerted_at null | needs skip | skip added |
| church_mail_trash_sweep | church_mail_alerts.trash_sweep | none | not business-scoped | none |
| academy_work_sweep | academy_work.sweep_tick | storage cleanup | not business-scoped | none |
| group_email_followup | group_email.sweep_tick | group_posts | needs skip | skip added |
| group_post_later | group_post_later.sweep_tick | group_posts publish_at | needs skip | skip added |
| group_study_drafts | group_study.sweep_tick | sermons published (LLM) | needs skip | skip added |
| event_signups_sweep | church_event_signups.sweep_tick | church_event_registrations | needs skip | skip added |
| celebrations_today | celebrations.sweep_tick | member_celebrations / settings | needs skip | skip added |
| news_alerts | news_alerts.sweep_tick | settings news alerts | needs skip | skip added |
| news_reach | news_reach.sweep_tick | church_posts important | needs skip | skip added |
| ministry_reminders | worship_ministries.sweep_tick | worship_ministries remind | needs skip | skip added |
| serving_alerts | sunday_serving_alerts.sweep_tick | settings flags | needs skip | skip added |
| academy_class_reminders | academy_reminders.sweep_tick | academy live sessions | needs skip | skip added |
| academy_class_nights | academy_class_nights.sweep_tick | academy_live_sessions ended | needs skip | skip added |
| lead_response_reconcile | lead_response.reconcile_tick | contacts first_response_at null | internal only | none |
| reorder_sweep | reorder_engine.low_stock_reorder_sweep | _all_active_business_ids | covered | none |
| chief_insights | chief_insights.insights_tick (+ chief_playbook.tick, memory backfill) | /businesses limit 500 (no filter) | needs skip (LLM) | skip added both |
| feed2_distill | vertical_distill.tick | _businesses_by_vertical, contributes() | needs skip (learning) | contributes() False for samples |
| vertical_seed / vertical_curate | vertical_knowledge / vertical_playbook | none | not business-scoped | none |
| booking_session_sync | booking_widget_router.booking_session_sync_tick | custom_modules booking_calendar | needs skip | skip added |
| square_booking_sync | square_booking_sync.sync_due_tick | env pilot owners | platform owner only | none |
| calendar_feed_sync | outside_calendar.sync_due_tick | calendar_feeds | internal only | none |
| platform_marketing_* (4) | platform_marketing / campaigns / marketing_engine | Solutionist's own posts | platform owner only | none |
| business_marketing_due | business_marketing_dispatch.due_tick | RPC marketing_claim_due | needs skip (social) | held like a business outside the pilot |
| business_marketing_delivery | delivery_tick / tell_owners | marketing_posts | needs skip | skip added |
| business_marketing_suggest | business_marketing_planner.marketing_tick | social_connections -> businesses | needs skip (LLM) | skip added _business_rows |
| business_marketing_requests | manual_tick | marketing_runs manual | needs skip | skip added |
| business_marketing_designs | marketing_design_tick | desk_on_for() | needs skip | _sweep_on (desk_on_for and not a sample) |
| business_marketing_openings_watch | openings_watch_tick | desk_on_for + tell_pulled | needs skip | skip added |
| chief_scheduled | chief_scheduler.due_tick | chief_scheduled_actions queued | needs skip | _execute_row closes it (failed: sample church) |
| media_library | media_library.tick | RPC claim_media_asset (user-queued) | no outbound | none |
| clip_finder | clip_finder.tick | RPC claim_clip_run (user-queued, paid) | needs skip | skip added |
| clip_finder_sweep | clip_finder.sweep_tick | storage retention | not business-scoped | none |
| clip_covers | clip_covers.cover_tick | media_clip_runs completed (LLM) | needs skip | skip added |
| video_studio | video_studio_worker.tick | RPC claim_video_job (LLM) | needs skip | skip added |
| chief_jobs_recover | chief_jobs.recover_tick | chief_jobs queued/running | not business-scoped (user-started only) | none |
| chief_agent | chief_agent.agent_tick | events agent_handled_at null | needs skip | skip added handle_business |
| chief_assignments | chief_assignments.assignments_tick | chief_assignments active | needs skip | exclude() + skip in check_one (pushed a day) |
| chief_cases | chief_cases.cases_tick | chief_cases open | needs skip | exclude() + drop in the due query |
| proposal_life | proposal_life.proposals_tick | agent_queue drafts | needs skip | exclude() + drop in both queries |
| outcome_ledger | outcome_ledger.outcomes_tick (+ standing sweep_revocations) | chief_moves; businesses autonomy standing | needs skip | skip added |
| brain_pass | chief_brain_pass.nightly_tick | active_businesses (conversations/queue) | needs skip (LLM, learning) | skip added |
| chief_week | chief_week.weekly_tick | is_active=eq.true | covered | none |
| standing_release | standing_permissions.release_tick | agent_queue scheduled drafts | needs skip | skip added release_one |
| rate_windows_purge | rate_limit.purge_shared | none | not business-scoped | none |
| campaigns_tick | campaigns_router.campaigns_tick | campaigns running | needs skip | exclude() + drop |
| journeys_tick | outreach_journeys.journeys_tick | settings journeys | needs skip | skip added |
| referral_tick | refer_a_friend.rewards_tick | module_entries / referral_rewards | needs skip | skip added |
| texting_registration_sweep | texting_registration.sweep_tick | texting_registrations | needs skip | skip added advance |
| platform_watchdog | platform_watchdog.watchdog_tick | platform health | platform owner only | none |
| trusted_proposals | rules_router._run_trusted_sweep_sync | /businesses limit 500 (no filter) | needs skip | skip added |
| balance_sweep | balance_sweep.sweep_tick | sessions / customer_ledger | needs skip | skip added |
| ledger_anchor_sweep | anchor_scheduler.sweep_tick | ledger_chain_state (paid Hedera) | needs skip | skip added |
| ledger_anchor_upgrade | anchor_scheduler.upgrade_tick | pending proofs | not business-scoped | none |
| lifecycle_emails / welcome_retry / week_beats | lifecycle_emails | is_active=eq.true | covered | none |
| signup_reminders | lifecycle_emails.signup_reminders_tick | users who own no business | not business-scoped | none |
| devotional_daily_texts / morning | devotional_daily._plan | devotional_texts + env allowlist | needs skip | skip added _plan |
| sample_church_cleanup (new) | sample_church.cleanup_tick | is_sample=is.true | new | the daily cleanup, 08:20 UTC |

Not scheduled: nurture_agent.run_nurture_for_all (is_active), first_week (via customer_health, is_active), billing_rehearsal (owner GET, is_active), referrals (router, is_active).
