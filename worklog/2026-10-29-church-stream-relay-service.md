---
title: Church stream relay server (the droplet), and Codex's re-check fixes R3-R, R6-R, R3-F1, R3-F2 and C1-F
date: 2026-10-29
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-29: "yes start on the fixes" (Codex re-check of 2026-10-16: R3-R and R6-R on #1461); on the offline window: "make the best option"; then "Fix the four findings in church-streaming-review.md (B3-F, R3-F1, R3-F2, C1-F)"'
status: waiting on Kevin
prs: [kmj-intake-server#1461]
migrations: []
left_undone:
  - "#1460 adds POST /stream-relay/relay/confirm (the contract is in decisions); until it does, the hourly re-check gets a 404 and changes nothing (keys then last 24h from their last /auth or heartbeat)"
  - "Codex re-check of #1461 at the new head (R3-F1, R3-F2, C1-F fixed); B3-F is #1460's, fixed in that PR, not here"
  - "Kevin: DigitalOcean droplet + reserved IP, private R2 bucket with CORS, two R2 tokens, DNS stream A record (stream_relay/README.md, One-time setup)"
  - "R9: recording retention and deleting a church's recordings with its account (needs Kevin's retention call)"
  - "R11 rest: a changed destination's old copy and its replacement can overlap for a moment (a stopped copy is now killed within 5 s)"
  - "standby droplet + reserved-IP watcher; uptime alert"
  - "a Linux Docker run of the real stack (the MediaMTX test runs the Windows binary)"
decisions:
  - "Kevin's call (2026-10-29, \"make the best option\"): the agent re-confirms every key it remembers hourly (GRANT_SYNC_S=3600) and a confirmed key works 24 hours while the backend can't be reached (OFFLINE_GRANT_S=86400). A key Kevin revokes stops within an hour while the backend is up; a Sunday outage that begins after Saturday's re-checks doesn't block the service"
  - "the 24 hours bind a running stream too: past them the publisher is disconnected and every copy and the recording stop; a key the re-check leaves out is forgotten and its stream cut the same way"
  - "the re-check contract: POST /stream-relay/relay/confirm, X-Relay-Secret, {grants: [{stream_id, key_hash (sha256 hex of the secret)}]} in chunks of 200; 200 {confirmed: [stream_id]} renews or drops; anything else changes nothing"
  - "the agent remembers one key per church, as its sha256 (never the key); a newly confirmed key replaces the old one"
  - "a confirmation counts from when the backend was asked, and an answer arriving after a key ran out brings nothing back, whether a re-check's or a heartbeat's; only a fresh /auth makes a new grant"
  - "a cut-off publisher is disconnected again every 10 s from the agent's own pass, on its saved connection, until MediaMTX says it is gone (200/404) or the listing no longer has it"
  - "a re-check answer is used only if every member of `confirmed` is a 20-hex stream id; otherwise the whole answer changes nothing"
  - "a church holds its place from the moment /auth lets it in, decided one at a time; a church waiting out its grace keeps its place; a publisher found past MAX_STREAMS is disconnected"
  - "a disk that can't be read counts as full: new streams are refused and recording stops"
related: [2026-10-16-church-streaming-review-fixes.md]
---
The relay server in `stream_relay/` (#1461): MediaMTX takes one RTMPS
stream per church on a DigitalOcean droplet, and `agent/relay_agent.py`
copies it unchanged to YouTube and Facebook, records it to the private R2
bucket, and reports to the backend (#1460, `stream_relay_router.py`). Built
2026-10-16 with Codex's first-review fixes R1 to R11. The 10-16 log in #1460
covers all three PRs.

On 10-29 the two items from Codex's re-check were fixed, each reproduced
first by a failing test in `__tests__/test_stream_relay_agent.py`. R3-R: a
running stream now has a deadline, its key's last confirmation plus
`OFFLINE_GRANT_S`, kept on the agent's own clock, so a stream is cut when the
backend has been silent that long, even while MediaMTX's API is down too.
R6-R: the limits run every pass whatever MediaMTX's API does, admission
reserves a place under a lock before the backend is asked, and the cap also
holds when publishers are found. Codex's own probes (`relay_bypass.py`) pass
unchanged. A recording journal left untouched past the grace is now finished
at restart instead of appended to (a residual of the bot's item 3).

Kevin then chose the window ("make the best option"): a short window AND a
Sunday that survives a Railway outage. The agent re-confirms every key it
remembers with the backend hourly (the one new route, `/relay/confirm`,
which #1460 adds), and a confirmed key works for 24 hours.

Codex's final re-check (same day, at c6814d93) closed R6-R and found three
smaller gaps here, each reproduced by its own probe (`test_final_extra.py`,
6 failing) before the fix. R3-F1: a failed disconnect is now retried from
the agent's own pass, not from publisher discovery. R3-F2: a heartbeat
answered after the key ran out no longer renews the remembered key. C1-F: a
`confirmed` list with anything but stream ids in it is ignored whole.

Before changing the agent's auth or publisher code, run
`__tests__/test_stream_relay_mediamtx.py` with `MEDIAMTX_BIN` set to a
MediaMTX 1.9.3 binary (CI skips it).
