---
title: Dev Desk fleet, private cards and owner alerts (M-3 a1)
date: 2026-10-15
agent: Codex (GPT-6)
asked: "KAI brief: build M-3 backend a1; push a PR, wait for test, do not merge or apply SQL"
status: waiting on review
prs: [kmj-intake-server#1448]
migrations: ["supabase/APPLY-2026-10-15-dev-desk-relay.sql (pending; Kevin applies manually)"]
left_undone: ["Claude Code review", "Kevin applies the migration before deployment", "a2 watches/checkers/netguard and desktop-offline jobs"]
decisions: ["Router additions mount through the existing dev_kai router; entry-point edits are only two startup job registrations", "Only stop for overlapping PRs opened or updated in the last seven days, per KAI", "No production calls, migration application, or merge", "CI dedupe retains hash-only tombstones after the 30-day inbox expires"]
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
