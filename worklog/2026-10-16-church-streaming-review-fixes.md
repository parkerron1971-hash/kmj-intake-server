---
title: Church stream relay, and Codex's review fixes
date: 2026-10-16
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "lets fix and build now"; then KAI: "Fix every must-fix in all three PRs, each reproduced first by a test, plus quick should-fix items"'
status: waiting on Codex re-check
prs: [kmj-intake-server#1460, kmj-intake-server#1461, solutionist-studio#1236]
migrations: [supabase/APPLY-2026-10-16-stream-relay.sql (applied), supabase/APPLY-2026-10-16-stream-relay-heartbeat.sql (NOT applied; Kevin applies)]
left_undone: ["Kevin: DigitalOcean droplet + reserved IP, Cloudflare R2 private bucket with CORS, two R2 tokens, DNS stream A record (stream_relay/README.md)", "apply the heartbeat migration", "set the seven Railway STREAM_* vars, deploy the droplet, test with Love City", "R9: recording retention and deletion on account deletion (needs Kevin's retention call)", "standby droplet + reserved-IP watcher; uptime alert", "Facebook may need a Go live click per Sunday with a persistent key: test on a weekday", "What's New entry at switch-on (a Thursday)", "#1459 (per-message billing) is ON HOLD: pricing waits for the Instinct Layer"]
decisions: ["our own relay on a DigitalOcean droplet, not Cloudflare Stream or Railway", "the R2 bucket is private; the backend's player hands out signed links: live is public, a recording only once a published sermon carries it or with a manager's 6-hour link", "the stream key is <stream id>?key=<secret>; RTMPS only on 443", "a key the backend confirmed keeps working 8 days while the backend is down", "Love City streams to both YouTube (@lovecitychurch) and Facebook (lovecitynation)"]
related: [2026-10-16-love-city-watch-youtube.md]
---
A church streams once (RTMPS) to our relay droplet (`stream_relay/`, #1461),
which copies the stream unchanged to YouTube and Facebook and records it to a
private R2 bucket; the backend (`stream_relay_router.py`, #1460) holds the
church's key, opens the live service with our player, and turns each service
into an unpublished sermon draft. The church's screen is "Stream from your
church" under Live (FE #1236), hidden until all seven Railway settings are on.

Codex reviewed all three PRs the same day (KAI's review file
`church-streaming-review.md`). Every must-fix was reproduced by a failing test
before it was fixed: B1–B5 in `__tests__/test_stream_relay.py`, R1–R11 in
`__tests__/test_stream_relay_agent.py`, `test_stream_relay_setup.py` and
`test_stream_relay_mediamtx.py` (the last runs against the real MediaMTX 1.9.3
binary when `MEDIAMTX_BIN` is set; CI skips it), F1–F3 in the frontend's
`tests/stream-setup-check.tsx`.

Before building more here: the relay's contract is in the router's docstring
(`/relay/started` is also the heartbeat; session ids derive from the relay's
run id; a draft's id from its session's). Nothing public may point at the
bucket. W2's Watch page and its one-time YouTube import must stop at the last
service before Love City's first Sunday on the relay, or that service becomes
two sermons.
