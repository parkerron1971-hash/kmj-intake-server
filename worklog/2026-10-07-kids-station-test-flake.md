---
title: The check-in station test no longer fails when a random hash contains the test PIN
date: 2026-10-07
agent: Claude Code (Claude Opus 5.5)
asked: "fix the flaky kids station test too"
status: done
prs: [kmj-intake-server kids-station-test-flake]
migrations: []
left_undone: []
decisions: ["Check whole stored values (the PIN itself, or human text containing it) instead of a substring of the whole row: ids and the PIN's HMAC are random hex, where 2468 appears about 1 run in 250"]
related: []
---
test_manager_creates_member_cannot_and_no_secrets_listed asserted that "2468"
(the test PIN) never appears anywhere in the stored station row. The row holds
a random uuid and an HMAC of the PIN, so the four digits turned up by chance
now and then and CI failed on unrelated PRs (seen on #1311). The test now asks
the real question, whether the PIN is stored as itself or inside readable
text, and a new test pins down that hashes, uuids and timestamps don't count.
