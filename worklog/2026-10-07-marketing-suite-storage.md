---
title: Marketing suite storage for every business (B3)
date: 2026-10-07
agent: Claude Code (Claude Opus 5.5)
asked: "This will work. let's build this."
status: waiting on Kevin
prs: [kmj-intake-server#1307]
migrations: [supabase/APPLY-2026-10-07-marketing-suite.sql]
left_undone: ["Kevin applies supabase/APPLY-2026-10-07-marketing-suite.sql by hand after merge", "B4 desk API is next and depends on the migration being applied"]
decisions: ["new marketing_* tenant tables; platform_marketing_* untouched until step 5", "one row per post idea with targets jsonb, like social_publications", "owner + member SELECT only, service-role writes, clicks and events service-role only", "content_hash binds id, business, caption, publish_text, landing_url, media (artwork ids in order, or clip + fingerprint + covers), sorted accounts, run_at, expires_at", "a post with no desk row is never claimed; a paused desk hands nothing over", "follow counts clicks for submitted, published and partly_published posts", "run, post, click and event history and the desk settings are exported and deleted with the business but never restored from a file (review: a file could switch the plan on or name another business's accounts)", "deletes of the two tables without an id column ask for a column that exists (_DELETE_SELECT)"]
related: [2026-10-07-marketing-plan-gates.md, 2026-10-02-marketing-desk.md]
---
Storage for the multi-tenant marketing desk from the 2026-10-07 marketing-suite
plan (docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md, decision D1, PR B3). One migration adds marketing_desks, marketing_runs,
marketing_posts, marketing_link_clicks and marketing_post_events with RLS and four
service-role RPCs (claim_run, approve, claim_due, follow), copied from the platform
desk's semantics and keyed by business. business_marketing_store.py is the
fail-closed door (a failed read raises, never reads as empty) plus digest() for the
approval binding and link_code(). account_lifecycle exports and deletes the five
tables. Nothing runs on any of it yet: no route, no job. Tests: the PGlite check
__tests__/business_marketing_db.mjs (wired into CI) and
__tests__/test_business_marketing_store.py.
