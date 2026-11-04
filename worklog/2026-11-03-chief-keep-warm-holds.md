---
title: Chief's keep-warm survives deploys (held in the database, pinged by the worker)
date: 2026-11-03
agent: Claude Code (Claude Opus 5.5)
asked: "go on all (the approved fix: Chief's keep-warm ping isn't keeping the cache warm)"
status: waiting on Kevin
prs: [kmj-intake-server#1734]
migrations: [supabase/APPLY-2026-11-03-chief-keep-warm.sql (NOT applied)]
left_undone:
  - "Apply supabase/APPLY-2026-11-03-chief-keep-warm.sql. Until then the web pings in its own process as before (with the new midnight rule) and the worker job does nothing."
  - "Measure on 2026-11-10: the share of Chief messages 1-4 h after the business's last one that are still full re-writes (was 4 of 5), pings per day (llm:chief_keep_warm rows), and chief_keep_warm stopped_reason counts."
decisions:
  - "Pings never cross 00:00 UTC: the cached copy is gone after it, so the day's first message writes its own."
  - "The ping is stored as JSON text, not jsonb: jsonb reorders tool-schema keys, which is another prompt to the cache."
  - "Stop-on-write kept. New stops: lapsed (copy last used 56+ minutes ago), midnight. A 429/5xx gets one more try while the copy lasts."
  - "A ping holds its row for 90 s (pinging_at) and moves touched_at only after it has read, so a worker that dies mid-ping never records a use the API didn't see (PR review, round 1)."
related: []
---
Measured cause (30 days to 2026-11-03, production api_usage plus the Railway
deploy list): the pings were asyncio tasks in the web process, and every
merge to main restarts it. 475 deploys in 30 days, a median of 26 minutes
apart, against a first ping due 55 minutes after a message. Only 33 pings
went out. All 4 cold messages that came 1-4 h after the business's last one
had a deploy land 3 to 42 minutes after that last message, and no ping
between. Of the 23 cold messages after a gap of more than 4 h, 15 had a
deploy before the first ping; the chains that did run ended at a later
deploy, at the 4 h window, or at 00:00 UTC. There is one web replica
(PROCESS_ROLE=web) and a separate worker service, so replicas were not the
cause. Deploys rarely change the cached brief: 4 of 4 messages within the
hour across a deploy were warm.

Second finding: the cached copy is gone after 00:00 UTC. All 3 pings that
crossed it in the 30 days found no copy and paid for a whole new one (25c,
40c, 45c: $1.10 of the $1.42 the pings cost), while the other 30 read. The
logs show the same payload reading 112,223 tokens at 23:30 UTC and writing
112,223 at 00:25. Real calls agree: 2 of 3 under 55 minutes apart across
midnight were full re-writes, against 57 of 1,226 otherwise.

What changed: the web writes the ping to `chief_keep_warm` after each main
Chief call (`record`; the ~0.5 MB brief only when it changed, otherwise just
the times). The worker's `chief_keep_warm` job, every 2 minutes on the
scheduler leader, pings each copy at ~50 minutes and ends chains that are
over (window, midnight, lapsed, wrote, refused). Each ping holds its row
for 90 seconds (`pinging_at`, on the `touched_at` it saw) and moves
`touched_at` only once it has read: two workers never ping one copy, a
worker that dies mid-ping leaves the true last use, and a message that
lands meanwhile keeps its own chain. A failed database call is never read
as "no row": it is logged and the next look tries again, early rather than
late. The in-process chain stays as the fallback
until the table exists, now also stopping at 00:00 UTC.

Expected (replayed on the same 30 days): 9 of the 33 cold messages turn warm
(all 4 of the 1-4 h ones), ~215 pings (~$2.40), ~$4.40 of re-writes avoided,
plus the 3 midnight writes ($1.10). What's left is about one full re-write
per business per UTC day of use (the copy is gone at midnight) and after
gaps over 24 h: ~20 messages, ~$10 a month at today's volume. Pinging a copy
after a deploy that changed the brief reads a stale copy (~1c a ping) until
the next message; rare, since deploys seldom change it.
