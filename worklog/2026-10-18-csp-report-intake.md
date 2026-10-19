---
title: CSP violation reports are logged (report-only policy)
date: 2026-10-18
agent: Claude Code (Claude Opus 5.5)
asked: '"you can start working on that list" (the needs sweep after the REA trial)'
status: shipped
prs: [kmj-intake-server#1498, solutionist-studio#1272]
migrations: []
left_undone: ["read `railway logs --filter \"[csp]\"` after a few days of real use, then decide what the enforcing policy allows", "srcdoc site previews inherit the app's policy and use inline/CDN scripts; they need their own answer before anything is enforced"]
decisions: ["reports are log lines only: nothing stored, never in the error ring buffer or the watchdog count", "fields cut to directive, scheme://host and first path segment, because paths can carry classroom/preview tokens"]
related: [solutionist-studio worklog/2026-10-18-needs-sweep.md]
---
`POST /telemetry/csp-report` takes the reports browsers send for the frontend's new `Content-Security-Policy-Report-Only` header. It is anonymous, rate-limited per IP (`csp_report`, fail-open) and always answers 204. Each new kind of violation logs one `[csp]` line in each process, and the same kind logs again at 10, 100 and 1000 sightings. Tests: `__tests__/test_csp_report.py`.
