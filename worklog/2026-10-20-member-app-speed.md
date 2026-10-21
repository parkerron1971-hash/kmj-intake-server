---
title: Faster member app tabs — database calls keep their connections open
date: 2026-10-20
agent: Claude Code (Claude Opus 5.5)
asked: '"can we figure out how to speed the app response up. for some reason when I click through tabs, the responses are slow in changing. figure out why please." … "this is the members app to be clear" (Kevin, 2026-10-20)'
status: in progress
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Member app pages still wait on their lookups one after another (the church, then the church's settings, then the member, then their spaces and roles, then the page): the next PR runs what can run together"
decisions:
  - "Fix the connections in sb_clients (every sync caller), not only the member app: the same handshake cost is in every server-side read and write"
  - "Only the transport (the pool) is shared; each call still opens a Client around it, so the tests that patch httpx.Client keep working"
  - "No cap on connections, as before (a busy moment opens more); 32 stay open for 30 s idle"
  - "A GET that meets a connection the database just closed goes once more; a write never does (it may have landed)"
related: []
---
Measured 2026-10-20 (owner's preview of Love City, live): every tab took 0.9-1.8 s on
the server (Railway's own log), Connect and Home the slowest; the network added ~0.2 s.
The page code made 5-15 database calls a tab, mostly one after another, and
`sb_clients._sync_request` opened a new connection for every one: a TCP + TLS handshake
from this server (us-west2) to the database (us-east-2), ~0.3 s a call before the query.
Now the sync calls share one kept-open pool (`sb_clients._pool`). Live-data check from
Kevin's PC: a read 462 ms → 87-97 ms after the first; 300 reads on 48 threads all right;
the pool recovers after sitting idle. `__tests__/test_sb_clients_pool.py` (each test
rehearsed red).
