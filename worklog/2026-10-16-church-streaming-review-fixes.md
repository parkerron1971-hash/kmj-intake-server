---
title: Church stream relay, and Codex's review fixes
date: 2026-10-16
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "lets fix and build now"; then KAI: "Fix every must-fix in all three PRs, each reproduced first by a test, plus quick should-fix items"; 10-29 Kevin: "yes start on the fixes", and on the offline window: "make the best option"; then "Fix the four findings in church-streaming-review.md (B3-F, R3-F1, R3-F2, C1-F)"; then KAI on Codex''s round 2: "Tell W3 to fix B3-F2 from that file"'
status: waiting on Kevin
prs: [kmj-intake-server#1460, kmj-intake-server#1461, solutionist-studio#1236]
migrations: [supabase/APPLY-2026-10-16-stream-relay.sql (applied), supabase/APPLY-2026-10-29-stream-relay-transitions.sql (NOT applied; Kevin applies; it carries the heartbeat column, so the never-applied APPLY-2026-10-16-stream-relay-heartbeat.sql was folded in and removed)]
left_undone: ["Kevin: apply supabase/APPLY-2026-10-29-stream-relay-transitions.sql before streaming is switched on (without it every relay start and end answers 503)", "Codex: round 3 on B3-F2 only (#1461 and FE #1236 were cleared in round 2; its needs_draft probe's hook needs the new _finish(sid, draft) and close's p_min_s; see the PR)", "Kevin: DigitalOcean droplet + reserved IP, Cloudflare R2 private bucket with CORS, two R2 tokens, DNS stream A record (stream_relay/README.md)", "set the seven Railway STREAM_* vars, deploy the droplet, test with Love City", "R9: recording retention and deletion on account deletion (needs Kevin's retention call)", "standby droplet + reserved-IP watcher; uptime alert", "Facebook may need a Go live click per Sunday with a persistent key: test on a weekday", "What's New entry at switch-on (a Thursday)", "#1459 (per-message billing) is ON HOLD: pricing waits for the Instinct Layer"]
decisions: ["our own relay on a DigitalOcean droplet, not Cloudflare Stream or Railway", "the R2 bucket is private; the backend's player hands out signed links: live is public, a recording only once a published sermon carries it or with a manager's 6-hour link", "the stream key is <stream id>?key=<secret>; RTMPS only on 443", "Kevin 10-29 (was 8 days): the relay re-confirms every key it remembers with the backend once an hour (POST /stream-relay/relay/confirm) and keeps one at most 24 hours while the backend is down, so a revoked key stops within an hour while the backend is up and a Sunday-morning outage doesn't stop a service", "Love City streams to both YouTube (@lovecitychurch) and Facebook (lovecitynation)", "10-29: a stream session goes live -> ending -> ended, and every change of state is a Postgres function under one advisory lock per church", "10-29: a run the backend never saw takes over only from a run that has missed 3 minutes of beats; an old run's late request is answered from its own session and never touches the live one", "10-29: a failed time-zone read is a 503, never a UTC date", "10-29 (B3-F): a session's totals only go up; an end's totals are saved by the locked close before anything can fail, and the draft is made from the saved length, inserted, linked and the session ended in one locked finish step; an ended session gets a draft only from a late end whose totals just took it past 5 minutes, so a draft the team deleted stays deleted", "10-29 (B3-F2): that late end's owed draft is a saved mark (stream_sessions.draft_owed), set in the same update as its totals and cleared only by the finish, so its retry or the sweep makes the draft whatever fails in between"]
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

Codex's final re-check (10-29, at 4ef49aa4) cleared B2-R and B3-R and found
B3-F: an end's totals lived only in its own request, and the draft was
saved outside the lock. So a failed draft followed by the sweep finished on
the heartbeat's shorter count with no draft, and a finalizer that lost a
race could leave a draft nothing pointed at. Both of Codex's probes failed
first here, then passed. The fix, in the same unapplied migration:
`stream_relay_close` now saves the caller's totals first (raised, never
lowered). A new `stream_relay_finish` makes the draft from the saved length
and the church's own setting, inserts it, links it and ends the session, in
one locked step. A new `stream_relay_beat` raises the heartbeat's totals
and never lowers them. A finalizer that finds the session already ended
returns that answer, unless its totals just took the saved length past 5
minutes with no draft: that late end makes the draft. A draft the team
deleted stays deleted. Re-run on a throwaway Postgres 18: the file applied
over its earlier draft, behaviour scripts and six two-connection races.
Main's #1645 was merged in first.

Codex's round 2 (10-29, at 3b41aae7) cleared #1461 and kept FE #1236
clear, and found B3-F2 on #1460. The late end's right to make the draft
came from its own request (the length before its close was under 5
minutes), and its close saved the new length. So if anything failed after
the close (the draft's insert, the finish, the time-zone read, or just the
close's answer), the retry's close saw the length already saved, took
itself for an ordinary repeat and answered 200 with no sermon. The sweep
never looked at ended sessions. Codex's four failure points failed first
here, then passed. The fix: `stream_sessions.draft_owed`, set by close in
the same update that saves the late end's length, and cleared only by the
finish. A retry or the sweep (which now also reads ended sessions still
owed) makes the draft from it. A deleted draft's session was already past
5 minutes, so no later end marks it again; drafts off clears the mark with
no draft. Close now takes the line (`p_min_s`), and finish no longer takes
the caller's "late" flag: the row's mark decides. Run on a throwaway
Postgres 18: upgrade over both earlier drafts plus three re-runs, every
failure point, the deleted draft, drafts off, and three two-connection
races.
