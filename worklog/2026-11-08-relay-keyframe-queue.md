---
title: Stream relay no longer damages the picture on large keyframes (MediaMTX writeQueueSize)
date: 2026-11-08
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-08, before Sunday service: "Make the fix now ... I want to run it today but need to know how its going to work."'
status: shipped
prs: [kmj-intake-server#1768]
migrations: []
left_undone:
  - "Real YouTube and Facebook legs were not part of the long test (two local readers stood in); the church's sound check covers them"
  - "The test church keeps a turned-off stream row and test recordings in solutionist-media (no retention job exists yet, R9)"
decisions:
  - "4096 packets, sized to the agent's 25 Mbps limit rather than to today's encoder setting"
related: [2026-10-29-church-stream-relay-service.md]
---
The relay had only ever run short tests. MediaMTX's default queue (512 packets,
about 740 KB) overflowed whenever a keyframe reached that size, which an
ordinary 6 Mbps stream does, and all three copies then lost part of the picture.
Measured on the real droplet with the same clip: 28 warnings in 60 s and
"Missing reference picture" in the copy members watch before, 0 after. Also 0
at 14 and 23 Mbps. It is keyframe size, not bitrate alone.

The droplet is not deployed from main: this config was applied by hand on
2026-11-08 (`mediamtx.yml.before-queue-fix` is the old file there). Use
`stream_relay/setup/deploy.sh` for later changes.
