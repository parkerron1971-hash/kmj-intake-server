---
title: Clip service for Find my best clips (sermon → short vertical clips)
date: 2026-10-05
agent: Claude Code (Claude Opus 5.5)
asked: "use the engine, upload only, Growth level — start the rehearsal; then: let's go with that"
status: in progress
prs: [kmj-intake-server#1272]
migrations: []
left_undone: ["PR 2: Find my best clips in Grow → Video Clips (upload from computer, Growth gate, run table, clips into media_assets, review grid + empty-spot notices, keep/skip, metering)", "PR 2: raise Supabase global upload limit (100 MB today) after giving every bucket an explicit limit", "PR 3: post kept clips through Post for Me + Chief caption/action", "PR 4: Make clips button on Sermons + Show the whole stage here fix", "Wire CLIPPER_URL + CLIPPER_TOKEN into the API service (PR 2, merge window only)"]
decisions: ["Vendor the MIT BridgeClip engine unchanged at b996820; Solutionist code lives beside it", "Clip service holds an OpenRouter key only; Chief stays on Anthropic direct", "Upload only (no YouTube links: datacenter IPs are blocked and the terms forbid it)", "Growth level (Solutionist plan), included: 10 video-hours/month, then 75 actions per extra hour", "Keep recording 7 days, skipped clips 30 days, kept clips while active", "Keep the name Video Clips; add a Find my best clips button"]
related: []
---
Kevin asked whether to bring github.com/bridge-mind/bridgeclip into the system.
Checked both repos' worklogs first: nothing on clips or Video Clips. The
desktop app is not usable; its Python engine is (MIT, server-mode remnants).
Rehearsed it on Kevin's 62.7-minute sermon "Separate Them": 16 clips in 5
minutes on a desktop, $0.367 provider-reported. A prototype empty-spot check
flagged 5 of 16 clips; all were real empty stages. Plan page with real clips:
https://claude.ai/artifact/8G4xXq7aw5r4oSaBykvBBn

This PR adds `clipper_worker/`, deployed as Railway service
`solutionist-clipper` (db4dceda-5fa4-4934-9279-aa70d072e126,
https://solutionist-clipper-production.up.railway.app). It is NOT connected to
GitHub, like the video renderer: deploy with `railway up --ci` from a folder
holding `clipper_worker/` plus a copy of its Dockerfile at the root (a root
`railway.toml` alone was ignored and the build fell to railpack). Variables:
`CLIPPER_TOKEN`, `OPENROUTER_API_KEY` (Kevin's key), `CLIPPER_SOURCE_HOSTS`
(the Supabase host). The API does not call it yet.

Verified on Railway with a 10-minute cut uploaded to `program-media` and
signed: 3 clips in 163 s, $0.085; captions render on Linux. A full sermon
could not be uploaded: the project's global storage upload limit is 100 MB
(`413 EntityTooLarge`), so the existing Video Clips "1 GB" Drive import has the
same latent failure. Review on #1272 asked for this log, a bytes compare in
auth, and tests for the download/probe/time limits; all added (37 tests).
