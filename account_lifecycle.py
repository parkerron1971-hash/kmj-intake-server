"""
account_lifecycle.py — data export + account/business deletion.

Hardening pass 1 (2026-07-03). Closes the two biggest lifecycle gaps
from the business-readiness audit: practitioners had no way to get
their data OUT and no way to delete a business or their account
(GDPR/CCPA portability + erasure).

Endpoints (all require the caller's Supabase JWT):
  GET    /account/export                 → JSON bundle of every owned
                                           business + its core records
  DELETE /account/business/{business_id} → delete ONE owned business
                                           (children first, then the row)
  DELETE /account                        → delete ALL owned businesses,
                                           then the auth user itself

Design notes:
  • Ownership is verified server-side on every call — the service-role
    key does the reads/deletes, but only after confirming
    businesses.owner_id == the JWT's user id.
  • Deletion walks a curated child-table list before removing the
    business row, so it works whether or not each FK is ON DELETE
    CASCADE. Tables that don't exist (migration not run) are skipped.
  • Export mirrors the same table list — what we delete is what we
    export. Keep BUSINESS_CHILD_TABLES in sync when adding tables.
  • Deletions are LOGGED loudly. There is no undo.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import ledger_unlock
import httpx
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Request

from audit_log import LEDGER_EXPORT_SELECT
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("account_lifecycle")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] account: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)

router = APIRouter(prefix="/account", tags=["account-lifecycle"])

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)

# Every table that hangs off a business via business_id. Order matters
# for deletion (children before parents where tables reference each
# other). Missing tables (404) are skipped silently so this list can be
# a superset of any one deployment's schema.
#
# S11 trust audit (2026-07-31): reconciled against the live schema —
# the list had drifted badly since it was written (time_entries,
# customer_ledger, campaigns, the whole GL cluster, the audit/undo
# logs and every 7/2x-era table were missing, so export was incomplete
# and deletion left orphans). "What we delete is what we export" is
# the module's contract; keep BOTH honest by keeping THIS list honest.
#
# Deliberately EXCLUDED (checked, not forgotten):
#   stripe_webhook_events   — platform-global Stripe event-dedup log,
#                             no business_id column.
#   site_events             — anonymous marketing-site traffic, no
#                             business_id by design (privacy).
#   vertical_knowledge      — Feed 2 cross-account learning; has NO
#                             business_id ON PURPOSE (k-anonymity).
#   usage_* / api_usage / product_events / credit grants internals —
#                             platform metering + billing records the
#                             platform must retain for its own books.
#   email_suppressions      — recipient-keyed deliverability protection;
#                             deleting it would let a deleted business's
#                             bounces be re-mailed by the platform.
#   entity_groups           — owner-keyed (owner_id), no business_id
#                             column; consolidation groups die with the
#                             auth user, not with one business.
#   mcp_oauth_* / referrals / waitlist / scheduler_lease / fx_rates /
#   platform_* / inference_cache — platform- or user-keyed, not
#                             business children.
#
# The list above used to be prose only, and prose does not fail a
# test. Every table a migration creates WITH a business_id column now
# has to appear in exactly one of BUSINESS_CHILD_TABLES or
# EXPORT_EXCLUDED (test_export_import pins it, scanning the migrations),
# so the next table someone adds is a decision, not an omission. On
# 2026-09-04 the scan found nine practitioner tables the export had
# never carried — concierge conversations, consent records, the
# business's own document templates, auditor links, push
# subscriptions, the Stripe disputes cache, support-ticket messages,
# and the texting number itself — and sixteen platform-side ones that
# belong here with a reason.

EXPORT_EXCLUDED: Dict[str, str] = {
    "church_keepers": "who keeps a church's guarded areas (church_keys.py): sign-in user ids that can't mean anything in another business; a restored church names its keepers again, and until it does nothing is locked; cascade on business deletion",
    "church_area_keys": "asks for an hour's key to a guarded area and their answers: sign-in user ids and a hashed one-time code, over within a day; nothing to restore; cascade on business deletion",
    "church_duty_holders": "who a church moved each office duty to (church_duties.py): sign-in user ids that can't mean anything in another business; a restored church follows its lanes' defaults until it moves its duties again; cascade on business and login deletion",
    "church_duty_changes": "the log of those moves, from and to as sign-in user ids (church_duties.py): meaningless in another business, and nothing to restore once the moves are gone; cascade on business deletion",
    "church_check_approvals": "each yes a check request has, at its step (church_money_levels.py): sign-in user ids that can't mean anything in another business; the export keeps the requests and where they stand; cascade with the request and on business deletion",
    "church_check_approval_codes": "the one-time codes a board member is emailed to give a yes from the member app (church_money_levels.py): hashed, over in minutes; nothing to restore; cascade with the request, the person and on business deletion",
    "devotional_texts": "who asked for the church's devotional by text each evening (devotional_daily.py): phone numbers and the words they agreed to, given to this account's texting; a restored account must not start texting them, so people sign up again; cascade on business deletion",
    "worship_screens": "each screen's private link (a token); a copied link would show another church's Sunday, so screens are added again after a restore; cascade on business deletion",
    "worship_live": "what was on screen at one moment of a service; nothing to restore; cascade on business deletion",
    "worship_team": "who is on the church's Sunday team: sign-in user ids and invite links (tokens) that can't mean anything in another business; the church invites its team again after a restore; cascade on business deletion",
    "academy_present_sessions": "a class presenting right now: a short-lived TV code and a copy of the slides without teacher notes (the deck itself is exported in academy_decks); expires within hours; cascade on business deletion",
    "chief_rail_practice": "the rail's practice record (chief_rail.py): a records-only answer next to Chief's, for deciding which question shapes may skip the full turn; platform tuning data, derived from records the export already carries; cascade on business deletion",
    "chief_reflection_runs": "nightly brain-pass run log (status, tokens, cost); operations metadata, not the business's content; the digest it wrote is exported in business_brain_versions; cascade on business deletion",
    "square_booking_sync": "temporary Square appointment copies; reconnect and opt in to sync; cascade through square_connections",
    "square_connections": "encrypted Square OAuth credentials and one-time login state; never portable, cascade on business deletion",
    "chief_event_deliveries": "internal worker leases and replay fences; not portable, cascade on business deletion",
    "agentcard_wallets": "encrypted customer OAuth credentials and wallet-bound purchase journal; never portable, cascade on user/business deletion",
    "lane_purchases": "encrypted wallet-bound purchase journal; never portable, cascade on user/business deletion",
    "lane_saved_links": "owner-saved Lane merchant links encrypted under the server key; never portable, cascade on user/business deletion",
    "link_wallet_sessions": "encrypted Link OAuth credentials and pending authorization; never portable, cascade on user/business deletion",
    "chief_link_pilot_sessions": "encrypted private Link OAuth credentials and test journal; never portable, cascade on user/business deletion",
    "business_card_connections": "encrypted third-party OAuth credentials and card preferences; never portable, cascade on business deletion",
    "business_secrets": "encrypted browser credentials; never exported, cascade on business deletion",
    "checkin_stations": "check-in station device tokens and PIN hashes; credentials, never portable — a restored church pairs its tablets again; cascade on business deletion",
    # The stream relay (stream_relay_router.py). The church's stream key is
    # a hash and its YouTube/Facebook keys are ciphertext under this
    # deployment's key: credentials, useless anywhere else. The session
    # rows are the relay's run log; each recording's link travels with
    # the sermon it became, which IS exported.
    "church_streams": "stream key hash and encrypted YouTube/Facebook stream keys; credentials, never portable — a restored church makes a new key; cascade on business deletion",
    "stream_sessions": "the stream relay's run log (when, how long, where the recording is); the recording's link is exported with its sermon; cascade on business deletion",
    # The practitioner's other calendar. The feed link is a credential
    # (it reads their whole calendar), and the busy blocks are re-derived
    # from it on every sync; both cascade with the business.
    "calendar_feeds": "private calendar links (each one reads a whole calendar); never exported, cascade on business deletion",
    "worship_calendar": "the church's calendar link for bringing events onto the announcements board (worship_announce_import.py); like calendar_feeds a secret that reads a whole calendar, so never exported; the church pastes it again after a restore; cascade on business deletion",
    "calendar_busy_blocks": "busy times re-derived from a private calendar link on every sync; cascade on feed/business deletion",
    # Platform books and metering — the platform must keep these for its
    # own accounts, whatever a business does with theirs.
    "usage_grants":            "platform credit grants; platform billing record",
    "usage_notifications":     "platform allowance notices; platform record",
    "usage_stripe_reports":    "platform usage reports to Stripe; platform record",
    "api_usage":               "platform metering",
    "product_events":          "platform product analytics",
    "stripe_webhook_events":   "platform-global Stripe dedup log",
    # Cross-account learning, k-anonymous by design.
    "vertical_knowledge":      "Feed 2 cross-account learning; no per-business rows on purpose",
    "library_gap_log":         "module-library learning; SET NULL on business delete, kept for the platform",
    "inference_cache":         "Arc 20 inference cache; platform-side, regenerable",
    # An employee's SSN is Fernet ciphertext keyed to the platform's
    # TIN_ENCRYPTION_KEY: unreadable outside this deployment, and an
    # SSN must never travel in an export ZIP anyway. Deleting the
    # business cascades employees → this table, so nothing lingers.
    "employee_tax_profiles":   "W-4 + encrypted SSN; never exported, cascades from employees on delete",
    "inference_gate_decisions": "Arc 20 gate decisions; platform-side learning about the gate, not practitioner records",
    "model_route_log":         "Chief routing + first-token telemetry (no content); platform-side tuning data, like api_usage",
    "voice_turn_log":          "call time-to-first-audio telemetry (durations only); platform-side tuning data, like api_usage",
    # Keyed to a person or to the platform, not to a business.
    "email_suppressions":      "recipient-keyed deliverability protection; deleting it re-mails bounces",
    "entity_groups":           "owner-keyed consolidation groups; die with the auth user",
    "mcp_oauth_codes":         "user-keyed OAuth codes; short-lived",
    "member_login_codes":      "member portal sign-in codes (hashed, 10-minute, pruned daily); credentials, not records, cascade on business deletion",
    # A member's Bible highlights and notes are private to the member: the
    # app tells them the church's staff can't read them, and an export
    # the church downloads would. Cascade on member and business deletion.
    "bible_marks":             "a member's own Bible highlights, private notes and saved verses; private to the member (staff can't read them), so never in the church's export; cascade on member/business deletion",
    # The same for a member's devotional days: their journal is private.
    "devotional_progress":     "a member's own devotional days: done, practices ticked and a private journal (staff can't read it), so never in the church's export; cascade on member/business/devotional deletion",
    "member_plan_starts":      "the reading plans and devotionals a member started on their own day; keyed to devotional ids an import re-mints; cascade on member/business deletion",
    "mcp_oauth_refresh":       "user-keyed OAuth refresh tokens",
    "site_events":             "anonymous marketing-site traffic; no business_id by design",
    # The tamper-evident ledger has its own door. audit_log is exported
    # under its own name and erased through the tombstone RPC; the chain
    # state, anchors, tombstones, redactions and their tickets are the
    # evidence that erasure happened, and bulk-deleting evidence of an
    # erasure defeats the ledger. They stay, and ledger_verify reads them.
    "ledger_chain_state":      "tamper-evident ledger: per-business chain head; erased through the ledger's own RPC",
    "ledger_tombstones":       "tamper-evident ledger: proof rows were erased; must outlive the business",
    "ledger_anchors":          "tamper-evident ledger: external anchors; evidence, outlives the business",
    "ledger_anchor_failures":  "tamper-evident ledger: anchor attempts; evidence",
    "ledger_anchor_upgrades":  "tamper-evident ledger: anchor provider upgrades; evidence",
    "ledger_redactions":       "tamper-evident ledger: what was redacted and why; evidence",
    "ledger_redaction_tickets": "tamper-evident ledger: redaction requests; evidence",
    "ledger_erasure_tickets":  "tamper-evident ledger: erasure requests; evidence",
}
BUSINESS_CHILD_TABLES: List[str] = [
    # Board & minutes (church_board.py): decisions and attendance before the
    # items and members they cite, items before their meetings, meetings and
    # members before their boards; all before the contacts and tasks they cite.
    "church_board_decisions", "church_board_attendance", "church_board_items", "church_board_meetings",
    "church_board_members", "church_boards",
    # Help requests (church_help.py): what was given before its request, and
    # both before the Prayer & care asks, contacts and expenses they cite.
    # The fund's settings name nothing by id.
    "church_help_given", "church_help_requests", "church_help_settings",
    # Check requests (church_checks.py): a request cites its person and its
    # expense, so it goes before contacts and expenses. The limit and the
    # budget lines name nothing by id.
    "church_check_requests", "church_check_settings",
    # The church register (church_register.py): each entry cites its people
    # and its Prayer & care ask by id, so it goes before both.
    "church_register_entries",
    # Owner-only account export includes private care and finance history.
    # Erase children before their business, contact and invoice records.
    # A request's private notes go before the request.
    "ministry_care_notes", "ministry_care_requests", "ministry_gift_history",
    # Which givers were emailed a year-end statement; before contacts.
    "giving_statement_sends",
    # Pledges and campaigns (church_pledges.py): each pledge cites a giver
    # and a campaign by id, so pledges go before contacts and campaigns.
    "church_pledges", "church_campaigns",
    # Members' notification devices and choices (before contacts), the log
    # of what the church sent them, and what waits through quiet hours.
    "member_push_subscriptions", "member_push_prefs", "member_push_sends", "member_push_held",
    # Who was at each occasion; before module_entries and contacts.
    "attendance", "attendance_headcounts",
    # Which days of the reading plan each member has read; before contacts.
    "reading_progress",
    # The church's own devotionals, their days inside each row (members'
    # days cascade with them; see EXPORT_EXCLUDED).
    "devotionals",
    # The church's song library for Sunday screens: each song's words,
    # orders and how often it was sung. Nothing points at it.
    "worship_songs",
    # Sunday teams and who serves when (sunday_planning.py): each ask and
    # its answer, who's trained on each place, who's away, the places and
    # the teams' turns, all before the services they're for, the teams'
    # groups and contacts (see _IMPORT_SKIP).
    "serve_notes", "serve_assignments", "serve_trained", "serve_away", "serve_prefs", "serve_positions", "serve_teams",
    # Sundays on screens: the services (their order, notes and the songs
    # they point at; see _IMPORT_SKIP) and the look every slide wears.
    "worship_services", "worship_settings",
    # The church's pictures and videos for Sunday's screens: the rows (name,
    # type, size, link); the files themselves are in business-assets. Not
    # re-imported (see _IMPORT_SKIP).
    "worship_media",
    # The announcements board: each announcement's words, dates, design and
    # QR code. Not re-imported (see _IMPORT_SKIP).
    "worship_announcements",
    # The ministries that send announcements by a link: each one's name, its
    # leader and the leader's email. Not re-imported (see _IMPORT_SKIP).
    "worship_ministries",
    # Families and children: notes, pickups and children before their
    # household, and the household's adult links before contacts.
    "child_checkins",
    # News (church_news): reports, Loves and comments before their posts,
    # reactions and who saw a post before it, the posts (which may be for
    # one group) and the people who post to the whole church — all before
    # groups and contacts.
    "church_post_reports", "church_post_comment_loves", "church_post_comments", "church_post_reactions",
    "church_post_seen", "church_posts", "church_news_posters",
    # Celebrations (celebrations.py): what each member said yes to, and a
    # couple's anniversary — both before contacts.
    "member_celebrations", "member_anniversaries",
    # The week's news by email (news_alerts): which week each person got
    # it — before contacts.
    "church_news_digests",
    # Groups: who saw each Board post, the posts and who's asking to join
    # (member_portal_groups), who came to each meeting, the meetings, the
    # roster, then the groups — all before contacts.
    "group_post_seen", "group_posts", "group_join_requests", "group_prayer_marks", "group_prayers", "group_rsvps",
    "group_bring", "group_studies", "group_live_sessions", "group_meeting_guests", "group_meeting_attendance", "group_meetings", "group_members", "groups",
    "sermons", "sermon_series",   # sermons before the series they point at
    # Live: chat, pauses and presence before their session; all before
    # contacts and module_entries.
    "live_chat", "live_mutes", "live_presence", "live_sessions",
    # Messaging: reports, staff looks, reactions, messages, people and blocks
    # before their chats; links and switches before contacts.
    "msg_reports", "msg_staff_views", "msg_reactions", "msg_poll_votes", "msg_polls", "msg_photos", "msg_messages", "msg_participants", "msg_blocks", "msg_threads",
    "msg_guardians", "msg_members", "msg_safety_officers", "msg_member_officers",
    # Youth and Kids spaces: leaders' posts and the office's leader
    # approvals (with background-check dates); before contacts.
    "space_posts", "space_leaders",
    # Leaders & follow-up: notes before their follow-up; follow-ups and
    # the leaders' roles before contacts. The role library (each role's
    # title, job and chain) and its settings name no contact.
    "church_follow_up_notes", "church_follow_ups", "church_leader_roles",
    "church_role_defs", "church_role_settings",
    # The map (church_areas): which area the church put a role or a team in.
    # It names no contact and cites role keys and team names, not ids, so
    # it restores as it is.
    "church_area_places",
    # Rooms & spaces (church_spaces): the bookings before the spaces they're
    # in, and before the contacts and invoices (a rental's bill) they cite.
    "church_space_bookings", "church_spaces",
    # Event sign-ups (church_event_signups): who signed up, what they paid
    # and their answers, then the ticket types and each event's setup, all
    # before the contacts and module entries (events) they cite.
    "church_event_registrations", "church_event_ticket_types", "church_event_signup_setups",
    # Sunday check-in's service (day, time, how long it stays open): no
    # contact, nothing it cites; a restored church keeps its Sunday.
    "church_checkin_settings",
    # Shepherding: touches and who-shepherds-whom before the families and
    # contacts they cite; the proposal, "Not a family" and the settings
    # name no row a foreign key holds.
    "church_shepherd_touches", "church_shepherds", "church_shepherd_drafts", "church_family_dismissals",
    "church_shepherd_settings",
    # Shepherding, round 2: a drifting family's signal cites its household;
    # the sent-once ledger of emails cites nothing.
    "church_shepherd_signals", "church_shepherd_notices",
    "child_care_notes", "household_pickups", "children", "household_adults", "households",
    "chief_errand_events", "chief_errands",  # preserve history; events before errands
    "agent_assignments",      # before connected_agents (foreign key)
    "connected_agents",       # bot profiles; no live credentials in this table
    # Connection metadata travels with the business; credentials never do.
    # Remove devices first so workers lose access before jobs are erased.
    "connected_ai_devices", "connected_ai_pairings",
    "creative_director_profiles",  # preserve owner preferences before deleting their source artwork
    "image_publications", "image_artworks",  # publication records reference originals
    "video_jobs", "video_messages", "video_revisions", "video_assets", "video_projects",
    "media_clip_runs",        # Find my best clips runs; before the recordings they reference
    "media_assets",
    "growth_events",         # references contacts; export history before erasure
    "growth_records",         # reporting settings, actions, costs and invoice credit
    "events",
    "agent_queue",
    "agent_runs",             # MCP agent access trail (business-scoped)
    "mcp_tokens",             # business-scoped agent tokens
    "chief_memories",
    "business_operating_profile_history",
    "program_outcome_reports",
    "business_financial_policies",
    "business_financial_account_locks",
    "business_financial_policy_history",
    "business_operating_profiles",
    "chief_conversations",
    "chief_activity",
    "chief_assignments",      # the outcomes they handed Chief + its moves log (9/4)
    "chief_cases",            # problems Chief diagnosed, forecasts and results (10/5)
    "chief_moves",            # what came of each of Chief's moves (9/4)
    "business_brain_versions",  # each distinct brain the business had: exported, so the brain travels with the business (10/11)
    "chief_proposals",
    "chief_bookkeeping_proposals",
    "chief_learning_signals",
    "chief_patterns",
    "chief_playbooks",
    "chief_templates",
    "chief_actions",
    "chief_suggestions",
    "chief_notifications",
    "chief_jobs",             # beta-readiness audit: was surviving deletion
    "chief_scheduled_actions",
    "chief_insights",
    "chief_undo_log",
    "insights",
    "notifications",
    "sessions",
    "tasks",
    # Rules/automation — runs reference their rule.
    "rule_runs",
    "practitioner_rules",
    # Campaigns — sends reference campaigns AND contacts.
    "campaign_sends",
    "campaigns",
    # Message content — MUST precede the thread/parent tables below so
    # their NO-ACTION foreign keys don't 409 the delete mid-way.
    "sms_messages",
    "sms_consents",
    "sms_keywords",
    "sms_bindings",
    "sms_opt_outs",
    "email_replies",
    # The texting number itself. Exported so the record says which line
    # was theirs; on delete the line is handed back to the provider FIRST
    # (_release_sms_lines) — a cascade would drop the row and leave the
    # number billing the platform forever.
    "sms_numbers",
    # Conversations the site concierge had with visitors (references
    # contacts), and the consent a client gave (the record a dispute
    # turns on — it goes with the business that holds it).
    "concierge_conversations",
    "consent_records",
    # Money ABOUT the business — ledgers before the rows they cite.
    "customer_ledger",        # references contacts, invoices, offerings
    "time_entries",           # references contacts
    "invoices",
    "bills",
    "orders",
    "order_items",
    "credit_ledger",
    "business_expenses",
    "business_budgets",
    "category_rules",
    "offerings",
    "documents",
    "esign_documents",
    "foundation_documents",
    "projects",
    "products",
    "intake_forms",
    "custom_modules",
    "module_records",
    # Children of a module ENTRY, listed before it so the export carries
    # them and the delete never trips an FK. Both cascade at the DB level
    # too; the list is what makes them EXPORTABLE, which is the half a
    # cascade cannot do.
    #
    # deadlines was missing entirely — a pre-existing gap found while
    # adding grant_budget_lines. Its business_id cascades, so erasure was
    # never leaking rows, but "what we delete is what we export" was
    # quietly untrue for every lawyer's docket.
    "grant_budget_lines",
    "deadlines",
    "module_entries",
    "module_specs",
    # Restricted (clinical/giving) class — entries + their access trail.
    "restricted_module_access_log",
    "restricted_module_entries",
    "business_sites",
    "site_chat_history",
    "site_content_overrides",
    "business_profiles",
    "business_customers",
    "social_accounts",
    "social_posts",
    # Which social accounts the business connected through Post for Me —
    # display fields only, no tokens (social_connect_router).
    "social_connections",
    # Posts the business sent through Post for Me, with how each went.
    "social_publications",
    # The marketing desk (APPLY-2026-10-07-marketing-suite.sql). Clicks and
    # the audit trail before the posts they cite; posts before the weekly
    # runs they belong to; the desk's settings last. All cascade with the
    # business too; listing them is what makes them EXPORTABLE.
    "marketing_post_events",
    "marketing_link_clicks",
    # Tracked links on texts and emails (APPLY-2026-10-09-marketing-links.sql):
    # their clicks before the links they count.
    "marketing_link_hits",
    "marketing_links",
    # The notes Outreach journeys sent (APPLY-2026-10-09-journeys.sql).
    "journey_sends",
    # The business's offers (APPLY-2026-10-10-offers.sql).
    "offers",
    # Refer a friend: each client's code and the thank-yous made
    # (APPLY-2026-10-11-refer-a-friend.sql).
    "referral_links",
    "referral_rewards",
    # The business's texting registration answers (APPLY-2026-10-11-texting-registrations.sql).
    "texting_registrations",
    "marketing_posts",
    "marketing_runs",
    "marketing_desks",
    "design_rationales",
    "design_feedback",
    "goals",
    "growth_milestones",
    "growth_objectives",
    "strategy_tracks",
    "business_tracks",
    # The day-one arc. Cascades on business delete already; listing it is
    # what makes it EXPORTABLE, which is the half a cascade cannot do.
    "first_run_arc",
    # Ticket messages reference their ticket.
    "support_ticket_messages",
    "support_tickets",
    "workflows",
    "workflow_definitions",
    # Academy — lessons/enrollments reference courses; a lesson's edited
    # slides reference the lesson. A program (The Making) is the business's
    # own series of classes; its tracks are rows keyed by course id. A
    # class's schedule (homework, gatherings) hangs off its lessons.
    "academy_decks",
    "academy_schedule_items",
    "academy_lessons",
    "academy_enrollments",
    "academy_courses",
    "academy_programs",
    "bank_accounts",
    "bank_transactions",
    "plaid_accounts",
    "plaid_items",
    "plaid_transactions",
    # A statement's rows (plaid_transactions.statement_import_id) go before it.
    "bank_statement_imports",
    # The Sunday match (giving_deposits.py): items before their match.
    "gift_deposit_items",
    "gift_deposit_matches",
    # A business's own expense categories: names and their line, portable.
    "expense_categories",
    # Its own names for the lines of its books, and lines of its own.
    "expense_lines",
    # Giving by service (giving_services.py): a count cites its service, a
    # sheet photo its count (the photos themselves are in giving-sheets).
    "giving_count_photos",
    "giving_counts",
    "giving_services",
    "reconciliations",
    "connectors",
    # GL cluster — queue/alarms/pushed-entries cite journal entries, so
    # they go first; periods and the chart go after the entries that
    # cite them; the QuickBooks connection row goes last of the cluster.
    "gl_sync_queue",
    "gl_divergence_alarms",
    "gl_admin_actions",
    "quickbooks_pushed_entries",
    "journal_entries",
    "ledger_entries",
    "ledger_accounts",
    "period_edit_overrides",  # references accounting_periods
    "accounting_periods",
    "coa_external_mappings",  # references chart_of_accounts rows
    "chart_of_accounts",
    "quickbooks_connections",
    # Pay your team (2026-09-05): line items reference runs and
    # employees; runs reference employees through the items. The W-4
    # profile (SSN ciphertext) is NOT exported — see EXPORT_EXCLUDED —
    # and cascades from employees on delete.
    # A minister's housing allowance (housing_allowance.py): entries before
    # their allowance, and both before the employees, people and Board
    # decisions an allowance names (those links set null on delete anyway).
    "minister_housing_entries",
    "minister_housing_allowances",
    # Funds for the year (funds.py): placements before their fund.
    "business_fund_items",
    "business_funds",
    "pay_run_items",
    "pay_runs",
    "employees",
    # Payroll/contractors — transfers reference contractors.
    "outbound_transfers",
    "payroll_interest",
    "contractors",
    "email_threads",
    "sms_threads",
    # The business's own document templates, the auditor links it
    # issued, the devices it pushes to, and Stripe's disputes as cached
    # for it — each keyed to the business and each part of its record.
    "business_doc_templates",
    "auditor_links",
    "push_subscriptions",
    "stripe_disputes_cache",
    # Team seats + invites die with the business.
    "business_users",
    "business_collaborators",
    "invite_tokens",
    "contacts",          # after the tables that reference contacts
    # THE LEDGER GOES LAST, on purpose. Deleting the business row
    # cascades into audit_log, and audit_log's append-only trigger
    # refuses that cascade — so the ledger must already be erased (via
    # the tombstone-writing RPC in _delete_table_rows) by the time the
    # business row is removed. Erasing it last also shrinks the window
    # in which some other writer appends a row that would re-block the
    # cascade; if that race ever fires, the business delete 502s loudly
    # and a retry re-runs the erasure. Failing closed is correct here.
    "audit_log",
]

# User-scoped tables (keyed by user_id, not business_id) — cleaned up in
# delete_account only, since they belong to the person, not a business.
USER_CHILD_TABLES: List[str] = [
    "push_subscriptions",
    "user_profiles",
]

# Supabase Storage buckets holding business-scoped files (logos, brand,
# site assets, receipt photos, digital product files). Objects are
# stored under a "{business_id}/…" prefix; business-documents nests one
# level deeper ("{business_id}/receipts/…") and product-files likewise
# ("{business_id}/{offering_id}/…"), which _delete_storage_objects
# handles by descending one folder level.
STORAGE_BUCKETS: List[str] = ["image-originals", "business-assets", "business-documents",
                              "product-files", "program-media", "video-studio",
                              # Students' homework files: "{business_id}/{course_id}/…".
                              "academy-work",
                              # Count sheet photos (giving_sheets.py): "{business_id}/{count_id}/…".
                              # Donors' names, amounts and check numbers: they go with the church.
                              "giving-sheets"]


def _service_headers() -> Dict[str, str]:
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


async def _owned_businesses(client: httpx.AsyncClient, user_id: str) -> List[Dict[str, Any]]:
    r = await client.get(
        f"{SUPABASE_URL}/rest/v1/businesses",
        headers=_service_headers(),
        params={"owner_id": f"eq.{user_id}", "select": "*"},
    )
    if r.status_code >= 400:
        raise HTTPException(502, f"Failed to load businesses: {r.text[:200]}")
    return r.json() or []


# audit_log is the one table this export does not take wholesale. Its
# payload/result columns hold copies of the records an action touched,
# and the ledger's standing invariant is that no surface returns them —
# an invariant only worth having if it has no quiet exceptions. Nothing
# is lost: the tables those copies were made FROM travel in the same
# export under their own names, and the hash columns come along so the
# chain stays independently verifiable. See audit_log.LEDGER_EXPORT_SELECT.
_TABLE_SELECT = {"audit_log": LEDGER_EXPORT_SELECT}
from media_library import PUBLIC_COLUMNS as MEDIA_EXPORT_COLUMNS
_TABLE_SELECT['media_assets'] = MEDIA_EXPORT_COLUMNS
# A devotional without its day count (the database works it out, and won't
# take one) or its Listen files (made again from the words after a restore).
_TABLE_SELECT['devotionals'] = (
    'id,business_id,title,kind,author,about,practices,days,starts_on,voice,status,published_at,created_at,updated_at'
)
_TABLE_SELECT['connected_ai_devices'] = (
    'id,business_id,owner_id,provider,label,state,last_seen_at,expires_at,revoked_at,created_at'
)
_TABLE_SELECT['connected_ai_pairings'] = (
    'id,business_id,owner_id,provider,expires_at,consumed_at,created_at'
)


# One page of a table, and the ceiling past which we stop and SAY SO.
#
# The old code asked for limit=10000 and returned whatever came back.
# Nothing paginated and nothing checked, so a business with more than
# 10,000 rows in any table exported the first 10,000 and reported
# success — while deletion, which has no such cap, removed all of them.
# "What we delete is what we export" is this module's stated contract,
# and that made it false in the one direction that cannot be undone.
#
# No table is over the cap today (largest business-scoped table in
# production is ~3k rows), so this was a loaded gun rather than active
# loss. It fires the first time a busy practitioner's events table grows
# up.
_EXPORT_PAGE = 1000
_EXPORT_MAX_ROWS = 500_000


async def _fetch_table(client: httpx.AsyncClient, table: str, business_id: str
                       ) -> Tuple[List[Dict[str, Any]], bool]:
    """Every row of `table` for this business, and whether that is ALL of
    them.

    Returns (rows, complete). `complete` is False only when the safety
    ceiling was reached — and the caller writes that into the export
    document, because a portability file that is quietly partial is
    worse than one that admits it. A missing table (404) or one with no
    business_id column returns ([], True): nothing to export is not the
    same as failing to export.
    """
    rows: List[Dict[str, Any]] = []
    offset = 0
    while True:
        r = await client.get(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers=_service_headers(),
            params={"business_id": f"eq.{business_id}",
                    "select": _TABLE_SELECT.get(table, "*"),
                    "order": "business_id",     # stable paging order
                    "offset": str(offset), "limit": str(_EXPORT_PAGE)},
        )
        if r.status_code >= 400:
            # First page failing means the table is absent or unscoped —
            # expected, and not an incomplete export. A LATER page
            # failing is a real fault and must not look like the end of
            # the data.
            if offset == 0:
                return [], True
            logger.error("export: %s page at offset %d failed (%s) — "
                         "marking incomplete", table, offset, r.status_code)
            return rows, False
        page = r.json() or []
        rows.extend(page)
        if len(page) < _EXPORT_PAGE:
            return rows, True
        offset += _EXPORT_PAGE
        if len(rows) >= _EXPORT_MAX_ROWS:
            logger.error("export: %s hit the %d-row ceiling for %s",
                         table, _EXPORT_MAX_ROWS, business_id)
            return rows, False


async def _erase_ledger(client: httpx.AsyncClient, business_id: str,
                        requested_by: str = "account_erasure") -> int:
    """The ONE sanctioned removal path for the action ledger.

    audit_log is append-only at the DATABASE level now — a plain DELETE
    raises, including the cascade from deleting the business row. GDPR
    still beats append-only, but never silently: this RPC writes a
    ledger_tombstones row (count + sequence range + the prior chain hash)
    BEFORE removing anything, and deliberately does not reset
    ledger_chain_state, so the erased range stays visible afterwards as a
    gap the tombstone explains.
    """
    try:
        r = await client.post(
            f"{SUPABASE_URL}/rest/v1/rpc/ledger_erase_business",
            headers=_service_headers(),
            json={"p_business_id": business_id, "p_reason": "gdpr_erasure",
                  "p_requested_by": requested_by})
        if r.status_code >= 400:
            logger.error(f"ledger erasure failed for {business_id}: {r.text[:300]}")
            return 0
        return int(r.json() or 0)
    except Exception as e:
        logger.error(f"ledger erasure raised for {business_id}: {e}")
        return 0


# Tables whose rows have no `id` column: the delete asks for a column that
# exists, or PostgREST answers 400 and the delete is skipped as "missing".
_DELETE_SELECT = {
    "marketing_desks": "business_id",       # keyed by the business
    "marketing_link_clicks": "post_id",     # keyed by (post_id, day)
    "marketing_link_hits": "link_id",       # keyed by (link_id, day)
}


async def _delete_table_rows(client: httpx.AsyncClient, table: str, business_id: str) -> int:
    # audit_log never takes the plain path — see _erase_ledger.
    if table == "audit_log":
        return await _erase_ledger(client, business_id)
    r = await client.delete(
        f"{SUPABASE_URL}/rest/v1/{table}",
        headers={**_service_headers(), "Prefer": "return=representation"},
        params={"business_id": f"eq.{business_id}", "select": _DELETE_SELECT.get(table, "id")},
    )
    if r.status_code >= 400:
        # 404/42P01 table missing, or no business_id column — skip.
        return 0
    try:
        return len(r.json() or [])
    except Exception:
        return 0


# ─── Export ─────────────────────────────────────────────────────────────

@router.get("/export")
async def export_account(user: AuthedUser = Depends(require_user)):
    """Everything the practitioner owns, as one JSON document. The
    frontend offers it as a file download. Portability first — pretty
    formats can come later; JSON is complete and machine-readable."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        businesses = await _owned_businesses(client, user.id)
        out: Dict[str, Any] = {
            # 2 — rows are paginated rather than capped at 10,000, and
            # every bundle now carries row_counts plus an explicit
            # `complete` flag. An importer can tell v1 (which may be
            # silently short) from v2 (which says so).
            "export_version": 2,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "user": {"id": user.id, "email": user.email},
            "businesses": [],
        }
        for biz in businesses:
            bundle: Dict[str, Any] = {"business": biz, "tables": {},
                                      "row_counts": {}, "complete": True,
                                      "incomplete_tables": []}
            for table in BUSINESS_CHILD_TABLES:
                rows, complete = await _fetch_table(client, table, biz["id"])
                if rows:
                    bundle["tables"][table] = rows
                    # Counts ride along so a recipient can check what
                    # they got against what we said we sent, without
                    # trusting either of us.
                    bundle["row_counts"][table] = len(rows)
                if not complete:
                    bundle["complete"] = False
                    bundle["incomplete_tables"].append(table)
            out["businesses"].append(bundle)
    logger.info(f"export user={user.id} businesses={len(out['businesses'])}")
    return out


# ─── Import ─────────────────────────────────────────────────────────────
#
# An export nobody can import is a file, not portability. This restores a
# bundle from GET /account/export into a NEW business owned by the caller.
#
# THE THREE RULES IT WILL NOT BEND
#
# 1. NEVER into an existing business. Merging an export into live data
#    means deciding what wins on every conflicting row, and getting that
#    wrong destroys the thing they were trying to protect. A fresh
#    business has nothing to lose an argument with.
# 2. Row ids are NOT reused. They may already exist here — a bundle can
#    be imported twice, or back into the account it came from — and
#    reusing them would either collide or silently overwrite. New ids
#    are minted and business_id is remapped.
# 3. It reports every table it could not restore. A partial import that
#    claims success is how somebody finds out three months later that
#    their invoices never came back.
#
# WHAT IT DELIBERATELY DOES NOT IMPORT
#
#   audit_log      the ledger is append-only, sequence-numbered per
#                  tenant and hash-chained. Rows imported into a new
#                  business would take new sequences and break the chain
#                  they exist to prove. History belongs to the business
#                  that lived it; the export keeps it readable.
#   agent_runs,    operational logs of a system this is not.
#   chief_jobs
#   mcp_tokens     live credentials. Re-importing them would resurrect
#                  access somebody may have revoked.
#
# Storage FILES are not covered either — the export is JSON and the
# documents live in S3. Stated here rather than discovered later.

_IMPORT_SKIP = {
    # Private archives retain original contact/form/invoice identifiers; the
    # generic importer cannot safely remap them or recreate audit evidence.
    # They remain in the owner archive and are explicitly reported as skipped.
    "ministry_care_notes", "ministry_care_requests", "ministry_gift_history",
    "giving_statement_sends",  # a send log: a restore must not claim statements went out
    # A pledge cites its giver and its campaign by id, which the importer
    # re-mints; the export keeps them, and the restored church records its
    # pledge cards again. Campaigns name nothing by id, so they restore.
    "church_pledges",
    # A deck is keyed by its lesson's original id, which the importer re-mints;
    # restored lessons rebuild their slides from the lesson text instead.
    "academy_decks",
    # A program's tracks are keyed by the original course ids, which the
    # importer re-mints; the shelf offers the program again from the
    # classes' series names ("The Making: …") after a restore.
    "academy_programs",
    # A schedule item is keyed by its class's and lesson's original ids,
    # which the importer re-mints; it stays in the owner archive, and the
    # restored class is scheduled again (or Chief drafts it again).
    "academy_schedule_items",
    # Members' phones are devices, not records (like push_subscriptions);
    # the send log must not claim a restored church already notified anyone,
    # and a note that waited through last night's quiet hours isn't news.
    "member_push_subscriptions", "member_push_prefs", "member_push_sends", "member_push_held",
    "chief_errand_events", "chief_errands",  # never restore execution authority or private frames
    "connected_agents", "agent_assignments",  # execution authority must never be restored from a file
    # Preserve the archive, but never restore paid job state, publication
    # claims or private storage paths tied to the original business.
    "creative_director_profiles",  # source/logo IDs belong to the original private gallery; remember again after restore
    "image_publications", "image_artworks",
    "video_jobs", "video_messages", "video_revisions", "video_assets", "video_projects",
    "media_clip_runs",  # paid job state, like video_jobs
    "media_assets",  # media files and review proofs need an explicit restore
    # Derived snapshots and security decisions cannot be recreated from an
    # untrusted uploaded bundle. Export preserves them for reference; reports
    # must be recalculated and approved against the restored source records.
    "program_outcome_reports", "business_financial_policies",
    "business_financial_account_locks", "business_financial_policy_history",
    "audit_log", "agent_runs", "chief_jobs", "mcp_tokens",
    # A restored archive must pair fresh devices, never resurrect access.
    "connected_ai_devices", "connected_ai_pairings",
    # Growth history and JSON records cite original contact/invoice/campaign
    # IDs. The generic importer mints new IDs without a reference map; copying
    # these would attach evidence to another business's records. Preserve the
    # full export, report the skipped restore, and keep fresh history coverage.
    "growth_events", "growth_records",
    # Attendance cites original occasion and contact ids; same reason.
    "attendance", "attendance_headcounts",
    # Families link contacts and each other by id; same reason. The export
    # keeps them (children's allergies included) for the owner.
    "households", "household_adults", "children", "household_pickups", "child_care_notes",
    "child_checkins",
    # Groups link contacts and each other by id; same reason. So do a
    # group's Board posts, who saw them, and who asked to join.
    "groups", "group_members", "group_meetings", "group_meeting_attendance", "group_live_sessions",
    "group_join_requests", "group_posts", "group_post_seen", "group_prayers", "group_prayer_marks", "group_rsvps",
    "group_bring", "group_studies", "group_meeting_guests",
    # The church's news cites people, groups, posts and comments by id;
    # same reason.
    "church_posts", "church_post_reactions", "church_post_seen", "church_post_comments",
    "church_post_comment_loves", "church_post_reports", "church_news_posters",
    # Celebrations cite people by id; same reason.
    "member_celebrations", "member_anniversaries",
    # The week's email log cites people by id; same reason.
    "church_news_digests",
    # Sermons cite their series by id; same reason.
    "sermon_series", "sermons",
    # Live sessions, chat and presence cite contacts and occasions by id;
    # same reason.
    "live_sessions", "live_chat", "live_mutes", "live_presence",
    # Messaging cites people, groups and messages by id; same reason. Safety
    # officers are team logins, not records.
    "msg_threads", "msg_participants", "msg_messages", "msg_blocks", "msg_reports", "msg_staff_views",
    "msg_guardians", "msg_members", "msg_safety_officers", "msg_reactions", "msg_polls", "msg_poll_votes", "msg_photos",
    # A member officer cites a contact by id; a restored church names its
    # officers again.
    "msg_member_officers",
    # Youth and Kids leaders and their posts cite contacts by id; same
    # reason. A restored church approves its leaders again.
    "space_leaders", "space_posts",
    # Leaders & follow-up cite people (the person, the leader) and each
    # other by id; same reason. A restored church names its leaders again.
    # Its roles cite each other (the chain) and a class by id; a restored
    # church's library fills again the first time Leaders & roles opens.
    "church_follow_up_notes", "church_follow_ups", "church_leader_roles",
    "church_role_defs", "church_role_settings",
    # Shepherding cites families and shepherds by id, a proposal cites
    # families and members by id, and "Not a family" is a hash of member
    # ids; same reason. A restored church keeps its shepherding settings
    # and asks Chief for families and a proposal again.
    "church_shepherd_touches", "church_shepherds", "church_shepherd_drafts", "church_family_dismissals",
    # A drifting family's signal cites its household by id; the emails'
    # sent-once ledger names shepherds and follow-ups by id. A restored
    # church's sweep starts its watch again.
    "church_shepherd_signals", "church_shepherd_notices",
    # A booking cites its space, the person it's for and a rental's bill by
    # id; same reason. A restored church keeps its list of spaces (they cite
    # nothing) and books them again.
    "church_space_bookings",
    # A board's members cite its people and logins by id; its meetings,
    # agenda items (carried from one another, linked to tasks), attendance
    # and decisions cite each other by id; same reason. The export keeps the
    # minutes; a restored church keeps its boards and names their members
    # again.
    "church_board_decisions", "church_board_attendance", "church_board_items", "church_board_meetings",
    "church_board_members",
    # A help request cites its person and its Prayer & care ask by id, and
    # help given cites its request and its expense; same reason. The export
    # keeps them; a restored church keeps its fund's settings.
    "church_help_given", "church_help_requests",
    # A housing allowance cites its minister's person, payroll employee and
    # Board decision by id, and its entries cite it and their pay run or bank
    # row; same reason. The export keeps them all; the owner records the
    # year's allowance again after a restore.
    "minister_housing_entries", "minister_housing_allowances",
    # A fund's placements cite bank transactions by id, which a restored
    # bank link gives new ids; same reason. The export keeps them; a
    # restored church places them again.
    "business_fund_items",
    # A statement added to the books cites its bank account by id, which a
    # restored bank link gives new ids; same reason. The export keeps them; a
    # restored church adds its statements again.
    "bank_statement_imports",
    # A Sunday match cites gifts and bank rows by id, which a restore re-mints
    # or a restored bank link renews; same reason. The export keeps them; a
    # restored church matches its deposits again.
    "gift_deposit_items", "gift_deposit_matches",
    # Giving by service: a gift cites its count and a count its service by
    # id; the export keeps them, and a restored church sets its services
    # again (its gifts come back without a count; see the import).
    "giving_counts", "giving_services",
    # A sheet photo cites its count and the file under the old business's
    # storage prefix; the export keeps the rows.
    "giving_count_photos",
    # A check request cites its person and its expense by id; same reason.
    # The export keeps them; a restored church keeps its limit and budget
    # lines. (Receipts live in business-documents under the church's own
    # folder, which deleting the account empties one level down.)
    "church_check_requests",
    # A register entry cites its people and its Prayer & care ask by id;
    # same reason. The export keeps the whole register.
    "church_register_entries",
    # Event sign-ups cite their event (a module entry) and the person by id,
    # and a setup and its ticket types cite the event; the importer re-mints
    # those ids, so the export keeps them and a restored church sets its
    # sign-ups up again. A paid sign-up's money stays in Stripe either way.
    "church_event_registrations", "church_event_ticket_types", "church_event_signup_setups",
    # A texting number belongs to the provider account that bought it;
    # a restored business provisions its own. Auditor links and push
    # subscriptions are credentials and devices, not records. The
    # disputes cache is Stripe's, re-fetched on demand.
    "sms_numbers", "auditor_links", "push_subscriptions", "stripe_disputes_cache",
    # A social connection points at an account held at Post for Me, and one
    # account belongs to one business (unique provider id). A restored
    # business signs in to its networks again rather than copying pointers.
    "social_connections",
    # Its posts point at those connections and at Post for Me post ids;
    # they are history in the export, not something to re-send.
    "social_publications",
    # Marketing history: weekly runs, posts (approvals, accounts, publication
    # ids), their clicks and audit trail. History in the export; a restored
    # business must never resend or re-approve from a file.
    "marketing_runs", "marketing_posts", "marketing_link_clicks", "marketing_post_events",
    # The tracked links on texts and emails, and their clicks: history too.
    "marketing_links", "marketing_link_hits",
    # The journeys' sent notes: history, never re-sent from a file.
    "journey_sends",
    # Offers: a restored business makes its offers again (the codes and their
    # rules are its own decisions); the export keeps them for reference.
    "offers",
    # Refer a friend: codes and thank-yous name contacts by id, and a restore
    # gives contacts new ids; the export keeps them for reference.
    "referral_links", "referral_rewards",
    # A texting registration belongs to the business Twilio approved; a
    # restored business registers again. The export keeps the answers.
    "texting_registrations",
    # The desk's settings are not restored either (review of #1307): an
    # uploaded file could switch the weekly plan on or name another
    # business's accounts and photos. The owner sets the desk up again; the
    # export keeps the old settings for reference.
    "marketing_desks",
    # A service's items point at song ids the import mints anew; the
    # services stay in the archive, readable, and are planned again.
    "worship_services",
    # Who serves when cites people, services, places and teams by id; the
    # export keeps it, and the church schedules again after a restore.
    "serve_notes", "serve_assignments", "serve_trained", "serve_away", "serve_prefs", "serve_positions", "serve_teams",
    # Rows that point at files under the OLD business's storage prefix; a
    # copy would show another account's files and lose them when it goes.
    # An announcement's picture is one of those files.
    "worship_media", "worship_announcements",
    # A ministry's link is signed for its row; a restore would mint new rows
    # and new links, so the church adds its ministries again and sends them.
    "worship_ministries",
}

# Columns the platform owns. Carrying them across would let an import
# assert its own billing state, or claim rows the hash chain wrote.
_IMPORT_STRIP = {"id", "business_id", "created_at", "sequence",
                 "prev_hash", "row_hash", "verb_registered", "redacted_at"}


class ImportBody(BaseModel):
    bundle: Dict[str, Any]
    business_name: Optional[str] = None


@router.post("/import")
async def import_account(body: ImportBody,
                         user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Restore ONE business bundle into a new business owned by the caller."""
    bundle = body.bundle or {}
    version = bundle.get("export_version")

    # v1 exports could be silently short — they capped every table at
    # 10,000 rows with no pagination and no flag. Importing one is
    # allowed, because refusing somebody their own data would be worse,
    # but the response says what it is rather than letting a partial
    # restore look complete.
    warnings: List[str] = []
    if version == 1:
        warnings.append(
            "this export predates pagination: any table with more than "
            "10,000 rows was silently truncated when it was written")
    elif version != 2:
        raise HTTPException(400, "unsupported export_version")

    businesses = bundle.get("businesses") or []
    if len(businesses) != 1:
        # One at a time, on purpose: a failure halfway through three
        # businesses leaves a mess nobody can reason about.
        raise HTTPException(
            400, "import one business at a time - send a single-business bundle")

    src = businesses[0] or {}
    src_biz = src.get("business") or {}
    if src.get("complete") is False:
        bad = ", ".join(src.get("incomplete_tables") or []) or "unknown tables"
        warnings.append("the export declares itself incomplete: " + bad)

    name = (body.business_name or src_biz.get("name") or "Imported business")

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        created = await client.post(
            SUPABASE_URL + "/rest/v1/businesses",
            headers={**_service_headers(), "Prefer": "return=representation"},
            json={"name": str(name)[:200], "owner_id": str(user.id),
                  "type": src_biz.get("type"),
                  "settings": src_biz.get("settings") or {}},
        )
        if created.status_code >= 400:
            logger.error("import: business create failed: %s", created.text[:300])
            raise HTTPException(502, "could not create the business to import into")
        made = created.json() or []
        row0 = made[0] if isinstance(made, list) and made else made
        new_id = str((row0 or {}).get("id") or "")
        if not new_id:
            raise HTTPException(502, "the new business came back without an id")

        restored: Dict[str, int] = {}
        skipped: Dict[str, str] = {}
        # Deletion runs children-first, so restoration runs parents-first.
        for table in reversed(BUSINESS_CHILD_TABLES):
            if table in _IMPORT_SKIP:
                skipped[table] = "not portable by design"
                continue
            src_rows = (src.get("tables") or {}).get(table) or []
            if not src_rows:
                continue
            payload = []
            for r in src_rows:
                if not isinstance(r, dict):
                    continue
                # A row added from a bank statement cites the statement, which
                # isn't restored (_IMPORT_SKIP): it comes back with it, never
                # pointing at nothing.
                if table == "plaid_transactions" and r.get("statement_import_id"):
                    continue
                clean = {k: v for k, v in r.items() if k not in _IMPORT_STRIP}
                # A gift's service count isn't restored (_IMPORT_SKIP): the
                # gift comes back, in no count.
                if table == "invoices":
                    clean.pop("giving_count_id", None)
                clean["business_id"] = new_id
                payload.append(clean)
            if not payload:
                continue

            ok = 0
            for i in range(0, len(payload), _EXPORT_PAGE):
                chunk = payload[i:i + _EXPORT_PAGE]
                resp = await client.post(
                    SUPABASE_URL + "/rest/v1/" + table,
                    headers={**_service_headers(), "Prefer": "return=minimal"},
                    json=chunk)
                if resp.status_code >= 400:
                    # Never abort the whole import for one table. A
                    # dropped column or a renamed table should cost that
                    # table, not the other ninety.
                    skipped[table] = str(resp.status_code) + ": " + resp.text[:120]
                    break
                ok += len(chunk)
            if ok:
                restored[table] = ok

    logger.info("import user=%s -> business=%s tables=%d skipped=%d",
                user.id, new_id, len(restored), len(skipped))

    try:
        import audit_log
        audit_log.record(
            new_id, actor_type="user", actor_id=str(user.id),
            verb="import_business", ok=True, source="account",
            summary="imported " + str(sum(restored.values())) + " rows into a new business",
            payload={"tables": len(restored), "skipped": len(skipped)})
    except Exception:
        pass

    return {"ok": True, "business_id": new_id, "name": name,
            "restored": restored, "rows": sum(restored.values()),
            "skipped": skipped, "warnings": warnings}


# ─── Deletion ───────────────────────────────────────────────────────────

async def _delete_storage_objects(client: httpx.AsyncClient, business_id: str) -> int:
    """Delete every uploaded file under the business's prefix in each
    storage bucket (beta-readiness audit: these survived account deletion
    before). Best-effort — never blocks the row deletion."""
    removed = 0
    for bucket in STORAGE_BUCKETS:
        try:
            lr = await client.post(
                f"{SUPABASE_URL}/storage/v1/object/list/{bucket}",
                headers={**_service_headers(), "Content-Type": "application/json"},
                json={"prefix": f"{business_id}/", "limit": 1000},
            )
            if lr.status_code >= 400:
                continue
            names: List[str] = []
            for o in (lr.json() or []):
                if not o.get("name"):
                    continue
                # Folder entries come back with no id (receipts live at
                # "{business_id}/receipts/…") — descend one level so the
                # files inside don't survive the deletion.
                if o.get("id") is None:
                    sub = await client.post(
                        f"{SUPABASE_URL}/storage/v1/object/list/{bucket}",
                        headers={**_service_headers(), "Content-Type": "application/json"},
                        json={"prefix": f"{business_id}/{o['name']}/", "limit": 1000},
                    )
                    if sub.status_code < 400:
                        names.extend(
                            f"{business_id}/{o['name']}/{s['name']}"
                            for s in (sub.json() or [])
                            if s.get("name") and s.get("id") is not None)
                else:
                    names.append(f"{business_id}/{o['name']}")
            if not names:
                continue
            dr = await client.request(
                "DELETE",
                f"{SUPABASE_URL}/storage/v1/object/{bucket}",
                headers={**_service_headers(), "Content-Type": "application/json"},
                json={"prefixes": names},
            )
            if dr.status_code < 400:
                removed += len(names)
        except Exception as e:
            logger.warning(f"storage cleanup {bucket} for {business_id} failed (non-fatal): {e}")
    return removed


async def _release_sms_lines(client: httpx.AsyncClient, business_id: str) -> int:
    """Hand the business's texting number(s) back to the provider before
    the row that remembers them is deleted. The normal path is a grace
    window and a sweep (sms_numbers_router.release_sweep); a deleted
    business has no later, so this releases now. Each line is its own
    try: a provider error must not stop the deletion, but it is logged
    loudly because the alternative is a number billing the platform
    for a business that no longer exists."""
    released = 0
    try:
        r = await client.get(
            f"{SUPABASE_URL}/rest/v1/sms_numbers", headers=_service_headers(),
            params={"business_id": f"eq.{business_id}",
                    "status": "in.(active,suspended,releasing)",
                    "select": "id,phone_number,provider_sid,account_sid"})
        rows = r.json() if r.status_code < 400 else []
    except Exception as e:
        logger.warning(f"[lifecycle] could not list sms lines for {business_id}: {e}")
        return 0
    for row in rows or []:
        sid = row.get("provider_sid")
        try:
            if sid:
                import twilio_sms
                from starlette.concurrency import run_in_threadpool
                # A business's own number (ISV) is released from its sub-account.
                extra = (row["account_sid"],) if row.get("account_sid") else ()
                await run_in_threadpool(twilio_sms.detach_from_service, sid, *extra)
                await run_in_threadpool(twilio_sms.release_number, sid, *extra)
            released += 1
        except Exception as e:
            logger.error(f"[lifecycle] release of {row.get('phone_number')} (sid={sid}) "
                         f"failed during business delete: {e} — release it by hand")
    return released


async def _delete_business(client: httpx.AsyncClient, biz: Dict[str, Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    lines = await _release_sms_lines(client, biz["id"])
    if lines:
        counts["_sms_lines_released"] = lines
    for table in BUSINESS_CHILD_TABLES:
        n = await _delete_table_rows(client, table, biz["id"])
        if n:
            counts[table] = n
    storage_removed = await _delete_storage_objects(client, biz["id"])
    if storage_removed:
        counts["_storage_files"] = storage_removed
    r = await client.delete(
        f"{SUPABASE_URL}/rest/v1/businesses",
        headers=_service_headers(),
        params={"id": f"eq.{biz['id']}"},
    )
    if r.status_code >= 400:
        raise HTTPException(502, f"Business row delete failed: {r.text[:300]}")
    return counts


async def _delete_user_rows(client: httpx.AsyncClient, user_id: str) -> Dict[str, int]:
    """Delete the person-scoped rows (keyed by user_id). Missing tables
    and missing user_id columns skip silently."""
    counts: Dict[str, int] = {}
    for table in USER_CHILD_TABLES:
        try:
            r = await client.delete(
                f"{SUPABASE_URL}/rest/v1/{table}",
                headers={**_service_headers(), "Prefer": "return=representation"},
                params={"user_id": f"eq.{user_id}", "select": "user_id"},
            )
            if r.status_code < 400:
                counts[table] = len(r.json() or [])
        except Exception:
            pass
    return counts


@router.delete("/business/{business_id}")
async def delete_business(business_id: str, request: Request,
                          user: AuthedUser = Depends(require_user)):
    """Permanently delete ONE business the caller owns. No undo."""
    # STEP-UP. "No undo" is the whole reason: an unattended session must
    # not be able to erase a practice, and a stolen JWT alone must not
    # be enough either.
    ledger_unlock.require_unlock(request, str(user.id), ledger_unlock.SCOPE_DANGER)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        businesses = await _owned_businesses(client, user.id)
        target = next((b for b in businesses if b["id"] == business_id), None)
        if not target:
            raise HTTPException(404, "Business not found or not yours")
        logger.warning(f"DELETE business {business_id} ({target.get('name')}) by user={user.id}")
        counts = await _delete_business(client, target)
    return {"ok": True, "deleted_business": business_id, "rows_removed": counts}


@router.delete("")
async def delete_account(request: Request,
                         user: AuthedUser = Depends(require_user)):
    """Permanently delete EVERY owned business, then the auth user.
    The session becomes invalid immediately after. No undo."""
    # STEP-UP. The most destructive call in the system.
    ledger_unlock.require_unlock(request, str(user.id), ledger_unlock.SCOPE_DANGER)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        businesses = await _owned_businesses(client, user.id)
        logger.warning(f"DELETE ACCOUNT user={user.id} email={user.email} businesses={len(businesses)}")
        removed = []
        for biz in businesses:
            await _delete_business(client, biz)
            removed.append(biz["id"])
        # Person-scoped rows (push subscriptions, profile) — keyed by
        # user_id, so they'd survive the per-business sweep otherwise.
        await _delete_user_rows(client, user.id)
        # Finally, the auth user itself (Supabase admin API).
        r = await client.delete(
            f"{SUPABASE_URL}/auth/v1/admin/users/{user.id}",
            headers={
                "apikey": os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
                "Authorization": f"Bearer {os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')}",
            },
        )
        if r.status_code >= 400:
            raise HTTPException(
                502,
                f"Businesses removed but auth-user delete failed ({r.status_code}) — contact support",
            )
    return {"ok": True, "deleted_businesses": removed, "account_deleted": True}
