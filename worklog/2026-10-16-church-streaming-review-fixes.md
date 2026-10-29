---
title: Church stream relay, and Codex's review fixes
date: 2026-10-16
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "lets fix and build now"; then KAI: "Fix every must-fix in all three PRs, each reproduced first by a test, plus quick should-fix items"; 10-29 Kevin: "yes start on the fixes", and on the offline window: "make the best option"'
status: waiting on Kevin
prs: [kmj-intake-server#1460, kmj-intake-server#1461, solutionist-studio#1236]
migrations: [supabase/APPLY-2026-10-16-stream-relay.sql (applied), supabase/APPLY-2026-10-29-stream-relay-transitions.sql (NOT applied; Kevin applies; it carries the heartbeat column, so the never-applied APPLY-2026-10-16-stream-relay-heartbeat.sql was folded in and removed)]
left_undone: ["Kevin: apply supabase/APPLY-2026-10-29-stream-relay-transitions.sql before streaming is switched on (without it every relay start and end answers 503)", "Codex: re-check B2-R and B3-R on #1460 (two of the 10-16 probes need their fault moved to the stream_relay_open_live function; see the PR)", "#1461 R3-R and R6-R (another session, 10-29), built to the /relay/confirm contract below: hourly re-confirm, 24-hour offline window, only a 200 counts as a confirmation", "Kevin: DigitalOcean droplet + reserved IP, Cloudflare R2 private bucket with CORS, two R2 tokens, DNS stream A record (stream_relay/README.md)", "set the seven Railway STREAM_* vars, deploy the droplet, test with Love City", "R9: recording retention and deletion on account deletion (needs Kevin's retention call)", "standby droplet + reserved-IP watcher; uptime alert", "Facebook may need a Go live click per Sunday with a persistent key: test on a weekday", "What's New entry at switch-on (a Thursday)", "#1459 (per-message billing) is ON HOLD: pricing waits for the Instinct Layer"]
decisions: ["our own relay on a DigitalOcean droplet, not Cloudflare Stream or Railway", "the R2 bucket is private; the backend's player hands out signed links: live is public, a recording only once a published sermon carries it or with a manager's 6-hour link", "the stream key is <stream id>?key=<secret>; RTMPS only on 443", "Kevin 10-29 (was 8 days): the relay re-confirms every key it remembers with the backend once an hour (POST /stream-relay/relay/confirm) and keeps one at most 24 hours while the backend is down, so a revoked key stops within an hour while the backend is up and a Sunday-morning outage doesn't stop a service", "Love City streams to both YouTube (@lovecitychurch) and Facebook (lovecitynation)", "10-29: a stream session goes live -> ending -> ended, and every change of state is a Postgres function under one advisory lock per church", "10-29: a run the backend never saw takes over only from a run that has missed 3 minutes of beats; an old run's late request is answered from its own session and never touches the live one", "10-29: a failed time-zone read is a 503, never a UTC date"]
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

2026-10-29 (Kevin: "yes start on the fixes"). Codex's re-check left two
must-fixes on #1460, both reproduced first by failing tests. B2-R: an old
run's late heartbeat or finishing retry closed the live run before learning
its own session was over. B3-R: a start retry racing the sweep opened a live
service for a session the sweep had just finished, which nothing would ever
close. Fix: a session now goes live -> ending -> ended, and every change of
state is one database function under one lock per church
(`APPLY-2026-10-29-stream-relay-transitions.sql`; the router calls them over
RPC). A run's own session is looked at first. A new run takes over only from
one that stopped beating. The live service is opened and linked in one step,
only while the session is live. The SQL was run twice and raced over two real
connections on a throwaway Postgres 18. The PR bot's 10-16 items 1-4 were
already fixed on 10-16; the tests now cover each, and its "worth a look"
(`_church_tz` falling back to UTC on a failed read) is fixed. Main was merged
in (no rebase). One of this PR's own tests pinned a date that went stale
after 10-18 (the alert cooldown); it now uses the real clock.

Later on 10-29, Kevin chose the offline window ("make the best option"):
the relay re-confirms every key it remembers once an hour and keeps one at
most 24 hours while the backend is down (it was 8 days). The backend's half
is `POST /stream-relay/relay/confirm`, behind the relay secret like the other
relay routes. Its body is `{grants: [{stream_id, key_hash}]}`, 200 at most;
more than 200 or a malformed entry is a 422. It answers
`{confirmed: [stream_id]}`. A stream id is listed only when its church's
current key has that hash and verify would admit it now (the same checks,
shared in `_admits`); switched off, nothing is confirmed. The relay cuts any
church left out, so a failed read is a 503 and never a short list. Keys are
read 50 hashes per query, because 200 in one `in.()` URL would pass a
proxy's 8 KB limit. The relay half is #1461.
