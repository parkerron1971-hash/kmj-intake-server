---
title: An import saves everyone even when only some rows have a field
date: 2026-11-06
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-06: "I want to make sure this is properly ready"'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone: []
decisions:
  - "contacts_import_router._same_keys gives every row in a chunk every key, null where it has none (subsplash_import._uniform already did this)"
  - "Both import test fixtures now refuse mixed keys the way PostgREST does, so a fake can't hide this again"
  - "Checked against the real database: a 7-person file into the kept test church saved 7 of 7, made both families, and a second run added nobody"
related: [2026-11-06-church-import-families.md]
---
#1745 put first_response_at on guests only and birthdate on rows that have one. PostgREST refuses a bulk insert whose rows don't share their keys (PGRST102), so any file mixing members and guests lost the whole chunk ("could not be saved"). The test fake accepted mixed rows, so 46 tests passed. The same rule had always applied to role: a file with a job title on only some rows failed the same way, for businesses too.
