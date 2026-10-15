---
title: Dev Desk fleet, private cards and owner alerts (M-3 a1)
date: 2026-10-15
agent: Codex (GPT-6)
asked: "KAI: build M-3 a1, fix review, encode four test values, then squash-merge when green and verify Railway/readiness; Kevin applied SQL"
status: in progress
prs: [kmj-intake-server#1448]
migrations: ["supabase/APPLY-2026-10-15-dev-desk-relay.sql (applied and verified by Kevin, confirmed by KAI)"]
left_undone: ["a2 watches/checkers/netguard and desktop-offline jobs"]
decisions: ["Router additions mount through the existing dev_kai router; entry-point edits are only two startup job registrations", "Only stop for overlapping PRs opened or updated in the last seven days, per KAI", "KAI authorized squash merge after green CI and production deployment/readiness verification; Kevin applied the migration", "CI dedupe retains hash-only tombstones after the 30-day inbox expires"]
related: [2026-10-14-dev-desk-kai-and-handoff.md]
---
Read both repositories' worklogs and the full M-3 design. Rebased the assigned
branch onto origin/main before changes. KAI cleared older #1257 and #642 overlaps;
shared-file changes stay minimal (one migration row and two startup jobs).

Added device-scoped fleet snapshots/deltas and latest screens with transactional
revision/cadence checks, owner watch/read/clear, and device revocation. Private
card uploads check MIME/magic bytes and size, redact text/JSON, retain failed
upload cleanup pointers, and sign owner URLs for 900 seconds. The KAI thread
returns only cards referenced on its returned page. Shared vectors define the
server redactor; existing KAI text/state and bridge screens also use it.

The alert inbox has atomic dedupe, settings, quiet hours, watch suppression,
configurable shared push budgets, rate/morning digests, urgent Resend fallback,
and a device-scoped server-alert feed. The leader-gated purge keeps ended fleet
rows 24 hours, screens one hour, cards/alerts 30 days and KAI messages 90 days.
Watch schema, runs and retention remain with a2; no incomplete watch endpoints
are exposed. DEV_ALERTS=off disables new delivery and digest work.

Tests call routes directly with fake PostgREST/auth/storage/delivery. An isolated
PGlite script applies the migration twice and checks actual RPC behavior, RLS,
revocation and restrictive storage access; CI runs that script using its existing
PGlite dependency. No test connects to production.

Local final validation: 218 tests passed across bridge, KAI, fleet, cards,
alerts, redaction, retention, shared rate limits and dispatched local work. The disposable SQL check
passed; syntax and whitespace checks passed. Full GitHub test check pending.

HTTP tests additionally exercise real multipart parsing/body caps, owner settings
round-trips, device metadata spoofing and revocation during an upload. GitHub
push protection initially flagged synthetic repeated-character Stripe fixtures;
replaced them with explicitly fake short values before the first successful push.
No protection bypass was used. PR #1448 is open for Claude Code review.

Automated-review follow-up: the 90-day KAI-message retention is intentional per
M-3 section 3.6 and the brief, and permanently deletes older conversation history.
It is now explicit in the PR. Card purge failures retain their pointer and no
longer starve later cards or alert/KAI retention; unpair still reports incomplete
cleanup after revoking the token. Screen redaction authenticates first. Valid
UUIDs survive entropy redaction, including KAI card/device references. Replaced
the overlapping assignment regex: the reported auth-repeat case took 1.13 s at
16 KB before, versus 0.032 s at 160 KB after, with new regressions.

The fleet shared limiter also runs off the event loop, matching alert budgets,
so its synchronous PostgREST call cannot stall other live relay requests.


Claude Code review fixes requested by KAI: copied the desktop fixture verbatim
from fleet-relay-and-show-tool commit 288904f (Git blob
a5ed5ba0dc74e0bdeac68b9368eb8a86b14d9a42; SHA-256 checked against the source).
All 65 server vectors compare exactly using expect; three desktop-only known
value vectors are skipped. Marker kinds now match the desktop. Fixed token
prose, auth name boundaries, trivial values, session UUIDs, adjacent flags,
quote termination, incomplete PEM blocks and terminal/comment-prefixed env runs.

Kevin's bridge notes and authenticated kai_say instructions retain their text
through storage. Session/device/dev notes, handoff and ordinary screens, KAI's
own line, fleet state and cards remain redacted. Large text (4 KB+) and bulk
fleet/KAI/card processing run in asyncio.to_thread before truncation/storage.
The 16,000-dash regression takes about 6 ms locally (previously reported 14 s).
Tests also cover nested assignments, threaded failure propagation and the real
KAI insert layer, including no desktop opt-in to the instruction exception.

Review-fix validation: 247 focused tests passed, three desktop-only vectors
skipped, including test_dev_bridge.py and test_dev_kai.py. Whitespace checks
passed. The new GitHub test run is pending push; its final result will be
recorded in PR #1448. No additional migration/startup edits, SQL application,
or merge. The prior full CI run passed 15,958 tests.

KAI confirmed Kevin applied and verified the production migration. Authorized
release once green: fetch/rebase main as needed, rerun tests, squash-merge
without admin override and keep the branch, then verify Railway and readiness.
At KAI's direction, encoded only the four blocked fake prefixes (Stripe
restricted test, GitLab, SendGrid, Twilio); the test loader reconstructs them.
A SHA-256 regression proves the decoded fixture is byte-identical to the desktop
source. No push-protection bypass requested or used. Amend the unpushed review
commit so the literal fixture values do not remain in pushed history.

Release validation: 248 focused tests passed and three desktop-only cases
skipped, including the decoded-fixture checksum. Updated only our migration
ledger row to reflect Kevin's confirmed application. Final CI and deployment
results will be recorded on PR #1448 after release.
