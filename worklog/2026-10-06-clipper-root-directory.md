---
title: The clip service builds from its own folder, so Railway can deploy it from GitHub
date: 2026-10-06
agent: Claude Code (Claude Opus 5.5)
asked: "fix what is needed to get this working.."
status: done
prs: [kmj-intake-server clipper-root-directory]
migrations: []
left_undone: []
decisions: ["Root Directory /clipper_worker instead of a config file: Config as Code is deprecated and this service cannot opt in, so the clipper_worker/railway.toml path was ignored", "Watch Paths /clipper_worker/** so an API-only merge never restarts a running clip job", "railway.toml stays as the written record of the dashboard settings"]
related: [2026-10-06-likeness-meter.md]
---
Kevin asked to connect the clip service to GitHub so deploys stop needing a
hand-run `railway up`. The first try set the config file path and connected
the repo; Railway ignored the path (Config as Code is deprecated, this service
never used it) and started building the API with Nixpacks from the repo root
(start command `python kmj_intake_automation.py`). It was aborted during the
build and the repo disconnected. The Dockerfile now builds from inside
clipper_worker/, so the service can use that folder as its Root Directory and
never see the backend's root files.
