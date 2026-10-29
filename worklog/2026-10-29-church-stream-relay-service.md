---
title: Church stream relay server (the droplet), and Codex's re-check fixes R3-R and R6-R
date: 2026-10-29
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-29: "yes start on the fixes" (Codex re-check of 2026-10-16: R3-R and R6-R on #1461)'
status: waiting on Kevin
prs: [kmj-intake-server#1461]
migrations: []
left_undone:
  - "Kevin: accept (or change) the 3-hour offline window, OFFLINE_GRANT_S; it was 8 days, which Codex flagged as an unapproved multi-day revocation window"
  - "Codex final review of #1461 at the new head; #1460's B2-R and B3-R are fixed in that PR, not here"
  - "Kevin: DigitalOcean droplet + reserved IP, private R2 bucket with CORS, two R2 tokens, DNS stream A record (stream_relay/README.md, One-time setup)"
  - "R9: recording retention and deleting a church's recordings with its account (needs Kevin's retention call)"
  - "R11 rest: a changed destination's old copy and its replacement can overlap for a moment (a stopped copy is now killed within 5 s)"
  - "standby droplet + reserved-IP watcher; uptime alert"
  - "a Linux Docker run of the real stack (the MediaMTX test runs the Windows binary)"
decisions:
  - "a key the backend confirmed keeps working 3 hours while it can't be reached, for a new stream and one already running; past that the publisher is disconnected and every copy and the recording stop"
  - "a confirmation counts from when the backend was asked, so an answer that crossed a cut-off can't re-admit the key"
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
at restart instead of appended to (a residual of the bot's item 3). The
backend contract is unchanged.

Before changing the agent's auth or publisher code, run
`__tests__/test_stream_relay_mediamtx.py` with `MEDIAMTX_BIN` set to a
MediaMTX 1.9.3 binary (CI skips it).
