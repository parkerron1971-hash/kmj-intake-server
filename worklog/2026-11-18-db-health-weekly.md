---
title: Weekly database health check in Mission Control (when to move the database up a size)
date: 2026-11-18
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-18, after moving production from Nano to Small on a "Disk IO Budget" warning, said yes to a weekly check that says when to move the database up a size'
status: in review
prs: [kmj-intake-server (this PR), "solutionist-studio (the Database page; merge after this one)"]
migrations: [supabase/APPLY-2026-11-18-db-health.sql (NOT APPLIED)]
left_undone:
  - "Apply supabase/APPLY-2026-11-18-db-health.sql (SQL editor). Until then the job reads nothing and the card says the check isn't set up."
  - "After applying, press Check now on Mission Control → Systems → Database once: it says whether Supabase's metrics feed accepts the service-role key (the docs now name an sb_secret_ key; supabase-grafana says the legacy service-role key works too). If it's refused, set SUPABASE_METRICS_KEY to a secret key."
  - "The Disk IO balance itself isn't in Supabase's metrics feed (checked against supabase-grafana's metrics.md); disk is judged by throughput and operations against the size's baseline. A Disk IO email from Supabase is still its own reason to move up."
  - "Page and Chief speed on Sunday vs weekdays (one of the guide's signs) isn't measured: the check compares the database's own CPU and disk on Sunday with Wednesday's."
  - "The Money room's Supabase bill (platform_money_bills, $35 flat) wasn't changed for the Small compute (~$15 a month more): Kevin edits it there."
  - "Nothing was proved against production: no prod database, metrics endpoint or Railway read."
decisions:
  - "Readings every 15 minutes Sunday 7:45 AM-1 PM Eastern (7:45 is the start line the 8:00 rate is measured from) and Wednesday 10:45 + 11 AM; a counter (CPU seconds, disk bytes) is turned into a rate only between two readings 4-25 minutes apart, so each rate is a 15-minute average."
  - "Once a slot on many replicas: the job is leader-gated (scheduler_lock.gate) AND each slot's row is inserted first (slot unique, ignore-duplicates), so a leader hand-over never reads twice. It runs every 5 minutes and decides in code (a deploy at the wrong minute loses at most 5 minutes; a cron at 8:00 would lose the whole report)."
  - "The size is read from the memory Supabase reports (smallest size with that much memory, 5% slack), then SUPABASE_COMPUTE_SIZE, then Small: when Kevin moves up, the check follows on its own."
  - "Lines: swap >= 256 MB or < 10% memory free = move (64 MB / 20% = watch); CPU >= 70% for two readings (half an hour) = move, once or >= 55% = watch; disk at or over the size's baseline MB/s or IOPS for two readings = move, >= 70% = watch; connections >= 80% = watch; memory promised out (Committed_AS) over the memory there is = watch. Churches past the size's planned top = watch while the readings are fine, move only when there were no readings; within 80% of the top = watch."
  - "Next size and its cost: hourly x 730, whole dollars (Small $15 -> Medium $60 = +$45)."
  - "The owner hears once, when the verdict turns to move (or the move target changes): the week's row is written once (week is the key) and told_at is claimed before the alert. Owner alert inbox, new source 'database' (push), opens studio:platform-database. Monday 8 AM Eastern, outside the default quiet hours."
  - "db_health_pg is SECURITY DEFINER, service role only; top writers are only normalized SELECT/INSERT/UPDATE/DELETE/MERGE/WITH text (utility statements aren't normalized by pg_stat_statements), quoted literals masked, 160 characters."
  - "Active churches: businesses that resolve to the ministry vertical with subscription active, trialing or past_due, or comped; never a sample church; the owner's own church counts (it uses the database)."
related: [2026-11-14-money-room-backend.md, 2026-11-16-new-customer-alert.md]
---
A weekly health check for the production database (Supabase), owner-only in
Mission Control → Systems → Database. It reads Supabase's metrics feed and
the database itself during Sunday morning, keeps the peak, and on Monday at
8 AM Eastern writes a verdict ("Fine at Small", "Watch: ...", or "Time to
move up to Medium (+$45/month)") with the one or two reasons, telling Kevin
once when it turns to "move up". `db_health.py` holds the reader, the pure
summarizer and judge, the job and the two routes (GET summary, POST check).
`DB_HEALTH_CHECK=off` turns it all off. Before building more here, read the
module's docstring: the metric names and the docs they were checked
against are there.
