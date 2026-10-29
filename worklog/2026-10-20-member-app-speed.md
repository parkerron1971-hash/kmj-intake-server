---
title: Faster member app tabs — database calls keep their connections open
date: 2026-10-20
agent: Claude Code (Claude Opus 5.5)
asked: '"can we figure out how to speed the app response up. for some reason when I click through tabs, the responses are slow in changing. figure out why please." … "this is the members app to be clear" (Kevin, 2026-10-20)'
status: shipped
prs: [kmj-intake-server#1542]
migrations: []
left_undone:
  - "Each database read from this server costs ~85 ms of travel (us-west2 to the database in us-east-2; the database side is 1-4 ms). Moving the Railway services to an east region would cut that to an estimated ~25-30 ms; that's Kevin's call"
decisions:
  - "Fix the connections in sb_clients (every sync caller), not only the member app"
  - "Only the transport (the pool) is shared; each call still opens a Client around it, so the tests that patch httpx.Client keep working"
  - "No cap on connections, as before (a busy moment opens more); 32 stay open for 30 s idle"
  - "A GET that meets a connection the database just closed (RemoteProtocolError, ReadError, WriteError) goes once more; a write never does (it may have landed); a timeout is not retried"
  - "Passing transport= stops httpx reading HTTP(S)_PROXY from the environment: Railway sets none (checked 2026-10-20)"
related: [2026-10-20-member-app-lookups-together.md]
---
Measured 2026-10-20 (owner's preview of Love City, live): every tab took 0.9-1.8 s on
the server (Railway's own log), Connect and Home the slowest; the network added ~0.2 s.
The page code made 5-15 database calls a tab, mostly one after another, and
`sb_clients._sync_request` opened a new connection for every one. Now the sync calls share
one kept-open pool (`sb_clients._pool`); `__tests__/test_sb_clients_pool.py` (each test
rehearsed red).

**Correction after it went live (#1542, deploy e2890096):** on Kevin's Windows PC a new
connection cost ~0.4 s, but from inside the Railway container (`railway ssh`) it costs almost
nothing: TCP connect 1-3 ms (Supabase's Cloudflare edge is next door), a read 80-110 ms new or
kept-open alike, of which the database side is 1-4 ms (`x-envoy-upstream-service-time`). The pool
saves ~10 ms a read on the server, not ~0.3 s; live tabs went 0.86-1.76 s → 0.84-1.44 s. The cost is
the number of reads made one after another × the ~85 ms trip to us-east-2. The fix for that is
2026-10-20-member-app-lookups-together.md (fewer reads in a row) and, if Kevin agrees, an east region.
