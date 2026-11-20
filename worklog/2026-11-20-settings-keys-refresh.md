---
title: Settings guard list catches up (extra_storage, payroll, guest_calls)
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'build (the guest Welcome Path); found while landing "Who calls our guests"'
status: in progress
prs: []
migrations: [supabase/APPLY-2026-11-20-settings-server-keys-refresh.sql]
left_undone: ["mark the ledger row APPLIED once the SQL editor run is read back"]
decisions: ["a new file replaces only the list function; the applied 11-17 file is not edited to change production"]
related: [2026-11-20-guest-welcome-path.md, 2026-11-20-who-calls-our-guests.md]
---
The settings guard (APPLY-2026-11-17-settings-server-keys.sql) is in
production, read 2026-11-20 with 42 keys. Three keys joined
business_settings.SERVER_KEYS after it went in: extra_storage, payroll and
guest_calls. Without them on the list, an app login's whole-object settings
write could still put back a stale copy of the church's "Who calls our
guests" choice. The refresh file replaces the list function alone with all
45, and a test pins it to the Python list.
